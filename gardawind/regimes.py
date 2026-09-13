"""Classificazione dei regimi di vento osservati.

Il Garda non ha due venti, ne ha parecchi, e chiamare "regime assente" tutto
cio' che non e' Ora o Peler butta via informazione utile proprio nei giorni in
cui uno che fa wing vorrebbe sapere qualcosa. Venti nodi da nord-ovest per una
perturbazione non sono "niente vento": sono una sessione, diversa e piu'
rafficata, ma una sessione.

Questo modulo etichetta le GIORNATE OSSERVATE. Non prevede niente: guarda i
dati della centralina e dice che regime c'e' stato. Serve a tre cose:

  1. costruire bersagli puliti (un Peler e' un Peler, non "c'erano 14 nodi");
  2. marcare i giorni ambigui invece di forzarli nell'addestramento;
  3. scegliere l'ampiezza dei settori direzionali sui dati e non a occhio.

Cautela deliberata sui nomi. I venti locali hanno nomi precisi e significati
precisi, e appiccicarli a qualunque cosa passi un filtro direzionale sarebbe
un abuso. Qui le classi sono descrittive (NORD_OVEST, NORD_SINOTTICO, ...);
il nome locale compare come annotazione solo quando direzione, orario e
persistenza sono coerenti, e resta comunque indicato come ipotesi.
"""

from . import config
from .util import angle_diff, mean, median, vector_mean_direction

# --------------------------------------------------------------------------
# Tassonomia
# --------------------------------------------------------------------------
# ORDINE DI PRECEDENZA: la prima regola che scatta vince. Le regole piu'
# specifiche (termiche, con orario e direzione stretti) vengono prima di
# quelle generiche.

CALMA = "CALMA"
PELER = "PELER"
ORA = "ORA"
NORD_OVEST = "NORD_OVEST"
NORD_SINOTTICO = "NORD_SINOTTICO"
SUD_SINOTTICO = "SUD_SINOTTICO"
OVEST = "OVEST"
EST = "EST"
VARIABILE = "VARIABILE"

ETICHETTE = {
    CALMA: "calma",
    PELER: "Pelèr",
    ORA: "Ora",
    NORD_OVEST: "vento da NO",
    NORD_SINOTTICO: "settentrionale sinottico",
    SUD_SINOTTICO: "meridionale sinottico",
    OVEST: "vento da ovest",
    EST: "vento da est",
    VARIABILE: "variabile",
}

# Nome locale proposto SOLO come ipotesi, quando i criteri coincidono.
NOMI_LOCALI = {
    NORD_OVEST: "compatibile con il Balinot (discendente dalla zona di Ballino)",
    OVEST: "compatibile con il Ponale",
}

# Settori di PROVENIENZA. Il settore del Peler e' volutamente stretto: con
# +/-70 gradi attorno a 24 il settore arriva a 314, cioe' inghiotte il vento
# da NO. Un discendente da Ballino verrebbe etichettato Peler, che e' sbagliato
# sia fisicamente sia per chi legge. Il valore va comunque confermato dai dati
# con sector_study().
SETTORI = {
    PELER: (config.LAKE_AXIS_PELER, 45.0),
    ORA: (config.LAKE_AXIS_ORA, 50.0),
    NORD_OVEST: (320.0, 30.0),
    OVEST: (270.0, 25.0),
    EST: (90.0, 35.0),
}

# Soglie
CALMA_KN = 6.0
MIN_REGIME_KN = 9.0
MIN_COSTANZA = 0.55        # sotto questa soglia la direzione non e' stabile
MIN_ORE = 3                # ore CONSECUTIVE sopra soglia perche' sia un regime

# Finestre orarie tipiche dei due termici (ore locali).
ORE_PELER = (3, 11)
ORE_ORA = (11, 20)


