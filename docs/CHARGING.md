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

Per un’analisi conforme integralmente al piano, il modulo analitico deve includere nel bundle: soglie di bonifica, parametri E/F/A e dei due p, soglia 10 minuti, minimo quattro giorni comparabili, quota imputata, versione modello, covariate e backtest di tutti i candidati. Le responsabilità del modulo analitico sono:

- capacità operativa per gruppo e ora, separazione DC gemello, esposizione E e tempo pieno F;
- decensura `A*E/(E-F)`, correzione `A+p*(stima-A)`, profili supportati e giornate mancanti/imputate;
- riserva sul periodo osservato, senza confonderne il percentile storico con una previsione;
- Timestral/ingenue, backtest, selezione metodo e calendario ufficiale di festività/vacanze per le covariate;
- raccomandazione minima robusta in tutte le celle, verifica economica a livello di rete, ripristino prima dell'ampliamento.

La base non fabbrica celle numeriche per riempire questi spazi. `/examples/charging/api/v1/analysis` rimane vuoto prima dell’importazione o dell’esecuzione della pipeline Timestral descritta sotto. Le note in `contracts/examples/analysis.unavailable.json` mostrano soltanto il formato, con prove segnaposto che l'importatore rifiuta finché non vengono sostituite.


## Condivisione offline

`python -m scripts.export_snapshot` produce un archivio SQLite e raw. Estrarlo solo a server fermo, in una checkout senza dati da preservare. Il vecchio adapter di ordini e fornitori è stato rimosso: il catalogo resta una fonte di assunzioni per discutere la proposta. Non esiste un endpoint di esecuzione.

## Previsioni locali con Timestral

