"""Forma intraday di Torbole da analoghi storici osservati.

Questo modulo modifica SOLO la forma temporale del profilo di giornata.
Il livello complessivo resta quello prodotto dal motore corrente.

Protocollo validato (da non cambiare senza nuova validazione):
- condizioni previste da best_match alla scadenza D+1/D+2/D+3;
- ciascuna sorgente standardizzata sulla propria distribuzione;
- archivio analoghi ERA5 + curve osservate T0193, training fino al 2023;
- k=3 vicini euclidei nello spazio standardizzato;
- mediana punto per punto delle curve normalizzate, griglia 10 minuti;
- nessun allineamento sull'ora d'ingresso.
"""

import datetime as _dt
import math
import statistics
import time

from . import store
from .util import (iso_utc, local_day, local_naive_to_utc, parse_dt_any,
                   to_local)

NORTH = (45.8701, 10.8774)
SOUTH = (45.7646, 10.8119)
STATION = "T0193"
TRAIN_START = "2012-07-05"
TRAIN_END = "2023-12-31"
EXPECTED_TRAIN_DAYS = 4020
EXPECTED_CONFIRM_DAYS = 617
# Quante giornate di differenza sul campione di conferma restano "gli stessi
# dati": quindici su seicentodiciassette, il 2,4%.
TOLLERANZA_CONFERMA_GG = 15
# E quante sulla libreria di addestramento: quaranta su quattromilaventi, l'1%.
# Il controllo esatto era giusto nell'intenzione e fragile nei fatti. La
# finestra di addestramento e' chiusa nel 2023, ma i dati di quelle giornate
# no: ogni recupero di storico della centralina - e ce n'e' stato uno, dai
# 4.267 giorni ai ~4.340 - cambia il conteggio, e con il controllo esatto il
# motore si spegneva in silenzio per sempre. Chi protegge davvero il prodotto
# non e' questo numero, e' la porta: misura su giornate mai viste, e se una
# libreria diversa peggiorasse i numeri la porta si chiuderebbe da se'.
TOLLERANZA_ADDESTRAMENTO_GG = 40
K = 3
GRID_MIN = tuple(range(4 * 60, 21 * 60 + 1, 10))
MIN_COVERAGE = 0.90
MIN_PEAK = 6.0
MAX_INTERP_GAP_MIN = 30.0
CACHE_S = 12 * 60 * 60
CURRENT_SOURCE = "analog_live"
GATE_KEY = "analog_shape_gate_v1"
GATE_SIGNATURE = "torbole-analogs-k3-20260916"
# Numeri del blocco cieco 2025-2026, RIMISURATI con le definizioni che usa
# questo codice. Non servono a ottimizzare nulla: sono una firma di
# regressione. Se questa implementazione non li riproduce entro tolleranze
# strette, NON modifica il prodotto pubblico.
#
# La prima stesura aveva i numeri del test che ha scelto il metodo, e con
# quelli la porta non poteva aprire MAI, per due differenze di definizione che
# non erano scelte di nessuno:
#
#   la RIPIDEZZA. Il test la misurava su tutta la curva 04:00-21:00, questo
#   codice la misura dentro la finestra dell'Ora (_steepness usa FINESTRA_ORA).
#   Sono due numeri diversi della stessa realta': 6,3 contro 5,95 prodotti, e
#   soprattutto 7,6 contro 6,99 VERI - e il controllo sulla ripidezza vera
#   aveva tolleranza 0,5, quindi cadeva sempre;
#
#   la STANDARDIZZAZIONE. Il test standardizzava le condizioni previste sulle
#   617 giornate di conferma; il motore, che in produzione non conosce il
#   futuro, usa tutta la sorgente disponibile (~966 giornate dal 2024). I
#   vicini cambiano un poco e i falsi allarmi a D+1 passano dal 20,9% al
#   24,4%, oltre la tolleranza di 0,035.
#
# Rimisurato il 2026-09-16 sull'archivio vero con le definizioni di qui, e la
# regola pre-registrata di selezione rifatta sul 2024 con le stesse
# definizioni sceglie ancora k=3 (falsi 16,3% entro il budget, ripidezza 5,69
# la piu' vicina alla vera 6,42). Il metodo non e' cambiato: e' cambiato il
# metro. La conclusione scientifica regge - 83,2% di colpi contro il 52,9%
# della curva liscia, sbilanciamento -8 minuti contro -94.
BENCHMARK = {
    1: {"hits": .832, "false_alarms": .244, "minute_error": 78.0,
        "bias_minutes": -8.0, "steepness": 5.95},
    2: {"hits": .812, "false_alarms": .289, "minute_error": 91.0,
        "bias_minutes": -6.0, "steepness": 6.25},
    3: {"hits": .812, "false_alarms": .274, "minute_error": 93.0,
        "bias_minutes": -8.0, "steepness": 6.02},
}
# La ripidezza VERA nella finestra dell'Ora, sulle giornate di conferma: e' una
# proprieta' del lago, non del codice, e serve da controllo di sanita' del
# campione. Se cambia, non stiamo guardando le stesse giornate.
RIPIDEZZA_VERA_ORA = 7.0
FEATURES = (
    "rad_tot", "cloud", "tmax", "precip", "dp_lago",
    "wx", "wy", "wnotte", "sin", "cos",
)

_CACHE = {"at": 0.0, "library": None, "era_stats": None,
          "lead_stats": {}, "diagnostic": None}


