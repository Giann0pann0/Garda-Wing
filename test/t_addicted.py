"""Il parser di addicted-sports contro il markup VERO, e contro i suoi tranelli.

Il frammento HTML qui sotto e' copiato dal corpo grezzo servito dal server di
it.addicted-sports.com il 15 settembre 2026, scaricato con una fetch
same-origin dalla pagina stessa (quindi senza JavaScript di mezzo: i numeri
sono davvero nell'HTML). Non e' inventato e non e' semplificato, ed e' tenuto
qui perche' il giorno in cui il sito cambia impaginazione questo file lo dica
prima del prossimo aggiornamento del sito.

Il tranello sta dentro il frammento, e va guardato bene: il riquadro della
PREVISIONE (fc-hero-main: media 10, raffica 21) viene PRIMA nel documento e
usa le stesse classi del riquadro MISURATO (fc-hero-meas: media 2, raffica
11). Una regex sulla pagina intera prende i numeri della previsione e li
salva come osservazione - e nessuno se ne accorge, perche' sono numeri
plausibili. Il controllo che conta e' quindi: il parser deve restituire 2 e
11, mai 10 e 21.
"""
import datetime as dt
import json
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwaddicted"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
shutil.rmtree("/tmp/gwaddicted", ignore_errors=True)

from gardawind import config, store
from gardawind.sources import addicted as A
from gardawind.sources.http import FetchError

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)
UTC = dt.timezone.utc
store.init()

# --------------------------------------------------------------------------
# Il markup vero, verbatim
# --------------------------------------------------------------------------
PAGINA = (
    '<main class="fc-wrap forecast"><nav class="fc-crumb">'
    '<a href="/forecast/">Vorhersage</a> › <a href="/forecast/gardasee/">'
    'Gardasee</a> › <span>Torbole</span></nav>'
    '<h1>Previsioni vento &amp; meteo Gardasee (Torbole)</h1>'
    '<div class="fc-hero"><div class="fc-hero-main">'
    '<div class="fc-hero-name">Gardasee</div>'
    '<div class="fc-hero-sub">Torbole · oggi</div>'
    '<div class="fc-hero-row"><span class="fc-badge wenig">Poco</span>'
    '<span class="fc-hero-wind"><span class="fc-hero-peak">'
    '<span class="avgs">Ø</span>'
    '<span class="fc-knpill windColor acht">10</span></span>'
    '<span class="fc-hero-boe"><span class="bl">Raffica</span> '
    '<span class="fc-knpill windColor zweinull">21</span></span> '
    '<small>kn</small></span></div></div>'
    '<div class="fc-hero-meas"><div class="lbl">misurato ora · 06:00</div>'
    '<div class="v"><span class="avgs">Ø</span>'
    '<span class="fc-knpill">2</span>'
    '<span class="fc-hero-boe"><span class="bl">Raffica</span> '
    '<span class="fc-knpill windColor acht">11</span></span> '
    '<small>kn</small></div></div>'
    '<a href="/webcam/gardasee/torbole/" title="Webcam live Gardasee">'
    '<img class="fc-hero-cam" src="/fileadmin/webcam/torbole/current/640.jpg" '
    'alt="Webcam Gardasee" loading="lazy"></a></div>'
    '<h2>Meteo e vento per giorno</h2>'
    '<p class="fc-sub">Per ogni giorno il livello di vento <b>più probabile</b>'
    ' e la sua probabilità – con meteo, temperatura, pioggia.</p>'
    '<div class="fc-day fc-day-wenig"><h3>mar, 15.09.</h3>'
    '<div class="fc-wind">Ø 4 · Raffica <b>13</b> kn</div></div>'
    '</main>')

# Alle 06:34 locali (04:34 UTC) la pagina dice "misurato ora · 06:00":
# l'ora civile in corso, non l'ultima conclusa.
ADESSO = dt.datetime(2026, 9, 15, 4, 34, tzinfo=UTC)

campione, etichetta = A.parse_hero(PAGINA, adesso=ADESSO)
ts, w, g, d = campione
ok(w == 2.0 and g == 11.0,
   "html: legge il riquadro MISURATO (%s / %s), non la previsione (10 / 21)"
   % (w, g))
