"""Il comportamento dell'"adesso" DENTRO un browser vero.

Le altre prove verificano che live.json contenga le cose giuste. Questa
verifica l'unica parte che nessun controllo in Python puo' vedere: cosa fa la
pagina quando il dato invecchia, quando ne arriva uno nuovo, e - la piu'
importante - quando la richiesta non riesce.

Quattro promesse:

  1. l'eta' mostrata la calcola il browser dall'orario del campione, non da
     quando e' stata costruita la pagina. Una pagina costruita cinque ore
     prima deve dire "dato non recente", non "adesso".
  2. quando arriva un live.json piu' recente, i valori cambiano senza
     ricaricare la pagina.
  3. se la richiesta FALLISCE, non si svuota niente: restano i valori con cui
     la pagina e' nata, con la loro eta'.
  4. un live.json piu' VECCHIO di quello che la pagina ha già non la fa
     tornare indietro.

Se Playwright non c'e', il file lo dice e non finge di aver provato.
"""
import datetime as dt
import json
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwlivepag"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
shutil.rmtree("/tmp/gwlivepag", ignore_errors=True)

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)
UTC = dt.timezone.utc

try:
    from playwright.sync_api import sync_playwright
except Exception as e:                                        # pragma: no cover
    print("SKIP playwright non disponibile (%s)" % str(e)[:60])
    raise SystemExit(0)

from gardawind import config, engine, export, live, store, web
from gardawind.util import iso_utc

store.init()
ST = config.SPOTS["Torbole-Ora"]["station"]
ADESSO = dt.datetime.now(UTC)

# Una pagina "nata" con un dato di venti minuti fa.
camp = []
for k in range(12, 0, -1):
    t = ADESSO - dt.timedelta(minutes=20 + 10 * k)
    camp.append((iso_utc(t), 14.0, 20.0, 191.0))
camp.append((iso_utc(ADESSO - dt.timedelta(minutes=20)), 14.0, 20.0, 191.0))
store.save_samples(ST, camp, "t_live_pagina")


# La previsione serve solo a far esistere le sezioni dei luoghi: qui si prova
# l'"adesso", non il modello. Si costruisce a mano, come in t_ui.py.
def profilo(base):
    return [{"hour": h, "key": "2026-09-14T%02d:00:00Z" % h,
             "wind": base, "gust": base * 1.4, "lo": base - 2, "hi": base + 2,
             "dir": 200, "t2m": 24.0, "cloud": 20.0, "precip": 0.0}
            for h in range(4, 21)]


def sessione(speed):
    return {"prob": 0.8, "speed": speed, "lo": speed - 2, "hi": speed + 2,
            "grade": "BUONO", "source": "appreso", "peak_hour": 16.2,
            "peak_hour_mae_min": 83.0, "mae": 1.8, "validata": True,
            "band_source": "residui misurati", "n_models": 8,
            "weights": "verificato",
            "affidabilita": {"livello": 2, "etichetta": "buona affidabilità",
                             "motivo": "prova", "uso": "prova",
                             "componenti": {"timing_min": 83.0}},
            "window": {"from": 14, "to": 18, "gust": speed * 1.4,
                       "from_min": 14 * 60 + 10, "to_min": 18 * 60}}


VIVO = {"wind": 14.0, "gust": 20.0, "dir": 191.0,
        "ts": iso_utc(ADESSO - dt.timedelta(minutes=20)),
        "age_min": 20.0, "stale": False}
GIORNI = [{
    "day": "2026-09-14", "lead": 0,
    "sessions": {n: sessione(16.0) for n in config.SPOT_ORDER},
    "places": {p: {"profile": profilo(18.0), "live": dict(VIVO)}
               for p in config.PLACES},
}]
engine.by_day = lambda product=None: [dict(g) for g in GIORNI]
engine.ensure_update = lambda force=False: False

SITO = "/tmp/gwlivepag/site"
shutil.rmtree(SITO, ignore_errors=True)
export.export(SITO)
pagina = "file://" + os.path.join(SITO, "index.html")

URL_LIVE = config.LIVE_JSON_URL


