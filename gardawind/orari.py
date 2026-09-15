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
from .util import (FINESTRA_RICORRENTE_MIN, alba_tramonto, angle_diff,
                   covered_minutes, gust_level, linear_modes, local_day,
                   mean, median, merge_by_instant, offset_locale_ore,
                   parse_dt_any, quantile, sampling_cadence, sustained_onset,
                   time_above, to_local, window_estimable)

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
#   left_censored             il regime era GIA' presente al primo campione
#                             della finestra: sappiamo che era entrato, non
#                             quando. L'orario e' un limite superiore (non
#                             dopo quell'istante), e la giornata NON entra
#                             nell'addestramento del timing come se fosse una
#                             misura precisa
#   no_data                   nessun campione con vento
#   insufficient_coverage     troppo poco tempo coperto per dire qualcosa
#   gap_too_large             il regime risulta entrato, ma il passaggio cade
#                             dentro un buco: l'orario e' un limite inferiore,
#                             non una certezza
#   direction_outside_sector  il vento bastava, la direzione era fuori settore
#   threshold_not_sustained   la soglia e' stata superata, ma non abbastanza
#                             a lungo perche' sia un ingresso
#   no_regime                 la soglia non e' mai stata superata
REASONS = ("ok", "left_censored", "no_data", "insufficient_coverage",
           "gap_too_large", "direction_outside_sector",
           "threshold_not_sustained", "no_regime")

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
        "peak_wind": None, "peak_regime": None,
        "first_sample_min": None,
        "regime_onset": None, "planing_onset": None,
        "regime_onset_wind": None, "planing_onset_wind": None,
        "regime_onset_censored": False, "planing_onset_censored": False,
        "regime_onset_wind_censored": False,
        "planing_onset_wind_censored": False,
        "regime_duration_min": None, "planing_duration_min": None,
        "regime_duration_wind_min": None, "planing_duration_wind_min": None,
    }
    # Si indicizza invece di scompattare: le righe possono portare un quarto
    # campo (la raffica) che qui non si guarda, e un giorno potrebbero portarne
    # un quinto. Scompattare tre nomi renderebbe questa funzione fragile a
    # un'aggiunta che non la riguarda.
    dati = sorted([(float(r[0]), r[1], r[2]) for r in righe if r[1] is not None],
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
    # Il picco della giornata nelle due letture. Non serve a giudicare
    # l'ingresso: serve alla descrittiva, e sta qui perche' "quanto ha tirato
    # oggi" e "quanto ha tirato oggi DAL SETTORE GIUSTO" vanno definiti una
    # volta sola, nello stesso posto dove e' definito il settore.
    base["peak_wind"] = max(v for _m, v in serie["vento"])
    base["peak_regime"] = max(v for _m, v in serie["regime"])
    # CENSURA A SINISTRA. sustained_onset restituisce il CENTRO dell'intervallo
    # coperto dal primo campione sopra soglia: se quel campione e' il primo
    # della finestra, il centro cade PRIMA dell'inizio dell'osservazione - ed e'
    # da li' che nascevano i 10:55 di Torbole e i 03:55 del Peler, orari che
    # nessuno ha misurato. Semanticamente non sappiamo che il vento sia entrato
    # alle 03:55: sappiamo che alle 04:00 era GIA' sopra soglia, e che quindi e'
    # entrato prima di quando abbiamo cominciato a guardare.
    #
    # Quindi: l'orario diventa il bordo della finestra (un limite, non una
    # misura) e la giornata viene marcata. A valle, il livello statistico la
    # tiene fuori dalle mediane come se fosse una misura precisa, ma NON la
    # butta via: sapere che in gennaio il Peler e' gia' dentro alle quattro e'
    # un'informazione, e buttarla renderebbe la mediana di gennaio
    # artificialmente tarda.
    #
    # Nota: nelle giornate censurate anche la DURATA e' troncata a sinistra,
    # per la stessa ragione.
    primo_minuto = minuti[0]
    # A che ora comincia il dato di questa giornata. Per una giornata censurata
    # e' il numero che distingue due cose molto diverse: "alle 04:00 il vento
    # era gia' dentro" (la finestra di osservazione comincia troppo tardi) e
    # "il primo campione e' alle 04:50" (di quella giornata non abbiamo il
    # dato prima). Senza questo campo le due sembrano la stessa cosa, e la
    # prima suggerisce di allargare la finestra mentre la seconda dice che
    # allargarla non servirebbe a niente.
    base["first_sample_min"] = primo_minuto
    for bers, soglia in (("regime", soglia_regime), ("planata", soglia_planata)):
        for lettura in LETTURE:
            s = serie[lettura]
            ing = sustained_onset(s, float(soglia), persist_min=persist_min,
                                  cadence_min=cad)
            dur = time_above(s, float(soglia), cad)
            suffisso = "" if lettura == "regime" else "_wind"
            censurato = ing is not None and ing < primo_minuto
            if censurato:
                ing = primo_minuto
            base["%s_onset%s" % (EN[bers], suffisso)] = ing
            base["%s_onset%s_censored" % (EN[bers], suffisso)] = censurato
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
        if base["regime_onset_censored"]:
            # Prima di gap_too_large: se il regime c'e' gia' al primo
            # campione non esiste un buco precedente di cui parlare.
            base["reason"] = "left_censored"
        else:
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

    {giorno: [(minuti_locali, vento, direzione, raffica)]}, con i campioni
    dello stesso istante gia' uniti fra le fonti.

    La raffica viaggia con il campione anche se giudica_giornata non la guarda:
    serve alla planabilita', che si decide su media E raffica ricorrente. Chi
    legge solo i primi tre campi continua a funzionare - e infatti
    giudica_giornata indicizza invece di scompattare, proprio per questo.
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
            out.setdefault(giorno, []).append(
                (minuti, u["wind"], u["dir"], u.get("gust")))
    for giorno in out:
        out[giorno].sort(key=lambda r: r[0])
    return out


def _disp(xs):
    """Dispersione robusta: mediana degli scarti dalla mediana, in minuti."""
    if len(xs) < 3:
        return None
    m = median(xs)
    return median([abs(x - m) for x in xs])


def _riassunto(xs, durs=None, min_gg=MIN_GG_MESE, censurati=None):
    """Il riassunto di un mese, con la censura a sinistra trattata per quello che e'.

    xs sono gli ingressi MISURATI; censurati sono i limiti delle giornate in
    cui il regime era gia' presente al primo campione ("entrato non dopo
    questo istante"). Buttarli non e' neutro: sono sistematicamente i piu'
    PRECOCI, e togliendoli la mediana del mese slitta in avanti. A gennaio, sul
    Peler, sono quasi tutte le giornate.

    Quindi si usa quello che si sa. Una osservazione censurata e' un valore
    ignoto ma NON PIU' GRANDE del suo limite, e per una MEDIANA questo basta:
    le censurate stanno tutte in fondo all'ordinamento, e finche' sono meno
    della meta' la mediana cade su un valore osservato ed e' esatta. Quando
    sono la meta' o piu', la mediana non e' un numero: e' "non dopo il bordo
    della finestra", e viene dichiarata come limite invece di essere inventata.

    La dispersione, con le censurate sostituite dal loro limite, e' un LIMITE
    INFERIORE: il valore vero e' piu' lontano dalla mediana, non piu' vicino.
    """
    censurati = list(censurati or [])
    n_tot = len(xs) + len(censurati)
    vuoto = {"n": n_tot, "n_misurati": len(xs), "n_censurati": len(censurati),
             "quota_censurata": (len(censurati) / float(n_tot)) if n_tot else None,
             "mediana": None, "mediana_limite": None, "disp": None,
             "disp_limite_inferiore": False, "durata": None,
             "modi": None, "dip": None, "modi_motivo": None}
    if n_tot < min_gg:
        return vuoto

    # Le censurate valgono "un filo prima del loro limite": e' l'unica cosa
    # che si sa, ed e' abbastanza per ordinare.
    finti = [c - 1e-6 for c in censurati]
    tutti = sorted(xs + finti)
    if len(censurati) * 2 >= n_tot:
        # La mediana cade dentro il gruppo censurato: non e' un orario, e' un
        # limite. Si dichiara il bordo piu' tardo fra quelli censurati.
        vuoto["mediana_limite"] = max(censurati)
        vuoto["durata"] = median(durs) if durs else None
        return vuoto

    m = median(tutti)
    disp = _disp(tutti)
    # La forma (i due picchi) si cerca solo sulle giornate MISURATE: una
    # colonna di valori tutti uguali al bordo della finestra produrrebbe un
    # picco che e' un artefatto della finestra, non del vento.
    modi, dip, motivo = linear_modes(xs, bin_size=30.0, dettagli=True)
    vuoto.update({"mediana": m, "disp": disp,
                  "disp_limite_inferiore": bool(censurati),
                  "durata": median(durs) if durs else None,
                  "modi": modi, "dip": dip, "modi_motivo": motivo})
    return vuoto


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

    # L'audit dei censurati: per ogni mese, quando comincia il dato nelle
    # giornate in cui il regime era gia' dentro al primo campione.
    inizio_finestra = spot["window"][0] * 60.0
    censura_audit = {}
    ingressi = {(b, l): {} for b in BERSAGLI for l in LETTURE}
    censurati = {(b, l): {} for b in BERSAGLI for l in LETTURE}
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
        if g.get("reason") == "left_censored" and g.get("first_sample_min") is not None:
            censura_audit.setdefault(mese, []).append(
                (g["first_sample_min"], g.get("cadence_min") or 0.0,
                 g.get("coverage_min") or 0.0))
        for bers in BERSAGLI:
            for lettura in LETTURE:
                suf = "" if lettura == "regime" else "_wind"
                ing = g["%s_onset%s" % (EN[bers], suf)]
                cens = g["%s_onset%s_censored" % (EN[bers], suf)]
                if ing is not None and cens:
                    censurati[(bers, lettura)].setdefault(mese, []).append(ing)
                elif ing is not None:
                    ingressi[(bers, lettura)].setdefault(mese, []).append(ing)
                dur = g["%s_duration%s_min" % (EN[bers], suf)]
                if dur:
                    durate[(bers, lettura)].setdefault(mese, []).append(dur)

    per_mese, annuale = {}, {}
    for bers in BERSAGLI:
        for lettura in LETTURE:
            tutti, tutti_cens = [], []
            for mese in range(1, 13):
                xs = ingressi[(bers, lettura)].get(mese, [])
                cs = censurati[(bers, lettura)].get(mese, [])
                tutti.extend(xs)
                tutti_cens.extend(cs)
                per_mese[(bers, lettura, mese)] = _riassunto(
                    xs, durate[(bers, lettura)].get(mese, []), min_gg,
                    censurati=cs)
            annuale[(bers, lettura)] = _riassunto(tutti, None, min_gg,
                                                  censurati=tutti_cens)

    return {"spot": spot_name, "asse": asse, "settore": settore,
            "soglie": soglie, "n_giorni": n_giorni,
            "n_dir_ignota": n_dir_ignota, "n_non_stimabili": n_non_stimabili,
            "per_mese": per_mese, "annuale": annuale, "ingressi": ingressi,
            "censurati": censurati, "per_giorno": per_giorno,
            "inizio_finestra": inizio_finestra,
            "censura_audit": audit_censura(censura_audit, inizio_finestra)}


# Quanto oltre il bordo della finestra un primo campione si considera "in
# ritardo". Mezz'ora e' la stessa persistenza che definisce un ingresso: se il
# dato comincia mezz'ora dopo l'inizio dell'osservazione, in quella mezz'ora un
# ingresso sarebbe stato possibile e non lo avremmo visto.
RITARDO_MIN = 30.0


def audit_censura(per_mese, inizio_finestra, ritardo_min=RITARDO_MIN):
    """Perche' una giornata e' censurata: finestra tarda o dato mancante.

    per_mese: {mese: [(primo_campione_min, cadenza_min, copertura_min)]} delle
    sole giornate censurate.

    Due spiegazioni, e vanno tenute separate perche' portano a due decisioni
    opposte:

      DAL BORDO   il dato c'era dall'inizio dell'osservazione (il primo
                  campione cade entro una cadenza dal bordo) e il vento era
                  gia' sopra soglia. Qui la finestra comincia troppo tardi, e
                  allargarla recupera l'informazione.
      IN RITARDO  il primo campione arriva molto dopo il bordo: di quella
                  giornata non abbiamo il dato prima, e allargare la finestra
                  non aggiunge niente. E' un problema di disponibilita'
                  storica, non di definizione.

    Fra le due c'e' una zona grigia (fra una cadenza e il ritardo): si conta a
    parte invece di essere assegnata d'ufficio a una delle due.
    """
    out = {}
    for mese, righe in per_mese.items():
        primi = [p for p, _c, _cv in righe]
        dal_bordo = in_ritardo = grigio = 0
        for p, cad, _cv in righe:
            tolleranza = max(cad or 0.0, 1.0)
            if p <= inizio_finestra + tolleranza:
                dal_bordo += 1
            elif p >= inizio_finestra + ritardo_min:
                in_ritardo += 1
            else:
                grigio += 1
        n = len(righe)
        out[mese] = {
            "n": n,
            "primo_mediano": median(primi),
            "primo_max": max(primi),
            "primo_min": min(primi),
            "dal_bordo": dal_bordo, "in_ritardo": in_ritardo, "grigio": grigio,
            "quota_dal_bordo": dal_bordo / float(n) if n else None,
            "quota_in_ritardo": in_ritardo / float(n) if n else None,
        }
    return out


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


def osservazioni(records, bersaglio="regime", lettura="regime",
                 censurate=False):
    """Le giornate con un ingresso MISURATO: [(data, mese, minuti)], in ordine.

    records: le strutture di giudica_giornata(), in qualunque ordine. Entrano
    solo quelle stimabili e con un ingresso: una giornata senza regime NON
    diventa un orario inventato, contribuisce solo al tasso di base.

    Le giornate CENSURATE A SINISTRA - regime gia' presente al primo campione
    della finestra - restano fuori: non sono misure dell'orario, sono limiti, e
    addestrare o misurare un modello del timing su un limite significa
    insegnargli un orario che nessuno ha osservato. Con censurate=True si
    ottengono proprio quelle, per contarle e dichiararle.
    """
    campo = _campo_ingresso(bersaglio, lettura)
    campo_cens = campo + "_censored"
    out = []
    for r in records:
        if not r.get("estimable") or r.get(campo) is None or not r.get("date"):
            continue
        if bool(r.get(campo_cens)) != bool(censurate):
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
    # I previsori vengono chiamati una volta per ogni giornata di validazione,
    # sempre con lo STESSO training dentro un fold. Rifare il raggruppamento
    # per mese a ogni chiamata rende il tutto quadratico: su quattordici anni
    # erano minuti di attesa per ricalcolare sei volte la stessa mediana.
    # La chiave e' quanto e' lungo il training e dove finisce: due prefissi
    # diversi non possono avere la stessa lunghezza E la stessa ultima data,
    # quindi la memoria non puo' rispondere per un altro insieme.
    cache = {}

    def previsore(training, ctx):
        chiave = (len(training), training[-1][0] if training else None,
                  ctx["mese"] if mensile else 0)
        if chiave not in cache:
            if not mensile:
                xs = [m for _g, _mm, m in training]
                cache[chiave] = ((median(xs), "annuale") if xs
                                 else (None, "insufficiente"))
            else:
                cache[chiave] = previsione_climatologica(
                    _per_mese(training), ctx["mese"], min_gg=min_gg)
        return cache[chiave]
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
    # Come sopra: la correzione dipende solo dal training e dal mese, non dalla
    # singola giornata da prevedere, e dentro un fold il training non cambia.
    # Senza questa memoria la stima si rifaceva per ogni giornata di
    # validazione, e su quattordici anni erano settanta secondi per bersaglio
    # invece di uno.
    cache = {}

    def previsore(training, ctx):
        grezzo, prov = base(training, ctx)
        if grezzo is None:
            return None, prov
        mese = ctx["mese"]
        chiave = (len(training), training[-1][0] if training else None, mese)
        if chiave not in cache:
            errori = []
            for i, (data, mm, obs) in enumerate(training):
                if mm != mese:
                    continue
                p, _pv = base(training[:i], {"date": data, "mese": mm})
                if p is not None:
                    errori.append(p - obs)
            cache[chiave] = median(errori) if len(errori) >= min_gg else None
        correzione = cache[chiave]
        if correzione is None:
            return grezzo, prov + "+bias:insufficiente"
        return grezzo - correzione, prov + "+bias"
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
    cens = osservazioni(records, bersaglio, lettura, censurate=True)
    stimabili = sum(1 for r in records if r.get("estimable"))
    base_nome = "climatologia"
    if previsori is None:
        previsori = {}
    previsori = dict(previsori)
    previsori.setdefault(base_nome, previsore_climatologico(min_gg=min_gg))

    vuoto = {"bersaglio": bersaglio, "lettura": lettura,
             "n_records": len(records), "n_stimabili": stimabili,
             "n_ingressi": len(oss), "n_censurati": len(cens),
             "quota_stimabile":
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

    # Le porte si misurano sul previsore che si USEREBBE. Non e' un dettaglio:
    # se nessun modello batte la climatologia, quello che si userebbe e' la
    # climatologia, e allora le porte vanno misurate su di lei - non su un
    # candidato che abbiamo scartato.
    #
    # Da qui i tre esiti, invece di due. "Incerto" e "climatologico" sono due
    # cose diverse, e confonderle sarebbe sbagliato in un modo preciso: dire
    # "orario incerto" mentre la finestra climatologica sta dentro venti
    # minuti significa buttare via un'informazione buona solo perche' nessun
    # modello sofisticato l'ha ancora migliorata.
    candidati = [nm for nm in risultati if nm != base_nome]
    scelto = None
    if candidati:
        con_mae = [(risultati[nm]["mae"], nm) for nm in candidati
                   if risultati[nm]["mae"] is not None]
        scelto = min(con_mae)[1] if con_mae else None

    porte = {}
    if scelto is None:
        porte["guadagno"] = {"valore": None, "ic": (None, None), "passa": None,
                             "nota": "nessun modello da confrontare"}
        vince = False
    else:
        g, lo, hi = risultati[scelto]["guadagno"]
        vince = (lo is not None and lo > 0.0)
        porte["guadagno"] = {"valore": g, "ic": (lo, hi), "passa": vince,
                             "nota": None if vince else
                             "nessun modello batte il riferimento fuori campione"}
    valutato = scelto if vince else base_nome
    r = risultati[valutato]

    porte["semiampiezza"] = {
        "valore": r["semiampiezza"], "limite": semiampiezza_max,
        "passa": (r["semiampiezza"] is not None
                  and r["semiampiezza"] <= semiampiezza_max)}
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

    # Tre esiti:
    #   affidabile     un modello batte la climatologia fuori campione, la
    #                  finestra sta nei limiti e non c'e' bias sistematico;
    #   climatologico  nessun modello batte la climatologia, ma la finestra
    #                  della climatologia stessa sta nei limiti: si dichiara
    #                  la finestra, dicendo da dove viene;
    #   incerto        la finestra e' troppo larga o c'e' un bias
    #                  sistematico: in home va una fascia larga.
    stretta = porte["semiampiezza"]["passa"]
    senza_bias = porte["bias_stagionale"]["passa"]
    if stretta and senza_bias:
        esito = "affidabile" if vince else "climatologico"
    else:
        esito = "incerto"
    motivo = None
    if esito == "incerto":
        mancate = [k2 for k2, p in porte.items() if p["passa"] is False
                   and k2 != "guadagno"]
        motivo = "porte non superate: " + ", ".join(sorted(mancate))
    elif esito == "climatologico":
        motivo = porte["guadagno"].get("nota")

    return {"bersaglio": bersaglio, "lettura": lettura,
            "n_records": len(records), "n_stimabili": stimabili,
            "n_ingressi": len(oss), "n_censurati": len(cens),
            "quota_stimabile": len(oss) / float(len(records)) if records else None,
            "n_fold": len(tagli), "fold": tagli,
            "riferimento": base_nome, "valutato": valutato,
            "previsori": risultati, "porte": porte,
            "esito": esito, "motivo": motivo}


# ==========================================================================
# 1b. La finestra utile: com'e' il vento QUANDO SI PUO' USCIRE
# ==========================================================================
#
# Domanda diversa da quella dell'ingresso, e per il Peler e' la domanda giusta.
# "A che minuto e' nato il Peler" e' inutile se e' nato alle tre di notte: la
# domanda e' "alle 6-9 quanto sara' buono". Quindi qui non si cerca un istante,
# si descrive un intervallo.
#
# Tre grandezze, tre ruoli distinti, e non vanno mescolate:
#
#   VENTO MEDIO         il fondo della sessione: quanto vento c'e' in modo
#                       continuo.
#   RAFFICA RICORRENTE  la spinta che TORNA: mediana dei massimi a 10 minuti
#       (30 minuti)     dentro una finestra mobile di mezz'ora. Entra nella
#                       planabilita', perche' con il wing si sta sul foil anche
#                       con una media modesta se la spinta ripassa spesso.
#   RAFFICA MASSIMA     NON decide la planata. Descrive quanto il vento e'
#                       rafficato, cioe' se la giornata e' gradevole o
#                       sgradevole: 11 kn medi con ricorrente 16 e' navigabile,
#                       11 kn medi con un solo picco a 23 no.
#
# Quello che questa funzione NON fa: non dice se si plana. Nessun coefficiente,
# nessuna soglia combinata, nessuna etichetta "forte / marginale / debole".
# Quei numeri si scelgono guardando la distribuzione vera di (media,
# ricorrente) sulle giornate forti e su quelle deboli - e la raffica
# nell'archivio lungo di Torbole non c'e', quindi quella distribuzione si
# costruisce da qui in avanti. Inventarla oggi vorrebbe dire scegliere le
# soglie prima di aver visto i dati, che e' esattamente cio' che abbiamo
# evitato di fare per la tabella wing.
#
# Al posto delle soglie: il tempo sopra soglia per una GRIGLIA di soglie
# candidate, sulla media e sulla ricorrente separatamente. Cosi' "quanta parte
# della finestra resta sopra X" e' disponibile per qualunque X si decidera',
# senza che nessun X sia cotto dentro.

# La griglia e' FITTA dove sta la distribuzione e larga dove non ci sta
# nessuno. Sul Peler in stagione calda la mediana del vento medio nella
# finestra pratica e' 8,4 kn e il 90esimo percentile 12,4: fra gli 8 e i 14
# nodi si decide tutto, e un passo di due nodi la' dentro salta esattamente le
# soglie che contano. Sopra i 16 il passo torna largo, perche' sono giornate
# rare e un nodo in piu' o in meno non cambia nessuna decisione.
#
# I 15 nodi ci sono per un motivo in piu': lui ha nominato "15-16" come la
# ricorrente che fa planare con dieci di media, e senza quel valore nella
# griglia la sua regola non sarebbe calcolabile il giorno in cui ci saranno
# le raffiche.
SOGLIE_CANDIDATE = (8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0,
                    18.0, 20.0)

# Sotto questa media il rapporto raffica/media non descrive la raffica: con 2
# nodi di media un rapporto 3 vuol dire 6 nodi, e non e' una giornata
# rafficata, e' una giornata senza vento.
MEDIA_MINIMA_RAPPORTO = 5.0


def giudica_finestra_utile(righe, asse, settore, inizio, fine,
                           soglie=SOGLIE_CANDIDATE,
                           persist_min=PERSISTENZA_MIN,
                           min_copertura_min=60.0):
    """La finestra utile di una giornata -> struttura. Nessuna etichetta.

    righe: [(minuti, vento, direzione, raffica_o_None)]. inizio e fine sono
    minuti dalla mezzanotte locale e arrivano da fuori: la luce e l'ora
    pratica sono decisioni, e una funzione pura non le prende.

    Come in giudica_giornata, la lettura e' quella del REGIME: i campioni
    fuori settore valgono zero e una direzione ignota non vale come coerente.
    """
    vuoto = {
        "inizio": inizio, "fine": fine,
        "estimable": False, "reason": None,
        "cadence_min": None, "coverage_min": 0.0, "n_samples": 0,
        "media_mediana": None, "media_q25": None, "media_q75": None,
        "media_max": None,
        "ric_stimabile": False, "ric_mediana": None, "ric_q75": None,
        "ric_max": None, "cadenza_raffica_min": None,
        "raffica_max": None,
        "rapporto_ric_media": None, "rapporto_max_media": None,
        "rapporto_disp": None,
        "minuti_sopra_media": {}, "minuti_sopra_ric": {},
        "planata_sostenuta_media": None, "planata_sostenuta_ric": None,
        "dir_unknown_frac": None,
    }
    dentro = sorted([r for r in righe
                     if r[1] is not None and inizio <= r[0] <= fine],
                    key=lambda r: r[0])
    if not dentro:
        vuoto["reason"] = "no_data"
        return vuoto

    minuti = [float(r[0]) for r in dentro]
    cad = sampling_cadence(minuti) or 0.0
    coperti = covered_minutes(minuti, cad)
    base = dict(vuoto)
    ignoti = sum(1 for r in dentro if r[2] is None)
    base.update({"cadence_min": cad, "coverage_min": coperti,
                 "n_samples": len(dentro),
                 "dir_unknown_frac": ignoti / float(len(dentro))})
    if coperti < min_copertura_min:
        base["reason"] = "insufficient_coverage"
        return base
    base["estimable"] = True
    base["reason"] = "ok"

    def nel_settore(d):
        return d is not None and angle_diff(d, asse) <= settore

    serie_media = [(float(r[0]), r[1] if nel_settore(r[2]) else 0.0)
                   for r in dentro]
    medie = [v for _m, v in serie_media]
    base.update({"media_mediana": median(medie),
                 "media_q25": quantile(medie, 0.25),
                 "media_q75": quantile(medie, 0.75),
                 "media_max": max(medie)})

    # La raffica: solo dai campioni che ce l'hanno, e con la cadenza di QUELLI.
    con_raffica = [(float(r[0]), r[3]) for r in dentro
                   if r[3] is not None and nel_settore(r[2])]
    cad_raffica = sampling_cadence([m for m, _g in con_raffica]) if con_raffica else None
    base["cadenza_raffica_min"] = cad_raffica
    if con_raffica:
        base["raffica_max"] = max(g for _m, g in con_raffica)
    serie_ric = []
    if con_raffica and window_estimable(cad_raffica, FINESTRA_RICORRENTE_MIN):
        base["ric_stimabile"] = True
        serie_ric = [(m, v) for m, v in
                     gust_level(con_raffica, FINESTRA_RICORRENTE_MIN,
                                centered=True, cadence_min=cad_raffica)
                     if v is not None]
        if serie_ric:
            valori = [v for _m, v in serie_ric]
            base.update({"ric_mediana": median(valori),
                         "ric_q75": quantile(valori, 0.75),
                         "ric_max": max(valori)})

    # I due rapporti, con i due significati diversi: la ricorrente sulla media
    # dice quanta spinta in piu' della media torna ripetutamente; il massimo
    # sulla media dice quanto la giornata e' irregolare. La dispersione del
    # primo e' la seconda componente della stabilita'.
    per_minuto = dict(serie_media)
    rapporti = []
    for m, v in serie_ric:
        media = per_minuto.get(m)
        if media and media >= MEDIA_MINIMA_RAPPORTO:
            rapporti.append(v / media)
    if rapporti:
        mediana_r = median(rapporti)
        base["rapporto_ric_media"] = mediana_r
        base["rapporto_disp"] = median([abs(r - mediana_r) for r in rapporti])
    if base["raffica_max"] is not None and base["media_mediana"] \
            and base["media_mediana"] >= MEDIA_MINIMA_RAPPORTO:
        base["rapporto_max_media"] = base["raffica_max"] / base["media_mediana"]

    # Il tempo sopra soglia per una griglia di soglie candidate, separatamente
    # sulla media e sulla ricorrente. Nessuna soglia e' "la" soglia.
    base["minuti_sopra_media"] = {
        t: time_above(serie_media, float(t), cad) for t in soglie}
    base["planata_sostenuta_media"] = {
        t: sustained_onset(serie_media, float(t), persist_min=persist_min,
                           cadence_min=cad) is not None for t in soglie}
    if serie_ric:
        base["minuti_sopra_ric"] = {
            t: time_above(serie_ric, float(t), cad_raffica) for t in soglie}
        base["planata_sostenuta_ric"] = {
            t: sustained_onset(serie_ric, float(t), persist_min=persist_min,
                               cadence_min=cad_raffica) is not None
            for t in soglie}
    return base


def finestra_utile_del_giorno(spot_name, giorno, alba_min=None):
    """(inizio, fine) della finestra utile, in minuti locali.

    Tre vincoli, e il piu' stretto vince:
      la finestra del regime, che dice quando quel vento puo' soffiare;
      l'ora pratica, che e' una scelta (le 06:00 per il Peler);
      la LUCE: alba + margine all'inizio, tramonto - margine alla fine.

    Questa funzione legge la configurazione, e per questo NON sta nella logica
    pura: l'ora pratica e i margini sono decisioni, e le decisioni stanno dove
    si possono cambiare senza toccare un calcolo.
    """
    spot = config.SPOTS[spot_name]
    h0, h1 = spot["window"]
    inizio, fine = h0 * 60.0, (h1 + 1) * 60.0
    pratica = spot.get("ora_pratica")
    if pratica is not None:
        inizio = max(inizio, pratica * 60.0)
    alba, tramonto = alba_tramonto(giorno, spot["lat"], spot["lon"],
                                   offset_locale_ore(giorno))
    # I limiti che vengono dalla luce si arrotondano a cinque minuti. Non e'
    # pigrizia: il margine dopo l'alba e' un giudizio con la precisione di una
    # mezz'ora, e i campioni arrivano ogni dieci minuti. Senza questo, a
    # giugno l'alba + 30 dava 06:01 e la finestra utile del Peler cominciava
    # alle 06:01 invece che alle 06:00 - un minuto che non esiste in nessun
    # dato e che rende il numero piu' preciso di quanto sia.
    def a_cinque(x):
        return round(x / 5.0) * 5.0

    if alba is not None:
        inizio = max(inizio, a_cinque(alba + config.MARGINE_ALBA_MIN))
    if tramonto is not None:
        fine = min(fine, a_cinque(tramonto - config.MARGINE_TRAMONTO_MIN))
    return inizio, fine


# ==========================================================================
# 1c. Due livelli di verita', e la contabilita' che li tiene separati
# ==========================================================================
#
# Lo storico lungo e il dataset della planabilita' NON sono lo stesso dataset,
# e la differenza e' enorme: quattordici anni contro poche giornate.
#
#   STORICO MEAN-ONLY        vento medio, direzione, stagionalita', frequenza
#                            dei regimi, durata, finestre tipiche. A Torbole
#                            sono 5153 giornate dal 2012.
#   PLANABILITY-READY        media + raffica ricorrente. Esiste solo dove c'e'
#                            la raffica, e l'archivio storico di Torbole non la
#                            contiene: e' un dataset PROSPETTIVO, che cresce da
#                            qui in avanti.
#
# Il rischio da cui questa contabilita' difende ha un nome preciso: il falso
# effetto "abbiamo quattordici anni di planabilita'". Non e' vero, e sarebbe il
# tipo di errore che non si vede - una tabella con l'aria di essere storica,
# costruita su nove giornate. E' gia' capitato una volta, quando l'analisi
# delle raffiche filtrava i campioni senza raffica e quattordici anni
# diventavano nove giorni senza dirlo.
#
# Quindi ogni analisi dichiara la sua copertura PRIMA dei suoi numeri, con i
# nomi che seguono - e sono i nomi decisi da lui, non tradotti.

def copertura_dataset(giorni, soglia_planability=30):
    """La contabilita' di copertura di un insieme di giornate.

    giorni: {giorno: [(minuti, vento, direzione, raffica)]} come lo produce
    giorni_osservati(). Ritorna i campi che ogni analisi deve dichiarare in
    testa, piu' la distinzione fra i due livelli.

    "planability_ready" non vuol dire "ci sono raffiche": vuol dire che su
    abbastanza giornate la raffica c'e' a una cadenza che sostiene la finestra
    mobile di 30 minuti. Una raffica ogni mezz'ora non rende una giornata
    planability-ready, e chiamarla tale sarebbe lo stesso errore di prima con
    un'altra maschera.
    """
    tot = sorted(giorni)
    con_raffica, ric_ok, cadenze, cadenze_g = [], [], [], []
    for giorno in tot:
        righe = giorni[giorno]
        minuti = [float(r[0]) for r in righe if r[1] is not None]
        if minuti:
            c = sampling_cadence(minuti)
            if c:
                cadenze.append(c)
        con_g = [float(r[0]) for r in righe if len(r) > 3 and r[3] is not None]
        if not con_g:
            continue
        con_raffica.append(giorno)
        cg = sampling_cadence(con_g)
        if cg:
            cadenze_g.append(cg)
        if window_estimable(cg, FINESTRA_RICORRENTE_MIN):
            ric_ok.append(giorno)

    n = len(tot)
    return {
        "n_days_total": n,
        "n_days_with_gust": len(con_raffica),
        "n_days_recurrent_ready": len(ric_ok),
        "quota_with_gust": (len(con_raffica) / float(n)) if n else None,
        "quota_recurrent_ready": (len(ric_ok) / float(n)) if n else None,
        "periodo": (tot[0], tot[-1]) if tot else (None, None),
        "periodo_gust": ((con_raffica[0], con_raffica[-1])
                         if con_raffica else (None, None)),
        "periodo_recurrent": (ric_ok[0], ric_ok[-1]) if ric_ok else (None, None),
        "cadenza_mediana": median(cadenze) if cadenze else None,
        "cadenza_raffica_mediana": median(cadenze_g) if cadenze_g else None,
        # Il livello che si puo' studiare adesso, dichiarato come tale.
        "livello_medio": "storico mean-only",
        "livello_planabilita": ("planability-ready"
                                if len(ric_ok) >= soglia_planability
                                else "prospettico: campione ancora troppo piccolo"),
        "planability_ready": len(ric_ok) >= soglia_planability,
        "soglia_planability": soglia_planability,
    }


# ==========================================================================
# 1d. La distribuzione della finestra utile: i numeri da cui si SCEGLIE
# ==========================================================================
#
# Le soglie di planata delle sue ali non sono mai state scelte, e finora il
# codice ha fatto la cosa giusta: non inventarle. Ma non scegliere non e'
# gratis - senza una soglia non esiste "quanto sara' buono alle 6-9", che e'
# la domanda da cui e' partito tutto il blocco del Peler.
#
# Questa aggregazione non sceglie niente nemmeno lei. Prende la griglia di
# soglie candidate e, per ogni mese, dice due cose per ognuna:
#
#   in quante giornate la MEDIA e' rimasta sopra quella soglia per almeno la
#   persistenza (trenta minuti consecutivi) DENTRO la finestra utile;
#   e quanto e' durata, quando e' successo.
#
# Cosi' la scelta si fa guardando: "a 14 nodi dicembre da' il 18% delle
# giornate per una media di 70 minuti" e' una frase su cui si puo' decidere.
# "La soglia e' 14" no.
#
# Una cosa che questa tabella NON dice, e che va detta ogni volta: e' tutta
# sul VENTO MEDIO. La raffica ricorrente non c'e' nell'archivio lungo, quindi
# queste percentuali sono un limite INFERIORE della planabilita' vera - con il
# wing si sta sul foil anche sotto la media, se la spinta ripassa. Il numero
# di giornate in cui la ricorrente era stimabile viaggia accanto, in chiaro,
# perche' e' quello che dice quanto siamo lontani dal poter rispondere davvero.

def aggrega_finestre(finestre, soglie=SOGLIE_CANDIDATE, min_gg=MIN_GG_MESE,
                     stagioni=None):
    """PURA. {giorno: esito di giudica_finestra_utile} -> distribuzione mensile.

    Nessuna soglia e' privilegiata e nessun coefficiente viene introdotto: si
    contano giornate e minuti, per ognuna delle soglie candidate.

    Un mese con meno di min_gg giornate stimabili viene comunque restituito,
    ma marcato `sufficiente: False`: nasconderlo darebbe l'impressione che non
    ci siano dati, e invece ci sono e sono pochi - che e' un'informazione
    diversa e piu' utile.
    """
    gruppi = {}
    for giorno in sorted(finestre):
        gruppi.setdefault(int(giorno[5:7]), []).append((giorno, finestre[giorno]))

    def riassumi(coppie):
        stimabili = [e for _g, e in coppie if e.get("estimable")]
        motivi = {}
        for _g, e in coppie:
            if not e.get("estimable"):
                r = e.get("reason") or "no_data"
                motivi[r] = motivi.get(r, 0) + 1
        out = {
            "n_giorni": len(coppie),
            "n_stimabili": len(stimabili),
            "motivi": motivi,
            "sufficiente": len(stimabili) >= min_gg,
            "n_ric_stimabile": sum(1 for e in stimabili if e.get("ric_stimabile")),
            "inizio_mediano": None, "fine_mediana": None, "durata_mediana": None,
            "media_q25": None, "media_mediana": None, "media_q75": None,
            "picco_mediano": None, "picco_q90": None,
            "soglie": {},
        }
        if not stimabili:
            return out
        inizi = [e["inizio"] for e in stimabili if e.get("inizio") is not None]
        fini = [e["fine"] for e in stimabili if e.get("fine") is not None]
        if inizi and fini:
            out["inizio_mediano"] = median(inizi)
            out["fine_mediana"] = median(fini)
            out["durata_mediana"] = median([b - a for a, b in zip(inizi, fini)])
        # Il "fondo" della giornata dentro la finestra: la mediana del vento
        # medio. Il picco e' il massimo istantaneo della media, che serve a
        # capire se la giornata aveva un momento buono o era piatta.
        centri = [e["media_mediana"] for e in stimabili
                  if e.get("media_mediana") is not None]
        if centri:
            ordinati = sorted(centri)
            out["media_q25"] = quantile(ordinati, 0.25)
            out["media_mediana"] = median(ordinati)
            out["media_q75"] = quantile(ordinati, 0.75)
        picchi = sorted([e["media_max"] for e in stimabili
                         if e.get("media_max") is not None])
        if picchi:
            out["picco_mediano"] = median(picchi)
            out["picco_q90"] = quantile(picchi, 0.9)

        # Una soglia che le giornate non hanno calcolato NON e' una soglia con
        # zero giornate sopra. La differenza e' tutta: la prima e' "non lo
        # sappiamo", la seconda e' "non succede mai", e una tabella che le
        # confonde stampa uno zero rassicurante al posto di un buco.
        for t in soglie:
            calcolate = [e for e in stimabili
                         if t in (e.get("planata_sostenuta_media") or {})]
            sopra = [e for e in calcolate
                     if e["planata_sostenuta_media"].get(t)]
            durate = sorted([(e.get("minuti_sopra_media") or {}).get(t) or 0.0
                             for e in sopra])
            out["soglie"][t] = {
                "n_calcolate": len(calcolate),
                "non_calcolata": len(calcolate) == 0,
                "n_sostenute": len(sopra),
                "quota": ((len(sopra) / float(len(calcolate)))
                          if calcolate else None),
                "durata_mediana": median(durate) if durate else None,
                "durata_q75": quantile(durate, 0.75) if len(durate) >= 4 else None,
            }
        return out

    tutte = [(g, e) for m in sorted(gruppi) for g, e in gruppi[m]]
    # Le stagioni arrivano da fuori, come la finestra: quali mesi sono "la
    # stagione in cui si naviga" e' una decisione, e una funzione pura non
    # prende decisioni. Passando None non ci sono stagioni, e la tabella e'
    # solo mensile - cosi' un fold o un controllo puo' chiedere i mesi nudi.
    per_stagione = {}
    for nome, mesi in (stagioni or ()):
        coppie = [c for m in mesi for c in gruppi.get(m, ())]
        per_stagione[nome] = riassumi(coppie)
        per_stagione[nome]["mesi_inclusi"] = tuple(mesi)
    return {
        "soglie": tuple(soglie),
        "min_gg": min_gg,
        "mesi": {m: riassumi(gruppi[m]) for m in sorted(gruppi)},
        "stagioni": per_stagione,
        "ordine_stagioni": tuple(n for n, _m in (stagioni or ())),
        "anno": riassumi(tutte),
    }


def distribuzione_finestra_utile(spot_name, giorni=None,
                                 soglie=SOGLIE_CANDIDATE,
                                 persist_min=PERSISTENZA_MIN,
                                 stagioni=None):
    """Livello 2: legge configurazione e archivio, poi aggrega.

    La finestra utile di OGNI giornata viene ricalcolata, perche' dipende dalla
    luce e quindi dal giorno dell'anno: a dicembre il Peler utilizzabile
    comincia dopo che a giugno, e mediare le due sarebbe mediare due finestre
    diverse chiamandole la stessa.
    """
    spot = config.SPOTS[spot_name]
    asse = spot.get("axis_obs", spot["axis"])
    settore = config.REGIME_SECTOR_DEG
    giorni = giorni_osservati(spot_name) if giorni is None else giorni
    finestre = {}
    for giorno in sorted(giorni):
        inizio, fine = finestra_utile_del_giorno(spot_name, giorno)
        if fine <= inizio:
            finestre[giorno] = {"inizio": inizio, "fine": fine,
                                "estimable": False, "reason": "no_daylight"}
            continue
        finestre[giorno] = giudica_finestra_utile(
            giorni[giorno], asse, settore, inizio, fine,
            soglie=soglie, persist_min=persist_min)
    D = aggrega_finestre(
        finestre, soglie=soglie,
        stagioni=config.STAGIONI_USO if stagioni is None else stagioni)
    D["spot"] = spot_name
    D["asse"] = asse
    D["settore"] = settore
    D["persist_min"] = persist_min
    D["copertura"] = copertura_dataset(giorni)
    return D
