"""addicted-sports.com: la pagina di Torbole, letta come si legge una pagina.

Non c'e' un'API dichiarata. C'e' una pagina HTML, servita dal server con i
numeri gia' dentro (nessun rendering in JavaScript: la verifica e' stata fatta
scaricando il corpo grezzo e ritrovandoci i valori), e c'e' l'indirizzo che la
pagina stessa usa per il suo grafico - la stessa pagina con "?json=wind" - che
restituisce la serie ORARIA, misurata e prevista. Sono due canali dello stesso
sito, e questo modulo li tiene separati e dichiarati:

  CANALE json    la serie oraria completa della giornata: media misurata
                 (mavg) e massimo misurato (mmax), con decimali. E' il canale
                 buono, e permette anche di tornare indietro di giorni.
  CANALE html    il riquadro "misurato ora" in cima alla pagina: un valore
                 solo, arrotondato all'intero, con l'ora dell'ultima ora
                 civile. Serve da ripiego e da controllo incrociato.

Tre cose che questo modulo NON fa:

  non inventa la DIREZIONE. La pagina pubblica la direzione PREVISTA (chiave
  "dir"), non quella misurata: non esiste un "mdir". Prendere la direzione
  prevista e salvarla come osservata significherebbe alimentare il filtro di
  settore - quello che decide se il vento e' Ora o Peler - con una previsione.
  Quindi direction_deg resta None, e lo dice;

  non tratta l'ultima ora come definitiva. Il riquadro dice "misurato ora ·
  06:00" alle 06:34: quell'ora e' in corso, e la sua media cambiera' ancora.
  La riga viene salvata (la chiave e' stazione+istante+fonte, quindi la
  lettura successiva la sostituisce) ma viene anche CONTATA come provvisoria;

  non finge che un parser su HTML sia stabile. Ogni lettura registra
  l'impronta della STRUTTURA - i tag senza i valori - e quando quella cambia
  lo dichiara: e' il momento in cui un parser va guardato, prima che
  restituisca numeri sbagliati invece di errori.
"""

import datetime as _dt
import hashlib
import json as _json
import re

from .. import config, store
from ..util import (iso_utc, local_naive_to_utc, num,
                    serie_locale_to_utc, to_local, utc_now)
from .http import FetchError, fetch_text

STATION = "torbole_addicted"
SOURCE = "addicted-sports"

# Si alza quando cambia il MODO di leggere, non quando cambia il sito. Sta
# dentro ogni riga di provenienza: se fra un anno due letture della stessa ora
# non tornano, la prima domanda e' "con quale parser?".
PARSER_VERSION = "addicted/1"

MAX_WIND_KN = 60.0
MAX_GUST_KN = 85.0

# Oltre questo scarto fra il riquadro HTML e la serie JSON sulla stessa ora si
# dichiara un disaccordo. Il riquadro e' arrotondato all'intero, quindi mezzo
# nodo e' normale; due nodi no.
TOLLERANZA_CANALI_KN = 1.6

_RE_LBL = re.compile(r'class="lbl"[^>]*>([^<]*)<', re.I)
_RE_ORA = re.compile(r"(\d{1,2})[:.](\d{2})")
_RE_PILL = re.compile(r'class="[^"]*fc-knpill[^"]*"[^>]*>\s*([0-9]+(?:[.,][0-9]+)?)\s*<',
                      re.I)
_RE_TESTO = re.compile(r">[^<]*<")
_RE_SPAZI = re.compile(r"\s+")


# ==========================================================================
# Impronte
# ==========================================================================

def impronta(testo):
    """sha256 del testo, in esadecimale. Serve all'audit di cosa si e' letto."""
    if testo is None:
        return None
    return hashlib.sha256(testo.encode("utf-8", "replace")).hexdigest()


def impronta_struttura_html(frammento):
    """sha256 della sola struttura: i tag, senza il testo in mezzo.

    Su una pagina con numeri vivi l'impronta del corpo cambia a ogni lettura e
    quindi non dice niente. Questa cambia quando il sito viene rifatto - ed e'
    l'unica sentinella utile per un parser che vive sull'HTML.
    """
    if frammento is None:
        return None
    solo_tag = _RE_TESTO.sub("><", frammento)
    return impronta(_RE_SPAZI.sub(" ", solo_tag).strip())


