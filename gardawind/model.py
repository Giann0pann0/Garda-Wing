"""Modello previsionale a due stadi, con promozione validata.

Struttura
---------
Stadio A  probabilita' che il regime si instauri nella finestra del giorno.
Stadio B  intensita' attesa (picco della media oraria) CONDIZIONATA al fatto
          che si instauri, addestrata solo sui giorni in cui e' successo.

Perche' due stadi: la distribuzione del vento sull'alto Garda e' bimodale.
O l'Ora entra, e sono 15-25 nodi, o non entra, e sono 3-6 nodi. Una singola
regressione stima la media dei due regimi, cioe' un valore che non si verifica
quasi mai: sovrastima sistematicamente i giorni morti e sottostima i giorni
buoni. Separare "se" da "quanto" e' anche molto piu' efficiente in termini di
campioni, perche' la classificazione ha bisogno di meno dati della regressione.

Promozione
----------
Tre livelli di complessita' (bias -> ridotto -> completo). Un livello viene
adottato solo se, in validazione a finestra crescente IN AVANTI NEL TEMPO,
batte SIA il livello precedente SIA i riferimenti banali (frequenza
climatologica per la probabilita', mediana e vento grezzo d'ensemble per
l'intensita'). Se nessun livello passa, si resta sul prior fisico e lo si
dichiara.

Tutte le metriche pubblicate sono fuori campione, e "fuori campione" qui vuol
dire anche fuori dal futuro: nessun giorno viene predetto da un modello che ha
visto i giorni successivi, e la calibrazione di ogni fold nasce dai soli fold
precedenti. Nessuna metrica in-sample raggiunge mai l'interfaccia: sarebbe una
promessa che il modello non puo' mantenere.

Le scadenze oltre il giorno corrente non passano da qui ma da validate.fit_band,
un modello per fascia, ognuno con i propri campioni e le proprie metriche.
"""

import math

from . import config, features as F
from .util import (banda_da_residui, brier, clamp, forward_folds_idx,
                   interval_coverage, LogisticModel, logistic_fit, mean,
                   median, quantile, regression_metrics, reliability_table,
                   RidgeModel, ridge_fit, sigmoid)

LAMBDA_GRID = (0.25, 1.0, 4.0, 16.0, 64.0)

# Qui stavano LEAD_SHRINK e LEAD_WIDEN: due tabelle di moltiplicatori, uno per
# scadenza, che attenuavano la probabilita' verso la climatologia e allargavano
# la banda. Non erano stimati da niente. "0.62 a quattro giorni" aveva l'aria
# di una misura e non lo era, e un numero inventato che sembra misurato e'
# peggio di nessun numero: chi legge non ha modo di sapere quale delle due cose
# sta guardando.
#
# Sono stati rimossi e sostituiti da due cose che si misurano:
#
#   attenuazione  la calibrazione isotonica tarata ALLA SCADENZA. Se a D+5 il
#                 modello non sa distinguere, la curva di affidabilita' di
#                 quella scadenza appiattisce da sola le probabilita' verso la
#                 frequenza climatologica: e' lo stesso effetto, ma stimato.
#   banda         i quantili dei residui misurati ALLA SCADENZA.
#
# Dove la scadenza non e' ancora validata non si inventa un sostituto: la
# banda viene dalla dispersione d'ensemble (che e' una misura, non una
# supposizione) e la previsione viaggia dichiarata come non validata.


# ==========================================================================
# Calibrazione isotonica (pool adjacent violators)
# ==========================================================================

def pava(probs, outcomes, min_per_block=None):
    """Calibrazione isotonica con blocchi di ampiezza minima: [p_lo, p_hi, freq].

    Una probabilita' non calibrata e' peggio che inutile: se l'app dice 70%
    devono essere 7 volte su 10, altrimenti chi legge impara a non fidarsi.

    L'AMPIEZZA MINIMA NON E' UN DETTAGLIO, e la sua assenza era un difetto
    grave. L'algoritmo dei violatori adiacenti, applicato ai singoli campioni,
    fonde solo i blocchi che violano la monotonia: tutti gli altri restano di
    un campione, e la loro "frequenza osservata" e' lo zero o l'uno di quel
    giorno. Una curva cosi' non calibra, memorizza. Misurata sugli stessi dati
    su cui e' nata da' un Brier quasi perfetto - restituisce l'esito vero - e
    su dati nuovi restituisce 0 o 1 a caso. Il difetto era invisibile finche'
    la curva veniva tarata e valutata sullo stesso insieme; e' bastato spostare
    la calibrazione fuori dal fold di prova per vederlo.

    Qui i campioni vengono prima raccolti in blocchi di conteggio uguale (per
    difetto circa la radice del numero di campioni, mai meno di venti), e solo
    dopo si fondono i violatori. Ogni frequenza pubblicata poggia quindi su
    almeno venti giornate.
    """
    pairs = sorted(zip(probs, outcomes))
    n = len(pairs)
    if n == 0:
        return []
    if min_per_block is None:
        min_per_block = max(20, int(n ** 0.5))
    bins = []
    for i in range(0, n, min_per_block):
        chunk = pairs[i:i + min_per_block]
        bins.append([chunk[0][0], chunk[-1][0],
                     float(sum(y for _p, y in chunk)), float(len(chunk))])
    # Ultimo spezzone troppo corto: si fonde col precedente invece di restare
    # un blocco fragile in cima, che e' proprio la zona delle probabilita' alte.
    # "Troppo corto" vuol dire sotto il minimo dichiarato, non sotto la sua
    # meta': con la meta', la docstring qui sopra promette venti giornate e il
    # blocco in cima ne poteva avere dieci - e dieci giornate, otto delle quali
    # entrate, pubblicano "80%" dove l'intervallo binomiale va dal 44 al 97.
    if len(bins) >= 2 and bins[-1][3] < min_per_block:
        b, a = bins.pop(), bins.pop()
        bins.append([a[0], b[1], a[2] + b[2], a[3] + b[3]])

    out = []
    for b in bins:
        out.append(b)
        while len(out) >= 2 and out[-2][2] / out[-2][3] > out[-1][2] / out[-1][3]:
            y, x = out.pop(), out.pop()
            out.append([x[0], y[1], x[2] + y[2], x[3] + y[3]])
    return [[lo, hi, s / c] for lo, hi, s, c in out]


