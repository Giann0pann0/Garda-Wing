"""Orchestrazione: raccolta dati, addestramento, produzione della previsione."""

import datetime as _dt
import os
import math
import threading
import time

from . import (aggregate, analogs, config, confidence as CONF, features as F,
               model as M, store, validate as V, verify)
from .sources import (addicted, addicted_live, malcesine, meteotrentino,
                      openmeteo)
from .sources.http import FetchError
from .util import (angle_diff, clamp, day_shift, iso_utc, local_day, local_hour,
                   local_minute_of_day, mean, median, parse_dt_any, pstdev,
                   recurrent_gust, sampling_cadence, serie_disegnabile,
                   utc_now,
                   vector_mean_direction, window_estimable,
                   FINESTRA_RICORRENTE_MIN)

STATE = {
    "running": False,
    "phase": "",
    "started": None,
    "finished": None,
    "errors": [],
}
_LOCK = threading.Lock()


def _note(level, scope, message):
    store.log_event(level, scope, message)
    if level == "error":
        STATE["errors"] = (STATE["errors"] + ["%s: %s" % (scope, message)])[-10:]


def _points():
    seen = {}
    for name, s in config.SPOTS.items():
        seen.setdefault(store.point_key(s["lat"], s["lon"]), (s["lat"], s["lon"]))
    return seen


# ==========================================================================
# Raccolta previsioni
# ==========================================================================

def update_forecasts():
    run = iso_utc(utc_now())
    okc = 0
    for point, (lat, lon) in _points().items():
        for name, m in config.MODELS.items():
            try:
                rows, _elev = openmeteo.fetch_forecast(lat, lon, m["id"], m["levels"])
                if rows:
                    store.save_forecast(point, name, run, rows)
                    okc += 1
            except FetchError as e:
                _note("warn", "forecast/%s" % name, str(e)[:160])
    # Sorgente separata per la selezione degli analoghi. Deve essere la stessa
    # famiglia (best_match) del previous-runs usato nella validazione,
    # e NON deve entrare nell'ensemble operativo. Per questo vive in arch_hour
    # con un prefisso dedicato invece che in fc_hour.
    for _point, (lat, lon) in _points().items():
        try:
            rows, _elev = openmeteo.fetch_forecast(
                lat, lon, config.ARCHIVE_MODEL, False)
            if rows:
                store.save_archive(store.point_key(lat, lon, analogs.CURRENT_SOURCE), rows)
        except FetchError as e:
            # La diagnostica deve dire la CONSEGUENZA, non solo la causa. Un
            # "handshake operation timed out" lo capisce chi conosce il
            # codice; che la curva mostrata sia tornata quella liscia lo
            # capisce chiunque guardi la pagina e si chieda perche'. E se la
            # porta e' aperta non e' un avviso: e' una funzione promessa e
            # spenta, quindi va in errore.
            livello = "error" if analogs.promoted() else "warn"
            _note(livello, "forecast/analoghi",
                  "condizioni per gli analoghi non scaricate, la forma resta"
                  " quella liscia: %s" % str(e)[:120])

    store.meta_set("last_forecast_run", run)
    store.prune_forecasts(keep_runs=3)
    return okc


def update_context():
    run = iso_utc(utc_now())
    n = 0
    for place, (lat, lon, _side) in config.CONTEXT_POINTS.items():
        try:
            rows = openmeteo.fetch_context(lat, lon)
            n += store.save_context(place, "live", rows)
        except FetchError as e:
            _note("warn", "context/%s" % place, str(e)[:160])
    store.meta_set("last_context_run", run)
    return n


# ==========================================================================
# Centraline
# ==========================================================================

def update_stations():
    done = []
    try:
        rows = meteotrentino.fetch_realtime(hours=168)
        store.save_samples("T0193", rows, "meteotrentino-realtime")
        # Il servizio restituisce i campioni dal piu' recente: la finestra da
        # riaggregare parte dal piu' VECCHIO, non dal primo della lista.
        aggregate.aggregate_station("T0193",
                                    since_iso=min(r[0] for r in rows) if rows else None)
        done.append("Torbole %d campioni" % len(rows))
    except FetchError as e:
        _note("error", "centralina/Torbole", str(e)[:160])

    try:
        sample, gust_day = malcesine.fetch_live()
        store.save_samples("malcesine", [sample], "meteoproject-live")
        aggregate.aggregate_station("malcesine", since_iso=day_shift(sample[0][:10], -2))
        if gust_day is not None:
            store.save_day_obs("malcesine", [(local_day(parse_dt_any(sample[0])),
                                              None, gust_day, None)],
                               "meteoproject-live")
        done.append("Malcesine 1 campione")
    except FetchError as e:
        _note("error", "centralina/Malcesine", str(e)[:160])

    # La raffica di Malcesine in tempo reale: la pagina live non ce l'ha (solo
    # la massima del giorno), l'archivio intraday si'. Si chiede solo oggi.
    try:
        rows = malcesine.fetch_intraday_giorno(local_day(utc_now()))
        if rows:
            store.save_samples("malcesine", rows, "meteoproject-intraday")
            aggregate.aggregate_station("malcesine", since_iso=rows[0][0])
            done.append("Malcesine %d misure intraday di oggi" % len(rows))
    except Exception as e:                        # noqa: BLE001
        _note("warn", "intraday/Malcesine",
              "%s: %s" % (type(e).__name__, str(e)[:140]))

    # Le centraline Addicted (Campione): serie ORARIA, oggi e ieri. Oggi
    # perche' e' il dato vivo, ieri perche' l'ultima ora di ieri era
    # provvisoria quando l'abbiamo letta.
    for stazione, slug in stazioni_addicted():
        try:
            n = 0
            for giorno in (day_shift(local_day(utc_now()), -1),
                           local_day(utc_now())):
                righe, meta = addicted.fetch_hourly(giorno=giorno, slug=slug)
                n += salva_ore_addicted(stazione, righe)
                # La LORO previsione viaggia nella stessa risposta, e finora
                # la buttavamo. Archiviarla non costa una richiesta in piu' ed
                # e' l'unica strada per un confronto che regga: loro
                # ripubblicano i giorni passati senza dire a che scadenza li
                # avevano previsti, e quel dubbio non si recupera dopo.
                store.save_fc_altrui(addicted.SOURCE, stazione,
                                     meta.get("previsione_loro") or [])
            done.append("%s %d ore" % (stazione, n))
        except Exception as e:                    # noqa: BLE001
            # Non solo FetchError: queste pagine cambiano senza avvisare, e
            # un parser che inciampa su una stazione non deve portarsi dietro
            # le altre - ne' impedire che live.json venga scritto. Il guasto
            # finisce nel registro, la giornata continua.
            _note("error", "centralina/%s" % stazione,
                  "%s: %s" % (type(e).__name__, str(e)[:140]))

    # A Torbole la centralina della pagina e' Meteotrentino, quindi il ciclo
    # qui sopra non passa dalla pagina Addicted di Torbole - ed e' proprio
    # quella su cui il confronto conta di piu', perche' li' abbiamo il modello
    # migliore. Una richiesta al giro, solo per archiviare la loro previsione.
    try:
        _righe, meta = addicted.fetch_hourly(slug="torbole")
        n = store.save_fc_altrui(addicted.SOURCE, "torbole_addicted",
                                 meta.get("previsione_loro") or [])
        if n:
            done.append("previsione Addicted a Torbole: %d ore" % n)
    except Exception as e:                                # noqa: BLE001
        _note("warn", "previsione-altrui/torbole",
              "%s: %s" % (type(e).__name__, str(e)[:140]))

    # E il canale VIVO, una richiesta per tutte le centraline Addicted. E'
    # quello che rende la curva del misurato di Campione e Malcesine fitta
    # come quella di Torbole: la serie oraria qui sopra da' un punto all'ora,
    # questo ne da' uno ogni giro del processo veloce.
    done += leggi_addicted_vivo()
    return done


def leggi_addicted_vivo():
    """Il canale vivo di Addicted -> obs_sample, per le stazioni della pagina.

    Scrive SOLO campioni. obs_hour resta della serie oraria: quella e' la
    grandezza su cui i modelli sono addestrati, e cambiarne la provenienza a
    meta' storia vorrebbe dire un bersaglio che cambia definizione nel tempo.
    """
    done = []
    try:
        letture, _meta = addicted_live.fetch()
    except Exception as e:                            # noqa: BLE001
        _note("warn", "centralina/addicted-vivo",
              "%s: %s" % (type(e).__name__, str(e)[:140]))
        return done
    for stazione, slug in stazioni_addicted():
        r = letture.get(slug)
        if not r or r["wind"] is None:
            continue
        if r["stale"] or (r["eta_min"] or 0) > addicted_live.ETA_MAX_MIN:
            # Il sito stesso dichiara quando una centralina non sta misurando:
            # si crede a lui invece di scrivere una riga vecchia come nuova.
            continue
        n = store.save_samples(stazione, [(r["ts"], r["wind"], r["gust"], r["dir"])],
                               addicted_live.SOURCE)
        if n:
            done.append("%s vivo: %.1f kn (media %g', %s campioni)"
                        % (stazione, r["wind"], r["finestra_min"] or 0,
                           r["n_campioni"]))
    return done


def stazioni_addicted():
    """[(station, slug)] delle centraline la cui fonte e' Addicted."""
    out = []
    for name in config.SPOT_ORDER:
        s = config.SPOTS[name]
        if s.get("source") == "addicted" and (s["station"], s["addicted_slug"]) not in out:
            out.append((s["station"], s["addicted_slug"]))
    return out


# Addicted media gia' i dieci minuti dentro l'ora: la riga oraria che arriva
# e' una media di sei letture che non vediamo. Si scrive 6 perche' il
# bersaglio scarta le ore "ricostruite da pochissimi campioni" (n < 2), e
# queste non lo sono: sono ore intere, mediate a monte.
N_CAMPIONI_ORA_ADDICTED = 6


def salva_ore_addicted(station, righe):
    """Righe (ts_utc, medio, massimo, None) -> obs_hour, piu' un campione per
    ora in obs_sample cosi' l'adesso della pagina ha qualcosa da leggere.

    La direzione resta None in entrambe le tabelle: non e' misurata. La
    prende in prestito store.obs_hours, dichiarandolo.
    """
    if not righe:
        return 0
    store.upsert_obs_hours(station, [{
        "hour": store.chiave_ora(ts), "wind_mean": w, "wind_max": None, "gust_max": g,
        "gust_rec": None, "dir_deg": None, "dir_const": None,
        "n_samples": N_CAMPIONI_ORA_ADDICTED} for ts, w, g, _d in righe])
    store.save_samples(station, righe, "addicted-json")
    return len(righe)


def promuovi_storico_addicted(station=None):
    """Lo storico Addicted (addicted_hour) diventa l'osservato della
    centralina (obs_hour), per le stazioni che hanno Addicted come fonte.

    Per Torbole non si fa: la pagina mostra Meteotrentino, e i due sensori
    non misurano la stessa raffica (1,9 contro 1,45). Per Campione si fa,
    perche' la centralina della pagina E' quella dello storico. Sovrascrive
    solo le ore che non sono gia' arrivate dal canale vivo.
    """
    out = {}
    for stazione, slug in stazioni_addicted():
        if station and stazione != station:
            continue
        gia = {r["hour"] for r in store._obs_hours_grezze(stazione)}
        righe = []
        for ora, media, massimo in storico_addicted(slug):
            # La chiave canonica, la stessa che c'e' in tabella: con la
            # forma corta il confronto con `gia` non combaciava, e lo storico
            # tornava a sovrascrivere le ore gia' arrivate dal canale vivo.
            chiave = store.chiave_ora(ora)
            if chiave in gia:
                continue
            righe.append({"hour": chiave, "wind_mean": media,
                          "wind_max": None, "gust_max": massimo,
                          "gust_rec": None, "dir_deg": None, "dir_const": None,
                          "n_samples": N_CAMPIONI_ORA_ADDICTED})
        if righe:
            store.upsert_obs_hours(stazione, righe)
        out[stazione] = len(righe)
    return out


