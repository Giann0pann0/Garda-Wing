"""La pagella: quello che abbiamo DETTO contro quello che e' successo.

E' l'unico controllo che guarda il prodotto da fuori, quindi il suo banco di
prova deve essere costruito al contrario di tutti gli altri: prima si sceglie
la risposta - "abbiamo promesso due nodi in piu', e il picco mezz'ora troppo
tardi" - poi si scrivono i dati che devono produrla. Se il banco preparasse i
dati e chiedesse al codice cosa ne pensa, misurerebbe il codice con se stesso.
"""
import datetime as dt
import os
import shutil
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(QUI, ".."))
os.environ["GARDAWIND_HOME"] = "/tmp/gwpagella"
shutil.rmtree("/tmp/gwpagella", ignore_errors=True)

from gardawind import config, pagella, store, verify, web  # noqa: E402
from gardawind.util import iso_utc, local_naive_to_utc  # noqa: E402

passati = 0


def ok(c, m):
    global passati
    if c:
        passati += 1
        print("PASS " + m)
    else:
        print("FAIL " + m)


store.init()
SPOT = "Torbole-Ora"
ST = config.SPOTS[SPOT]["station"]
H0, H1 = config.SPOTS[SPOT]["window"]
ASSE = config.SPOTS[SPOT]["axis_obs"]
OGGI = "2026-09-20"


def utc(giorno, ora):
    return iso_utc(local_naive_to_utc(
        dt.datetime.fromisoformat(giorno + "T00:00:00") + dt.timedelta(hours=ora)))


def osserva(giorno, picco, ora_picco):
    """Una giornata misurata: la finestra piena, con il picco dove dico io."""
    righe = []
    for ora in range(H0, H1 + 1):
        v = picco if ora == ora_picco else max(2.0, picco - 4.0 - abs(ora - ora_picco))
        righe.append({"hour": utc(giorno, ora), "wind_mean": v, "wind_max": v + 1,
                      "gust_max": None, "gust_rec": None, "dir_deg": ASSE,
                      "dir_const": 0.9, "n_samples": 6})
    store.upsert_obs_hours(ST, righe)


def pubblica(giorno_valido, giorno_emissione, ora_emissione, picco, ora_picco):
    """Una curva emessa: come se il sito l'avesse pubblicata quel giorno."""
    righe = []
    for ora in range(H0, H1 + 1):
        v = picco if ora == ora_picco else max(2.0, picco - 4.0 - abs(ora - ora_picco))
        righe.append({"key": utc(giorno_valido, ora), "wind": v, "gust": v * 1.3})
    store.save_issued_profile("Torbole", utc(giorno_emissione, ora_emissione), righe)


# ---- 1. dodici giornate in cui abbiamo promesso 2 nodi di troppo -----------
# e messo il picco un'ora piu' tardi di dov'e' arrivato.
giorni = []
for i in range(12):
    g = (dt.date.fromisoformat(OGGI) - dt.timedelta(days=i + 1)).isoformat()
    giorni.append(g)
    osserva(g, 16.0, 15)                      # misurato: 16 kn alle 15
    ieri = (dt.date.fromisoformat(g) - dt.timedelta(days=1)).isoformat()
    pubblica(g, ieri, 21, 18.0, 16)           # detto ieri sera: 18 kn alle 16

righe = pagella.confronto(giorni=60, adesso=local_naive_to_utc(
    dt.datetime.fromisoformat(OGGI + "T09:00:00")))
ora = next((x for x in righe if x["spot"] == SPOT), None)
ok(ora is not None and ora["n"] == 12,
   "dodici giornate confrontate (%s)" % (ora and ora["n"]))
ok(ora and abs(ora["scarto_medio"] - 2.0) < 1e-6,
   "lo scarto medio e' +2,0 kn: abbiamo promesso piu' vento di quanto e' arrivato (%.2f)"
   % (ora or {}).get("scarto_medio", -99))
ok(ora and abs(ora["scarto_assoluto"] - 2.0) < 1e-6,
   "e lo scarto tipico e' 2,0 kn, perche' sbagliamo sempre dalla stessa parte")
ok(ora and abs(ora["scarto_ore"] - 1.0) < 1e-6,
   "e il picco lo abbiamo messo un'ora troppo tardi (%.2f ore)"
   % (ora or {}).get("scarto_ore", -99))
ok(ora and list(ora["per_scadenza"]) == [1],
   "tutte a scadenza D+1, perche' emesse la sera prima (%s)"
   % list((ora or {}).get("per_scadenza") or {}))