def settori_per_spot(spot):
    """Settori centrati sui canali che QUELLA CENTRALINA vede.

    Non sullo spot: sulla stazione. E' la correzione di un errore che avevo
    fatto nella prima stesura, e vale la pena spiegarlo perche' e' un errore
    di ragionamento, non di battitura.

    I canali di una valle sono una proprieta' del posto. La centralina di
    Torbole vede il vento arrivare da 54 gradi oppure da 191, e questo vale
    per tutte e ventiquattro le ore: non e' che di mattina la valle e' fatta
    in un modo e di pomeriggio in un altro. La prima versione invece ruotava
    ENTRAMBI i settori termici dello scarto del regime DI QUELLO SPOT, e cosi'
    per lo spot "Torbole-Ora" (scarto -13) il settore del Peler finiva a 11
    gradi invece che a 54. Effetto visibile nei dati veri: nella finestra
    dell'Ora i Peler classificati erano scesi da 121 a 67 e i venti da est
    erano saliti a 212, di cui 184 marcati ambigui perche' finivano a ridosso
    di un confine messo nel posto sbagliato.

    Ora i due settori termici vengono presi dagli assi osservati della stessa
    STAZIONE, qualunque sia lo spot che chiede la classificazione. Gli altri
    settori (NO, O, E) restano dove sono: descrivono provenienze geografiche,
    non il canale locale.
    """
    out = dict(SETTORI)
    station = spot.get("station")
    for key, regime in ((PELER, "PELER"), (ORA, "ORA")):
        ax = None
        for _n, s2 in config.SPOTS.items():
            if s2.get("station") == station and s2.get("regime") == regime:
                ax = s2.get("axis_obs")
                break
        if ax is not None:
            out[key] = (ax, SETTORI[key][1])
    return out


def _in(direction, key, settori=None):
    axis, half = (settori or SETTORI)[key]
    return direction is not None and angle_diff(direction, axis) <= half


def _longest_run(hours):
    """Ore consecutive piu' lunghe in una lista di ore locali.

    Due ore ventose separate da un'ora di calma non sono un regime di due ore:
    sono due raffiche. Conta la sequenza, non il totale.
    """
    hs = sorted(set(int(h) for h in hours))
    if not hs:
        return 0
    best = run = 1
    for prev, cur in zip(hs, hs[1:]):
        run = run + 1 if cur == prev + 1 else 1
        if run > best:
            best = run
    return best


def _window_constancy(rows):
    """Costanza direzionale complessiva della finestra.

    Due cose diverse si moltiplicano, e vanno moltiplicate entrambe:

      - la costanza FRA le ore, cioe' quanto la media vettoriale oraria punta
        sempre nella stessa direzione (la da' vector_mean_direction);
      - la costanza DENTRO ciascuna ora, cioe' `dir_const` della centralina,
        che misura quanto il vento ha oscillato nei dieci minuti.

    Un vento che ogni ora ha una media da 24 gradi ma dentro l'ora gira di
    novanta gradi non e' un Peler: la prima misura vale 1.0 e direbbe "stabile".
    Per questo la seconda non e' un rimedio da usare solo quando la prima
    manca, ma un fattore che entra sempre. Il prodotto approssima la costanza
    che si otterrebbe dai campioni grezzi, pesando ogni ora per la sua
    intensita'.

    Se la centralina non fornisce `dir_const` il fattore vale 1.0: non si
    penalizza un dato assente, si dichiara solo quello che si sa.
    """
    direction, inter = vector_mean_direction(
        [(r["wind_mean"], r.get("dir_deg")) for r in rows])
    pesi = [(r["wind_mean"], r.get("dir_const")) for r in rows
            if r.get("dir_const") is not None and r.get("wind_mean")]
    if pesi:
        tot = sum(w for w, _c in pesi)
        intra = sum(w * c for w, c in pesi) / tot if tot else mean([c for _w, c in pesi])
    else:
        intra = 1.0
    if direction is None:
        # Nessuna direzione utilizzabile: la costanza residua e' solo quella
        # dichiarata dalla centralina, se c'e'.
        return None, (intra if pesi else 0.0)
    return direction, max(0.0, min(1.0, inter * (intra if intra is not None else 1.0)))