Il modulo `backend/acs/examples/charging/forecast.py` implementa inferenza reale con
[Timestral ufficiale](https://github.com/mistralai/timestral), confronto con una
baseline settimanale e scenari condizionati di capacità. Non usa `ACS_MODEL`,
OpenAI o una modalità mock. Le dipendenze numeriche sono opzionali per il server.

```sh
make forecast-setup   # installa anche PyTorch; prima esecuzione scarica pesi ~111 MB
make forecast         # storico 56 giorni, origine ora UTC corrente, orizzonte 168 ore
# Riproduzione sul dataset consegnato:
.venv/bin/python -m scripts.forecast_charging --end 2026-11-14T00:00:00Z
# Dopo il primo download dei pesi, anche senza rete:
.venv/bin/python -m scripts.forecast_charging --end 2026-11-14T00:00:00Z --offline
```

Modello: `mistralai/Timestral-28M`, revisione
`49b26409ac87b5935539a5d8ffe7f397b720db47`; libreria fissata al commit
`a534bdbd244d64f3d9d743f46c7bf6fc330ed4ff`. CPU, quattro thread, nessun fine-tuning.
La cache dei pesi è quella di Hugging Face. Il codice upstream è Apache 2.0,
i pesi hanno la licenza Modified MIT indicata nel repository ufficiale.

Il comando legge SQLite, calcola fuori dalle transazioni e salva atomicamente
un documento `forecast` e il relativo `analysis`. Ogni esecuzione ha nuovi ID;
i risultati precedenti rimangono consultabili. Esporta anche
`data/exports/forecast-latest.json`, sovrascritto a ogni esecuzione. Non aggiorna
ODH automaticamente: usare prima gli script di download se serve uno storico
più recente. `--latest` da solo non recupera le osservazioni intermedie mancanti.
Errori di installazione, download o inferenza interrompono il comando senza
pubblicare risultati parziali e senza sostituire il modello con dati simulati.

### Cosa viene stimato

Si selezionano soltanto le prese del feed corrente con connettori AC <=22 kW.
La serie è oraria UTC; il calendario di input usa ora e giorno della settimana
in Europe/Rome, anche ai cambi dell'ora legale. Non si uniscono fonti storiche e
attuali e non si presume l'indipendenza dei connettori DC.

La ricostruzione usa intervalli esatti fra osservazioni consecutive, soltanto
quando distano al massimo 120 minuti. Per contribuire a un'ora devono essere noti
gli stati di tutte le prese selezionate. Sono registrati:

- `E`: ore osservabili con capacità operativa maggiore di zero;
- `F`: parte di E durante cui tutte le prese operative sono occupate;
- `A`: transizioni osservate AVAILABLE → CHARGING in condizioni osservabili;
- occupazione media e capacità operativa media sul tempo E.

I due target sono `A/E + p*(A/(E-F)-A/E)`, per p=1 e p=0.5, in richieste/ora.
Sono **stime sotto ipotesi**, non conteggi reali delle persone respinte.
Si richiedono almeno 10 minuti sia di E sia di E-F. Altrimenti il target è null,
passato al modello come NaN; nessun riempimento con zero. Capacità zero e ore
interamente sature non producono una domanda nulla. Le ore osservate senza
arrivi possono invece avere valore zero. Nessuna estensione oltre l'ultimo
segnale, nessuna imputazione preventiva.

### Backtest e soglie

Default: due finestre temporali consecutive di sette giorni; almeno 14 giorni
prima della prima finestra. Per ciascuna finestra la serie di training viene
ricostruita da capo, escludendo osservazioni e revisioni successive al cutoff.
Non si utilizza il primo segnale futuro per estendere l'ultimo stato del training.
L'anagrafica disponibile resta uno snapshot corrente: la sua stabilità è
un'ipotesi dichiarata, non una verifica della configurazione storica.

Timestral è confrontato con la stessa ora UTC della settimana precedente,
con intervalli della baseline stimati dai soli residui di training. I punteggi
MAE, pinball loss e copertura p10–p90 usano esattamente gli stessi target osservati
per i due metodi. Si conservano cutoff e numerosità di ogni confronto. Vince la
pinball loss media ponderata per numero di campioni; il metodo deve anche poter
produrre tutti i valori futuri. Una baseline vincente è dichiarata
`selected_method=seasonal_naive`, mai spacciata per Timestral.

Le soglie tecniche della demo sono configurabili e registrate nell'artefatto:
`--gap-minutes`, `--minimum-exposure-minutes`, `--minimum-valid-fraction` (default
25%), `--history-days`, `--horizon-hours` (1..168), `--folds` (1..4).
Servono inoltre almeno quattro date osservate per ogni combinazione giorno della
settimana/ora locale futura, sia nel training di ciascun backtest sia nel contesto
finale; ore utilizzabili nell'ultimo giorno e almeno il 25% dei target
della finestra (minimo 24) comuni al backtest. Queste soglie non certificano la
qualità statistica. Non vengono allentate automaticamente. Il modello può
comunque emettere numeri su serie insufficienti: ciò non li rende pubblicabili.

`parameters.model_inference_calls` distingue una pipeline fermata dai controlli
preliminari da una che ha effettivamente eseguito il modello. `status=unavailable`
e `reason` indicano perché non sono pubblicati punti di previsione.

### Scenari di capacità e limiti rispetto al piano

Per ogni sito disponibile, le quattro celle p × quantile usano il massimo dei
valori orari p50 o p90 nell'orizzonte. La nuova definizione
`high_quantile_definition=pointwise_p90_peak` evita di chiamarlo percentile del
massimo giornaliero: **non è una banda simultanea**.

La durata è la media degli episodi completi fra 120 secondi e 48 ore; ne servono
almeno 20. Per la capacità corrente servono almeno 24 ore recenti con copertura
>=90% e capacità intera stabile nel >=90% di queste ore. La capacità futura è
assunta costante. Se uno di questi requisiti manca, le celle rimangono unavailable.
Il valore zero di `operational_capacity` nelle tabelle unavailable è un segnaposto
richiesto dal contratto v1, non una diagnosi di impianto fermo: consultare anche
`scenario_capacity=null` nel forecast e la motivazione delle celle.

Erlang-B calcola accesso immediato attuale/+2/+4, capacità minima per soglia 90%
e scenario di ripristino per Renon. Si assumono arrivi Poisson stazionari,
indipendenza e assenza di coda. I risultati sono scenari esplorativi: non
certificano quelle ipotesi, non correggono il bias delle durate censurate e non
sono una raccomandazione economica. Il massimo incremento considerato è quattro;
null significa che nessuno degli incrementi 0/2/4 basta. La ricerca della capacità
totale è limitata a 1000, oltre i quali la cella è unavailable.

Restano da validare per applicare integralmente il piano: identità e capacità
storica, calendario ufficiale di festività/vacanze, trattamento più robusto delle durate censurate, candidato
seasonal-naive-trend, backtest della domanda non osservabile e valutazione
economica di rete. L'integrazione Timestral non certifica queste parti.

### Risultato verificato sui dati locali

Con origine 14 novembre 2026 ore 00 UTC e parametri predefiniti, le ore con target
utilizzabile sono 12,6% per BZ_C_RISPARMIO_01, 16,2% per BZ_PIAVE_01 e 0% per
RENON_01: i tre siti risultano unavailable. Il database contiene quindi un
risultato persistito che spiega l'insufficienza, non previsioni inventate.
L'adapter ha anche eseguito realmente Timestral sui dati numerici del primo sito
per verificare download, caricamento e output: `docs/timestral-smoke.json`.
Quella prova tecnica non supera le soglie e non viene pubblicata come previsione
utilizzabile. I test con dati controllati verificano invece il flusso completo,
la selezione, gli scenari, la persistenza e le API.

Per ripetere la sola verifica di inferenza sui dati esportati:

```sh
.venv/bin/python -m scripts.smoke_timestral --offline
```

Il report di consegna include anche una prova del backtest completo con il modello
reale su una serie sintetica regolare, esplicitamente etichettata come test.
Nessuno di quei dati sintetici è importato nel database di produzione.

### Timeout del refresh HTTP e integrità delle prove

`GET /examples/charging/api/v1/live?refresh=true` usa un solo tentativo per pagina
con timeout HTTP di 5 secondi per operazione di rete; il downloader storico mantiene
90 secondi e fino a quattro tentativi. Non è un limite globale di durata del refresh:
la paginazione può richiedere più richieste. In caso di errore la risposta dichiara
`mode=snapshot`, riporta un warning e conserva i riferimenti alle prove locali.
Se alcune pagine sono state acquisite prima del guasto, restano nell’archivio:
lo snapshot locale può contenere acquisizioni di tempi diversi e non è dichiarato
un refresh live completo. In assenza di dati restituisce una lista vuota e stale,
mai osservazioni simulate. La lettura delle prove raw verifica gzip e SHA256;
una prova danneggiata restituisce `409 corrupt_evidence` anziché contenuto alterato.

## Readiness riproducibile e tool di lettura

`python -m scripts.charging_readiness --cutoff 2026-11-14T00:00:00Z
--output docs/charging-readiness.json` apre SQLite in sola lettura e conserva
separate le fonti. Il report confronta gap 60/120/240/480 minuti; non cambia il
default 120 minuti. Distingue punti senza osservazioni, gap di acquisizione,
esposizione insufficiente e saturazione che impedisce la stima. Il cutoff esclude
revisioni successive. Le identità e la capacità storica restano non verificate.
Il report conferma 12,6%, 16,2% e 0% nei tre gruppi correnti selezionati: non è
una validazione di previsioni utilizzabili.

Refresh operativo: scegliere esplicitamente intervallo UTC [start,end), usare
`download_data --start ... --end ...` con finestre di cinque giorni e retry
limitati già implementati. Le query storiche identiche riusano cache verificata;
`--latest` aggiorna solo lo stato recente. Conservare manifest, gzip e checksum.
Ricalcolare la readiness dopo l'acquisizione. Gli agenti non avviano download.

## Workspace con strumenti e input operativi

Profilo `charging`, versione 1: discover_sites, get_inventory, get_data_quality,
get_evidence, get_usage_summary, compare_maintenance_windows, request_forecast,
get_operational_inputs e assess_expansion. I nomi completi hanno prefisso
`charging.`. Nessuna query libera o download comandato dal modello.

Le aree Bolzano/Bozen usano il bounding box contestuale documentato, non un confine
comunale certificato. Altri nomi restituiscono candidati; fonti legacy/current non
sono unite. Periodi fino a 180 giorni, al massimo 10 siti nelle letture; limiti
ulteriori sulle osservazioni richiedono di restringere la query. Le metriche sono
osservate e coverage-aware; il modello riceve aggregati, profili locali e percorsi
numerici citabili. Le finestre manutentive confrontano occupazione osservata su
almeno quattro date comparabili e rispettano le ore consentite; restano suggerimenti
storici, non date future garantite. Capacità zero e dati mancanti non sono periodi
ideali. I record verificati possono fornire durata e scadenza di manutenzione;
senza questi la necessità resta sconosciuta, mai dedotta dallo stato ODH.

`request_forecast` accetta ID espliciti dei tre gruppi AC supportati, cutoff UTC,
storico, orizzonte 1..168 ore, soglie e modalità pesi offline. Nuovi siti/DC
richiedono una validazione separata, non sono aggiunti implicitamente. `run()`
conserva i default CLI e permette sottoinsiemi; analysis schema 1.1 consente
1–3 tabelle, mentre 1.0 richiede ancora i tre siti. L'obiettivo 20 colonnine entro
marzo è un target aziendale e una deadline, non una previsione di domanda a marzo.
La policy 90% è esplicita nel request, fingerprint e risultato; 95% è un altro
scenario, non il default implicito del catalogo simulato.

Input operativi opzionali: `python -m scripts.import_operational file.json` importa
una lista validata di record immutabili id/version, classificati verified,
simulated o assumed, con provenienza e date efficaci. Sono supportati preventivi,
permessi, capacità di connessione, budget, lead time, calendari, manutenzioni,
guasti e requisiti. Nessuna integrazione aziendale è inventata. Il read tool senza
ID restituisce al massimo 30 record; specificare gli ID con suffisso `:vN` nei
calcoli. Preventivi alternativi richiedono selezione esplicita. La conversione
punti/caricatori richiede il rapporto dichiarato; siti non sono equivalenti.

I costi usano Decimal, prezzi unitari IVA esclusa e aliquota dichiarata. Lead time
sono sommati conservativamente in giorni di calendario: calendari di lavoro,
dipendenze progettuali e fattibilità fisica richiedono verifica. Il risultato
soddisfatto/violato/sconosciuto riguarda soltanto i vincoli forniti; non certifica
l'investimento, la domanda né l'esecuzione. Prezzi sintetici rimangono sintetici.

## Conclusione con ipotesi non verificate

Gli errori persistenti nelle citazioni non interrompono più la discussione: dopo
un tentativo di correzione il turno viene marcato come ipotesi, privato dei
riferimenti numerici non validati e sottoposto agli altri ruoli e al critico.
Al limite dei round l’utente può confermare esplicitamente le incertezze e
concludere con un piano condizionale. La conferma non verifica capacità,
preventivi, permessi o altri dati mancanti e non esegue azioni esterne.