def storico_addicted(slug):
    """[(ora_utc, media, massimo)] dello storico Addicted di una stazione.

    Prima dal database (addicted_hour, il censimento fatto sul Mac di Gian);
    se li' non c'e' niente, dal file nel progetto, storico/<slug>-addicted
    .csv.gz. Il file esiste per una ragione precisa: il censimento Addicted
    - novecento richieste a un sito che non ci ha chiesto niente - e' stato
    fatto UNA volta, sul Mac, e il database con cui GitHub costruisce il sito
    e' un altro. Senza il file, Campione online sarebbe rimasta senza
    storico, quindi senza modello, mentre sul Mac funzionava. E' anche la
    rete di sicurezza se la cache di GitHub viene sfrattata: 326 KB per
    nove anni di ore.
    """
    righe = [(r["hour"], r["wind_mean_kn"], r["hourly_max_kn"])
             for r in store.connect().execute(
                 "SELECT hour, wind_mean_kn, hourly_max_kn FROM addicted_hour "
                 "WHERE station=? AND wind_mean_kn IS NOT NULL ORDER BY hour",
                 (slug,))]
    if righe:
        return righe
    import csv
    import gzip
    import io
    path = os.path.join(config.PROJECT_DIR, "storico",
                        "%s-addicted.csv.gz" % slug)
    if not os.path.isfile(path):
        return []
    with gzip.open(path, "rb") as fh:
        testo = fh.read().decode("utf-8")
    out = []
    for r in csv.DictReader(io.StringIO(testo)):
        try:
            media = float(r["wind_mean_kn"])
        except (TypeError, ValueError):
            continue
        massimo = float(r["hourly_max_kn"]) if r.get("hourly_max_kn") else None
        out.append((r["hour"], media, massimo))
    return out


def refresh_malcesine_intraday(months=2):
    """Riscarica gli ultimi mesi dell'archivio intraday di Malcesine.

    Serve solo in cloud, e li' serve parecchio. Il backfill completo gira una
    volta e poi si marca come fatto; da quel momento gli unici campioni nuovi
    arrivano da fetch_live(), che pesca UN istante per esecuzione. Sul Mac non
    e' un problema, perche' l'agente in background legge ogni quindici minuti.
    Su GitHub Actions, che gira quattro volte al giorno, vorrebbe dire quattro
    campioni al giorno invece di una novantina: il modello di Malcesine, che
    gia' soffre per mancanza di storico, resterebbe affamato per sempre.

    L'archivio CSV della stazione pubblica pero' tutte le letture a 15-30
    minuti, anche all'indietro. Due richieste per ciclo (il mese corrente e il
    precedente, per non perdere il cambio mese) recuperano tutto quello che la
    lettura istantanea non ha visto. INSERT OR REPLACE rende l'operazione
    idempotente: riscaricare lo stesso mese non duplica niente.
    """
    import datetime as _d
    oggi = _d.date.today()
    got = 0
    coppie = []
    for k in range(months):
        m = oggi.month - k
        y = oggi.year
        while m <= 0:
            m += 12
            y -= 1
        coppie.append((m, y))
    for month, year in coppie:
        try:
            rows = malcesine.fetch_intraday(month, year)
        except FetchError as e:
            _note("warn", "intraday/Malcesine",
                  "aggiornamento %02d/%d: %s" % (month, year, str(e)[:90]))
            continue
        if rows:
            store.save_samples("malcesine", rows, "meteoproject-intraday")
            got += len(rows)
    if got:
        aggregate.aggregate_station("malcesine",
                                    since_iso=day_shift(oggi.isoformat(), -70))
    return got


def backfill_station_history(force=False, on_progress=None):
    """Scarica una volta sola gli archivi storici pubblici delle centraline."""
    out = []

    # Campione: lo storico e' gia' in archivio (addicted_hour, importato dal
    # censimento Addicted). Qui diventa osservato, cosi' i passi successivi
    # - ERA5, archivio, scadenze - vedono da quando ha dati.
    for stazione, n in promuovi_storico_addicted().items():
        if n:
            out.append("%s: %d ore promosse dallo storico Addicted" % (stazione, n))
            if on_progress:
                on_progress("  %s: %d ore dallo storico Addicted" % (stazione, n))

    if force or not store.meta_get("backfill_torbole"):
        try:
            # Si salva anno per anno, appena arriva: se lo scaricamento si
            # interrompe a meta' (rete, chiusura dell'app, timeout del
            # servizio) quello gia' preso resta a terra e la volta dopo si
            # riparte da dove si era rimasti.
            saved = {"n": 0, "years": 0}

            def on_year(year, rows, err):
                if err:
                    _note("warn", "archivio/Torbole", "%d: %s" % (year, err))
                    return
                store.save_samples("T0193", rows, "meteotrentino-archivio")
                saved["n"] += len(rows)
                saved["years"] += 1
                store.meta_set("backfill_torbole_last_year", year)
                if on_progress:
                    on_progress("  Torbole %d: %d misure (totale %d)"
                                % (year, len(rows), saved["n"]))

            resume = store.meta_get("backfill_torbole_last_year")
            meteotrentino.fetch_archive(
                on_year=on_year,
                from_year=(int(resume) + 1) if resume else None)
            aggregate.aggregate_station("T0193")
            rows = []
            store.meta_set("backfill_torbole", iso_utc(utc_now()))
            out.append("Torbole: %d misure a 10 minuti su %d anni"
                       % (saved["n"], saved["years"]))
            # Controllo incrociato fra archivio e realtime: se le due sorgenti
            # fossero su fusi diversi lo si vedrebbe qui, non fra sei mesi.
            try:
                live = meteotrentino.fetch_realtime(hours=48)
                stored = [(r["hour"], r["wind_mean"], None, None)
                          for r in store.obs_hours("T0193")]
                n, agree, gap = meteotrentino.consistency_check(stored, live)
                if n and agree is not None and agree < 0.8:
                    _note("warn", "coerenza/Torbole",
                          "archivio e realtime divergono su %d istanti comuni "
                          "(accordo %.0f%%, scarto medio %.2f kn)" % (n, agree * 100, gap))
                else:
                    store.meta_set("torbole_consistency", "%d/%s" % (n, agree))
            except FetchError:
                pass
        except FetchError as e:
            _note("error", "archivio/Torbole", str(e)[:200])

    # Archivio INTRADAY di Malcesine: e' quello che permette di separare il
    # Peler dall'Ora. Il report NOAA giornaliero da' un solo numero al giorno
    # e non dice a che ora e' successo.
    if force or not store.meta_get("backfill_malcesine_intraday"):
        got = 0
        for month, year in malcesine.intraday_months():
            try:
                rows = malcesine.fetch_intraday(month, year)
            except FetchError as e:
                _note("warn", "intraday/Malcesine",
                      "%02d/%d: %s" % (month, year, str(e)[:90]))
                continue
            if not rows:
                continue
            store.save_samples("malcesine", rows, "meteoproject-intraday")
            got += len(rows)
            if on_progress:
                on_progress("  Malcesine %02d/%d: %d misure intraday" % (month, year, len(rows)))
        if got:
            aggregate.aggregate_station("malcesine")
            store.meta_set("backfill_malcesine_intraday", iso_utc(utc_now()))
            out.append("Malcesine: %d misure intraday" % got)
        else:
            _note("warn", "intraday/Malcesine", "nessun mese intraday scaricabile")

    if force or not store.meta_get("backfill_malcesine"):
        total = 0
        for month, year in malcesine.available_months():
            try:
                rows = malcesine.fetch_month(month, year)
                total += store.save_day_obs("malcesine", rows, "meteoproject-noaa")
            except FetchError:
                continue
            if on_progress and total:
                on_progress("  Malcesine %02d/%d: %d giorni finora" % (month, year, total))
        if total:
            store.meta_set("backfill_malcesine", iso_utc(utc_now()))
            out.append("Malcesine: %d giorni di archivio" % total)
        else:
            _note("warn", "archivio/Malcesine", "nessun report mensile scaricabile")
    return out


# ==========================================================================
# Predittori storici
# ==========================================================================

def _obs_span(station):
    st = store.obs_stats(station)
    days = [d for d in (st["hour_from"], st["day_from"]) if d]
    if not days:
        return None, None
    start = min(d[:10] for d in days)
    ends = [d for d in (st["hour_to"], st["day_to"]) if d]
    return start, max(d[:10] for d in ends)


def _punti_stazioni():
    """{chiave del punto: (lat, lon, [stazioni che stanno in quel punto])}.

    Serve per chiedere a ogni punto la cosa giusta: i predittori di Campione
    devono coprire le osservazioni di CAMPIONE, non il 2012 di Torbole.
    """
    out = {}
    for s in config.SPOTS.values():
        chiave = store.point_key(s["lat"], s["lon"])
        rec = out.setdefault(chiave, (s["lat"], s["lon"], []))
        if s["station"] not in rec[2]:
            rec[2].append(s["station"])
    return out


def _inizio_utile(stazioni, orizzonte):
    """Da quando servono i predittori per queste stazioni: l'inizio delle
    loro osservazioni, non prima dell'orizzonte dell'archivio."""
    inizi = [a for a in (_obs_span(st)[0] for st in stazioni) if a]
    if not inizi:
        return None
    return max(min(inizi), orizzonte)


# Quanto scarto si accetta fra l'inizio dei predittori e l'inizio delle
# osservazioni prima di dire "questo punto e' scoperto". Un mese: meno
# sarebbe rumore (l'archivio non comincia al giorno esatto), piu' vorrebbe
# dire buttare via giornate di addestramento.
SCOPERTO_GIORNI = 30


def predittori_scoperti(source="forecast", max_years=5):
    """I punti i cui predittori storici NON arrivano dove arrivano le
    osservazioni: [(punto, inizio_servito, inizio_che_serve)].

    E' la domanda giusta da fare prima di scaricare. Prima si chiedeva
    soltanto "quanto tempo e' passato dall'ultima volta?", e una localita'
    aggiunta oggi restava senza predittori - e quindi senza modello, e quindi
    in pagina col vento grezzo d'ensemble - fino a quando un orologio non
    scadeva. E' successo a Campione: osservazioni dal 2017 in archivio,
    modello assente, pagina con i numeri del modello nudo.

    Un punto che e' gia' stato tentato da quella data non e' scoperto: se
    l'archivio non ha quei giorni non li avra' nemmeno al prossimo giro, e
    riprovare a ogni ciclo sarebbe traffico infinito.
    """
    if source == "era5":
        # La rianalisi risale molto piu' indietro dell'archivio delle
        # previsioni: il suo orizzonte e' dichiarato in config, non cinque anni.
        orizzonte = config.ERA5_START
    else:
        orizzonte = (_dt.date.today()
                     - _dt.timedelta(days=int(365.25 * max_years))).isoformat()
    out = []
    for chiave, (lat, lon, stazioni) in _punti_stazioni().items():
        serve = _inizio_utile(stazioni, orizzonte)
        if not serve:
            continue
        punto = store.point_key(lat, lon, source)
        tentato = store.meta_get("predittori_tentati_%s" % punto)
        if tentato and tentato <= serve:
            continue
        ha, _b, _n = store.archive_span(punto)
        if ha and ha[:10] <= day_shift(serve, SCOPERTO_GIORNI):
            continue
        out.append((punto, ha[:10] if ha else None, serve))
    return out