ok(ts == "2026-09-15T04:00:00Z",
   "html: 06:00 ora del lago -> 04:00 UTC (%s)" % ts)
ok(d is None,
   "html: nessuna direzione, perche' la pagina non ne pubblica una misurata")
ok("misurato ora" in etichetta,
   "html: l'etichetta viene conservata (%r)" % etichetta)

# Il ritaglio deve prendere IL riquadro, non mezza pagina.
blocco = A.ritaglia_div(PAGINA, "fc-hero-meas")
ok(blocco.startswith('<div class="fc-hero-meas"') and blocco.endswith("</div>"),
   "html: il ritaglio comincia e finisce sul div giusto")
ok("fc-hero-main" not in blocco and "fc-hero-cam" not in blocco,
   "html: e non si porta dentro ne' la previsione ne' quello che viene dopo")
ok(blocco.count("<div") == blocco.count("</div"),
   "html: i div ritagliati sono bilanciati (%d)" % blocco.count("<div"))

# --------------------------------------------------------------------------
# Quando il markup cambia, il parser deve FALLIRE, non indovinare
# --------------------------------------------------------------------------
def fallisce(pagina, _perche=None):
    try:
        A.parse_hero(pagina, adesso=ADESSO)
        return False
    except FetchError:
        return True


ok(fallisce(PAGINA.replace('class="fc-hero-meas"', 'class="fc-hero-misurato"'),
            "riquadro rinominato"),
   "markup: se il riquadro cambia nome, errore - non i numeri della previsione")
ok(fallisce(PAGINA.replace('<div class="lbl">misurato ora · 06:00</div>',
                           '<div class="lbl">misurato ora</div>')),
   "markup: senza l'ora, errore - non un orario inventato")
ok(fallisce(PAGINA.replace('<span class="fc-knpill">2</span>', '')),
   "markup: senza la pastiglia della media, errore")
ok(fallisce(PAGINA.replace('<span class="avgs">Ø</span>'
                           '<span class="fc-knpill">2</span>',
                           '<span class="fc-knpill">2</span>', 1)
            .replace('<span class="avgs">Ø</span>', '', 1)),
   "markup: senza il segno della media, errore invece di leggere a caso")

# Una raffica assente e' un caso legittimo, non un errore: si perde la
# raffica, non la lettura.
senza_raffica = PAGINA.replace(
    '<span class="fc-hero-boe"><span class="bl">Raffica</span> '
    '<span class="fc-knpill windColor acht">11</span></span> '
    '<small>kn</small></div></div>',
    '<span class="fc-hero-boe"><span class="bl">Raffica</span> '
    '<span class="fc-knpill">-</span></span> <small>kn</small></div></div>')
c2, _e = A.parse_hero(senza_raffica, adesso=ADESSO)
ok(c2[1] == 2.0 and c2[2] is None,
   "html: raffica illeggibile -> vento salvo, raffica None (%s)" % (c2,))

# Un valore fuori scala non entra.
ok(fallisce(PAGINA.replace('<span class="fc-knpill">2</span>',
                           '<span class="fc-knpill">180</span>')),
   "html: 180 nodi non e' un vento: errore")

# --------------------------------------------------------------------------
# La data ricostruita dall'ora: il caso della mezzanotte
# --------------------------------------------------------------------------
# All'01:10 locale una pagina che dicesse 23:00 appartiene a IERI. Senza la
# cautela, la lettura finirebbe ventitre' ore nel futuro.
notte = PAGINA.replace("misurato ora · 06:00", "misurato ora · 23:00")
c3, _e = A.parse_hero(notte, adesso=dt.datetime(2026, 9, 15, 23, 10, tzinfo=UTC))
ok(c3[0] == "2026-09-15T21:00:00Z",
   "html: 23:00 del giorno prima, non del giorno dopo (%s)" % c3[0])

