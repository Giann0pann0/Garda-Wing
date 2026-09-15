"""Configurazione statica: spot, geometria del lago, modelli, finestre.

Tutti i tempi interni sono UTC. La conversione a ora locale (Europe/Rome)
avviene solo in presentazione e nel calcolo del "giorno locale".
"""

import math
import os

APP_NAME = "Garda Wind"
APP_VERSION = "3.7"
DB_FILENAME = "gardawind_v3.sqlite"

TZ_LOCAL = "Europe/Rome"

# --------------------------------------------------------------------------
# Geometria del lago
# --------------------------------------------------------------------------
# Asse dell'alto lago, calcolato dalle coordinate delle due centraline:
#   Torbole  45.870095 / 10.877355
#   Malcesine 45.7646  / 10.8119
# bearing Torbole -> Malcesine = 205.4 deg  (e quindi 25.4 deg in ritorno)
# L'Ora risale il lago da SSO verso NNE: la sua direzione di provenienza e'
# ~205 deg. Il Peler scende da NNE: provenienza ~25 deg.
LAKE_AXIS_ORA = 204.0     # direzione di PROVENIENZA dell'Ora
LAKE_AXIS_PELER = 24.0    # direzione di PROVENIENZA del Peler

# --------------------------------------------------------------------------
# Due assi, non uno: la geometria del lago e cio' che la centralina misura
# --------------------------------------------------------------------------
# Fino alla 3.6 un solo numero faceva due lavori diversi: proiettare il vento
# dei MODELLI lungo la valle, e decidere se la direzione OSSERVATA appartiene
# al regime. Sono due sistemi di riferimento distinti, e sui dati veri non
# coincidono affatto.
#
# Misurato su 3511 giornate ventose di Torbole (2012-2026, comando --direzioni):
#
#   Peler   asse geometrico 24    mediana circolare osservata 54   R=0.90
#           mode 55, e la mediana vale 54-55 in TUTTE E QUATTRO le stagioni
#   Ora     asse geometrico 204   mediana circolare osservata 191  R=0.55
#
# Trenta gradi di scarto, con una concentrazione altissima e stabile tutto
# l'anno: non e' rumore. La geometria del lago (bearing Torbole->Malcesine)
# descrive il solco, non cio' che arriva a quella centralina, che sta in una
# conca con la propria topografia.
#
# Conseguenza pratica: il BERSAGLIO ("il regime e' entrato") si giudica nel
# sistema della centralina, perche' e' la centralina che il modello deve
# prevedere. Le FEATURE continuano a proiettare il vento dei modelli sull'asse
# geometrico, che e' il riferimento giusto per un vento di griglia grossolana.
#
# Nota per Malcesine: i valori vengono da 101 e 50 giornate ventose di solo
# 2026, quindi sono PROVVISORI e per giunta viziati dalla stagione. Vanno
# riconfermati quando l'archivio intraday sara' piu' lungo.
OBS_AXIS = {
    "Torbole-Ora": 191.0,        # 4077 gg, mediana circolare, R=0.55
    "Torbole-Peler": 54.0,       # 3511 gg, mediana circolare, R=0.90
    "Malcesine-Ora": 230.0,      # PROVVISORIO: 101 gg
    "Malcesine-Peler": 68.0,     # PROVVISORIO: 50 gg
    "Malcesine-Giorno": 204.0,   # non usato: il bersaglio e' la raffica del giorno
}

# --------------------------------------------------------------------------
# Spot
# --------------------------------------------------------------------------
# LA FINESTRA UTILE, che non e' la finestra del regime.
#
# "window" dice quando il regime puo' soffiare. Ma la domanda di chi naviga non
# e' "a che minuto e' nato il Peler": e' "alle 6-9 quanto sara' buono". E per
# rispondere a quella serve un'altra finestra - quella in cui ha senso pensare
# di entrare in acqua - che dipende da due cose:
#
#   un'ora minima praticabile, che e' una scelta (le 06:00 per il Peler: prima
#   non ci si alza, e in estate e' quello il vincolo che morde);
#   la LUCE, che non e' una scelta. A Torbole l'alba passa da 05:31 a fine
#   giugno a 07:59 a fine dicembre: un'ora pratica fissa sarebbe sbagliata
#   mezzo anno, e lo sarebbe proprio nei mesi in cui il Peler e' piu' spesso
#   gia' attivo prima che si cominci a guardare.
#
# Quindi: inizio = max(inizio della finestra del regime, ora pratica,
#                      alba + margine).
#
# Il margine dopo l'alba non e' astronomico: e' il tempo fra "tecnicamente c'e'
# luce" e "ha senso essere in acqua".
MARGINE_ALBA_MIN = 30.0

