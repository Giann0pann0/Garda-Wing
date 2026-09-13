# Revisione tecnica — Garda Wind AI V2.5

Focus: **metodo previsionale** (scelta modelli, uso dello storico centraline, calibrazione, validazione).
File esaminato: `app.py`, 539 righe.

---

## Giudizio in due righe

L'impianto concettuale è quello giusto: multi-modello + contesto sinottico (gradiente Bolzano/Trento vs Brescia/Verona) + calibrazione sullo storico centraline. Il problema è che **la parte "AI" non gira mai** per un bug di una parola, e che **quando girerà si allenerà sulla verità sbagliata e si auto-valuterà in modo illusorio**. Quello che vedi oggi nel cruscotto è al 100% la formula `physics`, cioè una ventina di coefficienti inventati a mano.

---

## 1. Bug fatale: il modello empirico non si allena mai

Riga 328, in `ridge_fit`:

```python
inter = ym - sum(coef[j]*means[j] for j in range(p))
return intercept, coef     # <-- 'intercept' non esiste
```

Verificato eseguendolo: `NameError: name 'intercept' is not defined`, **ad ogni chiamata**. La chiamata è dentro un `try/except` a riga 356-358, quindi l'errore finisce silenziosamente in `errors` e non lo vedi mai in interfaccia.

Conseguenza a catena:
- `empirical_models` resta sempre vuota;
- `predict_empirical` cade sempre nel ramo `'fisica'` (riga 170);
- `mode='fisica'` non è mostrato da nessuna parte nel cruscotto, quindi non c'è modo di accorgersene;
- l'intera premessa dell'app ("collegare le previsioni allo storico delle centraline") non è mai stata eseguita nemmeno una volta.

**Fix:** `return inter, coef`. Un carattere. Ma prima di considerarla risolta, leggi i punti 2 e 3, perché una volta che si allena produce numeri peggiori del silenzio attuale.

---

## 2. La calibrazione dei modelli misura la cosa sbagliata

`calibrate_models` (riga 192) definisce la "verità" così:

```python
hist = get_json(HIST, {... 'models':'best_match'})
actual = {r['time']: r['wind_speed_10m'] ...}
```

`HIST` è `historical-forecast-api`, che — confermato sulla documentazione Open-Meteo — **non contiene osservazioni**: restituisce output di modello archiviato (le prime ore di ogni run concatenate). Quindi stai misurando quanto ECMWF, ICON-2I, ARPEGE ecc. **assomigliano a best_match**, non quanto ci prendono.

Perché su Garda è particolarmente grave: tutti i modelli globali sottostimano sistematicamente Ora e Pelèr nella stessa direzione, perché il lago è largo 2-3 km e la cella di griglia (7 km ICON-EU, 11-25 km GFS) cade sul versante montuoso a centinaia di metri di quota. Un errore comune a tutti i modelli è **invisibile** a questa calibrazione. I pesi `skill` che ne escono premiano la conformità al consenso, non l'accuratezza — e il `bias` sottratto a riga 136 è il bias rispetto a un altro modello, quindi rumore mascherato da correzione.

**La verità deve essere `station_obs`.** È l'unica serie reale che hai. Non ci sono scorciatoie: la calibrazione per-modello va rifatta accoppiando `previous_dayN` con le osservazioni di centralina, esattamente come già fa (correttamente) `train_empirical`. `calibrate_models` e `train_empirical` dovrebbero condividere lo stesso codice di accoppiamento.

Nota secondaria: quando lo fai, il numero minimo di 30 coppie per stimare MAE/bias/correlazione (riga 201) va alzato, e le coppie vanno raggruppate per blocchi giornalieri, non per ora — ore consecutive dello stesso giorno non sono campioni indipendenti e gonfiano `n` di un fattore ~8.

---

## 3. Le metriche di qualità sono calcolate in-sample: non significano niente

Riga 356:

```python
inter, coef = ridge_fit(X, y, 1.2)
pred = [inter + sum(a*b ...) for x in X]     # stesso X su cui ha addestrato
r2 = 1 - ssr/sst
```

MAE, RMSE, R² e `resid_sd` sono tutti calcolati sui dati di addestramento. Con 16 feature, ridge λ=1.2 su feature standardizzate (regolarizzazione molto blanda) e la soglia di utilizzo fissata a **n ≥ 30** (riga 168), sei in pieno overfitting: 30 campioni e 16 parametri daranno un R² apparente alto e zero capacità predittiva. In più `resid_sd` in-sample è sottostimato, quindi la banda `lo–hi` mostrata sul grafico sarà **troppo stretta** — l'errore peggiore possibile per chi decide se andare in acqua.

