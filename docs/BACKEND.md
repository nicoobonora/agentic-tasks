# Backend — orchestrazione generica v2

Il flusso è: task → analyst → operations → finance → critic → revisione, domanda umana o proposta finale. Nessun ordine, esecuzione esterna, sito o fornitore è codificato nell'orchestratore. Si riusano SQLite, eventi SSE e idempotenza della base precedente. L'esempio ODH resta separato in `backend/acs/examples/charging`; la sua documentazione è in [CHARGING.md](CHARGING.md).

## Configurazione e avvio

All'importazione dell'app API, il server legge automaticamente `.env` e
`.env.local` dalla radice del progetto, anche se avviato da un'altra directory.
Precedenza: variabili già presenti nel processo > `.env.local` > `.env`.
File assenti sono facoltativi; i valori sono letterali, senza interpolazione
`${VAR}`. Riavviare il backend dopo una modifica. Gli script standalone non
caricano automaticamente questi file.

È possibile mettere nello stesso `.env` le impostazioni backend e Vite:

```dotenv
OPENAI_API_KEY=la-propria-chiave
ACS_MODEL=nome-del-modello-con-structured-outputs
VITE_DATA_SOURCE=api
VITE_API_BASE_URL=http://localhost:8000
VITE_RUN_MODE=model
```

Poi avviare `make api` e, in un altro terminale, `npm run dev`.
La chiave non deve avere prefisso `VITE_`, che espone i valori al browser.
Entrambi i file sono ignorati da Git. In alternativa restano validi gli export:

```sh
make setup
export OPENAI_API_KEY='...'  # impostare nel proprio ambiente; mai nel repository
export ACS_MODEL='nome-del-modello-con-structured-outputs'
export ACS_MAX_ROUNDS=3
make api
```

Swagger: `http://localhost:8000/docs`. Il modello è scelto esplicitamente tramite `ACS_MODEL`: nessun modello implicito e nessuna sostituzione in caso di errore. `POST /api/v2/runs` senza `mode` seleziona `model` solo quando chiave e modello sono entrambi configurati; altrimenti avvia automaticamente la demo `mock`. La risposta espone sempre la modalità effettiva in `mode` e `notice`. Una richiesta esplicita `mode=model` senza configurazione risponde 503; un errore del provider reale non passa mai al mock. `mode=mock` forza la demo anche con credenziali presenti. `make mock` usa porta 8001 e `data/mock.sqlite`; per forzare gli stub in un ambiente configurato inviare `mode=mock`.

L'adapter reale chiama `https://api.openai.com/v1/responses` con schema JSON strict (`text.format`), `store=false`, massimo 5.000 token di output e timeout di 60 secondi per chiamata. Implementazione verificata sulla [documentazione ufficiale Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Non richiede l'SDK: riusa httpx già presente. Il modello deve supportare lo schema strict; rifiuti, risposte incomplete e errori HTTP diventano errori persistenti visibili, mai risultati mock.

In questa consegna non era configurata una chiave API. I test dell'adapter reale usano un trasporto HTTP controllato e verificano endpoint, payload, parsing, rifiuti e flusso completo. **Non costituiscono una prova di qualità o una chiamata live al modello.** `scripts/smoke_discussion.py --mode model` permette la verifica live una volta configurate le credenziali del server.

## File e responsabilità

| File | Responsabilità |
| --- | --- |
| `models.py` | Contratto generico task, messaggi, prove, domande, proposte, comandi |
| `providers.py` | Ruoli, prompt, adapter OpenAI reale, mock dichiarato |
| `discussion.py` | Cicli limitati, validazione riferimenti, versioni, domande e persistenza |
| `agent_port.py` | Inserimento controllato di un turno, senza bypass di versione/ruolo/lease |
| `api.py` | HTTP, SSE e worker semplice nel lifespan FastAPI |
| `db.py` | Tabelle esistenti più lease dei turni |
| `examples/charging/` | API dati, schema analitico e catalogo opzionali di dominio |