# Lo stesso vincolo morde all'altro capo: la finestra dell'Ora arriva alle
# 20:00, ma a dicembre il sole tramonta alle 16:39. Nessuno atterra al buio.
MARGINE_TRAMONTO_MIN = 30.0

# Non si va in acqua dodici mesi l'anno, e questo cambia quali righe di una
# tabella climatologica contano. Le soglie d'uso si guardano nella stagione in
# cui si naviga davvero; l'inverno resta utile, ma come banco - la' si vede la
# persistenza e la struttura del Peler senza che quei mesi tirino a se' una
# soglia che poi si usa a maggio.
#
# Una cosa che questa divisione NON fa: non scegliere la soglia di planata.
# Quanti nodi servono per stare sul foil e' una proprieta' dell'ala e di chi la
# usa, non del mese. La stagione decide quali quote si leggono, non il numero.
STAGIONI_USO = (
    ("primaria", (4, 5, 6, 7, 8, 9, 10)),
    ("transizione", (3, 11)),
    ("diagnostica", (12, 1, 2)),
)

# window: ore LOCALI incluse (start <= h <= end) in cui il regime puo' soffiare
# min_kn: soglia sopra la quale consideriamo il regime "entrato" (media oraria)
# planing_kn: soglia indicativa di planata per wing/windsurf
TORBOLE = dict(lat=45.870095, lon=10.877355, elevation=90,
               station="T0193", source="meteotrentino",
               station_name="Torbole (Belvedere) - Meteotrentino")
MALCESINE = dict(lat=45.7646, lon=10.8119, elevation=65,
                 station="malcesine", source="meteoproject",
                 station_name="Fraglia Vela Malcesine - MeteoProject")

# Ogni voce e' una coppia LUOGO + REGIME: sono due fenomeni diversi, con
# finestre, asse e fisica diversi, e vanno previsti separatamente.
# target: 'hourly'     -> picco della media oraria nella finestra
#         'daily_gust' -> raffica massima del giorno (archivio giornaliero)
SPOTS = {
    "Torbole-Ora": dict(TORBOLE, place="Torbole", label="Torbole · Ora",
                        regime="ORA", axis=LAKE_AXIS_ORA, window=(11, 19),
                        min_kn=11.0, planing_kn=14.0, target="hourly"),
    "Torbole-Peler": dict(TORBOLE, place="Torbole", label="Torbole · Pelèr",
                          regime="PELER", axis=LAKE_AXIS_PELER, window=(4, 10),
                          min_kn=10.0, planing_kn=13.0, target="hourly",
                          ora_pratica=6.0),
    "Malcesine-Ora": dict(MALCESINE, place="Malcesine", label="Malcesine · Ora",
                          regime="ORA", axis=LAKE_AXIS_ORA, window=(12, 19),
                          min_kn=11.0, planing_kn=14.0, target="hourly"),
    "Malcesine-Peler": dict(MALCESINE, place="Malcesine", label="Malcesine · Pelèr",
                            regime="PELER", axis=LAKE_AXIS_PELER, window=(5, 11),
                            min_kn=10.0, planing_kn=13.0, target="hourly",
                            ora_pratica=6.0),
    # L'archivio pubblico di Malcesine e' giornaliero: da' la raffica massima
    # del giorno senza dire a che ora. E' comunque un bersaglio allenabile su
    # due anni, e "quanto tira di punta oggi" e' una domanda sensata.
    "Malcesine-Giorno": dict(MALCESINE, place="Malcesine",
                             label="Malcesine · raffica di giornata",
                             regime="GIORNO", axis=LAKE_AXIS_ORA, window=(6, 20),
                             min_kn=18.0, planing_kn=22.0, target="daily_gust"),
}

