# Garda Wind in rete, senza il Mac acceso

L'app gira già tutta su Python della libreria standard e non ha dipendenze da
installare. Questo significa che lo stesso identico codice che gira sul tuo Mac
può girare su un runner di GitHub, quattro volte al giorno, e pubblicare il
cruscotto come sito.

Nessuna riscrittura, nessun secondo linguaggio, nessuna API da inventare: gli
stessi parser, le stesse conversioni di fuso, lo stesso modello. È il motivo per
cui questa strada è preferibile a un collector scritto da capo in JavaScript —
i fusi orari e le unità sono già risolti e testati una volta sola.

## Cosa ti serve

Un account GitHub. Nient'altro.

## I passaggi

1. **Crea un repository**, anche privato. Chiamalo per esempio `garda-wind`.

2. **Copia dentro il contenuto di questa cartella `cloud/`** e, accanto,
   la cartella `gardawind/` che trovi in
   `Garda Wind.app/Contents/Resources/gardawind`.

   La struttura deve essere:

   ```
   garda-wind/
     .github/workflows/garda-wind.yml
     gardawind/            <- il pacchetto Python, copiato dall'app
   ```

3. **Attiva GitHub Pages**: nel repository, *Settings → Pages → Source:
   GitHub Actions*.

4. **Lancia la prima esecuzione a mano**: scheda *Actions → Garda Wind →
   Run workflow*.

   La prima volta è lunga: scarica i quattordici anni di Torbole, la rianalisi
   ERA5, l'archivio dei predittori e addestra tutto. Mettila in moto e vai a
   fare altro. Le volte successive durano pochi minuti, perché tutti gli
   scaricamenti riprendono da dove erano arrivati.

5. Finita l'esecuzione, il sito è all'indirizzo che trovi in
   *Settings → Pages*, nella forma
   `https://TUONOME.github.io/garda-wind/`.

## Cosa succede a ogni esecuzione

- legge le due centraline e aggiorna lo storico;
- scarica le previsioni dei dodici modelli;
- riaddestra quando i dati sono cambiati abbastanza;
- riscrive `index.html`, `diagnostica.html` e `previsione.json`;
- pubblica su Pages.

Il database resta nella cache di Actions fra un'esecuzione e l'altra ed è anche
allegato a ogni esecuzione come artifact, scaricabile per 90 giorni. Se la cache
venisse sfrattata non si perde nulla di irrecuperabile: tutti gli archivi si
riscaricano da soli, ci vuole solo più tempo.

## Avvertenze oneste

- **Gli orari cron di GitHub sono UTC** e le esecuzioni possono slittare di
  qualche decina di minuti quando la piattaforma è carica. Per una previsione
  del vento è irrilevante.
- **I workflow schedulati si disattivano dopo 60 giorni** di inattività del
  repository. Qui non è un problema perché ogni esecuzione scrive qualcosa, ma
  se lo lasci fermo a lungo ricordati di riattivarlo.
- **Il sito è pubblico** se il repository è pubblico. Con repository privato,
  Pages richiede un piano a pagamento: in quel caso tieni il repo privato e
  scarica `previsione.json` dagli artifact, oppure rendilo pubblico — non c'è
  niente di personale dentro.
- **Le due copie non si parlano.** Il Mac e il cloud raccolgono ciascuno il
  proprio database. Non è un problema: ciascuno ricostruisce lo stesso storico
  dalle stesse fonti. Anzi, per il primo mese è utile — se i due arrivano agli
  stessi numeri, vuol dire che la catena regge.

## Se preferisci tenere solo il cloud

Puoi. L'app sul Mac serve a guardare la previsione comodamente e a sviluppare;
il cloud basta a sé stesso. In quel caso disattiva la raccolta automatica in
background sul Mac (comando 3) per non interrogare le centraline due volte.
