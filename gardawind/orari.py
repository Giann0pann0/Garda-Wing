"""Orario di ingresso: logica pura, poi statistica. Il rendering sta altrove.

Tre livelli tenuti separati, cosi' che un cambio di spaziatura o di lingua non
possa rompere un controllo scientifico:

  1. LOGICA PURA        giudica_giornata(): dati normalizzati -> struttura.
  2. STATISTICA         climatologia(), previsione_climatologica(): aggrega e
                        produce il riferimento banale.
  3. RENDERING          __main__.cmd_orari(): stampa. Al massimo un paio di
                        controlli di fumo.

Due bersagli separati, entrambi necessari, e separati restano fino alla UI:

  INGRESSO DEL REGIME   attraversamento sostenuto della soglia di regime.
                        "Quando entra davvero l'Ora / il Peler."
  INGRESSO DA PLANATA   attraversamento sostenuto della soglia di planata.
                        "Da quando ha senso andare in acqua."

E due letture di ciascuno:

  VENTO     solo intensita': il vento supera la soglia, da qualunque parte.
  REGIME    intensita' E direzione dentro il settore attorno all'asse
            osservato della centralina.

Affiancarle non e' pignoleria. "Il vento supera i 14 nodi nel 63% dei
pomeriggi" e "l'Ora e' utile nel 63% dei pomeriggi" sono due frasi diverse, e
la prima diventa la seconda appena la si stacca dalla sua colonna.

Qui non ci sono modelli: e' la climatologia OSSERVATA, cioe' anche il
riferimento banale che un modello dell'orario dovra' battere. Per MESE, non
annuale: giugno e settembre non hanno lo stesso timing, e confrontare un
modello con "l'ora media dell'anno" e' vincere contro chi non gioca.

Gli orari sono MINUTI DALLA MEZZANOTTE LOCALE, non datetime: e' l'unita' in
cui si fa tutta l'aritmetica a valle (mediane, scarti, bias), e la data la
possiede gia' chi chiama.
"""

from . import config, store
from .util import (angle_diff, covered_minutes, linear_modes, local_day,
                   median, merge_by_instant, parse_dt_any, sampling_cadence,
                   sustained_onset, time_above, to_local)

# Quanto deve restare sopra soglia perche' sia un ingresso e non un colpo di
# vento. Trenta minuti e' anche la finestra della raffica ricorrente: un solo
# parametro per "il tempo in cui si decide se scendere in acqua".
PERSISTENZA_MIN = 30.0

# Sotto questa copertura la giornata non e' misurata, e' intravista.
MIN_COPERTURA_MIN = 120.0

# Sotto questo numero di giornate un mese non produce statistiche: una mediana
# su cinque numeri e' il terzo di cinque numeri.
MIN_GG_MESE = 10

LETTURE = ("vento", "regime")

# "reason" e' un INSIEME CHIUSO di codici, non testo libero: la logica non
# contiene italiano e il rendering non contiene logica. Aggiungerne uno vuol
# dire aggiungerlo qui, e un controllo verifica che non se ne inventino altri.
#
#   ok                        la giornata e' stimabile e il regime e' entrato
#   no_data                   nessun campione con vento
#   insufficient_coverage     troppo poco tempo coperto per dire qualcosa
#   gap_too_large             il regime risulta entrato, ma il passaggio cade
#                             dentro un buco: l'orario e' un limite inferiore,
#                             non una certezza
#   direction_outside_sector  il vento bastava, la direzione era fuori settore
#   threshold_not_sustained   la soglia e' stata superata, ma non abbastanza
#                             a lungo perche' sia un ingresso
#   no_regime                 la soglia non e' mai stata superata
REASONS = ("ok", "no_data", "insufficient_coverage", "gap_too_large",
           "direction_outside_sector", "threshold_not_sustained", "no_regime")

# I campi della struttura per giornata usano i nomi del contratto.
EN = {"regime": "regime", "planata": "planing"}
BERSAGLI = ("regime", "planata")


# ==========================================================================
# 1. Logica pura
# ==========================================================================