Non c'è un framework di plugin o un workflow designer. Il tool di esempio `GET /examples/charging/task` costruisce un task ordinario con uno snapshot di dati locali e catalogo esplicitamente simulato. Questo endpoint rimane un fixture manuale precedente. Il workspace charging usa oggi capability_profile=charging e strumenti controllati di lettura/calcolo; nessuna operazione esterna è eseguita.

## Discussione e limiti

Ogni ciclo ha 1–6 round, default `ACS_MAX_ROUNDS=3`, sovrascrivibile nella richiesta. Ogni round contiene quattro turni in ordine; ciascun turno legge task, prove, messaggi precedenti, bozza e obiezioni. Gli agenti della stessa discussione non lavorano in parallelo perché devono poter reagire ai messaggi appena prodotti. Discussioni diverse possono avanzare contemporaneamente.

L'analista propone/rivede la bozza. Operations valuta fattibilità e dipendenze. Finance valuta costi se pertinenti e può dichiararsi non applicabile. Anche gli altri ruoli possono dichiararsi non applicabili con motivazione; un analista applicabile deve comunque produrre una bozza. Il critico verifica i supporti e può chiedere revisione; solo il critico può risolvere obiezioni esistenti, sempre con spiegazione.

Tutti producono `AgentTurn`, con tipo messaggio, applicabilità, spiegazione pubblica, riferimenti alle prove, claim, obiezioni, eventuali risoluzioni, bozza o domanda. Il programma assegna ID, tempi, versione e collegamenti. Non vengono richiesti ragionamenti privati. Il prompt distingue gli input del task dalle istruzioni di ruolo. Gli agenti scrivono sempre in inglese, qualunque sia la lingua di task, prove e risposte umane; anche i testi di sistema (recupero, domande al limite dei round) sono in inglese.

Uno schema invalido o riferimenti inesistenti concedono **un solo tentativo di correzione**. Dopo due fallimenti il sistema conserva il contenuto interpretabile come ipotesi esplicite, rimuove le citazioni inesistenti e i riferimenti numerici invalidi, apre un’obiezione e prosegue con il ruolo successivo fino al critico. Rifiuti, errori di rete e risposte incomplete producono un turno di indisponibilità dichiarata, senza inventare risultati e senza passare al mock. Se manca una bozza utilizzabile, il sistema propone soltanto la verifica degli input e della fattibilità. Per run generici: al massimo `4 * max_rounds * 2` richieste modello per ciclo. Per charging: al massimo `4 * max_rounds * 10`, incluse correzioni e riprese; default tre round = 120 richieste, massimo sei = 240. Una domanda può interrompere prima il ciclo. Dopo una risposta umana inizia un nuovo ciclo con lo stesso limite; non si riaprono cicli senza un intervento umano. Il contesto modello è limitato a 250.000 caratteri, senza troncamento silenzioso.

Se restano obiezioni o richieste di revisione, riparte l'analista nel round successivo. Al limite il run si ferma con una domanda che include i disaccordi effettivi. Solo il critico può interrompere il ciclo con una domanda all'operatore: le domande degli altri ruoli restano nel loro messaggio e il critico decide se inoltrarle. La domanda del critico conserva le opzioni dinamiche. Il server aggiunge ID e versione. La risposta viene registrata come prova e riparte dall'analista, senza perdere la conversazione.

La proposta finale riporta azioni raccomandate, rischi, questioni irrisolte, versione e messaggi di provenienza. Le bozze precedenti restano in `proposals`. Il motore non riscrive in silenzio le raccomandazioni dopo il controllo del critico; aggiunge alle questioni finali i disaccordi ancora aperti. A esaurimento round, l'umano può richiedere una proposta conditional con le incertezze mantenute. La conferma esplicita accetta le ipotesi e rende le obiezioni non bloccanti per l’approvazione del documento. Le obiezioni restano aperte, le prove restano non verificate e la proposta rimane conditional: non viene dichiarato consenso tecnico. L'approvazione riguarda solo il documento, mai l'esecuzione delle azioni.

## Persistenza, concorrenza e riavvio

