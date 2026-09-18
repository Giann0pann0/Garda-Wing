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
from gardawind.util import iso_utc, local_day, utc_now

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
# La giornata e' OGGI, perche' il segno dell'ora corrente compare solo sul
# grafico di oggi: con una data fissa non lo si proverebbe mai.
OGGI = local_day(utc_now())
from gardawind.util import day_shift
GIORNI = [{
    "day": day_shift(OGGI, lead), "lead": lead,
    "sessions": {n: sessione(16.0) for n in config.SPOT_ORDER},
    "places": {p: {"profile": profilo(18.0), "live": dict(VIVO)}
               for p in config.PLACES},
} for lead in range(3)]
engine.by_day = lambda product=None: [dict(g) for g in GIORNI]
engine.ensure_update = lambda force=False: False

SITO = "/tmp/gwlivepag/site"
shutil.rmtree(SITO, ignore_errors=True)
export.export(SITO)

# Si serve su HTTP, non da file://, per due ragioni: e' come la pagina vive
# davvero su Pages, e un indirizzo relativo da una pagina file:// il browser
# non lo carica affatto - la catena di ripiego non si potrebbe provare.
import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

_srv = ThreadingHTTPServer(
    ("127.0.0.1", 0),
    functools.partial(SimpleHTTPRequestHandler, directory=SITO))
threading.Thread(target=_srv.serve_forever, daemon=True).start()
pagina = "http://127.0.0.1:%d/index.html" % _srv.server_address[1]

URL_LIVE = config.LIVE_JSON_URL


def json_nuovo(ts, wind, gust, direzione=191.0):
    v = {"station": ST, "ts": iso_utc(ts), "wind": wind, "gust": gust,
         "dir": direzione, "gust_rec": None, "gust_rec_stato": "ok",
         "cadenza_min": 10.0, "n_campioni": 12}
    v["html"] = web.now_observed_html(v)
    return {"generato": iso_utc(ADESSO), "versione": config.APP_VERSION,
            "luoghi": {"Torbole": v, "Malcesine": dict(v, station="malcesine")}}