def giudica_giornata(righe, asse, settore, soglia_regime, soglia_planata,
                     persist_min=PERSISTENZA_MIN,
                     min_copertura_min=MIN_COPERTURA_MIN, date=None):
    """Una giornata -> la sua struttura. Nessun testo, nessuna stampa.

    righe: [(minuti_locali, vento_kn, direzione_deg_o_None)], in qualunque
    ordine. Tutto il resto sono parametri espliciti: la funzione non legge
    configurazione, cosi' un controllo puo' fissare le soglie che vuole.

    Nella lettura REGIME i campioni fuori settore valgono zero, e una
    direzione SCONOSCIUTA non vale come coerente: non lo sappiamo, e dare per
    buono cio' che non si sa e' il modo piu' rapido di gonfiare un conteggio.

    "estimable" e' falso quando la giornata non ha abbastanza copertura per
    dire qualcosa: in quel caso gli orari sono None e "reason" dice perche'.
    Una giornata senza ingresso, invece, e' stimabile: contribuisce alla base
    rate con uno zero, e non inventa un orario.
    """
    vuoto = {
        "date": date,
        "estimable": False, "reason": None,
        "cadence_min": None, "coverage_min": 0.0, "n_samples": 0,
        "source_span_min": 0.0,
        "dir_unknown_frac": None, "direction_ok": False,
        "regime_onset": None, "planing_onset": None,
        "regime_onset_wind": None, "planing_onset_wind": None,
        "regime_duration_min": None, "planing_duration_min": None,
        "regime_duration_wind_min": None, "planing_duration_wind_min": None,
    }
    dati = sorted([(float(m), w, d) for m, w, d in righe if w is not None],
                  key=lambda r: r[0])
    if not dati:
        vuoto["reason"] = "no_data"
        return vuoto

    minuti = [m for m, _w, _d in dati]
    cad = sampling_cadence(minuti) or 0.0
    coperti = covered_minutes(minuti, cad)
    ignoti = sum(1 for _m, _w, d in dati if d is None)
    base = dict(vuoto)
    # source_span_min e n_samples non servono a giudicare: servono all'audit.
    # Due giornate con lo stesso orario di ingresso possono venire da una
    # copertura fitta su due ore e da quattro campioni su nove, e senza questi
    # due numeri le due sembrano la stessa cosa.
    base.update({"cadence_min": cad, "coverage_min": coperti,
                 "n_samples": len(dati),
                 "source_span_min": minuti[-1] - minuti[0],
                 "dir_unknown_frac": ignoti / float(len(dati))})
    if coperti < min_copertura_min:
        base["reason"] = "insufficient_coverage"
        return base

    serie = {
        "vento": [(m, w) for m, w, _d in dati],
        "regime": [(m, w if (d is not None and angle_diff(d, asse) <= settore)
                    else 0.0) for m, w, d in dati],
    }
    base["estimable"] = True
    for bers, soglia in (("regime", soglia_regime), ("planata", soglia_planata)):
        for lettura in LETTURE:
            s = serie[lettura]
            ing = sustained_onset(s, float(soglia), persist_min=persist_min,
                                  cadence_min=cad)
            dur = time_above(s, float(soglia), cad)
            suffisso = "" if lettura == "regime" else "_wind"
            base["%s_onset%s" % (EN[bers], suffisso)] = ing
            base["%s_duration%s_min" % (EN[bers], suffisso)] = dur if dur > 0 else None

    # "La direzione era coerente" vuol dire: dove il vento bastava, veniva
    # anche dal settore giusto. Se il regime entra, e' coerente per costruzione;
    # se entra solo il vento, non lo era.
    base["direction_ok"] = (base["regime_onset"] is not None
                            if base["regime_onset_wind"] is not None else False)

    # Il codice, in ordine di precedenza. Dice perche' NON c'e' un ingresso di
    # regime, e quando c'e' dice se l'orario e' affidabile o solo un limite.
    if base["regime_onset"] is not None:
        # Il passaggio cade dentro un buco? Se il primo campione sopra soglia
        # arriva dopo un'interruzione piu' larga della cadenza, il vento
        # poteva essere salito durante il buco: l'orario e' un limite
        # inferiore, non una misura, e va marcato.
        soglia_buco = max(2.0 * cad, persist_min / 2.0)
        dentro_buco = False
        prec = None
        serie_r = serie["regime"]
        for m, v in serie_r:
            if v >= soglia_regime and prec is not None and (m - prec) > soglia_buco:
                dentro_buco = True
                break
            if v >= soglia_regime:
                break
            prec = m
        base["reason"] = "gap_too_large" if dentro_buco else "ok"
    elif base["regime_onset_wind"] is not None:
        base["reason"] = "direction_outside_sector"
    elif any(v >= soglia_regime for _m, v in serie["regime"]):
        base["reason"] = "threshold_not_sustained"
    elif any(v >= soglia_regime for _m, v in serie["vento"]):
        base["reason"] = "direction_outside_sector"
    else:
        base["reason"] = "no_regime"
    return base


# ==========================================================================
# 2. Statistica
# ==========================================================================

def giorni_osservati(spot_name):
    """Le giornate della centralina, dentro la finestra del regime.

    {giorno: [(minuti_locali, vento, direzione)]}, con i campioni dello stesso
    istante gia' uniti fra le fonti.
    """
    spot = config.SPOTS[spot_name]
    h0, h1 = spot["window"]
    pronti, etich = [], {}
    for s in store.samples_since(spot["station"], "0000"):
        dt_ = parse_dt_any(s["ts"])
        if dt_ is None:
            continue
        r = dict(s)
        r["_key"] = dt_.timestamp()
        pronti.append(r)
        loc = to_local(dt_)
        etich[r["_key"]] = (local_day(dt_), loc.hour * 60.0 + loc.minute)
    if not pronti:
        return {}
    per_istante, _conf = merge_by_instant(pronti)
    out = {}
    for key, u in per_istante.items():
        if u["wind"] is None:
            continue
        giorno, minuti = etich[key]
        if h0 * 60 <= minuti <= (h1 + 1) * 60:
            out.setdefault(giorno, []).append((minuti, u["wind"], u["dir"]))
    for giorno in out:
        out[giorno].sort(key=lambda r: r[0])
    return out


