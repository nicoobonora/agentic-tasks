# Frontend — discussione generica, API v2

`frontend/client.ts` usa `/api/v2`. Tipi generati da `contracts/openapi.json`; nessun sito, fornitore, ordine o alternativa di dominio compare nel contratto. Il servizio restituisce snapshot persistenti di `Run` e li trasmette tramite SSE. `make api` avvia porta 8000; `make mock` avvia un database separato su 8001, e il client attuale richiede una modalità nel payload (`mode: "mock"` per la demo). Il backend accetta anche `mode` omesso: seleziona `model` solo se chiave e modello sono configurati, altrimenti `mock`. OpenAPI e tipi TypeScript sono rigenerati insieme con make contracts.

## Inviare un task

```ts
import { createClient } from './client';
const api = createClient('http://localhost:8000');
const run = await api.createRun({
  task: {
    title: 'Preparare una guida per nuovi volontari',
    description: 'Proporre una guida di accoglienza breve per una biblioteca.',
    context: 'Utilizziamo solo le risorse già disponibili.',
    attachments: [{ name: 'Note', text: 'I volontari sono disponibili sabato mattina.' }],
  },
  mode: 'mock', // "model" usa realmente il modello configurato nel server
  max_rounds: 3,
  idempotency_key: crypto.randomUUID(),
});
const close = api.subscribe(run.id, (snapshot, sequence) => {
  // Sostituire lo stato UI e conservare sequence per la riconnessione.
  console.log(snapshot.state, snapshot.question, snapshot.proposal);
});
```

Risposta `202`: l'elaborazione prosegue nel worker del server, anche se il browser si chiude. Gli allegati accettano `name`, `text` (testo o contenuto estratto) e/o `url`. Un URL da solo è **reference_only**, non viene scaricato né considerato una fonte letta. Non inviare percorsi del computer o dati binari nel campo `text`. Il totale del task è limitato a 100.000 caratteri JSON; massimo 10 allegati. Il contesto è opzionale.

La UI deve mostrare `mode` e `notice`: il mock è deterministico, non una simulazione nascosta di chiamate AI. In modalità reale, task, contesto, allegati e discussione sono inviati al servizio modello. La chiave API resta nel server.

## Stato e messaggi

| Stato | Comportamento UI |
| --- | --- |
| `running` | Mostrare ciclo, round, `next_role`, messaggi e bozza attuale |
| `awaiting_input` | Mostrare la domanda corrente e le sue opzioni dinamiche |
| `proposal_ready` | Mostrare azioni raccomandate, rischi e questioni irrisolte |
| `approved` | Proposta approvata; nessuna azione eseguita |
| `failed` | Mostrare `error`; offrire retry esplicito |

`messages[].actor`: analyst, operations, finance, critic, operator, system. `content.kind`: proposal, review, objection, revision, not_applicable. Mostrare `content.explanation` come spiegazione pubblica. `content.applicability=not_applicable` è una valutazione esplicita del ruolo, non un errore. Ogni claim distingue supported, assumption ed estimate. Le prove sono disponibili in `run.evidence` e via `api.evidence(run.id)`; sono input forniti dall'utente o risposte umane, non certificazioni esterne.

Le obiezioni hanno ID, messaggio di origine, destinatario facoltativo, motivazione, gravità e risoluzione. Non nascondere le obiezioni aperte quando arriva la proposta finale. `run.proposals` conserva le bozze/revisioni e le proposte finali; `run.proposal` è l'ultima proposta disponibile. Durante una ripresa la proposta visibile può appartenere alla versione precedente: il token corrente per i comandi è **run.proposal_version**, non quello della vecchia bozza.

## Domanda umana e ripresa

```ts
const current = await api.run(run.id);
if (current.question) {
  await api.answer(current.id, {
    proposal_version: current.proposal_version,
    question_id: current.question.id,
    option_id: current.question.options[0].id, // usare la scelta effettiva dell'utente
    text: 'Cominciamo da una prima versione di due pagine.',
    actor: 'Nico',
    idempotency_key: crypto.randomUUID(),
  });
}
```

Non fissare le opzioni nell'interfaccia: leggere ID, label ed explanation dalla domanda. Il testo libero è sempre disponibile; inviare almeno un'opzione o testo non vuoto. Il server registra la risposta come prova, invalida i vecchi messaggi/approvazioni e riparte dall'analista in un nuovo ciclo limitato.

Quando `question.reason=round_limit`, il server offre anche di mantenere visibili i disaccordi. `finalize_with_unresolved: true` consente una proposta condizionata senza altro ciclo, solo se esiste già una bozza. Non significa risolvere un'obiezione o certificare un fatto. Confermare esplicitamente le ipotesi al limite round rende le obiezioni non bloccanti per il documento; restano aperte e non verificate. Senza tale conferma, le obiezioni bloccanti impediscono l’approvazione.