def backfill_era5_features(chunk_days=730):
    """Rianalisi ERA5 di superficie, dall'inizio delle osservazioni.

    E' cio' che permette di addestrare su quattordici anni invece che su
    cinque: l'archivio delle previsioni non risale oltre, ma le osservazioni
    di Torbole partono dal 2012. Il prezzo e' la mancanza dei livelli
    isobarici, e il confronto fra i due addestramenti lo arbitra il modello.
    """
    today = _dt.date.today()
    end_day = (today - _dt.timedelta(days=6)).isoformat()   # ERA5 ha ~5 gg di ritardo

    punti = _punti_stazioni()
    inizi = [g for g in (_inizio_utile(st, config.ERA5_START)
                         for _la, _lo, st in punti.values()) if g]
    if not inizi:
        return ["nessuna osservazione: niente da allineare"]
    start_day = min(inizi)      # per il contesto, che e' comune a tutti i punti

    out = []
    for _key, (lat, lon, stazioni) in punti.items():
        point = store.point_key(lat, lon, "era5")
        # Ogni punto parte da dove partono le SUE osservazioni: scaricare il
        # 2012 per una centralina che misura dal 2017 e' traffico buttato.
        da = _inizio_utile(stazioni, config.ERA5_START)
        if not da:
            continue
        _a, have_b, _n = store.archive_span(point)
        cursor = da
        if have_b and have_b[:10] >= da:
            cursor = day_shift(have_b[:10], 1)
        got = 0
        completo = True
        while cursor <= end_day:
            stop = min(day_shift(cursor, chunk_days - 1), end_day)
            try:
                rows = openmeteo.fetch_era5(lat, lon, cursor, stop)
                store.save_archive(point, rows)
                got += len(rows)
            except FetchError as e:
                _note("warn", "era5", "%s %s: %s" % (point, cursor, str(e)[:100]))
                completo = False
                break
            cursor = day_shift(stop, 1)
        if completo:
            # Il giro e' arrivato in fondo: da qui in avanti questo punto non
            # e' "scoperto" nemmeno se l'archivio non ha quei giorni, perche'
            # riprovare non li farebbe comparire.
            store.meta_set("predittori_tentati_%s" % point, da)
        if got:
            out.append("%s: %d ore ERA5" % (point, got))

    for place, (lat, lon, _side) in config.CONTEXT_POINTS.items():
        row = store.connect().execute(
            "SELECT MAX(valid) v FROM ctx_hour WHERE kind='era5' AND place=?",
            (place,)).fetchone()
        cursor = start_day
        if row and row["v"] and row["v"][:10] >= start_day:
            cursor = day_shift(row["v"][:10], 1)
        while cursor <= end_day:
            stop = min(day_shift(cursor, chunk_days - 1), end_day)
            try:
                rows = openmeteo.fetch_era5_context(lat, lon, cursor, stop)
                store.save_context(place, "era5", rows)
            except FetchError as e:
                _note("warn", "era5-contesto", "%s: %s" % (place, str(e)[:100]))
                break
            cursor = day_shift(stop, 1)
    return out


def backfill_lead_features(leads=None, chunk_days=180):
    """Predittori COME ERANO all'emissione, una copia per scadenza.

    Senza questo archivio non esiste alcun modo onesto di dire quanto vale la
    previsione a D+3: l'archivio ordinario (historical-forecast) contiene le
    prime ore di ogni run, cioe' una scadenza di poche ore, e un modello
    addestrato su quello e applicato a D+3 promette un'accuratezza che a D+3
    non ha. Qui ogni scadenza ha il proprio archivio, i propri campioni e le
    proprie metriche.

    L'archivio delle run precedenti parte dal 2024, quindi le scadenze lunghe
    avranno sempre meno giornate delle corte. E' un limite dei dati, non un
    difetto da nascondere: dove le giornate non bastano, la scadenza resta
    dichiarata non validata.
    """
    leads = leads or config.PREV_RUN_LEADS
    today = _dt.date.today()
    end_day = (today - _dt.timedelta(days=1)).isoformat()

    starts = []
    for station in {s["station"] for s in config.SPOTS.values()}:
        a, _b = _obs_span(station)
        if a:
            starts.append(a)
    if not starts:
        return ["nessuna osservazione: niente da allineare"]
    start_day = max(min(starts), config.PREV_RUN_START)

    out = []
    for lead in leads:
        source = "lead%d" % lead
        for _key, (lat, lon) in _points().items():
            point = store.point_key(lat, lon, source)
            _a, have_b, _n = store.archive_span(point)
            cursor = start_day
            if have_b and have_b[:10] >= start_day:
                cursor = day_shift(have_b[:10], 1)
            got = 0
            while cursor <= end_day:
                stop = min(day_shift(cursor, chunk_days - 1), end_day)
                try:
                    rows = openmeteo.fetch_lead_features(lat, lon, lead, cursor, stop)
                    store.save_archive(point, rows)
                    got += len(rows)
                except FetchError as e:
                    _note("warn", source, "%s %s: %s" % (point, cursor, str(e)[:100]))
                    break
                cursor = day_shift(stop, 1)
            if got:
                out.append("%s %s: %d ore" % (source, point, got))

        for place, (lat, lon, _side) in config.CONTEXT_POINTS.items():
            row = store.connect().execute(
                "SELECT MAX(valid) v FROM ctx_hour WHERE kind=? AND place=?",
                (source, place)).fetchone()
            cursor = start_day
            if row and row["v"] and row["v"][:10] >= start_day:
                cursor = day_shift(row["v"][:10], 1)
            while cursor <= end_day:
                stop = min(day_shift(cursor, chunk_days - 1), end_day)
                try:
                    rows = openmeteo.fetch_lead_features(
                        lat, lon, lead, cursor, stop, context=True)
                    store.save_context(place, source, rows)
                except FetchError as e:
                    _note("warn", source + "-contesto", "%s: %s" % (place, str(e)[:100]))
                    break
                cursor = day_shift(stop, 1)
    return out


def backfill_archive_features(max_years=5, chunk_days=180):
    """Scarica i predittori storici (historical-forecast, best_match).

    Si ferma al periodo effettivamente coperto dalle osservazioni: scaricare
    predittori per giorni senza bersaglio e' solo traffico sprecato.
    """
    today = _dt.date.today()
    horizon = (today - _dt.timedelta(days=int(365.25 * max_years))).isoformat()

    punti = _punti_stazioni()
    inizi = [g for g in (_inizio_utile(st, horizon)
                         for _la, _lo, st in punti.values()) if g]
    if not inizi:
        return ["nessuna osservazione: niente da allineare"]
    start_day = min(inizi)      # per il contesto, che e' comune a tutti i punti
    end_day = (today - _dt.timedelta(days=1)).isoformat()

    out = []
    for point, (lat, lon, stazioni) in punti.items():
        da = _inizio_utile(stazioni, horizon)
        if not da:
            continue
        have_a, have_b, _n = store.archive_span(point)
        cursor = da
        if have_b and have_b[:10] >= da:
            cursor = day_shift(have_b[:10], 1)
        completo = True
        while cursor <= end_day:
            stop = min(day_shift(cursor, chunk_days - 1), end_day)
            try:
                rows = openmeteo.fetch_archive(lat, lon, cursor, stop)
                store.save_archive(point, rows)
            except FetchError as e:
                _note("warn", "archivio-feature", "%s %s: %s" % (point, cursor, str(e)[:100]))
                completo = False
                break
            cursor = day_shift(stop, 1)
        if completo:
            store.meta_set("predittori_tentati_%s" % point, da)
        out.append("%s fino a %s" % (point, cursor))

    for place, (lat, lon, _side) in config.CONTEXT_POINTS.items():
        have_a, have_b, _n = store.context_span("arch")
        cursor = start_day
        row = store.connect().execute(
            "SELECT MAX(valid) v FROM ctx_hour WHERE kind='arch' AND place=?",
            (place,)).fetchone()
        if row and row["v"] and row["v"][:10] >= start_day:
            cursor = day_shift(row["v"][:10], 1)
        while cursor <= end_day:
            stop = min(day_shift(cursor, chunk_days - 1), end_day)
            try:
                rows = openmeteo.fetch_archive_context(lat, lon, cursor, stop)
                store.save_context(place, "arch", rows)
            except FetchError as e:
                _note("warn", "archivio-contesto", "%s: %s" % (place, str(e)[:100]))
                break
            cursor = day_shift(stop, 1)
    return out


# ==========================================================================
# Costruzione del campione di addestramento
# ==========================================================================

_TARGET_CACHE = {}

# In quale finestra si misura il bersaglio. "utile" e' il prodotto: la
# finestra in cui si puo' davvero essere in acqua, la stessa del riquadro.
# "regime" e' come si faceva prima, e resta SOLO come riferimento per il
# confronto (--confronta-bersaglio): un cambio di definizione del bersaglio
# si dichiara e si misura, non si fa in silenzio.
BERSAGLIO = "utile"


def _targets(spot_name, use_cache=True):
    """Bersaglio giornaliero osservato: {giorno: (valore, instaurato)}."""
    chiave = (spot_name, BERSAGLIO)
    if use_cache:
        hit = _TARGET_CACHE.get(chiave)
        if hit and time.time() - hit[0] < PRODUCT_TTL_S:
            return hit[1]
    result = _compute_targets(spot_name)
    _TARGET_CACHE[chiave] = (time.time(), result)
    return result


