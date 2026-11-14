# Esempio colonnine — dati e strumenti opzionali

I dati ODH e gli strumenti analitici sono conservati. L’orchestrazione generica non contiene siti, fornitori o policy di questo esempio. API dati: `/examples/charging/api/v1`; Swagger separato: `/examples/charging/docs`. `GET /examples/charging/task` prepara un task normale con metadati locali e catalogo simulato come allegati testuali, senza eseguire analisi o ordini.

## Avvio e acquisizione

Richiesti Python 3.12+ e, per rigenerare i tipi frontend, Node 22+. `make setup`, `make download`, `make prepare`, `make api`. Il download usa Internet, il resto funziona offline. Nessun token ODH è richiesto per i dati pubblici selezionati.

```sh
# Dataset corrente nel perimetro di Bolzano + contesto, storico dei siti selezionati
.venv/bin/python -m scripts.download_data --network --legacy
# Sottoinsieme temporale riproducibile; intervallo [start,end), in UTC
.venv/bin/python -m scripts.download_data --start 2026-10-01T00:00:00Z --end 2026-11-01T00:00:00Z
# Vero refresh live, niente riuso della cache per gli stati latest
.venv/bin/python -m scripts.download_data --network --latest
# Ricostruzione offline e esportazioni JSONL
.venv/bin/python -m scripts.prepare_data
.venv/bin/python -m scripts.dataset_report
```

Senza `--network`, il download seleziona i tre siti congelati e il contesto BZ_C_RISPARMIO_02, BZ_BOEHLER_01, CORNEDO. `--network` aggiunge il bounding box configurato, sempre filtrando `sorigin=Neogy-AMPECO`. Il vecchio feed `Neogy` è scaricato per i siti selezionati e di contesto, non per l'intera rete. ALPERIA è escluso. Non filtrare con `sactive=true`: eliminerebbe gli impianti storici dismessi.

La documentazione ufficiale dell'[API Time Series](https://docs.opendatahub.com/use-data/time-series-api/reference/) descrive gli intervalli semiaperti e la paginazione. La [sintassi dei filtri](https://docs.opendatahub.com/use-data/time-series-api/filtering/) richiede stringhe fra doppi apici. Gli URL esatti effettivamente richiesti sono nel manifest.

**Differenza verificata rispetto al PDF:** il 14 novembre 2026 la policy anonima risponde `429` con `You have exceeded the date range limit of 5 days` alle finestre di 90 giorni. Il default operativo è quindi 5 giorni, configurabile in `config/sources.json`; non fare affidamento sul limite di 100 citato nel piano. Non confondere questo 429 strutturale con un semplice rate limit temporaneo.

I conteggi del piano sono fotografie di una selezione precedente. Il perimetro è esplicito e versionato; non si forza il numero di prese a 162. L'inventario effettivo è `docs/dataset-report.json`.

## Struttura e proprietà dei dati

Database: `data/acs.sqlite`, configurabile con `ACS_DB`. Schema creato da `backend/acs/db.py`; SQLite WAL e transazioni serializzano le mutazioni dei dati. Raw in `data/raw`, esportazioni in `data/exports`. Database e raw non sono versionati in Git, il codice e i contratti sì.

| Tabella | Identità / contenuto | Regola |
| --- | --- | --- |
| `source_pages` | ID della risposta, URL, acquisizione, SHA256, percorso gzip, numero righe, tipo | Prova immutabile, anche una pagina vuota è una prova |
| `sites` | `pcode`, `pname`, origine, coordinate e metadati | ID di fonte, non nome come chiave primaria |
| `plugs` | `scode`, sito, `sname`, array connectors | Non presumere un solo standard per EVSE |
| `observations` | ID hash di presa, valid time, transaction time, valore; link alla prova | Deduplicazione idempotente; stati sconosciuti conservati |
| `observation_pages` | associazione osservazione/risposta | Conserva tutte le risposte da cui lo stesso record è stato acquisito |
| `transitions` | cambi di stato, gap e prima osservazione | `previous_status=null` quando non si può stabilire continuità |
| `heartbeats` | tutte le osservazioni effettive, flag repeated | Include i segnali periodici senza perderli con la compressione |
| `episodes` | tratti CHARGING, durata, censura, anomalie | Occupazione, mai sessioni ufficiali o energia |
| `documents` | JSON validati o documenti interni per kind/id | run, comandi, analisi, qualità, pipeline |
| `events` | sequenza globale, run, snapshot | Registro persistente da riprodurre via SSE |

I file raw sono risposte esatte dell'API, compresse. Per la serie storica la richiesta seleziona solo campi di osservazione; i metadati completi sono acquisiti separatamente. `mvalidtime` è il tempo del dato, `mtransactiontime` quello della transazione della fonte, `acquired_at` quello del nostro download. `mperiod=1` è presente nel raw: non significa che lo stato sia campionato ogni secondo.

Una pagina completata viene committata prima della successiva. Un riavvio riprende dalla cache delle query identiche, verificandone il checksum, senza duplicare le osservazioni. Gli stati `/latest` non usano la cache. Il metadata snapshot viene invece riutilizzato: per un aggiornamento dell'anagrafica rimuovere il solo manifest di query interessato da `data/raw`, conservando i gzip che sono prove. Non cancellare il database per un normale aggiornamento.