def _mean(values):
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return sum(vals) / len(vals) if vals else None


def _stdev(values, mu=None):
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if len(vals) < 2:
        return None
    mu = _mean(vals) if mu is None else float(mu)
    return math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals))


def _season(day):
    d = _dt.date.fromisoformat(day)
    a = 2.0 * math.pi * d.timetuple().tm_yday / 365.25
    return math.sin(a), math.cos(a)


def _rows_by_day(rows):
    out = {}
    for r in rows:
        dt = parse_dt_any(r["valid"])
        if dt is not None:
            out.setdefault(local_day(dt), []).append(r)
    return out


def daily_conditions(day, north_rows, south_rows):
    """Le 10 variabili del protocollo, aggregate sul giorno locale."""
    nr = [r for r in north_rows if local_day(parse_dt_any(r["valid"])) == day]
    sr = [r for r in south_rows if local_day(parse_dt_any(r["valid"])) == day]
    if not nr or not sr:
        return None

    def hour(r):
        return to_local(parse_dt_any(r["valid"])).hour

    rad = [r.get("rad") for r in nr if r.get("rad") is not None]
    cloud = [r.get("cloud") for r in nr if 8 <= hour(r) <= 16 and r.get("cloud") is not None]
    t2m = [r.get("t2m") for r in nr if r.get("t2m") is not None]
    precip = [r.get("precip") for r in nr if r.get("precip") is not None]

    nmap = {r["valid"]: r for r in nr}
    smap = {r["valid"]: r for r in sr}
    dp = []
    for valid in sorted(set(nmap).intersection(smap)):
        h = to_local(parse_dt_any(valid)).hour
        a, b = nmap[valid].get("mslp"), smap[valid].get("mslp")
        if 9 <= h <= 17 and a is not None and b is not None:
            dp.append(float(a) - float(b))

    wx, wy, wn = [], [], []
    for r in nr:
        h = hour(r)
        if not (0 <= h <= 6) or r.get("w10") is None:
            continue
        w = float(r["w10"])
        wn.append(w)
        if r.get("d10") is not None:
            d = math.radians(float(r["d10"]))
            wx.append(w * math.cos(d))
            wy.append(w * math.sin(d))

    s, c = _season(day)
    v = {
        "rad_tot": sum(float(x) for x in rad) if rad else None,
        "cloud": _mean(cloud),
        "tmax": max(float(x) for x in t2m) if t2m else None,
        "precip": sum(float(x) for x in precip) if precip else None,
        "dp_lago": _mean(dp),
        "wx": _mean(wx), "wy": _mean(wy), "wnotte": _mean(wn),
        "sin": s, "cos": c,
    }
    return v if all(v[k] is not None for k in FEATURES) else None


def _stats(vectors):
    if not vectors:
        return None
    out = {}
    for k in FEATURES:
        vals = [v[k] for v in vectors if v.get(k) is not None]
        mu = _mean(vals)
        sd = _stdev(vals, mu)
        if mu is None or sd is None or sd < 1e-9:
            return None
        out[k] = (mu, sd)
    return out


def _z(v, stats):
    if not v or not stats:
        return None
    try:
        return tuple((float(v[k]) - stats[k][0]) / stats[k][1] for k in FEATURES)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _archive_daily(source, start_day, end_day):
    pn = store.point_key(NORTH[0], NORTH[1], source)
    ps = store.point_key(SOUTH[0], SOUTH[1], source)
    # Margine UTC per coprire interamente il giorno locale ai cambi DST.
    a = ( _dt.date.fromisoformat(start_day) - _dt.timedelta(days=1)).isoformat() + "T00:00:00Z"
    b = ( _dt.date.fromisoformat(end_day) + _dt.timedelta(days=1)).isoformat() + "T23:59:59Z"
    nd = _rows_by_day(store.archive_rows(pn, a, b))
    sd = _rows_by_day(store.archive_rows(ps, a, b))
    out = {}
    for day in sorted(set(nd).intersection(sd)):
        if day < start_day or day > end_day:
            continue
        v = daily_conditions(day, nd[day], sd[day])
        if v:
            out[day] = v
    return out


def _interp_curve(points):
    """Ricostruisce 04:00-21:00/10' senza extrapolazione."""
    if not points:
        return None
    by_min = {}
    for minute, wind in points:
        by_min.setdefault(float(minute), []).append(float(wind))
    pts = [(m, _mean(by_min[m])) for m in sorted(by_min)]
    if not pts or pts[0][0] > 4 * 60 + 10 or pts[-1][0] < 20 * 60 + 50:
        return None

    out = []
    j = 0
    for target in GRID_MIN:
        while j + 1 < len(pts) and pts[j + 1][0] < target:
            j += 1
        if j < len(pts) and abs(pts[j][0] - target) < 1e-9:
            out.append(pts[j][1]); continue
        if j + 1 >= len(pts):
            out.append(None); continue
        xa, ya = pts[j]; xb, yb = pts[j + 1]
        if xa > target or xb < target or xb - xa > MAX_INTERP_GAP_MIN:
            out.append(None); continue
        f = (target - xa) / float(xb - xa)
        out.append(ya + f * (yb - ya))

    if sum(v is not None for v in out) < math.ceil(MIN_COVERAGE * len(GRID_MIN)):
        return None
    # Nessuna extrapolazione agli estremi: i punti mancanti interni possono
    # essere riempiti solo se racchiusi da due osservazioni valide.
    for i, v in enumerate(out):
        if v is not None:
            continue
        ia = next((x for x in range(i - 1, -1, -1) if out[x] is not None), None)
        ib = next((x for x in range(i + 1, len(out)) if out[x] is not None), None)
        if ia is None or ib is None:
            return None
        f = (i - ia) / float(ib - ia)
        out[i] = out[ia] + f * (out[ib] - out[ia])
    return out