def _disp(xs):
    """Dispersione robusta: mediana degli scarti dalla mediana, in minuti."""
    if len(xs) < 3:
        return None
    m = median(xs)
    return median([abs(x - m) for x in xs])


def _riassunto(xs, durs=None, min_gg=MIN_GG_MESE):
    if len(xs) < min_gg:
        return {"n": len(xs), "mediana": None, "disp": None, "durata": None,
                "modi": None, "dip": None}
    modi, dip = linear_modes(xs, bin_size=30.0)
    return {"n": len(xs), "mediana": median(xs), "disp": _disp(xs),
            "durata": median(durs) if durs else None,
            "modi": modi, "dip": dip}


def climatologia(spot_name, giorni=None, persist_min=PERSISTENZA_MIN,
                 min_gg=MIN_GG_MESE):
    """Distribuzione osservata dell'ingresso, per mese, bersaglio e lettura.

    giorni: se passato, si usa quello invece di leggere il database. Serve ai
    fold: dentro un fold la climatologia deve vedere SOLO le giornate di
    addestramento, e il modo di garantirlo e' passarle.
    """
    spot = config.SPOTS[spot_name]
    asse = spot.get("axis_obs", spot["axis"])
    settore = config.REGIME_SECTOR_DEG
    soglie = {"regime": spot["min_kn"], "planata": spot["planing_kn"]}
    giorni = giorni_osservati(spot_name) if giorni is None else giorni

    ingressi = {(b, l): {} for b in BERSAGLI for l in LETTURE}
    durate = {(b, l): {} for b in BERSAGLI for l in LETTURE}
    n_giorni = n_dir_ignota = n_non_stimabili = 0
    per_giorno = {}

    for giorno in sorted(giorni):
        g = giudica_giornata(giorni[giorno], asse, settore,
                             soglie["regime"], soglie["planata"],
                             persist_min=persist_min, date=giorno)
        per_giorno[giorno] = g
        if not g["estimable"]:
            n_non_stimabili += 1
            continue
        n_giorni += 1
        if (g["dir_unknown_frac"] or 0) > 0.2:
            n_dir_ignota += 1
        mese = int(giorno[5:7])
        for bers in BERSAGLI:
            for lettura in LETTURE:
                suf = "" if lettura == "regime" else "_wind"
                ing = g["%s_onset%s" % (EN[bers], suf)]
                if ing is not None:
                    ingressi[(bers, lettura)].setdefault(mese, []).append(ing)
                dur = g["%s_duration%s_min" % (EN[bers], suf)]
                if dur:
                    durate[(bers, lettura)].setdefault(mese, []).append(dur)

    per_mese, annuale = {}, {}
    for bers in BERSAGLI:
        for lettura in LETTURE:
            tutti = []
            for mese in range(1, 13):
                xs = ingressi[(bers, lettura)].get(mese, [])
                tutti.extend(xs)
                per_mese[(bers, lettura, mese)] = _riassunto(
                    xs, durate[(bers, lettura)].get(mese, []), min_gg)
            annuale[(bers, lettura)] = _riassunto(tutti, None, min_gg)

    return {"spot": spot_name, "asse": asse, "settore": settore,
            "soglie": soglie, "n_giorni": n_giorni,
            "n_dir_ignota": n_dir_ignota, "n_non_stimabili": n_non_stimabili,
            "per_mese": per_mese, "annuale": annuale, "ingressi": ingressi,
            "per_giorno": per_giorno}


def previsione_climatologica(ingressi_training, mese, min_gg=MIN_GG_MESE,
                             ricadi_su_annuale=True):
    """Il riferimento banale: la mediana degli ingressi osservati DI QUEL MESE.

    ingressi_training: {mese: [minuti]}, costruito SOLO sulle giornate di
    addestramento. Passarlo come argomento invece di ricalcolarlo qui non e'
    pedanteria: e' l'unico modo di garantire che dentro un fold la
    climatologia non abbia visto le giornate di prova.

    Ritorna (minuti, provenienza) dove provenienza e' "mese", "annuale" o
    "insufficiente". Un mese con troppe poche giornate ricade sulla mediana
    annuale, e chi legge deve saperlo: un baseline che tace e' un baseline che
    vince senza giocare.
    """
    xs = ingressi_training.get(mese, [])
    if len(xs) >= min_gg:
        return median(xs), "mese"
    if not ricadi_su_annuale:
        return None, "insufficiente"
    tutti = [v for vs in ingressi_training.values() for v in vs]
    if not tutti:
        return None, "insufficiente"
    return median(tutti), "annuale"
