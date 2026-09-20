"""Configurazione statica: spot, geometria del lago, modelli, finestre.

Tutti i tempi interni sono UTC. La conversione a ora locale (Europe/Rome)
avviene solo in presentazione e nel calcolo del "giorno locale".
"""

import math
import os

APP_VERSION = "3.7"
# Il nome del prodotto, in un posto solo: manifesto dell'app installata,
# titolo delle pagine, anteprima dei link. Scelto da Gian il 2026-09-18,
# sul mockup che ha mandato: "Time to Foil". Il nome precedente, "L'Ora e'
# arrivata", resta come FRASE dell'avviso Telegram - e' quello che si dice
# quando la scheda ha avuto ragione - ma non e' piu' il nome del sito.
# Il nome corto e' per l'icona sul telefono: dodici caratteri ci stanno.
APP_NAME = "Time to Foil"
APP_SHORT_NAME = "Time to Foil"
# La riga sotto il titolo, dal mockup. Una frase sola, e la dice il sito,
# non il regime: e' vera per il Peler quanto per l'Ora.
APP_TAGLINE = "Il vento giusto, al momento giusto."
# La foto di sfondo della testa, se c'e': un file che Gian mette nella
# cartella del progetto, accanto al README. Se manca, la pagina disegna un
# cielo in vettoriale. Non e' nel pacchetto perche' e' sua, non del codice.
SFONDO_FILE = "sfondo.jpg"


# --------------------------------------------------------------------------
# La SCALA del vento: tutte le localita' sui numeri della Meteotrentino
# --------------------------------------------------------------------------
# Gian: "uno vuole sapere quanto vento c'e' davvero, non quanto misura la
# centralina" - dopo aver visto tre pagine che per lo stesso vento dicevano
# 15, 11 e 9. Le centraline non leggono uguale: la Meteotrentino di Torbole
# (Belvedere, 90 m) legge piu' alto delle Addicted, che stanno sull'acqua ai
# circoli. Nello STESSO POSTO, Torbole, con i due strumenti fianco a fianco:
# 62.847 ore in comune, e sopra gli 8 kn la Meteotrentino legge x1,26-1,31
# volte l'Addicted, con dispersione stretta. E' un fattore di sensore, non di
# geografia: per questo si impara SOLO dalla coppia di Torbole e si applica
# uguale a tutte le Addicted (stessa famiglia di strumenti). Impararlo dalla
# coppia Campione-Torbole avrebbe mescolato dentro le giornate in cui a
# Campione tira e a Torbole no.
#
# La scala scelta e' quella della Meteotrentino, perche' e' quella su cui le
# soglie (11 kn "entra", 14 "si plana") sono state fissate e validate in
# anni, e quella dei numeri a cui Gian e' abituato. Quindi Torbole non si
# tocca; le letture Addicted (Campione, Malcesine) vengono riportate su
# questa scala LEGGENDOLE, con la curva qui sotto - in archivio resta il
# grezzo. Solo il vento medio: la raffica massima oraria dei due strumenti
# coincide gia' (rapporto x1,00 sopra gli 8 kn), e non si tocca.
#
# La curva: lettura Addicted -> mediana della Meteotrentino nello stesso
# scalino di 2 kn, resa monotona, interpolata linearmente fra i punti ed
# estrapolata col rapporto dell'ultimo punto. Con questa curva lo scarto
# mediano fra i due strumenti nelle ore con piu' di 14 kn passa da 4,7 a 1,5
# kn. Misurata il 2026-09-18 su ore 5-19; si rimisura con
# strumenti/estrai-scala.py.
SCALA_ADDICTED_A_MT = ((1.0, 2.5), (3.0, 4.6), (5.0, 7.2), (7.0, 9.9),
                       (9.0, 12.0), (11.0, 14.3), (13.0, 16.4),
                       (15.0, 18.6), (17.0, 20.2))
SCALA_ADDICTED_A_MT_N = 62847


def nome_centralina(station):
    """Il nome corto di una centralina, per dire da dove viene un prestito.

    Serve perche' il nome del LUOGO non basta: a Malcesine la direzione si
    prende in prestito dalla Fraglia, che sta a Malcesine, e la pagina
    scriveva "la si prende in prestito da Malcesine" - vero e inutile. Le
    centraline hanno un nome, ed e' quello che va detto.
    """
    for s in SPOTS.values():
        if s["station"] == station:
            return s.get("station_breve") or s.get("station_name") or station
    return station or ""