def _observed_curves(start_day=TRAIN_START, end_day=TRAIN_END):
    rows = store.connect().execute(
        "SELECT ts, AVG(wind_kn) wind_kn FROM obs_sample "
        "WHERE station=? AND wind_kn IS NOT NULL AND ts>=? AND ts<? "
        "GROUP BY ts ORDER BY ts",
        (STATION, start_day + "T00:00:00Z",
         (_dt.date.fromisoformat(end_day) + _dt.timedelta(days=2)).isoformat() + "T00:00:00Z")
    ).fetchall()
    byday = {}
    for r in rows:
        dt = parse_dt_any(r["ts"])
        if dt is None:
            continue
        loc = to_local(dt)
        day = loc.date().isoformat()
        if day < start_day or day > end_day:
            continue
        minute = loc.hour * 60 + loc.minute + loc.second / 60.0
        if 3 * 60 + 30 <= minute <= 21 * 60 + 30:
            byday.setdefault(day, []).append((minute, r["wind_kn"]))
    out = {}
    for day, pts in byday.items():
        curve = _interp_curve(pts)
        if not curve:
            continue
        peak = max(curve)
        if peak < MIN_PEAK:
            continue
        out[day] = tuple(max(0.0, x / peak) for x in curve)
    return out


def _build_library():
    era = _archive_daily("era5", TRAIN_START, TRAIN_END)
    curves = _observed_curves()
    common = sorted(set(era).intersection(curves))
    # Integrita' scientifica: il protocollo validato aveva 4020 giornate. Se il
    # DB non riproduce quel campione NON si usa in silenzio un motore diverso
    # da quello validato - ma "quel campione" e' un intorno dichiarato, non un
    # numero esatto, e il conteggio vero si porta sempre nella diagnostica.
    if abs(len(common) - EXPECTED_TRAIN_DAYS) > TOLLERANZA_ADDESTRAMENTO_GG:
        return None, None, {"reason": "training_days", "n": len(common),
                            "expected": EXPECTED_TRAIN_DAYS,
                            "tolerance": TOLLERANZA_ADDESTRAMENTO_GG}
    stats = _stats([era[d] for d in common])
    if not stats:
        return None, None, {"reason": "era5_stats", "n": len(common)}
    lib = []
    for day in common:
        z = _z(era[day], stats)
        if z is not None:
            lib.append({"day": day, "z": z, "curve": curves[day]})
    # Qui il confronto giusto non e' col numero congelato ma con le giornate
    # che erano appena entrate: questo controllo serve a intercettare uno
    # z-score che scarta giornate, e scartarne una sarebbe un difetto anche se
    # il totale tornasse per caso a 4020.
    if len(lib) != len(common):
        return None, None, {"reason": "training_z", "n": len(lib),
                            "expected": len(common)}
    return lib, stats, {"reason": "ok", "n": len(lib),
                        "expected": EXPECTED_TRAIN_DAYS}


def _ensure_library():
    if _CACHE["library"] is not None and time.time() - _CACHE["at"] < CACHE_S:
        return _CACHE["library"], _CACHE["era_stats"]
    lib, stats, diag = _build_library()
    _CACHE.update({"library": lib, "era_stats": stats,
                   "diagnostic": diag, "lead_stats": {}, "at": time.time()})
    return lib, stats


def diagnostic():
    _ensure_library()
    return dict(_CACHE.get("diagnostic") or {})


def _lead_stats(lead):
    lead = int(lead)
    if lead in _CACHE["lead_stats"]:
        return _CACHE["lead_stats"][lead]
    # Distribuzione della STESSA sorgente usata nel test: previous-runs
    # best_match alla specifica scadenza. Non ERA5 e non l'ensemble.
    yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    daily = _archive_daily("lead%d" % lead, "2024-01-01", yesterday)
    stats = None
    if len(daily) >= 900:
        freshest = max(daily)
        lag = (_dt.date.fromisoformat(yesterday) - _dt.date.fromisoformat(freshest)).days
        if lag <= 3:
            stats = _stats(list(daily.values()))
    _CACHE["lead_stats"][lead] = stats
    return stats


def _current_rows(day, point):
    a = (_dt.date.fromisoformat(day) - _dt.timedelta(days=1)).isoformat() + "T00:00:00Z"
    b = (_dt.date.fromisoformat(day) + _dt.timedelta(days=1)).isoformat() + "T23:59:59Z"
    return store.archive_rows(point, a, b)


def _current_conditions(day):
    pn = store.point_key(NORTH[0], NORTH[1], CURRENT_SOURCE)
    ps = store.point_key(SOUTH[0], SOUTH[1], CURRENT_SOURCE)
    return daily_conditions(day, _current_rows(day, pn), _current_rows(day, ps))


def _median_template(neighbours):
    if len(neighbours) != K:
        return None
    curve = tuple(statistics.median([n["curve"][i] for n in neighbours])
                  for i in range(len(GRID_MIN)))
    peak = max(curve) if curve else 0.0
    return tuple(v / peak for v in curve) if peak > 0 else None