def impronta_struttura_json(dati):
    """sha256 delle chiavi presenti e di quali sono liste. Non dei valori."""
    if not isinstance(dati, dict):
        return None
    forma = ";".join("%s:%s" % (k, "lista" if isinstance(dati[k], list) else "valore")
                     for k in sorted(dati))
    return impronta(forma)


# ==========================================================================
# Canale HTML: il riquadro "misurato ora"
# ==========================================================================

def ritaglia_div(html, ancora):
    """Il div che contiene "ancora", dal suo inizio al </div> che lo chiude.

    Contare le aperture e le chiusure invece di fidarsi di un'espressione
    regolare: il riquadro ha div annidati dentro, e una regex greedy prende
    mezza pagina o meta' riquadro a seconda di come e' scritta - e in entrambi
    i casi sbaglia in silenzio.
    """
    i = html.find(ancora)
    if i < 0:
        return None
    inizio = html.rfind("<div", 0, i)
    if inizio < 0:
        return None
    livello, pos = 0, inizio
    while pos < len(html):
        apre = html.find("<div", pos)
        chiude = html.find("</div", pos)
        if chiude < 0:
            return None
        if 0 <= apre < chiude:
            livello += 1
            pos = apre + 4
            continue
        livello -= 1
        pos = chiude + 5
        if livello == 0:
            fine = html.find(">", pos)
            return html[inizio:(fine + 1 if fine > 0 else pos)]
    return None


def parse_hero(html, adesso=None):
    """Il riquadro "misurato ora" -> (ts_utc, vento_kn, raffica_kn, None), ora_locale.

    Il riquadro misurato e quello PREVISTO, in cima alla stessa pagina, usano
    le stesse classi (fc-knpill, fc-hero-boe) e quello previsto viene PRIMA
    nel documento. Una regex sulla pagina intera prende i numeri della
    previsione e li salva come osservazione: percio' qui si ritaglia prima il
    riquadro giusto (fc-hero-meas) e solo dentro quello si cercano i valori.
    """
    blocco = ritaglia_div(html, "fc-hero-meas")
    if not blocco:
        raise FetchError("riquadro 'misurato' non trovato nella pagina "
                         "(cercavo fc-hero-meas)")

    m = _RE_LBL.search(blocco)
    etichetta = (m.group(1) if m else "").strip()
    mo = _RE_ORA.search(etichetta)
    if not mo:
        raise FetchError("ora del dato misurato non trovata; etichetta: %r"
                         % etichetta[:80])
    ora_l, min_l = int(mo.group(1)), int(mo.group(2))

    # La media sta prima di "fc-hero-boe", la raffica dentro. Dividere il
    # riquadro in due e' piu' robusto che contare le pastiglie: se un domani
    # ne aggiungono una, un indice fisso pescherebbe quella sbagliata.
    prima, sep, dopo = blocco.partition("fc-hero-boe")
    if not sep:
        raise FetchError("dentro il riquadro misurato manca fc-hero-boe; "
                         "struttura cambiata: %r" % blocco[:160])
    if "avgs" not in prima:
        raise FetchError("dentro il riquadro misurato manca il segno della "
                         "media (avgs): %r" % prima[:160])
    p_media = _RE_PILL.search(prima)
    p_raffica = _RE_PILL.search(dopo)
    if not p_media:
        raise FetchError("valore medio non trovato nel riquadro misurato: %r"
                         % prima[:160])
    vento = num(p_media.group(1))
    raffica = num(p_raffica.group(1)) if p_raffica else None
    if vento is None or not (0.0 <= vento <= MAX_WIND_KN):
        raise FetchError("vento misurato fuori scala: %r" % p_media.group(1))
    if raffica is not None and not (0.0 <= raffica <= MAX_GUST_KN):
        raffica = None

    # L'etichetta da' l'ora, non la data. La data e' quella locale di adesso -
    # con una cautela: se l'ora etichettata e' nel FUTURO di piu' di due ore
    # (pagina servita da una cache attraverso la mezzanotte) appartiene al
    # giorno prima. Senza questa riga, una lettura all'una di notte di una
    # pagina che dice 23:00 finirebbe ventitre' ore nel futuro.
    adesso = adesso or utc_now()
    loc = to_local(adesso)
    naive = _dt.datetime(loc.year, loc.month, loc.day, ora_l % 24, min_l)
    if (naive - loc.replace(tzinfo=None)).total_seconds() > 2 * 3600:
        naive -= _dt.timedelta(days=1)
    return (iso_utc(local_naive_to_utc(naive)), vento, raffica, None), etichetta