def scala_vento(source):
    """La curva con cui le letture di una fonte vanno riportate sulla scala
    comune, o None se la fonte E' la scala (Meteotrentino, e la Fraglia che
    da' solo la direzione)."""
    return SCALA_ADDICTED_A_MT if source == "addicted" else None


# La cartella del progetto: quella che contiene gardawind/, storico/, test/.
# Non e' la cartella dei dati (GARDAWIND_HOME): qui dentro sta cio' che
# viaggia con il codice, e quindi con git.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sfondo_path():
    """Il percorso della foto di sfondo, o None se non c'e'."""
    p = os.path.join(PROJECT_DIR, SFONDO_FILE)
    return p if os.path.isfile(p) else None
DB_FILENAME = "gardawind_v3.sqlite"

TZ_LOCAL = "Europe/Rome"

# --------------------------------------------------------------------------
# Da quanti minuti un dato osservato non e' piu' "adesso"
# --------------------------------------------------------------------------
# UNA domanda, UN posto. Viveva in quattro: web.py (45, scalato per tre volte
# la cadenza), engine.live_reading (45 fisso), live.py (45, scalato per due
# volte la cadenza) e store.direzione_recente (45 fisso). Due moltiplicatori
# diversi per la stessa idea: alzando la soglia in pagina, la raffica sarebbe
# sparita o la freccia in prestito si sarebbe spenta su una riga dichiarata
# fresca - senza un errore, senza un messaggio.
#
# Il valore e' quello di una centralina che pubblica ogni dieci minuti. Ma le
# Addicted (Campione, e il vento di Malcesine) mandano UN DATO ALL'ORA: alle
# 23:18 il piu' recente e' quello delle 23:00, e con una soglia fissa quelle
# centraline passavano meta' di ogni ora ingiallite, come guaste, mentre
# stavano rispettando il loro ritmo. Gian, guardando la pagina: "Campione e'
# morta". Percio' la soglia segue la CADENZA misurata, e il minimo resta
# quello dei dieci minuti.
ETA_STANTIA_MIN = 45.0
STANTIA_PASSI = 3.0

# Quanto si guarda indietro per la raffica del riquadro. E' una domanda
# diversa - "l'ultima raffica che la centralina ha DATO e' ancora di questo
# dato?" - e ha un passo suo, piu' corto; il pavimento invece e' lo stesso.
RAFFICA_PASSI = 2.0


def stantia_min(cadenza_min=None):
    """Da quanti minuti un dato di questa centralina e' 'non recente'."""
    if not cadenza_min or cadenza_min <= 0:
        return ETA_STANTIA_MIN
    return max(ETA_STANTIA_MIN, STANTIA_PASSI * float(cadenza_min))


def raffica_indietro_min(cadenza_min=None):
    """Quanto indietro cercare la raffica piu' recente di questa centralina."""
    if not cadenza_min or cadenza_min <= 0:
        return ETA_STANTIA_MIN
    return max(ETA_STANTIA_MIN, RAFFICA_PASSI * float(cadenza_min))

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
# La planata come l'ha detta lui, il 15 settembre 2026:
#
#   "un wing plana gia' dai 10 nodi, soprattutto se rafficano a 15-16.
#    direi che il threshold e' 14"
#
# Sono DUE affermazioni diverse, e appiattirle su un numero solo perderebbe la
# cosa che questo progetto ha passato giorni a tenere separata:
#
#   sulla MEDIA da sola la soglia e' 14 kn. Con quattordici nodi di fondo si
#   plana senza bisogno che la raffica aiuti - ed e' l'unica soglia
#   calcolabile sullo storico lungo, dove la raffica non c'e';
#   con la RAFFICA RICORRENTE disponibile la regola e' una COPPIA: media da
#   10 kn, se la ricorrente a 30' arriva a 15-16.
#
# La coppia non e' un coefficiente inventato: e' la sua esperienza, messa a
# verbale con la data. Ma non e' nemmeno validata, e la differenza fra le due
# cose e' tutta - le giornate che soddisfano la coppia sono PIU' di quelle che
# passano i 14 di media, quindi ogni numero calcolato sulla sola media resta
# un limite inferiore della planabilita' vera.
#
# Per questo la coppia sta qui come DATO DICHIARATO e non entra in nessun
# calcolo: si misurera' quando il dataset con la raffica sara' abbastanza
# grande (il gate e' mille ore contemporanee; oggi sono 211). Un controllo in
# test/t_distribuzione.py verifica che nessun modulo la legga, cosi' non puo'
# cominciare a decidere la planabilita' di nascosto prima di allora.
#
# Una nota di passaggio, ma non irrilevante: media 10 con ricorrente 15-16 e'
# un fattore di raffica fra 1,5 e 1,6. E' il range fisico, e NON e' il 2,3-2,6
# che dava il ponte mavg->mmax di SportAddicted: un'altra conferma che quel
# rapporto era gonfiato dal bias di mavg.
PLANATA_DICHIARATA = {
    "media_sola_kn": 14.0,
    "coppia_media_kn": 10.0,
    "coppia_ricorrente_kn": 15.0,
    "dichiarata_il": "2026-09-15",
    "fonte": "esperienza diretta, wing",
    "validata": False,
    "gate_ore": 1000,
}