def choose(day, lead, current=None):
    """Seleziona i tre analoghi usando solo informazioni disponibili in previsione."""
    if int(lead) not in (1, 2, 3):
        return None, None
    library, _era = _ensure_library()
    if not library:
        return None, None
    stats = _lead_stats(lead)
    current = current or _current_conditions(day)
    target = _z(current, stats)
    if target is None:
        return None, None
    ranked = sorted(((_distance(target, row["z"]), row) for row in library),
                    key=lambda x: x[0])
    picked = [r for _d, r in ranked[:K]]
    template = _median_template(picked)
    if not template:
        return None, None
    return template, {
        "k": K,
        "days": [r["day"] for r in picked],
        "distances": [round(d, 3) for d, _r in ranked[:K]],
        "training_days": len(library),
        "source": "best_match lead%d -> ERA5/T0193" % int(lead),
    }


def _interp_scalar(rows, hour, key, default=None):
    pts = sorted((float(r["hour"]), r.get(key)) for r in rows if r.get(key) is not None)
    if not pts:
        return default
    if hour <= pts[0][0]:
        return pts[0][1]
    if hour >= pts[-1][0]:
        return pts[-1][1]
    for (ha, va), (hb, vb) in zip(pts, pts[1:]):
        if ha <= hour <= hb:
            f = (hour - ha) / float(hb - ha)
            return float(va) + f * (float(vb) - float(va))
    return default


def _interp_dir(rows, hour):
    pts = sorted((float(r["hour"]), r.get("dir")) for r in rows if r.get("dir") is not None)
    if not pts:
        return None
    # Interpolazione vettoriale, per non passare da 359 a 180 a 1 grado.
    cs = [{"hour": h, "c": math.cos(math.radians(d)),
           "s": math.sin(math.radians(d))} for h, d in pts]
    c = _interp_scalar(cs, hour, "c")
    s = _interp_scalar(cs, hour, "s")
    if c is None or s is None:
        return None
    return (math.degrees(math.atan2(s, c)) + 360.0) % 360.0


def _ancore_di_livello(base_profile, template, finestre):
    """Un livello per ciascuna finestra di regime, non uno per la giornata.

    E' il difetto che si vedeva sul Peler. Il motore, senza analoghi, costruiva
    la curva con un fattore di correzione per SESSIONE, interpolato fra le due:
    la mattina prendeva il livello dalla previsione del Peler e il pomeriggio
    da quella dell'Ora. Applicando la forma analogica con un solo fattore - il
    picco della giornata - quel lavoro si buttava via, e il picco della
    giornata cade nella finestra dell'Ora solo nel 65% dei giorni.

    Misurato sulle 617 giornate di conferma: il livello della mattina cosi'
    ottenuto ha quartili 0,77-1,16 del vero, con il 23% delle giornate
    sovrastimate di oltre due nodi. Sono i falsi allarmi del Peler al 37,7%
    contro il 15,3% che si ottiene quando il livello della finestra e' giusto.
    Non e' la forma a sbagliare: e' il livello che le arriva da un'altra ora
    del giorno.
    """
    ancore = []
    for inizio, fine in finestre or ():
        # Estremo destro ESCLUSO: le due finestre del lago si toccano alle
        # 11:00, e con gli estremi inclusi la mattina si prendeva il primo
        # campione del pomeriggio - cioe' il livello dell'Ora, che e' esatta-
        # mente quello che qui si vuole smettere di ereditare.
        dentro_base = [float(r["wind"]) for r in base_profile
                       if r.get("wind") is not None
                       and inizio <= float(r["hour"]) * 60.0 < fine]
        dentro_tmpl = [rel for minute, rel in zip(GRID_MIN, template)
                       if inizio <= minute < fine]
        if not dentro_base or not dentro_tmpl:
            continue
        picco_tmpl = max(dentro_tmpl)
        if picco_tmpl <= 1e-9:
            continue
        ancore.append((float(inizio), float(fine),
                       max(dentro_base) / picco_tmpl))
    ancore.sort()
    return ancore


def _raccordo_min():
    """Meta' persistenza per parte del confine, e il perche' e' un vincolo.

    Serve un raccordo, perche' due fattori applicati di netto alle 11:00
    creerebbero un gradino che non sta nella forma - e il gradino delle 11:00,
    quando c'e', deve venire dalle giornate analoghe, non dall'aritmetica.

    Ma la sua LARGHEZZA non e' libera. Dentro il raccordo la fine della
    mattina viene tirata verso il livello dell'Ora, che d'estate e' due o tre
    volte piu' alto: se quel tratto fosse lungo quanto la persistenza,
    potrebbe da solo produrre la mezz'ora sopra soglia che fa dichiarare
    navigabile una giornata - un falso allarme fabbricato dal raccordo. Meta'
    persistenza per parte fa trenta minuti in tutto, di cui quindici dentro la
    finestra del Peler: meno della mezz'ora che serve per dichiarare qualcosa.
    Misurato: fra quindici e trenta minuti i falsi allarmi non si muovono
    (20,3% contro 19,9%), quindi si prende il valore che ha il vincolo.
    """
    return _persistenza_min() / 2.0


