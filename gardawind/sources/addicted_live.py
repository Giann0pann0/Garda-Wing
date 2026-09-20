"""Il canale in tempo reale di addicted-sports: tutte le centraline, ogni volta.

Gian, guardando la pagina: "sport addicted pubblica i dati in tempo reale ogni
10 minuti!". Aveva ragione e noi leggevamo il canale sbagliato. Quello che
usavamo - la pagina della stazione con "?json=wind" - da' UNA RIGA PER ORA, e
da quello nascevano due difetti visibili: la curva del misurato a Campione e a
Malcesine restava ferma all'ora della costruzione, e il riquadro dell'"adesso"
si ingialliva mezz'ora su ogni ora come se la centralina fosse guasta.

Questo modulo legge il terzo canale, quello che la pagina d'insieme del lago
interroga da sola (config.URL_ADDICTED_LIVE). Tre cose che dichiara:

  UNA RICHIESTA, TUTTE LE STAZIONI. Non una per centralina: la risposta e' un
  dizionario di stazioni. Dieci minuti per volta fanno 144 richieste al giorno
  in tutto, contro le 288 che ci vorrebbero leggendole a due a due.

  SI LEGGE "rec", NON "live". Ogni stazione ha due blocchi: "live" e' lo
  scatto dell'istante (un minuto), "rec" e' la media e il massimo su una
  finestra DICHIARATA ("min" minuti, "n" campioni). "rec" e' la stessa
  grandezza dei dieci minuti di Meteotrentino, e il confronto fra le due
  localita' vive su quella. Tenere "live" darebbe una riga piu' nervosa con lo
  stesso nome, che e' l'errore di sempre.

  LA DIREZIONE QUI E' MISURATA. Sulla pagina della stazione la direzione e'
  prevista, e il modulo addicted.py fa bene a rifiutarla. Qui no, e la prova
  sta nella stessa risposta: il campo del modello dava 334-343 gradi a tutte e
  cinque le stazioni mentre le misure davano 8, 358, 337, 10, e Capo Reamol -
  prevista come le altre - non ha alcuna misura. Non viene ancora usata per il
  bersaglio: vedi docs/DA-MISURARE.md.

E una cosa che NON fa: non decide quale stazione e' quale. La chiave della
webcam non e' il nostro slug ("gardasee" e' Malcesine), e una tabella scritta
a mano qui si sarebbe rotta in silenzio al primo rinominare. La risposta porta
per ogni stazione il campo "fc", cioe' l'indirizzo della sua pagina di
previsione: l'ultimo pezzo di quell'indirizzo E' lo slug. Lo dice il sito, non
lo indoviniamo noi.
"""
import json as _json

from .. import config, store
from ..util import iso_utc, utc_now
from .http import FetchError, fetch_text

SOURCE = "addicted-live"

# Si alza quando cambia il MODO di leggere, non quando cambia il sito.
PARSER_VERSION = "addicted-live/1"

# Oltre questo, il dato non e' "adesso" nemmeno per il sito: la risposta porta
# "age" in minuti e un suo "stale". Si rispetta il suo, quando c'e'.
ETA_MAX_MIN = 90.0


def slug_da_fc(fc):
    """"/forecast/gardasee/malcesine/" -> "malcesine". None se non e' un fc."""
    if not fc or not isinstance(fc, str):
        return None
    pezzi = [p for p in fc.split("/") if p]
    return pezzi[-1] if pezzi else None


def parse(dati):
    """{slug: lettura}. Una lettura senza "rec" non entra: non si inventa.

    lettura: ts (iso UTC), wind, gust, dir, temp, finestra_min, n_campioni,
    stale, eta_min, cam.
    """
    if not isinstance(dati, dict) or not dati.get("ok"):
        raise FetchError("risposta senza ok=true dal canale vivo Addicted")
    cams = dati.get("cams")
    if not isinstance(cams, dict) or not cams:
        raise FetchError("risposta senza stazioni dal canale vivo Addicted")
    out = {}
    for cam, v in cams.items():
        if not isinstance(v, dict):
            continue
        slug = slug_da_fc(v.get("fc")) or cam
        rec, live = v.get("rec"), v.get("live")
        if not isinstance(rec, dict) or rec.get("avg") is None:
            # Nessuna misura recente: Capo Reamol sta qui, e ci sta da quando
            # ha smesso di misurare. Si salta, non si mette a zero.
            continue
        # L'istante e' quello della lettura, non quello della richiesta: due
        # richieste nello stesso minuto devono scrivere la stessa riga, non
        # due. La chiave di obs_sample e' (stazione, istante, fonte).
        t = (live or {}).get("t") or dati.get("now")
        if not t:
            continue
        out[slug] = {
            "ts": iso_utc(_da_unix(t)),
            "wind": _num(rec.get("avg")),
            "gust": _num(rec.get("max")),
            "dir": _dir(rec.get("dir")),
            "temp": _num((live or {}).get("temp")),
            "finestra_min": _num(rec.get("min")),
            "n_campioni": rec.get("n"),
            "stale": bool(v.get("stale")),
            "eta_min": _num((live or {}).get("age")),
            "cam": cam,
        }
    return out


def _da_unix(t):
    import datetime as _dt
    return _dt.datetime.fromtimestamp(int(t), tz=_dt.timezone.utc)


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _dir(v):
    """I gradi, o None. La regola sta in util.direzione_o_niente, in un posto solo."""
    from ..util import direzione_o_niente
    return direzione_o_niente(v)


def fetch():
    """({slug: lettura}, meta). Registra il corpo grezzo, come gli altri canali."""
    url = config.URL_ADDICTED_LIVE
    corpo = fetch_text(url, timeout=30)
    try:
        dati = _json.loads(corpo)
    except ValueError as e:
        _registra(url, corpo, False, note="json illeggibile: %s" % e)
        raise FetchError("risposta non JSON da %s: %s" % (url, str(e)[:120]))
    letture = parse(dati)
    meta = _registra(url, corpo, True, n_rows=len(letture))
    meta["interval_s"] = dati.get("interval")
    return letture, meta


def _registra(url, corpo, ok, n_rows=None, note=None):
    from .addicted import impronta, impronta_struttura_json
    fetched_at = iso_utc(utc_now())
    struct = None
    if ok:
        try:
            struct = impronta_struttura_json(_json.loads(corpo))
        except Exception:                            # noqa: BLE001
            struct = None
    raw_id, cambiata = store.log_raw_fetch(
        SOURCE, url, fetched_at, channel="cams", station=None, ok=ok,
        body=corpo, sha256=impronta(corpo), struct_sha256=struct,
        parser_version=PARSER_VERSION, n_rows=n_rows, note=note)
    if cambiata:
        store.log_event("warn", "addicted/cams",
                        "la struttura del canale vivo e' cambiata (raw_fetch %d): "
                        "il parser va riguardato" % raw_id)
    return {"raw_id": raw_id, "struttura_cambiata": cambiata, "url": url,
            "fetched_at": fetched_at, "parser_version": PARSER_VERSION,
            "source": SOURCE, "n": n_rows}
