# Blocco A — Garda Wind 3.6

**Cosa è stato fatto, cosa resta valido, cosa va ritirato.**
Settembre 2026. 281 verifiche automatiche superate, 0 fallite.

---

## 1. I sette punti, nell'ordine che avevi chiesto

### 1. `persist` rigorosamente lead-aware

Non un modello a cui togliere `persist` in inferenza, come avevi specificato.
La feature è stata **sostituita**, e nel farlo è venuto fuori che il problema
era peggiore di una fuga di informazione.

Il conto, per esteso. La 3.5 usava come memoria il picco osservato del giorno
`T-1`, con `T` il giorno bersaglio. Con emissione il giorno `T-L`, il giorno
`T-1` è concluso solo se `T-1 < T-L`, cioè solo se `L = 0`. A D+1 quel giorno è
il giorno stesso dell'emissione e la sua finestra non si è ancora chiusa; da D+2
è nel futuro. Quindi la fascia che avevo scritto in `config.py` — *short (0,1)
con persist* — era **sbagliata anche a D+1**, e l'ho corretta.

Ma il danno reale era un altro. In addestramento la memoria c'era sempre,
perché l'archivio è fatto di giorni tutti passati. In esercizio, la ricerca
dell'osservazione inesistente restituiva `None` e il valore diventava `0.0`.
Risultato: **a ogni scadenza utile il modello applicava a un ingresso
costantemente nullo un coefficiente stimato su valori veri.** Non un vantaggio
indebito, un disallineamento fra addestramento ed esercizio.

La forma corretta non è buttare la memoria — l'autocorrelazione fra giorni
consecutivi esiste e vale qualcosa — ma dichiarare *quale* memoria si ha e
*quanto è vecchia*:

| | 3.5 | 3.6 |
|---|---|---|
| feature | `persist` = picco di `T-1` | `persist_obs` = ultimo picco **noto all'emissione** |
| | — | `persist_age` = la sua età in giorni (`L+1`) |
| a D+0 | valore vero | valore vero, età 1 |
| a D+3 | **0.0 travestito da misura** | picco di `T-4`, età 4, dichiarata |

Così il modello può imparare da sé quanto scontare un ricordo di sei giorni
prima. E le due strade combaciano: `engine.build_samples` e
`engine.forecast_days` fanno **lo stesso conto**, ed è un test a verificarlo su
3 648 campioni (`t_lead.py`), non un commento.

Le fasce restano, ma per la ragione giusta: fra D+0 e D+6 non cambia il
vettore, cambia il **legame** fra vettore ed esito. Un modello per fascia lo
lascia stimare invece di imporlo.

### 2. Forward chaining ovunque

`block_folds` non è più il modo in cui si valuta niente. Tenere insieme i giorni
evitava che ore dello stesso giorno finissero di qua e di là, ma non impediva la
cosa grave: **predire il 2019 con un modello addestrato anche sul 2023.**

Ora ogni fold si addestra solo su ciò che lo precede (`util.forward_folds_idx`,
`validate.forward_folds`), e nel confronto fra sorgenti diverse c'è un vincolo
in più: da ERA5 si prendono solo i giorni *precedenti* al fold di prova, non
"tutti tranne quelli del fold". Un modello addestrato su ERA5 del 2023 e provato
sul 2015 non descrive niente che possa succedere.

Il prezzo è reale: il primo 40% dei giorni serve solo ad addestrare e non viene
mai predetto. Si paga in campioni, non in onestà.

### 3. Calibrazione dentro i fold

Ogni fold viene calibrato con i soli fold **precedenti**, e il punteggio si
misura solo sui fold che hanno avuto una calibrazione vera alle spalle.

**È questo che ha fatto emergere il difetto più serio di tutta la revisione**
(sezione 2 qui sotto).

### 4. λ annidato

Scelto con una CV interna al solo periodo di addestramento
(`validate._pick_lambda`), mai guardando il fold di prova. Un test verifica che
la CV interna non tocchi il blocco cieco.

### 5. Metriche e bande separate per scadenza

`validate.fit_band` produce, per ogni singola scadenza dentro la fascia:
giorni di prova, MAE, bias, RMSE, MAE sulle giornate utili e sul quintile più
ventoso, Brier, log loss, errore di calibrazione, tabella di affidabilità,
errore di orario (mediano, ±30′, ±60′, bias), riferimenti banali e **intervallo
bootstrap** (400 ricampionamenti appaiati) del guadagno.