# Un regime e' un vento CON UNA DIREZIONE. Se al mattino soffiano 15 nodi da
# sud, quello non e' il Peler: e' un meridionale sinottico (o l'Ora che entra
# prestissimo). Contarlo come "Peler entrato" insegnerebbe al modello
# associazioni false, e direbbe all'utente una cosa sbagliata.
# Mezza ampiezza del settore di provenienza ammesso attorno all'asse.
REGIME_SECTOR_DEG = 70.0

for _n, _s in SPOTS.items():
    _s["axis_obs"] = OBS_AXIS.get(_n, _s["axis"])

PLACES = ["Torbole", "Malcesine"]
SPOT_ORDER = ["Torbole-Ora", "Torbole-Peler",
              "Malcesine-Ora", "Malcesine-Peler", "Malcesine-Giorno"]

# Punti geografici distinti da interrogare (spot diversi possono condividerli)
def forecast_points():
    """Punti unici (lat, lon) per cui servono previsioni, con gli spot associati."""
    pts = {}
    for name, s in SPOTS.items():
        key = (round(s["lat"], 4), round(s["lon"], 4))
        pts.setdefault(key, []).append(name)
    return pts


# --------------------------------------------------------------------------
# Punti di contesto sinottico
# --------------------------------------------------------------------------
# Servono a costruire il gradiente barico e termico fra la pianura padana
# (sud) e il solco atesino / conca alpina (nord). E' il motore di fondo che
# rinforza o uccide entrambi i regimi.
CONTEXT_POINTS = {
    "Bolzano":  (46.4983, 11.3548, "north"),
    "Trento":   (46.0748, 11.1217, "north"),
    "Brescia":  (45.5416, 10.2118, "south"),
    "Verona":   (45.4384, 10.9916, "south"),
    "Mantova":  (45.1564, 10.7914, "south"),
    "Merano":   (46.6713, 11.1595, "north"),
}

# --------------------------------------------------------------------------
# Modelli Open-Meteo
# --------------------------------------------------------------------------
# Verificati uno per uno su questo punto (settembre 2026).
# "levels" = il modello espone i livelli isobarici 925/850/700 hPa.
# "res_km" = risoluzione nominale, usata come prior sui pesi finche' non
#            ci sono osservazioni sufficienti per stimarli dai dati.
MODELS = {
    "ECMWF IFS":        {"id": "ecmwf_ifs025",                   "levels": True,  "res_km": 25, "gusts": True},
    "ECMWF AIFS":       {"id": "ecmwf_aifs025_single",           "levels": True,  "res_km": 25, "gusts": False},
    "ICON-D2":          {"id": "icon_d2",                        "levels": True,  "res_km": 2.2, "gusts": True},
    "ICON-EU":          {"id": "icon_eu",                        "levels": True,  "res_km": 7,  "gusts": True},
    "ICON-2I":          {"id": "italia_meteo_arpae_icon_2i",     "levels": True,  "res_km": 2.2, "gusts": True},
    "AROME Austria":    {"id": "geosphere_arome_austria",        "levels": False, "res_km": 2.5, "gusts": True},
    "ICON-CH2":         {"id": "meteoswiss_icon_ch2",            "levels": False, "res_km": 2.1, "gusts": True},
    "ARPEGE Europe":    {"id": "meteofrance_arpege_europe",      "levels": True,  "res_km": 11, "gusts": True},
    "HARMONIE":         {"id": "knmi_harmonie_arome_europe",     "levels": True,  "res_km": 5.5, "gusts": True},
    "GFS":              {"id": "gfs_seamless",                   "levels": True,  "res_km": 13, "gusts": True},
    "UKMO":             {"id": "ukmo_global_deterministic_10km", "levels": True,  "res_km": 10, "gusts": True},
    "GEM":              {"id": "gem_global",                     "levels": True,  "res_km": 15, "gusts": True},
}