# ==========================================================================
# Canale JSON: la serie oraria che la pagina usa per il suo grafico
# ==========================================================================

def parse_json(dati):
    """La serie oraria misurata -> [(ts_utc, vento_kn, raffica_kn, None)].

    Chiavi usate: "arch" (la chiave dello slot, "2026/09/15/0600", ora
    LOCALE), "mavg" (media misurata) e "mmax" (massimo misurato). Si usa
    "arch" e non "time" perche' "time" e' scritto per un lettore umano
    ("mar 15.09. 06:00") e leggere un'abbreviazione di giorno della settimana
    localizzata per ricostruire una data e' un modo di rompersi al primo
    cambio di lingua.

    La DIREZIONE non entra: la chiave "dir" e' la direzione PREVISTA. Non
    esiste una direzione misurata in questa fonte.
    """
    if not isinstance(dati, dict) or not dati.get("ok"):
        raise FetchError("risposta json senza ok=true")
    arch = dati.get("arch") or []
    mavg = dati.get("mavg") or []
    mmax = dati.get("mmax") or []
    if not arch or not mavg:
        raise FetchError("risposta json senza serie misurata (arch/mavg)")
    if len(mavg) != len(arch) or (mmax and len(mmax) != len(arch)):
        raise FetchError("serie di lunghezze diverse: arch %d, mavg %d, mmax %d"
                         % (len(arch), len(mavg), len(mmax)))

    istanti = _istanti(arch)
    out = []
    for i, chiave in enumerate(arch):
        w = num(mavg[i]) if i < len(mavg) else None
        if w is None:
            continue                      # ora futura, o non misurata
        g = num(mmax[i]) if i < len(mmax) else None
        ts = istanti[i]
        if ts is None:
            continue
        if not (0.0 <= w <= MAX_WIND_KN):
            continue
        if g is not None and not (0.0 <= g <= MAX_GUST_KN):
            g = None
        out.append((ts, w, g, None))
    out.sort()
    return out


def _istanti(chiavi):
    """Le chiavi "arch" di una risposta, convertite TUTTE INSIEME.

    Sono orologi da parete in ordine: l'ultima domenica di ottobre le 02:00 e
    le 02:30 compaiono due volte, e convertite una per una collasserebbero
    sullo stesso istante UTC - un'ora di misure persa. In serie, l'ordine
    delle chiavi dice qual e' il secondo passaggio.
    """
    naives = []
    for c in chiavi:
        try:
            anno, mese, giorno, hhmm = str(c).split("/")
            naives.append(_dt.datetime(int(anno), int(mese), int(giorno),
                                       int(hhmm[:2]), int(hhmm[2:])))
        except (ValueError, IndexError):
            naives.append(None)
    return [iso_utc(t) if t is not None else None
            for t in serie_locale_to_utc(naives)]


def parse_json_previsione(dati):
    """La serie oraria PREVISTA DA LORO -> [(ts_utc, vento, lo, hi)].

    Viene dalla stessa risposta della serie misurata - chiavi "avg", "lo",
    "hi" accanto a "mavg" - quindi non costa nessuna richiesta in piu'.

    A cosa serve: il 19/09/2026 il primo confronto con un concorrente
    (docs/CONFRONTO-ADDICTED.md) ha dovuto dichiarare "non sappiamo a quale
    scadenza fosse emessa questa previsione", perche' loro ripubblicano i
    giorni passati senza dire quando li avevano previsti. L'unico modo di
    togliere quel dubbio e' archiviarla noi, giorno per giorno, segnando
    QUANDO l'abbiamo letta. Da li' la scadenza e' una sottrazione.

    La direzione non entra nemmeno qui: e' prevista, e sarebbe una previsione
    salvata accanto a misure.
    """
    if not isinstance(dati, dict) or not dati.get("ok"):
        raise FetchError("risposta json senza ok=true")
    arch = dati.get("arch") or []
    avg = dati.get("avg") or []
    lo, hi = dati.get("lo") or [], dati.get("hi") or []
    if not arch or not avg:
        return []
    istanti = _istanti(arch)
    out = []
    for i, chiave in enumerate(arch):
        w = num(avg[i]) if i < len(avg) else None
        if w is None or not (0.0 <= w <= MAX_WIND_KN):
            continue
        ts = istanti[i]
        if ts is None:
            continue
        out.append((ts, w,
                    num(lo[i]) if i < len(lo) else None,
                    num(hi[i]) if i < len(hi) else None))
    out.sort()
    return out


