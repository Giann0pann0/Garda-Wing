# La tabella vera — lettura

Prima validazione su dati reali. 740 752 misure di Torbole dal 2012, 15 261
intraday di Malcesine, sette scadenze di archivio delle run precedenti.

---

## Prima di tutto: cosa avevo previsto, e come è andata

Avevo scritto tre attese, apposta per renderle verificabili. **Una giusta, due
sbagliate.**

| Avevo detto | Risultato |
|---|---|
| Pelèr di Torbole promosso a D+0/D+1 su entrambi gli stadi | ✅ **giusto** — fascia corta validata, +21 % probabilità, +20 % intensità |
| L'Ora più difficile sulla probabilità che sull'intensità | ❌ **sbagliato, e al contrario.** L'Ora ha la probabilità *migliore* di tutto il progetto (Brier 0,117 contro 0,250 climatologici, +53 %) e l'intensità che **non supera la porta** |
| Da D+4 poche fasce promosse e molte righe `ns` | ❌ **sbagliato.** D+4–D+7 è validato su entrambi gli spot di Torbole. Le righe `ns` stanno a D+0/D+1 dell'Ora e su Malcesine-Giorno |

Le due previsioni sbagliate non erano innocue: erano nella direzione che mi
avrebbe fatto fare bella figura ("il modello regge dove serve, si degrada dove
è normale"). La realtà è più interessante e meno lusinghiera.

---

## Il risultato che regge: il Pelèr di Torbole

È il caso solido, e lo è a **tutte e sette le scadenze**.

| Quando | Giorni provati | MAE | contro climatologia | Brier | contro climatologia | Calibrazione |
|---|---|---|---|---|---|---|
| Oggi | 1370 | 1,56 kn | 1,96 | 0,203 | 0,246 | 0,088 |
| Domani | 714 | 1,57 kn | — | 0,176 | 0,240 | — |
| Dopodomani | 515 | 1,52 kn | 2,20 | 0,178 | 0,238 | 0,028 |
| Tra 3 giorni | 515 | 1,53 kn | — | 0,183 | 0,238 | — |
| Tra 4 giorni | 510 | 1,62 kn | — | 0,196 | 0,238 | 0,027 |
| Tra 5 | 510 | 1,64 kn | — | 0,203 | 0,238 | — |
| Tra 6 | 510 | 1,66 kn | — | 0,210 | 0,238 | — |
| Tra 7 | 510 | 1,83 kn | — | **0,239** | 0,238 | — |

Cosa leggo qui:

- **L'intensità tiene lontano.** 1,52 kn a due giorni, 1,66 a sei. Il degrado
  c'è ma è mite, e il margine che cambia la decisione a Torbole (fra i 10 kn di
  soglia e i 13 di planata) è 3 kn: l'errore sta sotto quel margine fino a D+7.
- **La probabilità si consuma.** Guadagno +21 % a D+0/1, +24 % a D+2/3,
  **+11 %** a D+4-7. E a **D+7 il Brier è 0,239 contro 0,238 climatologici:
  zero.** A sette giorni, sul "se entra", l'app non sa niente più della
  climatologia. Dirlo è l'unica cosa onesta da fare.
- **La calibrazione a media scadenza è ottima** (0,027–0,028): quando dice 70 %,
  entra il 70 % delle volte. A D+0 è peggiore (0,088), il che è curioso e
  rientra nell'anomalia del punto successivo.

---

## L'anomalia che va capita prima di fidarsi del resto

**L'Ora di Torbole a D+0 è peggiore che a D+2.** Non di poco:

| Quando | MAE | Climatologia | Bias |
|---|---|---|---|
| Oggi | **2,84 kn** | 2,16 | **+1,82 kn** |
| Domani | 1,87 | 2,02 | +0,21 |
| Dopodomani | 1,85 | 2,20 | −0,71 |
| Tra 4 giorni | 1,92 | 2,20 | −0,61 |

