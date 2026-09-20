# Garda Wind in rete, senza il Mac acceso

Riscritto il 20/09/2026. La versione precedente descriveva il progetto di metà
settembre e su un punto diceva il falso — «se la cache venisse sfrattata non si
perde nulla di irrecuperabile» — che dal 19/09 non è più vero. Un documento
sbagliato su come rimettere in piedi le cose è peggio di nessun documento:
lo si legge proprio nel giorno in cui non si ha voglia di verificare.

L'app gira su Python della libreria standard e non ha dipendenze da installare,
quindi lo stesso identico codice che gira sul Mac gira su un runner di GitHub e
pubblica il cruscotto come sito. Nessuna riscrittura, nessun secondo linguaggio:
gli stessi parser, le stesse conversioni di fuso, lo stesso modello.

## Cosa serve

Un account GitHub, e il repository **pubblico**. Non è un vezzo: la pagina legge
`live.json` e `vivo.csv.gz` da URL anonimi di `raw.githubusercontent.com`
(`config.LIVE_JSON_URL`, `LIVE_VIVO_URL`). Su un repository privato quegli
indirizzi rispondono 404, e l'«adesso» della pagina resta fermo alla
ricostruzione del sito — cioè invecchia di sei ore mentre dice «adesso».

## I due flussi, e perché sono due

**`garda-wind.yml` — il giro lungo.** Quattro volte al giorno (cron `20 3,9,15,21`
UTC) e a ogni push che tocca `gardawind/**`. Scarica previsioni e centraline,
addestra, ricostruisce il sito, salva in `storico/` le serie irripetibili e
pubblica su Pages. Il suo database sta nella cache di Actions
(`GARDAWIND_HOME: dati`).

**`adesso.yml` — il giro veloce.** Ogni dieci minuti, database separato
(`dati-adesso`). Legge **solo** le tre letture che servono all'«adesso»
(Meteotrentino, la Fraglia, il canale vivo di Addicted) e scrive due file su un
ramo orfano chiamato `live`, force-pushato con un solo commit:

- `live.json`, che la pagina rilegge da sola mentre è aperta;
- `vivo.csv.gz`, il **ponte** verso il giro lungo.

Il ponte esiste perché i due processi hanno due database separati, e
necessariamente: le cache di Actions sono immutabili e si ripescano «la più
recente», quindi il veloce non può salvare sopra quella del lento senza
rischiare di fargli perdere i modelli appena addestrati. Senza il ponte, dei
campioni a dieci minuti con la direzione misurata — la serie che **non si
riscarica da nessuna parte** — in archivio arrivava una lettura su trentasei.

## Cosa si perde davvero, se si perde la cache

Questa è la parte che il documento precedente sbagliava.

**Si riscarica da solo** (basta una o due esecuzioni, con pazienza): i quattordici
anni di Torbole da Meteotrentino, la rianalisi ERA5, l'archivio dei predittori,
lo storico orario di Addicted (c'è anche una copia dentro il progetto, in
`storico/campione-addicted.csv.gz` e `malcesine-addicted.csv.gz`), i modelli
addestrati.

**NON si riscarica da nessuna parte**, e per questo dal 19/09 vive dentro il
repository sotto `storico/` (vedi `gardawind/archivio.py`):

| cartella | cos'è | perché è irripetibile |
|---|---|---|
| `storico/vivo/` | i campioni a dieci minuti delle centraline Addicted, con la **direzione misurata** | il loro canale vivo non ha archivio: quello che non si prende adesso non esiste più fra un'ora |
| `storico/emesse/` | le curve che **abbiamo pubblicato noi**, ora per ora | servono a verificarci su quello che l'utente ha davvero letto (è la «pagella») |
| `storico/altrui/` | la previsione dei concorrenti **con il giorno in cui l'abbiamo letta** | loro ripubblicano i giorni passati senza dire a che scadenza li avevano previsti: quel dato lo crea la nostra lettura |

Due regole rendono questi file un archivio e non una copia, e stanno scritte
in `archivio.py`: **non si rimpiccioliscono mai** (prima di scrivere si legge il
file che c'è e si fa l'unione) e **si rileggono all'indietro** (`recupera()` li
rimette nel database). Quindi: cache persa, una esecuzione, tutto a posto.

## I passaggi, da zero

1. **Crea il repository, pubblico.** Copiaci dentro tutto il contenuto del
   progetto: `gardawind/`, `test/`, `docs/`, `strumenti/`, `mac/`, `storico/`,
   `.github/workflows/`, `sfondo.jpg`, `README.md`.

   `storico/` va copiato **per primo e per intero**: sono i file irripetibili
   più la copia dello storico Addicted che permette a Campione e Malcesine di
   avere un modello anche in cloud.

