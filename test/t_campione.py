"""Campione: la terza localita', con la direzione in prestito.

Tre cose da difendere:

  1. una localita' e' una riga di config: pagina, navigazione, file, riquadri
     e grafici nascono da PLACES/SPOTS e non vanno toccati altrove;
  2. la direzione che Addicted non misura si prende in prestito da una
     centralina vicina, in UN posto (store.obs_hours), dichiarata riga per
     riga, e nella tabella non si scrive niente;
  3. lo storico Addicted diventa osservato solo per le stazioni che hanno
     Addicted come fonte, e non sovrascrive il canale vivo.
"""
import datetime as dt
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwcampione"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
shutil.rmtree("/tmp/gwcampione", ignore_errors=True)
os.makedirs("/tmp/gwcampione", exist_ok=True)

from gardawind import config, engine, store, web
from gardawind.sources import addicted
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

# ---- 1. una riga di config -------------------------------------------------
ok("Campione" in config.PLACES and config.PLACES.index("Campione") == 2,
   "Campione e' la terza localita'")
ok({"Campione-Ora", "Campione-Peler"} <= set(config.SPOT_ORDER),
   "con i suoi due regimi")
ok(config.SPOTS["Campione-Ora"]["station"] == "campione"
   and config.SPOTS["Campione-Ora"]["source"] == "addicted",
   "la centralina e' quella Addicted del Vela Club")
ok(engine.stazioni_addicted() == [("campione", "campione")],
   "ed e' l'unica con Addicted come fonte: Torbole resta Meteotrentino")
ok(web._slug("Campione") == "campione" and 'href="/campione"' in web.nav_luoghi("Torbole"),
   "la pagina e la navigazione nascono da config")
ok(addicted.url_json("2026-09-18", "campione")
   == "https://it.addicted-sports.com/forecast/gardasee/campione/?json=wind&from=2026-09-18",
   "l'indirizzo della serie oraria e' quello della stazione, sullo stesso schema")
ok(addicted.url_json("2026-09-18") == addicted.url_json("2026-09-18", "torbole"),
   "e senza stazione resta Torbole, com'era")
ok("body.p3{" in web.CSS, "la terza localita' ha il suo colore")


# ---- 2. la direzione in prestito -------------------------------------------
def ora(giorno, h):
    naive = dt.datetime.fromisoformat(giorno + "T00:00:00") + dt.timedelta(hours=h)
    return iso_utc(local_naive_to_utc(naive))[:13]


G = "2026-07-10"
# Campione: vento senza direzione. Malcesine: direzione solo alle 14 e 15.
# Torbole: direzione a tutte le ore, ma diversa - deve entrare solo dove
# Malcesine manca.
store.upsert_obs_hours("campione", [
    {"hour": ora(G, h), "wind_mean": 15.0, "wind_max": None, "gust_max": 24.0,
     "gust_rec": None, "dir_deg": None, "dir_const": None, "n_samples": 6}
    for h in (13, 14, 15, 16)])
store.upsert_obs_hours("malcesine", [
    {"hour": ora(G, h), "wind_mean": 14.0, "wind_max": 15.0, "gust_max": 22.0,
     "gust_rec": None, "dir_deg": 190.0, "dir_const": 0.95, "n_samples": 6}
    for h in (14, 15)])
store.upsert_obs_hours("T0193", [
    {"hour": ora(G, h), "wind_mean": 13.0, "wind_max": 14.0, "gust_max": 20.0,
     "gust_rec": None, "dir_deg": 200.0, "dir_const": 0.9, "n_samples": 6}
    for h in (13, 14, 15, 16)])

righe = {r["hour"]: r for r in store.obs_hours("campione")}
ok(len(righe) == 4, "le quattro ore di Campione ci sono")
ok(righe[ora(G, 14)]["dir_deg"] == 190.0 and righe[ora(G, 14)]["dir_prestito"] == "malcesine",
   "alle 14 la direzione viene da Malcesine, e lo dice")
ok(righe[ora(G, 13)]["dir_deg"] == 200.0 and righe[ora(G, 13)]["dir_prestito"] == "T0193",
   "alle 13, dove Malcesine non c'e', viene da Torbole, e lo dice")
ok(righe[ora(G, 14)]["dir_const"] == 0.95,
   "e con la direzione viaggia la sua costanza")
