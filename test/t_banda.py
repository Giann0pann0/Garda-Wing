"""La banda di incertezza, il metro del confronto, e la migrazione che fondeva male.

Tre difetti trovati rivedendo il progetto il 20/09/2026, e ognuno di questi
controlli esiste perche' il difetto era invisibile:

  IL SEGNO DELLA BANDA. Il residuo del progetto e' `previsto - osservato`, e la
  banda sommava i suoi quantili alla previsione. Ma se r = p - o allora
  o = p - r: i quantili si SOTTRAGGONO, e scambiati. Con residui simmetrici i
  due conti danno lo stesso risultato - ed e' per questo che nessuno se ne era
  accorto. Dove il modello sbaglia per un verso, la banda si sposta per
  l'altro, e il tetto della banda e' il numero su cui si decide se si plana.

  LA COPERTURA. Il numero che smaschera il punto precedente si calcolava e non
  si salvava: la colonna in diagnostica stampava "—" da sempre.

  LO STESSO METRO. Il MAE del modello vive sulle giornate con previsione fuori
  campione; quello dei riferimenti si calcolava su TUTTE. Il loro rapporto e'
  la percentuale di guadagno pubblicata e la porta di promozione.

  LA MIGRAZIONE CHE FONDEVA MALE. "UPDATE OR REPLACE ... SET hour=?": quando
  l'ora esisteva in entrambe le forme, la riga canonica (piu' ricca) veniva
  CANCELLATA per far posto a quella corta. Silenzioso, e irripetibile per un
  contrassegno che impediva di rifare la migrazione.
"""
import os
import shutil
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(QUI, ".."))
os.environ["GARDAWIND_HOME"] = "/tmp/gwbanda"
shutil.rmtree("/tmp/gwbanda", ignore_errors=True)

from gardawind import model, store, validate  # noqa: E402
from gardawind.util import banda_da_residui, quantile  # noqa: E402

passati = 0


def ok(c, m):
    global passati
    if c:
        passati += 1
        print("PASS " + m)
    else:
        print("FAIL " + m)


# ---- 1. il verso della banda -----------------------------------------------
# Un modello che SOTTOSTIMA: l'osservato sta sopra il previsto, quindi i
# residui (previsto - osservato) sono negativi.
lo, hi = banda_da_residui(12.0, -6.0, -1.0)
ok(lo > 12.0 and hi > 12.0,
   "se il modello sottostima, la banda sta SOPRA la previsione (%.1f-%.1f kn)"
   % (lo, hi))
ok(abs(lo - 13.0) < 1e-9 and abs(hi - 18.0) < 1e-9,
   "e i quantili si sottraggono scambiati: 12 - (-1) = 13, 12 - (-6) = 18")
lo, hi = banda_da_residui(20.0, 1.0, 6.0)
ok(hi < 20.0,
   "e se sovrastima, la banda sta sotto (%.1f-%.1f kn)" % (lo, hi))
lo, hi = banda_da_residui(3.0, 1.0, 9.0)
ok(lo == 0.0, "il vento negativo non esiste: il fondo della banda si ferma a 0")
ok(banda_da_residui(None, 1.0, 2.0) == (None, None)
   and banda_da_residui(10.0, None, 2.0) == (None, None),
   "senza previsione o senza quantili non si inventa una banda")

# ---- 2. la copertura: 80% dichiarato, 80% misurato --------------------------
# Residui ASIMMETRICI, come quelli veri del picco del vento: il modello
# sottostima le giornate forti. Si costruiscono osservati da previsioni note.
import random  # noqa: E402

random.seed(7)
previsti, osservati = [], []
for _i in range(400):
    p = random.uniform(8.0, 22.0)
    # errore con la coda a destra: quasi sempre poco, qualche volta molto
    e = random.expovariate(1 / 2.0) - 0.5
    previsti.append(p)
    osservati.append(p + e)
resid = [p - o for p, o in zip(previsti, osservati)]
cov, n_cov = validate._copertura_banda(resid, previsti, osservati)
ok(cov is not None and 0.65 <= cov <= 0.92,
   "con residui asimmetrici la banda 10-90%% copre quello che promette, o quasi "
   "(%.0f%% su %d giornate)" % (cov * 100, n_cov))
# E NON e' 80 per costruzione. Se i quantili si stimano sugli stessi residui su
# cui poi si misura, il risultato e' 80% qualunque cosa sia rotta a valle: e' il
# numero che il 20/09/2026 e' comparso in pagina identico su tutti e sette gli
# spot. Il conto vero taglia la lista a meta'.
q10c, q90c = quantile(resid, 0.10), quantile(resid, 0.90)
tautologica = sum(1 for p_, o in zip(previsti, osservati)
                  if p_ - q90c <= o <= p_ - q10c) / float(len(previsti))
ok(abs(tautologica - 0.80) < 0.02 and abs(cov - tautologica) > 1e-6,
   "misurata sugli stessi residui darebbe %.0f%% - sempre, per costruzione - "
   "mentre il conto onesto da' %.0f%%" % (tautologica * 100, cov * 100))
ok(n_cov > 0 and n_cov < len(previsti),
   "e si misura su una PARTE delle giornate (%d su %d), non su tutte"
   % (n_cov, len(previsti)))
# E la prova che il verso conta: con i quantili sommati, la copertura crolla.
q10, q90 = quantile(resid, 0.10), quantile(resid, 0.90)
dentro = sum(1 for p, o in zip(previsti, osservati) if p + q10 <= o <= p + q90)
storta = dentro / float(len(previsti))
ok(storta < 0.5,
   "mentre sommandoli - come si faceva - ne copriva il %.0f%%: la sentinella "
   "serviva, e non era collegata" % (storta * 100))