`documents(kind=discussion_v2)` contiene il run completo. I vecchi record `kind=run`, gli ordini preesistenti e l'archivio ODH rimangono intatti, ma non sono serviti dalle nuove API. `discussion_commands` conserva hash del payload e risposta per chiave idempotente. `events` conserva snapshot a sequenza globale crescente. `discussion_leases` assegna un singolo turno a un worker per 180 secondi.

Un turno segue questa sequenza:

1. Breve transazione `BEGIN IMMEDIATE`: legge stato/versione/ruolo e acquisisce la lease.
2. Chiamata modello e eventuale correzione **fuori dalla transazione**: il database resta utilizzabile da SSE e altre richieste.
3. Nuova transazione: controlla token lease, scadenza, versione, stato e ruolo attesi. Se sono cambiati, scarta la risposta tardiva.
4. Registra messaggio, nuova bozza, obiezioni e snapshot nello stesso commit; rilascia la lease.

Il worker riprende automaticamente i run running quando il server riparte. Dopo un arresto nel mezzo della chiamata, la lease scade entro tre minuti e il turno può essere richiesto nuovamente. Si garantisce l'applicazione una sola volta del risultato, **non** l'addebito una sola volta della chiamata esterna. Il worker serve fino a `ACS_WORKER_CONCURRENCY` turni contemporanei per processo (default 4, limitato a 1–32), sempre su discussioni diverse. Privilegia quelle aggiornate meno recentemente. Le lease proteggono anche dalla concorrenza fra processi. Non è progettato per grandi volumi. All’arresto ordinato smette di avviare turni e attende quelli già avviati: cancellare una coroutine non interromperebbe il relativo thread HTTP. Una configurazione numerica non valida impedisce l’avvio, evitando un server apparentemente sano con worker inattivo. Non eseguire migrazioni distruttive o azzerare il DB per un normale riavvio.

`proposal_version` cambia su nuova bozza, risposta umana, retry e finalizzazione. Una risposta a una domanda vecchia o un'approvazione su una versione superata viene rifiutata. Il frontend deve ricaricare, non aggiornare automaticamente il token e ritentare l'approvazione. Il replay idempotente restituisce la risposta originale, anche se nel frattempo lo stato è avanzato.

## Prove e allegati

Task, contesto e allegati vengono congelati in `run.evidence` con hash SHA256. Sono dichiarazioni dell'utente, non fatti automaticamente verificati. Un allegato con solo URL ha origine `reference_only`: il server non lo scarica, né legge file locali. Per documenti binari inviare testo estratto nel campo `text`; questa modifica non aggiunge un sistema di upload/conversione dei documenti.

Ogni riferimento del modello deve esistere in queste prove. Un claim supported richiede almeno una prova testuale letta; altrimenti deve essere assumption o estimate. Il controllo strutturale evita riferimenti inventati, ma non dimostra che il testo sostenga davvero la frase: questa è parte del compito del critico e dell'ispezione umana. Le risposte umane non diventano prove di fatti esterni solo perché esprimono una preferenza.

## Verifica e contratti

```sh
make contracts
make test
# Server avviato, sviluppo offline:
.venv/bin/python -m scripts.smoke_discussion --mode mock
# Server configurato con chiave e modello, richieste reali a pagamento:
.venv/bin/python -m scripts.smoke_discussion --mode model
```

Il test smoke tratta sia l'esempio colonnine sia una guida per volontari. Le risposte umane dello smoke sono dichiaratamente risposte automatiche di test; il programma non approva né esegue azioni. I test unitari/integrati coprono anche round limit, non-applicabilità, disaccordo, restart, idempotenza, SSE, lease scaduta, risposta tardiva, riferimenti inesistenti, correzione singola, rifiuti e assenza di credenziali. I test ODH precedenti restano separati.

Migrazione intenzionale a `/api/v2`: i vecchi endpoint v1 di run/ordine sono rimossi; le API dati v1 dell'esempio sono sotto `/examples/charging/api/v1`. OpenAPI principale, OpenAPI charging e tipi TypeScript sono generati separatamente. Non modificare a mano i file generati.

## Modulo numerico opzionale

