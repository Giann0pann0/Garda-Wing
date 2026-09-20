"""Costruzione delle feature giornaliere.

Una sola funzione costruisce il vettore sia in addestramento (da
historical-forecast) sia in previsione (dalla media d'ensemble). Se le due
strade divergessero, il modello imparerebbe una cosa e ne userebbe un'altra:
e' l'errore piu' insidioso di tutta la catena, e si evita solo condividendo
il codice.

Perche' GIORNALIERE e non orarie: l'Ora e il Peler o entrano o non entrano.
La domanda che conta per chi va in acqua e' "entra, e quanto forte", non
"quanti nodi esattamente alle 15:23". Un modello giornaliero ha un ordine di
grandezza meno di parametri da stimare a parita' di dati, e ore consecutive
dello stesso giorno non sono osservazioni indipendenti: usarle come tali
gonfia il campione senza aggiungere informazione.
"""

import math

from . import config
from .util import (along_axis, clamp, cross_axis, day_of_year, day_shift,
                   iso_hour_utc, local_day, local_hour, mean, parse_dt_any)

# --------------------------------------------------------------------------
# Nomi delle feature, per livello di complessita'
# --------------------------------------------------------------------------

TIER_BIAS = ["w10_win"]

TIER_REDUCED = [
    "w10_win", "along925", "rad_pre", "cloud_win",
    "pgrad", "tgrad", "doy_sin", "doy_cos",
]

TIER_FULL = [
    "w10_win", "w10_max", "along10",
    "along925", "cross925", "w700", "along700",
    "stab850", "stab925",
    "rad_pre", "cloud_win", "cloud_cool", "dewdep", "precip",
    "pgrad", "tgrad", "breeze", "persist_obs", "persist_age",
    "doy_sin", "doy_cos",
]

# Livello di SUPERFICIE: nessuna variabile isobarica, perche' la rianalisi
# ERA5 non le espone. In cambio si addestra su quattordici anni invece che su
# cinque. Meno informazione per giornata, molte piu' giornate: quale delle due
# cose conti di piu' non si decide a tavolino, lo decide il confronto.
TIER_SURFACE = [
    "w10_win", "w10_max", "along10",
    "rad_pre", "cloud_win", "cloud_cool", "dewdep", "precip",
    "pgrad", "tgrad", "persist_obs", "persist_age", "doy_sin", "doy_cos",
]

# Livello per il modello dell'orario. Include l'ora in cui il vento grezzo
# d'ensemble mette il proprio massimo: e' il punto di partenza da correggere,
# ed e' anche il riferimento che questo stadio deve battere.
TIER_TIMING = [
    "raw_peak_hour", "w10_win", "along925", "rad_pre", "cloud_win",
    "pgrad", "tgrad", "doy_sin", "doy_cos",
]

# Controllo: lo stesso livello di superficie SENZA memoria. Non e' un livello
# da mettere in produzione, e' il metro con cui si verifica se `persist_obs` si
# guadagna il posto a una data scadenza. Se non lo batte, la memoria a quella
# scadenza e' rumore e va tolta.
TIER_NOPERSIST = [n for n in TIER_SURFACE if not n.startswith("persist")]

TIERS = {"bias": TIER_BIAS, "reduced": TIER_REDUCED, "full": TIER_FULL,
         "surface": TIER_SURFACE, "timing": TIER_TIMING,
         "nopersist": TIER_NOPERSIST}

# Livelli utilizzabili a seconda della sorgente dei predittori.
TIERS_BY_SOURCE = {
    "forecast": ("bias", "reduced", "full"),
    "era5": ("bias", "surface"),
}

# Feature senza le quali il giorno non e' utilizzabile: se manca il vento
# previsto non c'e' nulla da correggere.
REQUIRED = {"w10_win"}


def _or(value, default):
    """Sostituisce SOLO i valori mancanti, non gli zeri."""
    return default if value is None else value


