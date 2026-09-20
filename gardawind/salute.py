"""La salute del giro lungo: il pallino verde non deve poter mentire.

Il guasto peggiore di questo progetto non e' un errore: e' un'esecuzione che
riesce a meta' e non lo dice. Il giro lungo avvolge previsioni, contesto,
centraline e addestramento in un solo `except Exception` che scrive una riga nel
registro e va avanti; `--ci` ignorava quel fallimento e usciva con zero. Se
Open-Meteo risponde 429 al primo passo, il sito viene RICOSTRUITO dal database
invecchiato e ci stampa sopra "previsione calcolata adesso". Su GitHub: pallino
verde. L'unica traccia sono due righe in fondo a un log di centinaia.

Stessa forma per l'archivio: il passo che salva le serie irripetibili ha
`continue-on-error` - giusto, perche' perdere la pubblicazione del sito per un
conflitto di git sarebbe peggio - ma non distingue "non e' riuscito una volta"
da "non riesce da giugno".

Qui si risponde a UNA domanda: **quello che il sito mostra adesso e' il
risultato di questo giro, o e' roba vecchia con una data nuova?**

Quattro controlli, e sono scelti per essere rumorosi solo quando serve.

Riletti a freddo il 20/09/2026, prima di due mesi in cui nessuno li avrebbe
letti, i primi tre avevano ognuno un modo di dire di si' senza aver guardato.
Sta scritto qui perche' e' la lezione, non l'aneddoto: **un controllo che non
puo' dire di no e' peggio di nessun controllo**, perche' su di lui si conta.

  LA PREVISIONE E' FRESCA. L'ora del run piu' recente scaricato. I modelli
  globali escono ogni sei ore: dodici ore di margine significa che due giri
  interi possono aver saltato lo scaricamento senza allarme, tre no.
  Il buco: `last_forecast_run` veniva scritto a ogni giro anche quando tutte
  le richieste erano fallite. L'occhio guardava il proprio orologio. Adesso
  quell'ora si scrive solo se almeno un modello e' arrivato (engine.py).

  IL PRODOTTO ESISTE. TUTTE le localita' hanno una previsione, non almeno una:
  con la somma, sei spot su sette vuoti passavano per buoni, e una localita'
  muta per due mesi non accendeva niente. I mancanti si dicono per nome.

  L'ARCHIVIO ARRIVA NEL REPOSITORY. Non "i file esistono": il push e' andato.
  Il buco era nell'ordine - `--ci` riscrive storico/emesse da `esporta()` poco
  prima, quindi quei file portano sempre l'ora di questo giro e il controllo
  non poteva scattare mai. Adesso il flusso lascia un biglietto quando il push
  riesce (MARCA_PUSH) e qui si legge quello; sul Mac, dove il biglietto non
  c'e', si torna a leggere i file, che li' vengono da git e dicono la verita'.
  Non e' solo l'archivio: finche' quel push non passa il repository non ha
  attivita', e dopo 60 giorni GitHub spegne i cron da solo.

  LE CENTRALINE PARLANO ANCORA. Il controllo che mancava, e mancava la meta'
  del quadro: gli altri tre guardano tutti la previsione, ma il metro contro
  cui questo progetto si corregge sono le MISURE. Se il lettore di una
  centralina si spegne - la pagina cambia, l'indirizzo si sposta - previsione
  fresca, prodotto pieno, archivio spinto: tutto verde, e intanto per due mesi
  non si impara piu' niente. Soglia lunga di proposito (quattro giorni): un'ora
  giu' e' normale, un giorno capita, quattro giorni sono noi.

Cosa NON fa fallire il giro: un errore su una singola fonte. Una centralina giu'
per un'ora e' normale, e un pallino rosso che si accende ogni settimana per una
ragione che non richiede di fare niente e' peggio di nessun pallino: si impara a
ignorarlo. Gli errori si contano e si stampano; a far fallire il giro sono solo
le quattro cose qui sopra, che vogliono tutte dire "stai guardando un sito che
non sa quello che dice".
"""