## Endpoint

Tutti relativi a `/api/v2`:

| Metodo | Percorso | Funzione |
| --- | --- | --- |
| GET | `/health` | Configurazione modello (senza chiave), limite round |
| POST | `/runs` | Avvia task; 202 |
| GET | `/runs/{id}` | Recupera snapshot persistito |
| GET | `/runs/{id}/evidence` | Fonti testuali immutabili del task |
| GET | `/runs/{id}/events` | SSE con snapshot completi |
| POST | `/runs/{id}/answers` | Risposta umana e ripresa |
| POST | `/runs/{id}/approve` | Registra approvazione della proposta corrente |
| POST | `/runs/{id}/retry` | Ritenta il ruolo fallito, esplicitamente |

Approve richiede `proposal_version`, `actor`, `idempotency_key`. Retry richiede versione e chiave. Non esistono execute, supplier-events o comandi di acquisto.

Gli errori sono `{code,message}`: 404 risorsa assente, 409 stato/versione/chiave/domanda non validi, 422 input non valido, 503 modello non configurato. Una chiave di idempotenza identifica una singola operazione: conservarla sui retry di rete. Il replay restituisce la risposta originale; dopo il replay ricaricare lo stato corrente se necessario. Su `stale_version` o `stale_question`, ricaricare e richiedere una scelta aggiornata. Non riapprovare automaticamente.

SSE: `event: snapshot`, ID globale crescente, `data: {sequence,run_id,type:"snapshot",data:Run}`. EventSource si riconnette con Last-Event-ID; una nuova connessione può usare `?after=42`. I salti di sequenza sono normali. Il client scarta eventi duplicati. `?once=true` restituisce un lotto finito fino a 100 eventi; i commenti heartbeat non sono messaggi. Chiudere la subscription allo smontaggio o usare polling GET in fallback.

## Esempio opzionale colonnine

```ts
import { createChargingClient } from './examples/charging';
const task = await createChargingClient().task();
const chargingRun = await api.createRun({ task, mode: 'mock', idempotency_key: crypto.randomUUID() });
```

Le API dati e i tipi specifici sono separati, sotto `/examples/charging`. Il flusso di discussione e la UI rimangono identici. Le vecchie API v1 di orchestrazione sono state rimosse; i record preesistenti restano nel database senza essere convertiti in task generici.

### Previsioni dell'esempio colonnine

`createChargingClient().forecasts()` legge l'ultimo artefatto (parametro opzionale
limit); `.forecast(id)` ne legge uno specifico. Endpoint GET:
`/examples/charging/api/v1/forecasts?limit=1` e `/forecasts/{id}`.
Il tipo generato è `ForecastBundle`, schema anche in `contracts/forecast.schema.json`.
I calcoli sono avviati offline con `make forecast`, mai durante una GET HTTP.

Mostrare modello/revisione, data di generazione, origine e orizzonte della
previsione, copertura e metodo effettivamente selezionato per sito. `status` e
`reason` governano la visualizzazione: unavailable non è una curva a zero.
`hours` contiene osservazioni derivate e null per ore insufficienti; `points`
contiene p10/p50/p90 orari per ciascuna ipotesi p=1 e p=0.5 (richieste/ora stimate).
`backtest` espone MAE, pinball, copertura dell'intervallo e numerosità per finestra.
Le bande sono quantili puntuali, non garanzie sul massimo dell'intero periodo.

Le quattro celle di capacità sono nel bundle analysis collegato da `analysis_id`.
Filtrare `.analysis()` per quell'ID, non associare risultati di esecuzioni diverse.
Sono scenari condizionati, non raccomandazioni certificate. Mostrare le limitations
anche quando le celle sono disponibili. `GET /examples/charging/task` include un
riepilogo dell'ultima previsione e dell'ultima analisi per la discussione; i task
precedenti conservano il proprio snapshot e non si aggiornano in silenzio.
Non confondere la data di generazione con l'origine del forecast: un esperimento
ricalcolato oggi su un cutoff passato non è una previsione sul periodo attuale.

## Workspace desktop (frontend)

Avvio della UI senza server o credenziali:

```sh
npm ci
npm run dev
# http://127.0.0.1:5173
npm run build
npx playwright install chromium  # solo la prima volta
npm run test:frontend
```

La UI ha tre colonne: catalogo task locale, area di discussione e risultati.
Il mock locale è il default; non effettua richieste HTTP né chiamate AI e si azzera
al refresh. I due ticket charging contengono solo obiettivi: espansione entro marzo 2027 e manutenzione a Bolzano. Le vecchie fixture generiche/errore restano soltanto nei test. I dialoghi sono script dimostrativi, non repliche del motore
backend né risultati verificati. Le fonti e le preferenze umane non sono prove
esterne. È possibile lavorare su più task e selezionarne la discussione.