def _compute_targets(spot_name, finestra=None):
    spot = config.SPOTS[spot_name]
    finestra = finestra or BERSAGLIO
    out = {}

    if spot["target"] == "daily_gust":
        for row in store.obs_days(spot["station"]):
            g = row["gust_max"]
            if g is None:
                continue
            out[row["day"]] = (g, g >= spot["min_kn"], None, None)
        return out

    # Il bersaglio si misura nella finestra UTILE del giorno, non in quella
    # del regime. Sono la stessa cosa per l'Ora e sono molto diverse per il
    # Peler: il regime comincia alle 04:00, la finestra utile alle 07:20
    # d'estate e alle 08 d'inverno. Il riquadro giudica la finestra utile;
    # se il modello imparasse sull'altra, la probabilita' risponderebbe a
    # "entra fra le 4 e le 10?" mentre il verdetto pone "si naviga dalle
    # 07:20?". Misurato sulle 4.995 giornate della centralina: entrato nel
    # regime ma non nell'utile 330 su 3.015, l'11%, e d'inverno una su sei.
    # In quelle giornate il modello imparava "si'" e la scheda diceva "no".
    #
    # E' lo stesso difetto dell'ancora (istantaneo contro orario), la seconda
    # volta: il numero che il modello prevede e quello che la scheda mostra
    # devono essere la stessa grandezza nella stessa finestra. La finestra
    # utile ha UNA definizione, in orari.finestra_utile_del_giorno, e qui la
    # si chiama: non se ne scrive una seconda.
    #
    # Un'ora della serie oraria entra se sta per almeno mezz'ora dentro la
    # finestra utile: mezz'ora e' la persistenza, cioe' la durata minima che
    # conta come vento, ed e' la stessa mezz'ora di tutto il resto.
    from . import orari as _orari
    h0, h1 = spot["window"]
    _ore_utili = {}

    def ore_utili(day):
        if day not in _ore_utili:
            try:
                inizio, fine = _orari.finestra_utile_del_giorno(spot_name, day)
            except (KeyError, ValueError, TypeError):
                inizio, fine = h0 * 60.0, (h1 + 1) * 60.0
            if finestra == "regime":            # solo per il confronto
                inizio, fine = h0 * 60.0, (h1 + 1) * 60.0
            ore = [h for h in range(h0, h1 + 1)
                   if min(fine, (h + 1) * 60.0) - max(inizio, h * 60.0)
                   >= _orari.PERSISTENZA_MIN]
            _ore_utili[day] = ore
        return _ore_utili[day]

    by_day = {}
    for row in store.obs_hours(spot["station"]):
        dt = parse_dt_any(row["hour"])
        if dt is None or row["wind_mean"] is None:
            continue
        day = local_day(dt)
        if local_hour(dt) not in ore_utili(day):
            continue
        # Un'ora ricostruita da pochissimi campioni non e' una media oraria.
        if (row["n_samples"] or 0) < 2:
            continue
        by_day.setdefault(day, []).append(
            (local_hour(dt), row["wind_mean"], row["dir_deg"]))

    for day, vals in by_day.items():
        # La copertura richiesta segue la finestra del giorno: a dicembre la
        # finestra utile del Peler ha tre ore, non sette.
        need = max(2, int(config.MIN_WINDOW_COVERAGE * len(ore_utili(day))))
        if len(vals) < need:
            continue                 # copertura insufficiente: giorno ESCLUSO,
                                     # non messo a zero. Dato mancante non e'
                                     # assenza di vento.
        vals.sort()
        peak_hour, peak, peak_dir = max(vals, key=lambda x: x[1])

        # "Instaurato" richiede la direzione giusta, non solo l'intensita'.
        # Quindici nodi da sud alle otto del mattino a Torbole sono vento,
        # ma non sono il Peler: per il modello del Peler quel giorno e' un
        # NEGATIVO corretto, non un positivo.
        #
        # Il confronto si fa contro l'asse OSSERVATO, non contro quello
        # geometrico. Sono trenta gradi di differenza sul Peler di Torbole
        # (vedi config.OBS_AXIS), e giudicare una direzione misurata dalla
        # centralina con un riferimento preso dalla mappa significa spostare
        # il bersaglio di trenta gradi rispetto a cio' che la centralina vede.
        axis_obs = spot.get("axis_obs", spot["axis"])
        in_sector = (peak_dir is None or
                     angle_diff(peak_dir, axis_obs) <= config.REGIME_SECTOR_DEG)
        established = peak >= spot["min_kn"] and in_sector

        onset = next((h for h, v, d in vals
                      if v >= spot["min_kn"]
                      and (d is None or angle_diff(d, axis_obs)
                           <= config.REGIME_SECTOR_DEG)), None)
        out[day] = (peak, established, float(peak_hour),
                    float(onset) if onset is not None else None)
    return out


def source_lead(source):
    """Scadenza in giorni implicata da una sorgente di predittori.

    "lead3" -> 3. "forecast" ed "era5" non hanno una scadenza dichiarata: le
    prime ore di ogni run e la rianalisi descrivono lo stato quasi-attuale,
    quindi valgono come scadenza zero. Dichiararlo qui, in un posto solo,
    evita che la stessa assunzione venga fatta in modo diverso altrove.
    """
    if source.startswith("lead"):
        try:
            return int(source[4:])
        except ValueError:
            return 0
    return 0


def _ctx_kind(source):
    if source == "forecast":
        return "arch"
    return source                      # "era5", "lead1".. usano il proprio


def build_samples(spot_name, source="forecast"):
    """Coppie (predittori storici, bersaglio osservato) pronte per l'addestramento.

    `source` sceglie l'archivio dei predittori:
      "forecast"  archivio delle previsioni, con i livelli isobarici, ~5 anni
      "era5"      rianalisi di sola superficie, ma dal 2012
      "leadN"     previsione come era N giorni prima del bersaglio, dal 2024

    La memoria (`persist_obs`) viene sempre presa all'eta' che avrebbe avuto
    all'emissione: per la scadenza N l'ultimo giorno interamente osservato e'
    N+1 giorni prima del bersaglio. Lo stesso conto lo fa `forecast_days` in
    esercizio, ed e' la ragione per cui le due strade ora combaciano.
    """
    spot = config.SPOTS[spot_name]
    point = store.point_key(spot["lat"], spot["lon"], source)
    targets = _targets(spot_name)
    if not targets:
        return []
    lead = source_lead(source)
    age = lead + 1

    days = sorted(targets)
    lo, hi = days[0], days[-1]
    rows = store.archive_rows(point, day_shift(lo, -2) + "T00:00:00Z",
                              day_shift(hi, 1) + "T23:00:00Z")
    hours = {r["valid"]: {k: r[k] for k in store.FC_COLS} for r in rows}
    if not hours:
        return []
    ctx = store.context_map(_ctx_kind(source),
                            day_shift(lo, -2) + "T00:00:00Z",
                            day_shift(hi, 1) + "T23:00:00Z")

    samples = []
    for day in days:
        prev = targets.get(day_shift(day, -age))
        feats = F.daily_features(spot_name, day, hours, ctx,
                                 persist=prev[0] if prev else None,
                                 persist_age=age)
        if feats is None:
            continue
        peak, established, peak_hour, onset = targets[day]
        samples.append({"day": day, "features": feats, "peak": peak,
                        "established": established, "lead": lead,
                        "peak_hour": peak_hour, "onset_hour": onset})
    return samples


def samples_by_lead(spot_name):
    """{scadenza: campioni}. La scadenza 0 viene dall'archivio ordinario."""
    out = {}
    fc = build_samples(spot_name, "forecast")
    if fc:
        out[0] = fc
    for lead in config.PREV_RUN_LEADS:
        got = build_samples(spot_name, "lead%d" % lead)
        if got:
            out[lead] = got
    return out


def train_bands(spot_name, tier="surface", by_lead=None, bands=None):
    """Un modello per fascia di scadenza, ognuno validato a se'.

    Il livello e' "surface" perche' l'archivio delle run precedenti non espone
    i livelli isobarici: mettere insieme fasce addestrate su vettori diversi
    renderebbe il confronto fra scadenze privo di significato, ed e' proprio il
    confronto fra scadenze la cosa da misurare.
    """
    by_lead = by_lead if by_lead is not None else samples_by_lead(spot_name)
    report = []
    for name, (a, b) in (bands or config.LEAD_BANDS):
        pooled = []
        for lead in range(a, b + 1):
            pooled.extend(by_lead.get(lead) or [])
        if len(pooled) < 120:
            report.append({"band": name, "n": len(pooled),
                           "leads": [l for l in range(a, b + 1) if by_lead.get(l)],
                           "status": "dati insufficienti"})
            continue
        r = V.fit_band(spot_name, pooled, tier, name)
        if not r:
            report.append({"band": name, "n": len(pooled),
                           "status": "periodo troppo corto per il forward chaining"})
            continue
        metrics = {k: v for k, v in r.items() if k != "payload"}
        # Nomi che model.predict conosce gia', per non avere due vocabolari.
        # "usable" qui vuol dire esattamente "ha superato le porte a QUESTA
        # fascia": nessuna promozione ereditata da un'altra scadenza.
        metrics.update({
            "lead_band": name,
            # Una porta per stadio: "usable" e' l'intensita', "usable_occurrence"
            # la probabilita'. Si promuovono separatamente (vedi model.predict).
            "usable": r["gain_int"]["significativo"],
            "usable_occurrence": r["gain_prob"]["significativo"],
            "base_rate": (r["prob"] or {}).get("base_rate"),
            "brier": (r["prob"] or {}).get("brier"),
            "brier_base": (r["prob"] or {}).get("brier_base"),
            "mae": (r["intensity"] or {}).get("mae"),
            "mae_base": (r["intensity"] or {}).get("mae_raw"),
        })
        store.save_learned(spot_name, "daily@" + name, tier, r["n"],
                           r["payload"], metrics)
        report.append({"band": name, "n": r["n"], "n_test": r["n_test"],
                       "leads": r["leads"], "status": "ok",
                       "validata": r["validated"],
                       "brier": (r["prob"] or {}).get("brier"),
                       "brier_base": (r["prob"] or {}).get("brier_base"),
                       "mae": (r["intensity"] or {}).get("mae"),
                       "mae_raw": (r["intensity"] or {}).get("mae_raw")})
    return report


def learned_by_band(spot_name):
    """{fascia: modello appreso}. Assente = quella fascia non e' validata."""
    out = {}
    for name, _rng in config.LEAD_BANDS:
        got = store.load_learned(spot_name, "daily@" + name)
        if got:
            out[name] = got
    return out


# Quante giornate servono perche' una climatologia osservata sia una misura e
# non un aneddoto. E' la stessa soglia che il modello chiede allo stadio B.
CLIM_MIN_GIORNATE = 40


def climatologia_osservata(spot_name):
    """Quanto tira di solito, e quanto spesso entra, dalle sole OSSERVAZIONI.

    Non serve nessun predittore: si legge il bersaglio. E' cio' che si
    pubblica quando un modello non c'e' - una localita' appena aggiunta, i cui
    predittori storici stanno ancora arrivando - al posto del prior fisico,
    che e' il vento grezzo d'ensemble e sul Garda legge sistematicamente meno
    del vero. Misurato a Campione sulle 55.830 ore in comune con Malcesine:
    la mediana del picco dell'Ora e' 9,9 kn (10,2 a settembre), e il modello
    nudo in pagina ne dava 5.

    Le due grandezze hanno gli stessi nomi che avrebbero se un modello ci
    fosse - base_rate e clim_median - perche' chi le usa e' lo stesso codice:
    model.predict le sceglie gia' quando il modello non batte la climatologia.
    Qui il caso e' solo piu' estremo: il modello non c'e' affatto.
    """
    t = _targets(spot_name)
    if len(t) < CLIM_MIN_GIORNATE:
        return None
    picchi = [v[0] for v in t.values() if v[1] and v[0] is not None]
    if len(picchi) < 5:
        # Entra troppo poche volte per dire "quanto": si dichiara solo il "se".
        picchi = []
    giorni = sorted(t)
    return {
        "source": "climatologia osservata",
        "tier": None,
        "solo_climatologia": True,
        "n": len(t),
        "n_eval": len(t),
        "n_established": sum(1 for v in t.values() if v[1]),
        "base_rate": sum(1 for v in t.values() if v[1]) / float(len(t)),
        "clim_median": median(picchi) if picchi else None,
        "days_from": giorni[0], "days_to": giorni[-1],
    }


def _salva_climatologia(spot_name, motivo):
    """Dove non c'e' un modello, la climatologia misurata e' la previsione.

    Non sovrascrive un modello vero: se in archivio c'e' gia' qualcosa di
    appreso, quello resta - un giro di addestramento andato male non deve
    declassare un modello che funzionava.
    """
    gia = store.load_learned(spot_name, "daily")
    if gia and not (gia.get("metrics") or {}).get("solo_climatologia"):
        return None
    m = climatologia_osservata(spot_name)
    if not m:
        return None
    m["status"] = motivo
    store.save_learned(spot_name, "daily", None, m["n"], {}, m)
    return m