Le bande di incertezza sono i quantili dei residui misurati **a quella
scadenza**. Nel mondo sintetico di prova si allargano da 4,9 kn a D+0 a 7,2 kn a
D+7 **senza che nessuno gliel'abbia detto**.

### 6. I moltiplicatori a mano sono spariti

`LEAD_SHRINK` e `LEAD_WIDEN` sono stati eliminati. Erano due tabelle di
moltiplicatori per scadenza non stimati da niente: «0.62 a quattro giorni» aveva
l'aria di una misura e non lo era, e **un numero inventato che sembra misurato è
peggio di nessun numero**, perché chi legge non ha modo di distinguere le due
cose.

Sostituiti da due cose che si misurano:

- **attenuazione** → la calibrazione isotonica tarata *alla scadenza*. Se a D+5
  il modello non discrimina, la curva di affidabilità di quella scadenza
  appiattisce da sé le probabilità verso la climatologia. Stesso effetto,
  stimato.
- **banda** → i quantili dei residui *a quella scadenza*.

Dove la scadenza non è validata non si inventa un sostituto: la banda viene
dalla dispersione d'ensemble (che è una misura del disaccordo fra modelli) e
**la previsione viaggia dichiarata come non validata**. Un test verifica che il
modello di una fascia applicato a un'altra non presti i propri residui.

### 7. Confronto fra strutture, ora possibile

`validate.band_study` mette a confronto cinque tagli di fascia, incluso
`unico 0-7` (nessuna separazione). Il criterio è **dichiarato** — media dei
guadagni relativi sui riferimenti banali, pesata sui campioni — perché Brier e
MAE non sono commensurabili e un `min()` silenzioso avrebbe nascosto la scelta.
Se separare non migliora, non si separa: tre modelli invece di uno sono tre
volte più parametri sugli stessi giorni.

Comandi nuovi: `--validate` (la tabella per spot × regime × scadenza),
`--bands` (il confronto fra tagli), `--validate-json FILE`.

---

## 2. Tre difetti trovati strada facendo

### a) La calibrazione isotonica non calibrava: memorizzava

Il più serio, e l'ho trovato solo perché ho spostato la calibrazione fuori dal
fold di prova.

`pava` applicato ai singoli campioni fonde solo i blocchi che violano la
monotonia. Tutti gli altri restano **di un campione**, e la loro «frequenza
osservata» è lo zero o l'uno di quel giorno. Sui dati del mondo sintetico
produceva **330 blocchi su 330 campioni**.

Una curva così, misurata sugli stessi dati su cui è nata, dà un Brier quasi
perfetto — restituisce l'esito vero. Su dati nuovi restituisce 0 o 1 quasi a
caso. Il numero, misurato:

| | Brier | climatologia |
|---|---|---|
| calibrazione in-sample (3.5) | *apparentemente ottima* | — |
| calibrazione fuori dal fold, `pava` come in 3.5 | **0,290** | 0,250 |
| calibrazione fuori dal fold, `pava` corretto | **0,139** | 0,250 |

Riga centrale: **peggio della climatologia**. La calibrazione in-sample non era
solo ottimistica, *nascondeva un calibratore rotto*.

Correzione: i campioni vengono prima raccolti in blocchi di conteggio uguale
(≈ radice del numero di campioni, mai meno di venti) e solo dopo si fondono i
violatori; ogni frequenza pubblicata poggia su almeno venti giornate.
`apply_calibration` interpola fra i centri dei blocchi invece di restituire un
gradino.

### b) Le due porte di promozione erano legate

Probabilità e intensità rispondono a due domande diverse e superano le proprie
porte in momenti diversi. Sui dati di prova capita — e capiterà sui tuoi — che
il *quanto* batta il vento grezzo del 48 % con intervallo [+46, +51] mentre il
*se* guadagni il 5 % con intervallo **[-1,9, +10,8]**, cioè niente.

Nella 3.5 la probabilità non promossa buttava via anche l'intensità. Ora si
promuovono separatamente e ogni numero pubblicato porta la propria provenienza
(`source_prob`, `source_int`). Quando il *se* non è promosso si dichiara la
frequenza climatologica osservata, non il prior fisico: il prior non è calibrato
e in quella posizione mentirebbe meglio.