Cosa serve:
- **Cross-validation a blocchi temporali** (leave-one-day-out, o 5 fold per giorni contigui). Le metriche salvate in `empirical_models` devono essere quelle out-of-fold.
- **Soglia di utilizzo realistica**: con 16 feature servono 200-300 osservazioni, non 30. Regola pratica: ≥15 campioni *indipendenti* (= giorni, non ore) per feature.
- **Un baseline da battere**, salvato accanto alle metriche: il modello empirico va usato solo se batte in CV sia la media multi-modello grezza, sia la climatologia per ora/mese. Oggi non c'è alcun confronto: il modello empirico viene usato appena `n≥30`, qualunque cosa valga.

---

## 4. Lo storico centraline: il collo di bottiglia vero

È la risorsa che rende il progetto sensato, ed è gestita male su tre fronti.

**Volume.** Malcesine (`fetch_malcesine_station`) fa scraping di **uno snapshot istantaneo per ogni avvio dell'app**. Se apri l'app tre volte al giorno raccogli 3 punti/giorno: per arrivare a un campione allenabile servono anni. Torbole va meglio (`h=168`, 7 giorni a rotazione) ma solo se apri l'app almeno una volta a settimana, altrimenti buchi permanenti.
→ Hai già `import_csv_bytes`: **usalo per un import massivo iniziale**. Meteotrentino pubblica serie storiche scaricabili per le sue stazioni (T0193 inclusa) sul portale open data; vale la pena verificare sul WSDL di `dati.meteotrentino.it/service.asmx` se esiste un metodo di archivio oltre a `datiRealtimeUnaStazione`. Per Malcesine, cercare un archivio della Fraglia Vela / MeteoProject o ripiegare su un'altra stazione dell'alto lago con storico pubblico. Due anni di dati orari importati in un pomeriggio valgono più di due anni di app aperta.

**Campionamento.** `iso_hour()` + `INSERT OR REPLACE` (riga 229): Meteotrentino restituisce dati a 10 minuti, tu tieni **l'ultimo record che l'attraversamento ricorsivo incontra dentro quell'ora**, non una media. È un sottocampionamento casuale con varianza alta — rumore puro iniettato nel target. Serve un'aggregazione esplicita: media oraria per il vento medio, massimo orario per la raffica, media vettoriale (non scalare!) per la direzione.

**Unità.** Riga 249: `wk = w*1.943844` applicato incondizionatamente, con un commento che dice "when plausible" ma senza alcun controllo di plausibilità. Se Meteotrentino cambia unità o se il walker aggancia un campo diverso, ti ritrovi tutto lo storico moltiplicato per 2 senza accorgertene. Stesso problema in `import_csv_bytes` (riga 306): l'unità viene dedotta solo se esiste una colonna che la dichiara, altrimenti assume nodi — e la maggior parte dei CSV italiani è in m/s o km/h.
→ Aggiungi un controllo di sanità su ogni inserimento (media della serie fuori da 0-60 kn → rifiuta e segnala) e mostra in interfaccia min/media/max dello storico per spot.

**Coerenza del target.** Torbole salva presumibilmente una media su 10 minuti, Malcesine la "velocità attuale" istantanea. Sono due grandezze diverse. Non è fatale (i modelli sono per-spot) ma va documentato, e soprattutto: se un giorno unisci due fonti sullo stesso spot, stai mescolando due definizioni di vento. Il campo `quality` esiste ma non viene mai usato come peso nel fit (riga 354-356: `q` viene estratto e ignorato).

---

## 5. Le feature: cosa c'è, cosa manca, cosa è sprecato

Le presenti sono ragionevoli (`pg`, `tg`, `rad`, `cloud_low`, `w925`) — l'intuizione di usare i livelli isobarici invece del solo 10 m è corretta ed è la cosa migliore del progetto. Ma:

**`spread` è una feature morta.** In `historical_feature_rows` è hardcoded a 4 (riga 344). Colonna costante → deviazione standard 0 → il ridge le assegna coefficiente 0. In previsione lo spread reale c'è, ma viene moltiplicato per zero. Risultato: **la dispersione fra modelli non influenza mai la stima**, anche se è il miglior indicatore di incertezza che hai. O la ricostruisci storicamente (richiedendo `previous_dayN` per più modelli e calcolandone la deviazione), o la togli dalle feature e la usi solo per l'intervallo.

