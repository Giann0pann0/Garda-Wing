# Le due diagnosi: cosa hanno detto

---

## 1. Il periodo comune: avevi ragione, era un artefatto

Confermato, e in modo netto. Torbole-Ora, intensità, stessi 952 giorni per
tutte le scadenze:

| | Prima (periodi diversi) | Dopo (periodo comune) |
|---|---|---|
| **Oggi** | 2,84 kn · bias **+1,82** | **1,75 kn** · bias **−0,55** |
| Domani | 1,87 | 1,82 |
| Dopodomani | 1,85 | 1,86 |
| Tra 3 giorni | 1,93 | 1,93 |
| Tra 4 | 1,92 | 1,92 |
| Tra 5 | 2,02 | 2,01 |
| Tra 6 | 2,02 | 2,01 |
| Tra 7 | 2,03 | 2,02 |

La riga "Oggi" passa da 2,84 a 1,75 e il bias si ribalta da +1,82 a −0,55. Tutte
le altre righe restano dove erano — cioè erano già pulite, ed era solo "Oggi" a
essere sporca. **La sequenza ora è monotona**: 1,75 → 1,82 → 1,86 → 1,93 → 1,92
→ 2,01 → 2,01 → 2,02. L'errore cresce con la distanza, come deve.

Conseguenza: **la fascia corta dell'Ora ora è validata** (prima risultava no per
via di quell'unica riga), e il guadagno sull'intensità passa da −18 % `ns` a
**+19 % [+15, +22]**.

Non era fisica, era la composizione dei fold. La tua lettura era quella giusta e
la mia ipotesi sullo scalino dei modelli non serve più a spiegare niente.

**Il quadro ora, tutto su periodo comune:**

| Spot | Fascia | Brier (clim) | MAE (clim 2,19 / 2,01) | Guadagno prob. | Guadagno int. |
|---|---|---|---|---|---|
| Torbole-Ora | Oggi / Domani | **0,096** (0,247) | 1,78 | +61 % | +19 % |
| | +2 / +3 | 0,131 | 1,89 | +47 % | +14 % |
| | +4…+7 | 0,180 | 1,99 | +27 % | +9 % |
| Torbole-Pelèr | Oggi / Domani | 0,174 (0,238) | **1,53** | +27 % | +24 % |
| | +2 / +3 | 0,190 | 1,54 | +20 % | +23 % |
| | +4…+7 | 0,213 | 1,69 | +10 % | +16 % |

**Tutte e sei le fasce validate.** Calibrazione fra 0,013 e 0,080. Il limite di
prima resta vero: a sette giorni il Brier del Pelèr è 0,240 contro 0,238
climatologici, cioè **zero**.

---

## 2. L'asse del Pelèr: confermato, e il segno è risolto

Avevo previsto dai quantili «una moda spostata di 30° con dispersione stretta,
quindi 354° oppure 54°». Il dato:

```
moda principale        55 gradi  (1644 giornate su 3511)
mediana circolare      54 gradi
media circolare        53 gradi   concentrazione R=0.90
UNIMODALE — una sola gobba
per stagione:  inv 55   pri 54   est 54   aut 55
```

**54 gradi. Unimodale. Identico in tutte e quattro le stagioni, con R fra 0,79 e
0,94.** Non due rami, uno solo, e messo dove non lo cercavamo.

La previsione quantitativa era giusta e il segno ora è deciso: **ENE, non NNW**.

Per l'Ora lo scarto è minore ma c'è: mediana **191°** contro i 204 geometrici,
con R=0,55.

E una cosa che salta fuori solo mettendo insieme i due: **Pelèr a 54 e Ora a 191
distano 137 gradi, non 180.** I due venti a quella centralina non sono
antiparalleli — non usano lo stesso canale.

### Cosa ho cambiato

Un parametro faceva due lavori diversi. Ora sono due:

| | valore | a cosa serve |
|---|---|---|
| **asse dei modelli** | 24 / 204 | proiettare il vento *previsto* lungo la valle. Resta la geometria del lago: un vento di griglia grossolana il solco ce l'ha lì |
| **asse della centralina** | **54 / 191** | giudicare la direzione *osservata*, cioè decidere se «il regime è entrato». È la centralina che dobbiamo prevedere, quindi conta il suo sistema di riferimento |

