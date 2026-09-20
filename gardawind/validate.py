"""Validazione temporale rigorosa.

Regola unica, da cui discende tutto il resto:

    nessun dato che un utente reale non avrebbe potuto conoscere al momento
    dell'emissione puo' entrare nel modello, ne' in addestramento ne' in
    inferenza ne' nella calibrazione.

Conseguenze concrete, ognuna delle quali corregge una violazione della 3.5:

  - **forward chaining**: si addestra sempre sul passato e si prova sempre sul
    futuro. La validazione a blocchi della 3.5 assegnava giorni contigui ai
    fold, ma il fold piu' antico veniva predetto anche con dati successivi.
  - **lambda annidato**: l'iperparametro si sceglie con una cross-validation
    interna al solo periodo di addestramento. Sceglierlo guardando il fold di
    prova significa ottimizzare sul banco di prova e poi vantarsene.
  - **calibrazione dentro il fold**: l'isotonica si tara sulle predizioni
    out-of-fold del solo periodo di addestramento. Nella 3.5 era tarata sulle
    stesse predizioni su cui veniva poi misurato il Brier, quindi la curva di
    affidabilita' era ottimistica per costruzione.
  - **blocco cieco**: l'ultimo periodo non entra in nessuna scelta e si apre
    una volta sola.
  - **bootstrap**: il miglioramento viaggia con il suo intervallo di
    confidenza. Una differenza dello 0,4% fra due candidati e' rumore, e senza
    intervallo non si distingue dal segnale.
"""

import math
import random

from . import config, features as F
from .model import apply_calibration, pava
from .util import (banda_da_residui, brier, clamp, interval_coverage,
                   logistic_fit, mean, median, quantile, regression_metrics,
                   ridge_fit, LogisticModel, RidgeModel)

# La griglia dei lambda e' UNA: la teneva anche questo modulo, identica, e due
# copie di una griglia sono due modelli diversi il giorno che una si allarga.
from .model import LAMBDA_GRID  # noqa: E402  (una sola definizione, in model)
MIN_TRAIN_DAYS = 200
N_FOLDS = 5
BOOTSTRAP = 400


# ==========================================================================
# Suddivisione temporale
# ==========================================================================

def split_blind(days, holdout_days=None):
    """Separa il blocco cieco finale dal resto. Il primo non si tocca."""
    holdout = config.BLIND_HOLDOUT_DAYS if holdout_days is None else holdout_days
    ordered = sorted(days)
    if len(ordered) <= holdout + MIN_TRAIN_DAYS:
        return ordered, []
    return ordered[:-holdout], ordered[-holdout:]