def apply_calibration(p, blocks):
    """Interpola fra i centri dei blocchi, invece di restituire un gradino.

    Con blocchi larghi il gradino butterebbe via la graduatoria dentro il
    blocco: due giorni a 0,41 e 0,58 uscirebbero identici. L'interpolazione
    lineare fra i centri conserva l'ordine e resta monotona, perche' i valori
    dei blocchi sono crescenti per costruzione.
    """
    if not blocks:
        return p
    if len(blocks) == 1:
        return blocks[0][2]
    centers = [(lo + hi) / 2.0 for lo, hi, _v in blocks]
    vals = [v for _lo, _hi, v in blocks]
    if p <= centers[0]:
        return vals[0]
    if p >= centers[-1]:
        return vals[-1]
    for i in range(1, len(centers)):
        if p <= centers[i]:
            c0, c1 = centers[i - 1], centers[i]
            t = 0.0 if c1 <= c0 else (p - c0) / (c1 - c0)
            return vals[i - 1] + t * (vals[i] - vals[i - 1])
    return vals[-1]


# ==========================================================================
# Addestramento
# ==========================================================================

def _fit_stage(X, y, groups, kind, lam_grid=LAMBDA_GRID, folds=5):
    """Sceglie lambda in cross-validation e restituisce (modello, oof, lam).

    I fold sono a finestra crescente in avanti nel tempo (vedi
    util.forward_folds_idx): il modello che predice un giorno non ha mai visto
    quel giorno ne' nessuno dei successivi. La versione precedente usava fold a
    blocchi, che tenevano insieme i giorni ma lasciavano che il blocco piu'
    antico venisse predetto anche con i dati degli anni dopo.
    """
    best = None
    for lam in lam_grid:
        if kind == "logistic":
            fit = lambda a, b, L=lam: logistic_fit(a, b, L)
            pred = lambda m, r: m.predict_proba(r)
        else:
            fit = lambda a, b, L=lam: ridge_fit(a, b, L)
            pred = lambda m, r: m.predict(r)

        oof = [None] * len(y)
        fold_of = [None] * len(y)
        for j, (tr, fold) in enumerate(forward_folds_idx(groups, folds)):
            if len(tr) < 10:
                continue
            m = fit([X[i] for i in tr], [y[i] for i in tr])
            if m is None:
                continue
            for i in fold:
                oof[i] = pred(m, X[i])
                fold_of[i] = j

        got = [i for i, v in enumerate(oof) if v is not None]
        if len(got) < max(12, len(y) // 3):
            continue
        if kind == "logistic":
            loss = brier([oof[i] for i in got], [y[i] for i in got])
        else:
            met = regression_metrics([oof[i] for i in got], [y[i] for i in got])
            loss = met["rmse"] if met else None
        if loss is None:
            continue
        if best is None or loss < best[0]:
            best = (loss, lam, oof, fold_of)

    if best is None:
        return None, None, None, None
    _loss, lam, oof, fold_of = best
    final = (logistic_fit(X, y, lam) if kind == "logistic" else ridge_fit(X, y, lam))
    return final, oof, lam, fold_of


def _fit_cross(eval_samples, train_samples, tier, kind, folds=5):
    """Addestra su una sorgente e predice sull'altra, fold per fold.

    I giorni del fold in valutazione vengono tolti anche dal set di
    addestramento, anche se arriva da una sorgente diversa: e' lo stesso
    giorno di calendario, quindi la stessa risposta.
    """
    eval_days = [s["day"] for s in eval_samples]
    X_eval = [F.vector(s["features"], tier) for s in eval_samples]
    if kind == "logistic":
        y_eval = [1 if s["established"] else 0 for s in eval_samples]
        target = lambda s: 1 if s["established"] else 0
        fit = logistic_fit
        predict = lambda m, r: m.predict_proba(r)
    else:
        y_eval = [math.log1p(max(0.0, s["peak"])) for s in eval_samples]
        target = lambda s: math.log1p(max(0.0, s["peak"]))
        fit = ridge_fit
        predict = lambda m, r: m.predict(r)
        train_samples = [s for s in train_samples if s["established"]]
        if len(train_samples) < 20:
            return None, None, None, None

    best = None
    for lam in LAMBDA_GRID:
        oof = [None] * len(eval_samples)
        fold_of = [None] * len(eval_samples)
        for j, (tr_idx, fold) in enumerate(forward_folds_idx(eval_days, folds)):
            # In avanti nel tempo anche qui, e con un vincolo in piu': dalla
            # sorgente di addestramento si prendono solo i giorni PRECEDENTI al
            # fold di prova. Escludere i soli giorni del fold non basterebbe:
            # un modello addestrato su ERA5 del 2023 e provato sul 2015 non
            # descrive niente che possa succedere davvero.
            limit = min(eval_days[i] for i in fold)
            tr = [s for s in train_samples if s["day"] < limit]
            if len(tr) < 15:
                continue
            if kind == "logistic":
                ys = [target(s) for s in tr]
                if sum(ys) < 5 or len(ys) - sum(ys) < 5:
                    continue
            m = fit([F.vector(s["features"], tier) for s in tr],
                    [target(s) for s in tr], lam)
            if m is None:
                continue
            for i in fold:
                oof[i] = predict(m, X_eval[i])
                fold_of[i] = j
        got = [i for i, v in enumerate(oof) if v is not None]
        if len(got) < max(12, len(eval_samples) // 4):
            continue
        if kind == "logistic":
            loss = brier([oof[i] for i in got], [y_eval[i] for i in got])
        else:
            # Il lambda si sceglie sulle giornate su cui questo modello vivra'.
            #
            # Lo stadio B risponde a "quanto tira QUANDO IL REGIME ENTRA": si
            # addestra sui soli giorni con regime (riga 219) e in produzione
            # viene applicato solo la'. Ma la perdita con cui si scegliva il
            # lambda girava su TUTTE le giornate, comprese quelle a tre nodi:
            # un errore che nessun lambda puo' ridurre e che copriva il segnale
            # vero. Misurato su dati sintetici, la parte discriminante valeva il
            # 3% della perdita, e la scelta coincideva con quella giusta in meno
            # della meta' dei casi - con scarti fino a un fattore 256, cioe' fra
            # un modello che risponde e uno che dice sempre lo stesso numero.
            scelti = [i for i in got if eval_samples[i]["established"]]
            if len(scelti) < 12:
                scelti = got
            met = regression_metrics([oof[i] for i in scelti],
                                     [y_eval[i] for i in scelti])
            loss = met["rmse"] if met else None
        if loss is not None and (best is None or loss < best[0]):
            best = (loss, lam, oof, fold_of)

    if best is None:
        return None, None, None, None
    _loss, lam, oof, fold_of = best
    final = fit([F.vector(s["features"], tier) for s in train_samples],
                [target(s) for s in train_samples], lam)
    return final, oof, lam, fold_of


def _copertura(resid, pred, obs):
    """Quante volte l'osservato cade nella banda, sulle previsioni out-of-fold."""
    q10, q90 = quantile(resid, 0.10), quantile(resid, 0.90)
    if q10 is None or q90 is None or not pred:
        return None
    coppie = [(p, o) for p, o in zip(pred, obs)
              if p is not None and o is not None]
    if not coppie:
        return None
    dentro = 0
    for p, o in coppie:
        lo, hi = banda_da_residui(p, q10, q90)
        if lo is not None and lo <= o <= hi:
            dentro += 1
    return dentro / float(len(coppie))


def _evaluate_candidate(eval_samples, train_samples, tier, source="forecast"):
    """Addestra su `train_samples` e valuta su `eval_samples`.

    Le due liste possono venire da sorgenti diverse. E' il punto in cui si
    evita l'errore piu' seducente di tutto il progetto: un modello addestrato
    sulla rianalisi ERA5 sembra bravissimo se lo si valuta sulla rianalisi,
    perche' li' gli ingressi sono lo stato atmosferico VERO. In esercizio
    ricevera' invece uno stato PREVISTO, piu' sporco. Quindi la valutazione
    usa sempre e solo i vettori costruiti dalle previsioni, qualunque sia la
    sorgente su cui si e' addestrato: e' l'unico confronto che significhi
    qualcosa.

    I giorni del fold di valutazione vengono esclusi anche dall'addestramento,
    per sorgente diversa o no: altrimenti il modello avrebbe gia' visto la
    risposta.
    """
    names = F.TIERS[tier]
    days = [s["day"] for s in eval_samples]
    X = [F.vector(s["features"], tier) for s in eval_samples]
    y_occ = [1 if s["established"] else 0 for s in eval_samples]
    peaks = [s["peak"] for s in eval_samples]

    if len(train_samples) < 3 * len(names) + 10 or len(eval_samples) < 30:
        return None
    tr_occ = [1 if s["established"] else 0 for s in train_samples]
    if sum(tr_occ) < 8 or (len(tr_occ) - sum(tr_occ)) < 8:
        return None
    if sum(y_occ) < 8 or (len(y_occ) - sum(y_occ)) < 8:
        return None

    same = (train_samples is eval_samples)
    if same:
        occ_model, occ_oof, occ_lam, fold_of = _fit_stage(X, y_occ, days, "logistic")
    else:
        occ_model, occ_oof, occ_lam, fold_of = _fit_cross(
            eval_samples, train_samples, tier, "logistic")
    if occ_model is None:
        return None
    got = [i for i, v in enumerate(occ_oof) if v is not None]

    # Calibrazione progressiva. Prima l'isotonica veniva tarata sulle STESSE
    # predizioni su cui poi si misurava il Brier: la curva di affidabilita' era
    # buona per costruzione, non per merito, e un modello con probabilita'
    # scadenti poteva sembrare calibrato. Qui ogni fold viene calibrato con i
    # soli fold PRECEDENTI, e il punteggio si misura solo sui fold che hanno
    # avuto una calibrazione vera alle spalle. Costa il primo fold.
    occ_cal = [None] * len(y_occ)
    scored = []
    folds_seen = sorted({f for f in fold_of if f is not None})
    for j in folds_seen:
        prior = [i for i in got if fold_of[i] is not None and fold_of[i] < j]
        if len(prior) < 40:
            continue
        blocks = pava([occ_oof[i] for i in prior], [y_occ[i] for i in prior])
        for i in got:
            if fold_of[i] == j:
                occ_cal[i] = apply_calibration(occ_oof[i], blocks)
                scored.append(i)
    if len(scored) < 30:
        # Troppo pochi giorni per calibrare fuori campione: si misura il
        # modello non calibrato e si dichiara. Meglio un numero grezzo di un
        # numero lucidato con l'informazione che doveva servire a giudicarlo.
        scored = list(got)
        for i in got:
            occ_cal[i] = occ_oof[i]
        cal_out_of_sample = False
    else:
        cal_out_of_sample = True

    b_model = brier([occ_cal[i] for i in scored], [y_occ[i] for i in scored])
    base_rate = mean([y_occ[i] for i in scored])
    b_base = brier([base_rate] * len(scored), [y_occ[i] for i in scored])
    # Per la produzione la curva si tara su TUTTE le out-of-fold: e' il massimo
    # di informazione disponibile, e non entra in nessun punteggio pubblicato.
    cal = pava([occ_oof[i] for i in got], [y_occ[i] for i in got])

    # Stadio B: solo i giorni in cui il regime e' entrato.
    idx = [i for i in range(len(eval_samples)) if y_occ[i]]
    int_model = int_oof = int_lam = None
    m_int = None
    base_mae = model_mae = None
    resid = []
    clim_median = None
    terzetti = []          # (previsto, grezzo, osservato) sulle stesse giornate
    if len(idx) >= max(20, 2 * len(names)):
        # Le due strade possono non trovare un modello (troppe poche giornate
        # per i fold, o per la sorgente incrociata): in quel caso restituiscono
        # None su tutta la linea, e le previsioni fuori campione non esistono.
        # Si controlla PRIMA di indicizzare: con Campione, che ha meno anni di
        # Torbole, e' successo, e l'addestramento di tutte le localita' e'
        # morto per una che non aveva ancora abbastanza giornate.
        if same:
            Xi = [X[i] for i in idx]
            yi = [math.log1p(max(0.0, peaks[i])) for i in idx]
            gi = [days[i] for i in idx]
            int_model, int_oof, int_lam, _f = _fit_stage(Xi, yi, gi, "ridge")
            pred_all = ([math.expm1(v) if v is not None else None for v in int_oof]
                        if int_oof is not None else None)
        else:
            int_model, oof_full, int_lam, _f = _fit_cross(
                eval_samples, train_samples, tier, "ridge")
            pred_all = ([math.expm1(oof_full[i]) if oof_full[i] is not None else None
                         for i in idx] if oof_full is not None else None)
        if int_model is not None and pred_all is not None:
            pred = pred_all
            obs = [peaks[i] for i in idx]
            m_int = regression_metrics(pred, obs)
            if m_int:
                model_mae = m_int["mae"]
                resid = m_int["resid"]
                # Due riferimenti da battere: la mediana climatologica e il
                # vento grezzo d'ensemble. Il secondo e' quello che conta:
                # se non battiamo il modello nudo, tutta questa macchina non
                # serve a niente.
                #
                # LO STESSO METRO. Il MAE del modello vive solo dove la
                # previsione fuori campione esiste: il primo 40% delle
                # giornate serve ad addestrare i primi fold e li' `pred` e'
                # None. I riferimenti invece si calcolavano su TUTTE le
                # giornate, e il loro rapporto e' sia la percentuale di
                # "guadagno" che pubblichiamo sia la porta che decide se un
                # modello entra in produzione. Su un archivio i cui primi anni
                # sono piu' dispersi - il caso normale - il modello vinceva
                # per il solo fatto di essere stato esaminato su giornate piu'
                # facili. Qui si confrontano sulle STESSE giornate.
                coppie_eval = [(i, p, o) for i, p, o in zip(idx, pred, obs)
                               if p is not None]
                obs_eval = [o for _i, _p, o in coppie_eval]
                med = median(obs_eval) if obs_eval else None
                mae_med = (mean([abs(med - o) for o in obs_eval])
                           if med is not None else None)
                terzetti = [(p, eval_samples[i]["features"].get("w10_win"), o)
                            for i, p, o in coppie_eval]
                raw_coppie = [(r, o) for _p, r, o in terzetti if r is not None]
                mae_raw = (mean([abs(r - o) for r, o in raw_coppie])
                           if len(raw_coppie) > 10 else None)
                base_mae = min([x for x in (mae_med, mae_raw) if x is not None]
                               or [None])
                clim_median = med

    # LA PORTA: il margine NON BASTA, ci vuole anche il bootstrap.
    #
    # Qui si promuoveva col solo margine, mentre validate._gate - che governa i
    # modelli per fascia - chiede entrambe le cose, e il README promette la
    # regola forte per tutti: "un modello entra in produzione solo se batte i
    # riferimenti banali... con un intervallo bootstrap che non attraversa lo
    # zero". Il modello "daily" e' quello usato a D+0 e ogni volta che la
    # fascia manca, e il suo `usable` decide sia la fonte dell'intensita' sia
    # la colonna "In uso" della diagnostica: era il piu' importante dei due, e
    # aveva la porta piu' larga.
    #
    # Misurato su bersagli di puro rumore: con 120-200 giornate la porta della
    # probabilita' si apriva in circa un caso su quindici. Riguarda le
    # localita' nuove, cioe' Campione e Malcesine.
    from .validate import bootstrap_gain
    err_occ_m = [(occ_cal[i] - y_occ[i]) ** 2 for i in scored]
    err_occ_b = [(base_rate - y_occ[i]) ** 2 for i in scored]
    _p, lo_occ, _h = bootstrap_gain(err_occ_m, err_occ_b) if scored else (None, None, None)
    ok_occ = (b_model is not None and b_base is not None
              and b_model < b_base * (1 - config.PROMOTION_MARGIN)
              and lo_occ is not None and lo_occ > 0)

    lo_int = None
    if m_int and base_mae is not None and terzetti:
        # Le giornate sono quelle in cui la previsione fuori campione esiste
        # (vedi sopra: accoppiare un numero con un buco non e' un confronto).
        #
        # E il riferimento e' QUELLO CHE MORDE. Il margine si misura contro il
        # migliore dei due (mediana climatologica o vento grezzo), ma il
        # bootstrap girava sempre e solo contro la mediana: dove il grezzo era
        # il riferimento duro, la prova di significativita' non lo toccava
        # mai, e un modello poteva risultare "validato" per un vantaggio del
        # 3% su un riferimento che nessuno aveva testato.
        err_int_m = [abs(p - o) for p, _r, o in terzetti]
        base_med = [abs(clim_median - o) for _p, _r, o in terzetti]
        con_grezzo = [(p, r, o) for p, r, o in terzetti if r is not None]
        if (len(con_grezzo) > 10
                and mean([abs(r - o) for _p, r, o in con_grezzo])
                <= mean([abs(clim_median - o) for _p, _r, o in con_grezzo])):
            err_int_m = [abs(p - o) for p, _r, o in con_grezzo]
            base_each = [abs(r - o) for _p, r, o in con_grezzo]
        else:
            base_each = base_med
        _p, lo_int, _h = bootstrap_gain(err_int_m, base_each)
    ok_int = (model_mae is not None and base_mae is not None
              and model_mae < base_mae * (1 - config.PROMOTION_MARGIN)
              and lo_int is not None and lo_int > 0)

    return {
        "tier": tier,
        "source": source,
        "n": len(train_samples),
        "n_eval": len(eval_samples),
        "n_established": sum(tr_occ),
        "occurrence": occ_model,
        "intensity": int_model,
        "calibration": cal,
        "lam_occ": occ_lam,
        "lam_int": int_lam,
        "brier": b_model,
        "brier_base": b_base,
        "base_rate": base_rate,
        "mae": model_mae,
        "mae_base": base_mae,
        # La mediana del picco nei giorni entrati: e' il riferimento che il
        # modello deve battere, e dove non lo batte e' anche la previsione
        # migliore che abbiamo - vedi predict_day.
        "clim_median": clim_median,
        "gain_lo_occ": lo_occ,
        "gain_lo_int": lo_int,
        "rmse": m_int["rmse"] if m_int else None,
        # La COPERTURA, misurata sulle previsioni fuori campione.
        #
        # Prima la calcolava verify_intervals applicando il modello FINALE -
        # quello riaddestrato su tutti i campioni - agli stessi campioni con
        # cui era stato addestrato. Il numero usciva gonfiato: misurato su dati
        # sintetici, 83-85% dichiarato contro 73-77% vero, con 80-200 giornate.
        # E finiva sotto l'intestazione che promette "tutti i numeri sono
        # misurati su giorni che il modello non aveva mai visto".
        #
        # Qui le previsioni sono quelle out-of-fold, quindi il grosso
        # dell'ottimismo sparisce. Resta quello dei quantili, che sono stimati
        # sugli stessi residui: la pagina lo dichiara invece di tacerlo.
        "coverage": _copertura(resid, pred, obs) if resid else None,
        "coverage_n": len(resid) if resid else 0,
        "q10": quantile(resid, 0.10) if resid else None,
        "q50": quantile(resid, 0.50) if resid else None,
        "q90": quantile(resid, 0.90) if resid else None,
        "reliability": reliability_table([occ_cal[i] for i in scored],
                                        [y_occ[i] for i in scored]),
        "calibrazione_fuori_campione": cal_out_of_sample,
        "n_scored": len(scored),
        "usable": bool(ok_occ and ok_int),
        "usable_occurrence": bool(ok_occ),
        "days_from": min(days), "days_to": max(days),
    }


def train(spot_name, sources):
    """Confronta tutti i candidati sullo STESSO metro e adotta il migliore.

    `sources` e' {"forecast": [...], "era5": [...]}. Il metro comune e' sempre
    il set costruito dalle previsioni: e' l'unico i cui ingressi somigliano a
    quelli che il modello ricevera' in esercizio. Un candidato addestrato su
    quattordici anni di rianalisi compete quindi ad armi pari con uno
    addestrato su cinque anni di previsioni, e vince solo se serve davvero.
    """
    if isinstance(sources, list):                 # compatibilita'
        sources = {"forecast": sources}
    eval_samples = sources.get("forecast") or []
    if len(eval_samples) < 30:
        return None, []

    results = []
    for source, samples in sources.items():
        if not samples:
            continue
        for tier in F.TIERS_BY_SOURCE.get(source, ("bias",)):
            r = _evaluate_candidate(eval_samples, samples, tier, source)
            if r:
                results.append(r)
    if not results:
        return None, []

    usable = [r for r in results if r["usable"]]
    if usable:
        chosen = min(usable, key=lambda r: (r["mae"] if r["mae"] is not None else 9e9))
    else:
        partial = [r for r in results if r["usable_occurrence"]]
        chosen = min(partial, key=lambda r: r["brier"]) if partial else None
    return chosen, results


def serialize(result):
    return {
        "tier": result["tier"],
        "source": result.get("source", "forecast"),
        "occurrence": result["occurrence"].to_dict() if result["occurrence"] else None,
        "intensity": result["intensity"].to_dict() if result["intensity"] else None,
        "calibration": result["calibration"],
        "q10": result["q10"], "q50": result["q50"], "q90": result["q90"],
        "base_rate": result["base_rate"],
    }


def metrics_of(result):
    out = {k: result.get(k) for k in
           ("tier", "source", "n", "n_eval", "n_established", "brier", "brier_base",
            "mae", "mae_base", "clim_median", "rmse", "usable", "usable_occurrence",
            # La copertura della banda si calcolava (model._copertura) e non si
            # salvava: la colonna "Copertura" della diagnostica stampava "—" da
            # sempre, sotto l'intestazione che promette numeri misurati fuori
            # campione. E' il numero che avrebbe smascherato il segno storto
            # della banda.
            "coverage", "coverage_n",
            "reliability",
            "days_from", "days_to", "base_rate", "lam_occ", "lam_int",
            "calibrazione_fuori_campione", "n_scored")}
    # Questo modello nasce dall'archivio ordinario delle previsioni, che
    # contiene le prime ore di ogni run: descrive lo stato quasi-attuale, non
    # una scadenza. Lo si dichiara qui una volta per tutte, invece di lasciare
    # che chi legge lo scambi per un modello a sette giorni.
    out["lead_band"] = "analisi"
    return out


# ==========================================================================
# Terzo stadio: l'orario
# ==========================================================================
# "Entra alle 13 o alle 15" cambia se devi partire da Verona, ed e' la
# domanda su cui un sistema verticale puo' staccare di piu': nessun modello
# globale e' addestrato a prevedere l'ora di innesco di UNA brezza in UN
# punto. L'errore si misura in minuti, non in nodi.

def train_timing(samples, tier="timing", folds=5):
    """Prevede l'ora del picco nella finestra, sui soli giorni in cui entra.

    Due riferimenti da battere, entrambi sensati:
      - la climatologia stagionale (l'ora media del picco in quel mese);
      - l'ora in cui l'ensemble grezzo mette il proprio massimo.
    Il secondo e' quello serio: se non battiamo l'orario che il modello indica
    gia' da solo, questo stadio non serve.
    """
    usable = [s for s in samples
              if s["established"] and s.get("peak_hour") is not None]
    if len(usable) < max(60, 4 * len(F.TIERS[tier])):
        return None

    days = [s["day"] for s in usable]
    X = [F.vector(s["features"], tier) for s in usable]
    y = [float(s["peak_hour"]) for s in usable]

    model, oof, lam, _f = _fit_stage(X, y, days, "ridge", folds=folds)
    if model is None:
        return None
    got = [i for i, v in enumerate(oof) if v is not None]
    if len(got) < 30:
        return None

    pred = [oof[i] for i in got]
    obs = [y[i] for i in got]
    met = regression_metrics(pred, obs)
    if not met:
        return None

    # Riferimento 1: media climatologica per mese. Calcolata su TUTTE le
    # giornate, comprese quelle su cui poi si misura: il commento diceva "fuori
    # dal fold" e non era vero. La direzione dell'errore e' conservativa - il
    # riferimento risulta un po' piu' forte del dovuto, quindi la porta e' piu'
    # severa, non piu' larga - ma un commento falso vale meno di niente.
    by_month = {}
    for s, hh in zip(usable, y):
        by_month.setdefault(int(s["day"][5:7]), []).append(hh)
    clim = {m: mean(v) for m, v in by_month.items()}
    overall = mean(y)
    clim_pred = [clim.get(int(usable[i]["day"][5:7]), overall) for i in got]
    mae_clim = mean([abs(a - b) for a, b in zip(clim_pred, obs)])

    # Riferimento 2: l'ora del massimo del vento grezzo previsto.
    raw = [usable[i]["features"].get("raw_peak_hour") for i in got]
    pairs = [(r, o) for r, o in zip(raw, obs) if r is not None]
    mae_raw = mean([abs(r - o) for r, o in pairs]) if len(pairs) > 20 else None

    bases = [x for x in (mae_clim, mae_raw) if x is not None]
    base_mae = min(bases) if bases else None

    # LA PORTA, con la stessa regola degli altri due stadi: il margine NON
    # BASTA, ci vuole anche il bootstrap. Qui si promuoveva col solo margine,
    # e PROMOTION_MARGIN e' 0,03: bastavano tre minuti su cento. Con 150
    # giornate il MAE fuori campione fluttua di due o tre minuti su una base di
    # ottantacinque, quindi un fold fortunato apriva la porta su un modello
    # senza segnale - e la parola "appreso" e' quella che autorizza la pagina a
    # scrivere i minuti.
    from .validate import bootstrap_gain
    err_m = [abs(p - o) for p, o in zip(pred, obs)]
    base_each = [abs(a - b) for a, b in zip(clim_pred, obs)]
    if mae_raw is not None and mae_raw <= mae_clim:
        coppie_raw = [(r, o) for r, o in zip(raw, obs) if r is not None]
        err_m = [abs(p - o) for p, (r, o) in zip(pred, zip(raw, obs))
                 if r is not None]
        base_each = [abs(r - o) for r, o in coppie_raw]
    _p, lo_gain, _h = bootstrap_gain(err_m, base_each) if err_m else (None, None, None)
    ok = (base_mae is not None
          and met["mae"] < base_mae * (1 - config.PROMOTION_MARGIN)
          and lo_gain is not None and lo_gain > 0)

    resid = met["resid"]
    return {
        "tier": tier, "n": len(usable),
        "mae_hours": met["mae"], "mae_minutes": met["mae"] * 60.0,
        "base_mae_hours": base_mae,
        "base_clim_hours": mae_clim, "base_raw_hours": mae_raw,
        "gain_lo": lo_gain,
        "bias_hours": met["bias"],
        "q10": quantile(resid, 0.10), "q90": quantile(resid, 0.90),
        "usable": bool(ok), "lam": lam,
        "payload": {"tier": tier, "model": model.to_dict(),
                    "q10": quantile(resid, 0.10), "q90": quantile(resid, 0.90),
                    "clim": {str(k): v for k, v in clim.items()},
                    "overall": overall},
    }


def predict_timing(feats, learned, day=None, fallback=None, lead=0):
    """Ora prevista del picco. Ritorna (ora, fonte) o (None, None).

    `lead` non c'era, e il modello appreso usciva marcato "appreso" a tutte le
    scadenze. Ma questo modello nasce dall'archivio ordinario delle previsioni,
    che contiene le prime ore di ogni run: e' misurato a D+0 e dice qualcosa
    solo li'. Oltre, la stessa parola valeva come una promessa che nessuna
    misura sostiene - "entra alle 14:20, appreso" a cinque giorni - e per la
    pagina "appreso" e' il timbro su cui si scrivono i minuti. Fuori da D+0 si
    scende alla climatologia, che almeno e' onesta sul suo nome.
    """
    payload = (learned or {}).get("payload") or {}
    metrics = (learned or {}).get("metrics") or {}
    if payload.get("model") and metrics.get("usable") and (lead or 0) <= 0:
        reg = RidgeModel.from_dict(payload["model"])
        h = reg.predict(F.vector(feats, payload["tier"]))
        return clamp(h, 0.0, 23.9), "appreso"
    if payload.get("clim") and day:
        h = payload["clim"].get(str(int(day[5:7])))
        if h is not None:
            return clamp(h, 0.0, 23.9), "climatologia"
    return (fallback, "ensemble") if fallback is not None else (None, None)


# ==========================================================================
# Prior fisico (quando non c'e' ancora un modello validato)
# ==========================================================================

def physical_prior(spot_name, feats):
    """Stima di partenza, dichiaratamente non calibrata.

    Non pretende di essere accurata: serve a non lasciare la schermata vuota
    il primo giorno e a dare un riferimento contro cui il modello appreso deve
    dimostrare di essere migliore. I coefficienti sono scelti a mano dalla
    fenomenologia dei due regimi, non stimati dai dati.
    """
    spot = config.SPOTS[spot_name]
    regime = spot["regime"]

    along = feats.get("along925") or 0.0
    cross = feats.get("cross925") or 0.0
    rad = feats.get("rad_pre") or 0.0
    cloud = feats.get("cloud_win") or 0.5
    precip = feats.get("precip") or 0.0
    pgrad = feats.get("pgrad") or 0.0
    tgrad = feats.get("tgrad") or 0.0
    stab = feats.get("stab850")
    w10 = feats.get("w10_win") or 0.0

    if regime == "ORA":
        drive = (0.42 * clamp(tgrad / 4.0, -1.5, 2.0)
                 + 0.30 * clamp(rad, 0.0, 1.6)
                 + 0.26 * clamp(-pgrad / 1.2, -1.5, 1.5)
                 + 0.22 * clamp(along / 8.0, -2.0, 1.2)
                 - 0.18 * clamp(cross / 10.0, 0.0, 2.0)
                 - 0.55 * clamp(cloud - 0.45, 0.0, 0.6)
                 - 0.80 * clamp(precip / 2.0, 0.0, 1.5))
        if stab is not None:
            drive += 0.12 * clamp((-stab - 14.0) / 4.0, -1.0, 1.0)
        prob = sigmoid((drive - 0.35) * 2.6)
        speed = w10 + 3.2 * clamp(drive, 0.0, 1.6) + 0.20 * max(0.0, along)
    else:
        drive = (0.46 * clamp(pgrad / 1.2, -1.5, 2.0)
                 + 0.30 * clamp(along / 8.0, -2.0, 1.5)
                 + 0.24 * clamp(1.0 - (feats.get("cloud_cool") or 0.5), 0.0, 1.0)
                 - 0.16 * clamp(cross / 10.0, 0.0, 2.0)
                 - 0.70 * clamp(precip / 2.0, 0.0, 1.5))
        prob = sigmoid((drive - 0.30) * 2.8)
        speed = w10 + 3.6 * clamp(drive, 0.0, 1.6) + 0.25 * max(0.0, along)

    return clamp(prob, 0.02, 0.96), max(0.0, speed)


# ==========================================================================
# Previsione
# ==========================================================================

def direction_penalty(direction, axis, sector):
    """Quanto pesa, sulla probabilita' del regime, una direzione fuori settore.

    Un regime E' una direzione. Se i modelli danno il vento da sud al mattino,
    il Peler non sta entrando, per quanto il resto della configurazione possa
    somigliare a una giornata da Peler. Senza questo freno la scheda puo'
    dichiarare "97% che entri" e due righe sotto "niente Peler": due affermazioni
    che non possono essere vere insieme.
    """
    if direction is None:
        return 1.0
    from .util import angle_diff as _ad
    excess = _ad(direction, axis) - sector
    if excess <= 0:
        return 1.0
    return clamp(math.exp(-((excess / 35.0) ** 2)), 0.03, 1.0)


def predict(spot_name, feats, learned, lead_days, spread_kn=None, direction=None):
    """Ritorna probabilita', intensita' e banda, dichiarando sempre la fonte.

    `learned` deve essere il modello DELLA FASCIA a cui appartiene `lead_days`
    (lo risolve il chiamante, vedi engine.learned_for_lead). Se per quella
    fascia non esiste un modello validato, la previsione esce marcata
    `validata: False` e con una banda di origine dichiarata.
    """
    lead = int(clamp(lead_days, 0, 7))
    band = config.band_for_lead(lead)
    spread = spread_kn if spread_kn is not None else 3.0

    prior_p, prior_v = physical_prior(spot_name, feats)

    payload = (learned or {}).get("payload") or {}
    metrics = (learned or {}).get("metrics") or {}
    tier = payload.get("tier")
    prob, speed = prior_p, prior_v
    lo = hi = None
    band_src = None
    src_prob = src_int = "prior"

    # I due stadi si promuovono SEPARATAMENTE, e questa e' una correzione a
    # come funzionava prima. La probabilita' e l'intensita' rispondono a due
    # domande diverse ("entra?" e "quanto?") e superano le proprie porte in
    # momenti diversi: capita, e nei dati veri capita spesso, che il "quanto"
    # batta il vento grezzo del 40% mentre il "se" non si distingua ancora
    # dalla climatologia. Legandoli si buttava via lo stadio buono per colpa di
    # quello incerto; separandoli, ogni numero pubblicato porta la propria
    # provenienza e chi legge sa quale dei due fidarsi.
    # A quale scadenza appartiene questo modello, e quindi cosa gli si puo'
    # chiedere. Tre casi, e la differenza fra il secondo e il terzo e' il punto:
    #
    #   dichiara la fascia giusta  -> si usa, la banda viene dai suoi residui,
    #                                 e la previsione puo' dirsi validata
    #   modello "analisi"          -> e' quello addestrato sull'archivio
    #     (o senza fascia)            ordinario, che contiene le prime ore di
    #                                 ogni run: descrive la scadenza zero. Lo si
    #                                 usa comunque a tutte le scadenze, perche'
    #                                 e' la stima migliore disponibile, ma oltre
    #                                 il giorno corrente non puo' ne' dirsi
    #                                 validato ne' prestare i propri residui,
    #                                 che sono stati misurati a D+0.
    #   dichiara un'altra fascia   -> non lo si usa affatto
    declared = metrics.get("lead_band")
    if declared and declared == band:
        usa, banda_misurata, valido_qui = True, True, True
    elif declared in (None, "analisi"):
        usa = True
        banda_misurata = valido_qui = (lead == 0)
    else:
        usa = banda_misurata = valido_qui = False

    if tier and usa and payload.get("occurrence") and metrics.get("usable_occurrence"):
        x = F.vector(feats, tier)
        occ = LogisticModel.from_dict(payload["occurrence"])
        raw = occ.predict_proba(x)
        prob = apply_calibration(raw, payload.get("calibration") or [])
        src_prob = "appreso"
    elif metrics.get("base_rate") is not None:
        # Niente modello promosso per il "se": si dichiara la frequenza
        # climatologica osservata, che almeno e' una misura. Il prior fisico
        # non e' calibrato e in questa posizione mentirebbe meglio.
        prob = clamp(metrics["base_rate"], 0.02, 0.97)
        src_prob = "climatologia"

    # Stessa logica per il "quanto": se il modello appreso non batte la
    # mediana climatologica, quella mediana E' la previsione migliore che
    # abbiamo, ed e' una misura. A Campione l'Ora e' cosi' regolare che
    # "dire sempre 14 kn" sbaglia di 1,40 kn e il modello di 1,36-1,41: il
    # cancello lo ferma, giustamente, e prima al suo posto entrava il prior
    # fisico, che non e' calibrato e sbaglia di piu' di entrambi.
    if metrics.get("clim_median") is not None and not metrics.get("usable"):
        speed = max(float(metrics["clim_median"]), config.SPOTS[spot_name]["min_kn"])
        src_int = "climatologia"

    if tier and usa and payload.get("intensity") and metrics.get("usable"):
        x = F.vector(feats, tier)
        reg = RidgeModel.from_dict(payload["intensity"])
        speed = max(0.0, math.expm1(reg.predict(x)))
        # Lo stadio B stima E[picco | il regime e' entrato], e "entrato"
        # e' definito come picco >= soglia. Una stima condizionata sotto la
        # soglia e' una contraddizione: e' la regressione che estrapola
        # fuori dal dominio su cui e' stata addestrata.
        speed = max(speed, config.SPOTS[spot_name]["min_kn"])
        src_int = "appreso"
        q10 = payload.get("q10") if banda_misurata else None
        q90 = payload.get("q90") if banda_misurata else None
        if q10 is not None and q90 is not None:
            # Quantili dei residui misurati a QUESTA fascia di scadenza.
            # Nessun allargamento aggiuntivo: se la fascia e' lunga, i
            # residui sono gia' piu' larghi, ed e' il dato a dirlo.
            lo, hi = banda_da_residui(speed, q10, q90)
            band_src = "residui misurati"

    source = ("appreso" if src_prob == src_int == "appreso"
              else "prior" if src_prob == src_int == "prior" else "misto")

    # Freno sulla direzione: vedi direction_penalty.
    #
    # E' una moltiplicazione fatta A MANO DOPO la calibrazione, quindi la
    # probabilita' che esce da qui non e' piu' quella che Brier e errore di
    # calibrazione hanno misurato. Finche' il freno non morde (direzione dentro
    # il settore) dpen vale esattamente 1 e non cambia niente. Quando morde
    # - 0,72 a novanta gradi fuori asse, 0,48 a cento - il numero pubblicato
    # non e' piu' verificato, e la pagina non puo' dire "viene dalla
    # probabilita' del regime, che e' addestrata e verificata, meno l'errore di
    # calibrazione misurato": sarebbe vero della probabilita' di prima, non di
    # questa. Percio' il freno si DICHIARA, e chi scrive l'affidabilita' lo sa.
    spot = config.SPOTS[spot_name]
    dpen = direction_penalty(direction, spot["axis"], config.REGIME_SECTOR_DEG)
    if dpen < 1.0 and src_prob == "appreso":
        src_prob = "appreso-frenato"
        source = "misto"
    prob = clamp(prob * dpen, 0.01, 0.97)

    if lo is None or hi is None:
        # Nessun residuo misurato a questa scadenza. La banda viene allora
        # dalla dispersione fra i modelli, che almeno e' una misura del
        # disaccordo, piu' un margine per l'errore comune a tutti (il lago non
        # e' risolto da nessuno di loro: se sbagliano insieme, la dispersione
        # e' piccola e la banda va comunque tenuta larga).
        half = 4.2 + 1.6 * spread
        lo = max(0.0, speed - half)
        hi = speed + half
        band_src = "dispersione d'ensemble"

    # Validata significa: promosso PROPRIO a questa fascia di scadenza. Un
    # modello bravissimo a D+0 non e' validato a D+5, e dirlo e' l'unico modo
    # di non prendersi un credito che non si e' guadagnato.
    return {
        "prob": prob,
        "dir_penalty": dpen,
        "speed": speed,
        "lo": lo,
        "hi": hi,
        "source": source,
        "source_prob": src_prob,
        "source_int": src_int,
        "band_source": band_src,
        "tier": tier,
        "lead": lead,
        "lead_band": band,
        "validata": bool(valido_qui and metrics.get("usable")
                         and metrics.get("usable_occurrence")),
        "validata_prob": bool(valido_qui and metrics.get("usable_occurrence")),
        "validata_int": bool(valido_qui and metrics.get("usable")),
        "mae": metrics.get("mae"),
        "brier": metrics.get("brier"),
        "brier_base": metrics.get("brier_base"),
        "n": metrics.get("n"),
    }


def verify_intervals(samples, learned):
    """Copertura osservata della banda dichiarata, su dati out-of-fold."""
    payload = (learned or {}).get("payload") or {}
    if not payload.get("intensity"):
        return None, 0
    q10, q90 = payload.get("q10"), payload.get("q90")
    if q10 is None or q90 is None:
        return None, 0
    reg = RidgeModel.from_dict(payload["intensity"])
    tier = payload["tier"]
    los, his, obs = [], [], []
    for s in samples:
        if not s["established"]:
            continue
        v = math.expm1(reg.predict(F.vector(s["features"], tier)))
        lo_v, hi_v = banda_da_residui(v, q10, q90)
        los.append(lo_v)
        his.append(hi_v)
        obs.append(s["peak"])
    return interval_coverage(los, his, obs)
