# Garda Wind

Previsione del vento per l'alto Garda — **Torbole** e **Malcesine**, Ora e Pelèr —
costruita per chi ci va in acqua.

Non è un altro front-end sopra un modello globale. È un modello locale addestrato
su **740.752 misure a dieci minuti** della centralina di Torbole dal 2012, che
corregge dodici modelli meteo confrontandoli con quello che il vento ha
davvero fatto in quel punto.

Python puro, nessuna dipendenza da installare, nessuna chiave API.

---

## Quanto vale, misurato

Ogni numero qui sotto è **fuori campione**, con forward chaining (si addestra sul
passato e si prova sul futuro), λ scelto dentro il solo periodo di addestramento,
calibrazione tarata fuori dal blocco di prova, e un blocco cieco finale di 240
giorni mai toccato. 510 giornate di prova per riga.

| Spot | Scadenza | Errore di intensità | vs. climatologia | Brier | vs. climatologia |
|---|---|---|---|---|---|
| Torbole · Ora | oggi / domani | **1,78 kn** | 2,19 | **0,096** | 0,247 |
| | +2 / +3 giorni | 1,89 kn | 2,19 | 0,131 | 0,247 |
| | +4 … +7 | 1,99 kn | 2,19 | 0,180 | 0,247 |
| Torbole · Pelèr | oggi / domani | **1,53 kn** | 2,01 | 0,174 | 0,238 |
| | +2 / +3 | 1,54 kn | 2,01 | 0,190 | 0,238 |
| | +4 … +7 | 1,69 kn | 2,01 | 0,213 | 0,238 |

E tre cose che **non** funzionano, perché un progetto che pubblica solo i
risultati buoni non è verificabile:

- **L'orario del picco**: errore 70–90 minuti, e il modello non batte la
  semplice media stagionale. L'app lo dichiara come voce separata
  («timing: bassa precisione, ±83 min») invece di far finta.
- **A sette giorni la probabilità vale zero**: Brier 0,240 contro 0,238
  climatologici. Scritto nella tabella, non nascosto in una media.
- **Malcesine non ha abbastanza storico** (l'archivio intraday parte da marzo
  2026): nessuna fascia validata, e l'app lo dice.

## Come funziona

**Due stadi, perché sono due domande.** *Entra?* è una classificazione, *quanto
forte?* una regressione addestrata solo sui giorni in cui è entrato. Il vento
sull'alto Garda è bimodale — o l'Ora entra e sono 15–25 nodi, o non entra e sono
3–6 — e una regressione unica stimerebbe la media dei due casi, cioè un valore
che non capita quasi mai.

**Un modello per fascia di scadenza**, ognuno addestrato sui predittori *come
erano a quella scadenza* (archivio delle run precedenti di Open-Meteo) e validato
per conto proprio. Niente moltiplicatori scritti a mano: le bande di incertezza
sono i quantili dei residui misurati a quella scadenza.

**Promozione con porte.** Un modello entra in produzione solo se batte i
riferimenti banali — frequenza climatologica, mediana, vento grezzo d'ensemble —
con un intervallo bootstrap che non attraversa lo zero. Altrimenti l'app usa una
stima fisica e lo dichiara.

**Un regime è una direzione.** Quindici nodi da sud al mattino non sono il Pelèr.
Gli assi sono misurati, non dedotti dalla mappa: a Torbole il Pelèr arriva da
**54°**, non dai 24° della geometria del lago (mediana circolare su 3511 giornate
ventose, R=0,90, identica in tutte e quattro le stagioni).

## Uso

```bash
python3 -m gardawind                 # cruscotto su http://127.0.0.1:8781
python3 -m gardawind --backfill      # scarica gli archivi e addestra (lungo)
python3 -m gardawind --train         # riaddestra dai dati già scaricati
python3 -m gardawind --validate      # tabella per spot × regime × scadenza
python3 -m gardawind --validate --periodo-comune
python3 -m gardawind --direzioni     # da dove viene il vento, per settore
python3 -m gardawind --bands         # confronta i tagli di fascia
python3 -m gardawind --export DIR    # sito statico
```

Su Mac: `./costruisci-app-mac.command` produce una cartella con l'app e i comandi
numerati da doppio clic. Il codice resta in `gardawind/`, che è l'unica copia.

## In rete senza tenere acceso il Mac

`.github/workflows/garda-wind.yml` esegue raccolta, addestramento ed esportazione
quattro volte al giorno su GitHub Actions e pubblica il sito su Pages. Stesso
codice, nessuna riscrittura. Istruzioni in [`docs/COME-METTERLO-IN-RETE.md`](docs/COME-METTERLO-IN-RETE.md).

Il database vive nella cache di Actions fra un'esecuzione e l'altra, con copia di
sicurezza come artefatto. Se la cache viene sfrattata (succede dopo 7 giorni di
inattività) la prima esecuzione successiva riscarica tutto: è lenta, non è rotta.

## Verifiche

```bash
for t in test/t_*.py; do python3 "$t"; done
```

268 controlli: conversioni di fuso e cambio dell'ora legale, parser delle
centraline contro i payload reali, algebra dei modelli, proprietà del forward
chaining, memoria all'età giusta a ogni scadenza, tassonomia dei regimi,
avvio a freddo con database vuoto. Se tocchi il codice, lancialo prima e dopo.

## Documentazione

In [`docs/`](docs/) ci sono i rapporti di validazione, compresi gli errori
trovati e ritirati. In particolare
[`Blocco_A_3.6.md`](docs/Blocco_A_3.6.md) elenca quali risultati delle versioni
precedenti restano validi e quali sono stati ritirati, e perché.

## Fonti

| | |
|---|---|
| Torbole | [Meteotrentino](https://dati.meteotrentino.it), stazione T0193 (Belvedere), 90 m — realtime a 10 min + archivio Hydstra dal 04/07/2012 |
| Malcesine | Fraglia Vela Malcesine, Davis Vantage Pro2 — via [MeteoProject](https://stazioni.meteoproject.it) |
| Modelli | [Open-Meteo](https://open-meteo.com) (forecast, historical-forecast, previous-runs): ECMWF IFS e AIFS, ICON-D2, ICON-EU, ICON-2I, AROME Austria, ICON-CH2, ARPEGE, HARMONIE, GFS, UKMO, GEM |

I dati Open-Meteo sono CC-BY 4.0. Le due centraline sono citate in fondo a ogni
pagina dell'app con il loro peso e il loro errore misurato.

## Licenza

MIT — vedi [LICENSE](LICENSE).
