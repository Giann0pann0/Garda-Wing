"""Previsto e misurato sullo stesso asse: il primo controllo del modello in diretta.

Quattro promesse, e sono tutte cose che un grafico fatto male direbbe male:

  1. l'osservato si ferma dove finisce il dato. Non viene prolungato fino a
     "adesso", non viene interpolato sui buchi: il senso della curva e' il
     confronto con la previsione, e un confronto con un dato inventato non e'
     un confronto.
  2. l'osservato entra nella SCALA. Una raffica misurata piu' alta del
     previsto deve stare dentro il disegno: la curva che conta di piu' non
     puo' essere quella che esce dal grafico.
  3. la raffica misurata dichiara QUALE raffica e'. La ricorrente a 30' e il
     massimo dell'ora non sono la stessa grandezza, e il massimo e' sempre il
     maggiore: scambiarle in silenzio gonfia la realta' rispetto alla
     previsione e fa sembrare il modello piu' sbagliato di quanto sia.
  4. la riga dello scarto confronta la stessa ORA. Non il picco, non la media
     del giorno. E non dice "in ritardo di quaranta minuti": un ritardo e' una
     stima di timing, e il timing qui ha semiampiezza sessanta minuti fuori
     campione - quel numero va guadagnato con le porte, non scritto perche'
     suona bene.
"""
import datetime as dt
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwsovra"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
shutil.rmtree("/tmp/gwsovra", ignore_errors=True)
os.makedirs("/tmp/gwsovra", exist_ok=True)

from gardawind import config, engine, store, web
from gardawind.util import iso_utc, local_day, utc_now

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)
UTC = dt.timezone.utc
store.init()

OGGI = local_day(utc_now())
ST = config.SPOTS["Torbole-Ora"]["station"]


def ora_utc(giorno, ora_locale):
    """L'ora UTC che corrisponde a quell'ora locale di quel giorno."""
    from gardawind.util import local_naive_to_utc
    naive = dt.datetime.fromisoformat(giorno + "T00:00:00") + dt.timedelta(hours=ora_locale)
    return local_naive_to_utc(naive)


def salva_ore(giorno, righe, ric=True):
    """righe: [(ora_locale, media, raffica)] -> obs_hour."""
    for ora, media, raffica in righe:
        t = ora_utc(giorno, ora)
        store.connect().execute(
            "INSERT OR REPLACE INTO obs_hour(station,hour,wind_mean,wind_max,"
            "gust_max,gust_rec,dir_deg,dir_const,n_samples) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (ST, iso_utc(t)[:13], media, media + 1.0,
             (raffica + 2.0) if raffica is not None else None,
             raffica if (ric and raffica is not None) else None,
             191.0, 0.8, 6))
    store.connect().commit()


# --------------------------------------------------------------------------
# 1. Solo le ore che esistono, e solo quelle di oggi
# --------------------------------------------------------------------------
salva_ore(OGGI, [(5, 6.0, 9.0), (6, 7.0, 11.0), (8, 9.0, 14.0)])   # manca la 7
from gardawind.util import day_shift
salva_ore(day_shift(OGGI, -1), [(14, 20.0, 30.0)])                  # ieri
salva_ore(day_shift(OGGI, 1), [(14, 21.0, 31.0)])                   # domani

O = engine.day_observed("Torbole", OGGI)
ore = [r["hour"] for r in O["righe"]]
ok(ore == [5, 6, 8], "solo le ore misurate di oggi, in ordine: %s" % ore)
ok(7 not in ore, "il buco delle 7 resta un buco: non viene riempito")
ok(all(r["hour"] != 14 for r in O["righe"]),
   "le ore di ieri e di domani non entrano nella giornata di oggi")
ok(O["ultima_ora"] == 8, "l'ultima ora misurata e' dichiarata (%s)" % O["ultima_ora"])

# --------------------------------------------------------------------------
# 2. Quale raffica, dichiarata
# --------------------------------------------------------------------------
ok(O["raffica_fonte"] == "ricorrente 30'",
   "con la ricorrente disponibile si usa quella: %r" % O["raffica_fonte"])
ok([r["gust"] for r in O["righe"]] == [9.0, 11.0, 14.0],
   "e i valori sono quelli della ricorrente, non i massimi")