### c) Un difetto nel mio stesso banco di prova

Scrivendo `t_lead.py` avevo salvato il contesto sinottico con il gradiente
barico **vero** a tutte le scadenze, degradando solo il vento. Il modello
leggeva la pressione esatta, ignorava il vento sporco, e l'errore a D+3
risultava *identico* a quello a D+0 (MAE 1,36 contro 1,37; bande 4,6 e 4,6).
Nessun errore, nessun avviso: solo due numeri sospettosamente uguali.

Con il contesto degradato per scadenza: **MAE 1,89 → 2,24; bande 5,9 → 7,2 kn.**

Nel prodotto è la ragione per cui `backfill_lead_features` scarica **anche il
contesto** dall'archivio delle run precedenti. Lo segnalo perché è il tipo di
errore che non lascia traccia, e perché se lo trovi in qualcosa che scrivo io
voglio che sappia riconoscerlo.

---

## 3. Risultati che RESTANO validi

Non sono stati toccati dalle correzioni, e il motivo è che non dipendevano dai
meccanismi difettosi:

- **L'archivio Hydstra di Meteotrentino**: 742 803 misure a dieci minuti dal
  2012. È un fatto sulla disponibilità dei dati. Resta la scoperta più utile del
  progetto: trasforma «aspetta un anno di dati» in «addestra oggi».
- **L'archivio intraday di Malcesine** (`csv.php`, da marzo 2026, nodi, raffiche
  e direzioni): stessa natura.
- **La gestione dei fusi**: Meteotrentino pubblica CET tutto l'anno,
  MeteoProject ora locale. Verificato per confronto fra sorgenti, non per
  deduzione, e coperto da test sul giorno di cambio ora legale.
- **L'argomento per i due stadi.** La distribuzione è bimodale; una regressione
  unica stima la media di due regimi, cioè un valore che non si verifica quasi
  mai. Ragionamento, non misura.
- **Il regime è una direzione.** Quindici nodi da sud al mattino non sono Pelèr:
  per il modello del Pelèr quel giorno è un negativo corretto. E la
  `direction_penalty`, che ha eliminato la scheda incoerente («97 % che entri»
  sopra «niente Pelèr»): verificata, 0,01 contro 0,38.
- **Il settore ±70° è troppo largo**, con l'aritmetica: 320° dista 64° dall'asse
  del Pelèr (24°), quindi un discendente da Ballino cadrebbe *dentro*. In
  `regimes.py` il settore del Pelèr è ora ±45°, e `sector_study` lo mette alla
  prova sui dati (nel campione sintetico: purezza 100 % a ±45 contro 74 % a ±90).
- **La regola sulla valutazione**: chiunque sia addestrato — archivio previsioni
  o ERA5 — viene valutato con i vettori costruiti dalle *previsioni*. Un modello
  addestrato su rianalisi e valutato su rianalisi sembra molto più bravo di
  quanto sia.
- **I difetti della 2.5 di ChatGPT**: il `return intercept, coef` con
  `intercept` mai definito (confermato per esecuzione: il modello empirico non si
  addestrava mai) e la calibrazione contro `historical-forecast-api`, cioè
  contro output di modello invece che contro osservazioni.

---

## 4. Risultati che vanno RITIRATI

Da non usare più, in nessuna forma, e i motivi sono strutturali:

| Che cosa | Perché |
|---|---|
| **Ogni Brier e ogni tabella di affidabilità pubblicati dalla 3.5** | calibrazione in-sample **e** calibratore rotto (§2a). Erano buoni per costruzione, non per merito. |
| **Ogni MAE ottenuto con `block_folds`** | il fold antico veniva predetto anche con dati successivi. Non è la quantità che misurava di essere. |
| **Ogni numero per D+1…D+7** | prodotti moltiplicando i valori di D+0 per `LEAD_SHRINK`/`LEAD_WIDEN`, che non erano stimati da niente. |
| **Ogni copertura di banda dichiarata** | calcolata con la banda in-sample e i moltiplicatori. |
| **Ogni contributo attribuito a `persist`** | a scadenza ≥ 1 la feature era zero in esercizio e vera in addestramento: il coefficiente non descriveva nulla di utilizzabile. |
| **La promozione di livello (`reduced`/`full`) dichiarata dalla 3.5** | decisa con Brier gonfiati; va ridecisa. |