grezze = {r["hour"]: r for r in store._obs_hours_grezze("campione")}
ok(all(r["dir_deg"] is None for r in grezze.values()),
   "nella tabella non si scrive niente: obs_hour di Campione resta senza direzione")
ok(all(r["dir_prestito"] is None for r in store.obs_hours("T0193")),
   "e Torbole, che la misura, non ha prestiti")
# Il bersaglio del modello legge da store.obs_hours: con la direzione in
# prestito nel settore dell'Ora la giornata e' "entrata".
targets = engine._compute_targets("Campione-Ora")
ok(G in targets and targets[G][1],
   "il bersaglio vede un Ora entrato a Campione grazie alla direzione in prestito")
store.upsert_obs_hours("T0193", [
    {"hour": ora(G, h), "wind_mean": 13.0, "wind_max": 14.0, "gust_max": 20.0,
     "gust_rec": None, "dir_deg": 20.0, "dir_const": 0.9, "n_samples": 6}
    for h in (13, 16)])
store.upsert_obs_hours("malcesine", [
    {"hour": ora(G, h), "wind_mean": 14.0, "wind_max": 15.0, "gust_max": 22.0,
     "gust_rec": None, "dir_deg": 20.0, "dir_const": 0.95, "n_samples": 6}
    for h in (14, 15)])
targets = engine._compute_targets("Campione-Ora")
ok(G in targets and not targets[G][1],
   "e con un nordico sulle centraline vicine quello stesso vento NON e' Ora")
ok("prestito" in web.dettagli_panel("Campione", []) and "Malcesine" in web.dettagli_panel("Campione", []),
   "il cassetto dei dettagli dichiara il prestito")
ok("prestito" not in web.dettagli_panel("Torbole", []),
   "e a Torbole no")

# ---- 3. lo storico Addicted diventa osservato -------------------------------
c = store.connect()
for h, w, g in ((10, 8.0, 14.0), (11, 9.0, 15.0), (14, 99.0, 99.0)):
    c.execute("INSERT OR REPLACE INTO addicted_hour(station,hour,wind_mean_kn,"
              "hourly_max_kn,source,series_group,raw_origin) VALUES(?,?,?,?,?,?,?)",
              ("campione", ora(G, h) + ":00:00Z", w, g, "addicted-sports-history",
               "campione", "prova"))
    c.execute("INSERT OR REPLACE INTO addicted_hour(station,hour,wind_mean_kn,"
              "hourly_max_kn,source,series_group,raw_origin) VALUES(?,?,?,?,?,?,?)",
              ("torbole", ora(G, h) + ":00:00Z", w, g, "addicted-sports-history",
               "torbole", "prova"))
c.commit()
esito = engine.promuovi_storico_addicted()
ok(esito == {"campione": 2}, "promosse le ore che mancavano, e solo quelle: %s" % esito)
righe = {r["hour"]: r for r in store._obs_hours_grezze("campione")}
ok(righe[ora(G, 10)]["wind_mean"] == 8.0 and righe[ora(G, 10)]["gust_max"] == 14.0
   and righe[ora(G, 10)]["n_samples"] == engine.N_CAMPIONI_ORA_ADDICTED,
   "con medio, massimo e il numero di campioni dichiarato")
ok(righe[ora(G, 14)]["wind_mean"] == 15.0,
   "l'ora che c'era gia' dal canale vivo NON viene sovrascritta dallo storico")
ok(not store._obs_hours_grezze("torbole") and
   all(r["wind_mean"] == 13.0 for r in store._obs_hours_grezze("T0193")),
   "e Torbole non viene toccata: la sua pagina mostra Meteotrentino, non Addicted")

# Il canale vivo scrive obs_hour E un campione per ora, senza direzione.
n = engine.salva_ore_addicted("campione", [(ora(G, 17) + ":00:00Z", 12.0, 19.0, None)])
ok(n == 1 and store._obs_hours_grezze("campione", ora(G, 17), ora(G, 17))[0]["wind_mean"] == 12.0,
   "la lettura viva finisce in obs_hour")
camp = list(c.execute("SELECT wind_kn, gust_kn, dir_deg, source FROM obs_sample "
                      "WHERE station='campione'"))
ok(len(camp) == 1 and camp[0][0] == 12.0 and camp[0][2] is None
   and camp[0][3] == "addicted-json",
   "e in obs_sample, cosi' l'adesso ha da leggere - senza direzione inventata")
print("%d controlli su Campione" % passati)