### Mappa azioni → flussi esistenti

Tutti i percorsi qui sotto sono relativi a `/api/v2`. Non sono introdotti nuovi
endpoint o stati di orchestrazione.

| Azione frontend | Client / endpoint | Transizione e rappresentazione |
| --- | --- | --- |
| Consultare la colonna sinistra | Catalogo `frontend/tasks.ts` | Catalogo locale, nessuna API catalogo prevista |
| Trascinare al centro o premere “Avvia task” | `createRun` / POST `/runs` con task, mode esplicito, max_rounds e chiave idempotente | La card lascia il catalogo solo dopo la risposta; apertura del run al centro |
| Seguire ruoli e dialogo | `subscribe` / GET `/runs/{id}/events` | Snapshot completi; running mostra ciclo, round, ruolo prossimo, messaggi pubblici e bozza |
| Recuperare stato / riconnettersi | `run` / GET `/runs/{id}` | GET periodica ogni 5 secondi in modalità API, SSE con riconnessione nativa e deduplicazione nel client |
| Selezionare un task avviato o un risultato | Stato locale, stessa subscription | Nessuna nuova elaborazione; apertura del dettaglio |
| Leggere contesto e fonti | `run.evidence` nello snapshot | Mostra origine e testo; un riferimento URL non è una fonte letta |
| Scegliere un’opzione o inviare testo libero | `answer` / POST `/runs/{id}/answers` | awaiting_input → running; ID domanda e opzioni dal server, versione corrente del run e identità utente |
| Finalizzare con disaccordi al limite round | Stessa answer, `finalize_with_unresolved: true` | Disponibile solo per round_limit con bozza; proposta conditional, obiezioni ancora visibili |
| Ricevere una proposta | Snapshot `proposal_ready` | Proposta nella discussione centrale, tab “Da approvare”; nessuna approvazione automatica |
| Approvare il documento | `approve` / POST `/runs/{id}/approve` | proposal_ready → approved, colonna destra “Completati”; disabilitato con obiezioni bloccanti aperte |
| Ritentare un turno fallito | `retry` / POST `/runs/{id}/retry` | failed → running; scelta esplicita, mai fallback a mock |
| Gestire versione/domanda superata | 409 + GET `/runs/{id}` | Mostra errore e stato aggiornato, richiede nuova scelta; nessuna riconferma automatica |

I comandi conservano la stessa chiave per ripetizioni dello stesso payload dopo
errori di rete, per tutta la sessione della pagina. Dopo una risposta si rilegge
lo stato corrente (un replay può essere vecchio). Non cambiare il payload per
ritentare una richiesta di esito incerto. Il browser non conserva i run: a ogni caricamento
della pagina il workspace riparte vuoto, tutti i ticket tornano disponibili e ogni
flusso può essere ripetuto. I run restano nel database del server, ma la UI non li
ricarica. Le chiavi delle operazioni incerte non sopravvivono al refresh.

### Collegamento al backend

`frontend/main.ts` sceglie tra `createMockClient()` e l'esistente `createClient()`;
entrambi espongono lo stesso tipo e usano i contratti generati senza modificarli.
Per collegarsi al server mock separato:

```sh
VITE_DATA_SOURCE=api VITE_API_BASE_URL=http://localhost:8001 VITE_RUN_MODE=mock npm run dev
```

Per richieste modello reali, impostare **esplicitamente** `VITE_RUN_MODE=model` e
la base URL del server configurato. L'intestazione distingue trasporto locale/API
e modalità model/mock; ogni run mostra anche `mode`, `model` e `notice` ricevuti.
In modalità model i task e le risposte sono inviati al servizio modello tramite
backend. Non inserire chiavi API nelle variabili VITE: sono pubbliche nel bundle.
In produzione, senza base URL, il client usa la stessa origine della pagina.

### Integrazioni da concordare, non implementate nel backend

- Il catalogo task non ha un contratto API: per task reali servono sorgente,
  identificatori e regole di assegnazione. Le fixture non inventano tale endpoint.
- Non esiste un endpoint di elenco run: la UI recupera solo gli ID conosciuti nel
  browser. Per storico condiviso, altri dispositivi o altri utenti occorre
  definire un contratto di elenco/ricerca e il legame task → run.
- Il backend include già CORS per `http://127.0.0.1:5173` e
  `http://localhost:5173`. Per origini diverse occorre configurare
  `ACS_CORS_ORIGINS`, oppure esporre `/api` sulla stessa origine tramite reverse
  proxy. Nessuna modifica backend o proxy implicito è inclusa.