def classify_window(rows, regime_hint=None, settori=None):
    """Classifica una finestra oraria osservata.

    rows: [{"hour": int locale, "wind_mean": kn, "gust_max": kn|None,
            "dir_deg": gradi|None, "dir_const": 0..1|None}]

    Ritorna un dizionario con classe, qualita' e i numeri su cui si basa.
    """
    usable = [r for r in rows if r.get("wind_mean") is not None]
    if not usable:
        return None

    peak_row = max(usable, key=lambda r: r["wind_mean"])
    peak = peak_row["wind_mean"]
    hours_over = [r for r in usable if r["wind_mean"] >= MIN_REGIME_KN]

    direction, constancy = _window_constancy(hours_over or usable)
    run = _longest_run([r["hour"] for r in hours_over])

    res = {
        "peak": peak, "peak_hour": peak_row["hour"],
        "dir": direction, "constancy": constancy,
        "hours_over": len(hours_over), "ore_consecutive": run,
        "gust": max([r.get("gust_max") or 0.0 for r in usable] or [0.0]) or None,
    }

    if peak < CALMA_KN:
        res.update(classe=CALMA, qualita=1.0, motivo="picco sotto %g kn" % CALMA_KN)
        return res

    if peak < MIN_REGIME_KN or run < MIN_ORE:
        res.update(classe=VARIABILE, qualita=0.5,
                   motivo=("picco %.0f kn sotto %g" % (peak, MIN_REGIME_KN)
                           if peak < MIN_REGIME_KN else
                           "solo %d ore consecutive sopra soglia (minimo %d)"
                           % (run, MIN_ORE)))
        return res

    if direction is None:
        res.update(classe=VARIABILE, qualita=0.3, motivo="direzione non disponibile")
        return res

    if constancy < MIN_COSTANZA:
        res.update(classe=VARIABILE, qualita=0.3,
                   motivo="direzione instabile (costanza %.2f)" % constancy)
        return res

    SET = settori or SETTORI
    ph = peak_row["hour"]
    # I due termici richiedono direzione E orario. Un settentrionale alle
    # quattro del pomeriggio non e' un Peler, per quanto venga da nord.
    if _in(direction, PELER, SET) and ORE_PELER[0] <= ph <= ORE_PELER[1]:
        res.update(classe=PELER, qualita=1.0, motivo="direzione e orario da Pelèr")
    elif _in(direction, ORA, SET) and ORE_ORA[0] <= ph <= ORE_ORA[1]:
        res.update(classe=ORA, qualita=1.0, motivo="direzione e orario da Ora")
    elif _in(direction, NORD_OVEST, SET):
        res.update(classe=NORD_OVEST, qualita=0.9, motivo="provenienza NO")
    elif _in(direction, OVEST, SET):
        res.update(classe=OVEST, qualita=0.8, motivo="provenienza O")
    elif _in(direction, EST, SET):
        res.update(classe=EST, qualita=0.8, motivo="provenienza E")
    elif _in(direction, PELER, SET):
        res.update(classe=NORD_SINOTTICO, qualita=0.8,
                   motivo="da nord ma fuori dall'orario del Pelèr")
    elif _in(direction, ORA, SET):
        res.update(classe=SUD_SINOTTICO, qualita=0.8,
                   motivo="da sud ma fuori dall'orario dell'Ora")
    else:
        res.update(classe=VARIABILE, qualita=0.4, motivo="direzione fuori da ogni settore")

    # Ambiguita': vicino al bordo di un settore, oppure due classi plausibili.
    borderline = []
    for key in (PELER, ORA, NORD_OVEST, OVEST):
        axis, half = SET[key]
        d = angle_diff(direction, axis)
        if half < d <= half + 15.0:
            borderline.append(key)
    if borderline or constancy < MIN_COSTANZA + 0.12:
        res["qualita"] = min(res.get("qualita", 1.0), 0.6)
        res["ambiguo"] = True
        res["vicino_a"] = borderline
    else:
        res["ambiguo"] = False

    nome = NOMI_LOCALI.get(res["classe"])
    if nome:
        res["nome_locale"] = nome
    return res