Verificato: **20 nodi da 345° al mattino non sono più un Pelèr** — ora escono
come "vento da NO". Con l'asse a 24 lo scarto era 39° (dentro), con 54 è 69°
(fuori). Il problema che avevi sollevato tempo fa si chiude come effetto
collaterale della correzione, senza toccare l'ampiezza del settore.

### Quello che NON so, e che va detto

Uno scarto costante di 30° in tutte le stagioni ha **due** spiegazioni, e portano
a rimedi opposti:

- **banderuola disallineata** → la centralina ruota *tutte* le direzioni della
  stessa quantità. Si correggerebbe il dato.
- **incanalamento locale** → la conca piega il vento *verso* il proprio asse, da
  qualunque parte arrivi. Si lascia il dato e si sposta l'asse.

Non si distinguono guardando la sola distribuzione. Si distinguono confrontando
la direzione **osservata** con quella **prevista dai modelli**: una rotazione
rigida dà uno scarto costante in ogni settore, un incanalamento dà uno scarto che
cambia segno attorno all'asse locale. Ho aggiunto quel confronto a `--direzioni`:
comparirà nel prossimo rapporto.

Per il modello cambia poco — in entrambi i casi il bersaglio è ciò che quella
centralina misura, e quindi la correzione è quella giusta. Cambia
l'interpretazione fisica, e cambia se convenga correggere anche Malcesine allo
stesso modo.

### Malcesine

Anche lì gli assi sono spostati — Ora 230 contro 204, Pelèr 68 contro 24 — ma su
**101 e 50 giornate di solo 2026**, quindi viziate dalla stagione. Li ho messi
come **provvisori**, dichiarati tali nel codice.

---

## 3. Cosa non ho toccato, e perché

**L'ampiezza del settore resta ±70.** Con l'asse corretto l'istogramma dice che
basterebbe molto meno (fra 20° e 80° c'è quasi tutto, cioè ±30 attorno a 54), ma
**non voglio cambiare asse e larghezza nello stesso passo**: se le metriche si
muovono non saprei quale delle due l'ha fatto. Il prossimo rapporto contiene la
tabella dei settori *ricentrata su 54*, ed è quella che decide la larghezza con
un numero invece che con un'impressione.

**Non ho toccato le 359 giornate navigabili senza Ora.** Dipendono dai settori,
i settori dipendono dall'asse, l'asse è appena cambiato. Dopo.

**Il timing ora è la seconda voce**, come avevi indicato:

```
Domani   Alta affidabilità   Timing: bassa precisione · ±83 min
Pelèr 78% · 16–20 kn
```

Tre livelli propri (buona / media / bassa precisione) più "non misurato". I
minuti della finestra compaiono solo sotto i 60 minuti di errore — oggi da
nessuna parte.

---

## 4. Il passo successivo

**Cambiare l'asse ridefinisce il bersaglio.** Tutti i numeri della tabella qui
sopra sono stati misurati con la definizione vecchia: cambiano i positivi e i
negativi, quindi cambiano base rate, Brier, MAE, calibrazione — tutto.

Doppio clic su **`6 - Riaddestra con l'asse corretto`**. Non scarica niente,
qualche minuto. Fa tre cose: riaddestra sui bersagli ridefiniti, rivalida sul
periodo comune, e ristampa le direzioni con il nuovo riferimento (inclusa la
discriminante banderuola/incanalamento).

Poi confrontiamo con i numeri di questa pagina. Le cose da guardare, in ordine:

1. **Il base rate del Pelèr cambia?** Con l'asse a 54 alcune giornate entrano e
   altre escono. Se cambia molto, il bersaglio era davvero storto.
2. **Le metriche migliorano?** Un bersaglio più pulito dovrebbe rendere il
   problema più imparabile. Se invece peggiorano, l'asse a 54 è sbagliato e va
   ridiscusso — lo saprei solo così.
3. **La tabella dei settori centrata su 54**: a quale larghezza la purezza
   smette di salire? Quello decide il ±.
4. **Lo scarto osservato-contro-previsto**: costante o variabile fra i settori?
   Decide se è la banderuola o la conca.