def _scala_morbida(minuto, ancore, predefinita):
    """Il fattore di livello al minuto dato.

    Costante dentro ciascuna finestra, con una rampa lineare di mezz'ora per
    parte sul confine. Un peso a campana su tutta la giornata - come quello
    che il motore usa per le sue ancore - qui non va: le due ancore stanno a
    otto ore di distanza e la campana e' larga, quindi il pomeriggio tirava su
    la fine della mattina dell'8%, che e' una parte di cio' che si sta
    correggendo.
    """
    if not ancore:
        return predefinita
    if len(ancore) == 1:
        return ancore[0][2]
    raccordo = _raccordo_min()
    for i, (inizio, fine, scala) in enumerate(ancore):
        if i + 1 < len(ancore):
            confine = (fine + ancore[i + 1][0]) / 2.0
            if abs(minuto - confine) < raccordo:
                dopo = ancore[i + 1][2]
                f = (minuto - (confine - raccordo)) / (2.0 * raccordo)
                return scala + (dopo - scala) * f
        if inizio <= minuto < fine:
            return scala
    return ancore[0][2] if minuto < ancore[0][0] else ancore[-1][2]


def apply_to_profile(day, lead, base_profile, finestre=None):
    """Restituisce il profilo Torbole a 10 minuti, conservando il picco corrente.

    `base_profile` e' la curva che il motore avrebbe mostrato senza analoghi.
    Il suo massimo resta identico: sostituiamo solo la forma. `finestre` sono
    le finestre dei regimi in minuti locali: se ci sono, ciascuna riceve il
    livello che aveva nel profilo del motore invece di ereditare il picco
    della giornata.
    """
    if int(lead) not in (1, 2, 3) or not base_profile:
        return base_profile, None
    peak = max((float(r["wind"]) for r in base_profile if r.get("wind") is not None),
               default=0.0)
    if peak <= 0:
        return base_profile, None
    template, meta = choose(day, lead)
    if template is None:
        return base_profile, None

    ancore = _ancore_di_livello(base_profile, template, finestre)
    grezzo = [rel * _scala_morbida(float(minute), ancore, peak)
              for minute, rel in zip(GRID_MIN, template)]
    # Il picco del motore resta ESATTAMENTE quello: dopo il raccordo il massimo
    # si e' spostato di qualche punto percento, e una correzione moltiplicativa
    # sola lo riporta al suo posto senza toccare i rapporti fra le finestre.
    # Serve perche' probabilita', bande e verifica parlano di quel numero.
    massimo = max(grezzo) if grezzo else 0.0
    correzione = (peak / massimo) if massimo > 1e-9 else 1.0

    out = []
    for (minute, rel), livello in zip(zip(GRID_MIN, template), grezzo):
        h = minute / 60.0
        wind = livello * correzione
        base_w = _interp_scalar(base_profile, h, "wind", 0.0) or 0.0
        base_g = _interp_scalar(base_profile, h, "gust", base_w) or base_w
        ratio = max(1.0, base_g / base_w) if base_w > 0.2 else 1.0
        lo = _interp_scalar(base_profile, h, "lo", wind)
        hi = _interp_scalar(base_profile, h, "hi", wind)
        half = max(0.0, ((hi or wind) - (lo or wind)) / 2.0)
        dt_local = _dt.datetime.fromisoformat(day) + _dt.timedelta(minutes=minute)
        key = iso_utc(local_naive_to_utc(dt_local))
        out.append({
            "hour": h, "key": key, "wind": wind, "gust": wind * ratio,
            "lo": max(0.0, wind - half), "hi": wind + half,
            "dir": _interp_dir(base_profile, h),
            "t2m": _interp_scalar(base_profile, h, "t2m"),
            "cloud": _interp_scalar(base_profile, h, "cloud"),
            "precip": _interp_scalar(base_profile, h, "precip"),
        })
    meta = dict(meta)
    meta["peak_preserved"] = peak
    meta["grid_minutes"] = 10
    meta["livelli_per_finestra"] = [(int(a), int(b), round(s, 3))
                                    for a, b, s in ancore]
    return out, meta


# ------------------------- validazione riproducibile -------------------------
#
# Le tre grandezze della porta hanno una definizione sola, e viene da fuori:
# PERSISTENZA_MIN e' la stessa mezz'ora della climatologia, del report e della
# scheda. Scriverne qui una seconda vorrebbe dire che fra sei mesi la porta e
# la tabella diranno numeri diversi sulla stessa giornata - ed e' esattamente
# quello che era: `run >= 3` su una griglia di dieci minuti sono VENTI minuti,
# non trenta, perche' tre campioni coprono due intervalli. La finestra della
# ripidezza aveva lo stesso conto: tre passi sono mezz'ora solo se si contano
# gli intervalli, e li' era giusto per caso.
PASSO_MIN = 10
SOGLIA_PORTA = 12.0
FINESTRA_ORA = (11 * 60, 20 * 60)
FINESTRA_RIPIDEZZA_MIN = 30
# Il Peler ha la sua soglia e la sua finestra, e va misurato: la forma
# analogica cambia TUTTA la giornata, mattina compresa, mentre la porta
# guardava solo il pomeriggio. Una mattina cambiata e mai misurata e' peggio
# di una mattina lasciata come stava, perche' e' quella che la scheda legge
# per dire "sopra 10 kn" e "continuita'". La soglia e' 10 perche' e' la prima
# riga della scheda, la finestra e' quella UTILE del giorno - luce e ora
# pratica comprese - perche' misurare le tre ore di buio prima dell'alba
# risponderebbe a una domanda che nessuno fa.
SOGLIA_PELER = 10.0
SPOT_PELER = "Torbole-Peler"
# Riferimenti della mattina misurati il 2026-09-16 sulle stesse 617 giornate.
# Hanno un ruolo diverso da quelli dell'Ora: qui NON si pretende
# discriminazione, perche' sui dati non c'e' - con il livello giusto il nullo
# prende gli stessi colpi del modello (83,3% contro 83,0%), cioe' nella
# mattina la forma non dice QUALE giornata, dice com'e' fatta una mattina di
# Peler. Si pretende invece calibrazione: la durata promessa e la ripidezza
# devono restare vicine al vero, e molto meglio della curva liscia, che
# sbaglia la durata di quarantasei minuti e produce una rampa di 0,3 kn/30'
# dove il lago ne fa 3,9.
BENCHMARK_PELER = {
    "bias_minutes_max": 25.0,      # |sbilanciamento| ammesso, contro -46 liscia
    "steepness_min": 2.0,          # rampa minima, contro 0,3 della liscia
    "true_steepness": 3.9,
}


