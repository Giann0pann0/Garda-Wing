import sqlite3
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from gardawind import addicted_validate as V

def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)

m = V.metriche([(10, 8), (20, 18), (30, 28)])
ok(m["n"] == 3, "metriche conta le coppie")
ok(abs(m["bias"] + 2) < 1e-9, "bias candidato-riferimento")
ok(abs(m["mae"] - 2) < 1e-9, "MAE")
ok(abs(m["corr"] - 1) < 1e-9, "correlazione")

c = sqlite3.connect(":memory:")
c.execute("CREATE TABLE addicted_hour(station TEXT,hour TEXT,wind_mean_kn REAL,hourly_max_kn REAL)")
c.execute("CREATE TABLE obs_hour(station TEXT,hour TEXT,wind_mean REAL)")
c.execute("CREATE TABLE obs_sample(station TEXT,ts TEXT,wind_kn REAL,gust_kn REAL)")
for h,ref,sa in [
    ("2026-07-01T04:00:00Z", 10, 8),   # 06 locale, Peler
    ("2026-07-01T11:00:00Z", 15, 13),  # 13 locale, Ora
]:
    c.execute("INSERT INTO obs_hour VALUES('T0193',?,?,?)".replace(',?,?,?', ',?,?'), (h,ref))
    c.execute("INSERT INTO addicted_hour VALUES('torbole',?,?,?)", (h,sa,20))
# serie condivisa e un sentinel ripetuto
for i in range(25):
    h="2020-01-%02dT00:00:00Z" % (1 + i % 20)
    c.execute("INSERT OR REPLACE INTO addicted_hour VALUES('torbole',?,?,?)", (h,5,49.6))
for i in range(3):
    h="2026-01-0%dT00:00:00Z" % (i+1)
    c.execute("INSERT INTO addicted_hour VALUES('campione',?,?,?)", (h,5+i,10+i))
    c.execute("INSERT INTO addicted_hour VALUES('brenzone',?,?,?)", (h,5+i,10+i))
c.commit()

cm = V.confronto_media(c)
ok(cm["tutto"]["n"] == 2, "join media")
ok(cm["peler_06_11"]["n"] == 1, "fascia Peler in ora locale")
ok(cm["ora_11_20"]["n"] == 1, "fascia Ora in ora locale")
sp = V.valori_massimo_sospetti(c, min_repeat=20)
ok(sp and sp[0]["value"] == 49.6, "segnala il valore estremo ripetuto")
cb = V.identita_campione_brenzone(c)
ok(cb["n"] == 3 and cb["uguali"] == 3 and abs(cb["quota"]-1) < 1e-9,
   "riconosce serie Campione/Brenzone identica")