Una precisazione sulla mia stessa affidabilità: **le cifre concrete della 3.5
addestrata sui tuoi dati veri non le ho più in contesto** (questa sessione è
stata compattata). Ritiro quindi le categorie, non i singoli numeri, e non ho
modo di dirti «quel 1,8 kn diventa 2,3». Quei numeri li ricostruisce solo una
corsa sul tuo Mac.

---

## 5. Cosa serve da te, e cosa resta da misurare

Il codice è pronto; **i numeri non ci sono ancora**, e non posso produrli da
qui: questo ambiente non ha accesso ai domini dei dati. Tutto ciò che ho
mostrato sopra è meccanica verificata su mondi sintetici a regola nota.

Sul tuo Mac, nell'ordine:

```
python3 -m gardawind --backfill      # aggiunge ERA5 e i predittori per scadenza
python3 -m gardawind --validate --validate-json validazione.json
python3 -m gardawind --bands         # quale taglio di fascia regge davvero
```

Il primo comando scarica gli archivi delle run precedenti (7 scadenze × 2 punti
× 6 punti di contesto): è la parte lunga, e parte dal 2024 perché l'archivio non
va più indietro. **Le scadenze lunghe avranno sempre meno giornate delle corte:
è un limite dei dati, e finché le giornate non bastano quelle scadenze restano
dichiarate non validate.**

Poi mandami l'output di `--validate`, e la tabella per spot × regime × scadenza
— quella vera, con i tuoi quattordici anni — la leggiamo insieme.

Quel che mi aspetto, e lo scrivo prima di vederlo così è verificabile: il Pelèr
di Torbole a D+0/D+1 promosso su entrambi gli stadi; l'Ora più difficile sulla
probabilità che sull'intensità; da D+4 in avanti poche fasce promosse e diverse
righe marcate `ns`. Se andrà diversamente, lo dirò.

---

## 6. La regola di prodotto sulle etichette

Implementata (`gardawind/confidence.py`), e costruita sui benchmark nuovi come
avevi chiesto. Due livelli distinti, separati anche nel codice:

**Scadenza** — fatto di calendario, in italiano, senza sigle: *Oggi, Domani,
Dopodomani, Tra 3 giorni…* Nessun `D+2` raggiunge l'interfaccia, e un test lo
verifica.

**Affidabilità** — quattro livelli, derivati dalle misure di **quella** scadenza
su **quello** spot: *alta affidabilità · buona affidabilità · tendenza ·
outlook*.

Il legame «tre giorni quindi tendenza» non esiste, ed è il punto. Nel test:
a D+2 il Pelèr di Torbole con buone metriche prende *alta affidabilità*, l'Ora di
Malcesine con metriche scarse prende *tendenza* — **stessa scadenza mostrata,
etichetta diversa**. E lo stesso spot a D+6, se le misure reggono, non viene
declassato per la sola distanza.

Una scala a scendere, non una somma pesata: si parte dall'alto e si scende al
primo requisito che manca, **annotando quale**. Una somma darebbe un numero
unico in cui un timing disastroso si compensa con una bella calibrazione. I
requisiti guardano tutte e sette le cose che hai elencato: giornate di verifica,
skill contro il riferimento (con il bootstrap), calibrazione, errore di
intensità, errore di orario, dispersione fra modelli, regime ambiguo.

L'errore di intensità non è confrontato con una soglia in nodi scelta a caso ma
con il **margine di decisione** dello spot — la distanza fra «il regime è
entrato» e «si plana», 3 kn a Torbole. Un errore più piccolo di quel margine non
cambia la scelta di andare; più grande, la cambia.

Sulle soglie che separano i quattro livelli sono esplicito, perché ho appena
finito di togliere numeri inventati e non voglio reintrodurne di nascosto:
**sono soglie editoriali, non stime.** Dove tagliare fra «alta» e «buona» è una
scelta di prodotto. Sono ancorate a qualcosa di reale (guadagni relativi ai
riferimenti, margine di decisione in nodi) e dichiarate in un posto solo, e i
numeri grezzi restano sempre visibili in diagnostica. Se un taglio ti sembra
sbagliato si sposta in una riga.