def json_nuovo(ts, wind, gust, direzione=191.0):
    v = {"station": ST, "ts": iso_utc(ts), "wind": wind, "gust": gust,
         "dir": direzione, "gust_rec": None, "gust_rec_stato": "ok",
         "cadenza_min": 10.0, "n_campioni": 12}
    v["html"] = web.now_observed_html(v)
    return {"generato": iso_utc(ADESSO), "versione": config.APP_VERSION,
            "luoghi": {"Torbole": v, "Malcesine": dict(v, station="malcesine")}}


def apri(p, corpo=None, fallisci=False):
    """Apre la pagina intercettando la richiesta del dato osservato."""
    chiamate = []

    def gestisci(route):
        chiamate.append(route.request.url)
        if fallisci:
            route.abort()
        else:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(corpo))

    p.route("**/live.json*", gestisci)
    pg = p.new_page()
    pg.goto(pagina)
    pg.wait_for_timeout(700)
    return pg, chiamate


def testo(pg, sel):
    el = pg.query_selector(sel)
    return el.inner_text().strip() if el else None


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context()

    # ---- 1. l'eta' la calcola il browser -------------------------------
    pg, chiamate = apri(ctx, json_nuovo(ADESSO - dt.timedelta(minutes=20),
                                        14.0, 20.0))
    eta = testo(pg, ".nowblock .nowage")
    ok(eta == "20 min fa", "eta' calcolata dall'orario del campione: %r" % eta)
    ok(chiamate and "live.json" in chiamate[0],
       "la pagina chiede il dato osservato da sola (%s)"
       % (chiamate[0].split("/")[-1] if chiamate else "-"))
    ok(URL_LIVE.split("/")[2] in chiamate[0],
       "e lo chiede all'indirizzo del ramo dedicato, non accanto a se stessa")

    # La pagina e' stata costruita ADESSO, ma se il dato fosse di cinque ore
    # fa l'eta' deve dirlo. Si simula spostando l'orario del blocco.
    pg.evaluate("""() => {
        document.querySelectorAll('.nowblock').forEach(function(b){
          b.setAttribute('data-ts', new Date(Date.now()-5*3600*1000).toISOString());
        });
        gwPaintAge();
    }""")
    ok(testo(pg, ".nowblock .nowage") == "dato non recente",
       "un dato di cinque ore si dichiara non recente, non 'adesso'")
    classe = pg.eval_on_selector(".nowblock .nowmeta", "e => e.className")
    ok("stale" in classe, "e la riga si ingiallisce (%s)" % classe)
    pg.close()

    # ---- 2. un dato nuovo entra senza ricaricare ------------------------
    pg, _ = apri(ctx, json_nuovo(ADESSO - dt.timedelta(minutes=2), 23.0, 31.0))
    v = testo(pg, ".nowblock .nowbig .v")
    ok(v is not None and v.startswith("23"),
       "il vento nuovo compare senza ricaricare la pagina (%r)" % v)
    ok("31" in (testo(pg, ".nowblock .nowgust") or ""),
       "e anche la raffica (%r)" % testo(pg, ".nowblock .nowgust"))
    ok(testo(pg, ".nowblock .nowage") == "adesso",
       "l'eta' torna a 'adesso' perche' il campione e' di due minuti fa")
    ok(pg.eval_on_selector(".nowblock", "e => e.getAttribute('data-ts')")
       == iso_utc(ADESSO - dt.timedelta(minutes=2)),
       "e il blocco si porta dietro il nuovo orario")
    pg.close()

    # ---- 3. la richiesta fallisce: non si svuota niente -----------------
    pg, chiamate = apri(ctx, None, fallisci=True)
    v = testo(pg, ".nowblock .nowbig .v")
    ok(v is not None and v.startswith("14"),
       "richiesta fallita: restano i valori con cui la pagina e' nata (%r)" % v)
    ok(testo(pg, ".nowblock .nowage") == "20 min fa",
       "e la loro eta' continua a essere mostrata")
    ok(chiamate, "la richiesta e' stata tentata davvero")
    errori = []
    pg.on("pageerror", lambda e: errori.append(str(e)))
    pg.wait_for_timeout(300)
    ok(not errori, "e non lascia errori in console: %s" % (errori[:1] or "nessuno"))
    pg.close()

    # ---- 4. un dato piu' vecchio non fa tornare indietro la pagina ------
    pg, _ = apri(ctx, json_nuovo(ADESSO - dt.timedelta(hours=3), 5.0, 6.0))
    v = testo(pg, ".nowblock .nowbig .v")
    ok(v is not None and v.startswith("14"),
       "un live.json piu' vecchio viene ignorato (%r)" % v)
    ok(testo(pg, ".nowblock .nowage") == "20 min fa",
       "e l'eta' resta quella del dato buono")
    pg.close()

    # ---- 5. la pagina statica non si ricarica da sola -------------------
    html = open(os.path.join(SITO, "index.html"), encoding="utf-8").read()
    ok("location.reload" not in html,
       "la pagina pubblicata non si ricarica da sola: aggiorna solo l'adesso")
    ok("gwPaintAge" in html and "gwFetchLive" in html,
       "ma il pezzo che tiene aggiornato l'adesso c'e'")
    ok(os.path.exists(os.path.join(SITO, "live.json")),
       "e accanto c'e' un live.json coerente con la pagina appena costruita")


    # ---- 6. l'intestazione e la scheda non possono contraddirsi ----------
    # Prima l'intestazione veniva scritta una volta e non si muoveva piu':
    # poteva dire "dati reali aggiornati adesso" mentre la scheda sotto diceva
    # "tre ore fa". Ora le due frasi vengono dalla stessa eta'.
    pg, _ = apri(ctx, json_nuovo(ADESSO - dt.timedelta(minutes=3), 14.0, 20.0))
    ok("adesso" in (testo(pg, "#gwlive") or ""),
       "intestazione: dato di tre minuti -> 'adesso' (%r)" % testo(pg, "#gwlive"))
    pg.evaluate("""() => {
        document.querySelectorAll('.nowblock').forEach(function(b){
          b.setAttribute('data-ts', new Date(Date.now()-3*3600*1000).toISOString());
        });
        gwPaintAge();
    }""")
    testa = testo(pg, "#gwlive") or ""
    scheda = testo(pg, ".nowblock .nowage") or ""
    ok("3 ore fa" in testa,
       "intestazione: spostando il dato a tre ore lo dice (%r)" % testa)
    ok("adesso" not in testa and "non recente" in scheda,
       "e non contraddice la scheda (%r / %r)" % (testa, scheda))
    ok("warn" in pg.eval_on_selector("#gwdot", "e => e.className"),
       "e il pallino passa a giallo")
    pg.close()

    # ---- 7. il banner della pagina statica dice il vero -----------------
    ok("si aggiornano da sole" in html and "condizioni attuali" in html.lower(),
       "il banner distingue cio' che si aggiorna da cio' che no")
    ok("Non si aggiorna da sola" not in html,
       "e non ripete la frase che ora sarebbe falsa")

    # ---- 8. un live.json senza letture non cancella la pagina ------------
    # Succede davvero: se le centraline non rispondono, il processo veloce
    # scrive comunque il file, con i campi a null. Quel file non deve
    # svuotare la scheda - altrimenti un guasto di rete cancellerebbe l'ultimo
    # dato buono che l'utente aveva davanti.
    vuoto = json_nuovo(ADESSO, 14.0, 20.0)
    for nome in vuoto["luoghi"]:
        v = vuoto["luoghi"][nome]
        v["ts"] = None
        v["wind"] = None
        v["gust"] = None
        v["html"] = web.now_observed_html(v)
    pg, _ = apri(ctx, vuoto)
    v = testo(pg, ".nowblock .nowbig .v")
    ok(v is not None and v.startswith("14"),
       "un live.json senza letture lascia il dato buono al suo posto (%r)" % v)
    ok(testo(pg, ".nowblock .nowage") == "20 min fa",
       "e la sua eta' continua a crescere normalmente")
    pg.close()

    browser.close()