- L'actor è un nome dichiarato, non un'identità autenticata; autenticazione e
  autorizzazione non sono definite da questi contratti.
- Non sono previsti cancellazione, sospensione, riassegnazione degli agenti,
  modifica del task avviato, esecuzione delle raccomandazioni o trascinamento
  manuale verso “Finiti”. Non vengono simulati come capacità backend.

Test frontend: drag-and-drop fino all'approvazione, risposta libera, retry dopo
fallimento, più run contemporanei con conservazione del testo durante gli
aggiornamenti, replay idempotente e rifiuto di versioni superate. Questi test
usano il simulatore locale. Un ulteriore test del client HTTP con risposte
intercettate verifica la conservazione della chiave dopo un errore di rete,
la gestione di 409 senza retry automatico e la ripartenza pulita dopo refresh.
Non attestano la qualità del modello o la connettività con un backend reale. La finalizzazione round_limit viene predisposta sul
contratto ma non è prodotta dai tre scenari dimostrativi iniziali.

### Workspace a singola schermata

Il workspace occupa `100dvh`, senza scorrimento della pagina. Il critico occupa
il pannello superiore; analista, operations e finance restano visibili in tre
colonne affiancate, anche su schermi stretti. Ogni pannello mostra una sintesi
breve di `content.text` (prima o prime due frasi), le affermazioni con la loro base
(Dato/Stima/Ipotesi) e i chip della fonte citata; il testo completo e
`content.explanation` restano in “Testo completo”. Una barra dei turni
(Analista → Operations → Finance → Critico → Tu) e lo stato del pannello derivano
solo da `state`, `next_role`, ciclo/round e messaggi del round corrente: il ruolo
in `next_role` è evidenziato, gli altri sono attenuati mentre lavora.

Le chiamate agli strumenti (`tool_activity`) sono mostrate nel pannello del ruolo
che le ha richieste: nome leggibile, nome tecnico, parametri sintetici, stato
(in coda/in corso/riuscita/fallita), risultato riassunto e pulsante “dati ↗” verso
l’artefatto. Il dialogo “Strumenti e prove” elenca tutte le chiamate per ciclo.
Le etichette dei tool charging stanno in `frontend/examples/charging.ts`; un tool
sconosciuto mostra il proprio nome. Nel simulatore locale i run charging
producono chiamate, obiezione e risoluzione scriptate, marcate come simulate. Non viene mostrato ragionamento privato né simulata elaborazione parallela:
il backend continua a orchestrare i turni in sequenza. Le frecce consentono di
consultare turni precedenti. Testi lunghi scorrono solo dentro il pannello.

Domanda e selettore restano sotto i ruoli. L'invio richiede un gesto esplicito;
selezionare “Scrivi una risposta…” apre il campo libero. La spiegazione della
domanda, le motivazioni delle opzioni e l'identità sono nel pulsante dettagli.
La barra del piano apre la proposta completa e l'approvazione. Cronologia,
obiezioni, contesto, prove e versioni sono consultabili in un dialogo con focus
confinato, chiusura Escape e scorrimento indipendente. Nessun contenuto viene
eliminato per farlo entrare nella schermata. Modalità mock/model resta visibile.

Su mobile ticket e completati diventano barre compatte sopra e sotto il
workspace. Le tre valutazioni rimangono affiancate. SSE conserva testo libero,
scelta, posizione dei pannelli e dettaglio aperto; non reinvia le operazioni.

## Indagine charging

Il catalogo è separato dal simulatore. POST runs invia capability_profile=charging
senza dataset o allegati nascosti. Il mock locale rimane uno script dichiarato e
non effettua query; API model usa il provider reale. Nessun form di creazione è
stato aggiunto. L'esempio attachment-based precedente rimane solo manuale.

La sezione Indagine mostra tool, parametri, stati persistiti, riuso della cache e
risultati. I pulsanti prova aprono l'artefatto esatto tramite client.artifact;
le citazioni delle azioni e dei claim usano lo stesso riferimento. I forecast
mostrano origine temporale distinta dalla generazione, metodo effettivamente
selezionato, quantili, backtest e limiti. Unavailable mostra motivazioni, mai una
curva a zero. Le versioni della proposta rimangono consultabili. Refresh e SSE
non reinviano il task né avviano calcoli; testo/focus delle risposte restano intatti.

`npm run test:frontend` verifica il simulatore e trasporto intercettato.
`npm run test:integration` avvia Vite/Uvicorn con DB temporaneo, provider controllato
e predictor numerico deterministico: verifica HTTP, SSE, job e riavvio reale.
I due livelli non attestano l'affidabilità generale di un modello live.