# NB: "best_match" NON entra nell'ensemble, perche' e' una copia di uno degli
# altri membri e falserebbe la dispersione. Lo usiamo solo come sorgente delle
# feature storiche (e' l'unico con archivio profondo e livelli isobarici).
ARCHIVE_MODEL = "best_match"

# Modelli su cui calcolare la verifica per-modello (previous-runs, superficie).
# Tutti quelli dell'ensemble: l'API li supporta a livello di superficie.
VERIFY_LEADS = (1, 2, 3)

# --------------------------------------------------------------------------
# Variabili
# --------------------------------------------------------------------------
SURFACE_VARS = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m",
    "precipitation", "cloud_cover", "cloud_cover_low",
    "pressure_msl", "shortwave_radiation",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
]
LEVEL_VARS = [
    "temperature_925hPa", "wind_speed_925hPa", "wind_direction_925hPa",
    "temperature_850hPa", "wind_speed_850hPa", "wind_direction_850hPa",
    "wind_speed_700hPa", "wind_direction_700hPa",
]
CONTEXT_VARS = ["pressure_msl", "temperature_2m", "cloud_cover", "shortwave_radiation"]

# Variabili disponibili nel previous-runs API. Verificate una per una su
# best_match alle scadenze 1, 3 e 7: passano tutte tranne cloud_cover_low.
# I livelli isobarici non sono esposti da questo endpoint.
PREV_RUN_VARS = [
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "temperature_2m", "dew_point_2m", "relative_humidity_2m",
    "pressure_msl", "shortwave_radiation", "precipitation", "cloud_cover",
]
PREV_RUN_CONTEXT_VARS = ["pressure_msl", "temperature_2m"]

# Scadenze per cui esiste un archivio di predittori COME ERANO AL MOMENTO
# DELL'EMISSIONE. Verificato: best_match, ECMWF e GFS arrivano a 7;
# ICON-EU si ferma a 4 (e' la sua portata).
PREV_RUN_LEADS = (1, 2, 3, 4, 5, 6, 7)
PREV_RUN_START = "2024-01-01"   # profondita' dell'archivio previous-runs

# Fasce di scadenza: un modello per fascia, addestrato sui predittori come
# erano a quella scadenza.
#
# La prima formulazione di queste fasce distingueva "con memoria" e "senza
# memoria", assumendo che a D0/D+1 il picco del giorno prima fosse noto e da
# D+2 no. Il conto e' piu' stretto di cosi': con emissione il giorno T-L, il
# giorno T-1 e' passato solo se L = 0. A D+1 quel giorno e' il giorno stesso
# dell'emissione e la sua finestra non si e' ancora chiusa. La distinzione
# binaria era quindi sbagliata a D+1, e va comunque superata: la memoria
# esiste a ogni scadenza, e' solo piu' vecchia (vedi features.daily_features).
#
# Resta la ragione vera per separare le fasce: fra D0 e D+6 non cambia il
# vettore, cambia il legame fra vettore ed esito. Un modello per fascia lo
# lascia stimare invece di imporlo con un moltiplicatore.
#
# I TAGLI SONO UN'IPOTESI. Vanno scelti sui dati di addestramento con
# validate.band_study(), mai sul blocco finale.
LEAD_BANDS = (
    ("short", (0, 1)),
    ("medium", (2, 3)),
    ("long", (4, 7)),
)

# Tagli alternativi messi a confronto da validate.band_study().
BAND_CANDIDATES = (
    (("short", (0, 1)), ("medium", (2, 3)), ("long", (4, 7))),
    (("short", (0, 0)), ("medium", (1, 2)), ("long", (3, 7))),
    (("short", (0, 1)), ("medium", (2, 4)), ("long", (5, 7))),
    (("short", (0, 2)), ("long", (3, 7))),
    (("unico", (0, 7)),)                  # nessuna separazione: il riferimento
)


def band_for_lead(lead, bands=None):
    for name, (a, b) in (bands or LEAD_BANDS):
        if a <= lead <= b:
            return name
    return (bands or LEAD_BANDS)[-1][0]