def window_hours(day, start_h, end_h):
    """Chiavi orarie UTC corrispondenti alle ore LOCALI [start_h, end_h] di `day`."""
    out = []
    # Si esplora un intervallo generoso in UTC e si filtra sull'ora locale:
    # e' l'unico modo corretto quando il giorno attraversa un cambio d'ora.
    base = parse_dt_any(day + " 00:00:00")
    if base is None:
        return out
    for offset in range(-3, 27):
        dt = base + _hours(offset)
        if local_day(dt) != day:
            continue
        h = local_hour(dt)
        if start_h <= h <= end_h:
            out.append(iso_hour_utc(dt))
    return sorted(set(out))


def span_hours(day, start_day_offset, start_h, end_day_offset, end_h):
    """Chiavi orarie UTC di un intervallo che puo' attraversare la mezzanotte."""
    out = []
    d_start = day_shift(day, start_day_offset)
    d_end = day_shift(day, end_day_offset)
    for d in sorted({d_start, d_end}):
        base = parse_dt_any(d + " 00:00:00")
        if base is None:
            continue
        for offset in range(-3, 27):
            dt = base + _hours(offset)
            ld = local_day(dt)
            lh = local_hour(dt)
            if ld == d_start and d_start != d_end and lh >= start_h:
                out.append(iso_hour_utc(dt))
            elif ld == d_end and d_start != d_end and lh <= end_h:
                out.append(iso_hour_utc(dt))
            elif d_start == d_end and ld == d_start and start_h <= lh <= end_h:
                out.append(iso_hour_utc(dt))
    return sorted(set(out))


def _hours(n):
    import datetime
    return datetime.timedelta(hours=n)


# --------------------------------------------------------------------------
# Gradienti sinottici
# --------------------------------------------------------------------------

def _gradients(ctx, keys):
    """Gradiente barico nord-sud e contrasto termico sud-nord.

    pgrad > 0 significa pressione piu' alta a nord: spinge l'aria verso sud
    lungo il lago e favorisce il Peler. pgrad < 0 favorisce l'Ora.
    tgrad > 0 significa pianura piu' calda della valle: e' il motore termico
    che alimenta la brezza di lago.
    """
    north = [p for p, (_la, _lo, side) in config.CONTEXT_POINTS.items() if side == "north"]
    south = [p for p, (_la, _lo, side) in config.CONTEXT_POINTS.items() if side == "south"]
    pg, tg = [], []
    for k in keys:
        at = ctx.get(k) or {}
        pn = mean([(at.get(p) or {}).get("mslp") for p in north])
        ps = mean([(at.get(p) or {}).get("mslp") for p in south])
        tn = mean([(at.get(p) or {}).get("t2m") for p in north])
        ts = mean([(at.get(p) or {}).get("t2m") for p in south])
        if pn is not None and ps is not None:
            pg.append(pn - ps)
        if tn is not None and ts is not None:
            tg.append(ts - tn)
    return mean(pg), mean(tg)


# --------------------------------------------------------------------------
# Vettore giornaliero
# --------------------------------------------------------------------------