# --------------------------------------------------------------------------
# Canale JSON: la serie oraria misurata
# --------------------------------------------------------------------------
# Forma reale della risposta di "?json=wind&from=...", con le chiavi vere.
# 96 slot nella risposta vera (quattro giorni); qui sei, che bastano.
RISPOSTA = {
    "ok": True, "from": "2026-09-15", "today": "2026-09-15",
    "title": "Anteprima: oggi + prossimi giorni", "nextFrom": None,
    "labels": ["", "", "", "", "", ""],
    "ticks": ["mar 15.09.", "", "", "", "", ""],
    "time": ["mar 15.09. 00:00", "mar 15.09. 01:00", "mar 15.09. 02:00",
             "mar 15.09. 03:00", "mar 15.09. 04:00", "mar 15.09. 05:00"],
    "arch": ["2026/09/15/0000", "2026/09/15/0100", "2026/09/15/0200",
             "2026/09/15/0300", "2026/09/15/0400", "2026/09/15/0500"],
    "cam": ["/fileadmin/webcam/torbole/2026/09/15/0000_lm.jpg", None, None,
            None, None, None],
    "avg": [4.3, 4.1, 4.0, 3.9, 4.2, 4.4],
    "lo": [2.0] * 6, "hi": [7.0] * 6,
    "boe": [12.4, 12.0, 11.8, 11.5, 12.1, 12.9],
    "boelo": [8.0] * 6, "boehi": [16.0] * 6,
    "dir": [341, 340, 338, 339, 341, 342],
    "show_dir": True,
    "mavg": [3.8, 3.1, 2.7, None, 2.0, None],
    "mmax": [8.6, 7.2, 6.4, None, 11.0, None],
    "mae": 1.3,
    "guete": [], "prob": [], "drivers": {},
    "wcUrl": "/webcam/gardasee/torbole/",
    "tilesHtml": "<div class=\"fc-day\"></div>",
    "tableHtml": "<div class=\"fc-wg\"></div>",
}

righe = A.parse_json(RISPOSTA)
ok(len(righe) == 4,
   "json: quattro ore misurate su sei slot, le altre sono future (%d)" % len(righe))
ok(righe[0] == ("2026-09-14T22:00:00Z", 3.8, 8.6, None),
   "json: 00:00 locale -> 22:00 UTC del giorno prima, con i decimali (%s)"
   % (righe[0],))
ok(all(r[3] is None for r in righe),
   "json: nessuna direzione salvata, benche' la risposta ne contenga una")
ok([r[1] for r in righe] == [3.8, 3.1, 2.7, 2.0],
   "json: si prende mavg (misurato), non avg (previsto)")
ok([r[2] for r in righe] == [8.6, 7.2, 6.4, 11.0],
   "json: e mmax come raffica, non boe")

# La direzione prevista NON deve poter entrare da nessuna parte: e' il
# guasto peggiore possibile, perche' alimenterebbe il filtro di settore -
# quello che decide se il vento e' Ora o Peler - con una previsione.
ok(not any(341 in (r[3],) for r in righe),
   "json: 341 gradi (previsti) non compare in nessuna riga")

# Difese sulla forma della risposta.
def json_fallisce(d):
    try:
        A.parse_json(d)
        return False
    except FetchError:
        return True


ok(json_fallisce(dict(RISPOSTA, ok=False)), "json: ok=false -> errore")
ok(json_fallisce(dict(RISPOSTA, mavg=[1.0, 2.0])),
   "json: serie di lunghezze diverse -> errore, non un accoppiamento a caso")
ok(json_fallisce({k: v for k, v in RISPOSTA.items() if k != "arch"}),
   "json: senza arch -> errore (le date non si leggono da 'time')")
fuori = dict(RISPOSTA, mavg=[300.0, 3.1, 2.7, None, 2.0, None])
ok(len(A.parse_json(fuori)) == 3, "json: 300 nodi scartati, il resto resta")
storta = dict(RISPOSTA, arch=["2026/09/15/0000", "buonanotte", "2026/09/15/0200",
                              "x", "2026/09/15/0400", "y"])
ok(len(A.parse_json(storta)) == 3,
   "json: una chiave di slot illeggibile salta quella riga, non tutte")

