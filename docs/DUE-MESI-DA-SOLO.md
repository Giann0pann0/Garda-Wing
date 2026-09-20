# Due mesi da solo

Scritto il 20/09/2026, il giorno in cui Gian ha detto che non ci avrebbe messo
mano per un paio di mesi. Non è un riassunto del progetto: è la risposta a una
domanda sola — **cosa succede qui dentro mentre nessuno guarda, e cosa si
guarda al ritorno.**

Vale fino a fine novembre 2026 circa. Dopo, va riletto.

---

## Quello che va avanti da solo

Quattro volte al giorno (03:20, 09:20, 15:20, 21:20 UTC) il giro lungo scarica
le previsioni, legge le centraline, **riaddestra i modelli**, ricostruisce il
sito e salva in `storico/` le serie che non si riscaricano da nessuna parte.
Ogni dieci minuti il giro veloce aggiorna l'«adesso» e il ponte.

Quindi il sistema non si limita a restare acceso: **impara anche da solo**. Fra
due mesi i modelli avranno visto sessanta giorni di misure in più di oggi, e la
pagella dirà un numero vero invece di «mancano N giornate».

---

## Le cose che possono fermarsi, in ordine di probabilità

### 1. GitHub spegne i cron dopo 60 giorni — ed è esattamente la finestra

Sui repository **pubblici**, GitHub disabilita da solo i workflow a orario
quando non c'è attività sul repository per 60 giorni. Il contatore qui lo
tiene vivo una cosa sola: **il commit dell'archivio**, che il giro lungo fa da
sé a ogni passaggio. Finché quel push riesce, il repository ha attività tutti i
giorni e non si spegne niente.

Se invece quel push smette di riuscire, si perdono due cose insieme: l'archivio
resta nella sola cache *e* il repository diventa inattivo. Per questo dal
20/09 il controllo della salute guarda proprio quello, e non «i file ci sono»
(vedi sotto).

**Come te ne accorgi**: la pagina invecchia e continua a dire un'ora nuova.
**Cosa fare**: *Actions* → il workflow nella colonna a sinistra → il pulsante
**Enable workflow**. Poi *Run workflow* per ripartire subito.

### 2. Una fonte cambia pagina e il nostro lettore smette di leggere

È già successo (Limone). Addicted o MeteoProject rifanno il sito, il parser non
trova più i numeri, e **la previsione continua a uscire lo stesso**: è il
guasto più insidioso, perché tutto sembra a posto mentre il metro contro cui ci
correggiamo è fermo.

Da oggi c'è il quarto controllo della salute: se una centralina non dice niente
da più di **quattro giorni**, il pallino diventa rosso e il motivo dice quale.

### 3. Open-Meteo risponde male per giorni

Il primo controllo della salute guarda l'età dell'ultima previsione **davvero
scaricata**. Fino a ieri quel controllo si guardava allo specchio: l'ora veniva
scritta a ogni giro anche quando tutte le richieste erano fallite. Adesso si
scrive solo se almeno un modello è arrivato.

### 3-bis. Un pallino rosso che dura

Se il pallino resta rosso per settimane (per esempio una centralina che chiude
per la stagione), **non si perde niente**: il database di quel giro si salva
comunque — il passo che lo salva ha `if: always()` apposta — e l'archivio
irripetibile viene spinto prima del controllo. Il rosso dice che qualcosa non
torna; non porta via il lavoro del giro.

### 4. La cache di Actions viene sfrattata

Succede e non è grave: `storico/` è dentro il repository e `recupera()` lo
rimette nel database. I quattordici anni di Torbole si riscaricano da soli in
una o due esecuzioni. Nei giorni intermedi il sito pubblica con più
climatologia e meno modello: si vede in diagnostica, alla colonna della fonte.

---

## Il 25 ottobre si cambia l'ora

Il passaggio all'ora solare è stato controllato riga per riga. **Non sposta
niente** di quello che conta: le chiavi del database sono in UTC, le finestre
dei regimi si calcolano sull'ora locale vera (non con un «più due» scritto a
mano), e l'ora doppia delle 02:00 del 25 ottobre è gestita apposta per le fonti
che pubblicano l'orologio da parete — senza quella gestione un'ora di misure si
sarebbe sovrascritta.

L'unica cosa che cambia: i quattro giri, che sono fissati in UTC, da quel
giorno cadono un'ora prima in orario italiano (04:20, 10:20, 16:20, 22:20). Il
giro di mezzogiorno arriva quindi un po' più «vecchio» rispetto all'Ora del
pomeriggio. È voluto: i modelli globali escono in UTC, e inseguire l'orologio
italiano vorrebbe dire scaricare prima che i dati esistano.

---

## La stagione gira, e la pagina lo dirà

Da ottobre l'Ora si spegne e il Pelèr diventa il vento della giornata. I voti
caleranno, e **è giusto che calino**: se a novembre la pagina dicesse
«fantastico» come ad agosto vorrebbe dire che non guarda il vento.

Una cosa da sapere, detta per intero: i modelli **appresi** la stagione la
conoscono (hanno il giorno dell'anno fra gli ingredienti). La **climatologia di
ripiego** — quella che entra quando per uno spot il modello non è promosso —
no: usa la media di tutto l'anno. Per quegli spot, in novembre, la probabilità
sarà un po' più generosa del vero. Non l'ho cambiata prima di sparire per due
mesi perché toccare la previsione senza nessuno che ne guardi gli effetti è il
tipo di modifica che si fa il giorno in cui si può controllare il giorno dopo.
È la prima cosa da rimettere in mano quando si riapre.

---

## Quando torni: cinque minuti, tre cose

1. **Il sito si aggiorna?** Apri la pagina: in fondo c'è l'ora di costruzione,
   e in alto l'età dell'ultimo dato reale. Se sono di oggi, il cuore batte.
2. **La pagella.** In cima alla diagnostica: adesso dovrebbe avere numeri veri
   su una sessantina di giornate. È la prima volta che il sito si dà un voto da
   solo su quello che ha davvero pubblicato.
3. **Il pallino di Actions.** Verde: i quattro controlli della salute dicono di
   sì. Rosso: il motivo è scritto in chiaro nell'ultimo passo del giro
   («Controlla la salute del giro»), in italiano, e dice cosa fare.

Lo stesso verdetto si chiede al Mac, con il progetto aperto nel terminale:

```
python3 -m gardawind --salute
```

Stampa le stesse righe: previsione, località, archivio, centraline.

---

## Le tre date che aspettano dei dati, non del lavoro

- **inizio ottobre** — la pagella arriva a dieci giornate confrontabili e
  comincia a dire un numero.
- **fine ottobre** — un mese di direzione misurata: si può aprire la strada
  chiusa del protocollo direzione (`docs/STRADE-CHIUSE.md`).
- **fine novembre** — due mesi di previsioni altrui archiviate con la data in
  cui le abbiamo lette: il confronto con Addicted diventa inattaccabile.
  Una cosa piccola va fatta **prima** però, ed è mezz'ora: conservare le nostre
  stime fuori campione invece di buttarle dopo l'addestramento
  (`docs/CONFRONTO-ADDICTED.md`).

---

## Se qualcosa si è rotto e non hai voglia di indagare

Non serve indagare. Il giro lungo si può rilanciare a mano da *Actions → Garda
Wind → Run workflow*: rilegge tutto, riaddestra e ripubblica. Se la cache è
sparita ci mette mezz'ora e basta lasciarlo andare. Niente di irrecuperabile
vive nella cache: quello che non si riscarica sta in `storico/`, dentro il
repository, e ci torna da solo.
