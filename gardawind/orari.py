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
                   mean, median, merge_by_instant, parse_dt_any, quantile,
                   sampling_cadence, sustained_onset, time_above, to_local)

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


# ==========================================================================
# 2b. Validazione fuori campione dell'orario
# ==========================================================================
#
# Qui si misura se un modo di prevedere l'ora di ingresso vale piu' del
# riferimento banale, e si misura FUORI CAMPIONE, in avanti nel tempo.
#
# Tre regole che questo blocco fa rispettare da solo, senza contare sulla
# buona volonta' di chi lo chiama:
#
#   1. un previsore riceve SOLO le giornate precedenti, piu' l'identita' della
#      giornata da prevedere (data, mese, e le feature note all'emissione) ma
#      MAI la sua osservazione. Non un elenco da cui potrebbe pescare il
#      futuro: proprio soltanto quelle.
#   2. qualunque parametro stimato - compresa la correzione del bias
#      stagionale - si stima sul training e si verifica sul validation. Una
#      correzione calcolata sullo stesso campione su cui la si misura non e'
#      una correzione, e' una sottrazione della media da se stessa.
#   3. il riferimento e' la climatologia MENSILE osservata, mai la media
#      annuale. Battere "l'ora media dell'anno" e' vincere contro chi non
#      gioca.
#
# Le tre porte di promozione, tutte necessarie:
#
#   A. semiampiezza: la meta'-larghezza della finestra che contiene la quota
#      richiesta degli ingressi reali (68% per difetto) deve stare entro 45
#      minuti. E' la promessa che si fa in home, e va misurata, non sperata.
#   B. guadagno: l'errore assoluto medio deve battere la climatologia
#      mensile, e l'intervallo bootstrap del miglioramento non deve
#      attraversare lo zero.
#   C. bias stagionale: nessun mese e nessuna stagione con un errore medio
#      sistematico. Un modello che a settembre sbaglia sempre di mezz'ora in
#      avanti non e' promosso per aver fatto media con maggio.
#
# Sulla porta C serve una cautela, altrimenti si chiude sempre. Con undici
# gruppi (dodici mesi e quattro stagioni) e un errore che ha una sua
# dispersione, il gruppo PIU' STORTO dei undici e' storto di venti minuti
# anche quando il previsore e' perfettamente centrato: e' il massimo di undici
# rumori, non un bias. Quindi un gruppo conta come sistematico solo se
# succedono due cose insieme: lo scarto supera il limite, E il suo intervallo
# bootstrap non contiene lo zero, con il livello allargato per il numero di
# gruppi guardati. Una porta che si chiude sempre non e' prudente: e' rotta, e
# non distingue piu' il modello buono da quello cattivo.

STAGIONI = {12: "inverno", 1: "inverno", 2: "inverno",
            3: "primavera", 4: "primavera", 5: "primavera",
            6: "estate", 7: "estate", 8: "estate",
            9: "autunno", 10: "autunno", 11: "autunno"}

# La quota di ingressi che la finestra dichiarata deve contenere. 68% non e'
# un numero sacro: e' la fascia che lui ha accettato consapevolmente di non
# coprire sempre, in cambio di una finestra abbastanza stretta da servire.
QUOTA_FINESTRA = 0.68

# La semiampiezza massima accettabile, in minuti. Oltre questa, la finestra
# non e' piu' una decisione: e' un pomeriggio.
SEMIAMPIEZZA_MAX = 45.0

# Oltre questo, il bias di un mese o di una stagione e' sistematico.
BIAS_STAGIONALE_MAX = 20.0

# Sotto questo numero di giornate non si dichiara un bias per mese: la media
# di quattro errori non e' una tendenza.
MIN_GG_BIAS = 8


def _campo_ingresso(bersaglio, lettura):
    return "%s_onset%s" % (EN[bersaglio], "" if lettura == "regime" else "_wind")


def osservazioni(records, bersaglio="regime", lettura="regime"):
    """Le giornate con un ingresso misurato: [(data, mese, minuti)], in ordine.

    records: le strutture di giudica_giornata(), in qualunque ordine. Entrano
    solo quelle stimabili e con un ingresso: una giornata senza regime NON
    diventa un orario inventato, contribuisce solo al tasso di base.
    """
    campo = _campo_ingresso(bersaglio, lettura)
    out = []
    for r in records:
        if not r.get("estimable") or r.get(campo) is None or not r.get("date"):
            continue
        out.append((r["date"], int(r["date"][5:7]), float(r[campo])))
    out.sort(key=lambda x: x[0])
    return out