# --------------------------------------------------------------------------
# Impronte: quella della struttura non si muove col vento
# --------------------------------------------------------------------------
altro_vento = PAGINA.replace('<span class="fc-knpill">2</span>',
                             '<span class="fc-knpill">17</span>')
b1 = A.ritaglia_div(PAGINA, "fc-hero-meas")
b2 = A.ritaglia_div(altro_vento, "fc-hero-meas")
ok(A.impronta(b1) != A.impronta(b2),
   "impronte: il corpo cambia quando cambia il vento (ed e' inutile come sentinella)")
ok(A.impronta_struttura_html(b1) == A.impronta_struttura_html(b2),
   "impronte: la STRUTTURA no - e' questo che la rende una sentinella")
rifatto = b1.replace('class="lbl"', 'class="etichetta"')
ok(A.impronta_struttura_html(b1) != A.impronta_struttura_html(rifatto),
   "impronte: ma cambia se il sito viene rifatto")
ok(A.impronta_struttura_json(RISPOSTA)
   == A.impronta_struttura_json(dict(RISPOSTA, mavg=[9.9] * 6)),
   "impronte: per il json conta l'insieme delle chiavi, non i valori")
ok(A.impronta_struttura_json(RISPOSTA)
   != A.impronta_struttura_json({k: v for k, v in RISPOSTA.items() if k != "mmax"}),
   "impronte: e cambia se una chiave sparisce")

# --------------------------------------------------------------------------
# Provenienza: ogni lettura lascia una riga, e i corpi non si accumulano
# --------------------------------------------------------------------------
A.fetch_text = lambda url, **k: json.dumps(RISPOSTA)
import gardawind.sources.addicted as _A
_A.fetch_text = lambda url, **k: json.dumps(RISPOSTA)

righe2, meta = _A.fetch_hourly("2026-09-15", adesso=ADESSO)
ok(len(righe2) == 4 and meta["parser_version"] == "addicted/1",
   "provenienza: la lettura porta la versione del parser (%s)"
   % meta["parser_version"])
for chiave in ("fetched_at", "url", "sha256", "struct_sha256", "channel",
               "station", "source", "bytes", "raw_id"):
    ok(meta.get(chiave) is not None, "provenienza: c'e' %s" % chiave)
ok(meta["station"] == "torbole_addicted" and meta["source"] == "addicted-sports",
   "provenienza: stazione e fonte come richiesto")
ok(meta["n_provvisorie"] == 1,
   "provenienza: l'ultima ora e' dichiarata provvisoria (e' in corso)")
ok(meta["direzione_misurata"] is False,
   "provenienza: e si dichiara che la direzione non e' misurata")

registro = store.raw_fetches(source="addicted-sports")
ok(len(registro) == 1 and registro[0]["ok"] == 1,
   "provenienza: una riga nel registro delle letture grezze")
ok(registro[0]["ha_corpo"] == 1,
   "provenienza: il primo corpo grezzo viene conservato")

# Una seconda lettura con la stessa struttura non riconserva il corpo.
_A.fetch_hourly("2026-09-15", adesso=ADESSO)
registro = store.raw_fetches(source="addicted-sports")
ok(len(registro) == 2 and registro[0]["ha_corpo"] == 0,
   "provenienza: la seconda lettura, struttura identica, non duplica il corpo")

# Una risposta con una chiave in meno: struttura cambiata, corpo conservato,
# e un avviso nel registro degli eventi.
ridotta = {k: v for k, v in RISPOSTA.items() if k != "tilesHtml"}
_A.fetch_text = lambda url, **k: json.dumps(ridotta)
_A.fetch_hourly("2026-09-15", adesso=ADESSO)
registro = store.raw_fetches(source="addicted-sports")
ok(registro[0]["ha_corpo"] == 1,
   "provenienza: struttura cambiata -> il corpo si conserva")
eventi = [e for e in store.recent_events(20)
          if "addicted" in (e["scope"] or "")]
ok(any("struttura" in (e["message"] or "") for e in eventi),
   "provenienza: e la struttura cambiata diventa un avviso, non un silenzio")