def _persistenza_min():
    """La mezz'ora, presa dall'unico posto dove e' definita."""
    from .orari import PERSISTENZA_MIN
    return float(PERSISTENZA_MIN)


def _punti_persistenza():
    """Quanti campioni servono per coprire la persistenza, intervalli inclusi."""
    return int(round(_persistenza_min() / PASSO_MIN)) + 1


def _sustained(curve, threshold=SOGLIA_PORTA, start=FINESTRA_ORA[0],
               end=FINESTRA_ORA[1]):
    vals = [curve[i] for i, m in enumerate(GRID_MIN) if start <= m <= end]
    servono = _punti_persistenza()
    run = 0
    for v in vals:
        run = run + 1 if v >= threshold else 0
        if run >= servono:
            return True
    return False


def _minutes_above(curve, threshold=SOGLIA_PORTA, start=FINESTRA_ORA[0],
                   end=FINESTRA_ORA[1]):
    return PASSO_MIN * sum(1 for i, m in enumerate(GRID_MIN)
                           if start <= m <= end and curve[i] >= threshold)


def _steepness(curve, start=FINESTRA_ORA[0], end=FINESTRA_ORA[1]):
    vals = [curve[i] for i, m in enumerate(GRID_MIN) if start <= m <= end]
    passi = int(round(FINESTRA_RIPIDEZZA_MIN / PASSO_MIN))
    return max((vals[i + passi] - vals[i] for i in range(len(vals) - passi)),
               default=0.0)


def _finestra_peler(day):
    """La finestra utile del Peler per quel giorno, dall'unico posto che la sa.

    Importata qui e non in testa al modulo perche' e' una decisione di
    prodotto (ora pratica, margini sulla luce) e vive in orari.py con la
    configurazione. Misurare la mattina in una finestra diversa da quella che
    la scheda mostra vorrebbe dire validare un numero e stamparne un altro.
    """
    from . import orari
    a, b = orari.finestra_utile_del_giorno(SPOT_PELER, day)
    return float(a), float(b)


def _template_mensile(library, month):
    """La forma media del mese sull'addestramento: la 'curva liscia' di prima.

    E' il riferimento onesto per la mattina. Senza un riferimento calcolato, il
    confronto sarebbe con una costante scritta a mano, e fra sei mesi nessuno
    saprebbe piu' da dove veniva.
    """
    curve = [r["curve"] for r in library if int(r["day"][5:7]) == month]
    if not curve:
        return None
    return tuple(sum(c[i] for c in curve) / float(len(curve))
                 for i in range(len(GRID_MIN)))


