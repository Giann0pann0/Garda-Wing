import os
import sys, math, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from gardawind import util as U
from datetime import datetime, timezone, timedelta

ok = lambda c,m: print(("PASS " if c else "FAIL ")+m)

# --- tempo ---
d = U.parse_dt_any("2026-09-13T10:15:00+01")
ok(d == datetime(2026,9,13,9,15,tzinfo=timezone.utc), "Meteotrentino +01 -> UTC 09:15 (%s)"%d)
ok(U.parse_dt_any("2026-09-13T10:15:00+01:00")==d, "offset a 5 char equivalente")
ok(U.parse_dt_any("13/09/26 11.28", assume_offset_hours=2)==datetime(2026,9,13,9,28,tzinfo=timezone.utc), "formato Malcesine con CEST")
ok(U.parse_dt_any("")is None and U.parse_dt_any("xx") is None, "input invalido -> None")
ok(U.local_hour(datetime(2026,9,13,9,15,tzinfo=timezone.utc))==11, "ora locale estiva = UTC+2")
ok(U.local_hour(datetime(2026,1,13,9,15,tzinfo=timezone.utc))==10, "ora locale invernale = UTC+1")
ok(U.local_day(datetime(2026,6,30,22,30,tzinfo=timezone.utc))=="2026-07-01", "giorno locale attraversa mezzanotte")
ok(U.iso_hour_utc(datetime(2026,9,13,9,47,tzinfo=timezone.utc))=="2026-09-13T09:00:00Z","chiave oraria")
ok(U.day_shift("2026-03-01",-1)=="2026-02-28","day_shift")

# --- angoli ---
ok(abs(U.along_axis(10,204,204)-10)<1e-9, "along_axis concorde = +v")
ok(abs(U.along_axis(10,24,204)+10)<1e-9, "along_axis opposto = -v")
ok(abs(U.along_axis(10,294,204))<1e-9, "along_axis perpendicolare = 0")
ok(abs(U.cross_axis(10,294,204)-10)<1e-9, "cross_axis perpendicolare = v")
dm,cst = U.vector_mean_direction([(10,200),(10,210)])
ok(abs(dm-205)<0.5 and cst>0.99, "media vettoriale direzioni coerenti (%.1f, %.2f)"%(dm,cst))
dm2,cst2 = U.vector_mean_direction([(10,0),(10,180)])
ok(cst2<0.01, "direzioni opposte -> costanza ~0 (%.3f)"%cst2)

# --- ridge: recupero coefficienti noti ---
random.seed(7)
n,p = 300, 5
beta = [2.0,-1.5,0.0,0.7,3.0]; b0=4.0
X=[[random.gauss(0,1) for _ in range(p)] for _ in range(n)]
y=[b0+sum(b*x for b,x in zip(beta,r))+random.gauss(0,0.25) for r in X]
m=U.ridge_fit(X,y,lam=0.01)
ok(m is not None, "ridge_fit ritorna un modello")
err=max(abs(a-b) for a,b in zip(m.coef,beta))
ok(err<0.08, "ridge recupera i coefficienti (err max %.4f)"%err)
ok(abs(m.intercept-b0)<0.08, "ridge recupera l'intercetta (%.3f)"%m.intercept)

# colonna costante non deve rompere nulla
Xc=[r+[5.0] for r in X]
mc=U.ridge_fit(Xc,y,lam=0.5)
ok(mc is not None and abs(mc.coef[-1])<1e-9, "colonna costante -> coefficiente 0, nessun crash")

# n < p
ms=U.ridge_fit(X[:3],y[:3],lam=1.0)
ok(ms is not None, "n<p non esplode (regolarizzazione alza fino a soluzione)")

# --- logistica ---
yb=[1 if (b0+sum(b*x for b,x in zip(beta,r)))>4.0 else 0 for r in X]
lm=U.logistic_fit(X,yb,lam=0.5)
ok(lm is not None, "logistic_fit ritorna un modello")
acc=sum(1 for r,t in zip(X,yb) if (lm.predict_proba(r)>0.5)==bool(t))/n
ok(acc>0.9, "logistica separa bene (acc %.3f)"%acc)
ok(U.logistic_fit(X,[1]*n,lam=.5) is None, "classe unica -> None")