def classify_days(obs_hours, window=None, settori=None):
    """Classifica ogni giorno locale. obs_hours: righe di store.obs_hours.

    Ritorna {giorno: risultato}. Se `window` e' dato, considera solo quelle
    ore locali.
    """
    from .util import local_day, local_hour, parse_dt_any
    by_day = {}
    for row in obs_hours:
        dt = parse_dt_any(row["hour"])
        if dt is None or row["wind_mean"] is None:
            continue
        h = local_hour(dt)
        if window and not (window[0] <= h <= window[1]):
            continue
        by_day.setdefault(local_day(dt), []).append({
            "hour": h, "wind_mean": row["wind_mean"],
            "gust_max": row["gust_max"], "dir_deg": row["dir_deg"],
            "dir_const": row["dir_const"],
        })
    out = {}
    for day, rows in by_day.items():
        if len(rows) < 3:
            continue
        r = classify_window(sorted(rows, key=lambda x: x["hour"]), settori=settori)
        if r:
            out[day] = r
    return out


def summary(classified):
    """Quante giornate per classe, con intensita' e orario tipici."""
    groups = {}
    for day, r in classified.items():
        groups.setdefault(r["classe"], []).append((day, r))
    total = len(classified) or 1
    out = []
    for classe, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        peaks = [r["peak"] for _d, r in items]
        hours = [r["peak_hour"] for _d, r in items]
        out.append({
            "classe": classe,
            "etichetta": ETICHETTE.get(classe, classe),
            "n": len(items),
            "quota": len(items) / total,
            "picco_mediano": median(peaks),
            "picco_max": max(peaks),
            "ora_mediana": median(hours),
            "ambigui": sum(1 for _d, r in items if r.get("ambiguo")),
        })
    return out


def sector_study(classified, axis, candidates=(30.0, 45.0, 60.0, 70.0, 90.0)):
    """Quanto separa, ciascuna ampiezza di settore, i veri eventi dagli altri.

    Guarda SOLO le osservazioni: nessun modello, quindi nessuna possibilita' di
    ottimizzare sul banco di prova. Per ogni soglia riporta quante giornate
    ventose cadono dentro, la loro intensita' mediana e quanta contaminazione
    da altre classi entra nel settore.
    """
    windy = [(r["peak"], r["dir"], r["classe"], int(day[5:7]))
             for day, r in classified.items()
             if r.get("dir") is not None and r["peak"] >= MIN_REGIME_KN]
    if len(windy) < 50:
        return None
    rows = []
    for th in candidates:
        inside = [(p, c) for p, d, c, _m in windy if angle_diff(d, axis) <= th]
        outside = [(p, c) for p, d, c, _m in windy if angle_diff(d, axis) > th]
        if not inside:
            continue
        classi = {}
        for _p, c in inside:
            classi[c] = classi.get(c, 0) + 1
        dominante = max(classi.items(), key=lambda kv: kv[1])
        rows.append({
            "deg": th,
            "n_dentro": len(inside),
            "quota_dentro": len(inside) / len(windy),
            "picco_mediano_dentro": median([p for p, _c in inside]),
            "picco_mediano_fuori": median([p for p, _c in outside]) if outside else None,
            "classe_dominante": dominante[0],
            "purezza": dominante[1] / len(inside),
        })
    stagioni = {}
    for p, d, c, m in windy:
        s = ("inverno" if m in (12, 1, 2) else "primavera" if m in (3, 4, 5)
             else "estate" if m in (6, 7, 8) else "autunno")
        stagioni.setdefault(s, []).append(angle_diff(d, axis))
    return {
        "n": len(windy),
        "soglie": rows,
        "per_stagione": {k: {"n": len(v), "scarto_mediano": median(v)}
                         for k, v in stagioni.items() if len(v) >= 20},
    }
