# Strade chiuse

Le idee che sembravano giuste e che i dati hanno rifiutato, con il numero che
le ha rifiutate. In fondo, le **aperte**: quelle con il protocollo già scritto
e i numeri non ancora guardati — che è l'unico ordine in cui si può dire di
aver provato qualcosa. Questo file esiste perché un'idea plausibile bocciata senza
traccia scritta torna: fra sei mesi ha lo stesso aspetto convincente di oggi, e
la si riprova da zero.

Regola di questo file: si scrive **cosa** è stato provato, **come** è stato
deciso prima di guardare il risultato, e **quale numero** ha chiuso la porta.
Non si scrivono impressioni.

---

## Allineare gli analoghi sull'ora d'ingresso

**L'idea.** Prima di mediare le curve delle giornate analoghe, traslarle così
che il loro ingresso coincida, per non smussare il gradino.

**Perché sembra giusta.** La mediana di tre gradini sfasati è una rampa. Se si
allineano, il gradino sopravvive.

**Perché è sbagliata su questo lago.** Ci sono due regimi in momenti diversi
della giornata. Allineare sull'ingresso sovrappone il picco del mattino di una
giornata di Pelèr a quello del pomeriggio di una giornata di Ora, e distrugge
la struttura a due gobbe che è tutto il senso della curva.

**Il numero.** Colpi dal 74,5% al 61,2%; errore sull'ora d'ingresso da 70 a 96
minuti. Rifiutata.

---

## Il MAE come metrica per scegliere la forma della curva

**L'idea.** Confrontare le curve candidate con l'errore assoluto medio, che è
la metrica standard.

**Perché è sbagliata.** Il MAE è minimizzato dalla media condizionata, che è
più piatta di qualunque giornata reale: la media di un processo a gradino è una
forma che non esiste. Quindi il MAE premia sempre la previsione moscia, e
misurando con quello la curva liscia vince per costruzione.

**Il numero.** Con il MAE la curva liscia vinceva; con le metriche decisionali
la stessa curva liscia manca il 47% delle giornate navigabili e promette 94
minuti in meno del vero. Le metriche giuste sono colpi, falsi allarmi, minuti
sopra soglia e ripidezza — mai il MAE, per la forma.

---

## Il nowcast intraday

**L'idea.** Correggere la curva del pomeriggio con le osservazioni del mattino.

**Il numero.** Contro la persistenza pura non guadagna. Il banco resta (il
comando `--nowcast-validazione` e il modulo `nowcast.py`), ma non tocca il
prodotto: se un giorno i dati cambiassero idea, si rimisura senza riscrivere
niente.

---

## Le condizioni NOTTURNE per scegliere gli analoghi del Pelèr

**L'idea.** Le dieci variabili che scelgono le giornate analoghe sono tutte
aggregati del giorno — radiazione totale, nuvolosità 08–16, massima, gradiente
di pressione 09–17 — e della notte c'è solo il vento medio 00–06. Ma il Pelèr è
un vento notturno: scende quando l'aria si raffredda e il gradiente lungo il
lago si inverte, fra mezzanotte e l'alba. Ipotesi: nella sua finestra la forma
non discrimina perché la stiamo scegliendo con i numeri del pomeriggio.

**Come è stato deciso, prima di guardare.** Quattro insiemi di predittori,
tutti a dieci dimensioni perché una distanza euclidea in undici non è
confrontabile con una in dieci: l'attuale; uno notturno (gradiente 00–06 e
04–08, nuvolosità notturna, minima, inversione termica rispetto alla massima
del giorno prima, vento notturno in componenti, raffica massima notturna); lo
stesso con la radiazione del giorno prima al posto della minima; e uno misto.
`k` fermo a 3. Si sceglie sul 2024 quello col vantaggio più alto — colpi meno
falsi allarmi — nella finestra utile del Pelèr a 10 kn, e poi si riporta la
conferma sul 2025-2026, mai guardato.

**Il numero.** Sul 2024 l'insieme notturno vince: vantaggio +29,0 contro +25,0
dell'attuale. Sulla conferma perde: **+18,9 contro +23,0**. La differenza fra i
due sulla conferma è +4,2 punti a favore dell'attuale, con intervallo al 95%
da −4,2 a +12,8: **include lo zero**. Cioè non si distinguono. L'ipotesi non è
confermata, e il vantaggio del 2024 era rumore.

**Non riprovare aggiungendo variabili finché una funziona.** Ogni candidata in
più aumenta la probabilità che una vinca per caso sul campione di selezione, ed
è esattamente il meccanismo che ha prodotto il +29,0 qui sopra. Se un giorno si
riapre questa strada, serve un'ipotesi fisica nuova dichiarata prima, non un
altro giro di predittori.

**E un risultato che vale più dell'ipotesi.** Lo stesso bootstrap dice che
nella finestra del Pelèr il vantaggio della forma analogica sul proprio nullo è
**+10,1 punti, intervallo da +0,3 a +20,3**: appena sopra lo zero. Con le
notturne è +3,9, intervallo da −6,3 a +13,8: sotto. E la curva liscia, nella
stessa finestra, fa +22,3 contro i +23,0 dell'analogica — statisticamente la
stessa cosa.