# I mesi vengono dai dati veri, non dal calendario. Sul Peler in finestra
# pratica, maggio-settembre e' la stagione in cui si naviga; aprile e ottobre
# sono di passaggio - ottobre ha una coda alta (il 90esimo percentile arriva a
# circa 14,5 kn) ma la finestra utile e' gia' corta per la luce; da novembre a
# marzo il Peler e' al suo massimo e non si va in acqua, quindi quei mesi
# servono come banco e non devono tirare a se' una soglia che si usa a maggio.
STAGIONI_USO = (
    ("primaria", (5, 6, 7, 8, 9)),
    ("transizione", (4, 10)),
    ("diagnostica", (11, 12, 1, 2, 3)),
)

# window: ore LOCALI incluse (start <= h <= end) in cui il regime puo' soffiare
# min_kn: soglia sopra la quale consideriamo il regime "entrato" (media oraria)
# planing_kn: soglia indicativa di planata per wing/windsurf
TORBOLE = dict(lat=45.870095, lon=10.877355, elevation=90,
               station="T0193", source="meteotrentino",
               station_name="Torbole (Belvedere) - Meteotrentino",
               station_breve="Torbole")
# Malcesine: il VENTO viene dalla centralina Addicted della spiaggia, la
# DIREZIONE dalla Fraglia Vela (MeteoProject). Perche' non tutto dalla
# Fraglia, che ha direzione e otto minuti di passo: perche' legge basso nel
# vento forte, e in modo sporco. Misurato sulle ore in comune con Addicted
# Malcesine: a 4-8 kn concordano, a 8-12 la Fraglia e' sotto di 1,5 kn, a
# 12-16 di 3,6, sopra i 16 di 6,6 - e sopra i 12 kn letti ha quindici ore in
# tutto. Quando tira forte quel sensore non lo vede, e non si puo'
# ricostruire cio' che uno strumento non ha misurato. Addicted invece e'
# sull'acqua, ha lo storico dal 2014 (95.000 ore, contro 200 giorni della
# Fraglia) ed e' la stessa famiglia di Campione. La Fraglia resta, e serve:
# la direzione, che Addicted non misura, e la raffica massima del giorno.
MALCESINE_FRAGLIA = dict(lat=45.7646, lon=10.8119, elevation=65,
                         station="malcesine", source="meteoproject",
                         station_name="Fraglia Vela Malcesine - MeteoProject",
                         station_breve="Fraglia Vela")
MALCESINE = dict(lat=45.7646, lon=10.8119, elevation=65,
                 station="malcesine_add", source="addicted",
                 addicted_slug="malcesine",
                 station_name="Malcesine (spiaggia) - Addicted Sports",
                 station_breve="spiaggia di Malcesine",
                 direzione_da=("malcesine", "T0193"))