**La direzione va scomposta lungo l'asse del lago, non ridotta a un punteggio.** L'asse Torbole→Malcesine è ~**205°/025°** (l'ho calcolato dalle coordinate nel file). Quindi:
- Torbole `ideal=180` è sbagliato di ~25°: l'Ora entra da 195-210, non da sud pieno.
- Malcesine `ideal=10` andrebbe a ~25.
- Meglio ancora: invece di `ang_score`, usa la **componente lungo l'asse** del vento a 925 hPa: `u_along = w925 · cos(dir925 − 205°)`. Fisicamente è la cosa che conta: un gradiente sinottico *contrario* uccide l'Ora, uno *favorevole* debole la rinforza. `ang_score` schiaccia i due casi opposti sullo stesso punteggio basso se la direzione è a 90°, e non distingue affatto il segno.

**Le tre feature che mancano e che conterebbero di più:**

1. **Indice di brezza di lago** (tipo Biggs-Graves): `ΔT / U²`, dove ΔT è il contrasto termico terra-acqua e U il vento di gradiente. È la formulazione classica per prevedere *se* la brezza si instaura, e tipicamente una singola feature del genere batte una decina di variabili grezze. La soglia va calibrata localmente, ma la forma funzionale è nota e ti fa risparmiare campioni — cosa cruciale quando ne hai pochi.
2. **Persistenza.** Il predittore singolo più forte dell'Ora di oggi è spesso com'è andata ieri (e, per l'Ora, com'è stato il Pelèr della notte precedente). Hai già `station_obs`: aggiungi come feature il picco della finestra del giorno precedente e la media notturna. Costa zero dati nuovi.
3. **Stabilità / inversione.** `T850 − T2m` (o il gradiente 925-2m) discrimina le giornate in cui il termico rompe l'inversione da quelle in cui resta tappato. Scarichi già `temperature_850hPa` e `temperature_925hPa` in `VARS`, ma **non le usi mai** né in `ensemble` né in `feature_vector`. Sono già nel database.

**Quota della cella di griglia.** Non controlli mai il campo `elevation` che Open-Meteo restituisce. Con `cell_selection='land'` su Torbole quasi certamente peschi una cella a diverse centinaia di metri di quota. Vale la pena loggarlo per modello e valutare `cell_selection='sea'` o il parametro `elevation` per la correzione di temperatura. Non risolve il problema di scala, ma almeno lo rendi visibile.

---

## 6. Il target è sbagliato: l'Ora è bimodale, la regressione lineare la spappola

Questo è il punto metodologico più importante dopo il bug.

L'Ora non è una variabile continua distribuita normalmente: o si instaura (e allora sono 15-25 nodi) o non si instaura (e allora sono 3-6 nodi). Una regressione lineare unica su tutti i campioni stima la *media* dei due regimi, cioè un valore che **non si verifica quasi mai**. Sistematicamente: sovrastimerà i giorni morti e sottostimerà i giorni buoni — esattamente l'errore che rende un'app inutile per decidere se caricare la macchina.

Struttura corretta, in due stadi:
- **Stadio A — classificazione giornaliera:** "l'Ora si instaura oggi?" (soglia, es. media ≥12 kn per ≥2 ore consecutive nella finestra). Feature giornaliere: indice di brezza, gradiente barico, radiazione integrata, componente sinottica lungo l'asse, persistenza. Output: una **probabilità**.
- **Stadio B — intensità condizionata:** regressione sul picco/media della finestra, allenata *solo* sui giorni in cui si è instaurata.

Il prodotto finale diventa: "72% di probabilità che entri, e se entra 16-21 kn fra le 14 e le 18". È sia più onesto sia più utile della stima puntuale attuale. E la classificazione è molto più efficiente in termini di campioni della regressione — importante visto il punto 4.

Se vuoi restare su un singolo modello di regressione, almeno allena su `sqrt(vento)` o `log1p(vento)`: la variabile è limitata a ≥0 e asimmetrica, e oggi il modello può predire valori negativi (riga 169: `max(0, y)` li tronca, che è una pezza, non una soluzione).

**Inoltre: allena sulla finestra, non sull'ora.** Con pochi giorni disponibili, un modello sul *picco della finestra* o sulla *media 13-18* ha molti meno parametri da stimare e un rapporto segnale/rumore molto migliore rispetto a un modello orario. Il profilo orario puoi ricostruirlo con una forma climatologica media scalata sul picco previsto.

---

## 7. L'ensemble sovrastima la propria sicurezza

`CORE` (riga 29) contiene 11 modelli, ma non sono 11 informazioni indipendenti:
- `Best Match` **è** uno degli altri (Open-Meteo seleziona il migliore per la località), quindi è conteggiato due volte;
- `ICON-EU`, `ICON Global`, `ICON Seamless`, `ICON-2I` condividono lo stesso modello e in larga parte le stesse condizioni iniziali;
- `ECMWF IFS` e `ECMWF AIFS` idem.

Lo `spread` calcolato a riga 140 come `pstdev` su membri correlati è quindi **sistematicamente troppo piccolo**, e da lì derivano `spreadq` → `confidence` → la banda sul grafico. L'app si dichiara più sicura di quanto sia. Inoltre `count = len(gs)/8` (riga 146) premia semplicemente il numero di fetch riusciti, che non è informazione meteorologica.

Rimedi: togli `Best Match` dall'ensemble (tienilo come riferimento a parte), scegli **un** membro per famiglia (ECMWF IFS, ICON-2I o ICON-EU, GFS, ARPEGE, UKMO, GEM, ICON-CH2, AROME), e soprattutto **calibra la confidenza sui residui verificati** invece di comporla da pesi arbitrari: se dichiari 70%, il valore osservato deve cadere nella banda il 70% delle volte. Questo si misura, e con lo storico centraline puoi misurarlo.

---

## 8. Minori, ma da sistemare

| Riga | Problema |
|---|---|
| 137-138 | Se `gust` è `None`, viene sostituita con `wc` (il vento medio corretto): la raffica prevista collassa sul medio senza alcun segnale |
| 154 | `confidence` = combinazione lineare di tre numeri arbitrari; non è una probabilità e non è verificata |
| 173-185 | `decisions()` non è mai chiamata dal cruscotto — codice morto che duplica (male) `hourly_product` |
| 33 | `FEATURES` è solo decorativo, non usato da `feature_vector`: se aggiungi/togli una feature i due si disallineano in silenzio |
| 351 | `max_days=730` sul previous-runs API: l'archivio Open-Meteo parte da **gennaio 2024** per la maggior parte dei modelli, quindi oggi ~630 giorni disponibili. La richiesta su 2 anni × 9 variabili × 5 punti geografici è anche pesante in termini di quota API |
| 110-113 | `MAX(issued)` per modello: se un modello fallisce in un aggiornamento, resta il suo run vecchio e l'ensemble mescola run di orari diversi senza segnalarlo |
| 236-254 | Il walker ricorsivo di `fetch_torbole_station` salva *e poi* ricorre nei figli: strutture annidate possono produrre salvataggi duplicati/spuri. Un parser esplicito dello schema è più noioso ma non ti tradisce |
| 224-225 | `iso_hour` su ora locale: nei due cambi d'ora annuali hai un'ora duplicata (che si sovrascrive) e una mancante. Meglio archiviare in UTC e convertire solo alla presentazione |
| 386-406 | `background_update` fa 11 modelli × 2 spot + contesto + calibrazioni su 180 giorni ad ogni ciclo stantio: verifica di non sbattere contro i limiti orari di Open-Meteo, i cui costi sono pesati per giorni e variabili |

Nota positiva: il server è correttamente legato a `127.0.0.1` (riga 539), WAL e `busy_timeout` sono impostati, gli errori di rete sono isolati per fonte. La struttura del DB è pulita e ben pensata.

---

## 9. In che ordine lo rifarei

1. **`return inter, coef`.** Poi fai emergere gli errori: `UPDATE_STATE['errors']` deve essere visibile in interfaccia, non nascosto dietro un pallino giallo, e `mode` (`empirico` / `fisica`) va mostrato accanto a ogni previsione. Finché non vedi cosa gira al buio, ogni altra modifica è cieca.
2. **Import massivo dello storico centraline.** È il vincolo che blocca tutto il resto. Senza 1-2 anni di osservazioni orarie non c'è modo di calibrare niente, e nessun raffinamento del modello vale quanto questo.
3. **Rifai `calibrate_models` contro `station_obs`** invece che contro `historical-forecast`, condividendo il codice di accoppiamento con `train_empirical`.
4. **Validazione out-of-sample a blocchi giornalieri + baseline da battere.** Senza questo non saprai mai se stai migliorando. È il passo che trasforma il progetto da "sembra funzionare" a "so di quanto sbaglia".
5. **Ristruttura il target in due stadi** (probabilità che entri + intensità condizionata), allenati sulla finestra invece che sull'ora.
6. **Poi** le feature: componente lungo l'asse a 205°, stabilità T850−T2m (dati già in DB), persistenza del giorno prima, indice di brezza.
7. Solo alla fine, con qualche centinaio di giorni verificati, ha senso passare da ridge a qualcosa di non lineare (gradient boosting). Prima è inutile.

**La domanda a cui l'app deve saper rispondere**, e che oggi non si pone: *"quando dico 18 nodi alle 15, quanto sbaglio in media, e con che frequenza il valore reale cade nella banda che mostro?"* Quel numero, misurato su dati che il modello non ha visto, è l'unica cosa che distingue questo progetto da un'interfaccia più bella sopra Windguru.
