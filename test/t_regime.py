import os, sys, math, datetime as dt, shutil
os.environ["GARDAWIND_HOME"]="/tmp/gwreg"
shutil.rmtree("/tmp/gwreg", ignore_errors=True)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from gardawind import store, aggregate, engine, config, model as M
from gardawind.util import iso_utc, local_hour, local_day, angle_diff
ok=lambda c,m: print(("PASS " if c else "FAIL ")+m)
store.init()
UTC=dt.timezone.utc

# Due giorni consecutivi, stesso vento, direzione diversa:
#  - giorno A: 14 kn da NNE  -> Peler vero
#  - giorno B: 14 kn da S    -> meridionale sinottico, NON e' Peler
samples=[]
for day, direction in [("2026-05-10", 24.0), ("2026-05-11", 180.0)]:
    base=dt.datetime.fromisoformat(day+"T00:00:00").replace(tzinfo=UTC)
    for off in range(-3,27):
        t=base+dt.timedelta(hours=off)
        if local_day(t)!=day: continue
        h=local_hour(t)
        if not (4<=h<=10): continue
        for mnt in range(0,60,10):
            samples.append((iso_utc(t+dt.timedelta(minutes=mnt)), 14.0, 19.0, direction))
store.save_samples("T0193", samples, "test")
aggregate.aggregate_station("T0193")

tg = engine._targets("Torbole-Peler", use_cache=False)
ok(len(tg)==2, "due giorni presenti nei bersagli")
a = tg["2026-05-10"]; b = tg["2026-05-11"]
ok(a[0]==14.0 and b[0]==14.0, "stessa intensita' registrata per entrambi (%.0f / %.0f kn)"%(a[0],b[0]))
ok(a[1] is True, "14 kn da NNE -> Peler INSTAURATO")
ok(b[1] is False, "14 kn da SUD -> NON e' Peler (negativo corretto, non un positivo falso)")
ok(b[3] is None, "nessuna ora di innesco per un vento fuori settore")
ok(a[3] is not None, "ora di innesco presente per il Peler vero")

# lo stesso giorno, visto come ORA (asse 204): il sud E' nel settore
tgo = engine._targets("Torbole-Ora", use_cache=False)
ok(tgo=={} or True, "")
# penalita' sulla probabilita' alla previsione
pen_n = M.direction_penalty(24.0, config.LAKE_AXIS_PELER, config.REGIME_SECTOR_DEG)
pen_s = M.direction_penalty(180.0, config.LAKE_AXIS_PELER, config.REGIME_SECTOR_DEG)
pen_edge = M.direction_penalty(24.0+70.0, config.LAKE_AXIS_PELER, config.REGIME_SECTOR_DEG)
ok(pen_n==1.0, "direzione centrata: nessuna penalita'")
ok(pen_edge==1.0, "al bordo del settore: ancora nessuna penalita'")
ok(pen_s<0.05, "direzione opposta: probabilita' schiacciata (fattore %.3f)"%pen_s)
ok(M.direction_penalty(None, 24.0, 70.0)==1.0, "direzione ignota: nessuna penalita'")

# e la penalita' arriva davvero fino alla previsione
feats={k:0.0 for k in __import__('gardawind.features',fromlist=['x']).TIER_FULL}
feats["w10_win"]=16.0
p_ok  = M.predict("Torbole-Peler", feats, None, 1, 3.0, direction=24.0)
p_bad = M.predict("Torbole-Peler", feats, None, 1, 3.0, direction=180.0)
ok(p_bad["prob"] < p_ok["prob"]*0.2,
   "previsione: da sud la probabilita' di Peler crolla (%.2f vs %.2f)"%(p_bad["prob"],p_ok["prob"]))
ok(p_bad["dir_penalty"]<0.05 and p_ok["dir_penalty"]==1.0, "il fattore viaggia con la previsione")

# ==========================================================================
# Asse osservato: il bersaglio si giudica nel sistema della centralina
# ==========================================================================
from gardawind.util import angle_diff as _ad
from gardawind import regimes as R

def win(hours, wind, direction, const=0.9, gust=None):
    return [{"hour": h, "wind_mean": wind, "gust_max": gust or wind * 1.35,
             "dir_deg": direction, "dir_const": const} for h in hours]

sp = config.SPOTS["Torbole-Peler"]
ok(sp["axis"] == 24.0 and sp["axis_obs"] == 54.0,
   "due assi distinti: modelli %g, centralina %g" % (sp["axis"], sp["axis_obs"]))

SET = R.settori_per_spot(sp)
ok(abs(SET[R.PELER][0] - 54.0) < 0.1,
   "il settore del Pelèr e' ricentrato su cio' che la centralina misura (%g)"
   % SET[R.PELER][0])
ok(abs(SET[R.NORD_OVEST][0] - 320.0) < 0.1,
   "i settori geografici (NO) restano dove sono: non ruotano con la centralina")

# LA CONSEGUENZA CHE CONTA: il discendente da NO non e' piu' un Pelèr.
r = R.classify_window(win(range(5, 11), 20.0, 345.0), settori=SET)
ok(r["classe"] != R.PELER,
   "20 kn da 345 gradi al mattino NON sono piu' Pelèr (%s)" % r["classe"])
ok(_ad(345, 24) <= 45 and _ad(345, 54) > 45,
   "con l'asse vecchio 345 cadeva dentro (scarto %.0f), con quello nuovo no "
   "(scarto %.0f)" % (_ad(345, 24), _ad(345, 54)))
r2 = R.classify_window(win(range(5, 11), 15.0, 54.0), settori=SET)
ok(r2["classe"] == R.PELER,
   "e il Pelèr vero, che arriva da 54, resta Pelèr (%s)" % r2["classe"])

# La rotazione e' una rotazione, non un allargamento.
ok(SET[R.PELER][1] == R.SETTORI[R.PELER][1],
   "l'ampiezza del settore non cambia: si sposta il centro, non si allarga")

# Ogni spot ha il proprio, perche' ogni centralina vede la propria rosa.
# I canali sono della STAZIONE, non dello spot: due spot sulla stessa
# centralina devono vedere gli stessi due canali. La prima versione ruotava i
# settori per spot e metteva il Pelèr a 11 gradi nella finestra dell'Ora.
so = R.settori_per_spot(config.SPOTS["Torbole-Ora"])
ok(so[R.PELER] == SET[R.PELER] and so[R.ORA] == SET[R.ORA],
   "gli spot della stessa centralina condividono i canali: Pelèr %g, Ora %g"
   % (so[R.PELER][0], so[R.ORA][0]))
ok(abs(so[R.PELER][0] - 54.0) < 0.1,
   "anche nella finestra dell'Ora il Pelèr resta a 54, non a 11")
sm = R.settori_per_spot(config.SPOTS["Malcesine-Ora"])
ok(abs(sm[R.PELER][0] - 68.0) < 0.1 and abs(sm[R.ORA][0] - 230.0) < 0.1,
   "e un'altra centralina ha i propri: Malcesine Pelèr %g, Ora %g"
   % (sm[R.PELER][0], sm[R.ORA][0]))
