# Strade chiuse

Le idee che sembravano giuste e che i dati hanno rifiutato, con il numero che
le ha rifiutate. Questo file esiste perché un'idea plausibile bocciata senza
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
