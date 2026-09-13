import os, sys
os.environ["GARDAWIND_HOME"]="/tmp/gwintra"
import shutil; shutil.rmtree("/tmp/gwintra", ignore_errors=True)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from gardawind.sources import malcesine as MC
from gardawind import store, aggregate, config
from gardawind.util import parse_dt_any, local_hour, local_day
ok=lambda c,m: print(("PASS " if c else "FAIL ")+m)
store.init()

# CSV REALE catturato dal sito (12 settembre 2026, passo 30 min)
csv = ('Data;Ora;Temp;Min;Max;Umid;"Dew pt";Vento;Dir;Raffica;"Dir Raff.";Press;Pioggia;Int.Pio.;Rad.Sol.\n'
       '12/9/2026;0:00;20.2;20.2;20.4;82;16.6;0.0;SE;1.7;SE;1021.7;0.0;0.0;-\n'
       '12/9/2026;0:30;20.3;20.1;20.3;83;16.9;0.0;ESE;2.6;ESE;1021.8;0.0;0.0;-\n'
       '12/9/2026;15:00;23.7;23.4;23.7;71;17.9;9.6;SW;16.5;WSW;1021.8;0.0;0.0;620\n'
       '12/9/2026;15:30;23.9;23.7;24.0;68;17.5;9.6;WSW;17.4;WSW;1021.6;0.0;0.0;590\n'
       '12/9/2026;23:30;20.7;20.4;20.7;76;15.9;1.7;ESE;5.2;E;1022.7;0.0;0.0;-\n'
       '"Unita di misura"\n'
       '"Temperatura: C";;"Vento: kts";;"Pressione: hPa"\n')
MC.fetch_text = lambda *a, **k: csv
rows = MC.fetch_intraday(9, 2026)
ok(len(rows)==5, "righe intraday lette: %d"%len(rows))
ts,w,g,d = rows[2]
ok(ts=="2026-09-12T13:00:00Z", "15:00 locali estive -> 13:00 UTC (%s)"%ts)
ok(w==9.6 and g==16.5, "vento %.1f e raffica %.1f gia' in nodi, nessuna conversione"%(w,g))
ok(d==225.0, "SW -> 225 gradi")
ok(rows[0][1]==0.0 and rows[0][2]==1.7, "la calma (0.0 kn) non viene scambiata per dato mancante")

# le righe di intestazione unita' non devono entrare
ok(all(parse_dt_any(r[0]) is not None for r in rows), "nessuna riga spuria")

# aggregazione: 15:00 e 15:30 finiscono nella stessa ora UTC
store.save_samples("malcesine", rows, "test-intraday")
n = aggregate.aggregate_station("malcesine")
hours = store.obs_hours("malcesine")
h13 = [h for h in hours if h["hour"]=="2026-09-12T13:00:00Z"][0]
ok(abs(h13["wind_mean"]-9.6)<1e-9 and h13["gust_max"]==17.4 and h13["n_samples"]==2,
   "ora aggregata: media %.1f, raffica max %.1f, %d campioni"%(h13["wind_mean"],h13["gust_max"],h13["n_samples"]))
ok(abs(h13["dir_deg"]-236.25)<1.0, "direzione media vettoriale SW+WSW = %.1f"%h13["dir_deg"])

# i mesi partono da marzo 2026
import datetime as dt
ms = MC.intraday_months(dt.date(2026,9,13))
ok(ms[0]==(9,2026) and ms[-1]==(3,2026) and len(ms)==7, "mesi intraday: da %s a %s (%d)"%(ms[-1],ms[0],len(ms)))