def daily_features(spot_name, day, hours, ctx, persist=None, persist_age=None,
                   persist_default=None):
    """Costruisce {nome: valore} per un giorno. Ritorna None se inutilizzabile.

    hours : {chiave_oraria_utc: {colonna: valore}}  (ensemble o archivio)
    ctx   : {chiave_oraria_utc: {luogo: {mslp,t2m,cloud,rad}}}
    persist: ULTIMO picco osservato che era gia' noto al momento dell'emissione
    persist_age: la sua eta' in giorni rispetto al giorno bersaglio

    Sulla memoria, per esteso, perche' qui la 3.5 sbagliava e non di poco.
    La feature si chiamava `persist` ed era il picco osservato del giorno
    T-1, con T il giorno bersaglio. In addestramento era sempre disponibile,
    perche' si guardava un archivio di giorni tutti passati. In esercizio, con
    emissione il giorno T-L, il giorno T-1 e' passato solo se T-1 < T-L, cioe'
    solo se L = 0. A L = 1 il giorno T-1 e' il giorno dell'emissione, e la sua
    finestra non si e' ancora chiusa; a L >= 2 e' addirittura nel futuro.
    Il risultato pratico era peggiore di una fuga di informazione: la ricerca
    dell'osservazione mancante restituiva None e il valore diventava zero, per
    cui a ogni scadenza utile il modello applicava un coefficiente stimato su
    valori veri a un ingresso costantemente nullo. Un disallineamento fra
    addestramento ed esercizio, non un vantaggio.

    La forma corretta non e' buttare la memoria: l'autocorrelazione fra giorni
    consecutivi esiste e vale qualcosa (le configurazioni bloccate durano). E'
    dichiarare QUALE memoria si ha e QUANTO e' vecchia. Con emissione al
    mattino del giorno T-L, l'ultimo giorno interamente osservato e' T-L-1,
    quindi eta' L+1 giorni. Entrambe le cose entrano nel vettore, cosi' il
    modello puo' imparare da solo quanto scontare un ricordo di sei giorni
    prima, invece di ricevere uno zero travestito da misura.
    """
    spot = config.SPOTS[spot_name]
    axis = spot["axis"]
    h0, h1 = spot["window"]

    win_keys = [k for k in window_hours(day, h0, h1) if k in hours]
    # La copertura minima e' UNA, ed e' in config: qui c'era un 0,5 scritto a
    # mano contro lo 0,55 che usano il bersaglio (engine) e la verifica. Un
    # giorno col 52% delle ore veniva accettato dal lato dei predittori e
    # rifiutato dal lato dell'osservato: due numeri per una regola sola.
    if len(win_keys) < max(3, int(config.MIN_WINDOW_COVERAGE * (h1 - h0 + 1))):
        return None

    win = [hours[k] for k in win_keys]

    def col(name, rows=None):
        return [r.get(name) for r in (rows if rows is not None else win)]

    w10 = mean(col("w10"))
    if w10 is None:
        return None

    f = {}
    f["w10_win"] = w10
    f["w10_max"] = max([v for v in col("w10") if v is not None] or [w10])
    # Attenzione ai valori nulli: "or default" tratterebbe uno zero legittimo
    # (cielo sereno, vento nullo, calma piatta) come dato mancante. Qui lo zero
    # e' un'informazione, non un buco.
    f["along10"] = _or(mean([along_axis(r.get("w10"), r.get("d10"), axis) for r in win]), 0.0)
    f["along925"] = _or(mean([along_axis(r.get("w925"), r.get("d925"), axis) for r in win]), 0.0)
    f["cross925"] = _or(mean([cross_axis(r.get("w925"), r.get("d925"), axis) for r in win]), 0.0)
    f["w700"] = _or(mean(col("w700")), 0.0)
    f["along700"] = _or(mean([along_axis(r.get("w700"), r.get("d700"), axis) for r in win]), 0.0)

    t2m = mean(col("t2m"))
    t850 = mean(col("t850"))
    t925 = mean(col("t925"))
    f["stab850"] = (t850 - t2m) if (t850 is not None and t2m is not None) else -20.0
    f["stab925"] = (t925 - t2m) if (t925 is not None and t2m is not None) else -8.0

    dew = mean(col("dew"))
    f["dewdep"] = (t2m - dew) if (t2m is not None and dew is not None) else 6.0

    cl = mean(col("cloud_low"))
    f["cloud_win"] = _or(cl if cl is not None else mean(col("cloud")), 50.0) / 100.0

    # Finestra di preriscaldamento (Ora) o di raffreddamento notturno (Peler).
    if spot["regime"] == "ORA":
        pre_keys = [k for k in window_hours(day, 8, max(9, h0)) if k in hours]
        cool_keys = pre_keys
    else:
        pre_keys = [k for k in span_hours(day, -1, 12, -1, 18) if k in hours]
        cool_keys = [k for k in span_hours(day, -1, 21, 0, h0) if k in hours]

    pre = [hours[k] for k in pre_keys] or win
    cool = [hours[k] for k in cool_keys] or win
    f["rad_pre"] = _or(mean(col("rad", pre)), 0.0) / 500.0
    f["cloud_cool"] = _or(mean(col("cloud", cool)), 50.0) / 100.0

    precip_keys = [k for k in window_hours(day, max(0, h0 - 3), h1) if k in hours]
    f["precip"] = sum(max(0.0, hours[k].get("precip") or 0.0) for k in precip_keys)

    pgrad, tgrad = _gradients(ctx, win_keys)
    # Lo zero serve al modello - un vettore di feature non ha buchi - ma NON
    # significa "campo barico piatto": significa "non lo sappiamo". La pagina
    # mostra questi due numeri come misure confrontabili con l'esperienza di chi
    # c'era, e senza questa distinzione scriveva "DeltaP +0.0 hPa, neutro" ogni
    # volta che la chiamata al contesto sinottico non era andata a buon fine.
    f["pgrad"] = pgrad if pgrad is not None else 0.0
    f["tgrad"] = tgrad if tgrad is not None else 0.0
    f["contesto_noto"] = 1.0 if pgrad is not None else 0.0

    # Indice di brezza: il contrasto termico che alimenta la circolazione
    # diviso il quadrato del vento sinottico che tende a spazzarla via.
    # E' la forma classica per le brezze di lago; la soglia va calibrata sul
    # posto, ma la forma funzionale risparmia campioni rispetto a lasciare che
    # il modello scopra da solo una relazione non lineare.
    synoptic = _or(mean(col("w925")), 0.0)
    f["breeze"] = clamp(f["tgrad"] / max(1.0, (synoptic * 0.5144) ** 2), -30.0, 30.0)

    # MEMORIA MANCANTE NON E' ZERO NODI, ed e' la seconda volta che questo
    # campo lo dimentica: la prima fu l'ETA', che restava plausibile su un
    # valore inventato, e la docstring qui sopra la dichiara corretta. Lo zero
    # no. Se la centralina tace per piu' di quattro giorni - o se quattro
    # giorni di fila non hanno copertura sufficiente, cosa normale d'inverno
    # sul Peler - il modello riceveva "l'ultimo picco osservato e' 0 kn", che
    # e' l'affermazione piu' forte possibile nella direzione sbagliata: la
    # probabilita' crollava all'1% su TUTTO l'orizzonte, e la pagina non aveva
    # modo di dire che il crollo veniva da un dato che non c'era.
    #
    # Al suo posto si mette un valore NEUTRO - la mediana del picco di quella
    # sessione, che il chiamante passa - e lo passano allo stesso modo le due
    # strade, addestramento e previsione, perche' altrimenti si ricrea la
    # divergenza che questo file esiste per impedire.
    if persist is None:
        persist = persist_default if persist_default is not None else 0.0
    f["persist_obs"] = persist
    f["persist_age"] = float(persist_age if persist_age is not None else 1)

    # Ora (locale) in cui la previsione grezza mette il suo massimo nella
    # finestra: serve come punto di partenza e come riferimento per lo stadio
    # che prevede l'orario.
    best_h, best_v = None, -1.0
    for k in win_keys:
        v = hours[k].get("w10")
        if v is not None and v > best_v:
            best_v, best_h = v, local_hour(parse_dt_any(k))
    f["raw_peak_hour"] = float(best_h) if best_h is not None else (h0 + h1) / 2.0

    doy = day_of_year(day)
    f["doy_sin"] = math.sin(2 * math.pi * doy / 365.25)
    f["doy_cos"] = math.cos(2 * math.pi * doy / 365.25)

    for name in REQUIRED:
        if f.get(name) is None:
            return None
    return f


def vector(features, tier):
    names = TIERS[tier]
    return [float(_or(features.get(n), 0.0)) for n in names]


def hourly_shape(spot_name, day, hours):
    """Profilo orario normalizzato entro la finestra, dalla previsione stessa.

    Serve solo a distribuire sul giorno l'intensita' prevista: il modello
    lavora sul giorno, ma chi va in acqua vuole sapere a che ora.
    """
    spot = config.SPOTS[spot_name]
    h0, h1 = spot["window"]
    keys = [k for k in window_hours(day, h0, h1) if k in hours]
    if not keys:
        return []
    vals = [(k, _or(hours[k].get("w10"), 0.0)) for k in keys]
    peak = max(v for _k, v in vals) or 1.0
    return [(k, v / peak) for k, v in vals]