def url_stazione(slug=None):
    """La pagina di una stazione Addicted. Senza slug: Torbole, com'era."""
    if not slug or slug == "torbole":
        return config.URL_ADDICTED_TORBOLE
    return config.URL_ADDICTED_TORBOLE.replace("/torbole/", "/%s/" % slug)


def url_json(giorno, slug=None):
    return "%s?json=wind&from=%s" % (url_stazione(slug), giorno)


def url_frame_webcam(ts_utc):
    """L'inquadratura oraria della webcam per quell'istante.

    Non e' una misura del vento: e' una prova indipendente che alle 06:00 il
    sito era vivo e stava registrando. Come controllo secondario e' onesto -
    dice "c'era qualcuno che guardava" - e non pretende di essere altro.
    """
    dt = None
    try:
        from ..util import parse_dt_any
        dt = parse_dt_any(ts_utc)
    except Exception:
        dt = None
    if dt is None:
        return None
    loc = to_local(dt)
    return "%s%04d/%02d/%02d/%02d%02d_lm.jpg" % (
        config.URL_ADDICTED_WEBCAM_FRAMES, loc.year, loc.month, loc.day,
        loc.hour, loc.minute - loc.minute % 60)


# ==========================================================================
# Lettura con provenienza
# ==========================================================================

def _registra(channel, url, corpo, struct, ok, n_rows=None, note=None,
              fetched_at=None):
    fetched_at = fetched_at or iso_utc(utc_now())
    raw_id, cambiata = store.log_raw_fetch(
        SOURCE, url, fetched_at, channel=channel, station=STATION, ok=ok,
        body=corpo, sha256=impronta(corpo), struct_sha256=struct,
        parser_version=PARSER_VERSION, n_rows=n_rows, note=note)
    if cambiata:
        # Non e' un errore: e' un preavviso. Il parser oggi ha funzionato, ma
        # la pagina non e' piu' quella su cui e' stato scritto.
        store.log_event("warn", "addicted/%s" % channel,
                        "la struttura della pagina e' cambiata (raw_fetch %d): "
                        "il parser va riguardato" % raw_id)
    return {"raw_id": raw_id, "struttura_cambiata": cambiata,
            "fetched_at": fetched_at, "url": url,
            "sha256": impronta(corpo), "struct_sha256": struct,
            "parser_version": PARSER_VERSION, "channel": channel,
            "station": STATION, "source": SOURCE,
            "bytes": len(corpo) if corpo is not None else None}


def fetch_hourly(giorno=None, adesso=None, slug=None):
    """La serie oraria misurata di un giorno locale. (righe, meta).

    slug: la stazione Addicted. Nasce per Torbole (controllo incrociato) e
    dal 2026-09 serve Campione, dove Addicted e' LA centralina della pagina:
    stesso parser, stessa impronta, stessa provenienza registrata.
    """
    adesso = adesso or utc_now()
    giorno = giorno or to_local(adesso).strftime("%Y-%m-%d")
    url = url_json(giorno, slug)
    corpo = fetch_text(url, timeout=45)
    struct = None
    try:
        dati = _json.loads(corpo)
    except ValueError as e:
        _registra("json", url, corpo, None, False, note="json illeggibile: %s" % e)
        raise FetchError("risposta non JSON da %s: %s" % (url, str(e)[:120]))
    struct = impronta_struttura_json(dati)
    try:
        righe = parse_json(dati)
    except FetchError as e:
        _registra("json", url, corpo, struct, False, note=str(e)[:200])
        raise
    meta = _registra("json", url, corpo, struct, True, n_rows=len(righe))
    # L'ultima ora misurata e' quella in corso: la sua media non e' ancora
    # definitiva e verra' sostituita dalla lettura successiva.
    # La LORO previsione viaggia nella stessa risposta. Sta dentro meta e non
    # fra le righe perche' righe sono OSSERVAZIONI e questa e' una previsione
    # altrui: due grandezze diverse non vanno nella stessa lista. Ma viene da
    # una sola richiesta, e rifarne una seconda per averla sarebbe traffico
    # regalato al loro server.
    try:
        previste = parse_json_previsione(dati)
    except FetchError:
        previste = []
    meta.update({"giorno": giorno, "n_righe": len(righe),
                 "n_provvisorie": 1 if righe else 0,
                 "ultima": righe[-1][0] if righe else None,
                 "mae_dichiarato": dati.get("mae"),
                 "previsione_loro": previste,
                 "direzione_misurata": False})
    return righe, meta