shutil.rmtree("/tmp/gwsovra2", ignore_errors=True)
os.environ["GARDAWIND_HOME"] = "/tmp/gwsovra2"
store.close()
store.init()
salva_ore(OGGI, [(5, 6.0, 9.0), (6, 7.0, 11.0), (8, 9.0, 14.0)], ric=False)
O2 = engine.day_observed("Torbole", OGGI)
ok(O2["raffica_fonte"] == "massimo dell'ora",
   "senza ricorrente si ripiega sul massimo, e lo dice: %r" % O2["raffica_fonte"])
ok([r["gust"] for r in O2["righe"]] == [11.0, 13.0, 16.0],
   "e i valori sono i massimi (piu' alti della ricorrente), non mescolati")

# Una sola ora con la ricorrente su tre non basta: la serie non cambia
# definizione a metà strada.
shutil.rmtree("/tmp/gwsovra3", ignore_errors=True)
os.environ["GARDAWIND_HOME"] = "/tmp/gwsovra3"
store.close()
store.init()
salva_ore(OGGI, [(5, 6.0, 9.0)], ric=True)
salva_ore(OGGI, [(6, 7.0, 11.0), (8, 9.0, 14.0)], ric=False)
O3 = engine.day_observed("Torbole", OGGI)
ok(O3["raffica_fonte"] == "massimo dell'ora",
   "una ricorrente su tre ore non basta: si usa il massimo per tutta la serie")

ok(engine.day_observed("Torbole", day_shift(OGGI, 3))["righe"] == [],
   "una giornata futura non ha osservato, e non lo inventa")
ok(engine.day_observed("Luogo-Inesistente", OGGI)["righe"] == [],
   "un luogo senza centralina non esplode: torna vuoto")

# --------------------------------------------------------------------------
# 3. La riga dello scarto: stessa ora, e niente stime di ritardo
# --------------------------------------------------------------------------
previsione = [{"hour": h, "wind": 10.0 + h, "gust": 14.0 + h} for h in range(4, 21)]
osservato = {"raffica_fonte": "ricorrente 30'", "ultima_ora": 8,
             "righe": [{"hour": 6, "wind": 12.0, "gust": 18.0},
                       {"hour": 7, "wind": 13.0, "gust": 19.0},
                       {"hour": 8, "wind": 14.0, "gust": 20.0}]}
sc = web.scarto_line(previsione, osservato)
ok(sc["hour"] == 8, "si confronta l'ultima ora misurata (%s)" % sc["hour"])
ok(sc["previsto"] == 18.0 and sc["misurato"] == 14.0,
   "contro la previsione DELLA STESSA ORA: 18 previsti, 14 misurati")
ok(abs(sc["scarto"] - (-4.0)) < 1e-9, "scarto -4 kn (%s)" % sc["scarto"])
ok(sc["tendenza"] == "sale", "e la tendenza viene dalle due ultime ore misurate")
testo = web.scarto_words(sc)
ok("alle 08:00" in testo and "4 kn sotto previsione" in testo and "salendo" in testo,
   "la riga lo dice in italiano: %s" % testo)
ok("ritardo" not in testo and "minuti" not in testo,
   "e non inventa un ritardo in minuti, che sarebbe una stima di timing")

# Il picco previsto NON e' il riferimento: se lo fosse, lo scarto alle 6
# sarebbe enorme invece di -4.
sc6 = web.scarto_line(previsione, {"righe": [{"hour": 6, "wind": 12.0, "gust": 18.0}]})
ok(abs(sc6["scarto"] - (-4.0)) < 1e-9,
   "alle 6 lo scarto e' -4 contro le 6 previste, non contro il picco del giorno")
ok(sc6["tendenza"] is None,
   "con una sola ora misurata non si dichiara nessuna tendenza")
ok(web.scarto_line(previsione, None) is None
   and web.scarto_line(previsione, {"righe": []}) is None,
   "senza osservato non c'e' riga dello scarto")
ok(web.scarto_words(None) == "", "e il rendering di un None e' vuoto, non 'None'")

# Scarto piccolo: si dice "in linea", non "0 kn sotto previsione".
sc0 = web.scarto_line(previsione, {"righe": [{"hour": 8, "wind": 18.4, "gust": 22.0}]})
ok("in linea con la previsione" in web.scarto_words(sc0),
   "uno scarto sotto il nodo e mezzo e' 'in linea': %s" % web.scarto_words(sc0))