def train_all():
    report = []
    for spot_name in config.SPOTS:
        sources = {}
        for src in ("forecast", "era5"):
            got = build_samples(spot_name, src)
            if got:
                sources[src] = got
        fc = sources.get("forecast") or []
        if len(fc) < 30:
            motivo = ("pochi dati: %d giornate allineate fra predittori e "
                      "osservazioni" % len(fc))
            clim = _salva_climatologia(spot_name, motivo)
            report.append({"spot": spot_name, "n": len(fc), "status": "pochi dati",
                           "climatologia": (clim or {}).get("clim_median")})
            continue

        chosen, candidates = M.train(spot_name, sources)
        if chosen is None:
            clim = _salva_climatologia(spot_name, "nessun candidato adottabile")
            report.append({"spot": spot_name, "n": len(fc),
                           "status": "nessun candidato adottabile",
                           "climatologia": (clim or {}).get("clim_median")})
            continue
        metrics = M.metrics_of(chosen)
        learned = {"payload": M.serialize(chosen), "metrics": metrics}
        cov, ncov = M.verify_intervals(fc, learned)
        metrics["coverage"] = cov
        metrics["coverage_n"] = ncov
        metrics["candidates"] = [
            {"source": c.get("source"), "tier": c["tier"], "n": c["n"],
             "brier": c["brier"], "mae": c["mae"], "usable": c["usable"]}
            for c in candidates]
        store.save_learned(spot_name, "daily", chosen["tier"], chosen["n"],
                           M.serialize(chosen), metrics)

        # Terzo stadio: l'orario. Si addestra sul set piu' ampio disponibile
        # che abbia i livelli isobarici, perche' il livello "timing" li usa.
        line = {"spot": spot_name, "n": chosen["n"], "status": "ok",
                "source": chosen.get("source"), "tier": chosen["tier"],
                "usable": chosen["usable"], "mae": chosen["mae"],
                "brier": chosen["brier"]}
        if config.SPOTS[spot_name]["target"] == "hourly":
            t = M.train_timing(fc)
            if t:
                store.save_learned(spot_name, "timing", t["tier"], t["n"],
                                   t["payload"],
                                   {k: v for k, v in t.items() if k != "payload"})
                line["timing_min"] = t["mae_minutes"]
                line["timing_usable"] = t["usable"]

        # Un modello per fascia di scadenza, dove l'archivio per-lead lo
        # consente. Le fasce senza dati restano senza modello, e la previsione
        # a quelle scadenze esce dichiarata non validata.
        try:
            line["fasce"] = train_bands(spot_name)
        except Exception as e:                       # pragma: no cover
            _note("warn", "fasce", "%s: %s" % (spot_name, str(e)[:140]))
            line["fasce"] = [{"status": "errore: %s" % str(e)[:80]}]
        report.append(line)
    store.meta_set("last_training", iso_utc(utc_now()))
    return report


def verify_all(days=420):
    """Misura la skill di ogni modello contro le osservazioni."""
    today = _dt.date.today()
    end = (today - _dt.timedelta(days=2)).isoformat()
    start = (today - _dt.timedelta(days=days)).isoformat()
    done = 0
    for spot_name, spot in config.SPOTS.items():
        if spot["target"] != "hourly":
            continue
        observed = verify.observed_daily_peaks(spot_name)
        if len(observed) < verify.MIN_DAYS_FOR_SKILL:
            continue
        for model_name in config.MODELS:
            for lead in config.VERIFY_LEADS:
                try:
                    stats = verify.verify_model(
                        spot_name, model_name, lead, openmeteo.fetch_previous_run,
                        start, end, observed)
                except FetchError as e:
                    _note("warn", "verifica/%s" % model_name, str(e)[:120])
                    continue
                if stats:
                    store.save_skill(spot_name, model_name, lead, stats)
                    done += 1
    store.meta_set("last_verification", iso_utc(utc_now()))
    return done


# ==========================================================================
# Ensemble
# ==========================================================================

def ensemble_hours(spot_name):
    """Media pesata dei modelli, ora per ora, piu' la dispersione.

    I pesi vengono dalla verifica contro centralina quando esiste, altrimenti
    da un prior sulla risoluzione. Ogni famiglia di modelli entra una volta
    sola: contare ICON-EU, ICON Global e ICON Seamless come tre pareri
    indipendenti restringe artificialmente la dispersione e fa sembrare la
    previsione piu' sicura di quanto sia.
    """
    spot = config.SPOTS[spot_name]
    point = store.point_key(spot["lat"], spot["lon"])
    runs = {m: r for m, r in store.latest_runs(point).items() if m in config.MODELS}
    if not runs:
        return {}, {}, 0, "nessuna"

    newest = max(runs.values())
    fresh = {m: r for m, r in runs.items()
             if (parse_dt_any(newest) - parse_dt_any(r)).total_seconds() <= 6 * 3600}
    if not fresh:
        fresh = runs

    today = local_day(utc_now())
    per_model = {}
    for m, run in fresh.items():
        per_model[m] = {r["valid"]: r for r in store.forecast_rows(point, m, run)}

    weights_cache = {}

    def weights_for(lead):
        if lead not in weights_cache:
            weights_cache[lead] = verify.compute_weights(spot_name, clamp(lead, 1, 3))
        return weights_cache[lead]

    all_valid = sorted({v for rows in per_model.values() for v in rows})
    out, spread = {}, {}
    origin = "prior"
    for valid in all_valid:
        dt = parse_dt_any(valid)
        lead = max(0, (_dt.date.fromisoformat(local_day(dt))
                       - _dt.date.fromisoformat(today)).days)
        wmap, origin = weights_for(lead)

        members = []
        for m, rows in per_model.items():
            r = rows.get(valid)
            if not r or r["w10"] is None:
                continue
            bias = verify.model_bias(spot_name, m, int(clamp(lead, 1, 3)))
            members.append((m, wmap.get(m, 0.0), r, bias))
        if not members:
            continue
        total = sum(w for _m, w, _r, _b in members) or 1.0

        agg = {}
        for col in store.FC_COLS:
            if col in ("d10", "d925", "d850", "d700"):
                continue
            num = den = 0.0
            for _m, w, r, bias in members:
                v = r[col]
                if v is None:
                    continue
                if col == "w10":
                    v = max(0.0, v - bias)
                elif col == "g10":
                    # La correzione di bias va applicata a ENTRAMBE le
                    # grandezze, e in modo relativo. Correggendo solo la media
                    # si rompe il rapporto raffica/media del modello: dove i
                    # modelli sottostimano il Peler il bias e' negativo, la
                    # media corretta sale SOPRA la raffica grezza, e piu' a
                    # valle il rapporto viene stretto a 1,0 - cioe' la curva
                    # della raffica si appiattisce su quella del vento medio e
                    # sparisce dal grafico. Il livello si corregge, la
                    # turbolenza del modello no: si scala.
                    w10 = r["w10"]
                    if w10 is not None and w10 > 0.5:
                        v = v * max(0.0, w10 - bias) / w10
                num += w * v
                den += w
            agg[col] = (num / den) if den > 0 else None

        for dcol, scol in (("d10", "w10"), ("d925", "w925"),
                           ("d850", "w850"), ("d700", "w700")):
            pairs = [(r[scol] or 1.0, r[dcol]) for _m, _w, r, _b in members
                     if r[dcol] is not None]
            agg[dcol] = vector_mean_direction(pairs)[0]

        out[valid] = agg
        vals = [max(0.0, r["w10"] - b) for _m, _w, r, b in members if r["w10"] is not None]
        spread[valid] = pstdev(vals, 0.0)

    return out, spread, len(per_model), origin


# ==========================================================================
# Prodotto finale
# ==========================================================================

GRADES = (
    (22, "ECCEZIONALE"),
    (18, "MOLTO BUONO"),
    (14, "BUONO"),
    (11, "SI PLANA A TRATTI"),
    (8, "MARGINALE"),
    (0, "TROPPO POCO"),
)


def grade(speed, prob=None):
    """Giudizio sintetico: unisce quanto tira e quanto e' probabile che tiri.

    Tenere separati i due numeri porta a schede incoerenti del tipo "90% di
    probabilita'" accanto a "6 nodi". Il giudizio deve dire una cosa sola.
    """
    label = GRADES[-1][1]
    for threshold, name in GRADES:
        if speed >= threshold:
            label = name
            break
    if prob is None:
        return label
    if prob < 0.25:
        return "IMPROBABILE"
    if prob < 0.45:
        return label + " · INCERTO"
    return label


def last_observed_peak(spot_name, today=None):
    """Ultimo picco osservato con la finestra GIA' CHIUSA, e la sua data.

    E' l'unica memoria che un utente possiede al mattino: il giorno di ieri.
    Vale identica per tutte le scadenze dell'orizzonte; cio' che cambia con la
    scadenza e' solo la sua eta'. Si tollera un buco di qualche giorno
    (centralina muta) risalendo indietro, perche' un ricordo di tre giorni
    dichiarato tale e' meglio di uno zero.
    """
    targets = _targets(spot_name)
    today = today or local_day(utc_now())
    for back in range(1, 5):
        day = day_shift(today, -back)
        hit = targets.get(day)
        if hit:
            return hit[0], day
    return None, None