Gli snapshot anagrafici non certificano la configurazione storica dell'impianto: i collegamenti per nome fra Neogy e Neogy-AMPECO sono candidati, non merge validati. Per RENON mantenere separati i pcode del vecchio feed. Prima di utilizzare lo storico lungo in previsione, il modulo analitico deve validare capacità per periodo, mapping stati e identità fisica come da §4.9.

## Normalizzazione conservativa

`normalize.rebuild` ricostruisce le tabelle derivate dall'intero archivio, non dalla sola ultima finestra scaricata. Ordinamento per presa, valid time, transaction time, ID. Se arrivano revisioni allo stesso valid time, si usa l'ultima transazione, mantenendo tutte le revisioni nei raw e in observations.

La continuità è ammessa solo fra osservazioni distanti al massimo `heartbeat_max_gap_minutes` (default 120, **assunzione tecnica**, non proprietà certificata del feed). Oltre questa soglia si interrompe l'episodio all'ultima osservazione valida e il tratto seguente riparte censurato. Nessun riempimento del buco giugno-luglio. Nessuna estensione dell'ultimo stato fino a oggi. La prima osservazione CHARGING non conta come inizio osservato.

Durante la verifica sono stati osservati anche heartbeat a distanza di 4–8 ore: il default di 2 ore è deliberatamente prudente e può frammentare lo storico. Le durate censurate e `covered_seconds` **non bastano** a confermare i numeri del piano, una continuità di 14 giorni, o una capacità operativa oraria. Chi implementa l'analisi deve validare la cadenza per fonte/presa, esplicitare la soglia usata e trattare le ore prive di segnali come mancanti secondo §4.9. Non aumentare la soglia solo per riprodurre una conclusione attesa.

La qualità base segnala indisponibilità lunga/intermittente e occupazioni >=48h sui tratti osservabili. DC: `dc_pairing_review_required`; il riconoscimento del gemello e la capacità effettiva sul singolo impianto restano al modulo analitico. Non trasformare queste segnalazioni in “guasti accertati”. I tratti sotto 120 secondi restano presenti e marcati. Un gruppo con capacità zero è fuori servizio, non saturo.

## Punto di ingresso del modulo analitico

Formato autorevole: `contracts/analysis.schema.json`, modelli `AnalysisBundle`, `ControlTable`, `Cell` in `backend/acs/examples/charging/models.py`. L'analista produce **lo stesso formato** per riserva e previsione; l'API legge i bundle importati senza fare previsioni a richiesta.

```sh
.venv/bin/python -m scripts.import_analysis percorso/risultato.json
```

Il bundle contiene tre tabelle, una per sito congelato, quattro celle per tabella: p=1/0.5 × p50/high. Unità: richieste/ora, ore/episodio, capacità in prese operative, probabilità [0,1]. Ogni cella disponibile contiene accesso attuale/+2/+4, capacità totale minima e incremento minimo tra 0/2/4 (null se nessuno basta). Per RENON indicare la probabilità alla capacità ripristinata. Le celle non calcolabili richiedono `status=unavailable`, `reason`, metriche null.

Le `evidence_ids` devono essere ID di `source_pages` esistenti. `input_sha256` è SHA256 del JSON canonico della lista ordinata e deduplicata `{id,sha256}` delle prove citate: usare `analysis_contract.input_fingerprint(db, ids)`. L'importatore controlla schema, prove, impronta, probabilità Erlang, capacità minima e incremento. Uno stesso ID di analisi è immutabile. Il controllo numerico non certifica la bontà dello stimatore o della previsione.

Il modulo da sviluppare deve includere nel bundle: soglie di bonifica, parametri E/F/A e dei due p, soglia 10 minuti, minimo quattro giorni comparabili, quota imputata, versione modello, covariate e backtest di tutti i candidati. Restano sue responsabilità:

- capacità operativa per gruppo e ora, separazione DC gemello, esposizione E e tempo pieno F;
- decensura `A*E/(E-F)`, correzione `A+p*(stima-A)`, profili supportati e giornate mancanti/imputate;
- riserva sul periodo osservato, senza confonderne il percentile storico con una previsione;
- Timestral/ingenue, backtest, selezione metodo e calendario ufficiale di festività/vacanze per le covariate;
- raccomandazione minima robusta in tutte le celle, verifica economica a livello di rete, ripristino prima dell'ampliamento.

La base non fabbrica celle numeriche per riempire questi spazi. `/examples/charging/api/v1/analysis` rimane vuoto prima dell'importazione. Le note in `contracts/examples/analysis.unavailable.json` mostrano soltanto il formato, con prove segnaposto che l'importatore rifiuta finché non vengono sostituite.


## Condivisione offline

`python -m scripts.export_snapshot` produce un archivio SQLite e raw. Estrarlo solo a server fermo, in una checkout senza dati da preservare. Il vecchio adapter di ordini e fornitori è stato rimosso: il catalogo resta una fonte di assunzioni per discutere la proposta. Non esiste un endpoint di esecuzione.