import gzip
import io
import os

from . import config, store
from .util import iso_utc, parse_dt_any, utc_now

# Da quante ore la previsione non e' piu' "di questo giro". I run globali escono
# ogni sei ore e il giro lungo passa quattro volte al giorno: dodici ore
# tollerano un buco, non una settimana.
PREVISIONE_MAX_ORE = 12.0

# Da quanti giorni l'archivio dentro il progetto non cresce piu'. Il giro passa
# quattro volte al giorno: tre giorni sono nove giri andati a vuoto.
ARCHIVIO_MAX_GIORNI = 3.0

# Da quanti giorni una centralina non dice piu' niente. Un'ora e' normale, un
# giorno capita; quattro giorni non sono il tempo, sono il nostro lettore che
# non legge piu' - e mentre nessuno guarda il bersaglio dell'addestramento si
# congela senza che si accenda niente.
OSSERVAZIONI_MAX_GIORNI = 4.0


# Il nome del biglietto che il flusso lascia quando il push dell'archivio e'
# andato a buon fine. Sta nella cartella dei dati (quella nella cache), non nel
# progetto: cosi' viaggia con il database da un giro all'altro e non finisce
# nel repository.
MARCA_PUSH = "archivio-spinto.txt"


def marca_push_riuscito(adesso=None):
    """Segna che l'archivio e' allineato al remoto. Lo chiama il flusso."""
    p = os.path.join(store.support_dir(), MARCA_PUSH)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(iso_utc(adesso or utc_now()) + "\n")
    return p


def _ultimo_push_archivio():
    """Quando il push dell'archivio e' riuscito l'ultima volta, o None.

    E' la misura DIRETTA di quello che interessa. Leggere la data dentro i
    file di storico/emesse e' una misura indiretta, e dentro il flusso non
    funziona affatto: quei file li riscrive `archivio.esporta()` a ogni giro,
    prima che il controllo arrivi a guardarli. Sul Mac, dove il biglietto non
    c'e', si torna alla misura indiretta - li' i file vengono da `git pull` e
    dicono la verita'.
    """
    p = os.path.join(store.support_dir(), MARCA_PUSH)
    try:
        with open(p, encoding="utf-8") as fh:
            return (fh.read() or "").strip() or None
    except OSError:
        return None


def ultima_curva_nei_file():
    """L'ultimo `issued_at` che si trova nei file di storico/emesse.

    Nei FILE, non nel database: il database e' pieno anche quando il push
    dell'archivio non riesce, ed e' esattamente il caso da scoprire.

    QUANDO si legge conta quanto COSA si legge. Dentro il flusso, `--ci`
    riscrive quei file da archivio.esporta() prima di arrivare qui: letti dopo,
    portano sempre l'ora di questo giro e il controllo non puo' scattare mai.
    Vanno letti PRIMA, quando sul disco c'e' ancora quello che git ha davvero
    (il runner parte da un checkout), e il risultato si passa a stato() come
    `ultima_curva`.
    """
    cartella = os.path.join(config.PROJECT_DIR, "storico", "emesse")
    if not os.path.isdir(cartella):
        return None
    ultimo = None
    for nome in sorted(os.listdir(cartella)):
        if not nome.endswith(".csv.gz"):
            continue
        try:
            with gzip.open(os.path.join(cartella, nome), "rt",
                           encoding="utf-8") as fh:
                for riga in io.StringIO(fh.read()):
                    primo = riga.split(",", 1)[0]
                    if primo and primo[0].isdigit():
                        if ultimo is None or primo > ultimo:
                            ultimo = primo
        except (OSError, EOFError, UnicodeDecodeError):
            continue
    return ultimo