def forecast_days(spot_name, horizon=None):
    """Previsione giorno per giorno per uno spot-regime."""
    horizon = horizon or config.MAX_LEAD_DAYS
    hours, spread, nmodels, weight_origin = ensemble_hours(spot_name)
    if not hours:
        return []

    ctx = store.context_map("live")
    learned = store.load_learned(spot_name, "daily")
    by_band = learned_by_band(spot_name)
    timing = store.load_learned(spot_name, "timing")
    today = local_day(utc_now())
    mem_peak, mem_day = last_observed_peak(spot_name, today)

    spot = config.SPOTS[spot_name]
    days = sorted({local_day(parse_dt_any(v)) for v in hours})
    out = []
    for day in days:
        if day < today:
            continue
        lead = (_dt.date.fromisoformat(day) - _dt.date.fromisoformat(today)).days
        if lead > horizon:
            continue
        # La memoria e' la stessa per tutto l'orizzonte (l'ultimo giorno
        # osservato), quello che cambia e' quanto e' vecchia rispetto al
        # bersaglio. Esattamente il conto che fa build_samples.
        age = (_dt.date.fromisoformat(day)
               - _dt.date.fromisoformat(mem_day)).days if mem_day else lead + 1
        feats = F.daily_features(spot_name, day, hours, ctx,
                                 persist=mem_peak, persist_age=age)
        if feats is None:
            continue

        win_keys = [k for k in F.window_hours(day, *config.SPOTS[spot_name]["window"])
                    if k in hours]
        sp = mean([spread.get(k) for k in win_keys])
        sp = 3.0 if sp is None else sp
        # Con pochi membri la dispersione non misura l'incertezza, misura solo
        # quanti modelli hanno risposto: non puo' valere come rassicurazione.
        if nmodels < 3:
            sp = max(sp, 4.0)
        win_pairs = [(hours[k].get("w10") or 0.0, hours[k].get("d10")) for k in win_keys]
        dir_pred, dir_const = vector_mean_direction(win_pairs)
        # Il modello di QUESTA fascia, se e' stato validato; altrimenti quello
        # generale, che pero' esce marcato come non validato a questa scadenza.
        band = config.band_for_lead(lead)
        use = by_band.get(band) or learned
        pred = M.predict(spot_name, feats, use, lead, sp, direction=dir_pred)

        peak_hour, peak_hour_src = M.predict_timing(
            feats, timing, day, fallback=feats.get("raw_peak_hour"))
        pred["peak_hour"] = peak_hour
        pred["peak_hour_source"] = peak_hour_src
        pred["peak_hour_mae_min"] = (timing or {}).get("metrics", {}).get("mae_minutes")

        # Affidabilita': non dalla scadenza, dalle misure fatte A QUESTA
        # scadenza su QUESTO spot. Se la fascia non e' stata misurata,
        # metrics_lead resta None e l'etichetta scende a "outlook" da se'.
        per_lead = ((use or {}).get("metrics") or {}).get("per_lead") or {}
        metrics_lead = per_lead.get(lead) or per_lead.get(str(lead))
        off = angle_diff(dir_pred, spot["axis"]) if dir_pred is not None else None
        pred["affidabilita"] = CONF.assess(
            spot_name, lead, metrics_lead, spread_kn=sp,
            dir_penalty=pred.get("dir_penalty"), dir_offset=off,
            ambiguo=bool(off is not None
                         and config.REGIME_SECTOR_DEG - 15 <= off <= config.REGIME_SECTOR_DEG + 15))

        shape = F.hourly_shape(spot_name, day, hours)
        profile = []
        for key, rel in shape:
            dt = parse_dt_any(key)
            value = pred["speed"] * rel
            profile.append({
                "hour_local": local_hour(dt),
                "key": key,
                "wind": value,
                # Lo stesso rapporto del profilo della giornata, dallo stesso
                # posto: era una seconda copia del g10/w10 del modello, con
                # un limite diverso (2,2 invece di 2,1), e due raffiche per
                # la stessa ora.
                "gust": value * rapporto_raffica(spot_name, value),
                "spread": spread.get(key) if spread.get(key) is not None else 0.0,
            })

        in_sector = (dir_pred is None or
                     angle_diff(dir_pred, spot["axis"]) <= config.REGIME_SECTOR_DEG)

        # Se il vento previsto NON viene dal settore del regime, la previsione
        # del regime non e' la risposta giusta: il modello e' addestrato sui
        # giorni in cui quel regime c'era. Si dichiara l'altro vento per quello
        # che e', con il valore grezzo dei modelli e senza correzione appresa.
        other = None
        if not in_sector:
            raw = feats.get("w10_max") or feats.get("w10_win") or 0.0
            other = {
                "speed": raw,
                "dir": dir_pred,
                "steady": dir_const,
                "usable": raw >= spot["planing_kn"] * 0.8,
                "along_lake": angle_diff(dir_pred, config.LAKE_AXIS_ORA) <= 55
                or angle_diff(dir_pred, config.LAKE_AXIS_PELER) <= 55,
            }

        best = _best_window(profile, config.SPOTS[spot_name])
        out.append({
            "spot": spot_name,
            "day": day,
            "lead": lead,
            "prob": pred["prob"],
            "speed": pred["speed"],
            "lo": pred["lo"],
            "hi": pred["hi"],
            "source": pred["source"],
            "source_prob": pred["source_prob"],
            "source_int": pred["source_int"],
            "band_source": pred["band_source"],
            "lead_band": pred["lead_band"],
            "validata": pred["validata"],
            "validata_prob": pred["validata_prob"],
            "validata_int": pred["validata_int"],
            "affidabilita": pred["affidabilita"],
            "tier": pred["tier"],
            "mae": pred["mae"],
            "brier": pred["brier"],
            "brier_base": pred["brier_base"],
            "n_train": pred["n"],
            "dir": dir_pred,
            "dir_steady": dir_const,
            "in_sector": in_sector,
            "other_wind": other,
            "peak_hour": pred["peak_hour"],
            "peak_hour_source": pred["peak_hour_source"],
            "peak_hour_mae_min": pred["peak_hour_mae_min"],
            "spread": sp,
            "n_models": nmodels,
            "weights": weight_origin,
            "grade": grade(pred["speed"], pred["prob"]),
            "profile": profile,
            "window": best,
            "features": feats,
        })
    return out


def _best_window(profile, spot):
    """Fascia oraria contigua con il vento piu' utilizzabile."""
    usable = [p for p in profile if spot["window"][0] <= p["hour_local"] <= spot["window"][1]]
    if not usable:
        return None
    peak = max(usable, key=lambda p: p["wind"])
    threshold = max(spot["min_kn"] * 0.85, peak["wind"] * 0.75)
    runs, cur = [], []
    for p in usable:
        if p["wind"] >= threshold and (not cur or p["hour_local"] == cur[-1]["hour_local"] + 1):
            cur.append(p)
        elif p["wind"] >= threshold:
            if cur:
                runs.append(cur)
            cur = [p]
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    if not runs:
        runs = [[peak]]
    best = max(runs, key=lambda r: (peak in r, mean([p["wind"] for p in r]) * len(r)))

    # Minuti per interpolazione, non per invenzione. Il profilo e' orario, ma la
    # curva del vento e' continua: l'istante in cui attraversa la soglia si
    # stima interpolando fra l'ora sotto e l'ora sopra. Non aggiunge
    # informazione, rende leggibile quella che c'e' - la differenza fra "dalle
    # 8" e "dalle 8:40" e' dentro i dati orari, basta non buttarla via
    # arrotondando.
    #
    # Resta un secondo limite, molto piu' grande di questo: l'errore sull'ORA
    # del picco, che si misura in decine di minuti. Per questo i minuti si
    # mostrano solo dove lo stadio dell'orario e' stato validato a quella
    # scadenza; altrove si dichiara che l'orario e' incerto (vedi web.py). Un
    # 08:10 accanto a un'incertezza di due ore sarebbe precisione finta.
    byh = {p["hour_local"]: p["wind"] for p in usable}

    def cross(h, prev_h):
        """Minuto in cui la curva passa per `threshold` fra prev_h e h."""
        a, b = byh.get(prev_h), byh.get(h)
        if a is None or b is None or a == b:
            return h * 60.0
        t = clamp((threshold - a) / (b - a), 0.0, 1.0)
        return (prev_h + t) * 60.0

    h0, h1 = best[0]["hour_local"], best[-1]["hour_local"]
    start_min = cross(h0, h0 - 1) if (h0 - 1) in byh else h0 * 60.0
    end_min = cross(h1 + 1, h1) if (h1 + 1) in byh else (h1 + 1) * 60.0
    return {
        "from": h0,
        "to": h1 + 1,
        "from_min": start_min,
        "to_min": max(end_min, start_min + 20.0),
        "mean": mean([p["wind"] for p in best]),
        "peak": peak["wind"],
        "peak_hour": peak["hour_local"],
        "gust": max(p["gust"] for p in best),
    }


_PRODUCT_CACHE = {"at": 0.0, "value": None}
PRODUCT_TTL_S = 90


def full_product(force=False):
    """Previsione completa, con una breve cache.

    Ogni ricostruzione rilegge tutte le osservazioni orarie e ricalcola
    l'ensemble per cinque coppie spot/regime: senza cache un semplice
    aggiornamento di pagina rifarebbe tutto il lavoro.
    """
    now = time.time()
    if not force and _PRODUCT_CACHE["value"] is not None \
            and now - _PRODUCT_CACHE["at"] < PRODUCT_TTL_S:
        return _PRODUCT_CACHE["value"]
    value = {name: forecast_days(name) for name in config.SPOT_ORDER}
    _PRODUCT_CACHE.update({"at": now, "value": value})
    return value


def invalidate_product():
    _PRODUCT_CACHE["value"] = None


# ==========================================================================
# Cicli di aggiornamento
# ==========================================================================

def _age_minutes(key):
    v = store.meta_get(key)
    if not v:
        return 1e9
    dt = parse_dt_any(v)
    return 1e9 if dt is None else (utc_now() - dt).total_seconds() / 60.0


def update_cycle(force=False, deep=True):
    if not _LOCK.acquire(False):
        return False
    STATE.update({"running": True, "started": iso_utc(utc_now()),
                  "phase": "previsioni", "errors": []})
    try:
        update_forecasts()
        STATE["phase"] = "contesto"
        update_context()
        STATE["phase"] = "centraline"
        update_stations()

        if deep:
            STATE["phase"] = "archivio centraline"
            backfill_station_history(force=False)
            # Gli ultimi due mesi di Malcesine a ogni ciclo: recupera cio' che
            # la lettura istantanea non ha visto. Due richieste, idempotenti.
            try:
                n_intra = refresh_malcesine_intraday()
                if n_intra:
                    store.meta_set("last_malcesine_refresh", iso_utc(utc_now()))
            except Exception as e:                      # pragma: no cover
                _note("warn", "intraday/Malcesine", str(e)[:140])
            # I predittori si scaricano quando MANCANO, non quando scade un
            # orologio. La differenza si e' vista aggiungendo Campione: il
            # giorno dopo aveva 66.507 ore di osservazioni in archivio e
            # nessun modello, perche' l'orologio dei predittori era stato
            # rimesso a zero poche ore prima - e la pagina intanto mostrava
            # il vento grezzo d'ensemble, che sul Garda legge troppo poco.
            # L'orologio resta, per il seguito quotidiano; la copertura ha la
            # precedenza, e lo sposta solo un giro arrivato in fondo.
            STATE["phase"] = "predittori storici"
            if force or predittori_scoperti("forecast") or \
                    _age_minutes("last_archive_backfill") > 24 * 60:
                backfill_archive_features()
                if not predittori_scoperti("forecast"):
                    store.meta_set("last_archive_backfill", iso_utc(utc_now()))
            STATE["phase"] = "rianalisi ERA5"
            if force or predittori_scoperti("era5") or \
                    _age_minutes("last_era5_backfill") > 7 * 24 * 60:
                backfill_era5_features()
                if not predittori_scoperti("era5"):
                    store.meta_set("last_era5_backfill", iso_utc(utc_now()))
            STATE["phase"] = "predittori per scadenza"
            if force or _age_minutes("last_lead_backfill") > 24 * 60:
                backfill_lead_features()
                store.meta_set("last_lead_backfill", iso_utc(utc_now()))
            STATE["phase"] = "verifica modelli"
            if force or _age_minutes("last_verification") > 7 * 24 * 60:
                verify_all()
            STATE["phase"] = "addestramento"
            if force or _age_minutes("last_training") > 12 * 60:
                train_all()

        store.meta_set("last_update", iso_utc(utc_now()))
        invalidate_product()
        STATE["phase"] = "pronto"
        return True
    except Exception as e:                                   # pragma: no cover
        _note("error", "ciclo", "%s: %s" % (type(e).__name__, e))
        return False
    finally:
        STATE.update({"running": False, "finished": iso_utc(utc_now())})
        _LOCK.release()


def ensure_update(force=False):
    if force or _age_minutes("last_update") > config.UPDATE_INTERVAL_MIN:
        if not STATE["running"]:
            threading.Thread(target=update_cycle, args=(force, True), daemon=True).start()
            return True
    return False


def poller_loop():
    """Interroga le centraline di continuo finche' l'app e' aperta.

    Torbole ha una finestra scorrevole di 168 ore, quindi basta aprire l'app
    una volta a settimana per non perdere nulla. Malcesine espone solo
    l'istante corrente: li' ogni passaggio del poller e' un dato che
    altrimenti sarebbe perso per sempre.
    """
    while True:
        try:
            update_stations()
        except Exception as e:                               # pragma: no cover
            _note("warn", "poller", str(e)[:120])
        time.sleep(config.POLL_INTERVAL_MIN * 60)


# ==========================================================================
# Lettura in tempo reale e profilo di giornata
# ==========================================================================

