import os
import sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from gardawind import features as F, config
from gardawind.util import parse_dt_any, local_hour, local_day
ok=lambda c,m: print(("PASS " if c else "FAIL ")+m)

# finestra estiva: 11-19 locali = 09-17 UTC
k=F.window_hours("2026-07-15",11,19)
ok(k[0]=="2026-07-15T09:00:00Z" and k[-1]=="2026-07-15T17:00:00Z" and len(k)==9, "finestra estiva -> UTC-2 (%s..%s n=%d)"%(k[0],k[-1],len(k)))
# finestra invernale: 11-19 locali = 10-18 UTC
k2=F.window_hours("2026-01-15",11,19)
ok(k2[0]=="2026-01-15T10:00:00Z" and len(k2)==9, "finestra invernale -> UTC-1 (%s n=%d)"%(k2[0],len(k2)))
# tutte le chiavi appartengono al giorno locale giusto e all'ora giusta
ok(all(local_day(parse_dt_any(x))=="2026-07-15" and 11<=local_hour(parse_dt_any(x))<=19 for x in k), "coerenza giorno/ora locale")
# giorno del cambio ora legale (29/03/2026)
k3=F.window_hours("2026-03-29",5,11)
ok(len(k3)>=6, "giorno di cambio ora legale non degenera (n=%d)"%len(k3))
# span notturno che attraversa la mezzanotte
s=F.span_hours("2026-07-15",-1,21,0,5)
hrs=[local_hour(parse_dt_any(x)) for x in s]
days=set(local_day(parse_dt_any(x)) for x in s)
ok(days=={"2026-07-14","2026-07-15"} and all(h>=21 or h<=5 for h in hrs), "span notturno 21->05 (%d ore, giorni %s)"%(len(s),sorted(days)))

# vettore feature su dati sintetici
import math
hours={}
for x in F.window_hours("2026-07-15",0,23):
    h=local_hour(parse_dt_any(x))
    hours[x]={"w10":6+8*math.exp(-((h-15)/3)**2),"d10":205,"w925":12,"d925":200,"w700":18,"d700":210,
              "t2m":28,"t850":14,"t925":20,"dew":15,"cloud":20,"cloud_low":10,"rad":700 if 8<=h<=18 else 0,
              "precip":0,"mslp":1015,"g10":None,"rh":50,"w850":14,"d850":205}
ctx={x:{p:{"mslp":1014 if config.CONTEXT_POINTS[p][2]=="north" else 1016,
           "t2m":24 if config.CONTEXT_POINTS[p][2]=="north" else 31,"cloud":10,"rad":700}
        for p in config.CONTEXT_POINTS} for x in hours}
f=F.daily_features("Torbole-Ora","2026-07-15",hours,ctx,persist=14.0,persist_age=3)
ok(f is not None, "daily_features produce un vettore")
ok(abs(f["along925"]-12*math.cos(math.radians(200-204)))<0.1, "along925 quasi allineato (%.2f)"%f["along925"])
ok(f["pgrad"]<0, "pgrad negativo = alta a sud -> favorevole all'Ora (%.2f)"%f["pgrad"])
ok(f["tgrad"]>6, "tgrad positivo = pianura piu' calda (%.2f)"%f["tgrad"])
ok(f["stab850"]<0, "stab850 negativo = instabile (%.1f)"%f["stab850"])
ok(f["persist_obs"]==14.0 and f["persist_age"]==3.0, "memoria passata con la sua eta' (%.0f kn, %.0f gg)"%(f["persist_obs"],f["persist_age"]))
fd=F.daily_features("Torbole-Ora","2026-07-15",hours,ctx)
ok(fd["persist_obs"]==0.0 and fd["persist_age"]==1.0, "senza memoria dichiarata: eta' 1 giorno per difetto")
ok("persist" not in f, "la vecchia feature persist non esiste piu'")
v=F.vector(f,"full")
ok(len(v)==len(F.TIER_FULL) and all(isinstance(z,float) for z in v), "vettore full completo (%d)"%len(v))
ok(len(F.vector(f,"bias"))==1 and len(F.vector(f,"reduced"))==8, "tier bias/reduced")
# copertura insufficiente -> None
few={k:hours[k] for k in list(hours)[:2]}
ok(F.daily_features("Torbole-Ora","2026-07-15",few,ctx) is None, "copertura insufficiente -> None")
sh=F.hourly_shape("Torbole-Ora","2026-07-15",hours)
ok(abs(max(v for _k,v in sh)-1.0)<1e-9, "profilo orario normalizzato a 1")