def _per_mese(oss):
    d = {}
    for _giorno, mese, minuti in oss:
        d.setdefault(mese, []).append(minuti)
    return d


def previsore_climatologico(min_gg=MIN_GG_MESE, mensile=True):
    """Il riferimento banale, come funzione: (training, ctx) -> (minuti, prov).

    La firma dice da sola cosa un previsore puo' vedere:

      training  le osservazioni delle giornate PRECEDENTI, e nient'altro.
      ctx       l'identita' della giornata da prevedere - data, mese, e le
                feature note all'ora di emissione - MA NON la sua osservazione.

    Un modello vero ha diritto di sapere che oggi il gradiente e' forte: e'
    un dato disponibile prima, non dopo. Non ha diritto di sapere a che ora e'
    entrata l'Ora. Il banco non gli passa il secondo, e il test di leakage
    serve a scoprire chi se lo va a prendere da fuori.
    """
    def previsore(training, ctx):
        if not mensile:
            xs = [m for _g, _mm, m in training]
            return (median(xs), "annuale") if xs else (None, "insufficiente")
        return previsione_climatologica(_per_mese(training), ctx["mese"],
                                       min_gg=min_gg)
    previsore.nome = "climatologia mensile" if mensile else "mediana annuale"
    return previsore


def previsore_corretto(base, min_gg=MIN_GG_BIAS, nome=None):
    """base piu' la correzione del bias del mese, STIMATA SUL TRAINING.

    La correzione si calcola facendo predire al previsore le giornate di
    addestramento - e per ognuna usando solo quelle che la precedono, esatto
    come in produzione - e prendendo la mediana degli errori di quel mese.
    Costa tempo di calcolo e lo vale: una correzione stimata sul validation
    migliorerebbe qualunque cosa, comprese le cose false.
    """
    def previsore(training, ctx):
        grezzo, prov = base(training, ctx)
        if grezzo is None:
            return None, prov
        mese = ctx["mese"]
        errori = []
        for i, (data, mm, obs) in enumerate(training):
            if mm != mese:
                continue
            p, _pv = base(training[:i], {"date": data, "mese": mm})
            if p is not None:
                errori.append(p - obs)
        if len(errori) < min_gg:
            return grezzo, prov + "+bias:insufficiente"
        return grezzo - median(errori), prov + "+bias"
    previsore.nome = nome or ("%s, bias del mese corretto sul training"
                             % getattr(base, "nome", "base"))
    return previsore


def _ic_mediana(errs, livello=0.95, n_boot=400, seed=11):
    """Intervallo bootstrap della mediana degli errori. Dice se e' distinguibile
    da zero, che e' l'unica cosa che rende un bias "sistematico" invece che
    "il piu' storto di undici gruppi"."""
    import random as _random
    if len(errs) < 5:
        return None, None
    rng = _random.Random(seed)
    k = len(errs)
    campioni = []
    for _ in range(n_boot):
        campioni.append(median([errs[rng.randrange(k)] for _ in range(k)]))
    coda = (1.0 - livello) / 2.0
    return quantile(campioni, coda), quantile(campioni, 1.0 - coda)


def _bias_per_gruppo(coppie, chiave, min_gg=MIN_GG_BIAS, livello=0.95):
    """{gruppo: {"n", "bias", "mae", "ic", "significativo"}}.

    "significativo" non vuol dire "grande": vuol dire che l'intervallo
    bootstrap della mediana degli errori non contiene lo zero. Il livello
    arriva da fuori, gia' allargato per il numero di gruppi che si guardano.
    """
    gruppi = {}
    for mese, err in coppie:
        gruppi.setdefault(chiave(mese), []).append(err)
    out = {}
    for g, errs in gruppi.items():
        if len(errs) < min_gg:
            out[g] = {"n": len(errs), "bias": None, "mae": None,
                      "ic": (None, None), "significativo": None}
            continue
        lo, hi = _ic_mediana(errs, livello=livello)
        out[g] = {"n": len(errs), "bias": median(errs),
                  "mae": median([abs(e) for e in errs]), "ic": (lo, hi),
                  "significativo": (lo is not None and (lo > 0.0 or hi < 0.0))}
    return out


