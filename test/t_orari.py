"""I casi sintetici dell'orario di ingresso, con risultato atteso scritto prima.

Tutti contro la LOGICA PURA (giudica_giornata), che e' deterministica, non
legge configurazione, non conosce fold e non stima niente: produce solo fatti
osservabili su una giornata. Se uno di questi casi fallisce, e' sbagliata la
logica - non una regex su una tabella.

Climatologia, stagionalita' e bimodalita' vanno contro il secondo livello.
Bias, fold e causalita' arriveranno col terzo blocco, quello del modello.
"""
import os, sys
os.environ["GARDAWIND_HOME"] = "/tmp/gworari"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import shutil
shutil.rmtree("/tmp/gworari", ignore_errors=True)

from gardawind.orari import (climatologia, giudica_giornata,
                             previsione_climatologica)
from gardawind.util import linear_modes

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)

# Parametri espliciti: la funzione pura non legge configurazione.
ASSE, SETTORE = 191.0, 70.0          # come Torbole-Ora osservata
REG, PLAN = 11.0, 14.0               # soglia di regime, soglia di planata
DENTRO, FUORI = 191.0, 11.0          # 11 gradi dista 180 dall'asse: fuori


def giorno(eventi, cad=10.0, da=660.0, a=1200.0, dir_calmo=None):
    """Una giornata a cadenza cad: 3 kn di base, piu' gli eventi richiesti.

    eventi: [(minuto_inizio, minuto_fine, vento, direzione)] - estremi inclusi.
    """
    righe = []
    m = da
    while m <= a:
        w, d = 3.0, dir_calmo
        for i0, i1, vv, dd in eventi:
            if i0 <= m <= i1:
                w, d = vv, dd
        righe.append((m, w, d))
        m += cad
    return righe


P = dict(asse=ASSE, settore=SETTORE, soglia_regime=REG, soglia_planata=PLAN)


def giudica(righe, **kw):
    q = dict(P)
    q.update(kw)
    return giudica_giornata(righe, q["asse"], q["settore"],
                            q["soglia_regime"], q["soglia_planata"],
                            **{k: v for k, v in kw.items()
                               if k in ("persist_min", "min_copertura_min",
                                        "date")})


# ---- 1. ingresso noto: rampa stabile dalle 13:20 ----
# Un campione copre i dieci minuti che lo precedono, e l'ingresso torna il
# CENTRO di quell'intervallo: atteso 13:20 - 5 = 13:15.
g = giudica(giorno([(800.0, 1200.0, 18.0, DENTRO)]))
ok(g["estimable"] and g["reason"] == "ok", "giornata stimabile")
ok(g["source_span_min"] == 540.0 and g["n_samples"] == 55,
   "span e numero di campioni viaggiano col record per l'audit (%s, %s)"
   % (g["source_span_min"], g["n_samples"]))
ok(g["regime_onset"] == 795.0,
   "ingresso noto alle 13:20 -> 13:15, centro dell'intervallo (%s)"
   % g["regime_onset"])
ok(g["planing_onset"] == 795.0, "e la planata allo stesso istante, 18 > 14 kn")

# ---- 2. falso attraversamento: sopra soglia 20 minuti, poi ricade ----
g = giudica(giorno([(800.0, 810.0, 18.0, DENTRO)]))
ok(g["regime_onset"] is None,
   "venti minuti sopra soglia non sono un ingresso sostenuto (%s)"
   % g["regime_onset"])
ok(g["estimable"] is True,
   "ma la giornata resta stimabile: contribuisce alla base rate con uno zero")
ok(g["regime_duration_min"] == 20.0,
   "la durata sopra soglia c'e' comunque: 20 min (%s)" % g["regime_duration_min"])
ok(g["reason"] == "threshold_not_sustained",
   "e il codice distingue \"superata ma non sostenuta\" (%s)" % g["reason"])

# ---- 3. direzione sbagliata: intensita' perfetta, fuori settore ----
g = giudica(giorno([(800.0, 1200.0, 18.0, FUORI)]))
ok(g["regime_onset_wind"] == 795.0, "vento sopra soglia: SI (%s)"
   % g["regime_onset_wind"])
