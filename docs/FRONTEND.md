# Frontend — discussione generica, API v2

`frontend/client.ts` usa `/api/v2`. Tipi generati da `contracts/openapi.json`; nessun sito, fornitore, ordine o alternativa di dominio compare nel contratto. Il servizio restituisce snapshot persistenti di `Run` e li trasmette tramite SSE. `make api` avvia porta 8000; `make mock` avvia un database separato su 8001, ma la modalità **va sempre scelta nel payload** (`mode: "mock"`). Il default è `model`.

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

Quando `question.reason=round_limit`, il server offre anche di mantenere visibili i disaccordi. `finalize_with_unresolved: true` consente una proposta condizionata senza altro ciclo, solo se esiste già una bozza. Non significa risolvere un'obiezione o certificare un fatto. Una proposta con obiezioni bloccanti aperte non è approvabile.

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