In pagina, per ogni sessione:

```
Domani                          ← scadenza, in parole
Alta affidabilità               ← derivata dalle misure di D+1 su questo spot
Pelèr 78%
16–20 kn
Finestra migliore 08:10–10:20
```

e dove non si sa:

```
Tra 3 giorni
Tendenza
Ora 54%
14–18 kn
Timing ancora incerto
```

I minuti sono interpolati, non inventati: il profilo è orario ma la curva del
vento è continua, e l'istante in cui attraversa la soglia si stima fra l'ora
sotto e l'ora sopra. Arrotondati a dieci minuti, perché 08:07 suggerirebbe una
precisione al minuto che l'interpolazione non ha. E **compaiono solo dove lo
stadio dell'orario è stato validato a quella scadenza**: un «08:10» accanto a
un'incertezza di due ore sarebbe precisione finta proprio dove il modello sa
meno. Altrove: «timing ancora incerto».

L'intestazione del giorno prende il livello **più basso** fra le sessioni
mostrate: letta da sola verrebbe presa per un giudizio sul giorno, e non può
promettere più della riga più debole.

La parte tecnica sta in diagnostica, come chiedevi: una tabella per spot ×
scadenza con giorni provati, MAE, grezzo, Brier, climatologia, errore di
calibrazione, errore di orario, guadagno con intervallo bootstrap, e le righe
non significative marcate `ns`.

---

## 7. Cosa NON è stato fatto

Perché un elenco di cose fatte senza il suo complemento è una mezza verità:

- **La tassonomia dei regimi non è ancora nel prodotto.** `regimes.py` è scritto
  e testato (13 verifiche) e classifica le giornate osservate — Pelèr, Ora, NO,
  settentrionale/meridionale sinottico, O, E, variabile, calma — ma serve ancora
  solo a `--validate`. L'interfaccia continua a parlare di Ora e Pelèr.
  Il nome locale resta un'ipotesi annotata, come avevi chiesto: *«compatibile
  con il Balinot»*, mai «Balinot».
- **Il settore direzionale non è ancora stato scelto sui tuoi dati.** Lo
  strumento c'è (`sector_study`, con la variazione per stagione), il ±45° del
  Pelèr è argomentato ma non ancora validato sui quattordici anni.
  `REGIME_SECTOR_DEG` in `config.py` è ancora 70 per la definizione del
  bersaglio: cambiarlo ridefinisce «instaurato» e va fatto **con** la
  rivalidazione, non prima.
- **Il blocco cieco non è stato aperto.** 240 giorni finali che non entrano in
  nessuna scelta. Si aprono una volta sola, quando le fasce saranno stabili. Non
  prima, e non due volte.
- **`--validate` non è mai girato su dati veri.** Vedi §5.

---

## 8. File

| File | Cosa |
|---|---|
| `gardawind/validate.py` | forward chaining, λ annidato, calibrazione nei fold, metriche per scadenza, bande empiriche, bootstrap, `fit_band`, `band_study` |
| `gardawind/confidence.py` | **nuovo** — scadenza in parole e affidabilità dalle misure |
| `gardawind/regimes.py` | tassonomia dei regimi osservati, studio dei settori |
| `gardawind/features.py` | `persist_obs` + `persist_age` al posto di `persist` |
| `gardawind/model.py` | `pava` con blocchi di ampiezza minima, calibrazione progressiva, promozione per stadio, moltiplicatori rimossi |
| `gardawind/engine.py` | archivio per scadenza, campioni per scadenza, un modello per fascia |
| `gardawind/web.py` | etichette in parole, distintivi di affidabilità, tabella per scadenza in diagnostica |
| `gardawind/__main__.py` | `--validate`, `--bands`, `--validate-json` |
| `test/t_lead.py` | 26 verifiche: memoria all'età giusta, archivi separati, fasce distinte |
| `test/t_validate.py` | 33 verifiche: proprietà del forward chaining, blocco cieco, bande crescenti |
| `test/t_fiducia.py` | 29 verifiche: etichette dalle misure, non dall'orizzonte |
| `test/t_regime.py` | 13 verifiche: tassonomia e settori |