`make forecast-setup` installa le dipendenze separate per Timestral;
`make forecast` esegue localmente preparazione, backtest e pubblicazione di
forecast/analisi. Non richiede OPENAI_API_KEY e non cambia ACS_MODEL. Il processo HTTP legge artefatti persistiti senza importare PyTorch; i job on-demand usano subprocessi numerici separati.
Il modulo è isolato in `examples/charging/forecast.py`; contratti in
`forecast_models.py`. Procedura, soglie, provenienza, limiti e risultati reali
sono descritti in [CHARGING.md](CHARGING.md#previsioni-locali-con-timestral).
I test numerici richiedono le dipendenze opzionali; in loro assenza sono marcati
skip esplicitamente. Il file `docs/timestral-smoke.json` documenta una chiamata
locale reale distinta dai test con predictor controllato.

## Verifica MVP v2

Avvio e stato usano rispettivamente `POST /api/v2/runs` e
`GET /api/v2/runs/{run_id}`. L'identificativo è `id`, lo stato iniziale
è `running` e `proposal_version` parte da zero. La persistenza JSON è
atomica tramite le transazioni SQLite; non esiste un endpoint di reset.
Per una nuova discussione inviare un nuovo task con una nuova chiave idempotente.

Le letture SQLite del worker e di SSE sono eseguite fuori dall'event loop.
Un errore nell'elaborazione di un run viene registrato nei log senza saltare
le altre discussioni del lotto. Le richieste di revisione di tutti i ruoli,
compreso l'analista, impediscono la finalizzazione automatica del round.
I test verificano anche la consultazione di stato ed eventi durante una
chiamata provider sospesa, usando un provider controllato senza rete.

## Demo, arresto e limiti della consegna

Avvio offline senza chiavi: `make api`, poi inviare un task senza `mode` oppure
con `mode=mock`. Per isolare i dati della demo: `make mock` (porta 8001).
`GET /api/v2/health` espone `model_configured`, mai la chiave.
Per abilitare gli LLM impostare `OPENAI_API_KEY` e `ACS_MODEL`, quindi riavviare.
Le altre variabili sono `ACS_DB`, `ACS_MAX_ROUNDS` (1–6),
`ACS_WORKER_CONCURRENCY` (1–32) e `ACS_CORS_ORIGINS` (origini separate da virgole).
La modalità e il modello del run sono congelati alla creazione: configurare una
chiave dopo la creazione non converte le discussioni demo già persistite.
Il replay di una creazione automatica conserva il risultato originale anche se
la configurazione cambia. Omettere `mode` e specificare `mode=model` sono richieste
diverse e non possono condividere la stessa chiave. Per creazioni anteriori a
questa modifica senza `mode`, il vecchio hash equivaleva a `mode=model`: un replay
con il vecchio payload omesso può quindi restituire 409; recuperare il run esistente.

Per arrestare il servizio usare Ctrl-C/SIGTERM e attendere il completamento dei
turni in corso. Un arresto forzato conserva i documenti committati e lascia scadere
le lease; al riavvio i run running riprendono. Non cancellare il DB mentre il server
è attivo. Per ripartire da zero inviare un nuovo task con una nuova chiave oppure
avviare il server con un diverso `ACS_DB`, conservando il precedente archivio.
Questo è un arresto del servizio, **non** un kill-switch applicativo con revoca
immediata delle chiamate già inviate. Reset e kill-switch HTTP non hanno un contratto
nella v2 e non sono stati introdotti.

Fornitori, ordini, annullamenti, distributore, ticketing, ritardi di consegna e
switch fra fornitori non sono implementati: la specifica v2 li esclude e conserva
solo il catalogo simulato come input alla discussione. Occorrono contratti e regole
operative di dominio prima di aggiungerli nell’esempio opzionale; approvare una
proposta non simula né provoca l’esecuzione di quelle operazioni.

## Workspace con capacità e job

`CreateRun.capability_profile="charging"` seleziona il profilo server v1. Ometterlo
mantiene la discussione generica. Profili sconosciuti sono rifiutati. La modalità
mock resta dichiarata: il mock backend non simula indagini come risultati reali.

Gli strumenti hanno schemi di argomenti controllati e risultati available,
unavailable, needs_clarification o error. Le chiamate e gli artefatti immutabili
sono separati dagli snapshot. GET `/api/v2/runs/{id}/tools` accetta offset/limit;
GET `/api/v2/runs/{id}/artifacts/{artifact_id}` è limitato al run proprietario.
Il profilo non autorizza SQL, shell, URL arbitrari, download o ordini.

Ogni ruolo ha un progresso persistente: massimo 8 tool e 5 chiamate provider
(default, massimo 10), configurabili con ACS_TOOL_REQUESTS e ACS_PROVIDER_REQUESTS.

Profilo veloce (default): il server privilegia la rapidità dei turni rispetto alla
profondità. `ACS_REASONING_EFFORT=low` (vuoto = parametro non inviato; il modello
attuale accetta none/low/medium/high), `ACS_MAX_OUTPUT_TOKENS=3000`, solo gli ultimi
`ACS_CONTEXT_MESSAGES=12` messaggi nel prompt (con il numero di quelli omessi) e testo
delle prove troncato a `ACS_EVIDENCE_CHARS=1200` caratteri nel prompt; prove e
artefatti completi restano immutabili sul server. Il prompt chiede testi di massimo
due frasi. La UI richiede 1 round per ciclo (`VITE_MAX_ROUNDS`). SSE invia
aggiornamenti ogni 0,3 s.
Due job forecast unici al massimo per ciclo. Il contesto provider è limitato a
300.000 caratteri, ogni output tool a 24.000; le serie complete stanno negli
artefatti. Ogni invocazione provider ha la lease breve esistente e timeout HTTP;
il limite complessivo del turno è 30 minuti. L'esaurimento produce un turno
di valutazione incompleta con motivo esplicito e passa al ruolo successivo,
mai consenso implicito. Dopo la revisione del critico e il limite dei round,
le incertezze vengono sottoposte alla conferma umana per concludere il piano.

Il protocollo usa function_call e function_call_output correlati per call_id;
lo stato di continuazione è persistito separatamente. Documentazione verificata:
[Function calling](https://developers.openai.com/api/docs/guides/function-calling).
Non si estraggono comandi dalla prosa. Gli errori reali non diventano mock.

Il worker numerico parte nel lifespan; ACS_NUMERICAL_CONCURRENCY è 1..4, default
1 per processo server. Ogni job ha deadline 20 minuti e heartbeat; lease default
60 secondi, ACS_JOB_LEASE_SECONDS limitato a 5..300. Dopo crash si riacquisiscono
job con lease scaduta. Un arresto ordinato termina i subprocessi e registra
numerical_interrupted; un retry richiede una scelta esplicita. Job scaduti,
dipendenze mancanti ed errori di esecuzione sono distinti da unavailable.
I job acquisiscono un backup SQLite coerente, controllano il fingerprint richiesto
e pubblicano forecast/analysis insieme. Cambiamenti prima della cattura producono
errore, non un risultato attribuito allo snapshot precedente. Nessun risultato
tardivo può cambiare ciclo, ruolo o approvazione. Attendere calcoli non crea domande
umane e non genera polling LLM.

I riferimenti numerici specificano prova, path, valore, unità, sito e periodo.
Tolleranza relativa 1e-6 e assoluta 1e-9. Prove inesistenti, risultati unavailable,
unità/periodi errati e valori alterati sono respinti come fatti verificati, anche da agent_port. Nel loop automatico, dopo una correzione fallita, il contenuto viene ripresentato come ipotesi esplicita da revisionare e confermare. Questo
controlla corrispondenze misurabili, non la verità semantica del testo; serve ancora
la valutazione del critico e la rubric del piano.

Rigenerazione: `make contracts`; tipi TypeScript allineati, nessun rinvio.
Test offline: `make test`, `npm run test:frontend`, `npm run test:integration`.
L'ultimo target usa HTTP/SSE veri, DB temporaneo e provider/predictor controllati;
il test browser riavvia il backend durante un job. Non prova qualità LLM.
Validazione live esplicita: `python -m scripts.smoke_investigation`; può chiamare
modelli a pagamento e usa un backup isolato. Report e limiti nel progress log.
