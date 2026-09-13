# Garda Wind 3.5 — audit metodologico

Verifica dei 14 criteri contro il codice, punto per punto. Dove il sistema
viola un criterio è scritto, non corretto in silenzio. Le violazioni sono
ordinate per gravità in fondo.

Legenda: **OK** rispettato · **PARZIALE** rispettato a metà · **VIOLATO** ·
**ASSENTE** non implementato.

---

## 1. LONG-SURFACE vs SHORT-FULL vs HYBRID — PARZIALE

Cosa c'è: i due candidati esistono e competono (`model.train`, `_evaluate_candidate`).
LONG-SURFACE = ERA5 superficie dal 2012, livello `surface` (13 feature).
SHORT-FULL = historical-forecast ~5 anni, livelli `bias` / `reduced` / `full`
(1 / 8 / 20 feature, incluse 925-850-700 hPa).

Lo schema di CV è identico e il periodo di test è **lo stesso insieme di
giorni** per entrambi: si valuta sempre sui vettori costruiti dalle previsioni,
mai sulla rianalisi. Questo era il punto critico ed è a posto.

**Cosa manca:**

- **HYBRID non esiste.** Nessuno stacking, nessuna combinazione.
- **La promozione fra candidati non ha margine.** Il gate al 3%
  (`PROMOTION_MARGIN`) vale solo contro i *baseline*. Fra due candidati si
  prende `min(mae)` senza soglia: un candidato migliore dello 0,4% vince. Con
  ~500 giorni di test una differenza del genere è rumore.
- **Nessun intervallo di confidenza** sulla differenza. Non c'è bootstrap.

---

## 2. Validazione temporale rigorosa — VIOLATO (tre punti)

**a) Lo split non è forward-chaining.** `block_folds` assegna i giorni a fold
temporali *contigui*, quindi dentro un fold non c'è mescolamento — ma il fold 1
(il più antico) viene predetto da un modello addestrato anche sui fold
successivi. Informazione dal futuro verso il passato. Per un processo
stagionale stazionario è una scelta difendibile e comune, ma **non è quello che
hai chiesto** e non simula una previsione reale. Solo l'ultimo fold lo fa.

**b) Il lambda è scelto sui fold di valutazione.** `_fit_stage` prova la griglia
di λ e tiene quello con la perdita out-of-fold minore, poi riporta quella stessa
perdita come metrica. È selezione sul test: serve una CV annidata, o un λ fisso.
L'ottimismo è modesto (griglia di 5 valori) ma è reale.

**c) La calibrazione isotonica è tarata sui dati su cui poi viene misurata.**
`_evaluate_candidate` costruisce la PAVA sulle predizioni out-of-fold
dell'intero insieme e subito dopo calcola il Brier di quelle stesse predizioni
calibrate. **La tabella di affidabilità che vedi in diagnostica è quindi
ottimistica per costruzione.** È la violazione più insidiosa perché riguarda
proprio la metrica che deve dirti se il 70% vale 70%.

**d) Reanalysis del giorno target:** qui siamo a posto. Il candidato ERA5 è
addestrato su ERA5 ma valutato con i vettori previsti. Nessuna rianalisi del
giorno bersaglio entra come predittore in valutazione.

**MA** — vedi il punto 8, dove c'è una fuga di informazione futura vera.

---

## 3. Separazione dei tre problemi — OK

Tre modelli distinti, addestrati su insiemi diversi:

- P(regime) — logistica, tutti i giorni;
- intensità | regime — ridge su `log1p(picco)`, **solo** i giorni in cui il
  regime è entrato;
- timing — ridge sull'ora del picco, solo i giorni in cui è entrato.

Nessun modello unico che mescoli le tre cose.

---

## 4. Timing — PARZIALE

C'è il **peak time** con MAE in minuti e due benchmark (climatologia stagionale,
ora del massimo dell'ensemble grezzo), con gate di promozione contro il
migliore dei due.

**Manca:**

- **onset non è addestrato.** Viene calcolato nei bersagli (`onset_hour`) e poi
  non usato da nessuna parte.
- **end non è nemmeno definito.**
- Metriche: solo MAE. Mancano mediana, P(|err|<30 min), P(|err|<60 min).
- La climatologia di riferimento è calcolata in-sample (su tutti i giorni, poi
  confrontata sugli stessi). Qui l'errore favorisce il *baseline*, quindi è
  conservativo — ma resta sporco.

---

## 5. Definizione del regime — PARZIALE (migliorata nella 3.5)