ok(g["regime_onset"] is None, "regime: NO, la direzione e' fuori settore")
ok(g["reason"] == "direction_outside_sector", "e il codice lo dice (%s)" % g["reason"])
ok(g["direction_ok"] is False, "e direction_ok lo dice")

# ---- 4. il bordo del settore, esattamente ----
appena_dentro = (ASSE + SETTORE) % 360.0            # 261: distanza 70.0
appena_fuori = (ASSE + SETTORE + 1.0) % 360.0       # 262: distanza 71.0
g = giudica(giorno([(800.0, 1200.0, 18.0, appena_dentro)]))
ok(g["regime_onset"] == 795.0,
   "a distanza esattamente 70 gradi il settore include (%s)" % g["regime_onset"])
g = giudica(giorno([(800.0, 1200.0, 18.0, appena_fuori)]))
ok(g["regime_onset"] is None, "a 71 gradi esclude")

# ---- 5. regime e planata a due orari distinti ----
# 12 kn dalle 12:30 (regime si, planata no), 18 kn dalle 13:20
g = giudica(giorno([(750.0, 790.0, 12.0, DENTRO),
                    (800.0, 1200.0, 18.0, DENTRO)]))
ok(g["regime_onset"] == 745.0,
   "regime alle 12:30 -> 12:25 (%s)" % g["regime_onset"])
ok(g["planing_onset"] == 795.0,
   "planata alle 13:20 -> 13:15 (%s)" % g["planing_onset"])
ok(g["regime_onset"] < g["planing_onset"],
   "due timing distinti, non uno solo")

# ---- 6. buco nei dati durante l'ingresso ----
righe = [r for r in giorno([(800.0, 1200.0, 18.0, DENTRO)])
         if not (795.0 <= r[0] <= 900.0)]      # buco di quasi due ore
g = giudica(righe)
ok(g["regime_onset"] is not None and g["regime_onset"] >= 900.0,
   "col buco l'ingresso non viene interpolato ma spostato a dopo (%s)"
   % g["regime_onset"])
ok(g["reason"] == "gap_too_large",
   "e l'orario e' marcato come limite inferiore, non come misura (%s)"
   % g["reason"])
# e una giornata quasi tutta vuota non e' stimabile
g = giudica(giorno([(800.0, 1200.0, 18.0, DENTRO)])[:6])
ok(g["estimable"] is False and g["reason"] == "insufficient_coverage",
   "copertura insufficiente: codice chiuso, non testo libero (%s)" % g["reason"])
ok(g["regime_onset"] is None, "e nessun orario inventato")

# ---- 7. giornata senza regime: zero, non un orario ----
g = giudica(giorno([]))
ok(g["estimable"] is True, "una giornata calma e' stimabile")
ok(g["regime_onset"] is None and g["planing_onset"] is None,
   "senza regime non si inventa un orario")
ok(g["regime_duration_min"] is None, "e la durata e' assente, non zero finto")
ok(g["reason"] == "no_regime", "codice no_regime (%s)" % g["reason"])

# ---- 8. determinismo e assenza di stato ----
r = giorno([(800.0, 1200.0, 18.0, DENTRO)])
a1 = giudica(r)
a2 = giudica(list(reversed(r)))
ok(a1["regime_onset"] == a2["regime_onset"],
   "l'ordine delle righe in ingresso non cambia il risultato")
ok(giudica(r)["regime_onset"] == a1["regime_onset"],
   "due chiamate identiche danno lo stesso risultato")

# ---- 9. cadenza rada: la persistenza si misura in minuti, non in campioni ----
g = giudica(giorno([(800.0, 1200.0, 18.0, DENTRO)], cad=30.0))
ok(g["regime_onset"] is not None,
   "a cadenza 30 min l'ingresso si trova comunque (%s)" % g["regime_onset"])
ok(g["cadence_min"] == 30.0, "e la cadenza e' dedotta dai dati (%s)"
   % g["cadence_min"])

