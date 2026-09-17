"""Forma intraday di Torbole da analoghi storici osservati.

Questo modulo modifica SOLO la forma temporale del profilo di giornata.
Il LIVELLO resta quello prodotto dal motore corrente, e "livello" vuol dire
una grandezza precisa: il massimo delle medie orarie nella finestra, che e' su
cosa il motore e' addestrato. Non il massimo istantaneo della curva a dieci
minuti, che e' mediamente l'11% piu' alto e che il motore non prevede.
Confondere le due cose e' stato il difetto piu' costoso di questo modulo: vedi
livello_orario.

Protocollo validato (da non cambiare senza nuova validazione):
- condizioni previste da best_match alle scadenze in LEADS;
- ciascuna sorgente standardizzata sulla propria distribuzione;
- archivio analoghi ERA5 + curve osservate T0193, training fino al 2023;
- k=9 vicini euclidei nello spazio standardizzato (vedi K);
- mediana punto per punto delle curve normalizzate, griglia 10 minuti;
- ancoraggio sul massimo delle medie orarie, la stessa operazione sui due lati;
- nessun allineamento sull'ora d'ingresso.

Cosa questa forma NON fa, misurato e scritto in docs/STRADE-CHIUSE.md: non
discrimina. Quali giornate saranno navigabili lo decide il livello; la forma
dice com'e' fatta una giornata, e per dirlo non ha bisogno di sapere quale
giorno e'. Il vantaggio della scelta dei vicini sul nullo e' +1,0 punti
nell'Ora, intervallo da -2,7 a +5,0. Quello che la forma porta e' la
calibrazione: durata e ripidezza vicine al vero invece di una media piatta.
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
# Quante giornate storiche si mediano per fare la sagoma.
#
# Era 3, e 3 era stato scelto con l'ANCORA SBAGLIATA: la sagoma veniva portata
# al livello previsto imponendo il suo massimo istantaneo, mentre il motore
# prevede il massimo delle medie orarie (vedi livello_orario). Sotto quella
# configurazione la regola pre-registrata - falsi allarmi entro il 20% in
# selezione - non selezionava niente, perche' il k migliore sul 2024 ne faceva
# il 27,2%, e k era rimasto 3 per non scegliere dopo aver visto la conferma.
#
# Con l'ancora giusta i falsi allarmi scendono al 7% e quel vincolo non morde
# piu': k non era mai stato misurato nelle condizioni in cui il prodotto
# funziona adesso. Il criterio e' stato scritto in docs/STRADE-CHIUSE.md e
# messo nel repository (commit 52bfcc5) PRIMA della misura: colpi piu' alti
# sul 2024 nella finestra dell'Ora, sotto falsi <= 15% e |sbilanciamento della
# durata| <= 15 minuti, a pari colpi lo scarto di ripidezza dal vero piu'
# piccolo. Il secondo vincolo e' quello che rende la prova onesta: senza di
# lui vince k grandissimo, che e' la curva liscia, che prende i colpi perche'
# promette quarantadue minuti di troppo.
#
# Sul 2024 hanno pari colpi k=9 e k=15 (90,9%); lo scarto di ripidezza decide,
# 1,93 contro 2,38. Sulla conferma 2025-2026, mai guardata prima, k=9 batte
# k=3 su quasi tutto: nell'Ora colpi 93,3% contro 90,1% e falsi 5,5% contro
# 7,0% a D+1; nella mattina del Peler colpi 92,9% contro 83,9%, errore di
# durata 25 minuti contro 31, sbilanciamento +1 contro -9.
#
# Il prezzo e' la ripidezza: 5,44 contro 6,19, su una vera di 6,99. Una
# mediana di nove curve e' meno spigolosa di una mediana di tre. Ma lo scarto
# MEDIANO giorno per giorno fra promessa e vero e' 2,18 contro 2,27: k=9 non
# e' piu' lontano dal vero, e' meno lontano - la ripidezza mediana di k=3 era
# alta anche quando il giorno non la voleva.
K = 9
# Le scadenze su cui la forma analogica sostituisce quella dell'ensemble.
# Era scritta a mano in otto posti: in choose, in apply_to_profile, tre volte
# in validation_report, nella promozione, nel motore e nel comando. Otto copie
# di una decisione, e aggiungere una scadenza voleva dire trovarle tutte.
#
# D+4 e' entrato il 2026-09-16 dopo aver passato, sul blocco cieco 2025-2026,
# gli stessi criteri delle altre: vantaggio +51,4 con +15,3 punti sul proprio
# nullo, ripidezza 6,67, Peler sbilanciato di +13 minuti. La forma non
# peggiora con la scadenza - le condizioni che la decidono, stagione e
# gradiente e radiazione, sono piu' prevedibili del vento stesso.
#
# D+5 e' RIMASTO FUORI, e va detto perche': passa tutto tranne un criterio,
# lo sbilanciamento della durata del Peler, +26 minuti contro i 25 ammessi.
# Un minuto. Il limite era dichiarato prima, e spostarlo perche' un caso ci
# cade appena fuori e' la definizione di spostare il bersaglio. Se un giorno
# si vuole D+5, si ricava quel limite da un principio e si rimisura tutto,
# non si cambia il 25 in 30.
LEADS = (1, 2, 3, 4)
GRID_MIN = tuple(range(4 * 60, 21 * 60 + 1, 10))
MIN_COVERAGE = 0.90
MIN_PEAK = 6.0
MAX_INTERP_GAP_MIN = 30.0
CACHE_S = 12 * 60 * 60
CURRENT_SOURCE = "analog_live"
GATE_KEY = "analog_shape_gate_v1"
GATE_SIGNATURE = "torbole-analogs-k9-20260917"
# Numeri del blocco cieco 2025-2026 con k=9 e l'ancora oraria, rimisurati il
# 2026-09-17. Non servono a ottimizzare nulla: sono una firma di regressione,
# e le tolleranze sono BANDE, non riproduzioni a cifre decimali. Il motivo di
# quella scelta e' costato due giorni: i numeri li misuro fuori dal prodotto
# (curve osservate, libreria e scelta dei vicini calcolate a parte, ma
# scalatura e metriche chiamate da QUESTO modulo), e una differenza di
# standardizzazione fra il mio calcolo e il motore - che in produzione non
# conosce il futuro e usa tutta la sorgente dal 2024 - sposta i falsi allarmi
# di tre o quattro punti. Una tolleranza da cifra decimale su un numero
# misurato altrove chiude la porta per sempre e non dice perche'.
#
# Quello che le bande DEVONO catturare e' un cambio di configurazione, non un
# decimale. La prova: con l'ancora sbagliata i falsi allarmi a D+1 erano 36,3%
# contro 5,5%, e nessuna banda ragionevole li confonde.
#
# Il resto della porta non e' fatto di numeri congelati ma di RELAZIONI
# misurate dentro lo stesso rapporto - la forma analogica contro la curva
# liscia e contro il nullo, sulle stesse giornate. Una relazione sopravvive
# alla deriva dei dati; un valore assoluto no.
BENCHMARK = {
    1: {"hits": .933, "false_alarms": .055, "minute_error": 58.0,
        "bias_minutes": 7.0, "steepness": 5.44},
    2: {"hits": .945, "false_alarms": .055, "minute_error": 60.0,
        "bias_minutes": 10.0, "steepness": 5.41},
    3: {"hits": .952, "false_alarms": .055, "minute_error": 57.0,
        "bias_minutes": 13.0, "steepness": 5.35},
    4: {"hits": .962, "false_alarms": .050, "minute_error": 61.0,
        "bias_minutes": 13.0, "steepness": 5.29},
}
# Le bande, dichiarate qui e non sparse nella porta. La porta controlla le
# chiavi di QUESTO dizionario, non quelle di BENCHMARK: cosi' un numero puo'
# stare nel benchmark come registrazione di cio' che si e' misurato senza
# diventare per forza un cancello.
#
# `false_alarms` non c'e', ed e' una scelta. Sui falsi allarmi il requisito e'
# il BUDGET (BUDGET_FALSI, 15%), che e' una promessa all'utente e si spiega da
# sola. Una banda centrata sul misurato - 5,5% piu' o meno sei punti - sarebbe
# piu' stretta del budget, quindi il budget non potrebbe mai scattare: due
# guardie sullo stesso numero, di cui una muta. E la banda non serve nemmeno
# per riconoscere la configurazione, perche' l'ancora sbagliata dava il 36,3%
# e il budget lo prende di gran lunga.
TOLLERANZA_BENCHMARK = {"hits": .06, "minute_error": 12.0,
                        "bias_minutes": 10.0, "steepness": 1.0}
# La ripidezza VERA nella finestra dell'Ora, sulle giornate di conferma: e' una
# proprieta' del lago, non del codice, e serve da controllo di sanita' del
# campione. Se cambia, non stiamo guardando le stesse giornate.
RIPIDEZZA_VERA_ORA = 7.0
# Il budget dei falsi allarmi, che e' una decisione di prodotto e non una
# misura: quante volte si accetta di far venire qualcuno al lago per niente.
# Misurato 5,5%; il budget e' 15%.
BUDGET_FALSI = .15
#
# Le tre relazioni che la porta pretende, e perche' sono TRE e non una.
#
# Quello che la forma analogica porta non e' discriminazione: e' calibrazione.
# Nella finestra dell'Ora, regalando a tutti il livello vero, il vantaggio
# (colpi meno falsi) della forma analogica sul NULLO - le stesse sagome
# assegnate al giorno sbagliato - e' +1,0 punti con intervallo al 95% da -2,7
# a +5,0: include lo zero. La scelta dei vicini non discrimina meglio del
# caso, e nella mattina lo sapevamo gia'. Pretendere qui dei colpi in piu' del
# nullo chiuderebbe la porta per un merito che il metodo non ha mai avuto.
#
# E contro la curva liscia la forma analogica PERDE sul binario: -3,8 punti,
# intervallo da -7,1 a -0,4. La liscia prende il 98,1% delle giornate
# navigabili e li paga promettendo quarantadue minuti di vento in piu' di
# quanto ce n'e'. Una curva troppo lunga supera per costruzione una soglia di
# mezz'ora: i suoi colpi sono comprati con lo stesso errore che li rende
# inutili sulla scheda.
#
# Quindi:
#   1. sui falsi allarmi si pretende il budget, che e' una promessa all'utente;
#   2. sul binario si pretende NON-DEGRADO, non vantaggio: la forma puo' stare
#      qualche punto sotto la liscia, non puo' crollare;
#   3. sulla calibrazione si pretende un vantaggio vero e misurato, perche' e'
#      quello che la scheda legge e stampa: lo sbilanciamento della durata e
#      lo scarto fra ripidezza promessa e ripidezza vera.
#
# Misurati a D+1: sbilanciamento 35,1 minuti meglio della liscia (intervallo da
# 28,8 a 41,6) e scarto di ripidezza 2,79 meglio (da 2,48 a 3,05). Le soglie
# sono meno della meta' di cio' che si e' misurato.
SVANTAGGIO_MAX_SU_LISCIA = 8.0
SVANTAGGIO_MAX_SU_NULLO = 5.0
SBIL_MEGLIO_DELLA_LISCIA_MIN = 15.0
SCARTO_RIP_MEGLIO_DELLA_LISCIA_MIN = 1.0
# E nella mattina, dove la calibrazione e' tutto il merito: l'errore di durata
# dev'essere piu' piccolo di quello della liscia. Misurato 25 minuti contro
# 34, cioe' nove; la soglia e' quattro, perche' sotto i quattro minuti su una
# griglia da dieci si sta leggendo rumore.
DURATA_MEGLIO_DELLA_LISCIA_MIN = 4.0
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
    if int(lead) not in LEADS:
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


MIN_CAMPIONI_ORA = 4


def livello_orario(punti, inizio, fine):
    """Il massimo delle medie orarie nella finestra.

    E' L'OPERAZIONE che definisce il bersaglio del motore: _compute_targets
    addestra sul massimo di `wind_mean` fra le ore della finestra. Quindi
    quando si scala una sagoma su un livello previsto, la stessa operazione va
    fatta sui due lati - altrimenti si mette un numero al posto di un altro.

    Era il difetto piu' costoso di tutta questa storia, e il piu' invisibile.
    Il motore prevede il massimo delle medie ORARIE; apply_to_profile lo
    imponeva come massimo del profilo a DIECI MINUTI. Misurato su 619
    giornate: il massimo orario vale 0,892 del massimo istantaneo (mediana) e
    corrisponde al quantile 0,909 della curva vera. Undici per cento di
    differenza sistematica, e in una direzione precisa: la sagoma di una
    giornata piena, scalata sul picco di una giornata a raffiche brevi,
    promette due ore di vento dove ce n'erano dieci minuti.

    In numeri, nella finestra dell'Ora sul blocco cieco: falsi allarmi dal
    35,8% al 9,0%, sbilanciamento della durata da +15 minuti a +1, senza un
    predittore nuovo e senza un dato nuovo. Non era la scelta dei vicini: era
    l'ancora.

    Non ha parametri: nessun quantile da scegliere, nessuna taratura
    possibile. La stessa operazione su entrambi i lati.
    """
    per_ora = {}
    for minuto, valore in punti:
        if valore is None or not (inizio <= minuto < fine):
            continue
        per_ora.setdefault(int(minuto // 60), []).append(float(valore))
    medie = [sum(v) / len(v) for v in per_ora.values()
             if len(v) >= MIN_CAMPIONI_ORA]
    return max(medie) if medie else None


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


def scala_sagoma(template, livelli, predefinito):
    """La sagoma portata ai livelli attesi. UN percorso, due chiamanti.

    `livelli` e' [(inizio, fine, livello_atteso)] in minuti locali, dove il
    livello atteso e' un MASSIMO DELLE MEDIE ORARIE: quello che il motore
    prevede, o quello misurato sulla giornata vera quando e' la porta a
    chiamare. Su entrambi i lati si applica la stessa operazione.

    Questa funzione esiste perche' prodotto e porta la chiamino entrambi. Ogni
    difetto grosso di questa settimana e' nato da due implementazioni della
    stessa idea che si credevano uguali: la persistenza, la ripidezza, la
    normalizzazione della sagoma. La porta deve misurare cio' che si spedisce,
    e il modo di esserne certi non e' rileggere il codice: e' che sia lo
    stesso codice.
    """
    ancore = []
    for inizio, fine, atteso in livelli or ():
        if atteso is None:
            continue
        liv_t = livello_orario(
            [(m, r) for m, r in zip(GRID_MIN, template)], inizio, fine)
        if not liv_t or liv_t <= 1e-9:
            continue
        ancore.append((float(inizio), float(fine), float(atteso) / liv_t))
    grezzo = [rel * _scala_morbida(float(minute), ancore, predefinito)
              for minute, rel in zip(GRID_MIN, template)]
    # Il livello del motore resta ESATTAMENTE quello, e "livello" vuol dire la
    # sua grandezza: il massimo delle medie orarie, non il massimo istantaneo.
    # Qui prima si forzava il massimo istantaneo della curva a dieci minuti a
    # valere il numero che il motore prevede per le medie orarie - lo stesso
    # scambio di grandezza, all'ultimo passo, che annullava tutto il resto.
    atteso_globale = max([a for _i, _f, a in livelli if a is not None] or [0.0])
    liv_finale = livello_orario(
        [(m, v) for m, v in zip(GRID_MIN, grezzo)],
        GRID_MIN[0], GRID_MIN[-1] + 1)
    if atteso_globale > 0 and liv_finale and liv_finale > 1e-9:
        k = atteso_globale / liv_finale
        grezzo = [v * k for v in grezzo]
    return grezzo, ancore


def apply_to_profile(day, lead, base_profile, finestre=None):
    """Il profilo Torbole a 10 minuti: forma dagli analoghi, livello dal motore.

    `base_profile` e' la curva che il motore avrebbe mostrato senza analoghi.
    Il suo LIVELLO resta quello: il massimo delle sue medie orarie, che e' la
    grandezza su cui il modello e' addestrato. Il massimo istantaneo della
    curva mostrata sara' piu' alto - una curva a dieci minuti supera le sue
    medie orarie, ed e' giusto che lo faccia - e questo e' il punto della
    correzione del 2026-09-17.
    """
    if int(lead) not in LEADS or not base_profile:
        return base_profile, None
    peak = max((float(r["wind"]) for r in base_profile if r.get("wind") is not None),
               default=0.0)
    if peak <= 0:
        return base_profile, None
    template, meta = choose(day, lead)
    if template is None:
        return base_profile, None

    # Il lato BASE e' gia' orario: il profilo del motore ha un punto per ora,
    # quindi il suo massimo nella finestra E' il massimo delle medie orarie.
    livelli = []
    for inizio, fine in finestre or ((GRID_MIN[0], GRID_MIN[-1] + 1),):
        dentro = [float(r["wind"]) for r in base_profile
                  if r.get("wind") is not None
                  and inizio <= float(r["hour"]) * 60.0 < fine]
        livelli.append((float(inizio), float(fine),
                        max(dentro) if dentro else None))
    grezzo, ancore = scala_sagoma(template, livelli, peak)
    correzione = 1.0

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
    meta["livello_orario_preservato"] = peak
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
# Riferimenti della mattina, misurati il 2026-09-16 sull'archivio vero: D+1 fa
# 68,5% di colpi con 44,8% di falsi, sbilanciamento +7,5 minuti e ripidezza
# 3,59 su una vera di 3,89; il nullo fa 57,1% con 51,2%.
#
# Hanno un ruolo diverso da quelli dell'Ora: qui NON si pretende
# discriminazione. Il vantaggio della mattina sul nullo e' 23,7 contro 5,9
# punti, cioe' c'e', ma quasi tutto viene dal LIVELLO della sessione, non
# dalla forma: separando le due cose - regalando il picco vero dentro la
# finestra - il nullo prende gli stessi colpi del modello. Nella mattina la
# forma dice com'e' fatta una mattina di Peler, non QUALE mattina lo sara'.
#
# Si pretende invece calibrazione: la durata promessa e la ripidezza devono
# restare vicine al vero, e molto meglio della curva liscia, che sbaglia la
# durata di quarantasei minuti e produce una rampa di 0,25 kn/30' dove il lago
# ne fa 3,89.
# Aggiornato il 2026-09-17 con k=9: la mattina e' il posto dove il k nuovo ha
# guadagnato di piu'. Colpi 92,9% contro 83,9%, falsi 4,3% contro 5,0%, errore
# di durata 25 minuti contro 31, sbilanciamento +1 minuto contro -9. E qui,
# soltanto qui, il vantaggio sul nullo esiste: +4,3 punti, intervallo da +0,2
# a +8,6. Appena sopra lo zero, quindi non lo si pretende: si registra.
#
# La ripidezza scende a 2,51 (era 3,41) su una vera di 3,89, ed e' il prezzo
# della mediana piu' larga. Il minimo resta 2,0 perche' era dichiarato prima:
# quello che deve restare vero e' che la mattina NON e' una rampa da 0,56
# kn/30' come la curva liscia.
BENCHMARK_PELER = {
    "bias_minutes_max": 12.0,      # |sbilanciamento| ammesso, contro +23 liscia
    "steepness_min": 2.0,          # rampa minima, contro 0,56 della liscia
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
                  for lead in LEADS}
    pred = {lead: {d: v for d, v in source_all[lead].items()
                   if start_day <= d <= end_day}
            for lead in LEADS}
    common = set(obs_norm)
    for lead in LEADS:
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
            self.gaps = []

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
            rp = _steepness(forecast, inizio, fine)
            rv = _steepness(real, inizio, fine)
            self.slopes.append(rp)
            self.true_slopes.append(rv)
            # Lo scarto GIORNO PER GIORNO fra la ripidezza promessa e quella
            # vera. La differenza fra le due mediane non lo dice: una curva
            # sempre ripida ha la mediana giusta e sbaglia tutti i giorni
            # piatti. E' la misura con cui k=9 batte k=3 (2,18 contro 2,27)
            # nonostante abbia la mediana piu' lontana.
            self.gaps.append(abs(rp - rv))

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
                "steepness_gap": (statistics.median(self.gaps)
                                  if self.gaps else None),
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
            real = tuple(raw[day])
            # Il regalo e' il LIVELLO, e il livello e' il massimo delle medie
            # orarie: la grandezza che il motore prevede. Prima si regalava il
            # massimo istantaneo, che il motore non prevede e che e' mediamente
            # l'11% piu' alto - quindi la porta misurava una configurazione
            # diversa da quella che si spedisce, e nella direzione che
            # gonfiava le durate. E si scala con scala_sagoma, la STESSA
            # funzione del prodotto: non un secondo calcolo che le assomiglia.
            fin = finestre_peler.get(day)
            finestre_gg = [FINESTRA_ORA]
            if fin:
                finestre_gg = [(fin[0], fin[1]), FINESTRA_ORA]
            livelli = [(a, b, livello_orario(
                [(m, v) for m, v in zip(GRID_MIN, real)], a, b))
                for a, b in finestre_gg]
            if all(l is None for _a, _b, l in livelli):
                continue
            grezzo, _anc = scala_sagoma(
                template, livelli,
                max([l for _a, _b, l in livelli if l is not None]))
            forecast = tuple(grezzo)
            ora.aggiungi(forecast, real, SOGLIA_PORTA, *FINESTRA_ORA)
            if fin:
                peler.aggiungi(forecast, real, SOGLIA_PELER, fin[0], fin[1])
            used += 1
        out = ora.esito(used)
        out["peler"] = peler.esito(used)
        return out

    leads = {lead: measure(lead, {}) for lead in LEADS}
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



def _vantaggio(m):
    """Colpi meno falsi allarmi, in punti percentuali. None se non misurato."""
    h, f = (m or {}).get("hits"), (m or {}).get("false_alarms")
    return None if h is None or f is None else 100.0 * (float(h) - float(f))


def benchmark_gate(report):
    """Apre la porta solo se la forma fa cio' che ha dimostrato di fare.

    Tre famiglie di controlli, in ordine di importanza crescente:

    1. BANDE assolute sul blocco cieco. Servono a riconoscere un cambio di
       configurazione - l'ancora sbagliata spostava i falsi allarmi di trenta
       punti - non a riprodurre decimali misurati altrove.
    2. NON-DEGRADO sul binario, contro la curva liscia e contro il nullo. Non
       vantaggio: la forma analogica sul binario perde contro la liscia di 3,8
       punti e pareggia col nullo, e pretendere il contrario chiuderebbe la
       porta per un merito che il metodo non ha mai avuto.
    3. CALIBRAZIONE, dove il merito c'e' ed e' grande: la durata promessa e la
       ripidezza. E' anche l'unica cosa che la scheda legge e stampa.

    La differenza fra la prima famiglia e le altre due e' che le prime sono
    numeri, le altre due sono RELAZIONI misurate sulle stesse giornate dentro
    lo stesso rapporto. Le relazioni sopravvivono alla deriva dei dati.
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
    for lead, ref in sorted(BENCHMARK.items()):
        got = (report.get("leads") or {}).get(lead)
        if not got:
            reasons.append("D+%d mancante" % lead)
            continue
        for key, tol in sorted(TOLLERANZA_BENCHMARK.items()):
            target, value = ref.get(key), got.get(key)
            if target is None:
                continue
            if value is None or abs(float(value) - target) > tol:
                reasons.append("D+%d %s=%s (atteso %.3f +/- %.3f)"
                               % (lead, key, value, target, tol))
        # I falsi allarmi non hanno una banda: hanno un BUDGET, che e' una
        # promessa all'utente e non una misura. Vedi TOLLERANZA_BENCHMARK.
        fa = got.get("false_alarms")
        if fa is not None and float(fa) > BUDGET_FALSI:
            reasons.append("D+%d falsi allarmi %.1f%%, oltre il budget del"
                           " %.0f%%" % (lead, 100.0 * float(fa),
                                        100.0 * BUDGET_FALSI))
        tv = got.get("true_steepness")
        if tv is None or abs(float(tv) - RIPIDEZZA_VERA_ORA) > .5:
            reasons.append("D+%d ripidezza vera=%s (attesa %.1f +/- 0.5)"
                           % (lead, tv, RIPIDEZZA_VERA_ORA))

    uno = (report.get("leads") or {}).get(1) or {}
    liscia = report.get("liscia") or {}
    nullo = report.get("null") or {}
    if not liscia:
        reasons.append("curva liscia non misurata: senza il riferimento i"
                       " numeri della forma non vogliono dire niente")
    if not nullo:
        reasons.append("nullo non misurato")
    v_mod, v_lis, v_nul = (_vantaggio(uno), _vantaggio(liscia),
                           _vantaggio(nullo))
    if v_mod is not None and v_lis is not None:
        if v_mod < v_lis - SVANTAGGIO_MAX_SU_LISCIA:
            reasons.append("sul binario la forma sta %.1f punti sotto la curva"
                           " liscia (ammessi %.1f): non e' un compromesso, e'"
                           " un crollo"
                           % (v_lis - v_mod, SVANTAGGIO_MAX_SU_LISCIA))
    if v_mod is not None and v_nul is not None:
        # Il nullo NON deve essere battuto: deve non battere. E' un controllo
        # di sanita' - se rimescolare le giornate MIGLIORA le previsioni, il
        # legame fra condizioni e sagoma e' rotto da qualche parte.
        if v_mod < v_nul - SVANTAGGIO_MAX_SU_NULLO:
            reasons.append("il nullo fa %.1f punti MEGLIO del modello"
                           " (ammessi %.1f): rimescolare le giornate migliora"
                           " le previsioni, quindi qualcosa non lega le"
                           " condizioni alla sagoma"
                           % (v_nul - v_mod, SVANTAGGIO_MAX_SU_NULLO))
    # La calibrazione: qui si pretende un vantaggio vero, perche' c'e'.
    sb_mod, sb_lis = uno.get("bias_minutes"), liscia.get("bias_minutes")
    if sb_mod is None or sb_lis is None:
        reasons.append("sbilanciamento non confrontabile con la liscia")
    else:
        guadagno = abs(float(sb_lis)) - abs(float(sb_mod))
        if guadagno < SBIL_MEGLIO_DELLA_LISCIA_MIN:
            reasons.append("sulla durata la forma guadagna solo %.0f minuti"
                           " sulla liscia (minimo %.0f): il merito della forma"
                           " e' la calibrazione, e senza quella non serve"
                           % (guadagno, SBIL_MEGLIO_DELLA_LISCIA_MIN))
    g_mod, g_lis = uno.get("steepness_gap"), liscia.get("steepness_gap")
    if g_mod is None or g_lis is None:
        reasons.append("scarto di ripidezza non confrontabile con la liscia")
    elif float(g_lis) - float(g_mod) < SCARTO_RIP_MEGLIO_DELLA_LISCIA_MIN:
        reasons.append("la ripidezza promessa non e' piu' vicina al vero della"
                       " liscia: scarto %.2f contro %.2f (guadagno minimo"
                       " %.2f)" % (float(g_mod), float(g_lis),
                                   SCARTO_RIP_MEGLIO_DELLA_LISCIA_MIN))
    # La mattina: si pretende CALIBRAZIONE, non discriminazione.
    #
    # Nella mattina il vantaggio sul nullo esiste - +4,3 punti, intervallo da
    # +0,2 a +8,6 - ma e' appena sopra lo zero, e un intervallo che sfiora lo
    # zero non e' una cosa da pretendere a ogni avvio: si registra e si
    # rimisura. Quello che la scheda del Peler legge e stampa e' la durata e la
    # continuita', e quelle si pretendono.
    p_lis = liscia.get("peler") or {}
    for lead in sorted(BENCHMARK):
        p = ((report.get("leads") or {}).get(lead) or {}).get("peler")
        if not p:
            reasons.append("D+%d mattina non misurata" % lead)
            continue
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
        em, el = p.get("minute_error"), p_lis.get("minute_error")
        if em is None or el is None:
            reasons.append("D+%d durata della mattina non confrontabile con la"
                           " liscia" % lead)
        elif float(el) - float(em) < DURATA_MEGLIO_DELLA_LISCIA_MIN:
            reasons.append("D+%d sulla mattina la forma non batte la liscia"
                           " sulla durata: %.0f minuti di errore contro %.0f"
                           " (guadagno minimo %.0f)"
                           % (lead, float(em), float(el),
                              DURATA_MEGLIO_DELLA_LISCIA_MIN))
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
