import os, sys, math, random, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from gardawind import regimes as R, config
from gardawind.util import angle_diff
ok=lambda c,m: print(("PASS " if c else "FAIL ")+m)

def win(hours, wind, direction, const=0.9, gust=None):
    return [{"hour":h,"wind_mean":wind,"gust_max":gust or wind*1.35,
             "dir_deg":direction,"dir_const":const} for h in hours]

# --- i casi che contano ---
r=R.classify_window(win(range(5,11), 15.0, 24.0))
ok(r["classe"]==R.PELER, "15 kn da NNE al mattino -> Pelèr (%s)"%r["classe"])

r=R.classify_window(win(range(13,19), 18.0, 204.0))
ok(r["classe"]==R.ORA, "18 kn da SSO al pomeriggio -> Ora (%s)"%r["classe"])

# IL CASO CHE LA 3.5 SBAGLIAVA: discendente da NO
r=R.classify_window(win(range(6,12), 22.0, 325.0))
ok(r["classe"]==R.NORD_OVEST, "22 kn da NO al mattino -> vento da NO, NON Pelèr (%s)"%r["classe"])
ok("nome_locale" in r and "Ballino" in r["nome_locale"], "nome locale proposto come ipotesi: %s"%r.get("nome_locale"))
ok(angle_diff(325, config.LAKE_AXIS_PELER)<70, "...e con il settore a +/-70 della 3.5 sarebbe caduto dentro al Pelèr (scarto %.0f gradi)"%angle_diff(325,config.LAKE_AXIS_PELER))

r=R.classify_window(win(range(5,11), 16.0, 180.0))
ok(r["classe"]==R.SUD_SINOTTICO, "16 kn da sud al mattino -> meridionale sinottico (%s)"%r["classe"])

r=R.classify_window(win(range(13,19), 16.0, 20.0))
ok(r["classe"]==R.NORD_SINOTTICO, "16 kn da nord alle 15 -> settentrionale sinottico, non Pelèr (%s)"%r["classe"])

r=R.classify_window(win(range(5,11), 3.0, 24.0))
ok(r["classe"]==R.CALMA, "3 kn -> calma (%s)"%r["classe"])

r=R.classify_window(win(range(5,11), 15.0, 24.0, const=0.3))
ok(r["classe"]==R.VARIABILE, "direzione instabile -> variabile, non forzata in un regime (%s)"%r["classe"])

r=R.classify_window(win([5,6], 15.0, 24.0))
ok(r["classe"]==R.VARIABILE, "solo due ore sopra soglia con finestra corta -> non e' un regime")

# ambiguita' al bordo del settore
r=R.classify_window(win(range(5,11), 15.0, 24.0+50.0))
ok(r.get("ambiguo") is True and r["qualita"]<=0.6,
   "vicino al bordo -> marcato ambiguo con qualita' ridotta (%.1f)"%r["qualita"])

# --- studio dei settori su 14 anni sintetici ---
random.seed(5)
classified={}
for i in range(2000):
    day="%04d-%02d-%02d"%(2012+i//365, 1+(i//30)%12, 1+i%28)
    u=random.random()
    if u<0.35: d, p = random.gauss(24,18), random.uniform(10,24)      # Peler
    elif u<0.55: d, p = random.gauss(204,20), random.uniform(10,26)   # Ora
    elif u<0.65: d, p = random.gauss(322,12), random.uniform(12,28)   # NO
    else: d, p = random.uniform(0,360), random.uniform(6,12)          # resto
    cls = R.classify_window(win(range(5,11), p, d%360))["classe"]
    classified[day]={"peak":p,"dir":d%360,"classe":cls,"peak_hour":7,"constancy":.9}
st=R.sector_study(classified, config.LAKE_AXIS_PELER)
ok(st is not None and len(st["soglie"])==5, "studio dei settori su %d giornate ventose"%st["n"])
print("   soglia | dentro | picco med | classe dominante | purezza")
for row in st["soglie"]:
    print("   %5.0f  |  %4d  |   %5.1f   | %-16s |  %.0f%%"%(
        row["deg"], row["n_dentro"], row["picco_mediano_dentro"], row["classe_dominante"], row["purezza"]*100))
pur={r["deg"]:r["purezza"] for r in st["soglie"]}
ok(pur[45.0] > pur[90.0], "un settore stretto e' piu' puro di uno largo (%.0f%% a 45 vs %.0f%% a 90)"%(pur[45]*100,pur[90]*100))
ok("per_stagione" in st and st["per_stagione"], "distribuzione anche per stagione")

s=R.summary(classified)
print("   classi trovate:", ", ".join("%s %d (%.0f%%)"%(x["etichetta"],x["n"],x["quota"]*100) for x in s[:5]))
ok(len(s)>=4, "la tassonomia distingue almeno quattro classi")