def band_leads(name, bands=None):
    for bname, (a, b) in (bands or LEAD_BANDS):
        if bname == name:
            return list(range(a, b + 1))
    return []


# Ultimo blocco temporale tenuto fuori da OGNI scelta (feature, modello,
# iperparametri) e aperto una volta sola alla valutazione finale.
BLIND_HOLDOUT_DAYS = 240

# --------------------------------------------------------------------------
# Sorgenti
# --------------------------------------------------------------------------
URL_FORECAST = "https://api.open-meteo.com/v1/forecast"
# Rianalisi ERA5: nessun livello isobarico, ma le variabili di superficie
# risalgono a decenni fa. Verificato fino al 1990 su tutti i nostri punti.
# Serve a estendere l'addestramento oltre i ~5 anni coperti dall'archivio
# delle previsioni: le osservazioni di Torbole partono dal 2012.
URL_ARCHIVE_ERA5 = "https://archive-api.open-meteo.com/v1/archive"
ERA5_MODEL = "era5"
ERA5_START = "2012-07-04"   # inizio della serie della centralina di Torbole
URL_ARCHIVE_FC = "https://historical-forecast-api.open-meteo.com/v1/forecast"
URL_PREV_RUNS = "https://previous-runs-api.open-meteo.com/v1/forecast"

URL_METEOTRENTINO = "https://dati.meteotrentino.it/service.asmx/datiRealtimeUnaStazione"
# La centralina di Meteotrentino marca i dati con offset +01 tutto l'anno
# (ora solare CET, senza ora legale). Verificato dal picco di radiazione.
METEOTRENTINO_UTC_OFFSET_HOURS = 1

# index.php e' l'unica pagina con i valori etichettati
# ("Velocita' attuale: X kts DIR", "Media: Y kts"). dati.php li mette in
# una tabella senza etichette e il parser non aveva appigli.
# addicted-sports: una pagina, non un'API. I numeri sono nel corpo servito dal
# server (verificato scaricando il corpo grezzo), e la pagina stessa usa
# "?json=wind&from=YYYY-MM-DD" per il suo grafico: quella risposta contiene la
# serie ORARIA misurata (mavg, mmax) con i decimali. La direzione pubblicata e'
# quella PREVISTA, non misurata, e non va usata come osservazione.
URL_ADDICTED_TORBOLE = "https://it.addicted-sports.com/forecast/gardasee/torbole/"
URL_ADDICTED_WEBCAM = "https://it.addicted-sports.com/webcam/gardasee/torbole/"
# Le inquadrature orarie archiviate: .../YYYY/MM/DD/HHMM_lm.jpg. Non misurano
# il vento; provano che a quell'ora il sito stava registrando.
URL_ADDICTED_WEBCAM_FRAMES = "https://it.addicted-sports.com/fileadmin/webcam/torbole/"

URL_MALCESINE_LIVE = "https://stazioni.meteoproject.it/dati/malcesine/index.php"
URL_MALCESINE_NOAA_CSV = "https://stazioni.meteoproject.it/dati/malcesine/csvnoaa.php"
MALCESINE_ARCHIVE_START = (2024, 8)   # primo mese del report NOAA giornaliero

# Archivio INTRADAY della Davis Vantage Pro2 della Fraglia Vela: passo 15-30
# minuti, vento e raffica gia' in nodi, con direzione di entrambe. E' la
# sorgente che permette di separare davvero il Peler dall'Ora a Malcesine:
# il report NOAA da' solo un numero al giorno e non dice a che ora.
# Massimo un mese per richiesta; nei parametri gg2/mm2/aa2 e' la data INIZIALE
# e gg/mm/aa quella finale (non il contrario, nonostante l'ordine).
URL_MALCESINE_CSV = "https://stazioni.meteoproject.it/dati/malcesine/csv.php"
MALCESINE_INTRADAY_START = (2026, 3)  # primo mese con dati, verificato