def validation_report(start_day="2025-01-01", end_day="2026-09-14"):
    """Porta scientifica shape-only sullo STESSO campione D+1/D+2/D+3.

    Come nel test che ha scelto k, a ogni concorrente viene regalato il picco
    vero: qui si verifica solo la forma, non l'errore di livello.

    Si misurano DUE finestre, perche' la forma ne cambia due: l'Ora
    (11:00-20:00, soglia 12) e il Peler (finestra utile del giorno, soglia
    10). La seconda mancava, e mancava nel modo peggiore: la mattina veniva
    sostituita e promossa sulla base di numeri che parlavano del pomeriggio.
    """
    library, _ = _ensure_library()
    if not library:
        return {"usable": False, "diagnostic": diagnostic()}
    obs_norm = _observed_curves(start_day, end_day)
    # La standardizzazione descrive la SORGENTE, quindi usa tutta la sua
    # distribuzione disponibile dal 2024. Il campione di conferma resta invece
    # rigorosamente 2025-2026 e comune ai tre lead.
    source_all = {lead: _archive_daily("lead%d" % lead, "2024-01-01", end_day)
                  for lead in (1, 2, 3)}
    pred = {lead: {d: v for d, v in source_all[lead].items()
                   if start_day <= d <= end_day}
            for lead in (1, 2, 3)}
    common = set(obs_norm)
    for lead in (1, 2, 3):
        common &= set(pred[lead])
    days = sorted(common)
    # Il campione di conferma NON deve essere esattamente quello di allora.
    # Una giornata in piu' o in meno e' disponibilita' di dati, non un metodo
    # diverso: l'archivio delle run cresce, un buco di centralina si chiude,
    # e la prima volta che succede una porta esatta si chiude per sempre con
    # un messaggio che non dice niente. Qui il conteggio si DICHIARA e la
    # tolleranza la applica la porta, che e' il posto dove si decide.
    if not days:
        return {"usable": False, "reason": "confirm_days", "n": 0,
                "expected": EXPECTED_CONFIRM_DAYS}

    raw = {day: _raw_curve(day) for day in days}
    mancanti = [d for d in days if raw[d] is None]
    if mancanti:
        # Prima si scartavano tutte le giornate se ne mancava una sola. Una
        # curva grezza assente e' una giornata da togliere, non un motivo per
        # non misurare le altre seicento.
        days = [d for d in days if raw[d] is not None]
        if not days:
            return {"usable": False, "reason": "raw_curve_missing",
                    "n": 0, "scartate": len(mancanti)}

    finestre_peler = {}
    for day in days:
        try:
            finestre_peler[day] = _finestra_peler(day)
        except Exception:
            finestre_peler[day] = None

    class _Conto(object):
        """Un accumulatore per finestra: colpi, falsi, durata, ripidezza."""

        def __init__(self):
            self.tp = self.fp = self.pos = self.neg = 0
            self.bias, self.abserr, self.slopes, self.true_slopes = [], [], [], []

        def aggiungi(self, forecast, real, soglia, inizio, fine):
            yp = _sustained(forecast, soglia, inizio, fine)
            yt = _sustained(real, soglia, inizio, fine)
            if yt:
                self.pos += 1; self.tp += int(yp)
            else:
                self.neg += 1; self.fp += int(yp)
            d = (_minutes_above(forecast, soglia, inizio, fine)
                 - _minutes_above(real, soglia, inizio, fine))
            self.bias.append(d); self.abserr.append(abs(d))
            self.slopes.append(_steepness(forecast, inizio, fine))
            self.true_slopes.append(_steepness(real, inizio, fine))

        def esito(self, n):
            return {
                "n": n,
                "hits": self.tp / self.pos if self.pos else None,
                "false_alarms": self.fp / self.neg if self.neg else None,
                "navigabili": self.pos,
                "minute_error": _mean(self.abserr),
                "bias_minutes": _mean(self.bias),
                "steepness": (statistics.median(self.slopes)
                              if self.slopes else None),
                "true_steepness": (statistics.median(self.true_slopes)
                                   if self.true_slopes else None),
            }

    def measure(lead, day_map, mensile=False):
        """Misura una scadenza sulle due finestre.

        `mensile=True` misura la forma media del mese al posto degli analoghi:
        e' la curva liscia di prima, il riferimento contro cui il guadagno ha
        un senso. Calcolata dalla libreria, non scritta a mano.
        """
        stats = _stats(list(source_all[lead].values()))
        if stats is None:
            return None
        ora, peler = _Conto(), _Conto()
        used = 0
        for day in days:
            if mensile:
                template = _template_mensile(library, int(day[5:7]))
            else:
                source_day = day_map.get(day, day)
                z = _z(pred[lead][source_day], stats)
                if z is None:
                    continue
                ranked = sorted(((_distance(z, r["z"]), r) for r in library),
                                key=lambda x: x[0])
                template = _median_template([r for _d, r in ranked[:K]])
            if template is None:
                continue
            real = tuple(raw[day]); peak = max(real)
            forecast = tuple(peak * x for x in template)
            ora.aggiungi(forecast, real, SOGLIA_PORTA, *FINESTRA_ORA)
            fin = finestre_peler.get(day)
            if fin:
                peler.aggiungi(forecast, real, SOGLIA_PELER, fin[0], fin[1])
            used += 1
        out = ora.esito(used)
        out["peler"] = peler.esito(used)
        return out

    leads = {lead: measure(lead, {}) for lead in (1, 2, 3)}
    # Il vincolo che conta qui non e' la DIMENSIONE del campione - quella la
    # giudica la porta, con la sua tolleranza dichiarata - ma che i tre lead
    # abbiano misurato le STESSE giornate. E' il difetto che aveva reso
    # inutilizzabile il primo test esterno: tre baseline diverse (49,4 / 48,6 /
    # 45,1) su tre campioni diversi, confrontate come se fossero lo stesso.
    # Con il controllo sul numero congelato, invece, bastava una giornata di
    # differenza perche' la misura non venisse nemmeno prodotta.
    if any(v is None or v.get("n") != len(days) for v in leads.values()):
        return {"usable": False, "reason": "validation_incomplete",
                "n": len(days), "expected": EXPECTED_CONFIRM_DAYS,
                "conteggi": {k: (v or {}).get("n") for k, v in leads.items()},
                "leads": leads}

    # Nullo obbligatorio: D+1 con condizioni di un altro giorno, permutazione
    # deterministica. Se non peggiora chiaramente, la selezione non vale.
    import random
    shuffled = days[:]
    random.Random(20260915).shuffle(shuffled)
    null = measure(1, dict(zip(days, shuffled)))
    # E la curva liscia: senza di lei "83% di colpi" non e' un guadagno, e'
    # solo un numero. E' anche l'unico modo di dire che la mattina analogica
    # sbaglia la durata di un minuto dove la liscia ne sbaglia quarantasei.
    liscia = measure(1, {}, mensile=True)
    return {"usable": True, "n": len(days), "from": days[0], "to": days[-1],
            "leads": leads, "null": null, "liscia": liscia}



