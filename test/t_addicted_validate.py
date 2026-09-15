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


# QC: un plateau alto e massivo viene segnalato ma non cancellato.
qc = V.qc_massimi_storici(c)
ok("torbole" in qc and qc["torbole"]["plateau_sospetti"],
   "QC trova il plateau estremo ripetuto")
ok(qc["torbole"]["plateau_sospetti"][0]["value"] == 49.6,
   "QC conserva il valore sospetto esplicito (49.6)")
ok(qc["torbole"]["ore_qc_ok"] < qc["torbole"]["n"],
   "le ore sospette non entrano nel sottoinsieme QC-ok")

# Modello di nullo: tre coppie identiche allo stesso istante non devono
# restare identiche dopo uno shift se la serie di prova non lo prevede.
sh = V.identita_shiftata_campione_brenzone(c, 7)
ok(sh["uguali"] == 0, "shift temporale rompe l'identita' artificiale")

# Ponte storico: il plateau sospetto non deve entrare nelle ore QC-ok.
prof = V.profilo_rafficosita_storica(c)
ok(prof["ore_escluse_qc"] >= 20, "profilo esclude il plateau dal ponte storico")
ok(prof["gruppi"]["peler_06_11"]["n"] >= 1, "profilo conserva la fascia Peler QC-ok")
ok(prof["gruppi"]["ora_11_20"]["n"] >= 1, "profilo conserva la fascia Ora QC-ok")

# Il gate di copertura resta chiuso su un campione minuscolo e dichiara le soglie.
gate = V.gate_proxy_gust_rec(c, min_ore=10, min_giorni=2, min_mesi=2)
ok(gate["pronto"] is False and gate["min_ore"] == 10,
   "gate proxy esplicito e chiuso senza copertura sufficiente")

# Calibrazione mensile: le due fasce devono restare separate e usare mese locale.
cal = V.calibrazione_media_mensile(c)
ok(cal["fascia_mensile"][("peler_06_11", 7)]["n"] == 1,
   "calibrazione mensile conserva Peler e mese locale")
ok(cal["fascia_mensile"][("ora_11_20", 7)]["n"] == 1,
   "calibrazione mensile conserva Ora e mese locale")

# Stabilita' ponte: servono almeno due punti per stimare una pendenza.
c.execute("INSERT INTO addicted_hour VALUES('torbole','2026-07-02T04:00:00Z',9,19)")
c.commit()
stab = V.stabilita_ponte_storico(c, min_n_mese=2)
ok(stab["peler_06_11"]["mesi_validi"] >= 1,
   "stabilita' ponte dichiara i mesi con copertura sufficiente")

# Il progresso del gate e' esplicito e limitato a 100% per ogni dimensione.
gate2 = V.gate_proxy_gust_rec(c, min_ore=10, min_giorni=2, min_mesi=2)
ok("progresso" in gate2 and 0.0 <= gate2["progresso_gate"] <= 1.0,
   "gate espone avanzamento normalizzato")