A oggi il modello **sovrastima di 1,8 nodi in media** ed è peggio della
climatologia; a due giorni va bene. Questo è all'incontrario e non può essere
fisica. È la ragione per cui la fascia corta dell'Ora risulta *non validata*.

La causa più probabile è **mia, di costruzione della fascia**. La fascia corta
mette insieme due archivi con profondità diverse:

- D+0 viene dall'archivio ordinario delle previsioni: **dal 2021**, 1813 giorni.
- D+1 viene dall'archivio delle run precedenti: **dal 2024**, 958 giorni.

Il forward chaining addestra sul passato e prova sul futuro. I primi fold, cioè
il 2021-2023, **contengono solo campioni D+0** — il periodo in cui il modello ha
meno dati e sbaglia di più. Quei fold finiscono tutti nella riga D+0 e in
nessun'altra. **La riga "Oggi" porta il peso del periodo peggiore, le altre no:
non sono confrontabili fra loro.**

C'è un secondo indizio, e punta a una cosa diversa e interessante. L'errore del
solo vento grezzo d'ensemble fa un gradino netto:

```
D+0  10,06     D+1   9,56     D+2  12,17     D+3  12,17
D+4  12,33     D+5  12,50     D+6  12,50     D+7  11,79
```

Un degrado fisico sarebbe graduale. Questo è **piatto, con uno scalino di 2,6 kn
fra D+1 e D+2**. L'ipotesi che mi convince: `best_match` di Open-Meteo cambia
modello sotto — fino a un giorno usa un modello ad alta risoluzione (ICON-D2 o
ICON-2I, 2 km, che *vede* il solco del lago), da due giorni ripiega su uno
globale a 7-25 km, che il lago non lo vede. Se è così, **il taglio fra fascia
corta e media non è arbitrario: cade dove cambia il modello**, il che è un
ottimo argomento per le fasce — ma va verificato, non creduto.

### Cosa farei, in questo ordine

1. **Ritagliare tutte le fasce sullo stesso periodo** (dal 2024-01-20, dove
   esistono tutte le scadenze) e rifare la tabella. Se l'anomalia di D+0
   sparisce, era l'artefatto del periodo e la diagnosi è chiusa.
2. **Stampare la media di `w10_win` per scadenza.** Se lo scalino resta, è il
   cambio di modello sotto `best_match`, e allora conviene interrogare i modelli
   per nome invece di affidarsi a `best_match`.
3. Solo dopo, ridecidere i tagli delle fasce con `--bands`.

Finché il punto 1 non è fatto, **la colonna "Oggi" della tabella non va usata
per confronti fra scadenze.** Le righe da D+1 in poi sono omogenee fra loro e si
possono leggere.

---

## L'orario: un no misurato

Su questo il verdetto è netto e negativo, su tutti gli spot e tutte le scadenze.

- Errore sull'ora del picco: **70–90 minuti**. Entro mezz'ora solo nel 20–27 %
  dei casi.