# Campione del Garda, sulla sponda bresciana, di fronte a Malcesine. La
# centralina e' quella di Addicted Sports al Vela Club, sul lago: e' la
# stessa del suo storico (2017 in poi, gia' in archivio), quindi il modello
# impara sulla stessa raffica che poi mostra accanto.
#
# Due limiti dichiarati, che vengono dalla fonte e non da noi:
#   la serie e' ORARIA (media e massimo dell'ora), non a dieci minuti: la
#   curva del misurato e' piu' grossolana, e la raffica ricorrente non c'e';
#   la DIREZIONE misurata non esiste (Addicted pubblica solo quella prevista).
#   La direzione decide se un vento e' Ora o un nordico sinottico, e a
#   Torbole il 22% delle ore ventose pomeridiane NON sono Ora per direzione:
#   etichettare per sola ora del giorno sarebbe sbagliato una volta su
#   cinque. Quindi si prende in prestito da una centralina vicina che ce
#   l'ha - Malcesine, a quattro chilometri sull'altra sponda, e Torbole
#   prima del 2026, quando Malcesine non aveva la direzione. Misurato su
#   4.607 ore in comune: quando entrambe hanno vento concordano sul settore
#   il 100% delle volte di pomeriggio e il 99% di mattina. E' un prestito,
#   e store.obs_hours lo segna riga per riga (dir_prestito).
CAMPIONE = dict(lat=45.7577, lon=10.7397, elevation=66,
                station="campione", source="addicted", addicted_slug="campione",
                station_name="Campione del Garda (Vela Club) - Addicted Sports",
                station_breve="Vela Club Campione",
                direzione_da=("malcesine", "T0193"))

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
                          min_kn=10.0, planing_kn=14.0, target="hourly",
                          ora_pratica=6.0),
    "Malcesine-Ora": dict(MALCESINE, place="Malcesine", label="Malcesine · Ora",
                          regime="ORA", axis=LAKE_AXIS_ORA, window=(12, 19),
                          min_kn=11.0, planing_kn=14.0, target="hourly"),
    "Malcesine-Peler": dict(MALCESINE, place="Malcesine", label="Malcesine · Pelèr",
                            regime="PELER", axis=LAKE_AXIS_PELER, window=(5, 11),
                            min_kn=10.0, planing_kn=14.0, target="hourly",
                            ora_pratica=6.0),
    "Campione-Ora": dict(CAMPIONE, place="Campione", label="Campione · Ora",
                         regime="ORA", axis=LAKE_AXIS_ORA, window=(11, 19),
                         min_kn=11.0, planing_kn=14.0, target="hourly"),
    "Campione-Peler": dict(CAMPIONE, place="Campione", label="Campione · Pelèr",
                           regime="PELER", axis=LAKE_AXIS_PELER, window=(5, 11),
                           min_kn=10.0, planing_kn=14.0, target="hourly",
                           ora_pratica=6.0),
    # L'archivio pubblico di Malcesine e' giornaliero: da' la raffica massima
    # del giorno senza dire a che ora. E' comunque un bersaglio allenabile su
    # due anni, e "quanto tira di punta oggi" e' una domanda sensata.
    "Malcesine-Giorno": dict(MALCESINE_FRAGLIA, place="Malcesine",
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

PLACES = ["Torbole", "Malcesine", "Campione"]
SPOT_ORDER = ["Torbole-Ora", "Torbole-Peler",
              "Malcesine-Ora", "Malcesine-Peler", "Malcesine-Giorno",
              "Campione-Ora", "Campione-Peler"]

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
# serie ORARIA misurata (mavg, mmax) con i decimali. La direzione pubblicata
# LI' e' quella PREVISTA, non misurata, e non va usata come osservazione.
URL_ADDICTED_TORBOLE = "https://it.addicted-sports.com/forecast/gardasee/torbole/"

# E c'e' un terzo canale, che per due settimane non abbiamo visto. Gian:
# "sport addicted pubblica i dati in tempo reale ogni 10 minuti!". Ha ragione:
# la pagina d'insieme del lago interroga questo indirizzo, e lo dichiara lei
# stessa nel suo javascript. Risposta piccola, tutte le centraline in una
# richiesta, e un "interval" che dice ogni quanto la pagina lo rilegge.
#
# Per stazione: "live" (l'istante: avg, max, dir, temp) e "rec" (la finestra
# dichiarata: avg, max, dir, n campioni, min minuti). Si legge "rec", non
# "live": "rec" e' la media e il massimo su una finestra dichiarata - la
# stessa grandezza dei dieci minuti di Meteotrentino - mentre "live" e' uno
# scatto di un minuto, e due definizioni di "vento misurato" sulla stessa
# pagina sono il modo piu' sicuro di far leggere un numero per un altro.
#
# Qui la direzione E' misurata, ed e' la differenza che conta. Verificato il
# 19/09/2026 confrontando, nella stessa risposta, il campo del MODELLO (la
# mappa animata delle correnti, chiave "wind" allineata a "times") con la
# misura: il modello dava 334-343 gradi a tutte e cinque le stazioni - un
# campo liscio - e le misure davano 8, 358, 337, 10; e Capo Reamol, che il
# modello prevede come le altre, ha "live": null e "stale": true, cioe' la
# centralina che il 20 marzo 2025 ha smesso di misurare. Un campo previsto
# c'e' per tutti; una misura manca dove manca lo strumento.
URL_ADDICTED_LIVE = "https://it.addicted-sports.com/forecast/gardasee/?json=cams"
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
# La radice dell'impianto: csv.php e csvnoaa.php stanno accanto, e il lettore
# (sources/davis_csv.py) li compone da qui. Limone ha la stessa forma.
URL_MALCESINE_BASE = "https://stazioni.meteoproject.it/dati/malcesine/"

# --------------------------------------------------------------------------
# Limone sul Garda
# --------------------------------------------------------------------------
# Due sensori, e nessuno dei due basta da solo.
#
# Capo Reamol (Addicted Sports, sull'acqua a nord del paese) ha lo storico
# lungo - 90.891 ore dal 2014 - ma e' MORTA: l'ultima misura e' del 20 marzo
# 2025, e oggi la sua pagina serve la previsione con le letture tutte vuote
# (verificato: zero misure, mentre Campione nello stesso momento ne ha 22).
# Un archivio, non una centralina.
#
# Il Consorzio Turistico Limonese (MeteoSystem, Davis Vantage Pro 2) e' VIVA
# e pubblica con lo stesso pacchetto della Fraglia di Malcesine: csv.php a 15
# minuti, csvnoaa.php mensile dal settembre 2022. Ma il vento e' in KM/H, non
# in nodi - lo dice la sua pagina - e questo va dichiarato, non indovinato:
# un fattore 1,852 preso al contrario lascia numeri plausibili e sbagliati.
#
# MISURATO il 2026-09-19, e la risposta e' no: vedi docs/STRADE-CHIUSE.md.
# La centralina viva non vede il vento medio. A luglio 2026 le sue mediane
# orarie stanno fra 0,0 e 0,9 kn a OGNI ora e il 67% delle letture e'
# esattamente zero, mentre Campione negli stessi giorni va da 4,1 a 11,2 con
# la termica che sale. Registra qualche raffica, la media no. Una curva di
# scala non la salva: zero per qualunque fattore resta zero.
#
# L'unita' dichiarata qui sotto e' invece CONFERMATA, e vale la pena tenerla
# scritta: la pagina diceva "raffica giornaliera 12,9 km/h" e il file dello
# stesso giorno aveva massimo 12,9. Stesso numero, stessa unita'.
#
# Quindi Limone non e' in PLACES. Resta tutto pronto - il lettore, gli
# indirizzi, lo strumento di misura - per il giorno in cui a Limone comparira'
# un sensore che misura: allora e' una riga di configurazione, e la verifica
# si rifa' con strumenti/estrai-limone.py invece che da capo.
URL_LIMONE_BASE = "http://www.meteosystem.com/stazione/limonesulgarda/"
LIMONE_UNITA = "kmh"
LIMONE_NOAA_START = (2022, 9)
LIMONE_INTRADAY_START = (2022, 9)
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

# E accanto a live.json, sullo stesso ramo, i CAMPIONI del canale vivo.
#
# Serve perche' i due processi hanno due database separati, e per un motivo
# buono: le cache sono immutabili e si ripescano "la piu' recente", quindi un
# processo veloce che salvasse sopra rischierebbe di far ripartire quello
# lento da una copia priva dei modelli appena addestrati. La conseguenza pero'
# non era stata vista: i campioni a dieci minuti con la DIREZIONE misurata li
# legge il veloce, 144 volte al giorno, e li mette nel suo database; quello
# lento - che addestra e che archivia - li raccoglieva da se' quattro volte al
# giorno. Dell'unica serie che non si riscarica da nessuna parte ne salvavamo
# una su trentasei.
#
# Il ramo "live" e' gia' il canale fra i due processi: si riscrive da zero a
# ogni giro (un commit solo, niente storia che si gonfia), e ci passa gia'
# live.json. Ci passano anche i campioni, e il processo lento li rilegge.
LIVE_VIVO_URL = os.environ.get(
    "GARDAWIND_VIVO_URL",
    LIVE_JSON_URL.rsplit("/", 1)[0] + "/vivo.csv.gz")

# Quanti giorni di campioni tiene quel file. Il processo lento passa quattro
# volte al giorno: tre giorni sono un margine larghissimo, e restano pochi
# kilobyte. Se il processo lento restasse fermo piu' a lungo, si perderebbe
# l'eccedenza - ed e' scritto qui perche' sia una scelta e non una sorpresa.
LIVE_VIVO_GIORNI = 3

# L'indirizzo pubblico del sito. Serve SOLO alle anteprime dei link - quando
# la pagina viene condivisa in una chat, l'immagine e il titolo devono avere
# un indirizzo assoluto - e all'installazione sul telefono. Non entra in
# nessun calcolo. Vuoto = niente anteprima con immagine.
SITE_URL = os.environ.get("GARDAWIND_SITE_URL",
                          "https://giann0pann0.github.io/Garda-Wing/")

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