Nella 3.4 c'era un difetto grosso, che hai intercettato con la domanda sul
vento da sud: il bersaglio era *solo intensità*. Quindici nodi da sud alle otto
del mattino venivano contati come "Pelèr entrato".

Nella 3.5 il criterio è deterministico e riproducibile:

- **presenza**: picco della media oraria nella finestra ≥ soglia **E**
  direzione osservata al picco entro ±70° dall'asse del regime;
- **onset**: prima ora che soddisfa entrambe le condizioni;
- **finestre**: fisse per spot/regime, dichiarate in `config`;
- in previsione, la probabilità viene frenata con continuità se la direzione
  prevista esce dal settore.

**Manca ancora:**

- **nessuna marcatura dei giorni ambigui.** Transizioni, sinottico che imita il
  termico, giorni con direzione instabile: entrano tutti nel training con lo
  stesso peso. Il campo `dir_const` (costanza direzionale) è calcolato e salvato
  in `obs_hour` ma **non viene usato** — sarebbe il candidato naturale per un
  flag di qualità.
- **`end` non è definito.**
- La soglia di ±70° è scelta a mano, non tarata sui dati.

---

## 6. Metriche probabilistiche — PARZIALE

Brier ✔, curva di affidabilità ✔ (ma vedi 2c: ottimistica).
**Log loss assente. ROC-AUC assente.**

---

## 7. Metriche intensità — PARZIALE

MAE ✔, bias ✔ (calcolato, non mostrato), RMSE ✔.

**Assenti:** errore sulle sole giornate utili per il wing, errore sui picchi,
distribuzione degli errori per stagione, distribuzione per lead time.

---

## 8. Lead time — VIOLATO, ed è grave

Questa è la violazione peggiore, su due fronti.

**a) Fuga di informazione futura.** La feature `persist` è il picco osservato
del **giorno precedente al bersaglio**. Per una previsione a D-1 è legittima.
Per D-3 non lo è: il giorno T-1 è ancora nel futuro rispetto al momento in cui
la previsione viene emessa. Il modello si addestra avendola sempre disponibile
e la usa a tutti i lead. **È informazione che in esercizio a D-3 non esiste.**

`persist` è nei livelli `full` e `surface`, cioè in quelli che vengono
tipicamente promossi.

**b) Nessuna validazione per lead.** Esiste **un solo** modello giornaliero per
spot, addestrato su predittori a scadenza ~0-24 h, applicato a tutti i giorni
da oggi a D+7. L'adattamento alla scadenza è affidato a due dizionari di
costanti **inventate a mano**:

```python
LEAD_SHRINK = {0:1.00, 1:1.00, 2:0.90, 3:0.78, 4:0.62, 5:0.48, 6:0.36, 7:0.26}
LEAD_WIDEN  = {0:1.00, 1:1.00, 2:1.15, 3:1.32, 4:1.55, 5:1.80, 6:2.05, 7:2.30}
```

Non sono stimate da niente. Il ±1,9 kn mostrato sulla scheda di D+5 è l'errore
misurato a D-1, allargato di un fattore deciso a occhio.

La verifica per-lead che esiste (`model_skill`) riguarda i **singoli modelli
meteo**, non il prodotto finale.

**Conseguenza pratica: dei sette giorni che l'app mostra, uno solo ha un
errore misurato. Gli altri sei hanno un errore estrapolato.**

---

## 9. Wing Decision Score — ASSENTE

`grade()` produce l'etichetta (ECCEZIONALE / BUONO / …) ma non viene **mai
valutata**. Nessuna matrice di confusione, nessuna precision dei GO, nessun
recall delle giornate buone, nessuna false-partenza contata, nessun costo
asimmetrico.

È la metrica di prodotto e oggi non esiste.

---

## 10. Torbole e Malcesine con promesse diverse — PARZIALE

La diagnostica mostra le metriche separate per spot, e la scheda dichiara la
fonte del modello. Ma **l'interfaccia fa la stessa promessa visiva**: stessa
barra, stessa percentuale, stessa aria di precisione, che dietro ci siano
quattordici anni o sei mesi.

Nessuna differenziazione grafica della fiducia in funzione della quantità di
dati.

---

## 11. Collector ridotto all'essenziale — OK, d'accordo

Già concordato: l'unico buco non ricostruibile sono i **livelli isobarici per
modello alle varie issued_at**. ERA5, l'archivio Hydstra di Torbole, l'intraday
di Malcesine e previous-runs sono tutti riscaricabili a ritroso.