# ---- 10. direzione ignota non vale come coerente ----
g = giudica(giorno([(800.0, 1200.0, 18.0, None)]))
ok(g["regime_onset_wind"] == 795.0, "il vento c'e'")
ok(g["regime_onset"] is None,
   "ma con direzione ignota il regime non si da' per buono")
ok(g["dir_unknown_frac"] is not None and g["dir_unknown_frac"] > 0.5,
   "e la quota di direzione ignota viaggia col record (%.2f)"
   % g["dir_unknown_frac"])

# ==========================================================================
# secondo livello: climatologia, stagionalita', bimodalita'
# ==========================================================================
import datetime as dt
from gardawind import store, config
from gardawind.util import iso_utc, median, to_local

store.init()
SPOT = "Torbole-Ora"
spot = config.SPOTS[SPOT]

def scrivi_giorno(giorno_iso, minuto_ingresso, vento=18.0, direzione=None):
    """Scrive in UTC tale che l'ora LOCALE sia quella voluta."""
    direzione = spot.get("axis_obs", spot["axis"]) if direzione is None else direzione
    camp = []
    m = 660.0
    while m <= 1200.0:
        w = vento if m >= minuto_ingresso else 3.0
        d = direzione if m >= minuto_ingresso else 0.0
        cand = dt.datetime.fromisoformat(giorno_iso + "T00:00:00").replace(
            tzinfo=dt.timezone.utc) + dt.timedelta(minutes=m)
        off = to_local(cand).utcoffset() or dt.timedelta(0)
        camp.append((iso_utc(cand - off), w, w * 1.3, d))
        m += 10.0
    store.save_samples(spot["station"], camp, "prova")

# stagionalita' nota: giugno entra alle 12:00, settembre alle 13:30
for g_ in range(1, 26):
    scrivi_giorno("2024-06-%02d" % g_, 720.0)
for g_ in range(1, 26):
    scrivi_giorno("2024-09-%02d" % g_, 810.0)
# dispersione nota: luglio sparso su +-60 minuti attorno alle 13:00
for g_ in range(1, 26):
    scrivi_giorno("2024-07-%02d" % g_, 780.0 + ((g_ % 13) - 6) * 10.0)
# bimodalita' nota: agosto meta' alle 12:00, meta' alle 15:00
for g_ in range(1, 27):
    scrivi_giorno("2024-08-%02d" % g_, 720.0 if g_ % 2 else 900.0)

C = climatologia(SPOT)
K = ("regime", "regime")

giu = C["per_mese"][K + (6,)]
set_ = C["per_mese"][K + (9,)]
ok(giu["mediana"] == 715.0 and set_["mediana"] == 805.0,
   "stagionalita' letta: giugno %s, settembre %s"
   % (giu["mediana"], set_["mediana"]))
ok(abs(set_["mediana"] - giu["mediana"]) == 90.0,
   "la differenza fra i due mesi e' quella costruita: 90 minuti")

ann = C["annuale"][K]
err_mensile = (abs(giu["mediana"] - 715.0) + abs(set_["mediana"] - 805.0)) / 2.0
err_annuale = (abs(ann["mediana"] - 715.0) + abs(ann["mediana"] - 805.0)) / 2.0
ok(err_mensile < err_annuale,
   "il climatologico MENSILE batte quello annuale (%.0f min contro %.0f)"
   % (err_mensile, err_annuale))

lug = C["per_mese"][K + (7,)]
ok(lug["disp"] is not None and lug["disp"] > 15.0,
   "dispersione nota: luglio non ha disp zero (%s min)" % lug["disp"])
ok(abs(lug["mediana"] - 775.0) <= 15.0,
   "ma la mediana resta corretta (%s)" % lug["mediana"])

ago = C["per_mese"][K + (8,)]
ok(ago["modi"] is not None and len(ago["modi"]) == 2,
   "bimodalita' scoperta ad agosto: %s" % (ago["modi"],))
ok(ago["dip"] is not None and ago["dip"] < 0.3,
   "con una valle profonda fra i due picchi (dip %s)" % ago["dip"])
ok(giu["modi"] is not None and len(giu["modi"]) == 1,
   "e giugno resta unimodale: %s" % (giu["modi"],))

