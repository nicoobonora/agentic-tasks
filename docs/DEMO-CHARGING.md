# Due task demo basati sui dati locali

`demo-charging-tasks.json` contiene due elementi con `id` e `request`.
Ogni `request` è un payload validato per `POST /api/v2/runs`, in modalità
`model`, con snapshot allegato. Non sono stati avviati run o effettuate chiamate
AI per preparare questi file. Questi task non sostituiscono ancora i ticket
del workspace, che rimangono fixture generiche.

1. **Valutare se autorizzare un ampliamento delle colonnine.** Confrontare ciò
   che è dimostrabile sui tre siti e sui possibili incrementi 0/+2/+4. Se le
   analisi sono indisponibili, proporre prerequisiti per la decisione, senza
   inventare il dimensionamento. L'intervento umano sceglie priorità e vincoli.
2. **Preparare i dati per una previsione affidabile della domanda.** Spiegare
   le insufficienze di copertura e proporre misurazioni e controlli con criteri
   di accettazione. Il risultato atteso è un piano verificabile, non una
   promessa di accuratezza o una diagnosi di guasto.

Gli allegati provengono da una lettura SQLite in sola lettura del 14 novembre
2026. Includono metadati ODH dei tre siti, sintesi dell'ultimo forecast e
l'analisi identificata dal suo `analysis_id`. Non includono conversazioni
utente, credenziali o il catalogo economico simulato. Mancano quindi preventivi
reali: Finance deve dichiarare il limite, senza inventarli.

Il forecast allegato ha origine `2026-11-14T01:00:00Z`, copertura utile
12,6% / 16,2% / 0% e `model_inference_calls=0`. Tutti i siti sono unavailable.
Questo snapshot resta congelato: non rappresenta automaticamente dati futuri
o un refresh live. Per una nuova demo aggiornata ricostruire gli allegati
dall'archivio e usare una nuova chiave idempotente; per ripetere la medesima
richiesta dopo un errore di rete conservare invece la stessa chiave.

## Collegamento attuale e limite di scope

Il workspace invia le fixture di `frontend/mock.ts`, senza chiamare
`GET /examples/charging/task`. L'orchestratore discute qualsiasi dominio e
invia al modello soltanto task, prove allegate, risposte umane, conversazione,
bozza e obiezioni. Non consulta autonomamente SQLite, ODH, documentazione o
Timestral. L'endpoint di esempio prepara un contesto separato; non basta che
il dataset sia presente sul disco perché gli agenti lo ricevano.

Il modello conversazionale è chiamato tramite OpenAI. Timestral è una
pipeline numerica locale separata e avviata offline: i risultati persistiti
possono diventare allegati della discussione. Non è un agente conversazionale
né uno strumento richiamabile dagli agenti attuali.

Per una demo di prodotto sulle colonnine, collegare i ticket a snapshot di
dominio e imporre requisiti di evidenza nel livello dell'esempio, mantenendo
generica l'orchestrazione. Le citazioni strutturalmente valide non dimostrano
da sole che una conclusione sia sostenuta dai dati.
