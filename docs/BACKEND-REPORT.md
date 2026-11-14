# Report backend — consolidamento v2

Il backend di discussione v2 funziona senza API key. Non è un sistema di esecuzione
ordini ChargeCo: `docs/BACKEND.md` esclude intenzionalmente quel workflow e i relativi
contratti non sono presenti. Le modifiche preesistenti sono state preservate e
nessun file sotto `frontend/` è stato modificato.

## Interventi

- Selezione automatica `mock` se manca chiave o modello e il payload omette `mode`.
  `mode=model` esplicito richiede configurazione; errori reali non diventano mock.
  Modalità effettiva e avviso sono persistiti nella risposta.
- Worker concorrente fra discussioni, limite configurabile, priorità ai run meno
  recentemente aggiornati, esclusione delle lease attive di altri processi.
  L’arresto ordinato attende i turni avviati, senza perdere il controllo dei thread.
- Replay idempotente stabile al cambio della configurazione; distinzione fra
  selezione automatica ed esplicita. Test di creazione simultanea e singolo commit
  del turno. Documentata la compatibilità dei vecchi hash.
- Corretta una race osservata all’inizializzazione WAL di un database vuoto:
  retry limitato agli errori SQLite BUSY/LOCKED e chiusura della connessione in errore.
- Refresh ODH HTTP con timeout per operazione di 5 secondi e un tentativo per pagina;
  download storico invariato. Fallback esplicito allo snapshot locale.
- Verifica gzip e SHA256 prima di servire prove raw; errore esplicito per corruzione.
- OpenAPI rigenerato, documentazione aggiornata e smoke esteso a `--mode auto`.

## Funzionalità esistenti verificate

Macchina a stati running → awaiting_input → running → proposal_ready → approved,
failed/retry, quattro ruoli stub, domande dinamiche, risposte dell’operatore,
obiezioni bloccanti, revisione, limite round, proposte condizionate, versionamento,
riferimenti alle prove, restart, lease scadute e scarto delle risposte tardive.
API di stato, prove, comandi e SSE; adapter OpenAI Responses con structured output,
correzione limitata, gestione di rifiuti e risposte incomplete.

## Verifiche eseguite

- Suite completa: **41 passed, 5 skipped**, senza API key.
- I cinque skip riguardano test numerici opzionali che richiedono NumPy, assente.
- `npm run typecheck`: superato. `git diff --check`: superato.
- Stress SQLite: 20 database nuovi × 8 connessioni simultanee, tutti riusciti.
- Smoke HTTP con Uvicorn, DB temporaneo e chiavi rimosse dall’ambiente:
  task ChargeCo e guida per volontari entrambi a `proposal_ready`, proposta final,
  9 messaggi e una risposta umana **simulata di test** ciascuno. Modalità restituita:
  mock. Server temporaneo arrestato dopo la prova.
- Test ODH e OpenAI con trasporti controllati: nessuna chiamata live esterna in
  questa verifica. Questi test verificano il protocollo, non la qualità degli LLM.
- Rimane un warning di deprecazione Starlette/TestClient sull’uso di httpx.

## Avvio

Con le dipendenze già installate:

```sh
make api
# http://localhost:8000/docs
```

Inviare `POST /api/v2/runs` con `task` e `idempotency_key`, omettendo `mode` per la
selezione automatica oppure indicando `mode=mock` per forzare gli stub.
Per una demo con DB separato: `make mock`, porta 8001.

```sh
.venv/bin/python -m scripts.smoke_discussion --mode auto
```

Per gli LLM impostare `OPENAI_API_KEY` e `ACS_MODEL` nell’ambiente del server e
riavviare; il modello deve supportare Structured Outputs. Nessun segreto è nel codice.
Opzioni: `ACS_DB`, `ACS_MAX_ROUNDS`, `ACS_WORKER_CONCURRENCY`, `ACS_CORS_ORIGINS`.
Su una checkout senza dipendenze usare prima `make setup`.

## Limiti e lavoro non implementato

Ordini, annullamenti, distributore, ticketing, ritardi e cambio fornitore richiedono
specifiche operative assenti dalla v2. Il catalogo è simulato e serve solo da input
alla discussione: nessuna operazione viene dichiarata eseguita. Non sono stati
inventati nuovi stati o endpoint per questi servizi.

Non esistono reset o kill-switch HTTP. Ctrl-C/SIGTERM arresta ordinatamente il
servizio; per una nuova discussione usare una nuova chiave, per un archivio pulito
un diverso ACS_DB a server fermo. Non è una revoca immediata delle chiamate esterne.

Il frontend è invariato e compatibile con richieste che specificano `mode`.
La rigenerazione TypeScript è stata provata in `/tmp`: renderebbe solo `mode`
opzionale e rimuoverebbe il default statico. L’applicazione di questa modifica al
file frontend generato è rinviata all’autorizzazione dell’utente.

La verifica live degli LLM resta da eseguire con credenziali. La pipeline numerica
opzionale e il download ODH live non sono stati rieseguiti in questa consegna.
