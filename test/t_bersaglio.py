"""Il bersaglio del modello e' la finestra UTILE, non quella del regime.

Il difetto che questo file impedisce di rimettere: il modello del Peler
imparava sul massimo delle medie orarie fra le 04 e le 10, il riquadro
giudica dalle 07:20 (estate) o dalle 08 (inverno). Misurato: 330 giornate su
3.015 "entrate" per il modello e "non navigabili" per la scheda, l'11%, e
d'inverno una su sei.

Qui si costruiscono due giornate d'inverno e una d'estate e si pretende che
il bersaglio le legga come le legge la scheda.
"""
import datetime as dt
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwbersaglio"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
shutil.rmtree("/tmp/gwbersaglio", ignore_errors=True)
os.makedirs("/tmp/gwbersaglio", exist_ok=True)

from gardawind import config, engine, orari, store
from gardawind.util import iso_utc, local_naive_to_utc

passati = 0


def ok(c, m):
    global passati
    if c:
        passati += 1
        print("PASS " + m)
    else:
        print("FAIL " + m)


store.init()
SPOT = "Torbole-Peler"
ST = config.SPOTS[SPOT]["station"]
# La direzione del banco di prova NON sta esattamente sull'asse osservato.
# Ci stava, e cosi' il filtro di settore non poteva sbagliare: giudicare una
# direzione misurata con l'asse preso dalla mappa (24 gradi) invece di quello
# osservato dalla centralina (54) sposta il bersaglio di trenta gradi, e con la
# direzione scritta sull'asse i due riferimenti erano indistinguibili. Qui la
# direzione e' dentro il settore di axis_obs (55 gradi di scarto su 70) e FUORI
# da quello dell'asse geometrico (85): se qualcuno tornasse a usare `axis`,
# queste giornate smetterebbero di contare e il controllo cade.
ASSE = config.SPOTS[SPOT]["axis_obs"] + 55.0


def salva_ore(giorno, righe):
    """righe: [(ora_locale, media)] -> obs_hour, direzione nel settore."""
    for ora, media in righe:
        naive = dt.datetime.fromisoformat(giorno + "T00:00:00") + dt.timedelta(hours=ora)
        t = local_naive_to_utc(naive)
        store.connect().execute(
            "INSERT OR REPLACE INTO obs_hour(station,hour,wind_mean,wind_max,"
            "gust_max,gust_rec,dir_deg,dir_const,n_samples) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (ST, store.chiave_ora(iso_utc(t)), media, media + 1.0, None, None,
             ASSE, 0.9, 6))
    store.connect().commit()


# Una giornata di dicembre: Peler forte alle 5 e alle 6, al buio; niente dopo.
# Il regime (04-10) la vede "entrata". La finestra utile - dalle 08 - no.
BUIO = "2025-12-20"
salva_ore(BUIO, [(4, 12.0), (5, 14.0), (6, 13.0), (7, 9.0), (8, 6.0),
                 (9, 5.0), (10, 4.0)])
# Una giornata di dicembre con il Peler che regge fino alle 9: entrata.
CHIARO = "2025-12-21"
salva_ore(CHIARO, [(4, 12.0), (5, 14.0), (6, 13.0), (7, 12.0), (8, 12.0),
                   (9, 11.0), (10, 8.0)])
# Una di luglio con il vento solo alle 5: al buio anche d'estate.
ESTATE = "2025-07-10"
salva_ore(ESTATE, [(4, 13.0), (5, 14.0), (6, 7.0), (7, 6.0), (8, 6.0),
                   (9, 5.0), (10, 5.0)])

targets = engine._compute_targets(SPOT)
a, b = orari.finestra_utile_del_giorno(SPOT, BUIO)
ok(a >= 8 * 60 - 1, "a dicembre la finestra utile del Peler comincia alle otto"
   " (%02d:%02d)" % (a // 60, a % 60))

peak, entrato, _h, _on = targets[BUIO]
ok(not entrato,
   "quattordici nodi alle cinque di dicembre NON sono un Peler entrato:"
   " la scheda direbbe no, e il modello impara no")
ok(peak < 10.0,
   "e il livello e' quello della finestra utile (%.1f), non i 14 delle cinque"
   % peak)

peak2, entrato2, _h2, _on2 = targets[CHIARO]
ok(entrato2 and peak2 >= 11.0,
   "mentre un Peler che regge fino alle nove e' entrato, a %.0f kn" % peak2)

ok(ESTATE in targets and not targets[ESTATE][1],
   "e a luglio, con l'ora pratica alle sei, il vento delle cinque non conta")

# La definizione della finestra e' una: orari.finestra_utile_del_giorno. Se
# engine.py se ne scrivesse una seconda, questo controllo lo direbbe.
import inspect
src = inspect.getsource(engine._compute_targets)
ok("finestra_utile_del_giorno(" in src,
   "il bersaglio chiama la finestra utile, non ne riscrive una")
ok("PERSISTENZA_MIN" in src,
   "e la soglia di appartenenza di un'ora alla finestra e' la persistenza")


# Il riferimento resta disponibile SOLO per il confronto: con la finestra del
# regime la giornata al buio torna "entrata", e questo e' esattamente il
# numero che il confronto deve poter mostrare.
prima = engine._compute_targets(SPOT, finestra="regime")
ok(prima[BUIO][1] and prima[BUIO][0] >= 14.0,
   "con la finestra del regime la stessa giornata era 'entrata' a 14 kn:"
   " e' il riferimento del confronto, e vive solo li'")
ok(engine.BERSAGLIO == "utile",
   "e il prodotto usa la finestra utile: BERSAGLIO = %r" % engine.BERSAGLIO)
print("%d controlli sul bersaglio" % passati)