2. **Attiva GitHub Pages**: *Settings → Pages → Source: GitHub Actions*.

3. **Lancia il giro lungo a mano**: *Actions → Garda Wind → Run workflow*. La
   prima volta è lunga (scarica quattordici anni e addestra tutto): mettila in
   moto e torna dopo una mezz'ora.

4. **Controlla che il ramo `live` nasca.** Dopo il primo giro veloce
   (`Actions → Garda Wind - adesso`) deve esistere un ramo `live` con dentro
   `live.json` e `vivo.csv.gz`. Se c'è solo `live.json`, il ponte non si è
   scritto: guarda il log di quel passo.

5. **Guarda `diagnostica.html`.** In cima c'è **La pagella**: per i primi dieci
   giorni dirà «mancano N giornate», ed è giusto. Sotto, «Quanto sbaglia» deve
   avere numeri e non trattini.

## Gli avvisi Telegram (facoltativi, e spenti finché non li accendi)

Il codice c'è e non fa niente finché mancano le due cose:

- `TELEGRAM_BOT_TOKEN` come **segreto** del repository
  (*Settings → Secrets and variables → Actions → Secrets*);
- `TELEGRAM_CHAT` come **variabile** (stessa pagina, scheda *Variables*), per
  esempio `@nomecanale`.

Senza, il passo scrive «avvisi: non configurati» e prosegue: `live.json` si
aggiorna comunque.

## Come si sa che sta funzionando

Il pallino verde di Actions **non basta**, e questa è la ragione per cui esiste
`gardawind/salute.py`. Il giro lungo ingoia di proposito i propri errori — una
fonte giù non deve impedire al sito di aggiornarsi — e per mesi un'esecuzione
riuscita a metà è restata verde: se Open-Meteo risponde 429 al primo passo, il
sito viene ricostruito dal database vecchio e ci stampa sopra «previsione
calcolata adesso».

L'ultimo passo del giro lungo (`python3 -m gardawind --salute`) chiede quattro
cose, e fa diventare rosso il pallino solo per queste:

1. la previsione più recente ha meno di 12 ore — e quell'ora si scrive **solo
   se almeno un modello è davvero arrivato**: fino al 20/09 veniva scritta
   comunque, quindi il controllo guardava il proprio orologio;
2. **tutte** le località hanno una previsione, non almeno una: con «almeno
   una», sei spot su sette vuoti passavano per buoni;
3. l'archivio è **arrivato nel repository** negli ultimi 3 giorni. Non «i file
   esistono»: il flusso lascia un biglietto (`dati/archivio-spinto.txt`) solo
   quando il push va a buon fine, e si legge quello. Prima si guardava la data
   dentro i file di `storico/emesse` — che però `--ci` riscrive da sé poco
   prima, quindi erano sempre freschi e il controllo non poteva scattare mai.
   Non è solo l'archivio: finché quel push non passa, il repository non ha
   attività, e **dopo 60 giorni GitHub spegne i cron da solo**;
4. le centraline parlano: nessuna ferma da più di 4 giorni. È il metro contro
   cui tutto il resto si corregge, e senza questo controllo poteva fermarsi per
   mesi con tutto il resto verde.

Un errore su una singola fonte **non** fa diventare rosso niente: si conta e si
stampa. Un allarme che suona ogni settimana per una ragione che non richiede di
fare niente è un allarme che si impara a ignorare.

Lo stesso comando si può lanciare sul Mac, e dice le stesse quattro cose.

Se il progetto deve restare mesi senza che nessuno lo guardi, la lista di cosa
può fermarsi e cosa controllare al ritorno sta in `docs/DUE-MESI-DA-SOLO.md`.

## Le cose che vanno sapute, e che non si vedono dal codice

- **Il repository è pubblico**: non ci vanno segreti, e infatti non ce ne sono
  (il token Telegram vive nei segreti di Actions, non nel codice). In `storico/`
  ci sono solo orari e numeri: nessun dato personale.
- **La cache di Actions** cancella le copie non usate da 7 giorni e ne tiene
  10 GB per repository. Col database che si riscrive a ogni giro fa circa quattro
  giorni di profondità: è il motivo per cui `storico/` esiste.
- **Il ramo `live` si riscrive da zero** a ogni giro veloce, con un solo commit:
  è un contenitore, non una storia, e serve a non gonfiare il repository di
  migliaia di commit da dieci minuti.
- **I cron di GitHub non sono puntuali**: un `*/10` in pratica gira ogni 10-20
  minuti. La pagina mostra sempre l'età del dato, quindi un ritardo si vede
  invece di essere mascherato.