def apri(p, corpo=None, fallisci=False, solo_ramo_rotto=False):
    """Apre la pagina intercettando la richiesta del dato osservato.

    solo_ramo_rotto: il primo indirizzo (il ramo dedicato) fallisce e il
    secondo (il file accanto alla pagina) risponde. E' il caso da cui la
    catena di indirizzi difende: se raw.githubusercontent non fosse
    raggiungibile, o non mandasse l'intestazione CORS giusta, la pagina deve
    peggiorare - un dato vecchio con la sua eta' - non rompersi.
    """
    chiamate = []

    def gestisci(route):
        url = route.request.url
        chiamate.append(url)
        if fallisci or (solo_ramo_rotto and url.startswith("https://raw.")):
            route.abort()
        else:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(corpo))

    p.route("**/live.json*", gestisci)
    pg = p.new_page()
    pg.goto(pagina)
    pg.wait_for_timeout(900)
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

    # ---- 9. se il ramo dedicato non risponde, si prova il file accanto ----
    pg, chiamate = apri(ctx, json_nuovo(ADESSO - dt.timedelta(minutes=4),
                                        19.0, 26.0),
                        solo_ramo_rotto=True)
    ok(len(chiamate) >= 2, "catena: provati due indirizzi (%d)" % len(chiamate))
    ok(chiamate[0].startswith("https://raw."),
       "catena: prima il ramo dedicato")
    ok(chiamate[1].startswith("http://127.0.0.1"),
       "catena: poi il file accanto alla pagina (%s)" % chiamate[1][:40])
    v = testo(pg, ".nowblock .nowbig .v")
    ok(v is not None and v.startswith("19"),
       "catena: il secondo indirizzo viene applicato (%r)" % v)
    pg.close()

    # E se cadono entrambi, resta quello con cui la pagina e' nata.
    pg, chiamate = apri(ctx, None, fallisci=True)
    ok(len(chiamate) >= 2, "catena: con entrambi rotti si provano entrambi (%d)"
       % len(chiamate))
    v = testo(pg, ".nowblock .nowbig .v")
    ok(v is not None and v.startswith("14"),
       "catena: e la pagina resta quella di partenza (%r)" % v)
    pg.close()

    # ---- 10. il segno dell'ora corrente sul grafico di oggi --------------
    # Nasce da una domanda: "perche' il pallino e' alle 7 mentre ora sono le
    # 14.25?". Il pallino e' il picco previsto, ma su una curva del tempo un
    # punto con un numero accanto si legge come "sei qui". Ora il "sei qui"
    # c'e' davvero, lo mette il browser, e sta nell'ora del lago.
    pg, _ = apri(ctx, json_nuovo(ADESSO - dt.timedelta(minutes=5), 14.0, 20.0))
    oggi_n = len(pg.query_selector_all('svg.chart[data-today="1"]'))
    altri_n = len(pg.query_selector_all('svg.chart[data-today="0"]'))
    # Una pagina, una localita': un solo grafico di oggi, e uno per ognuno
    # degli altri giorni. Prima la pagina teneva dentro tutte le localita' e
    # questi conteggi si moltiplicavano per due.
    ok(oggi_n == 1,
       "adesso: un solo segno, sul grafico di oggi (%d)" % oggi_n)
    ok(altri_n >= 2,
       "adesso: i giorni successivi non lo hanno (%d grafici senza segno)"
       % altri_n)
    ok(len(pg.query_selector_all('line[id$="-now"]')) == oggi_n,
       "adesso: e l'elemento esiste solo dove serve")

    # L'ora del lago, con l'orologio vero, PRIMA di sostituirla: se la si
    # legge dopo si sta solo rileggendo il proprio finto.
    ora_lago = pg.evaluate("() => gwOraLago()")
    ora_sistema = pg.evaluate("() => new Date().getHours()+new Date().getMinutes()/60")
    ok(isinstance(ora_lago, (int, float)) and 0 <= ora_lago < 24,
       "adesso: l'ora del lago e' un numero di ore (%.2f)" % ora_lago)
    # Il container gira in UTC, il lago e' a UTC+1 o +2: la differenza deve
    # esserci, e deve essere di ore intere.
    _diff = (ora_lago - ora_sistema) % 24
    ok(abs(_diff - round(_diff)) < 0.02,
       "adesso: la differenza col fuso del dispositivo e' di ore intere (%.2f)"
       % _diff)

    def segno(ora):
        pg.evaluate("(o) => { window.gwOraLago = function(){return o;}; gwNowLine(); }",
                    ora)
        pg.wait_for_timeout(60)
        return pg.eval_on_selector(
            'svg.chart[data-today="1"] line[id$="-now"]',
            "e => [parseFloat(e.getAttribute('x1')), e.getAttribute('opacity')]")

    x15, op15 = segno(15.5)
    x7, op7 = segno(7.0)
    ok(float(op15) > 0 and float(op7) > 0,
       "adesso: dentro la finestra il segno si vede")
    ok(x15 > x7, "adesso: alle 15.30 sta a destra che alle 7 (%s > %s)" % (x15, x7))
    _x, op2 = segno(2.0)
    ok(float(op2) == 0.0,
       "adesso: fuori dalla finestra disegnata si nasconde invece di incollarsi al bordo")
    ok((pg.eval_on_selector('svg.chart[data-today="1"] text[id$="-nowlab"]',
                            "e => e.textContent") or "").strip() == "ADESSO",
       "adesso: l'etichetta dice ADESSO")
    pg.close()

    # ---- 11. la curva del misurato si aggiorna da sola -------------------
    # Gian: "Il fatto che il grafico del vento reale non si aggiorni
    # migliorera' con le ultime modifiche?". No, e adesso si'. Il numerone
    # dell'adesso si rifaceva da solo e la curva no: restava quella della
    # costruzione, quindi un 22 kn scritto grande sopra una riga che si
    # fermava a mezzogiorno. Sembrava rotto, e in un certo senso lo era.
    #
    # Qui si prova la parte che nessun controllo in Python vede: che il
    # browser prenda il percorso in coordinate 0-1 e lo porti DENTRO il
    # riquadro del disegno, nel punto giusto.
    from gardawind.util import curva_monotona as _cm

    def curva_finta(punti):
        ux = lambda h: (h - 4.0) / 17.0
        uy = lambda v: v / 60.0
        return {
            "ora_da": 4.0, "ora_a": 21.0, "ymax": 60.0,
            "media": _cm([(ux(h), uy(v)) for h, v in punti], cifre=4),
            "raffica": _cm([(ux(h), uy(v * 1.4)) for h, v in punti], cifre=4),
            "max_kn": round(max(v * 1.4 for _h, v in punti), 1),
            "ultimo": {"x": round(ux(punti[-1][0]), 4),
                       "y": round(uy(punti[-1][1]), 4),
                       "ora": punti[-1][0], "kn": punti[-1][1]},
            "n": len(punti)}

    PUNTI_A = [(6.0, 8.0), (9.0, 12.0), (12.0, 22.0), (14.0, 19.0)]
    PUNTI_B = PUNTI_A + [(16.0, 24.0), (17.5, 21.0)]
    corpo = json_nuovo(ADESSO - dt.timedelta(minutes=4), 21.0, 28.0)
    corpo["luoghi"]["Torbole"]["curve"] = curva_finta(PUNTI_A)
    pg, _ = apri(ctx, corpo)

    svg_id = pg.eval_on_selector('svg.chart[data-today="1"]', "e => e.id")
    d1 = pg.eval_on_selector("#%s-live-w" % svg_id, "e => e.getAttribute('d')")
    ok(bool(d1) and d1.startswith("M") and "C" in d1,
       "la curva riletta e' in pagina, ed e' una curva (%s...)" % (d1 or "")[:18])
    ok(pg.eval_on_selector("#%s-live" % svg_id,
                           "e => e.getAttribute('opacity')") == "1",
       "il gruppo del misurato riletto e' accesso")
    ok(bool(pg.eval_on_selector("#%s-live-g" % svg_id,
                                "e => e.getAttribute('d')")),
       "e la raffica misurata con lui")

    # Dentro il riquadro, e nel punto giusto: si rifa' la mappa dai data-*
    # del disegno e si controlla che il browser sia arrivato dove doveva.
    box = pg.eval_on_selector('svg.chart[data-today="1"]', """e => ({
        W:+e.getAttribute('data-w'), H:+e.getAttribute('data-h'),
        pl:+e.getAttribute('data-pl'), pr:+e.getAttribute('data-pr'),
        pt:+e.getAttribute('data-pt'), pb:+e.getAttribute('data-pb'),
        top:+e.getAttribute('data-top'), h0:+e.getAttribute('data-h0'),
        h1:+e.getAttribute('data-h1'), tenue:e.getAttribute('data-tenue'),
        place:e.getAttribute('data-place')})""")
    import re as _re
    coppie = [(float(a), float(b)) for a, b in
              _re.findall(r"(-?[\d.]+),(-?[\d.]+)", d1)]
    dentro = all(box["pl"] - 1 <= xx <= box["W"] - box["pr"] + 1
                 and box["pt"] - 1 <= yy <= box["H"] - box["pb"] + 1
                 for xx, yy in coppie)
    ok(dentro, "e sta dentro il riquadro del disegno, non sopra le scritte")
    Wp = box["W"] - box["pl"] - box["pr"]
    Hp = box["H"] - box["pb"] - box["pt"]
    atteso_x = (box["pl"] + Wp * (PUNTI_A[0][0] - box["h0"])
                / (box["h1"] - box["h0"]))
    atteso_y = (box["H"] - box["pb"]) - Hp * PUNTI_A[0][1] / box["top"]
    ok(abs(coppie[0][0] - atteso_x) < 0.4 and abs(coppie[0][1] - atteso_y) < 0.4,
       "e il primo punto cade dove cadono le 06:00 a 8 kn: (%.1f, %.1f) contro"
       " (%.1f, %.1f)" % (coppie[0] + (atteso_x, atteso_y)))
    dot = pg.eval_on_selector("#%s-live-dot" % svg_id,
                              "e => [+e.getAttribute('cx'),+e.getAttribute('cy')]")
    atteso_dx = (box["pl"] + Wp * (PUNTI_A[-1][0] - box["h0"])
                 / (box["h1"] - box["h0"]))
    ok(abs(dot[0] - atteso_dx) < 0.6,
       "il pallino sta sull'ultima misura (%.1f contro %.1f)"
       % (dot[0], atteso_dx))

    # E la previsione si fa da parte, anche se la pagina e' nata senza niente
    # di misurato: da sola non si sarebbe mai tirata indietro.
    ok(pg.eval_on_selector("#%s-prev" % svg_id,
                           "e => e.getAttribute('opacity')") == box["tenue"],
       "la previsione si sbiadisce all'arrivo della misura (%s)" % box["tenue"])
    vecchio = pg.query_selector("#%s-oss" % svg_id)
    ok(vecchio is None or vecchio.get_attribute("opacity") == "0",
       "e la curva della costruzione si spegne: una misura per volta")

    # Un file piu' recente con una curva piu' lunga: la riga cresce.
    corpo2 = json_nuovo(ADESSO - dt.timedelta(minutes=1), 21.0, 28.0)
    corpo2["luoghi"]["Torbole"]["curve"] = curva_finta(PUNTI_B)
    pg.evaluate("d => gwApplyLive(d)", corpo2)
    d2 = pg.eval_on_selector("#%s-live-w" % svg_id, "e => e.getAttribute('d')")
    ok(d2 != d1 and len(d2) > len(d1),
       "un file piu' recente allunga la curva senza ricaricare la pagina")

    # Un file SENZA curva non cancella quella che c'e': una centralina muta
    # non deve far sparire la misura di stamattina.
    corpo3 = json_nuovo(ADESSO, 21.0, 28.0)
    pg.evaluate("d => gwApplyLive(d)", corpo3)
    ok(pg.eval_on_selector("#%s-live-w" % svg_id,
                           "e => e.getAttribute('d')") == d2,
       "un file senza curva lascia in pagina quella che c'e'")

    # E un file piu' VECCHIO non fa tornare indietro la curva.
    corpo4 = json_nuovo(ADESSO - dt.timedelta(minutes=30), 21.0, 28.0)
    corpo4["generato"] = iso_utc(ADESSO - dt.timedelta(hours=2))
    corpo4["luoghi"]["Torbole"]["curve"] = curva_finta(PUNTI_A)
    pg.evaluate("d => gwApplyLive(d)", corpo4)
    ok(pg.eval_on_selector("#%s-live-w" % svg_id,
                           "e => e.getAttribute('d')") == d2,
       "e un file pubblicato in ritardo non accorcia la curva")
    errori = []
    pg.on("pageerror", lambda e: errori.append(str(e)))
    pg.wait_for_timeout(200)
    ok(not errori, "niente errori in console: %s" % (errori[:1] or "nessuno"))
    pg.close()

    browser.close()