---

## 12. Tabella di benchmark automatica — ASSENTE

Non esiste. La diagnostica mostra il modello promosso e i candidati in gara, ma
non c'è una tabella per spot × regime × lead con: ensemble grezzo, miglior
singolo modello, climatologia, SHORT-FULL, LONG-SURFACE, HYBRID, promosso, e
intervallo bootstrap del miglioramento.

---

## 13. Blocco cieco contro l'overfitting da iterazione — VIOLATO

Non esiste nessun blocco riservato. E il rischio non è teorico: **in questa
sessione abbiamo guardato i numeri e cambiato il sistema più volte.** Ogni
decisione presa guardando le metriche out-of-fold le ha rese, di un po', non
più out-of-sample.

---

## 14. Report tecnico sintetico — ASSENTE

Non c'è. Andrebbe generato come file, non come schermata.

---

# Riepilogo: dove il sistema è debole

Ordinate per gravità.

| # | Problema | Effetto |
|---|---|---|
| 1 | `persist` usa il giorno prima del bersaglio, a tutti i lead | informazione futura reale a D≥2; gonfia il vantaggio misurato |
| 2 | Nessuna validazione per lead; costanti inventate | 6 giorni su 7 hanno un errore estrapolato, non misurato |
| 3 | Calibrazione PAVA tarata sui dati su cui è misurata | la curva di affidabilità è ottimistica per costruzione |
| 4 | λ scelto sui fold di valutazione | ottimismo modesto ma sistematico |
| 5 | Promozione fra candidati senza margine né CI | il rumore può scegliere il vincitore |
| 6 | CV a blocchi non forward-chaining | informazione futura→passato fra i fold |
| 7 | Nessun blocco cieco | abbiamo iterato sulle metriche che usiamo per decidere |
| 8 | Wing Decision Score mai valutato | la metrica di prodotto non esiste |
| 9 | Giorni ambigui non marcati (`dir_const` calcolato e inutilizzato) | training contaminato dalle transizioni |
| 10 | onset ed end non modellati | il timing copre un terzo del problema |

**Quanto valgono davvero i numeri della 3.4?**

I guadagni riportati (Ora 12%, Pelèr 26% sull'intensità; Brier 27% e 24%) sono
misurati a **D-1**, con blocked CV, e sono inquinati da: `persist` (che a D-1 è
legittima, quindi qui non è un problema), λ scelto sul test, e calibrazione
in-sample per la parte probabilistica.

La mia stima onesta: **il guadagno sull'intensità a D-1 è sostanzialmente
reale** (la fuga di `persist` non morde a quel lead, e il confronto contro
l'ensemble grezzo è pulito). **Il guadagno probabilistico è sovrastimato** di
una quantità che non so quantificare senza rifare la calibrazione dentro i
fold. **Tutto ciò che riguarda D+2 e oltre non è validato.**

---

# Ordine di lavoro proposto

Prima le cose che cambiano i numeri, poi quelle che li misurano meglio, poi
quelle che aggiungono.

**Blocco A — correttezza (invalidano i numeri attuali se non fatte)**

1. `persist` lead-aware: o modelli separati per lead, o la feature sparisce dai
   lead ≥ 2. Va deciso, non aggirato.
2. Calibrazione dentro i fold.
3. λ in CV annidata.
4. Forward-chaining come schema predefinito, blocked CV come opzione dichiarata.

**Blocco B — misura (senza questi non sappiamo dove siamo)**

5. Valutazione per lead: D-3, D-2, D-1, sera prima, mattina stessa. Modelli e
   pesi possono cambiare con la scadenza.
6. Bootstrap sull'IC del miglioramento; promozione solo se l'IC non attraversa
   lo zero.
7. Blocco cieco: l'ultima stagione riservata, aperta una volta sola alla fine.
8. Tabella di benchmark automatica + report tecnico su file.

**Blocco C — completamento**

9. Wing Decision Score con costi asimmetrici (falsa partenza ≫ occasione persa).
10. onset ed end, con le quattro metriche richieste.
11. Marcatura dei giorni ambigui usando `dir_const`.
12. Metriche per stagione, per lead, sulle giornate utili, sui picchi.
13. Log loss; HYBRID solo se il blocco B dice che serve.
14. Differenziare la promessa di affidabilità fra Torbole e Malcesine
    nell'interfaccia.

Il blocco A è la precondizione: finché non è fatto, ogni numero prodotto dal
blocco B misurerebbe un sistema che non è quello che andrà in esercizio.