def live_reading(station):
    """Ultimo campione disponibile dalla centralina.

    E' il numero che chi va in acqua guarda per primo: non una previsione,
    ma quanto sta tirando adesso. Viaggia con la sua eta', perche' un dato
    di quaranta minuti fa non e' "adesso".
    """
    righe = store.samples_recent(station, 1)
    row = righe[0] if righe else None
    if not row:
        return None
    dt = parse_dt_any(row["ts"])
    age = (utc_now() - dt).total_seconds() / 60.0 if dt else None
    # Molte stazioni pubblicano la raffica come massimo GIORNALIERO: se il
    # campione non ne ha una propria si preferisce non inventarla.
    return {
        "wind": row["wind_kn"], "gust": row["gust_kn"], "dir": row["dir_deg"],
        "ts": row["ts"], "age_min": age, "stale": (age is None or age > 45),
    }


def day_observed(place, day):
    """Cosa e' DAVVERO successo oggi, ora per ora, sullo stesso asse della previsione.

    Ritorna {"righe": [...], "raffica_fonte": ..., "ultima_ora": ...} dove ogni
    riga e' {"hour": ora locale, "wind": media oraria, "gust": raffica, "n":
    campioni}. Solo le ore che esistono: nessun buco riempito, nessuna ora
    futura inventata - il punto di questa serie e' proprio il confronto con la
    previsione, e una previsione confrontata con un dato interpolato non dice
    piu' niente.

    Sulla raffica c'e' una scelta da dichiarare, non da nascondere: si preferisce
    la RAFFICA RICORRENTE (mediana mobile a 30 minuti, la grandezza su cui si
    decide se si plana) e si ripiega sul massimo dell'ora solo dove la
    ricorrente non e' stimabile. Le due non sono la stessa cosa - il massimo e'
    sempre maggiore - quindi quale delle due si sta guardando viene detto.
    """
    station = next((config.SPOTS[s]["station"] for s in config.SPOTS
                    if config.SPOTS[s]["place"] == place), None)
    if not station:
        return {"righe": [], "raffica_fonte": None, "ultima_ora": None}

    righe = []
    for row in store.obs_hours(station, day_shift(day, -1) + "T00",
                               day_shift(day, 1) + "T23"):
        dt = parse_dt_any(row["hour"])
        if dt is None or local_day(dt) != day:
            continue
        if row["wind_mean"] is None and row["gust_rec"] is None \
                and row["gust_max"] is None:
            continue
        righe.append({"hour": local_hour(dt), "wind": row["wind_mean"],
                      "gust_rec": row["gust_rec"], "gust_max": row["gust_max"],
                      "n": row["n_samples"] or 0})
    righe.sort(key=lambda r: r["hour"])

    # Quale raffica: la ricorrente se c'e' su almeno meta' delle ore, altrimenti
    # il massimo dell'ora. Una serie che cambia definizione a meta' strada
    # sarebbe illeggibile, quindi la scelta e' unica per tutta la giornata.
    con_ric = sum(1 for r in righe if r["gust_rec"] is not None)
    usa_ric = righe and con_ric * 2 >= len(righe)
    for r in righe:
        r["gust"] = r["gust_rec"] if usa_ric else r["gust_max"]
    fonte = None
    if righe:
        fonte = "ricorrente 30'" if usa_ric else "massimo dell'ora"
    fini = campioni_fini(station, day)
    return {"righe": righe, "fini": fini,
            "raffica_fonte": fonte,
            # La raffica della curva fine puo' avere un'altra definizione da
            # quella oraria (ricorrente, o quella dichiarata dalla centralina):
            # si porta il nome, cosi' la pagina lo scrive.
            "raffica_fonte_fine": fini[0].get("raffica_fonte") if fini else None,
            "ultima_ora": righe[-1]["hour"] if righe else None}


def campioni_fini(station, day):
    """I campioni veri della giornata, alla cadenza a cui arrivano.

    Pubblica, non privata, perche' ha due clienti: la pagina costruita e il
    processo veloce che scrive live.json. La regola della fonte unica qui
    sotto e' costata un pomeriggio di diagnosi, e una seconda lettura dei
    campioni scritta altrove la perderebbe da capo.

    La serie oraria sopra resta, perche' e' quella su cui si confronta con la
    previsione e il confronto vive sull'asse orario. Ma DISEGNARE la misura
    per ore e' un'altra cosa, ed era un errore: la media oraria nasconde
    esattamente quello che la misura serve a mostrare.

    Misurato su 2.769 inversioni di regime in quattordici anni: il fondo del
    buco fra Peler e Ora sta al 25% del livello con i campioni veri e al 40%
    con le medie orarie - 2,6 kn contro 4,2 su un livello di 10,5 - e nel 25%
    dei giri in cui il buco c'e', la media oraria lo cancella del tutto.
    Disegnavamo la nostra stessa misura sei volte piu' grossolana di come la
    abbiamo, e la riga "misurato" diceva che il vento non era mai caduto.

    La raffica qui e' la RICORRENTE a trenta minuti, la stessa grandezza della
    serie oraria e della scheda: il massimo dei dieci minuti sarebbe piu' alto
    e piu' nervoso, e due righe con lo stesso nome e due definizioni sono il
    modo piu' sicuro di far leggere un numero per un altro.

    E UNA FONTE SOLA per giornata, che e' la stessa regola della raffica qui
    sopra applicata a un'altra dimensione. La stessa giornata arriva da due
    canali - il tempo reale e il recupero d'archivio - e non sono la stessa
    misura: possono avere cadenze diverse, finestre di media diverse,
    arrotondamenti diversi. Tenerne una per istante non basta, perche' il
    risultato e' una serie che cambia definizione a meta' strada: un tratto da
    un canale, un tratto dall'altro, e in mezzo un salto verticale che non e'
    vento - e' un cambio di fonte. Guardando la pagina vera si vedeva
    esattamente questo: gradini di dieci nodi in dieci minuti, "un gran
    casino".

    Quindi si sceglie il canale che copre meglio la giornata e si tiene solo
    quello. Preferire il piu' abbondante non e' arbitrario: e' il canale che
    la giornata ha davvero, e gli altri sono frammenti.
    """
    campioni = store.samples_since(station, day_shift(day, -1) + "T00:00:00Z")
    del_giorno = []
    for r in campioni:
        dt = parse_dt_any(r["ts"])
        if dt is None or local_day(dt) != day:
            continue
        del_giorno.append((iso_utc(dt), r))
    # Una fonte sola PER SERIE, non per giornata. Il vento dalla fonte piu'
    # abbondante che lo ha; la raffica dalla fonte piu' abbondante che HA la
    # raffica. A Malcesine sono due canali diversi - il vivo ogni otto minuti
    # senza raffica, l'intraday ogni trenta con la raffica - e tenere la
    # regola "una fonte per giornata" avrebbe voluto dire scegliere il vivo e
    # non disegnare mai la raffica. Ogni serie resta di una definizione sola.
    def piu_abbondante(campo):
        quante = {}
        for _k, r in del_giorno:
            if r.get(campo) is not None:
                f = r.get("source") or ""
                quante[f] = quante.get(f, 0) + 1
        if not quante:
            return None
        return max(sorted(quante), key=lambda f: quante[f])

    def serie(fonte, campo):
        per_ist = {}
        for k, r in del_giorno:
            if (r.get("source") or "") == fonte and r.get(campo) is not None:
                per_ist.setdefault(k, r)
        ordinati = sorted(per_ist.items())
        return ([local_minute_of_day(parse_dt_any(k)) for k, _r in ordinati],
                [float(_r.get(campo)) for _k, _r in ordinati])

    fonte_w = piu_abbondante("wind_kn")
    if fonte_w is None:
        return []
    # I minuti VERI, non l'ora arrotondata: con local_hour i sei campioni di
    # un'ora finivano tutti alla stessa ascissa, e la curva fra loro era un
    # salto verticale. Disegnavamo dei gradini e li chiamavamo vento.
    minuti, venti = serie(fonte_w, "wind_kn")
    # Abbastanza per essere una curva si misura in ARCO DI TEMPO, non in
    # numero di campioni: vedi util.serie_disegnabile. Con il conto fisso,
    # una centralina oraria non arrivava mai a dodici prima delle sedici.
    if not serie_disegnabile(minuti):
        return []

    # La raffica: la RICORRENTE a trenta minuti dove la cadenza la sostiene;
    # altrimenti la raffica che la centralina dichiara, col SUO nome
    # (raffica_fonte), perche' due righe con lo stesso nome e due
    # definizioni fanno leggere un numero per un altro. Con un dato ogni
    # trenta minuti la mediana sui trenta minuti non esiste, e prima si
    # preferiva non disegnare niente: ma "niente" e' peggio di una raffica
    # dichiarata per quello che e'.
    fonte_g = piu_abbondante("gust_kn")
    raff = {}
    raffica_fonte = None
    if fonte_g is not None:
        m_g, v_g = serie(fonte_g, "gust_kn")
        cad_g = sampling_cadence(m_g) if len(m_g) >= 2 else None
        if cad_g is not None and window_estimable(cad_g, FINESTRA_RICORRENTE_MIN):
            raff = {m: v for m, v in recurrent_gust(list(zip(m_g, v_g)),
                                                     cadence_min=cad_g)
                    if v is not None}
            raffica_fonte = "ricorrente 30'"
        else:
            raff = dict(zip(m_g, v_g))
            raffica_fonte = "raffica della centralina"
    out = []
    for m, w in zip(minuti, venti):
        out.append({"hour": m / 60.0, "wind": w, "gust": raff.get(m)})
    # La raffica ha i suoi istanti: se non coincidono con quelli del vento
    # (due canali), entra come punti propri, senza vento.
    if raff:
        propri = set(minuti)
        for m in sorted(raff):
            if m not in propri:
                out.append({"hour": m / 60.0, "wind": None, "gust": raff[m]})
        out.sort(key=lambda r: r["hour"])
    for r in out:
        r["raffica_fonte"] = raffica_fonte
    return out


# ---------------------------------------------------------------------------
# La raffica prevista: medio per un rapporto MISURATO, non per quello del modello
# ---------------------------------------------------------------------------
#
# Gian: "la previsione delle raffiche e' molto lontana dal medio, si puo' fare
# qualcosa?". Misurato prima di toccare niente (Malcesine, marzo-settembre
# 2026, 970 ore con vento >= 8 kn; poi Sport Addicted, dodici anni, sei
# centraline, 107.000 ore):
#
#   la raffica E' lontana dal medio, ed e' il lago: il massimo dell'ora vale
#   1,5-2,0 volte il medio, e il rapporto SCENDE quando il vento sale (Ora:
#   1,76 fra 8 e 12 kn, 1,57 fra 12 e 16, 1,51 sopra i 16; Peler: da 1,98 a
#   1,49). Un rapporto fisso sbaglia di 2-3 nodi proprio nelle giornate forti;
#
#   il rapporto g10/w10 che dice il modello, ora per ora, non ha nessuna
#   relazione con quello vero: correlazione 0,23 con l'Ora e 0,03 col Peler.
#   Un rapporto imparato dalle misure dimezza l'errore (2,0 -> 1,1 kn);
#
#   il ripiego di 1,35 che si usava senza raffica del modello sottostimava di
#   4-6 nodi;
#
#   e i SENSORI non misurano la stessa raffica: lo stesso posto da' 1,9 su
#   Addicted e 1,45 su Meteotrentino. Quindi il rapporto va imparato dalla
#   centralina che la pagina mostra come "misurato", non da un archivio piu'
#   ricco di un altro sensore - altrimenti la raffica prevista starebbe sempre
#   il 25% sopra quella misurata accanto, e sembrerebbe sbagliata ogni giorno.
#   Sedici ore del sensore giusto valgono piu' di seimila di quello sbagliato.
#
# La forma e' a scalini per livello di vento (verificata alla cieca: imparata
# sugli anni pari, controllata sui dispari, il bias sopra i 16 kn passa da
# +-2,4 a meno di mezzo nodo). Si impara ogni volta dall'archivio orario della
# centralina, cosi' cresce da sola: Torbole oggi ha novanta ore di raffica, fra
# un mese ne avra' quattrocento, e nessuno deve ricordarsi di aggiornare un
# numero.
RAFFICA_SCALINI = (8.0, 12.0, 16.0, 20.0)
RAFFICA_MIN_ORE = 12          # sotto, uno scalino non si fida di se stesso
RAFFICA_PREDEFINITO = 1.6     # la mediana di tutto quello che si e' misurato
RAFFICA_LIMITI = (1.0, 2.5)