def fetch_hero(adesso=None):
    """Il riquadro "misurato ora" della pagina. (campione, meta)."""
    url = config.URL_ADDICTED_TORBOLE
    corpo = fetch_text(url, timeout=45)
    blocco = ritaglia_div(corpo, "fc-hero-meas")
    struct = impronta_struttura_html(blocco)
    try:
        campione, etichetta = parse_hero(corpo, adesso=adesso)
    except FetchError as e:
        _registra("html", url, corpo, struct, False, note=str(e)[:200])
        raise
    meta = _registra("html", url, corpo, struct, True, n_rows=1)
    meta.update({"etichetta": etichetta, "direzione_misurata": False})
    return campione, meta


def confronta_canali(riga_json, campione_html, tol=TOLLERANZA_CANALI_KN):
    """I due canali sullo stesso istante devono dire quasi la stessa cosa.

    Il riquadro HTML e' arrotondato all'intero e la serie JSON ha i decimali,
    quindi mezzo nodo di scarto e' normale. Uno scarto grande vuol dire che
    uno dei due parser sta leggendo il posto sbagliato - ed e' esattamente il
    guasto che un parser su HTML produce senza dare errore.
    """
    if not riga_json or not campione_html:
        return None
    ts_j, w_j, g_j, _d = riga_json
    ts_h, w_h, g_h, _d2 = campione_html
    if ts_j != ts_h:
        return {"accordo": None, "nota": "istanti diversi: json %s, html %s"
                                         % (ts_j, ts_h)}
    scarti = {}
    if w_j is not None and w_h is not None:
        scarti["vento"] = abs(w_j - w_h)
    if g_j is not None and g_h is not None:
        scarti["raffica"] = abs(g_j - g_h)
    fuori = {k: v for k, v in scarti.items() if v > tol}
    return {"accordo": not fuori, "scarti": scarti, "fuori": fuori,
            "ts": ts_j}


def raccogli(giorni=1, adesso=None, con_html=True):
    """Legge, salva e racconta. Ritorna un sommario, senza stampare niente.

    giorni: quanti giorni locali indietro leggere, compreso oggi. La pagina
    accetta "from", quindi l'archivio recente si puo' ripescare - utile per
    riempire i buchi dopo un'interruzione.
    """
    adesso = adesso or utc_now()
    oggi = to_local(adesso).date()
    sommario = {"station": STATION, "source": SOURCE,
                "parser_version": PARSER_VERSION, "giorni": [],
                "n_salvate": 0, "errori": [], "confronto": None}
    tutte = []
    for k in range(int(giorni)):
        g = (oggi - _dt.timedelta(days=k)).isoformat()
        try:
            righe, meta = fetch_hourly(g, adesso=adesso)
        except FetchError as e:
            sommario["errori"].append("%s: %s" % (g, str(e)[:160]))
            continue
        n = store.save_samples(STATION, righe, SOURCE)
        sommario["n_salvate"] += n
        sommario["giorni"].append({"giorno": g, "n_righe": len(righe),
                                   "n_salvate": n, "meta": meta})
        tutte.extend(righe)

    if con_html:
        try:
            campione, meta_h = fetch_hero(adesso=adesso)
            ultima = None
            if tutte:
                per_ts = {r[0]: r for r in tutte}
                ultima = per_ts.get(campione[0])
            sommario["html"] = {"campione": campione, "meta": meta_h}
            sommario["confronto"] = confronta_canali(ultima, campione)
            if sommario["confronto"] and sommario["confronto"].get("fuori"):
                store.log_event(
                    "warn", "addicted/qc",
                    "i due canali non concordano su %s: %s"
                    % (campione[0], sommario["confronto"]["fuori"]))
            # Se il canale json non ha dato niente, il riquadro e' comunque un
            # campione: meglio un'ora arrotondata che nessuna.
            if not tutte:
                sommario["n_salvate"] += store.save_samples(
                    STATION, [campione], SOURCE + "-hero")
        except FetchError as e:
            sommario["errori"].append("riquadro: %s" % str(e)[:160])
    return sommario
