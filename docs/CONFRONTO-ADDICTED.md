# Quanto sbaglia Addicted, sul nostro bersaglio

Prima misura di un concorrente. Fatta il 19/09/2026 su **96 giornate**
(15 giugno – 18 settembre 2026), tre stazioni, con
`strumenti/confronto-addicted.py`.

Perché era necessaria: i numeri della diagnostica dicono quanto siamo meglio
di **noi stessi senza modello** — la mediana climatologica e il vento grezzo
d'ensemble. Non dicono niente su chi altro c'è. Gian: *"quanto siamo efficaci
rispetto ai competitors?"*, e la risposta onesta era "non lo sappiamo".

Addicted rende il confronto possibile come nessun altro sito: nella stessa
risposta pubblicano la **loro previsione oraria** (`avg`) e la **misura della
stessa ora** (`mavg`), giorno per giorno, anche all'indietro.

---

## Il protocollo, dichiarato prima di guardare

1. **Il bersaglio è il nostro**: il picco della media oraria dentro la finestra
   del regime. Il loro MAE dichiarato — 1,3 kn a Torbole, che ho ricalcolato e
   viene 1,28, quindi il loro numero è onesto — è su **tutte le 24 ore**, notte
   compresa. Le ore di notte sul Garda sono 0–2 kn: sono le ore in cui
   sbagliare è difficile, e mediarle dentro abbassa l'errore di chiunque.
   Confrontare quel numero con il nostro sarebbe confrontare due esami diversi.
2. **Solo le giornate entrate**, cioè con il picco misurato sopra la soglia del
   regime. Sbagliare una giornata senza vento non interessa a nessuno.
3. **Tutto sulla scala Meteotrentino**, con la curva misurata su 62.847 ore con
   i due strumenti fianco a fianco a Torbole — perché i nostri numeri sono su
   quella scala. Il bias si riporta **anche sulla scala loro**, non convertita:
   serve a escludere che sia la nostra conversione a produrre ciò che troviamo.
4. **Il bias tolto in leave-one-out**: per ogni giornata si corregge con la
   mediana degli errori di tutte le altre. Correggere con una mediana che
   include il giorno da prevedere è sbirciare la risposta.

---

## I numeri

Nodi sulla scala Meteotrentino. «senza bias» = il loro MAE dopo aver tolto il
bias in leave-one-out, cioè la loro **abilità** separata dalla loro
**taratura**. «mancate» = giornate misurate sopra i 14 kn (la soglia del "si
plana") che la loro previsione dava sotto.

| stazione | regime | n | MAE | bias | bias (scala loro) | senza bias | climatologia | mancate | falsi |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Torbole | Ora | 87 | 1,55 | −1,23 | −1,13 | **1,23** | 1,31 | 22 su 72 | 2 |
| Torbole | Pelèr | 61 | 1,42 | −1,17 | −1,04 | **1,04** | 1,35 | 9 su 9 | 0 |
| Malcesine | Ora | 79 | 1,84 | −1,40 | −1,44 | **1,31** | 2,01 | 23 su 53 | 3 |
| Malcesine | Pelèr | 81 | 1,63 | −0,39 | −0,61 | 1,62 | 2,94 | 6 su 52 | 10 |
| Campione | Ora | 81 | 2,78 | −2,33 | −2,23 | **2,07** | 2,08 | 22 su 63 | 6 |
| Campione | Pelèr | 83 | 1,44 | −1,35 | −1,35 | **1,06** | 1,08 | 7 su 9 | 0 |

## Cosa dicono

**1. Sottostimano, sempre, ovunque.** Il bias è negativo in tutte e sei le
righe, e resta negativo anche sulla scala loro — quindi non è un effetto della
nostra conversione. A Torbole sono 1,1 kn, a Campione 2,2.

**2. L'errore cresce con il vento.** A Torbole, sull'Ora: bias −0,57 fra 11 e
14 kn, −1,02 fra 14 e 17, **−2,69 sopra i 17**. È la firma classica di un
modello poco disperso: la previsione si muove meno del vento vero, quindi
sbaglia poco nelle giornate medie e molto in quelle forti — che sono proprio
quelle per cui uno guarda la previsione.

**3. Il costo, in giornate.** Sull'Ora, un'estate: **22 giornate planabili su
72 date sotto i 14 kn** a Torbole, 23 su 53 a Malcesine, 22 su 63 a Campione.
Circa una buona su tre. Falsi allarmi quasi nessuno (2, 3, 6). È una previsione
**prudente**: non ti delude quasi mai, ma ti lascia a casa un giorno buono su
tre.

**4. L'informazione c'è: è la taratura che la butta via.** Togliendo il solo
bias, il loro MAE scende da 1,55 a 1,23 sull'Ora di Torbole, da 1,42 a 1,04 sul
Pelèr, da 2,78 a 2,07 a Campione. Un quinto-un terzo dell'errore è taratura,
non previsione. Con una retta (pendenza e quota) a Torbole si scende a 1,11, e
la pendenza stimata è **0,59**: la loro previsione copre poco più della metà
dell'escursione vera.

Questa quarta riga è, misurata su un altro, esattamente la tesi del progetto:
**il modello grezzo sa più di quello che dice, e quello che gli manca è la
storia misurata della centralina.**

---

## Cosa questi numeri NON dicono

Va scritto accanto a ogni volta che si citano.

- **Non è ancora un confronto diretto con noi.** Il nostro MAE pubblicato
  (1,74 sull'Ora di Torbole, 1,32 sul Pelèr) è misurato fuori campione su circa
  1.800 giornate che comprendono l'inverno, e sulla finestra **utile**. Questo è
  su un'estate e sulla finestra del **regime**. L'estate è la stagione facile e
  la finestra utile è più stretta: i due numeri non si possono affiancare.
  Per il confronto stretto servono le stesse giornate e la stessa definizione.
- **Non sappiamo a quale scadenza** fosse emessa la previsione che loro
  ripubblicano per i giorni passati. Se fosse una previsione a poche ore, il
  loro compito era più facile del nostro a tre giorni. Il bias sistematico
  suggerisce che non sia un ricalcolo col senno di poi — un ricalcolo non
  avrebbe un bias — ma è un indizio, non una prova.
- **Il verdetto è il nostro, non il loro.** "Buone mancate" usa la nostra soglia
  dei 14 kn applicata al loro numero. Loro pubblicano un verdetto proprio
  (`guete`: *kein, wenig, surfbar, big*), ed è quello che il loro utente legge.
  Misurare **il loro verdetto** invece della nostra rilettura è il passo
  successivo, e i dati per farlo sono già nella stessa risposta.
- **Un'estate, tre stazioni.** Il Pelèr di Torbole ha solo 9 giornate sopra i
  14 kn nel periodo: "9 mancate su 9" è vero e quasi privo di valore statistico.

## Le due cose da fare

1. **Il confronto in avanti.** Archiviare ogni giorno la loro previsione a
   scadenza dichiarata (D+1, D+2, D+3), come già facciamo con le nostre fasce.
   Dopo due mesi il confronto è a prova di obiezione, ed è l'unico modo
   possibile anche per Windguru e Windy, che un archivio non lo pubblicano.
2. **Il nostro errore sulle stesse giornate.** Serve la previsione fuori
   campione delle nostre giornate estive con la definizione di finestra del
   regime. I valori esistono dentro l'addestramento (le stime out-of-fold) ma
   non vengono conservati: conservarli è un lavoro piccolo e rende il confronto
   immediato per sempre.