# --------------------------------------------------------------------------
# 4. Il disegno: l'osservato entra nella scala e si ferma
# --------------------------------------------------------------------------
bande = web.regime_bands("Torbole")
# Una raffica misurata di 40 kn, molto sopra il previsto: deve stare dentro.
oss_alto = {"raffica_fonte": "ricorrente 30'", "ultima_ora": 8,
            "righe": [{"hour": 6, "wind": 20.0, "gust": 38.0},
                      {"hour": 7, "wind": 22.0, "gust": 40.0},
                      {"hour": 8, "wind": 21.0, "gust": 39.0}]}
svg = web.place_chart("Torbole", previsione, bande, "cx", oggi=True,
                      osservato=oss_alto)
import re
# Le scritte del grafico portano una CLASSE e non un font-size scritto a
# mano: la loro dimensione dipende dalla larghezza dello schermo (un viewBox
# solo non puo' servire telefono e desktop), quindi il numero vive nel CSS.
# Questo controllo cercava il font-size e non trovava piu' niente: passava a
# "max None" e diceva che la scala non arrivava, mentre ci arrivava.
etichette = [float(v) for v in re.findall(
    r'text-anchor="end" class="t-s" fill="var\(--ink-3\)">(\d+)</text>', svg)]
ok(etichette and max(etichette) >= 40.0,
   "la scala arriva oltre la raffica misurata di 40 kn (max %s)"
   % (max(etichette) if etichette else None))

senza = web.place_chart("Torbole", previsione, bande, "cy", oggi=True)
ok("misurato" in svg and "misurato" not in senza,
   "la curva misurata compare solo quando c'e' l'osservato")
# Gli spessori si leggono da web.TRATTO: il rapporto fra le linee e'
# l'informazione, e un controllo che inseguisse numeri magici si romperebbe a
# ogni ritocco senza dire niente di vero.
W_MIS = 'stroke-width="%g"' % web.TRATTO["misurato"]
W_PREV = 'stroke-width="%g"' % web.TRATTO["previsto"]
OP = 'opacity="%g"' % web.OPACITA_PREVISTO
ok(W_MIS in svg, "la linea misurata c'e', con lo spessore dichiarato")
ok(web.TRATTO["misurato"] < web.TRATTO["previsto"]
   and web.OPACITA_PREVISTO < 0.5,
   "e non e' la piu' GROSSA: e' la piu' evidente perche' la previsione si"
   " sbiadisce (opacita' %g), non perche' la misura si ingrossa"
   % web.OPACITA_PREVISTO)
ok(OP in svg and OP not in senza,
   "la previsione si fa piu' tenue solo quando c'e' qualcosa con cui confrontarla")
# La legenda dice solo pieno/tenue: la definizione della raffica misurata
# (ricorrente a 30') sta nel cassetto dei dettagli della pagina, dove la
# spiegazione ha spazio. Qui si controlla che la legenda non sia tornata
# prolissa e che la distinzione misurato/previsto ci sia.
ok("pieno: misurato" in svg and "tenue: previsto" in svg,
   "la legenda distingue misurato e previsto, in quattro parole")
ok("ricorrente" not in svg,
   "e la definizione della raffica non sta piu' in legenda")
ok("ricorrente" in web.dettagli_panel("Torbole", []),
   "ma nel cassetto dei dettagli, dove ha spazio")
ok(svg.count(W_MIS) == 1,
   "una sola curva misurata del vento medio, non una per ora")

# L'osservato si ferma: nessun punto della curva misurata oltre le 8.
#
# Le curve sono percorsi cubici monotoni e non spezzate, quindi i vertici si
# leggono dai punti di ARRIVO dei segmenti (il terzo di ogni C, piu' la M
# iniziale): sono esattamente i punti dei dati, perche' questa interpolazione
# ci passa per forza. I due punti di controllo in mezzo non sono dati e non
# vanno contati.
def punti(sv, largh):
    for d in re.findall(r'<path d="([^"]+)" fill="none" '
                        r'stroke="var\(--pc\)" stroke-width="%s"' % largh, sv):
        fuori = []
        for pezzo in d.replace("M", " ").replace("L", " ").split("C"):
            coppie = pezzo.split()
            if coppie:
                fuori.append(tuple(float(v) for v in coppie[-1].split(",")))
        return fuori
    return []


pm = punti(svg, "%g" % web.TRATTO["misurato"])
pp = punti(svg, "%g" % web.TRATTO["previsto"])
ok(len(pm) == 3 and len(pp) == len(previsione),
   "tre punti misurati contro diciassette previsti (%d / %d)" % (len(pm), len(pp)))
ok(max(p[0] for p in pm) < max(p[0] for p in pp),
   "e la curva misurata finisce prima di quella prevista")