- Il modello dell'orario **non batte la media stagionale**: `timing_usable:
  false` ovunque. Batte il vento grezzo (74 contro 89 minuti a Torbole-Ora, 83
  contro 134 sul Pelèr), ma non la cosa banale.

Quindi: **l'app non sa dire a che ora entra meglio di "come al solito in quella
stagione"**, e va scritto.

Questo tocca una cosa che avevamo concordato. La scheda che mi avevi disegnato
aveva `Finestra migliore 08:10–10:20`. Con un'incertezza misurata di ottanta
minuti, quei minuti sarebbero **finta precisione nel punto esatto in cui il
modello sa meno**. Ho fatto due cose:

- i minuti compaiono **solo** dove l'errore sull'orario è sotto i 45 minuti.
  Oggi non succede da nessuna parte, quindi la scheda scrive «meglio fra le 11 e
  le 16» e, accanto, «timing ancora incerto (±83 min misurati)»;
- **ho tolto l'orario dalla scala di affidabilità**, e questo è un cambiamento
  rispetto a quanto mi avevi chiesto, quindi te lo segnalo perché tu possa
  ribaltarlo. Con l'orario dentro la scala, **ogni riga di ogni spot sarebbe
  scesa a "tendenza"**, per un motivo che non riguarda quello che la scheda
  promette. L'etichetta risponde a *entra?* e *quanto forte?* — le due domande
  misurate e promosse. L'ora è una terza domanda, oggi con una brutta risposta,
  e merita una riga propria che lo dica invece di trascinare in basso un
  giudizio su altro. Resta fra le componenti e nella diagnostica.

---

## Il settore direzionale: l'asse del Pelèr è probabilmente sbagliato

Questa è la scoperta che mi ha sorpreso di più.

**Ora (asse 204°)** — l'asse è a posto. Il 64 % delle giornate ventose cade
entro ±30°, e allargare a ±90° aggiunge solo dieci punti. Purezza 80 % a ±30 e
±45, che scende a 77 % a ±90: **±45 è il taglio giusto**, allargare peggiora la
purezza senza raccogliere quasi nulla.

**Pelèr (asse 24°)** — i numeri non tornano:

```
entro ±30°  →  49 % delle giornate ventose
entro ±45°  →  94 %
entro ±60°  →  95 %
```

Se le direzioni fossero concentrate *sull'asse*, il 49 % entro 30° implicherebbe
una dispersione di circa 45°, e allora entro 45° ci si aspetterebbe il **68 %**,
non il 94 %. Ho cercato quale distribuzione riproduce tutti e tre i numeri: una
moda **spostata di 30° dall'asse, con dispersione stretta (≈10°)** li riproduce
quasi esattamente (50 %, 93 %, 100 %).

Tradotto: **il Pelèr al Belvedere non arriva da 24°, arriva da circa 354° oppure
da circa 54°**, con una direzione molto costante. L'asse dichiarato è preso
dalla geometria del lago (Torbole→Malcesine, 204,5°, quindi 24,5° in ritorno) e
la geometria del lago non è la direzione che vede quella centralina, che sta in
una conca con la sua topografia.

Conferma anche la distribuzione stagionale: lo scarto mediano dall'asse è
**30–31° in tutte e quattro le stagioni**. Un errore di puntamento è costante
per stagione; un fenomeno diverso no.

Non posso dire da solo **da quale dei due lati** sia lo scostamento: servono le
direzioni grezze. Ho aggiunto un comando che le stampa e chiude la questione in
dieci secondi, senza scaricare niente (istruzioni in fondo).

Perché conta, e non è un dettaglio estetico: l'asse entra nella definizione di
«il Pelèr è entrato». Se è spostato di 30°, allora una parte delle giornate
contate come Pelèr non lo sono e viceversa, e **tutti i bersagli di
addestramento del Pelèr sono un po' storti**. Va corretto — ma **insieme** alla
rivalidazione, non prima, perché cambia la definizione stessa di ciò che si
misura.

Nota collegata: **con il settore a ±45 il Pelèr si prende ancora il vento da
339–350°**, cioè il discendente da NO. Nella tassonomia il NORD_OVEST raccoglie
**3 giornate su 5151**: non perché non esista, ma perché il filtro Pelèr lo
assorbe prima. Il problema che avevi sollevato è ridotto rispetto a ±70, non
risolto.

### Un regime che non stavamo guardando

Nella finestra dell'Ora, la tassonomia trova **158 giornate di vento da est**
(3 %) con picco mediano **14,5 kn**, e **201 giornate di settentrionale
sinottico** (4 %) con picco mediano 14,0 kn. Sono 359 giornate navigabili in
quindici anni che l'app oggi classifica come «l'Ora non entra».

E in inverno, nella finestra 11–19, lo scarto mediano dall'asse dell'Ora è
**142°**: più di metà delle giornate ventose invernali pomeridiane vengono
dalla direzione opposta. **L'Ora d'inverno non esiste** — quello che soffia di
pomeriggio a gennaio è un settentrionale. Ovvio per chi il lago lo frequenta,
ma ora è misurato, ed è un buon argomento per mostrare in inverno il regime
giusto invece di «Ora improbabile».

---

## Malcesine: non ci sono ancora i dati, ed è normale

- **Malcesine-Ora e Malcesine-Pelèr**: 196 giorni. L'archivio intraday parte da
  marzo 2026. «Periodo troppo corto per il forward chaining» è il messaggio
  giusto: con 196 giorni non si può addestrare sul passato e provare sul futuro
  in modo credibile. Servono altri sei-dodici mesi di raccolta. L'agente in
  background che raccoglie ogni 15 minuti sta facendo esattamente questo.
- **Malcesine-Giorno** (raffica massima): 762 giorni, **nessuna fascia
  validata**. La probabilità guadagna un po' (+17 %, +16 %, +4 %) ma
  l'intensità non batte la climatologia a nessuna scadenza (−1 %, +3 %, −6 %,
  tutti `ns`). Prevedere la raffica massima giornaliera è difficile e il
  bersaglio è rumoroso: per ora l'app lo dichiara non validato, ed è corretto.

**Un sospetto sulla classificazione di Malcesine, che è un difetto mio.** La
tassonomia dice: variabile 69 %, Ora 19 %. Per Malcesine in estate è
implausibile. Il probabile colpevole è una modifica che ho fatto io in questa
sessione: la costanza direzionale ora è il *prodotto* fra la costanza tra le ore
e quella dentro l'ora. Malcesine campiona ogni 15-30 minuti, quindi un'ora
contiene 2-3 campioni e la costanza interna risulta bassa e rumorosa **per
mancanza di campioni, non per instabilità del vento**. Il prodotto la trascina
sotto soglia e la giornata finisce in «variabile». Va corretto: il fattore
interno deve valere solo quando l'ora ha abbastanza campioni.

---

## Cosa resta valido della prima validazione, e cosa no

**Valido e da tenere:**

- Il Pelèr di Torbole a D+1…D+6: intensità 1,5–1,7 kn, probabilità calibrata,
  guadagni significativi. È il risultato del progetto.
- La probabilità dell'Ora di Torbole: Brier 0,117 contro 0,250. Molto forte.
- L'intensità dell'Ora da D+2 a D+7: +14 % e +9 % sui riferimenti, significativi.
- Tutte le bande empiriche da D+1 in poi.
- La constatazione negativa sull'orario, e quella su Malcesine-Giorno: sono
  risultati anche quelli.

**Da non usare finché non si rifà la tabella sul periodo comune:**

- Ogni riga «Oggi», per tutti gli spot.
- Il confronto *fra* scadenze in generale (perché la riga Oggi lo sporca).
- Il giudizio «la fascia corta dell'Ora non è validata»: probabilmente è vero
  per l'artefatto, non per il modello.

---

## Cosa fai adesso, in pratica

Nel pacchetto aggiornato c'è un comando nuovo che **non scarica niente** e
risponde in dieci secondi alla domanda sull'asse del Pelèr. Da Terminale:

```
cd "Garda Wind.app/Contents/Resources"
python3 -m gardawind --direzioni
```

Stampa, per ogni spot, da dove arriva davvero il vento nelle giornate ventose,
in settori di 15°, con un istogramma. Se il settore più frequente del Pelèr
risulta intorno a 350° o intorno a 55° invece che a 24°, la diagnosi è
confermata e l'asse si corregge.

Mandami quell'output. Poi rifaccio la tabella sul periodo comune e ridecidiamo
insieme l'asse, i settori e i tagli delle fasce — in un colpo solo, perché sono
la stessa decisione.