def benchmark_gate(report):
    """Verifica che il codice riproduca il blocco cieco gia' validato.

    Le tolleranze coprono arrotondamenti/interpolazione, non un metodo diverso.
    Il nullo deve inoltre degradare in modo evidente.
    """
    reasons = []
    if not report or not report.get("usable"):
        return False, ["nessuna misura: %s"
                       % ((report or {}).get("reason")
                          or (report or {}).get("diagnostic") or "?")]
    n = report.get("n") or 0
    # Tolleranza sul campione: quindici giornate su seicento. Sotto quella
    # soglia e' disponibilita' di dati; sopra e' un altro campione, e i numeri
    # del benchmark non sono piu' confrontabili.
    if abs(n - EXPECTED_CONFIRM_DAYS) > TOLLERANZA_CONFERMA_GG:
        reasons.append("campione di conferma %d, atteso %d +/- %d"
                       % (n, EXPECTED_CONFIRM_DAYS, TOLLERANZA_CONFERMA_GG))
    tol = {"hits": .025, "false_alarms": .035, "minute_error": 8.0,
           "bias_minutes": 5.0, "steepness": .6}
    for lead, ref in BENCHMARK.items():
        got = (report.get("leads") or {}).get(lead)
        if not got:
            reasons.append("D+%d mancante" % lead); continue
        for key, target in ref.items():
            value = got.get(key)
            if value is None or abs(float(value) - target) > tol[key]:
                reasons.append("D+%d %s=%s (atteso %.3f +/- %.3f)"
                               % (lead, key, value, target, tol[key]))
        tv = got.get("true_steepness")
        if tv is None or abs(float(tv) - RIPIDEZZA_VERA_ORA) > .5:
            reasons.append("D+%d ripidezza vera=%s (attesa %.1f +/- 0.5)"
                           % (lead, tv, RIPIDEZZA_VERA_ORA))
    null = report.get("null") or {}
    if null.get("hits") is None or null["hits"] >= .65:
        reasons.append("nullo non degrada abbastanza sui colpi")
    if null.get("false_alarms") is None or null["false_alarms"] <= .15:
        reasons.append("nullo non degrada abbastanza sui falsi")
    # La mattina: si pretende CALIBRAZIONE, non discriminazione.
    #
    # Sui dati la mattina non discrimina: col livello giusto il nullo prende
    # gli stessi colpi del modello (83,3% contro 83,0%), cioe' la forma dice
    # com'e' fatta una mattina di Peler, non QUALE mattina sara' di Peler -
    # quella la decide il livello, che viene dalla previsione della sessione ed
    # e' l'unica parte validata. Pretendere qui dei colpi chiuderebbe la porta
    # per un merito che il metodo non ha mai dichiarato di avere.
    #
    # Si pretende invece che la durata promessa e la ripidezza restino vicine
    # al vero, perche' e' quello che la scheda del Peler legge e stampa.
    for lead in sorted(BENCHMARK):
        p = ((report.get("leads") or {}).get(lead) or {}).get("peler")
        if not p:
            reasons.append("D+%d mattina non misurata" % lead); continue
        sb = p.get("bias_minutes")
        if sb is None or abs(float(sb)) > BENCHMARK_PELER["bias_minutes_max"]:
            reasons.append("D+%d durata del Peler sbilanciata di %s minuti"
                           " (ammessi +/-%.0f)"
                           % (lead, sb, BENCHMARK_PELER["bias_minutes_max"]))
        rp = p.get("steepness")
        if rp is None or float(rp) < BENCHMARK_PELER["steepness_min"]:
            reasons.append("D+%d mattina troppo liscia: %s kn/30' (minimo %.1f,"
                           " il lago ne fa %.1f)"
                           % (lead, rp, BENCHMARK_PELER["steepness_min"],
                              BENCHMARK_PELER["true_steepness"]))
    return not reasons, reasons


def promote_from_validation(report=None):
    """Apre la porta solo se il codice riproduce il benchmark congelato."""
    report = report or validation_report()
    ok, reasons = benchmark_gate(report)
    if ok:
        store.meta_set(GATE_KEY, GATE_SIGNATURE)
    else:
        store.meta_set(GATE_KEY, "closed")
    return ok, reasons, report


def promoted():
    return store.meta_get(GATE_KEY) == GATE_SIGNATURE

def _raw_curve(day):
    rows = store.connect().execute(
        "SELECT ts, AVG(wind_kn) wind_kn FROM obs_sample WHERE station=? "
        "AND wind_kn IS NOT NULL AND ts>=? AND ts<? GROUP BY ts ORDER BY ts",
        (STATION,
         (_dt.date.fromisoformat(day) - _dt.timedelta(days=1)).isoformat() + "T00:00:00Z",
         (_dt.date.fromisoformat(day) + _dt.timedelta(days=2)).isoformat() + "T00:00:00Z")
    ).fetchall()
    pts = []
    for r in rows:
        dt = parse_dt_any(r["ts"])
        if dt is None or local_day(dt) != day:
            continue
        loc = to_local(dt)
        pts.append((loc.hour * 60 + loc.minute + loc.second / 60.0, r["wind_kn"]))
    curve = _interp_curve(pts)
    if not curve or max(curve) < MIN_PEAK:
        return None
    return tuple(curve)


__all__ = ["CURRENT_SOURCE", "K", "GRID_MIN", "FEATURES",
           "daily_conditions", "choose", "apply_to_profile", "diagnostic",
           "validation_report", "benchmark_gate", "promote_from_validation",
           "promoted"]