def valida_ingressi(records, bersaglio="regime", lettura="regime",
                    previsori=None, k=6, quota=QUOTA_FINESTRA,
                    semiampiezza_max=SEMIAMPIEZZA_MAX,
                    bias_max=BIAS_STAGIONALE_MAX, min_gg=MIN_GG_MESE):
    """Misura uno o piu' previsori dell'ora di ingresso, fuori campione.

    previsori: {nome: fn(training, mese) -> (minuti, provenienza)}. Il primo
    nome dell'elenco "climatologia" e' il riferimento; se non lo si passa, lo
    si costruisce qui, mensile, come deve essere.

    Ritorna una struttura: nessuna stampa, nessun italiano nei verdetti
    (`esito` e' "affidabile" o "incerto", e chi impagina decide le parole).
    """
    from .validate import bootstrap_gain

    oss = osservazioni(records, bersaglio, lettura)
    stimabili = sum(1 for r in records if r.get("estimable"))
    base_nome = "climatologia"
    if previsori is None:
        previsori = {}
    previsori = dict(previsori)
    previsori.setdefault(base_nome, previsore_climatologico(min_gg=min_gg))

    vuoto = {"bersaglio": bersaglio, "lettura": lettura,
             "n_records": len(records), "n_stimabili": stimabili,
             "n_ingressi": len(oss), "quota_stimabile":
                 (len(oss) / float(len(records)) if records else None),
             "n_fold": 0, "fold": [], "previsori": {}, "esito": "incerto",
             "porte": None, "motivo": "troppe poche giornate con un ingresso"}
    if len(oss) < 20:
        return vuoto

    # Fold in avanti: il primo blocco serve solo ad addestrare e non viene
    # mai predetto. Si paga in campioni, non in onesta'.
    n = len(oss)
    inizio = max(int(n * 0.40), 8)
    if n - inizio < k:
        k = max(1, n - inizio)
    passo = max(1, (n - inizio) // max(1, k))
    tagli, pos = [], inizio
    while pos < n and len(tagli) < k:
        stop = min(n, pos + passo)
        tagli.append((pos, stop))
        pos = stop
    if not tagli:
        return vuoto

    risultati = {}
    for nome, fn in previsori.items():
        per_giorno, errori, coppie = [], [], []
        prov_conteggi = {}
        for i_fold, (a, b) in enumerate(tagli):
            training = oss[:a]
            for giorno, mese, obs in oss[a:b]:
                # Il contesto contiene l'identita' della giornata, non il suo
                # esito: e' esattamente cio' che si sa all'ora di emissione.
                pred, prov = fn(training, {"date": giorno, "mese": mese,
                                           "stagione": STAGIONI[mese]})
                prov_conteggi[prov] = prov_conteggi.get(prov, 0) + 1
                riga = {"date": giorno, "mese": mese, "fold": i_fold,
                        "osservato": obs, "previsto": pred,
                        "provenienza": prov,
                        "errore": (pred - obs) if pred is not None else None}
                per_giorno.append(riga)
                if pred is not None:
                    errori.append(pred - obs)
                    coppie.append((mese, pred - obs))
        assoluti = [abs(e) for e in errori]
        risultati[nome] = {
            "nome": getattr(fn, "nome", nome),
            "n": len(errori),
            "n_senza_previsione": len(per_giorno) - len(errori),
            "mae": mean(assoluti) if assoluti else None,
            "mae_mediano": median(assoluti) if assoluti else None,
            "bias": mean(errori) if errori else None,
            "bias_mediano": median(errori) if errori else None,
            "semiampiezza": quantile(sorted(assoluti), quota) if assoluti else None,
            "copertura_30": (sum(1 for a in assoluti if a <= 30) / float(len(assoluti))
                             if assoluti else None),
            "copertura_45": (sum(1 for a in assoluti if a <= 45) / float(len(assoluti))
                             if assoluti else None),
            "copertura_60": (sum(1 for a in assoluti if a <= 60) / float(len(assoluti))
                             if assoluti else None),
            # 16 gruppi possibili (12 mesi + 4 stagioni): il livello si
            # allarga di conseguenza, altrimenti il piu' storto dei sedici
            # sembra sempre un bias.
            "bias_per_mese": _bias_per_gruppo(coppie, lambda m: m,
                                              livello=1.0 - 0.05 / 16.0),
            "bias_per_stagione": _bias_per_gruppo(coppie, lambda m: STAGIONI[m],
                                                  livello=1.0 - 0.05 / 16.0),
            "provenienza": prov_conteggi,
            "per_giorno": per_giorno,
        }

    # Confronto col riferimento, appaiato giorno per giorno: il bootstrap ha
    # senso solo se i due errori vengono dalla stessa giornata.
    rif = risultati[base_nome]
    err_rif = {r["date"]: abs(r["errore"]) for r in rif["per_giorno"]
               if r["errore"] is not None}
    for nome, r in risultati.items():
        if nome == base_nome:
            r["guadagno"] = (None, None, None)
            continue
        mio, suo = [], []
        for riga in r["per_giorno"]:
            if riga["errore"] is None or riga["date"] not in err_rif:
                continue
            mio.append(abs(riga["errore"]))
            suo.append(err_rif[riga["date"]])
        r["guadagno"] = bootstrap_gain(mio, suo)
        r["n_appaiati"] = len(mio)

    # Le tre porte, applicate al previsore migliore che non sia il riferimento
    # (se c'e' solo il riferimento, si misurano su di lui: e' la climatologia
    # a dover dire se almeno LEI sta dentro i 45 minuti).
    candidati = [nm for nm in risultati if nm != base_nome]
    scelto = None
    if candidati:
        con_mae = [(risultati[nm]["mae"], nm) for nm in candidati
                   if risultati[nm]["mae"] is not None]
        scelto = min(con_mae)[1] if con_mae else None
    valutato = scelto or base_nome
    r = risultati[valutato]

    porte = {}
    porte["semiampiezza"] = {
        "valore": r["semiampiezza"], "limite": semiampiezza_max,
        "passa": (r["semiampiezza"] is not None
                  and r["semiampiezza"] <= semiampiezza_max)}
    if valutato == base_nome:
        porte["guadagno"] = {"valore": None, "passa": None,
                             "nota": "nessun modello da confrontare: "
                                     "questo E' il riferimento"}
    else:
        g, lo, hi = r["guadagno"]
        porte["guadagno"] = {"valore": g, "ic": (lo, hi),
                             "passa": (lo is not None and lo > 0.0)}
    # Due numeri diversi, e vanno detti entrambi: il gruppo piu' storto in
    # assoluto (utile a leggere) e il gruppo piu' storto fra quelli
    # SISTEMATICI, che e' l'unico che chiude la porta.
    peggiore = peggiore_dove = None
    sistematico = sistematico_dove = None
    for dove, gruppi in (("mese", r["bias_per_mese"]),
                         ("stagione", r["bias_per_stagione"])):
        for g, v in gruppi.items():
            if v["bias"] is None:
                continue
            if peggiore is None or abs(v["bias"]) > abs(peggiore):
                peggiore, peggiore_dove = v["bias"], "%s %s" % (dove, g)
            if (v.get("significativo") and abs(v["bias"]) > bias_max
                    and (sistematico is None or abs(v["bias"]) > abs(sistematico))):
                sistematico, sistematico_dove = v["bias"], "%s %s" % (dove, g)
    porte["bias_stagionale"] = {
        "valore": peggiore, "dove": peggiore_dove,
        "sistematico": sistematico, "sistematico_dove": sistematico_dove,
        "limite": bias_max, "passa": (sistematico is None)}

    passate = [p["passa"] for p in porte.values() if p["passa"] is not None]
    esito = "affidabile" if passate and all(passate) else "incerto"
    motivo = None
    if esito == "incerto":
        mancate = [k2 for k2, p in porte.items() if p["passa"] is False]
        motivo = "porte non superate: " + ", ".join(sorted(mancate))

    return {"bersaglio": bersaglio, "lettura": lettura,
            "n_records": len(records), "n_stimabili": stimabili,
            "n_ingressi": len(oss),
            "quota_stimabile": len(oss) / float(len(records)) if records else None,
            "n_fold": len(tagli), "fold": tagli,
            "riferimento": base_nome, "valutato": valutato,
            "previsori": risultati, "porte": porte,
            "esito": esito, "motivo": motivo}