def relazione_raffica(spot_name):
    """{scalino_kn: rapporto} imparato dalla centralina dello spot, nel suo regime.

    Ritorna anche "ore" (quante ne ha imparate) e "fonte" per poterlo dire in
    pagina. Il calcolo e' una passata sull'archivio orario di una centralina:
    e' piccolo, e si tiene in memoria per giornata.
    """
    chiave = "raffica:%s:%s" % (spot_name, local_day(utc_now()))
    if chiave in STATE:
        return STATE[chiave]
    spot = config.SPOTS[spot_name]
    h0, h1 = spot["window"]
    per_scalino = {s: [] for s in RAFFICA_SCALINI}
    for r in store.obs_hours(spot["station"]):
        w, g = r.get("wind_mean"), r.get("gust_max")
        if w is None or g is None or w < RAFFICA_SCALINI[0] or g < w:
            continue
        dt = parse_dt_any(r["hour"])
        # La finestra di config e' INCLUSIVA agli estremi (start <= h <= end),
        # e tutti gli altri lettori la usano cosi'. Qui c'era un "<", e l'ora
        # di chiusura non entrava mai: a Torbole sull'Ora (11-19) si buttava
        # via un nono del campione, sempre lo stesso - l'ora in cui la brezza
        # cala, che e' anche quella con il rapporto piu' alto.
        if dt is None or not (h0 <= local_hour(dt) <= h1):
            continue
        scalino = max(s for s in RAFFICA_SCALINI if s <= w)
        per_scalino[scalino].append(g / w)
    tabella = {}
    for s, v in per_scalino.items():
        if len(v) >= RAFFICA_MIN_ORE:
            v.sort()
            tabella[s] = clamp(v[len(v) // 2], *RAFFICA_LIMITI)
    esito = {"scalini": tabella, "ore": sum(len(v) for v in per_scalino.values()),
             "fonte": spot["station"]}
    STATE[chiave] = esito
    return esito


def rapporto_raffica(spot_name, wind):
    """Il rapporto raffica/medio da usare a questo livello di vento.

    Lo scalino del livello, o l'ultimo che c'e' sotto; e se la centralina non
    ha ancora insegnato niente, il predefinito - che e' una mediana misurata,
    non un numero a occhio.
    """
    tab = relazione_raffica(spot_name)["scalini"]
    if not tab:
        return RAFFICA_PREDEFINITO
    sotto = [s for s in tab if s <= wind]
    return tab[max(sotto)] if sotto else tab[min(tab)]


def _spot_per_ora(spot_names, h):
    """Lo spot (regime) a cui appartiene un'ora: la raffica dell'Ora non e'
    quella del Peler, e a Torbole differiscono di mezzo punto di rapporto."""
    for name in spot_names:
        a, b = config.SPOTS[name]["window"]
        if a <= h < b:
            return name
    return min(spot_names, key=lambda n: min(abs(h - x)
                                             for x in config.SPOTS[n]["window"]))


def day_profile(place, day, sessions):
    """Andamento orario dell'intera giornata per un luogo, gia' corretto.

    Il modello lavora sulla giornata, non sull'ora: qui la forma oraria viene
    dall'ensemble e l'ampiezza dalla previsione. Fra una sessione e l'altra il
    fattore di correzione si interpola, cosi' la curva resta continua invece
    di spezzarsi a meta' mattina.
    """
    spot_names = [s for s in config.SPOT_ORDER
                  if config.SPOTS[s]["place"] == place
                  and config.SPOTS[s]["target"] == "hourly"]
    if not spot_names:
        return []
    hours, spread, _n, _o = ensemble_hours(spot_names[0])
    if not hours:
        return []

    keys = [k for k in F.window_hours(day, 3, 21) if k in hours]
    if not keys:
        return []

    # Per ciascuna sessione due correzioni: di quanto il modello alza o abbassa
    # il vento grezzo (fattore), e di quanto sposta l'ora del massimo (shift).
    anchors = []
    for name in spot_names:
        data = sessions.get(name)
        if not data:
            continue
        h0, h1 = config.SPOTS[name]["window"]
        win = [(local_hour(parse_dt_any(k)), hours[k].get("w10"))
               for k in F.window_hours(day, h0, h1) if k in hours]
        win = [(h, v) for h, v in win if v is not None]
        if not win:
            continue
        raw_hour, raw_peak = max(win, key=lambda hv: hv[1])
        if raw_peak <= 0.5:
            continue
        shift = 0.0
        if data.get("peak_hour") is not None:
            shift = clamp(data["peak_hour"] - raw_hour, -4.0, 4.0)
        anchors.append(((h0 + h1) / 2.0,
                        clamp(data["speed"] / raw_peak, 0.35, 3.0), shift))
    if not anchors:
        anchors = [(12.0, 1.0, 0.0)]

    by_hour = {}
    for k in keys:
        h = local_hour(parse_dt_any(k))
        if hours[k].get("w10") is not None:
            by_hour[h] = k

    def sample(h):
        """Vento grezzo a un'ora anche frazionaria, per interpolazione."""
        lo_h = int(math.floor(h))
        hi_h = lo_h + 1
        a = by_hour.get(lo_h)
        b = by_hour.get(hi_h)
        if a is None and b is None:
            return None, None
        if a is None:
            return hours[b].get("w10"), hours[b]
        if b is None:
            return hours[a].get("w10"), hours[a]
        t = h - lo_h
        va, vb = hours[a].get("w10"), hours[b].get("w10")
        return va * (1 - t) + vb * t, hours[a]

    out = []
    for k in keys:
        dt = parse_dt_any(k)
        h = local_hour(dt)
        weights = [1.0 / (1.0 + abs(h - hc) ** 2) for hc, _f, _s in anchors]
        total = sum(weights) or 1.0
        factor = sum(wt * f for wt, (_hc, f, _s) in zip(weights, anchors)) / total
        shift = sum(wt * sh for wt, (_hc, _f, sh) in zip(weights, anchors)) / total

        # Si legge il vento grezzo all'ora SPOSTATA: se il modello dell'orario
        # dice che il picco arriva un'ora dopo, tutta la curva scorre con lui.
        w, src = sample(clamp(h - shift, min(by_hour), max(by_hour)))
        if w is None:
            continue
        wind = max(0.0, w * factor)
        # Non il g10/w10 del modello: ora per ora e' rumore (correlazione
        # 0,03-0,23 con il rapporto vero). Il rapporto misurato alla
        # centralina, per regime e per livello di vento - vedi
        # relazione_raffica.
        ratio = rapporto_raffica(_spot_per_ora(spot_names, h), wind)
        sp = spread.get(k)
        sp = 2.0 if sp is None else sp * factor
        out.append({
            "hour": h, "key": k, "wind": wind, "gust": wind * ratio,
            "lo": max(0.0, wind - sp), "hi": wind + sp,
            "spread": sp,
            "dir": hours[k].get("d10"),
            # Aria e cielo viaggiano con il profilo invece di essere ripescati
            # da una seconda passata sull'ensemble: sono gia' qui, e una
            # chiamata in meno per luogo e per giorno si sente all'avvio.
            "t2m": hours[k].get("t2m"),
            "cloud": hours[k].get("cloud"),
            "precip": hours[k].get("precip"),
        })

    # A Torbole, sulle scadenze in analogs.LEADS, la forma validata viene dalle
    # giornate storiche analoghe (quante, lo dice analogs.K). Il LIVELLO resta
    # esattamente quello del profilo che avremmo mostrato senza analoghi, e
    # "livello" vuol dire il massimo delle medie orarie, che e' la grandezza su
    # cui il modello e' addestrato: non il massimo istantaneo della curva a
    # dieci minuti, che sta piu' in alto e che il modello non prevede. La
    # libreria restituisce 10 minuti, cosi' il gradino non viene ricreato e poi
    # distrutto da un ricampionamento orario.
    if place == "Torbole" and analogs.promoted():
        leads = [int(e.get("lead")) for e in sessions.values()
                 if e and e.get("lead") is not None]
        lead = min(leads) if leads else None
        if lead in analogs.LEADS:
            # Le finestre dei regimi viaggiano con la chiamata: la forma viene
            # dagli analoghi, ma il LIVELLO di ciascuna finestra resta quello
            # che il motore aveva previsto per quella sessione. Altrimenti la
            # mattina eredita il picco del pomeriggio, ed e' il difetto che sul
            # Peler portava i falsi allarmi dal 15% al 38%.
            finestre = tuple((config.SPOTS[n]["window"][0] * 60.0,
                              (config.SPOTS[n]["window"][1] + 1) * 60.0)
                             for n in spot_names)
            shaped, _meta = analogs.apply_to_profile(day, lead, out, finestre)
            if shaped is not out:
                return shaped
    return out


def by_day(product=None):
    """Riorganizza la previsione PER GIORNO.

    E' il modo in cui si decide davvero: prima si sceglie il giorno, poi si
    guarda dove e a che ora. La struttura precedente, un blocco per luogo con
    i giorni nascosti dentro, costringeva a confrontare due schede diverse
    per rispondere a "domani dove vado".
    """
    product = product or full_product()
    days = {}
    for spot_name, entries in product.items():
        for e in entries:
            days.setdefault(e["day"], {})[spot_name] = e
    out = []
    for day in sorted(days):
        sessions = days[day]
        lead = min(e["lead"] for e in sessions.values())
        places = {}
        for place in config.PLACES:
            profile = day_profile(place, day, sessions)
            # Archiviamo la curva *prima* di qualunque futuro nowcast. La chiave
            # e' il run delle previsioni, quindi un refresh della pagina e'
            # idempotente. Questa storia prospettica e' il gate necessario per
            # validare la correzione esattamente sul prodotto mostrato.
            issued_at = store.meta_get("last_forecast_run")
            if profile and issued_at:
                store.save_issued_profile(place, issued_at, profile)
            places[place] = {"profile": profile,
                             # L'osservato serve solo per la giornata di oggi:
                             # nei giorni futuri non esiste, e nei passati la
                             # pagina non li mostra.
                             "osservato": (day_observed(place, day)
                                           if day == local_day(utc_now())
                                           else None),
                             "live": live_reading(
                                 next(config.SPOTS[s]["station"]
                                      for s in config.SPOTS
                                      if config.SPOTS[s]["place"] == place))}
        out.append({"day": day, "lead": lead, "sessions": sessions, "places": places})
    return out


# Taglie indicative di wing per un rider intorno agli 80 kg su foil.
# Sono un punto di partenza, non un consiglio: dipendono da tavola, ala,
# livello e da quanto e' rafficato.
WING_SIZES = (
    (27, "3.0 m o meno"),
    (23, "3.0-3.5 m"),
    (19, "3.5-4.0 m"),
    (16, "4.0-4.5 m"),
    (13, "4.5-5.0 m"),
    (10, "5.5-6.5 m"),
)


def wing_hint(speed):
    for threshold, label in WING_SIZES:
        if speed >= threshold:
            return label
    return None
