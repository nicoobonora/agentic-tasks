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

Non c'è un framework di plugin o un workflow designer. Il tool di esempio `GET /examples/charging/task` costruisce un task ordinario con uno snapshot di dati locali e catalogo esplicitamente simulato. Gli agenti ricevono quei dati come allegati; non viene data loro autorità di mutare il database o richiamare endpoint operativi.

## Discussione e limiti

Ogni ciclo ha 1–6 round, default `ACS_MAX_ROUNDS=3`, sovrascrivibile nella richiesta. Ogni round contiene quattro turni in ordine; ciascun turno legge task, prove, messaggi precedenti, bozza e obiezioni. Gli agenti della stessa discussione non lavorano in parallelo perché devono poter reagire ai messaggi appena prodotti. Discussioni diverse possono avanzare contemporaneamente.

L'analista propone/rivede la bozza. Operations valuta fattibilità e dipendenze. Finance valuta costi se pertinenti e può dichiararsi non applicabile. Anche gli altri ruoli possono dichiararsi non applicabili con motivazione; un analista applicabile deve comunque produrre una bozza. Il critico verifica i supporti e può chiedere revisione; solo il critico può risolvere obiezioni esistenti, sempre con spiegazione.

Tutti producono `AgentTurn`, con tipo messaggio, applicabilità, spiegazione pubblica, riferimenti alle prove, claim, obiezioni, eventuali risoluzioni, bozza o domanda. Il programma assegna ID, tempi, versione e collegamenti. Non vengono richiesti ragionamenti privati. Il prompt distingue gli input del task dalle istruzioni di ruolo.

Uno schema invalido o riferimenti inesistenti concedono **un solo tentativo di correzione**. Dopo due fallimenti il run diventa failed; il retry è una scelta esplicita. Rifiuti, errori di rete e risposte incomplete non generano un loop automatico. Limite di costo: al massimo `4 * max_rounds * 2` richieste modello per ciclo, contando le correzioni. Una domanda può interrompere prima il ciclo. Dopo una risposta umana inizia un nuovo ciclo con lo stesso limite; non si riaprono cicli senza un intervento umano. Il contesto modello è limitato a 250.000 caratteri, senza troncamento silenzioso.

Se restano obiezioni o richieste di revisione, riparte l'analista nel round successivo. Al limite il run si ferma con una domanda che include i disaccordi effettivi. Se il modello richiede input prima del limite, si conserva la sua domanda e le opzioni dinamiche. Il server aggiunge ID e versione. La risposta viene registrata come prova e riparte dall'analista, senza perdere la conversazione.

La proposta finale riporta azioni raccomandate, rischi, questioni irrisolte, versione e messaggi di provenienza. Le bozze precedenti restano in `proposals`. Il motore non riscrive in silenzio le raccomandazioni dopo il controllo del critico; aggiunge alle questioni finali i disaccordi ancora aperti. A esaurimento round, l'umano può richiedere una proposta conditional con le incertezze mantenute. Questo **non risolve** obiezioni bloccanti e non le rende approvabili. L'approvazione riguarda solo il documento, mai l'esecuzione delle azioni.

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
forecast/analisi. Non richiede OPENAI_API_KEY e non cambia ACS_MODEL. Il server
legge soltanto artefatti persistiti, senza importare PyTorch o caricare i pesi.
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

OpenAPI è rigenerato con `python -m scripts.export_contracts`. La rigenerazione
TypeScript è stata verificata in un file temporaneo senza modificare il frontend:
la sola differenza è `CreateRun.mode` opzionale e la rimozione del default statico.
Il client attuale resta compatibile inviando `mode` esplicitamente; per esporre la
selezione automatica nei suoi tipi occorre rigenerarli quando sarà autorizzato
l’aggiornamento del frontend.