# Un parse fallito lascia una riga con ok=0 e il corpo, che e' il momento in
# cui il corpo serve davvero.
_A.fetch_text = lambda url, **k: '{"ok": false}'
try:
    _A.fetch_hourly("2026-09-15", adesso=ADESSO)
    rotto = False
except FetchError:
    rotto = True
registro = store.raw_fetches(source="addicted-sports")
ok(rotto and registro[0]["ok"] == 0 and registro[0]["ha_corpo"] == 1,
   "provenienza: un parse fallito conserva il corpo e lo dichiara")

# --------------------------------------------------------------------------
# Controllo incrociato fra i due canali
# --------------------------------------------------------------------------
riga = ("2026-09-15T04:00:00Z", 2.4, 11.2, None)
c = A.confronta_canali(riga, ("2026-09-15T04:00:00Z", 2.0, 11.0, None))
ok(c["accordo"] is True,
   "incrocio: mezzo nodo di scarto e' l'arrotondamento, non un disaccordo")
c2 = A.confronta_canali(riga, ("2026-09-15T04:00:00Z", 10.0, 21.0, None))
ok(c2["accordo"] is False and "vento" in c2["fuori"],
   "incrocio: i numeri della previsione al posto di quelli misurati si vedono")
c3 = A.confronta_canali(riga, ("2026-09-15T03:00:00Z", 2.0, 11.0, None))
ok(c3["accordo"] is None,
   "incrocio: istanti diversi non si confrontano, e si dice perche'")

# --------------------------------------------------------------------------
# L'inquadratura oraria della webcam come controllo secondario
# --------------------------------------------------------------------------
u = A.url_frame_webcam("2026-09-15T04:00:00Z")
ok(u.endswith("/2026/09/15/0600_lm.jpg"),
   "webcam: l'inquadratura dell'ora locale corrispondente (%s)" % u)
ok(u.startswith(config.URL_ADDICTED_WEBCAM_FRAMES),
   "webcam: sotto l'indirizzo dichiarato in configurazione")

# --------------------------------------------------------------------------
# Rete assente: si racconta, non si esplode
# --------------------------------------------------------------------------
# Il container in cui giro non raggiunge quel dominio (il proxy risponde 403),
# quindi la lettura dal vivo avviene sul Mac o in Actions. Il comando deve
# sopravvivere a una rete che non c'e' - e va provato, perche' e' lo stato in
# cui si trovera' ogni volta che il sito e' giu'.
def _rifiuta(url, **k):
    raise FetchError("Tunnel connection failed: 403 Forbidden")


_A.fetch_text = _rifiuta
s = _A.raccogli(giorni=2, adesso=ADESSO)
ok(s["n_salvate"] == 0 and len(s["errori"]) == 3,
   "rete assente: due giorni piu' il riquadro, tre errori raccolti (%d)"
   % len(s["errori"]))
ok(s["station"] == "torbole_addicted" and s["confronto"] is None,
   "rete assente: il sommario resta ben formato")
ok(all("403" in e for e in s["errori"]),
   "rete assente: e gli errori dicono cosa e' andato storto")

# E il ripiego: se il canale json non da' niente ma il riquadro c'e', si salva
# almeno quello - un'ora arrotondata e' meglio di nessuna ora.
def _solo_html(url, **k):
    if "json=wind" in url:
        raise FetchError("json non disponibile")
    return PAGINA


_A.fetch_text = _solo_html
s2 = _A.raccogli(giorni=1, adesso=ADESSO)
ok(s2["n_salvate"] == 1 and s2["html"]["campione"][1] == 2.0,
   "ripiego: senza il canale json si salva il riquadro (%s)" % s2["n_salvate"])
righe_salvate = list(store.connect().execute(
    "SELECT ts, wind_kn, gust_kn, dir_deg, source FROM obs_sample "
    "WHERE station='torbole_addicted' ORDER BY ts"))
ok(any(r["source"] == "addicted-sports-hero" for r in righe_salvate),
   "ripiego: e si distingue nella fonte, perche' e' un dato piu' grezzo")
ok(all(r["dir_deg"] is None for r in righe_salvate),
   "salvataggio: nessuna riga porta una direzione (%d righe)" % len(righe_salvate))