def forward_folds(days, n_folds=N_FOLDS, min_train=MIN_TRAIN_DAYS):
    """Fold a finestra crescente: [(giorni_train, giorni_test), ...].

    Il training e' sempre e solo cio' che precede il test. Nessun fold vede il
    proprio futuro, e nessun giorno viene mai predetto da un modello che lo
    contiene.
    """
    ordered = sorted(set(days))
    n = len(ordered)
    if n < min_train + 30:
        return []
    usable = n - min_train
    size = max(15, usable // n_folds)
    folds = []
    start = min_train
    while start < n and len(folds) < n_folds:
        stop = min(n, start + size)
        if stop - start < 10:
            break
        folds.append((ordered[:start], ordered[start:stop]))
        start = stop
    return folds


# ==========================================================================
# Adattamento con iperparametro annidato
# ==========================================================================

def _inner_oof(samples, tier, kind, lam, n_folds=3):
    """Predizioni out-of-fold DENTRO il periodo di addestramento.

    Ritorna una LISTA di coppie (campione, predizione), non un dizionario per
    giorno. La differenza non e' cosmetica: quando si mettono insieme piu'
    scadenze nella stessa fascia, lo stesso giorno di calendario compare piu'
    volte (a D+2 e a D+3 il bersaglio e' lo stesso giorno, i predittori no).
    Una mappa per giorno ne terrebbe uno solo e le altre scadenze
    scomparirebbero senza rumore, falsando sia le metriche sia il conteggio
    dei campioni.

    I fold restano invece raggruppati PER GIORNO, perche' e' il giorno la
    cosa che non deve stare a cavallo fra addestramento e prova.
    """
    days = sorted({s["day"] for s in samples})
    if len(days) < 60:
        return None
    out = []
    folds = forward_folds(days, n_folds=n_folds, min_train=max(40, len(days) // 3))
    if not folds:
        return None
    for tr_days, te_days in folds:
        tr = set(tr_days)
        te = set(te_days)
        train = [s for s in samples if s["day"] in tr]
        test = [s for s in samples if s["day"] in te]
        m = _fit(train, tier, kind, lam)
        if m is None:
            continue
        for s in test:
            out.append((s, _apply(m, s, tier, kind)))
    return out or None


def _fit(samples, tier, kind, lam):
    if kind == "logistic":
        X = [F.vector(s["features"], tier) for s in samples]
        y = [1 if s["established"] else 0 for s in samples]
        if sum(y) < 8 or len(y) - sum(y) < 8:
            return None
        return logistic_fit(X, y, lam)
    rows = [s for s in samples if s["established"]]
    if len(rows) < 20:
        return None
    X = [F.vector(s["features"], tier) for s in rows]
    if kind == "intensity":
        y = [math.log1p(max(0.0, s["peak"])) for s in rows]
    else:                                   # timing
        rows = [s for s in rows if s.get("peak_hour") is not None]
        if len(rows) < 20:
            return None
        X = [F.vector(s["features"], tier) for s in rows]
        y = [float(s["peak_hour"]) for s in rows]
    return ridge_fit(X, y, lam)


def _apply(model, sample, tier, kind):
    v = F.vector(sample["features"], tier)
    if kind == "logistic":
        return model.predict_proba(v)
    if kind == "intensity":
        return max(0.0, math.expm1(model.predict(v)))
    return model.predict(v)


def _pick_lambda(train_samples, tier, kind):
    """Sceglie lambda con CV interna al SOLO periodo di addestramento."""
    best = (None, None)
    for lam in LAMBDA_GRID:
        oof = _inner_oof(train_samples, tier, kind, lam)
        if not oof:
            continue
        if kind == "logistic":
            pairs = [(p, 1 if s["established"] else 0) for s, p in oof]
            loss = brier([p for p, _ in pairs], [o for _, o in pairs])
        else:
            key = "peak" if kind == "intensity" else "peak_hour"
            pairs = [(p, s[key]) for s, p in oof
                     if s["established"] and s.get(key) is not None]
            if len(pairs) < 15:
                continue
            met = regression_metrics([p for p, _ in pairs], [o for _, o in pairs])
            loss = met["rmse"] if met else None
        if loss is not None and (best[0] is None or loss < best[0]):
            best = (loss, lam)
    return best[1] or LAMBDA_GRID[1]


def _calibration_blocks(train_samples, tier, lam):
    """Isotonica tarata sulle out-of-fold del SOLO periodo di addestramento."""
    inner = _inner_oof(train_samples, tier, "logistic", lam)
    if not inner or len(inner) < 40:
        return []
    return pava([p for _s, p in inner],
                [1 if s["established"] else 0 for s, _p in inner])


# ==========================================================================
# Valutazione di un candidato a una scadenza
# ==========================================================================

def evaluate(samples, tier, holdout=None, with_timing=True):
    """Forward chaining completo. Ritorna predizioni fuori campione.

    `samples` deve contenere SOLO campioni il cui vettore di feature era
    disponibile all'emissione della previsione a quella scadenza.

    Le predizioni escono come liste di coppie (campione, predizione): lo stesso
    giorno puo' comparire piu' volte se la fascia mette insieme piu' scadenze.
    """
    days = sorted({s["day"] for s in samples})
    train_days, blind = split_blind(days, holdout)
    folds = forward_folds(train_days)
    if not folds:
        return None

    occ, inten, timing, cal_used = [], [], [], []
    for tr_days, te_days in folds:
        tr, te = set(tr_days), set(te_days)
        train = [s for s in samples if s["day"] in tr]
        test = [s for s in samples if s["day"] in te]
        if len(train) < 60 or not test:
            continue

        # --- probabilita' ---
        lam = _pick_lambda(train, tier, "logistic")
        model = _fit(train, tier, "logistic", lam)
        if model is not None:
            # La calibrazione nasce dalle predizioni out-of-fold del SOLO
            # periodo di addestramento: il fold di prova non la vede mai.
            blocks = _calibration_blocks(train, tier, lam)
            cal_used.append(len(blocks))
            for s in test:
                raw = _apply(model, s, tier, "logistic")
                occ.append((s, apply_calibration(raw, blocks) if blocks else raw))

        # --- intensita' (solo giorni con regime, come in esercizio) ---
        lam_i = _pick_lambda(train, tier, "intensity")
        mi = _fit(train, tier, "intensity", lam_i)
        if mi is not None:
            for s in test:
                inten.append((s, _apply(mi, s, tier, "intensity")))

        # --- orario ---
        if with_timing:
            lam_t = _pick_lambda(train, tier, "timing")
            mt = _fit(train, tier, "timing", lam_t)
            if mt is not None:
                for s in test:
                    timing.append((s, _apply(mt, s, tier, "timing")))

    return {
        "tier": tier,
        "prob": occ, "intensity": inten, "timing": timing,
        "test_days": sorted({s["day"] for s, _p in occ}),
        "n_test": len(occ),
        "blind_days": blind,
        "n_folds": len(folds),
        "calibration_blocks": median(cal_used) if cal_used else 0,
    }


# ==========================================================================
# Metriche
# ==========================================================================

def probability_metrics(pred):
    """pred: [(campione, probabilita')]."""
    pairs = [(p, 1 if s["established"] else 0) for s, p in pred]
    if len(pairs) < 20:
        return None
    ps = [p for p, _ in pairs]
    os_ = [o for _, o in pairs]
    base = mean(os_)
    ll = -mean([o * math.log(clamp(p, 1e-6, 1 - 1e-6))
                + (1 - o) * math.log(1 - clamp(p, 1e-6, 1 - 1e-6))
                for p, o in pairs])
    ll_base = -mean([o * math.log(clamp(base, 1e-6, 1 - 1e-6))
                     + (1 - o) * math.log(1 - clamp(base, 1e-6, 1 - 1e-6))
                     for _p, o in pairs])
    bins = []
    for i in range(5):
        lo, hi = i / 5.0, (i + 1) / 5.0
        sel = [(p, o) for p, o in pairs if lo <= p < hi or (i == 4 and p >= hi)]
        if sel:
            bins.append({"lo": lo, "hi": hi, "n": len(sel),
                         "declared": mean([p for p, _ in sel]),
                         "observed": mean([o for _, o in sel])})
    # Scostamento medio fra dichiarato e osservato, pesato sui campioni.
    tot = sum(b["n"] for b in bins) or 1
    cal_err = sum(b["n"] * abs(b["declared"] - b["observed"]) for b in bins) / tot
    return {
        "n": len(pairs), "base_rate": base,
        "brier": brier(ps, os_), "brier_base": brier([base] * len(pairs), os_),
        "brier_each": [(p - o) ** 2 for p, o in pairs],
        "brier_base_each": [(base - o) ** 2 for _p, o in pairs],
        "logloss": ll, "logloss_base": ll_base,
        "calibration_error": cal_err, "reliability": bins,
    }


def _copertura_banda(resid, pred, obs):
    """Frazione di osservati dentro la banda 10-90% costruita da quei residui.

    Non e' una tautologia solo perche' la banda ha un verso: se i quantili
    venissero applicati al contrario - come succedeva - questo numero scende
    sotto l'80% dichiarato, e si vede in diagnostica.
    """
    if not resid or len(resid) < 20:
        return None
    q10, q90 = quantile(resid, 0.10), quantile(resid, 0.90)
    los, his = [], []
    for p in pred:
        lo, hi = banda_da_residui(p, q10, q90)
        los.append(lo)
        his.append(hi)
    cov, _n = interval_coverage(los, his, obs)
    return cov


def intensity_metrics(pred, planing_kn=None):
    """pred: [(campione, intensita' prevista)]. Solo i giorni con regime."""
    rows = [(s, p) for s, p in pred if s["established"]]
    pairs = [(p, s["peak"]) for s, p in rows]
    if len(pairs) < 15:
        return None
    ps = [p for p, _ in pairs]
    os_ = [o for _, o in pairs]
    met = regression_metrics(ps, os_)
    # Terzetti allineati (modello, grezzo, osservato) sugli stessi campioni:
    # il bootstrap appaiato ha senso solo se i due errori vengono dallo stesso
    # giorno, altrimenti confronta due popolazioni diverse.
    trip = [(p, s["features"].get("w10_win"), s["peak"]) for s, p in rows
            if s["features"].get("w10_win") is not None]
    raw = [(r, o) for _p, r, o in trip]
    med = median(os_)
    out = {
        "n": met["n"], "mae": met["mae"], "bias": met["bias"], "rmse": met["rmse"],
        "mae_raw": mean([abs(a - b) for a, b in raw]) if len(raw) > 10 else None,
        "mae_clim": mean([abs(med - o) for o in os_]),
        # La mediana climatologica esce da qui perche' serve a model.predict:
        # dove la porta dell'intensita' si chiude, il ripiego deve essere la
        # climatologia, non il prior fisico. Prima questa chiave la produceva
        # solo il modello "daily", quindi per i modelli per fascia il ripiego
        # non esisteva e tornava il prior - 10,4 kn a Campione-Ora contro 14
        # di mediana, cioe' "non vale la pena" al posto di "ci siamo".
        "clim_median": med,
        # La copertura vera della banda 10-90%: quante volte l'osservato ci
        # cade dentro, sulle previsioni fuori campione. E' la sentinella che
        # avrebbe smascherato il segno sbagliato della banda, e non era
        # collegata a niente.
        "coverage": _copertura_banda(met["resid"], ps, os_),
        "coverage_n": met["n"],
        "resid": met["resid"],
        # Errori appaiati, campione per campione: sono quelli che il bootstrap
        # ricampiona. Senza appaiamento l'intervallo sarebbe troppo largo.
        "ae_each": [abs(p - o) for p, _r, o in trip],
        "ae_raw_each": [abs(r - o) for _p, r, o in trip] if len(trip) > 10 else None,
        "ae_clim_each": [abs(med - o) for _p, _r, o in trip],
    }
    # Errore sulle giornate che contano davvero e sui picchi.
    if planing_kn:
        useful = [(p, o) for p, o in pairs if o >= planing_kn]
        if len(useful) > 10:
            out["mae_useful"] = mean([abs(p - o) for p, o in useful])
            out["n_useful"] = len(useful)
    strong = sorted(pairs, key=lambda po: -po[1])[:max(10, len(pairs) // 5)]
    out["mae_top20"] = mean([abs(p - o) for p, o in strong])
    return out


def timing_metrics(pred):
    """pred: [(campione, ora prevista del picco)]."""
    rows = [(s, p) for s, p in pred
            if s["established"] and s.get("peak_hour") is not None]
    errs = [p - s["peak_hour"] for s, p in rows]
    if len(errs) < 15:
        return None
    a = [abs(e) for e in errs]
    raws = [(s["features"].get("raw_peak_hour"), s["peak_hour"]) for s, _p in rows
            if s["features"].get("raw_peak_hour") is not None]
    return {
        "n": len(errs),
        "mae_min": mean(a) * 60.0,
        "median_min": median(a) * 60.0,
        "p30": mean([1.0 if x * 60 <= 30 else 0.0 for x in a]),
        "p60": mean([1.0 if x * 60 <= 60 else 0.0 for x in a]),
        "bias_min": mean(errs) * 60.0,
        "mae_raw_min": (mean([abs(r - o) for r, o in raws]) * 60.0) if len(raws) > 10 else None,
    }


def empirical_band(resid, lo=0.10, hi=0.90):
    """Banda di incertezza dai residui VERI a questa scadenza.

    Sostituisce i moltiplicatori scritti a mano della 3.5, che non erano
    stimati da niente.
    """
    if not resid or len(resid) < 20:
        return None, None
    return quantile(resid, lo), quantile(resid, hi)


# ==========================================================================
# Bootstrap sull'intervallo di confidenza del miglioramento
# ==========================================================================

def bootstrap_gain(model_err, base_err, n=BOOTSTRAP, seed=7):
    """IC del miglioramento relativo, ricampionando le coppie di errori.

    Ritorna (guadagno%, ic_basso%, ic_alto%). Se l'intervallo attraversa lo
    zero, il miglioramento non e' distinguibile dal rumore e non giustifica
    una promozione.
    """
    pairs = [(m, b) for m, b in zip(model_err, base_err)
             if m is not None and b is not None]
    if len(pairs) < 20:
        return None, None, None
    rng = random.Random(seed)
    k = len(pairs)
    gains = []
    for _ in range(n):
        sample = [pairs[rng.randrange(k)] for _ in range(k)]
        mm = mean([a for a, _ in sample])
        bb = mean([b for _, b in sample])
        if bb > 1e-9:
            gains.append(100.0 * (1.0 - mm / bb))
    if not gains:
        return None, None, None
    point = 100.0 * (1.0 - mean([a for a, _ in pairs]) / mean([b for _, b in pairs]))
    return point, quantile(gains, 0.025), quantile(gains, 0.975)


# ==========================================================================
# Un modello per fascia di scadenza
# ==========================================================================

def _gate(model_each, base_each, margin=None):
    """Promozione: meglio della baseline, e il meglio non e' rumore.

    Due condizioni, entrambe necessarie. Il margine da' la soglia minima di
    miglioramento; l'intervallo bootstrap dice se quel miglioramento
    sopravvive al ricampionamento. Un guadagno del 5% con intervallo da -4% a
    +13% non e' un guadagno, e' un campione fortunato.
    """
    margin = config.PROMOTION_MARGIN if margin is None else margin
    if not model_each or not base_each:
        return False, None, None, None
    m, b = mean(model_each), mean(base_each)
    point, lo, hi = bootstrap_gain(model_each, base_each)
    ok = bool(b and b > 0 and m < b * (1 - margin) and lo is not None and lo > 0)
    return ok, point, lo, hi


def _split_by_lead(pairs):
    out = {}
    for s, p in pairs:
        out.setdefault(int(s.get("lead", 0)), []).append((s, p))
    return out


def fit_band(spot_name, samples, tier, band, holdout=None):
    """Addestra e valida il modello di UNA fascia di scadenza.

    Tutto cio' che esce da qui e' fuori campione e ottenuto in avanti nel
    tempo: forward chaining per i fold, lambda scelto dentro il solo periodo
    di addestramento, isotonica tarata sulle out-of-fold di quel periodo, e il
    blocco finale mai toccato. Le metriche per singola scadenza nascono
    spezzando le stesse predizioni fuori campione: e' la prestazione del
    modello che verra' realmente pubblicato a quella scadenza, non quella di un
    modello costruito su misura per essa.
    """
    spot = config.SPOTS[spot_name]
    ev = evaluate(samples, tier, holdout=holdout,
                  with_timing=(spot["target"] == "hourly"))
    if not ev:
        return None

    pm = probability_metrics(ev["prob"])
    im = intensity_metrics(ev["intensity"], planing_kn=spot["min_kn"])
    tm = timing_metrics(ev["timing"]) if ev["timing"] else None

    ok_p = ok_i = False
    gain_p = gain_i = (None, None, None)
    if pm:
        ok_p, *g = _gate(pm["brier_each"], pm["brier_base_each"])
        gain_p = tuple(g)
    if im:
        base_each = im["ae_raw_each"] or im["ae_clim_each"]
        if im["ae_raw_each"] and im["ae_clim_each"]:
            # Si batte la MIGLIORE delle due baseline, non la piu' comoda.
            base_each = (im["ae_raw_each"]
                         if mean(im["ae_raw_each"]) <= mean(im["ae_clim_each"])
                         else im["ae_clim_each"])
        ok_i, *g = _gate(im["ae_each"], base_each)
        gain_i = tuple(g)

    # --- modello finale: solo il periodo di addestramento ---
    blind = set(ev["blind_days"])
    train = [s for s in samples if s["day"] not in blind]
    lam_o = _pick_lambda(train, tier, "logistic")
    occ = _fit(train, tier, "logistic", lam_o)
    blocks = _calibration_blocks(train, tier, lam_o)
    lam_i = _pick_lambda(train, tier, "intensity")
    inten = _fit(train, tier, "intensity", lam_i)
    q10, q90 = empirical_band(im["resid"]) if im else (None, None)

    per_lead = {}
    prob_by_lead = _split_by_lead(ev["prob"])
    int_by_lead = _split_by_lead(ev["intensity"])
    time_by_lead = _split_by_lead(ev["timing"])
    for lead in sorted(set(list(prob_by_lead) + list(int_by_lead))):
        p = probability_metrics(prob_by_lead.get(lead, []))
        i = intensity_metrics(int_by_lead.get(lead, []), planing_kn=spot["min_kn"])
        t = timing_metrics(time_by_lead.get(lead, []))
        entry = {
            "lead": lead,
            "n_test_days": len({s["day"] for s, _x in prob_by_lead.get(lead, [])}),
            "prob": {k: v for k, v in (p or {}).items()
                     if not k.endswith("_each")} or None,
            "intensity": {k: v for k, v in (i or {}).items()
                          if k not in ("resid",) and not k.endswith("_each")} or None,
            "timing": t,
        }
        if i:
            # Anche qui la MIGLIORE delle due baseline, non la piu' comoda:
            # questo e' il guadagno per singola scadenza, quello che finisce in
            # diagnostica e in confidence._skill. Testarlo contro il solo
            # grezzo poteva marcare "significativo" un peggioramento rispetto
            # alla climatologia.
            base_each = i["ae_raw_each"] or i["ae_clim_each"]
            if i["ae_raw_each"] and i["ae_clim_each"]:
                base_each = (i["ae_raw_each"]
                             if mean(i["ae_raw_each"]) <= mean(i["ae_clim_each"])
                             else i["ae_clim_each"])
            g_ok, g_pt, g_lo, g_hi = _gate(i["ae_each"], base_each)
            entry["gain_int"] = {"punto": g_pt, "ic_lo": g_lo, "ic_hi": g_hi,
                                 "significativo": g_ok}
            lo_q, hi_q = empirical_band(i["resid"])
            entry["banda"] = {"q10": lo_q, "q90": hi_q}
        if p:
            g_ok, g_pt, g_lo, g_hi = _gate(p["brier_each"], p["brier_base_each"])
            entry["gain_prob"] = {"punto": g_pt, "ic_lo": g_lo, "ic_hi": g_hi,
                                  "significativo": g_ok}
        per_lead[lead] = entry

    validated = bool(ok_p and ok_i and occ is not None and inten is not None)
    return {
        "band": band, "tier": tier,
        "n": len(train), "n_test": ev["n_test"],
        "n_test_days": len(ev["test_days"]),
        "leads": sorted({int(s.get("lead", 0)) for s in samples}),
        "days_from": min(s["day"] for s in samples),
        "days_to": max(s["day"] for s in samples),
        "n_blind_days": len(ev["blind_days"]),
        "n_folds": ev["n_folds"],
        "calibration_blocks": ev["calibration_blocks"],
        "prob": {k: v for k, v in (pm or {}).items() if not k.endswith("_each")} or None,
        "intensity": {k: v for k, v in (im or {}).items()
                      if k != "resid" and not k.endswith("_each")} or None,
        "timing": tm,
        "gain_prob": {"punto": gain_p[0], "ic_lo": gain_p[1], "ic_hi": gain_p[2],
                      "significativo": ok_p},
        "gain_int": {"punto": gain_i[0], "ic_lo": gain_i[1], "ic_hi": gain_i[2],
                     "significativo": ok_i},
        "per_lead": per_lead,
        "validated": validated,
        "payload": {
            "tier": tier, "lead_band": band,
            "occurrence": occ.to_dict() if occ else None,
            "intensity": inten.to_dict() if inten else None,
            "calibration": blocks,
            "q10": q10, "q90": q90,
            "lam_occ": lam_o, "lam_int": lam_i,
        },
    }


def band_study(spot_name, samples_by_lead, tier, candidates=None):
    """Quale taglio di fasce regge meglio, scelto sul periodo di addestramento.

    Confronta anche il caso "unico", cioe' nessuna separazione. Se separare non
    migliora, non si separa: tre modelli invece di uno sono tre volte piu'
    parametri da stimare sugli stessi giorni.
    """
    candidates = candidates or config.BAND_CANDIDATES
    out = []
    for layout in candidates:
        rows, ok = [], True
        for name, (a, b) in layout:
            pooled = []
            for lead in range(a, b + 1):
                pooled.extend(samples_by_lead.get(lead) or [])
            if len(pooled) < 120:
                ok = False
                continue
            r = fit_band(spot_name, pooled, tier, name)
            if not r:
                ok = False
                continue
            rows.append(r)
        if not rows:
            continue
        # Perdita complessiva: Brier e MAE pesati sui campioni di prova, cosi'
        # una fascia con pochi giorni non domina il confronto.
        wn = sum(r["n_test"] for r in rows) or 1
        brier_w = sum((r["prob"] or {}).get("brier", 0.0) * r["n_test"]
                      for r in rows) / wn
        mae_rows = [r for r in rows if r["intensity"]]
        mae_w = (sum(r["intensity"]["mae"] * r["intensity"]["n"] for r in mae_rows)
                 / sum(r["intensity"]["n"] for r in mae_rows)) if mae_rows else None
        # Il criterio va dichiarato, non lasciato implicito in un min(). Ogni
        # stadio viene misurato come guadagno RELATIVO sul proprio riferimento
        # banale, perche' Brier e MAE non sono commensurabili: un Brier di
        # 0,24 e un MAE di 2,1 kn non si sommano. I due guadagni, che sono
        # entrambi frazioni, si mediano. Un taglio che perde su uno stadio e
        # vince sull'altro risulta cosi' a pari, ed e' giusto: la scelta fra i
        # due la fa chi conosce l'uso, non una somma silenziosa.
        gain_p = sum(max(0.0, 1.0 - (r["prob"] or {}).get("brier", 1.0)
                         / ((r["prob"] or {}).get("brier_base") or 1.0)) * r["n_test"]
                     for r in rows) / wn
        gi = [r for r in mae_rows if r["intensity"].get("mae_raw")]
        gain_i = (sum(max(0.0, 1.0 - r["intensity"]["mae"] / r["intensity"]["mae_raw"])
                      * r["intensity"]["n"] for r in gi)
                  / sum(r["intensity"]["n"] for r in gi)) if gi else None
        out.append({
            "layout": [(n, tuple(rng)) for n, rng in layout],
            "completo": ok,
            "brier_pesato": brier_w,
            "mae_pesato": mae_w,
            "guadagno_prob": gain_p,
            "guadagno_int": gain_i,
            "punteggio": mean([x for x in (gain_p, gain_i) if x is not None]),
            "fasce": [{"band": r["band"], "n": r["n"], "n_test": r["n_test"],
                       "validata": r["validated"],
                       "brier": (r["prob"] or {}).get("brier"),
                       "mae": (r["intensity"] or {}).get("mae")} for r in rows],
        })
    scored = [o for o in out if o["punteggio"] is not None]
    best = max(scored, key=lambda o: o["punteggio"]) if scored else None
    return {"candidati": out, "criterio": "media dei guadagni relativi sui "
                                          "riferimenti banali, pesata sui campioni",
            "scelto": best["layout"] if best else None}


# ==========================================================================
# Settore direzionale: scelto dai dati, non a mano
# ==========================================================================

def sector_evidence(day_records, axis):
    """Distribuzione delle direzioni osservate nei giorni ventosi.

    Non usa il modello: guarda solo le osservazioni. Serve a scegliere
    l'ampiezza del settore su una base empirica invece che "sembra
    ragionevole". Ritorna, per ciascuna soglia candidata, quanti giorni
    ventosi cadono dentro e la concentrazione direzionale.

    day_records: [(picco_kn, direzione_al_picco, mese)]
    """
    from .util import angle_diff
    windy = [(v, d, m) for v, d, m in day_records if d is not None]
    if len(windy) < 50:
        return None
    diffs = [angle_diff(d, axis) for _v, d, _m in windy]
    out = {"n": len(windy), "median_diff": median(diffs), "thresholds": []}
    for th in (30.0, 45.0, 60.0, 70.0, 90.0):
        inside = [x for x in diffs if x <= th]
        out["thresholds"].append({
            "deg": th,
            "share": len(inside) / len(diffs),
            "mean_wind_inside": mean([v for (v, d, _m), x in zip(windy, diffs) if x <= th]),
            "mean_wind_outside": mean([v for (v, d, _m), x in zip(windy, diffs) if x > th]),
        })
    by_season = {}
    for (v, d, m), x in zip(windy, diffs):
        season = "inverno" if m in (12, 1, 2) else "primavera" if m in (3, 4, 5) \
            else "estate" if m in (6, 7, 8) else "autunno"
        by_season.setdefault(season, []).append(x)
    out["by_season"] = {k: {"n": len(v), "median_diff": median(v)}
                        for k, v in by_season.items() if len(v) >= 20}
    return out
