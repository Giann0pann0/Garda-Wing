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
              fetched_at=None, station=STATION, parser_version=None):
    fetched_at = fetched_at or iso_utc(utc_now())
    parser_version = parser_version or PARSER_VERSION
    raw_id, cambiata = store.log_raw_fetch(
        SOURCE, url, fetched_at, channel=channel, station=station, ok=ok,
        body=corpo, sha256=impronta(corpo), struct_sha256=struct,
        parser_version=parser_version, n_rows=n_rows, note=note)
    if cambiata:
        # Non e' un errore: e' un preavviso. Il parser oggi ha funzionato, ma
        # la pagina non e' piu' quella su cui e' stato scritto.
        store.log_event("warn", "addicted/%s" % channel,
                        "la struttura della pagina e' cambiata (raw_fetch %d): "
                        "il parser va riguardato" % raw_id)
    return {"raw_id": raw_id, "struttura_cambiata": cambiata,
            "fetched_at": fetched_at, "url": url,
            "sha256": impronta(corpo), "struct_sha256": struct,
            "parser_version": parser_version, "channel": channel,
            "station": station, "source": SOURCE,
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


# ==========================================================================
# Il sito nuovo (dal 6/11/2026): misure orarie e previsione, due indirizzi
# ==========================================================================
#
# Il canale json qui sopra (fetch_hourly, "?json=wind") non risponde piu': il
# sito e' stato rifatto e quell'indirizzo restituisce una pagina. Resta nel
# file perche' i controlli lo tengono fermo e perche' gli archivi gia'
# scaricati hanno quella forma; in esercizio si leggono i due canali sotto.
# Vedi config.URL_ADDICTED_MISURE per che cosa sono e che cosa NON sono.

PARSER_VERSION_MISURE = "addicted-misure/1"
PARSER_VERSION_PAGINA = "addicted-pagina/1"

_RE_GIORNO = re.compile(r'id="vh-d(\d+)"')
_RE_H2 = re.compile(r"<h2[^>]*>([^<]*)</h2>", re.I)
_RE_ORA_RIGA = re.compile(r'class="vh-row-h"[^>]*>\s*<b[^>]*>\s*(\d{1,2})\b', re.I)
_RE_KN_MEDIA = re.compile(r'class="vh-gb-mv"[^>]*>\s*<span[^>]*\bdata-kn="([0-9.]+)"', re.I)


def slug_da_url(url):
    """"/vorhersage/gardasee/campione/rueckblick/?d=..." -> "campione".

    Lo slug lo dice il sito, come faceva il campo "fc" del canale vivo: una
    tabella scritta a mano qui (la chiave della stazione e' "p454") si
    romperebbe in silenzio al primo rinominare.
    """
    if not url or not isinstance(url, str):
        return None
    pezzi = [p for p in url.split("?")[0].split("/") if p]
    if "rueckblick" in pezzi:
        i = pezzi.index("rueckblick")
        return pezzi[i - 1] if i > 0 else None
    return pezzi[-1] if pezzi else None


def parse_misure(dati, giorno):
    """Le misure orarie di un giorno locale -> {slug: [(ts_utc, vento, raffica, None)]}.

    Per stazione "h" e' [medie, direzioni, raffiche], ventiquattro caselle:
    l'indice E' l'ora locale (verificato sulla loro pagina "retrospettiva",
    che scrive gli stessi numeri sotto le etichette 00..23).

    Le caselle sono sempre 24, anche nei due giorni del cambio dell'ora: a
    marzo le 02 sono vuote, a ottobre l'ora doppia e' una casella sola. Quindi
    ogni casella si converte da sola, e si tiene solo se torna indietro sulla
    stessa ora - cosi' le 02 che a marzo non esistono non finiscono sopra le 03.

    La DIREZIONE non entra, come prima. Qui e' pubblicata fra le misure, ma lo
    zero vuol dire sia "nord" sia "non ho la banderuola" (Malcesine Nord e'
    tutta zeri) e non c'e' modo di distinguerli da questa risposta.
    """
    if not isinstance(dati, dict):
        raise FetchError("risposta delle misure senza oggetto")
    stazioni = dati.get("stations")
    if not isinstance(stazioni, list) or not stazioni:
        raise FetchError("risposta delle misure senza stazioni")
    if dati.get("date") and dati.get("date") != giorno:
        raise FetchError("chiesto il %s, risposto il %s" % (giorno, dati.get("date")))
    try:
        base = _dt.datetime.strptime(giorno, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise FetchError("giorno non valido: %r" % (giorno,))
    out = {}
    for st in stazioni:
        if not isinstance(st, dict):
            continue
        slug = slug_da_url(st.get("url"))
        h = st.get("h")
        if not slug or not isinstance(h, list) or len(h) < 3:
            continue
        medie, raffiche = h[0], h[2]
        if not isinstance(medie, list) or not isinstance(raffiche, list) \
                or len(medie) != 24 or len(raffiche) != 24:
            raise FetchError("misure di %s: attese 24 ore, trovate %s e %s"
                             % (slug, _lung(medie), _lung(raffiche)))
        righe = []
        for ora in range(24):
            w = num(medie[ora])
            if w is None or not (0.0 <= w <= MAX_WIND_KN):
                continue                  # ora futura, o non misurata
            t = local_naive_to_utc(base + _dt.timedelta(hours=ora))
            if t is None or to_local(t).hour != ora:
                continue                  # un'ora che quel giorno non esiste
            g = num(raffiche[ora])
            if g is not None and not (0.0 <= g <= MAX_GUST_KN):
                g = None
            righe.append((iso_utc(t), w, g, None))
        out[slug] = sorted(righe)
    if not out:
        raise FetchError("risposta delle misure senza nessuna stazione leggibile")
    return out


def _lung(x):
    return len(x) if isinstance(x, list) else type(x).__name__


def _forma_misure(dati):
    """L'impronta della struttura: le chiavi in cima e quelle di una stazione."""
    if not isinstance(dati, dict):
        return None
    st = dati.get("stations")
    prima = st[0] if isinstance(st, list) and st and isinstance(st[0], dict) else {}
    return impronta("%s|%s" % (",".join(sorted(dati)), ",".join(sorted(prima))))


def fetch_misure(giorno=None, adesso=None):
    """Le misure orarie di TUTTE le stazioni del lago, un giorno. ({slug: righe}, meta).

    Una richiesta sola, qualunque sia il numero delle stazioni che ci servono.
    L'ultima ora di oggi e' quella in corso: e' provvisoria, e la lettura dopo
    la sostituisce (la chiave e' stazione+istante+fonte).
    """
    adesso = adesso or utc_now()
    giorno = giorno or to_local(adesso).strftime("%Y-%m-%d")
    url = config.URL_ADDICTED_MISURE + giorno
    corpo = fetch_text(url, timeout=45)
    try:
        dati = _json.loads(corpo)
    except ValueError as e:
        _registra("misure", url, corpo, None, False, station=None,
                  parser_version=PARSER_VERSION_MISURE,
                  note="json illeggibile: %s" % e)
        raise FetchError("risposta non JSON da %s: %s" % (url, str(e)[:120]))
    struct = _forma_misure(dati)
    try:
        per_slug = parse_misure(dati, giorno)
    except FetchError as e:
        _registra("misure", url, corpo, struct, False, station=None,
                  parser_version=PARSER_VERSION_MISURE, note=str(e)[:200])
        raise
    meta = _registra("misure", url, corpo, struct, True, station=None,
                     parser_version=PARSER_VERSION_MISURE,
                     n_rows=sum(len(r) for r in per_slug.values()))
    meta.update({"giorno": giorno, "stazioni": sorted(per_slug),
                 "direzione_misurata": False, "decimali": False})
    return per_slug, meta


def parse_pagina_previsione(html, adesso=None):
    """La LORO previsione oraria dalla pagina della stazione -> [(ts, vento, None, None)].

    La pagina ha sette sezioni, id "vh-d0" (oggi) ... "vh-d6", e dentro ognuna
    una riga per ora con la media in data-kn - con i decimali, a differenza
    del testo che si vede. La banda "lo/hi" che il vecchio canale pubblicava
    non c'e' piu': restano None, e non si riempiono con la raffica, che e'
    un'altra grandezza.

    Due cautele, tutte e due contro lo stesso errore - archiviare una
    previsione sotto il giorno sbagliato:

      la data non si legge dal titolo ("domenica 15 nov": un mese abbreviato e
      localizzato), si calcola da oggi piu' il numero della sezione. Ma il
      NUMERO del giorno nel titolo deve tornare: se la pagina arriva da una
      cache attraverso la mezzanotte non torna, e quella sezione si salta;

      dentro la sezione le ore si cercano solo dopo "vh-rows". Prima c'e' una
      tabella con gli stessi numeri e le stesse classi, e leggerle tutte e due
      vorrebbe dire ogni ora due volte.
    """
    if not html or 'id="vh-d0"' not in html:
        raise FetchError("pagina di previsione senza le giornate (cercavo vh-d0)")
    oggi = to_local(adesso or utc_now()).replace(tzinfo=None)
    oggi = _dt.datetime(oggi.year, oggi.month, oggi.day)
    segni = list(_RE_GIORNO.finditer(html))
    naives, valori = [], []
    for k, m in enumerate(segni):
        fine = segni[k + 1].start() if k + 1 < len(segni) else len(html)
        sezione = html[m.start():fine]
        giorno = oggi + _dt.timedelta(days=int(m.group(1)))
        titolo = _RE_H2.search(sezione)
        numeri = re.findall(r"\d+", titolo.group(1)) if titolo else []
        if str(giorno.day) not in [n.lstrip("0") or "0" for n in numeri]:
            continue
        _prima, sep, righe = sezione.partition('class="vh-rows"')
        if not sep:
            continue
        ore = list(_RE_ORA_RIGA.finditer(righe))
        for j, mo in enumerate(ore):
            pezzo = righe[mo.end():(ore[j + 1].start() if j + 1 < len(ore)
                                    else len(righe))]
            mv = _RE_KN_MEDIA.search(pezzo)
            w = num(mv.group(1)) if mv else None
            ora = int(mo.group(1))
            if w is None or not (0.0 <= w <= MAX_WIND_KN) or ora > 23:
                continue
            naives.append(giorno + _dt.timedelta(hours=ora))
            valori.append(w)
    if not naives:
        raise FetchError("pagina di previsione senza nessuna ora leggibile "
                         "(%d giornate trovate)" % len(segni))
    out = [(iso_utc(t), w, None, None)
           for t, w in zip(serie_locale_to_utc(naives), valori) if t is not None]
    out.sort()
    return out


def fetch_previsione(slug=None, adesso=None):
    """La previsione che Addicted pubblica per una stazione. (righe, meta)."""
    slug = slug or "torbole"
    url = config.URL_ADDICTED_PAGINA % slug
    corpo = fetch_text(url, timeout=45)
    struct, pezzo = _forma_pagina(corpo)
    try:
        righe = parse_pagina_previsione(corpo, adesso=adesso)
    except FetchError as e:
        _registra("pagina", url, pezzo, struct, False, station=slug,
                  parser_version=PARSER_VERSION_PAGINA, note=str(e)[:200])
        raise
    meta = _registra("pagina", url, pezzo, struct, True, station=slug,
                     parser_version=PARSER_VERSION_PAGINA, n_rows=len(righe))
    return righe, meta


def _forma_pagina(corpo):
    """(impronta della struttura, pezzo da conservare) della pagina di previsione.

    La pagina pesa mezzo megabyte e cambia a ogni lettura, larghezze delle
    barre comprese: l'impronta si prende sui soli NOMI dei tag della prima
    riga oraria, dall'etichetta dell'ora fino alla fine dei due valori del
    vento. E' il pezzo che il parser legge, ed e' quello che si conserva.
    """
    if not corpo:
        return None, corpo
    i = corpo.find('class="vh-row-h"')
    if i < 0:
        return None, corpo[:20000]
    j = corpo.find('class="vh-row-x"', i)
    riga = corpo[i:j if j > i else i + 1500]
    return impronta(" ".join(re.findall(r"<(/?[a-zA-Z0-9]+)", riga))), corpo[i:i + 8000]