# ---- 2. il verso conta: se sottostimiamo, il segno gira --------------------
shutil.rmtree("/tmp/gwpagella", ignore_errors=True)
store.close()
store.init()
for i in range(12):
    g = (dt.date.fromisoformat(OGGI) - dt.timedelta(days=i + 1)).isoformat()
    osserva(g, 20.0, 15)
    ieri = (dt.date.fromisoformat(g) - dt.timedelta(days=1)).isoformat()
    pubblica(g, ieri, 21, 17.0, 15)
r2 = next(x for x in pagella.confronto(giorni=60, adesso=local_naive_to_utc(
    dt.datetime.fromisoformat(OGGI + "T09:00:00"))) if x["spot"] == SPOT)
ok(abs(r2["scarto_medio"] + 3.0) < 1e-6,
   "sottostimando, lo scarto e' NEGATIVO (-3,0 kn): il verso e' l'informazione (%.2f)"
   % r2["scarto_medio"])
ok("in MENO" in pagella.in_parole(r2),
   "e la frase lo dice in italiano: \"%s\"" % pagella.in_parole(r2))

# ---- 3. l'emissione piu' recente vince ------------------------------------
# Della stessa giornata pubblichiamo quattro volte: conta quella che chi
# guardava ha letto per ultima, non la prima.
g = (dt.date.fromisoformat(OGGI) - dt.timedelta(days=2)).isoformat()
ieri = (dt.date.fromisoformat(g) - dt.timedelta(days=1)).isoformat()
pubblica(g, ieri, 5, 30.0, 15)            # emissione del mattino: 30 kn
pubblica(g, ieri, 21, 20.0, 15)           # emissione della sera: 20 kn (corretta)
r3 = next(x for x in pagella.confronto(giorni=60, adesso=local_naive_to_utc(
    dt.datetime.fromisoformat(OGGI + "T09:00:00"))) if x["spot"] == SPOT)
ok(abs(r3["scarto_medio"] + 3.0) < 0.3,
   "la previsione delle 5 del mattino (30 kn) non sposta la pagella: vale "
   "l'ultima di quel giorno (%.2f)" % r3["scarto_medio"])

# ---- 4. poche giornate: si dice quante mancano, non si fa una media -------
shutil.rmtree("/tmp/gwpagella", ignore_errors=True)
store.close()
store.init()
for i in range(3):
    g = (dt.date.fromisoformat(OGGI) - dt.timedelta(days=i + 1)).isoformat()
    osserva(g, 16.0, 15)
    ieri = (dt.date.fromisoformat(g) - dt.timedelta(days=1)).isoformat()
    pubblica(g, ieri, 21, 25.0, 15)
r4 = next(x for x in pagella.confronto(giorni=60, adesso=local_naive_to_utc(
    dt.datetime.fromisoformat(OGGI + "T09:00:00"))) if x["spot"] == SPOT)
ok(r4["n"] == 3 and "mancano 7" in pagella.in_parole(r4),
   "con tre giornate non si pubblica una media: \"%s\"" % pagella.in_parole(r4))
pannello = web.pagella_panel()
ok("mancano 7" in pannello and "+9" not in pannello,
   "e in pagina non compare nessun numero grande e falso")

# ---- 5. la giornata di oggi non entra: non e' finita ----------------------
osserva(OGGI, 16.0, 15)
pubblica(OGGI, OGGI, 3, 25.0, 15)
r5 = next(x for x in pagella.confronto(giorni=60, adesso=local_naive_to_utc(
    dt.datetime.fromisoformat(OGGI + "T09:00:00"))) if x["spot"] == SPOT)
ok(r5["n"] == 3, "la giornata in corso non entra nella pagella (%d)" % r5["n"])

# ---- 6. una sola riduzione dell'osservato, non due -----------------------
# verify (i pesi dei modelli) e pagella devono guardare la stessa cosa.
picchi_verify = verify.observed_daily_peaks(SPOT)
picchi_pagella = {g: p for g, (p, _o) in pagella.osservato_giornaliero(SPOT).items()}
ok(picchi_verify == picchi_pagella and picchi_verify,
   "verify e pagella riducono l'osservato allo stesso modo (%d giornate)"
   % len(picchi_verify))
src = open(os.path.join(QUI, "..", "gardawind", "verify.py"), encoding="utf-8").read()
ok("pagella.osservato_giornaliero" in src
   and src.count("MIN_WINDOW_COVERAGE") == 0,
   "e la riduzione vive in un posto solo: verify la chiede, non la riscrive")

# ---- 7. il pannello sta in cima alla diagnostica -------------------------
dg = web.page_diagnostics()
ok(dg.index("La pagella") < dg.index("Quanto sbaglia"),
   "la pagella e' il primo pannello: e' l'unico sguardo da fuori")

print("%d controlli sulla pagella" % passati)
