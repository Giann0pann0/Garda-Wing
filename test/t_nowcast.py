#!/usr/bin/env python3
"""Banco a risposta nota per la persistenza intraday."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
HOME=tempfile.mkdtemp(prefix="gw-nowcast-")
os.environ["GARDAWIND_HOME"]=HOME

from gardawind import nowcast as N, store

n=okn=0
def ok(x,msg):
    global n,okn
    n+=1
    if x:
        okn+=1
        print("PASS "+msg)
    else:
        print("FAIL "+msg)

rows=[]
# errore +4 kn persistente: alpha 1 deve correggere perfettamente le ore dopo.
import datetime as dt
for y in (2024,2025):
    start=dt.date(y,1,1)
    for d in range(180):
        day=(start+dt.timedelta(days=d)).isoformat()
        for h in range(6,11):
            rows.append({"day":day,"year":y,"hour":h,"fc":10.0+h/10.0,"obs":14.0+h/10.0})
t=N.make_targets(rows,1.0)
ok(len(t)>0,"crea bersagli")
ok(max(abs(r["corrected"]-r["obs"]) for r in t)<1e-9,"usa solo scarto precedente e corregge")
ch=N.choose_alpha(rows)
ok(ch is not None and ch["alpha"]==1.0,"sceglie alpha 1 su risposta nota")

# Nessun dato produttivo all'inizio: gate chiuso con codice chiuso.
p=N.production_coverage("Torbole")
ok(p["state"]=="closed" and p["reason"]==N.REASON_PRODUCTION_HISTORY_SHORT,
   "gate prospettico chiuso senza storia")

# Archivio emesso: un'ora futura NON conta finche' non esiste l'osservato.
store.save_issued_profile("Torbole","2026-09-15T08:00:00Z",[
    {"key":"2026-09-15T09:00:00Z","wind":12.0,"gust":18.0}])
p0=N.production_coverage("Torbole")
ok(p0["n"]==0 and p0["days"]==0,"gate conta solo curve gia verificate")
# Quando arriva T0193 la stessa ora diventa verificabile.
store.connect().execute("INSERT INTO obs_hour(station,hour,wind_mean) VALUES(?,?,?)",
                        ("T0193","2026-09-15T09:00:00Z",14.0))
store.connect().commit()
store.save_issued_profile("Torbole","2026-09-15T08:00:00Z",[
    {"key":"2026-09-15T09:00:00Z","wind":13.0,"gust":19.0}])
r=store.connect().execute("select count(*) n,max(wind_kn) w from issued_profile").fetchone()
ok(r["n"]==1 and abs(r["w"]-13.0)<1e-9,"snapshot idempotente per run/ora")
p1=N.production_coverage("Torbole")
ok(p1["n"]==1 and p1["days"]==1,"ora emessa conta dopo osservazione reale")
# Il candidato non deve prendersi automaticamente il merito della persistenza.
t=N.make_targets(rows,1.0)
ok(all("persistence" in x and "static_bias" in x for x in t),
   "bersagli conservano persistenza e bias statico come riferimenti")

shutil.rmtree(HOME,ignore_errors=True)
raise SystemExit(0 if n==okn else 1)