Quindi nella mattina la forma **non discrimina**, e non è una questione di
predittori: è così. Quello che l'analogica porta al Pelèr è la calibrazione —
sbilanciamento +8 minuti contro −46 della liscia, ripidezza 3,58 contro 0,25 su
una vera di 3,89 — e quello vale, perché è ciò che la scheda legge e stampa.
Quale mattina sarà di Pelèr lo decide il **livello**, che viene dalla previsione
della sessione: è l'unica parte validata, ed è quella che migliora con i dati
che si raccolgono.

È anche la ragione per cui la porta, sulla mattina, pretende calibrazione e non
pretende colpi. Quella scelta non era prudenza: era già il risultato.

---

## La SCELTA dei vicini come merito della forma (anche nell'Ora)

**L'idea.** Dieci predittori scelgono le tre giornate storiche più simili, e
quella scelta è il cuore del metodo: se si scegliessero tre giornate a caso la
curva sarebbe peggiore.

**Perché sembrava vera.** Con l'ancora sbagliata lo era: il modello faceva
52,9 punti di vantaggio contro 37,1 del nullo, quindici punti e mezzo. La
porta li pretendeva (`GUADAGNO_MIN_SU_NULLO`).

**Il numero, con l'ancora giusta.** Nella finestra dell'Ora, sul blocco cieco
di 617 giornate, regalando a tutti il livello vero — che è il massimo delle
medie orarie, la grandezza che il motore prevede:

| | colpi | falsi | e.min | sbil. | ripidezza |
|---|---|---|---|---|---|
| curva liscia | 98,1% | 6,5% | 67 | +42 | 1,86 |
| D+1 | 90,1% | 7,0% | 59 | −5 | 6,19 |
| D+4 | 92,8% | 6,0% | 64 | −1 | 6,49 |
| **nullo** | **92,1%** | **4,5%** | 74 | −25 | 6,35 |

vera 6,99. Vantaggio D+1 meno nullo: **−4,4 punti, intervallo da −9,6 a +0,1:
include lo zero.** Cioè non si distinguono, e il segno è pure quello
sbagliato. Lo scarto di ripidezza dal vero, D+1 meno nullo, è −0,1 con
intervallo da −0,5 a +0,2: anche lì zero.

**Cosa vuol dire.** Quello che la forma analogica porta non viene dalla
scelta dei vicini: viene dall'essere **una curva vera del lago** invece di una
media. Una giornata a caso di questo lago ha un gradino, un plateau e un
crollo; la media di trent'anni di giornate no. La ripidezza 6,3 su una vera di
6,99 la prende anche il nullo; la media mensile fa 1,86.

Era già scritto per la mattina (vantaggio sul nullo +10,1, intervallo da +0,3
a +20,3, appena sopra lo zero). Adesso lo dice anche il pomeriggio, e con
l'ancora giusta lo dice più forte. **Il livello decide se, la forma decide
come — e "come" non ha bisogno di sapere quale giorno è.**

**Cosa NON segue da qui.** Non segue che i dieci predittori vadano buttati:
servono per prendere la forma del mese e della stagione giusta, e il nullo del
test li usa comunque, perché rimescola le giornate del 2025-2026 fra loro e
non con quelle di gennaio. Segue che la porta non può pretendere
discriminazione da una cosa che non ne ha, in nessuna delle due finestre — e
che il posto dove cercare colpi è il **livello**, non la sagoma.

---
---

# Aperte, con il protocollo già dichiarato

## `k` rimisurato con l'ancora giusta

*Dichiarata il 2026-09-17, prima di qualunque numero. Il protocollo è scritto
qui e messo nel repository **prima** di lanciare la misura.*

**Perché si riapre.** `k = 3` era stato scelto con l'ancora sbagliata, e la
regola pre-registrata di allora — falsi entro il 20% in selezione — sotto la
normalizzazione giusta non selezionava niente (il k migliore sul 2024 faceva
27,2% di falsi). Con l'ancora oraria i falsi allarmi crollano al 7%: il
vincolo che aveva bloccato la scelta non è più vincolante, e `k` non è mai
stato misurato nelle condizioni in cui il prodotto funziona adesso.

**Perché `k` e non altro.** `k` è l'unico parametro che governa la
**larghezza** della sagoma, ed è esattamente la dimensione su cui l'analogica
perde: la curva liscia prende 8 punti di colpi in più (98,1% contro 90,1%) e
li paga con una durata promessa di 42 minuti più lunga del vero. Trentatré
delle 416 giornate navigabili l'analogica le manca, e non sono giornate al
confine: la mediana dei minuti veri sopra 12 kn, su quelle trentatré, è
**120**. Sono giornate con due ore di vento dette non navigabili. Una mediana
su più vicini è più larga e meno spigolosa: dovrebbe prenderne una parte.

**Il criterio, deciso adesso.** `k` fra 3, 5, 7, 9, 11, 15. Si sceglie sul
**2024** quello con i **colpi più alti** nella finestra dell'Ora a 12 kn,
sotto due vincoli entrambi obbligatori:

1. falsi allarmi **≤ 15%** — il budget dichiarato da Gian;
2. **|sbilanciamento della durata| ≤ 15 minuti**.

Il secondo vincolo è il motivo per cui questa misura si può fare senza
imbrogliare. Senza di lui la risposta è nota in partenza: `k` grandissimo
riporta la sagoma alla media climatologica, cioè alla curva liscia, che vince
sui colpi **perché** promette quarantadue minuti di troppo. Il vincolo
proibisce di ricomprare i colpi con la stessa bugia.

A pari colpi decide lo scarto mediano fra ripidezza promessa e ripidezza vera,
più piccolo è meglio.

La conferma sul 2025-2026 si guarda **dopo**, una volta sola. Se il `k`
vincitore non batte `k = 3` sulla conferma, `k` resta 3 e qui sopra si scrive
che è stato provato.



## Il gradiente SINOTTICO per scegliere la forma

*Dichiarata il 2026-09-17, prima di qualunque numero.*

**Da dove viene.** Da un altro progetto sullo stesso lago
(`github.com/cesareprimultini/garda-wind`), che usa il ΔP Bolzano–Ghedi con le
tabelle di profiwetter.ch. È l'indicatore operativo classico dell'Ora.

**Cosa abbiamo già.** Il modello del livello lo usa, e in forma più generale:
`features.pgrad` è la pressione media di Bolzano, Trento e Merano meno quella
di Brescia, Verona e Mantova — sei punti su 150 km invece di una coppia — più
`features.tgrad`, il contrasto termico pianura-valle, che è il motore vero
della brezza di lago e che loro non hanno.

**Il buco vero.** La selezione degli **analoghi** non lo vede. Il suo unico
gradiente è `dp_lago`: nord del lago meno sud del lago, quindici chilometri,
media 0,033 hPa con dispersione 0,12. Un sussurro. E non è una scelta: è che
`analogs.py` legge `arch_hour`, dove ci sono i due punti del lago, mentre il
contesto sinottico vive in `ctx_hour`.

**L'ipotesi, in una frase.** Quale regime vince, e quando si passano la mano, è
deciso dal gradiente attraverso le Alpi, non da quello lungo il lago. Quindi
sostituire `dp_lago` con il gradiente sinottico dovrebbe migliorare la
selezione dei vicini — e in particolare la **mattina**, dove oggi la forma non
discrimina (vantaggio sul nullo +10,1 punti, intervallo da +0,3 a +20,3).

**Il protocollo, deciso adesso.** Quattro candidate a dieci dimensioni, `k`
fermo a 3:

1. l'attuale;
2. l'attuale con `pgrad_giorno` al posto di `dp_lago`;
3. l'attuale con `pgrad_notte` e `dp_variazione` al posto di `dp_lago` e
   `wnotte` — `dp_variazione` è `pgrad_giorno − pgrad_notte`, cioè di quanto il
   gradiente **gira** nella giornata, e non l'abbiamo mai misurato;
4. l'attuale con `pgrad_alba` e `tgrad_max` al posto di `dp_lago` e `tmax`.

Si sceglie sul 2024 quella col vantaggio più alto nella finestra del Pelèr a
10 kn; la conferma sul 2025-2026 si guarda **dopo**. Se la vincitrice non batte
l'attuale sulla conferma, la risposta è no e si scrive qui sopra, come per le
notturne.

**Cosa serve prima.** `ctx_hour` con `kind='era5'` che copra il 2012-2023: la
libreria degli analoghi vive in quegli anni, e senza il contesto storico non
c'è niente da confrontare. `backfill_era5_features` lo scarica già su tutti e
sei i punti — va verificato che ci sia arrivato davvero.

**Una nota che vale più dell'ipotesi.** Ogni sorgente si standardizza sulla
propria distribuzione, e `ctx_hour` tiene `era5`, `arch` e `live` nella stessa
tabella. Mescolarle sarebbe lo stesso errore che ci è costato due giorni sulla
normalizzazione della sagoma.

**Aggiornamento del 2026-09-17, e cambia il senso della prova.** Questa
ipotesi era nata per curare i falsi allarmi al 36%, letti come un problema di
**selezione** dei vicini. Quella premessa è caduta: i falsi allarmi erano
l'ancora sbagliata, e con l'ancora oraria scendono al 7% senza toccare i
predittori. Peggio, per questa ipotesi: la scelta dei vicini non discrimina
meglio del caso in nessuna delle due finestre (vedi la strada chiusa qui
sopra), quindi un predittore migliore non ha un difetto da riparare — non c'è
un vantaggio sul nullo da aumentare, perché non c'è un vantaggio sul nullo.

Resta provabile, e vale la pena solo così: non come cura per i falsi allarmi,
ma come **la** domanda a cui il gradiente sinottico può rispondere — se la
selezione dei vicini possa discriminare qualcosa, visto che oggi non lo fa.
Il protocollo sopra resta valido parola per parola; cambia il criterio di
successo, che adesso è uno solo: **battere il nullo**, con l'intervallo che
non include lo zero. Se non lo batte, la selezione della forma è una questione
chiusa e il posto dove lavorare è il livello.
