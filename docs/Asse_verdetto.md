# L'asse corretto: verdetto

## Prima di tutto: la mia previsione era sbagliata

Ti avevo scritto: «cambiare l'asse ridefinisce il bersaglio, cambiano i positivi
e i negativi, quindi cambia tutto». Ecco cosa è cambiato:

| | prima | dopo |
|---|---|---|
| base rate Pelèr | 0,611764705882353 | **0,611764705882353** |
| Brier fascia corta | 0,173575 | **0,173575** |
| MAE | 1,525370 | **1,525370** |
| giornate con regime nel test | 312 | **312** |

**Niente. Zero giornate hanno cambiato classificazione.** Identico alla
quindicesima cifra decimale, su entrambi gli spot e tutte e tre le fasce.

Il motivo è aritmetico e avrei potuto verificarlo prima di annunciarlo. Il
settore è largo ±70°. Attorno a 24 copre 314–94; attorno a 54 copre 344–124. La
massa delle giornate ventose sta fra 20 e 80 gradi, cioè **dentro tutti e due**.
Spostare il centro di trenta gradi, con un settore così largo, non tocca
nessuno.

Avevo anche giustificato il non toccare la larghezza insieme all'asse — «una
cosa per volta, altrimenti non so quale delle due ha mosso le metriche». Il
ragionamento era buono in astratto e sbagliato qui: le due cose **non sono
separabili**, perché con ±70 l'asse non fa niente da solo.

---

## L'asse però è giusto, e si vede da un'altra parte

Lo scarto mediano delle direzioni osservate dall'asse, stagione per stagione:

| | con l'asse a 24 | con l'asse a 54 |
|---|---|---|
| inverno | 31° | **6°** |
| primavera | 30° | **6°** |
| estate | 30° | **5°** |
| autunno | 31° | **5°** |

Da trenta gradi a cinque, in tutte e quattro le stagioni. **Ora il riferimento è
centrato.** La correzione era giusta: semplicemente non produce effetti finché
il filtro resta così largo.

E la classificazione dei regimi, che usa settori stretti, è cambiata davvero:
nella finestra del Pelèr i venti da est passano da 14 a 0 e i meridionali
sinottici da 52 a 28 — cioè giornate prima attribuite male ora stanno al posto
giusto.

---

## Il risultato più bello: la valle ha due bocche, e basta

Il confronto fra direzione **osservata** e direzione **prevista dai modelli**,
nella finestra dell'Ora, 1409 giornate:

| i modelli prevedono | la centralina osserva |
|---|---|
| 0–30 | 55 |
| 30–60 | 53 |
| 60–90 | 55 |
| 90–120 | 66 |
| 120–150 | 172 |
| 150–180 | 194 |
| 180–210 | 194 |
| 210–240 | 193 |
| 240–270 | 193 |
| 300–330 | 201 |
| 330–360 | 65 |

Qualunque cosa dicano i modelli, la centralina misura **54 oppure 193**. Non c'è
una terza risposta. Il vento sinottico entra nella valle e ne esce incanalato in
una delle due direzioni, a seconda da che parte arriva.

Nella finestra del Pelèr è ancora più netto: su undici settori di provenienza
prevista, l'osservato è 51–58 gradi in **dieci** (l'unica eccezione è il
meridionale, che passa).

Quindi: **incanalamento, confermato.** Non è una banderuola storta — una
banderuola ruoterebbe tutto della stessa quantità, e invece qui direzioni
diverse vengono tirate verso lo stesso punto.

### E questo ha una conseguenza scomoda

Se la centralina vede solo due direzioni, **il filtro direzionale a Torbole non
filtra quasi niente.** I numeri, con l'asse corretto:

| ampiezza | giornate ventose dentro |
|---|---|
| ±30 | 93 % |
| ±45 | 95 % |
| ±60 | 95 % |
| ±90 | 95 % |

Da ±30 a ±90 si guadagnano due punti. La curva è piatta, la purezza resta 76 %
a ogni larghezza. Il meccanismo «un regime È una direzione» — che avevo
sostenuto con forza, e che resta giusto in linea di principio — **a questa
centralina è quasi inerte**, perché il posto non offre altre direzioni da
escludere. In tutta la finestra del Pelèr, i meridionali sinottici sono 28
giornate su 5151.

Dove il meccanismo continua a servire davvero è in **previsione**: il freno
sulla probabilità quando i modelli danno il vento fuori settore è ciò che ha
eliminato la scheda incoerente «97 % che entri / niente Pelèr». Quello lavora
sulla direzione prevista dai modelli, non su quella osservata, e lì le
direzioni sono tutte.

---

## Un errore che ho introdotto io, e che i dati hanno mostrato

Nel ricentrare i settori avevo scritto una rotazione **per spot** invece che
**per stazione**. I canali di una valle sono una proprietà del posto: la
centralina di Torbole vede 54 e 191 a tutte le ore, non è che di mattina la
valle è fatta in un modo e di pomeriggio in un altro.

Con la rotazione per spot, nella finestra dell'Ora il settore del Pelèr finiva a
**11 gradi** invece che a 54. Si vede nell'output che mi hai mandato:

- Pelèr classificati nella finestra dell'Ora: 121 → **67** (dimezzati)
- venti da est: 158 → **212**, di cui **184 marcati ambigui** perché finivano a
  ridosso di un confine messo nel posto sbagliato

Corretto: ora i due settori termici vengono dagli assi osservati della stessa
stazione, qualunque spot chieda la classificazione. 268 verifiche automatiche,
tutte superate.

---

## Cosa proporrei adesso

L'asse va tenuto: è centrato, e rende giusta la classificazione. Ma **non è lì
la leva**, e l'ho scoperto solo facendolo.

1. **Stringere il settore a ±45** — non perché cambi le metriche (cambierà
   pochissimo), ma perché ±70 non ha più alcuna giustificazione ora che il
   centro è al posto giusto. È igiene, non ottimizzazione.
2. **Rigirare il comando 6** con i settori corretti per stazione, per vedere la
   classificazione senza il mio errore.
3. Poi la domanda vera, che ti giro perché è una scelta di prodotto: **dove
   mettiamo lo sforzo?** I candidati, in ordine di quanto promettono:
   - **l'orario** — è il punto debole misurato (70–90 min, peggio della
     climatologia) ed è quello che un utente chiede di più dopo «entra?»;
   - **Malcesine** — non ha dati, servono mesi di raccolta, ma è metà del
     prodotto;
   - **le giornate navigabili senza Ora** — 359 in quindici anni, e ora che i
     settori sono giusti si possono isolare bene.

Il filtro direzionale, invece, lo considererei chiuso: è corretto, è validato, e
a Torbole vale poco. Saperlo è un risultato, anche se non è quello che speravo.
