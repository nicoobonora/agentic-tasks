# Task discussion — multi-agent backend

Invia un task con titolo, descrizione e contesto/allegati opzionali. Analista, Operations, Finance e Critico discutono, contestano e revisionano una proposta. Se serve una scelta umana il processo si ferma, pone una domanda dinamica e riprende dopo la risposta. Il risultato è una proposta versionata con azioni, rischi e questioni irrisolte. **Le azioni non vengono eseguite.**

## Avvio

Python 3.12+ e Node 22+ per i tipi frontend.

```sh
make setup
make api
# Swagger: http://localhost:8000/docs
```

Per modelli reali, impostare nel server `OPENAI_API_KEY` e `ACS_MODEL` prima dell'avvio. Il modello deve supportare Structured Outputs. Omettendo `mode`, il backend usa automaticamente la demo `mock` se manca chiave o modello; altrimenti usa `model`. La richiesta esplicita `mode=model` senza configurazione restituisce 503. Gli errori delle chiamate reali non vengono sostituiti con risultati mock.

Esempio di sviluppo senza credenziali:

```sh
curl http://localhost:8000/api/v2/runs \
  -H 'Content-Type: application/json' \
  -d '{"task":{"title":"Guida per volontari","description":"Proponi una guida breve per accogliere volontari in biblioteca."},"mode":"mock","max_rounds":3,"idempotency_key":"volontari-1"}'
```

Il run prosegue nel worker del server. Leggere `/api/v2/runs/{id}` o gli eventi `/api/v2/runs/{id}/events`; rispondere a `/answers` quando `state=awaiting_input`. Mock è sempre etichettato come deterministico e non usa modelli.

Il server carica automaticamente `.env` e `.env.local` dalla radice del progetto.
Si possono salvare lì `OPENAI_API_KEY` e `ACS_MODEL`, senza export manuali.
Le variabili del terminale hanno precedenza, poi `.env.local`, poi `.env`.
Riavviare il server dopo le modifiche; non usare il prefisso `VITE_` per la chiave.

## Consegne

- [Guida frontend](docs/FRONTEND.md): client generico, domande, versioni, SSE e migrazione v2.
- [Guida backend](docs/BACKEND.md): modelli reali, limiti, persistenza, errori e test.
- [OpenAPI generico](contracts/openapi.json), [messaggi agenti](contracts/agent-turn.schema.json), [eventi](contracts/events.schema.json).
- [Client TypeScript](frontend/client.ts), [tipi generati](frontend/api-types.ts).
- [Esempio colonnine](docs/CHARGING.md): dati ODH e strumenti originali, separati dall'orchestrazione.

`GET /examples/charging/task` prepara un task di esempio con i dati locali. Swagger dati separato: `/examples/charging/docs`. L'archivio ODH e gli script di download sono conservati; una nuova checkout può usare `make download` e `make prepare`. I vecchi run specifici rimangono nel DB, senza conversioni distruttive.

## Verifica

```sh
make contracts
make test
.venv/bin/python -m scripts.smoke_discussion --mode mock
```

Il test smoke invia sia il task colonnine sia un task non correlato, e simula esplicitamente le risposte dell'operatore. Con server configurato si può usare `--mode model` per chiamate reali. L'implementazione è stata verificata offline e con un trasporto HTTP controllato per l'adapter reale; una prova live richiede la propria chiave API.

## Timestral per l'esempio colonnine

```sh
make forecast-setup
make forecast
```

Inferenza locale reale Timestral-28M, backtest contro baseline settimanale,
quantili e scenari condizionati attuale/+2/+4. Non richiede chiavi OpenAI.
Risultati: `/examples/charging/api/v1/forecasts`, analisi collegate in `/analysis`.
Con il dataset consegnato e le soglie conservative, la copertura non basta per
pubblicare previsioni utilizzabili: vengono salvate le motivazioni, non valori
simulati. [Istruzioni e limiti](docs/CHARGING.md#previsioni-locali-con-timestral).