# --------------------------------------------------------------------------
# Archivio storico Meteotrentino (Hydstra/WEB)
# --------------------------------------------------------------------------
# Espone l'intera serie a 10 minuti della T0193 dal 04/07/2012.
# Flusso: si legge lo userid anonimo dalla pagina principale, si chiede la
# generazione dell'estrazione, si scarica lo ZIP prodotto.
URL_HYDSTRA_MAIN = "http://storico.meteotrentino.it/cgi/webhyd.pl?main"
URL_HYDSTRA_APP = "http://storico.meteotrentino.it/cgi/webhyd.pl"
HYDSTRA_VARS = {
    "wind": ("515.00_515.00", "Veloc. vento media"),      # m/s
    "dir": ("500.00_500.00", "Direzione vento media"),    # gradi
}
HYDSTRA_ARCHIVE_START = "2012-07-04"
# Anche l'archivio Hydstra, come il servizio realtime, marca i dati in ora
# solare CET tutto l'anno. Verificato sul ciclo diurno: minimo di transizione
# alle 10 (= 11 locali d'estate), massimo dell'Ora alle 13.
HYDSTRA_UTC_OFFSET_HOURS = 1

# --------------------------------------------------------------------------
# Parametri del motore
# --------------------------------------------------------------------------
FORECAST_DAYS = 8
UPDATE_INTERVAL_MIN = 25        # aggiornamento completo dei modelli
POLL_INTERVAL_MIN = 8           # polling centraline (piu' frequente)

# Il dato osservato e la previsione hanno due tempi diversi: le centraline
# ogni dieci minuti, i modelli globali ogni sei ore. Finche' la pagina li
# pubblicava insieme, l'"adesso" invecchiava come la previsione e diceva
# "adesso" anche dopo cinque ore. Ora il dato osservato sta in un file suo,
# che un processo veloce riscrive da solo, e la pagina lo rilegge.
#
# LIVE_JSON_URL e' dove la pagina pubblicata va a cercarlo. Non puo' essere
# il live.json della pagina stessa: GitHub Pages si pubblica tutto insieme,
# quindi quel file si aggiorna solo quando si ricostruisce il sito. Il
# processo veloce scrive invece su un ramo dedicato del repository, e da li'
# il file e' leggibile via HTTP senza ricostruire niente.
#
# Se la richiesta non riesce - rete assente, ramo non ancora creato - la
# pagina NON resta vuota: tiene i valori con cui e' stata costruita e
# continua a mostrarne l'eta', che cresce. Un dato vecchio che si vede
# invecchiare e' onesto; un dato vecchio scritto "adesso" no.
LIVE_JSON_URL = os.environ.get(
    "GARDAWIND_LIVE_URL",
    "https://raw.githubusercontent.com/Giann0pann0/Garda-Wing/live/live.json")

# Ogni quanto la pagina rilegge quel file. Il processo veloce gira ogni dieci
# minuti circa (il cron di GitHub non e' puntuale), quindi chiederlo piu'
# spesso di cinque minuti non porta dati nuovi.
LIVE_REFRESH_MIN = 5.0
# Sette giorni. Oltre il terzo restano solo i modelli globali: quelli ad area
# limitata (ICON-D2, AROME, ICON-2I, che sono anche i piu' bravi su un lago
# stretto in mezzo alle montagne) si fermano prima. La scheda lo dichiara
# mostrando quanti modelli hanno risposto per quel giorno.
MAX_LEAD_DAYS = 7

# Copertura minima della finestra oraria perche' un giorno sia usabile
# come campione di training. Un giorno con dati mancanti NON e' un giorno
# senza vento: va escluso, non messo a zero.
MIN_WINDOW_COVERAGE = 0.55

# Scala di shrinkage: con N giorni utili il modello appreso pesa N/(N+K).
SHRINK_K_DAILY = 45
SHRINK_K_HOURLY = 400

# Livelli minimi di campione per salire di gradino
TIER_THRESHOLDS = {
    "bias": 12,      # correzione lineare a+b*w  (giorni)
    "reduced": 45,   # modello a feature ridotte
    "full": 130,     # modello completo
}

# Margine di miglioramento richiesto in cross-validation per promuovere
# un modello piu' complesso (in frazione di RMSE).
PROMOTION_MARGIN = 0.03

RUNTIME_PORT = 8781