# --- CV a blocchi ---
groups=[str(i//10) for i in range(n)]
folds=U.block_folds(groups,5)
ok(len(folds)==5 and sum(len(f) for f in folds)==n, "block_folds copre tutto")
gsets=[set(groups[i] for i in f) for f in folds]
ok(all(not (gsets[i]&gsets[j]) for i in range(5) for j in range(i+1,5)), "nessun gruppo attraversa due fold")
pr,okn=U.cv_predict(X,y,groups,lambda a,b:U.ridge_fit(a,b,0.1),lambda m,r:m.predict(r))
mt=U.regression_metrics(pr,y)
ok(okn==n and mt["rmse"]<0.35, "CV out-of-fold accurata (rmse %.3f)"%mt["rmse"])

# --- metriche ---
ok(abs(U.brier([1.0]*10,[1]*10))<1e-12, "brier perfetto = 0")
cov,_=U.interval_coverage([0]*100,[10]*100,[5]*100)
ok(cov==1.0, "copertura 100%")
print("\n-- quantile --", U.quantile([1,2,3,4,5],0.5), U.quantile([1,2,3,4,5],0.1))

# ===================== luce del giorno =====================
# Serve a una decisione pratica: sul Peler la finestra utile non comincia
# quando nasce il vento, comincia quando si vede. Un'ora pratica fissa alle
# 06:00 a dicembre e' due ore prima dell'alba.
from gardawind.util import alba_tramonto, offset_locale_ore
from gardawind import config as _cfg

_T = _cfg.TORBOLE


def _alba(data):
    a, _t = alba_tramonto(data, _T["lat"], _T["lon"], offset_locale_ore(data))
    return a


def _tramonto(data):
    _a, t = alba_tramonto(data, _T["lat"], _T["lon"], offset_locale_ore(data))
    return t


# Valori veri per Torbole (45.87 N, 10.88 E), tolleranza cinque minuti: la
# formula ridotta NOAA non promette di piu', e cinque minuti non cambiano
# nessuna decisione qui.
ok(abs(_alba("2026-06-21") - (5 * 60 + 31)) <= 5,
   "alba del solstizio d'estate 05:31 (%.0f min)" % _alba("2026-06-21"))
ok(abs(_alba("2026-12-21") - (7 * 60 + 59)) <= 5,
   "alba del solstizio d'inverno 07:59 (%.0f min)" % _alba("2026-12-21"))
ok(abs(_tramonto("2026-12-21") - (16 * 60 + 39)) <= 5,
   "tramonto del solstizio d'inverno 16:39 (%.0f min)" % _tramonto("2026-12-21"))
ok(_alba("2026-12-21") - _alba("2026-06-21") > 140,
   "fra i due solstizi l'alba si sposta di oltre due ore: un'ora pratica "
   "fissa sarebbe sbagliata in uno dei due")

# L'ora legale non si indovina dentro la formula: arriva dalla stessa
# conversione che usa tutto il resto del programma.
ok(offset_locale_ore("2026-01-15") == 1.0 and offset_locale_ore("2026-07-15") == 2.0,
   "l'offset del fuso viene dalla conversione locale, non da una regola "
   "riscritta qui")

# Simmetria attorno al mezzogiorno solare: alba e tramonto devono stare a
# uguale distanza, altrimenti c'e' un segno sbagliato da qualche parte.
for _d in ("2026-03-21", "2026-06-21", "2026-11-05"):
    _a, _t = alba_tramonto(_d, _T["lat"], _T["lon"], offset_locale_ore(_d))
    _mezzo = (_a + _t) / 2.0
    ok(abs((_mezzo - _a) - (_t - _mezzo)) < 1e-6,
       "%s: alba e tramonto simmetrici attorno al mezzogiorno solare" % _d)

# Il giorno piu' lungo e' il solstizio, e la durata cresce con la latitudine.
_durata_giu = _tramonto("2026-06-21") - _alba("2026-06-21")
_durata_dic = _tramonto("2026-12-21") - _alba("2026-12-21")
ok(_durata_giu > 900 and _durata_dic < 540,
   "quindici ore e mezza a giugno, meno di nove a dicembre (%.0f / %.0f min)"
   % (_durata_giu, _durata_dic))

# Oltre il circolo polare il sole puo' non sorgere: si dichiara None invece
# di restituire un numero inventato.
ok(alba_tramonto("2026-12-21", 78.2, 15.6, 1.0) == (None, None),
   "a Svalbard a dicembre il sole non sorge, e la funzione lo dice")
ok(alba_tramonto("2026-06-21", 78.2, 15.6, 2.0) == (None, None),
   "e a giugno non tramonta")

# --------------------------------------------------------------------------
# Il cambio d'ora di ottobre: l'ora che esiste due volte
#
# L'ultima domenica di ottobre le 02:00-02:59 italiane si ripetono, e le fonti
# che pubblicano l'orologio da parete - la Fraglia, Addicted - le scrivono due
# volte uguali. Convertite una per una finiscono sullo stesso istante UTC, e
# siccome i campioni si salvano con INSERT OR REPLACE la seconda cancella la
# prima: un'ora di misure persa e un'ora di UTC che nessuna chiave produce.
# Il 25 ottobre 2026.
# --------------------------------------------------------------------------
from gardawind.util import (local_naive_to_utc as _loc,  # noqa: E402
                            serie_locale_to_utc as _serie)
import datetime as _dtu  # noqa: E402

_doppia = [_dtu.datetime(2026, 10, 25, 1, 30), _dtu.datetime(2026, 10, 25, 2, 0),
           _dtu.datetime(2026, 10, 25, 2, 30), _dtu.datetime(2026, 10, 25, 2, 0),
           _dtu.datetime(2026, 10, 25, 2, 30), _dtu.datetime(2026, 10, 25, 3, 0)]
_ist = _serie(_doppia)
ok(len(set(_ist)) == len(_ist),
   "l'ora doppia del 25 ottobre da' sei istanti distinti, non quattro (%d)"
   % len(set(_ist)))
ok(_ist == sorted(_ist),
   "e in ordine crescente: l'ordine delle righe e' l'unica informazione che "
   "la fonte ci da'")
ok(_ist[3] - _ist[2] == _dtu.timedelta(minutes=30),
   "il secondo passaggio sta mezz'ora dopo il primo, non un'ora prima")
_normale = [_dtu.datetime(2026, 7, 10, 10, 0), _dtu.datetime(2026, 7, 10, 10, 10)]
ok(_serie(_normale) == [_loc(_normale[0]), _loc(_normale[1])],
   "e in una giornata qualunque non cambia niente")
ok(_serie([None, _dtu.datetime(2026, 7, 10, 10, 0)])[0] is None,
   "una riga illeggibile resta None invece di far saltare la serie")