# --------------------------------------------------------------------------
# Una rilettura mancata deve DIRSI, non farsi confondere con una centralina zitta
# --------------------------------------------------------------------------
# Domanda di Gian: "il nostro sito e' fermo". Tutta la catena era a posto - il
# processo veloce girava, live.json era fresco e ben formato, la pagina aveva
# l'indirizzo giusto - e l'unico anello non verificabile da qui era la
# richiesta dal SUO browser. Il problema e' che quell'anello, rompendosi, si
# presentava identico a un guasto delle centraline: un numero che invecchia.
#
# Sono due cose diverse da fare: se le centraline sono zitte non c'e' niente
# da aggiustare; se e' la pagina che non raggiunge il file, il dato fresco
# esiste e non arriva, e chi guarda non ha modo di saperlo.
import re as _re

_H = web.page_home()
ok("GW_NOREACH" in _H and web.BANNER_NON_RAGGIUNGIBILE in _H,
   "la pagina porta con se' la frase per la rilettura mancata")
ok("gwMancate=0" in _H.replace(" ", ""),
   "e un contatore dei tentativi mancati, che parte da zero")
ok(_re.search(r"gwMancate\s*\+\+", _H) is not None,
   "che cresce quando gli indirizzi sono esauriti")
ok(_re.search(r"gwMancate\s*=\s*0;\s*gwApplyLive", _H) is not None,
   "e si azzera appena una rilettura riesce")
# L'ordine conta: la frase della rilettura mancata deve stare PRIMA del
# controllo sull'eta', altrimenti vince "ultimo dato reale cinque ore fa" -
# che e' vero e fuorviante, perche' sembra che le centraline siano zitte.
_corpo = _H.split("function gwBanner(")[1].split("function ")[0]
ok(_corpo.index("GW_NOREACH") < _corpo.index("nessuna lettura"),
   "e la dice PRIMA di parlare di eta': un dato che non arriva non e' un"
   " dato che manca")
ok(web.LIVE_MANCATE_PRIMA_DI_DIRLO >= 2,
   "una sola rilettura mancata non basta a dirlo: puo' essere un passaggio"
   " di rete (%d)" % web.LIVE_MANCATE_PRIMA_DI_DIRLO)