def stato(adesso=None, prodotto=None, ultima_curva=None):
    """{"ok": bool, "motivi": [...], "dettagli": {...}}.

    `prodotto` si passa quando il chiamante l'ha gia' calcolato, per non
    rifarlo: il giro lungo ce l'ha in mano. `ultima_curva` si passa quando la
    si e' letta PRIMA che l'esportazione dell'archivio riscrivesse i file
    (vedi ultima_curva_nei_file): dentro il flusso e' l'unico modo perche' il
    terzo controllo voglia dire qualcosa.
    """
    adesso = adesso or utc_now()
    motivi = []
    dettagli = {}

    # 1. la previsione e' di questo giro?
    run = store.meta_get("last_forecast_run")
    dt = parse_dt_any(run) if run else None
    ore = (adesso - dt).total_seconds() / 3600.0 if dt else None
    dettagli["previsione_run"] = run
    dettagli["previsione_eta_ore"] = round(ore, 1) if ore is not None else None
    if ore is None:
        motivi.append("non c'e' nessun run di previsione: il sito non ha niente "
                      "di cui essere la versione nuova")
    elif ore > PREVISIONE_MAX_ORE:
        motivi.append("la previsione piu' recente ha %.0f ore (limite %.0f): il "
                      "sito e' stato ricostruito da dati vecchi con una data "
                      "nuova addosso" % (ore, PREVISIONE_MAX_ORE))

    # 2. il prodotto esiste? Non "almeno uno": TUTTI. Con la somma di prima,
    # sei spot su sette vuoti passavano per buoni, e una localita' muta per due
    # mesi non accendeva niente. I mancanti si scrivono per nome, cosi' un
    # rosso si spiega da solo a chi lo trova.
    mancanti = []
    try:
        from . import config, engine
        prodotto = prodotto if prodotto is not None else engine.full_product()
        prodotto = prodotto or {}
        attesi = list(config.SPOT_ORDER)
        con_oggi = sum(1 for nome in attesi if (prodotto.get(nome)))
        mancanti = [nome for nome in attesi if not prodotto.get(nome)]
    except Exception as e:                            # noqa: BLE001
        con_oggi = 0
        attesi = []
        dettagli["prodotto_errore"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    dettagli["spot_con_previsione"] = con_oggi
    dettagli["spot_attesi"] = len(attesi)
    dettagli["spot_senza_previsione"] = mancanti
    if not con_oggi:
        motivi.append("nessuna localita' ha una previsione: il sito si "
                      "ricostruirebbe vuoto")
    elif mancanti:
        motivi.append("queste localita' non hanno previsione: %s (le altre %d "
                      "si', quindi il sito esce lo stesso e la mancanza non si "
                      "vede)" % (", ".join(mancanti), con_oggi))

    # 3. l'archivio irripetibile e' arrivato DAVVERO nel repository?
    #
    # Due misure per la stessa domanda, e si prende la migliore disponibile:
    # il biglietto lasciato dal flusso quando il push e' riuscito (misura
    # diretta), e in mancanza la data dentro i file di storico/emesse (misura
    # indiretta, giusta sul Mac dove quei file vengono da git).
    #
    # La misura indiretta, da sola, dentro il flusso non poteva scattare mai:
    # `archivio.esporta()` riscrive quei file dal database poco prima, quindi
    # portano sempre l'ora di questo giro. Un controllo che non puo' dire di
    # no e' peggio di nessun controllo, perche' si conta su di lui.
    spinto = _ultimo_push_archivio()
    ultimo = spinto or (ultima_curva if ultima_curva is not None
                        else ultima_curva_nei_file())
    dettagli["archivio_misura"] = "push riuscito" if spinto else "file di storico"
    dettagli["archivio_ultima_curva"] = ultimo
    if ultimo is None:
        dettagli["archivio_giorni"] = None
    else:
        d = parse_dt_any(ultimo)
        giorni = (adesso - d).total_seconds() / 86400.0 if d else None
        dettagli["archivio_giorni"] = round(giorni, 2) if giorni is not None else None
        if giorni is not None and giorni > ARCHIVIO_MAX_GIORNI:
            motivi.append("l'archivio non arriva nel repository da %.1f giorni "
                          "(limite %.0f, misura: %s): le serie che non si "
                          "riscaricano stanno vivendo nella sola cache, e la "
                          "cache scade. E finche' non arriva, il repository "
                          "non ha attivita': dopo 60 giorni GitHub spegne i "
                          "cron da solo."
                          % (giorni, ARCHIVIO_MAX_GIORNI,
                             dettagli["archivio_misura"]))

    # 4. le centraline parlano ancora? E' la domanda che mancava, e senza di
    # lei i tre controlli sopra guardano tutti dalla stessa parte: la
    # previsione. Ma il bersaglio contro cui questo progetto si corregge sono
    # le MISURE, e se il lettore di una centralina si spegne - la pagina
    # cambia, l'indirizzo si sposta - la previsione resta fresca, il prodotto
    # esiste, l'archivio cresce, e intanto per due mesi non impariamo piu'
    # niente. Soglia lunga di proposito: un'ora giu' e' normale, un giorno
    # capita, quattro giorni sono noi.
    ritardo = {}
    try:
        from . import config as _c
        from . import store as _s
        viste = []
        for _n, _sp in _c.SPOTS.items():
            st = _sp.get("station")
            if st and st not in viste:
                viste.append(st)
        for st in viste:
            d = _s.obs_stats(st)
            ult = d.get("hour_to")
            dt_o = parse_dt_any(ult) if ult else None
            if dt_o is None:
                # Mai vista parlare: non e' una centralina che tace, e' una
                # centralina nuova o un database appena nato. Lo dice il
                # controllo 1, non questo.
                ritardo[st] = None
                continue
            ritardo[st] = round((adesso - dt_o).total_seconds() / 86400.0, 2)
    except Exception as e:                            # noqa: BLE001
        dettagli["osservazioni_errore"] = "%s: %s" % (type(e).__name__,
                                                      str(e)[:120])
    dettagli["osservazioni_giorni"] = ritardo
    mute = sorted(st for st, g in ritardo.items()
                  if g is not None and g > OSSERVAZIONI_MAX_GIORNI)
    if mute:
        motivi.append("queste centraline non dicono niente da piu' di %.0f "
                      "giorni: %s - la previsione continua a uscire, ma il "
                      "metro contro cui si corregge e' fermo"
                      % (OSSERVAZIONI_MAX_GIORNI,
                         ", ".join("%s (%.1f)" % (st, ritardo[st])
                                   for st in mute)))

    # Gli errori si contano e si mostrano, ma non fanno fallire il giro: una
    # centralina giu' per un'ora e' normale, e un allarme che suona ogni
    # settimana per niente e' un allarme che si impara a ignorare.
    try:
        from . import engine as _e
        errori = [x for x in _e.STATE.get("errors") or []]
    except Exception:                                 # noqa: BLE001
        errori = []
    dettagli["errori"] = errori[:20]
    dettagli["n_errori"] = len(errori)

    return {"ok": not motivi, "motivi": motivi, "dettagli": dettagli}


def righe_da_stampare(s):
    """Il verdetto in righe pronte da stampare, per il flusso e per il Mac."""
    d = s["dettagli"]
    out = ["salute del giro: %s" % ("a posto" if s["ok"] else "QUALCOSA NON TORNA")]
    out.append("  previsione: run %s (%s ore)"
               % (d.get("previsione_run") or "nessuno",
                  d.get("previsione_eta_ore")))
    out.append("  localita' con previsione: %s su %s%s"
               % (d.get("spot_con_previsione"), d.get("spot_attesi"),
                  ("  (senza: %s)" % ", ".join(d["spot_senza_previsione"]))
                  if d.get("spot_senza_previsione") else ""))
    out.append("  archivio: ultima curva emessa %s (%s giorni)"
               % (d.get("archivio_ultima_curva") or "nessuna",
                  d.get("archivio_giorni")))
    oss = d.get("osservazioni_giorni") or {}
    if oss:
        out.append("  centraline, giorni dall'ultima ora misurata: %s"
                   % ", ".join("%s %s" % (st, oss[st]) for st in sorted(oss)))
    out.append("  errori nel registro di questo giro: %s" % d.get("n_errori"))
    for m in s["motivi"]:
        out.append("  ! " + m)
    return out