# il riferimento banale si costruisce su un sottoinsieme, non su tutto
solo_training = {6: C["ingressi"][K][6], 9: C["ingressi"][K][9]}
p6, fonte6 = previsione_climatologica(solo_training, 6)
p7, fonte7 = previsione_climatologica(solo_training, 7)
ok(p6 == 715.0 and fonte6 == "mese",
   "previsione climatologica di giugno dal solo training (%s, %s)" % (p6, fonte6))
ok(fonte7 == "annuale",
   "un mese assente dal training ricade sull'annuale, e lo dichiara (%s)" % fonte7)
p7b, fonte7b = previsione_climatologica(solo_training, 7, ricadi_su_annuale=False)
ok(p7b is None and fonte7b == "insufficiente",
   "oppure si rifiuta di rispondere, se glielo si chiede")

# ---- causalita' del secondo livello: passare le giornate, non leggerle ----
solo_giugno = {d: r for d, r in
               __import__("gardawind.orari", fromlist=["x"]).giorni_osservati(SPOT).items()
               if d.startswith("2024-06")}
C6 = climatologia(SPOT, giorni=solo_giugno)
ok(C6["per_mese"][K + (9,)]["n"] == 0,
   "una climatologia costruita sulle sole giornate di giugno non sa niente di settembre")
ok(C6["per_mese"][K + (6,)]["n"] == 25,
   "e conosce le sue venticinque (%d)" % C6["per_mese"][K + (6,)]["n"])


# ---- l'insieme dei codici e' chiuso ----
from gardawind.orari import REASONS
visti = set()
for gg in C["per_giorno"].values():
    visti.add(gg["reason"])
for caso in (giorno([]), giorno([(800.0, 810.0, 18.0, DENTRO)]),
             giorno([(800.0, 1200.0, 18.0, FUORI)]),
             giorno([(800.0, 1200.0, 18.0, DENTRO)])[:6], []):
    visti.add(giudica(caso)["reason"])
ok(visti <= set(REASONS),
   "nessun codice inventato fuori dall'insieme: %s" % sorted(visti))
ok("ok" in visti and len(visti) >= 4,
   "e i casi costruiti ne esercitano diversi (%d)" % len(visti))

# --------------------------------------------------------------------------
# I due picchi della giornata: uguali quando la direzione e' buona, diversi
# quando non lo e'. Servono alla descrittiva, e stanno nella logica pura
# perche' "quanto ha tirato dal settore giusto" usa la stessa definizione di
# settore dell'ingresso: due copie di quella definizione divergerebbero.
# --------------------------------------------------------------------------
g = giudica_giornata(giorno([(720, 900, 18.0, DENTRO)]), ASSE, SETTORE, REG, PLAN)
ok(g["peak_wind"] == 18.0 and g["peak_regime"] == 18.0,
   "picchi: con la direzione giusta le due letture coincidono")

# Nella giornata di prova il fondo da 3 kn non ha direzione, quindi nella
# lettura REGIME vale zero come tutto il resto di cio' che non sappiamo.
g = giudica_giornata(giorno([(720, 900, 18.0, FUORI)]), ASSE, SETTORE, REG, PLAN)
ok(g["peak_wind"] == 18.0 and g["peak_regime"] == 0.0,
   "picchi: fuori settore il picco di regime va a zero (%s)" % g["peak_regime"])

g = giudica_giornata(giorno([(720, 900, 18.0, None)]), ASSE, SETTORE, REG, PLAN)
ok(g["peak_wind"] == 18.0 and g["peak_regime"] == 0.0,
   "picchi: direzione sconosciuta non vale come coerente nemmeno sul picco")

g = giudica_giornata(giorno([(720, 900, 18.0, DENTRO)], dir_calmo=DENTRO),
                     ASSE, SETTORE, REG, PLAN)
ok(g["peak_regime"] == 18.0,
   "picchi: col fondo dentro settore il picco di regime resta il picco")

g = giudica_giornata([(m, None, None) for m in range(660, 1200, 10)],
                     ASSE, SETTORE, REG, PLAN)
ok(g["peak_wind"] is None and g["peak_regime"] is None,
   "picchi: senza vento restano None, non zero")
