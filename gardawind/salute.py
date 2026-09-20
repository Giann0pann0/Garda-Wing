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

Tre controlli, e sono scelti per essere rumorosi solo quando serve:

  LA PREVISIONE E' FRESCA. L'ora del run piu' recente scaricato. I modelli
  globali escono ogni sei ore: dodici ore di margine significa che due giri
  interi possono aver saltato lo scaricamento senza allarme, tre no.

  IL PRODOTTO ESISTE. Almeno una localita' con una previsione per oggi. Un sito
  che si ricostruisce vuoto e' il caso che nessuno guarda mai.

  L'ARCHIVIO IRRIPETIBILE CRESCE. Si legge la data dell'ultima curva emessa
  DENTRO I FILE del progetto, non nel database: e' l'unico modo di accorgersi
  che il push dell'archivio fallisce sempre invece di una volta. Se quei file
  sono fermi da piu' di tre giorni, la serie che non si riscarica da nessuna
  parte sta vivendo nella sola cache - e la cache scade.

Cosa NON fa fallire il giro: un errore su una singola fonte. Una centralina giu'
per un'ora e' normale, e un pallino rosso che si accende ogni settimana per una
ragione che non richiede di fare niente e' peggio di nessun pallino: si impara a
ignorarlo. Gli errori si contano e si stampano; a far fallire il giro sono solo
le tre cose qui sopra, che vogliono tutte dire "stai guardando un sito che non
sa quello che dice".
"""

import gzip
import io
import os

from . import config, store
from .util import parse_dt_any, utc_now

# Da quante ore la previsione non e' piu' "di questo giro". I run globali escono
# ogni sei ore e il giro lungo passa quattro volte al giorno: dodici ore
# tollerano un buco, non una settimana.
PREVISIONE_MAX_ORE = 12.0

# Da quanti giorni l'archivio dentro il progetto non cresce piu'. Il giro passa
# quattro volte al giorno: tre giorni sono nove giri andati a vuoto.
ARCHIVIO_MAX_GIORNI = 3.0


def _ultima_curva_emessa_nei_file():
    """L'ultimo `issued_at` che si trova nei file di storico/emesse.

    Nei FILE, non nel database: il database e' pieno anche quando il push
    dell'archivio non riesce, ed e' esattamente il caso da scoprire.
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


def stato(adesso=None, prodotto=None):
    """{"ok": bool, "motivi": [...], "dettagli": {...}}.

    `prodotto` si passa quando il chiamante l'ha gia' calcolato, per non
    rifarlo: il giro lungo ce l'ha in mano.
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

    # 2. il prodotto esiste?
    try:
        from . import engine
        prodotto = prodotto if prodotto is not None else engine.full_product()
        con_oggi = sum(1 for righe in (prodotto or {}).values() if righe)
    except Exception as e:                            # noqa: BLE001
        con_oggi = 0
        dettagli["prodotto_errore"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    dettagli["spot_con_previsione"] = con_oggi
    if not con_oggi:
        motivi.append("nessuna localita' ha una previsione: il sito si "
                      "ricostruirebbe vuoto")

    # 3. l'archivio irripetibile cresce?
    ultimo = _ultima_curva_emessa_nei_file()
    dettagli["archivio_ultima_curva"] = ultimo
    if ultimo is None:
        dettagli["archivio_giorni"] = None
    else:
        d = parse_dt_any(ultimo)
        giorni = (adesso - d).total_seconds() / 86400.0 if d else None
        dettagli["archivio_giorni"] = round(giorni, 2) if giorni is not None else None
        if giorni is not None and giorni > ARCHIVIO_MAX_GIORNI:
            motivi.append("l'archivio dentro il progetto e' fermo da %.1f giorni "
                          "(limite %.0f): le serie che non si riscaricano stanno "
                          "vivendo nella sola cache, e la cache scade"
                          % (giorni, ARCHIVIO_MAX_GIORNI))

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
    out.append("  localita' con previsione: %s" % d.get("spot_con_previsione"))
    out.append("  archivio: ultima curva emessa %s (%s giorni)"
               % (d.get("archivio_ultima_curva") or "nessuna",
                  d.get("archivio_giorni")))
    out.append("  errori nel registro di questo giro: %s" % d.get("n_errori"))
    for m in s["motivi"]:
        out.append("  ! " + m)
    return out