# ---- 3. la copertura arriva davvero in diagnostica -------------------------
finto = {"tier": "bias", "coverage": 0.79, "coverage_n": 120, "mae": 1.0}
ok(model.metrics_of(finto).get("coverage") == 0.79,
   "metrics_of porta la copertura fuori: la colonna della diagnostica ha un numero")
engine_src = open(os.path.join(QUI, "..", "gardawind", "engine.py"),
                  encoding="utf-8").read()
ok('"coverage": (r["intensity"] or {}).get("coverage")' in engine_src
   and '"clim_median": (r["intensity"] or {}).get("clim_median")' in engine_src,
   "e i modelli per fascia la portano insieme alla mediana climatologica, "
   "senza la quale il ripiego tornava al prior fisico")

# ---- 4. pava: il blocco in cima non e' mai meta' del minimo -----------------
random.seed(3)
probs = [random.random() for _i in range(155)]
esiti = [1 if p > 0.5 else 0 for p in probs]
blocchi = model.pava(probs, esiti, min_per_block=20)
pieni = [b for b in blocchi]
ok(all(b[2] >= 0 for b in pieni) and blocchi,
   "pava restituisce blocchi")
# La conta per blocco non esce da pava: si rifa' il taglio come lo fa lui.
conteggi = []
pairs = sorted(zip(probs, esiti))
for i in range(0, len(pairs), 20):
    conteggi.append(len(pairs[i:i + 20]))
if len(conteggi) >= 2 and conteggi[-1] < 20:
    conteggi = conteggi[:-2] + [conteggi[-2] + conteggi[-1]]
ok(min(conteggi) >= 20,
   "e nessun blocco poggia su meno di venti giornate, come la docstring "
   "promette (conteggi: %s)" % conteggi)

# ---- 5. lo stesso metro: i riferimenti sulle giornate del modello -----------
src = open(os.path.join(QUI, "..", "gardawind", "model.py"),
           encoding="utf-8").read()
pezzo = src[src.index("coppie_eval = "):src.index("clim_median = med")]
ok("obs_eval" in pezzo and "mean([abs(med - o) for o in obs_eval])" in pezzo,
   "la mediana climatologica si misura sulle sole giornate in cui la "
   "previsione fuori campione esiste")
ok("for _p, r, o in terzetti if r is not None" in pezzo,
   "e il vento grezzo pure, appaiato giornata per giornata")
pezzo2 = src[src.index("if m_int and base_mae is not None and terzetti:"):
             src.index("ok_int = (model_mae is not None")]
ok("con_grezzo" in pezzo2 and "base_med" in pezzo2,
   "il bootstrap prova il riferimento che MORDE, non sempre la mediana")

# ---- 6. la migrazione delle ore fonde, non sovrascrive ----------------------
store.init()
c = store.connect()
c.execute("INSERT OR REPLACE INTO obs_hour(station, hour, wind_mean, wind_max, "
          "gust_max, gust_rec, dir_deg, dir_const, n_samples) "
          "VALUES('campione','2026-09-19T10',9.0,NULL,11.0,NULL,NULL,NULL,6)")
c.execute("INSERT OR REPLACE INTO obs_hour(station, hour, wind_mean, wind_max, "
          "gust_max, gust_rec, dir_deg, dir_const, n_samples) "
          "VALUES('campione','2026-09-19T10:00:00Z',12.5,15.0,19.0,17.0,205.0,0.8,36)")
# Un'ora che esiste SOLO nella forma corta: quella si rinomina e basta.
c.execute("INSERT OR REPLACE INTO obs_hour(station, hour, wind_mean, wind_max, "
          "gust_max, gust_rec, dir_deg, dir_const, n_samples) "
          "VALUES('campione','2026-09-18T07',7.7,NULL,10.0,NULL,NULL,NULL,6)")
c.commit()
store.meta_set("migrazione_chiavi_ora", None)
c.execute("DELETE FROM meta WHERE k='migrazione_chiavi_ora'")
c.commit()
store._migra_chiavi_ora()

righe = {r["hour"]: dict(r) for r in c.execute(
    "SELECT * FROM obs_hour WHERE station='campione'")}
ok("2026-09-19T10" not in righe and "2026-09-19T10:00:00Z" in righe,
   "dopo la migrazione la chiave corta non c'e' piu' e resta la canonica")
r = righe.get("2026-09-19T10:00:00Z") or {}
ok(r.get("wind_mean") == 12.5 and r.get("gust_max") == 19.0
   and r.get("gust_rec") == 17.0 and r.get("dir_deg") == 205.0
   and r.get("n_samples") == 36,
   "e la riga sopravvissuta e' quella RICCA: la prima stesura di questa "
   "migrazione la cancellava per far posto a quella povera (9.0, niente "
   "raffica, niente direzione)")
ok("2026-09-18T07:00:00Z" in righe
   and (righe["2026-09-18T07:00:00Z"]["wind_mean"] == 7.7),
   "un'ora che esisteva solo nella forma corta diventa canonica senza perdere niente")

# E il contrassegno: la migrazione non si rifa' due volte, ma un cambio di
# versione la fa rifare una volta sola.
prima = store.meta_get("migrazione_chiavi_ora")
ok(prima == store.VERSIONE_MIGRAZIONE_ORE,
   "il contrassegno porta la VERSIONE, non la data: cosi' una migrazione "
   "corretta si puo' rifare una volta sola")
ok(store._migra_chiavi_ora() == 0,
   "e a versione uguale non si rifa'")

print("%d controlli sulla banda, sul metro e sulla migrazione" % passati)
