"""Il sito di Addicted rifatto (6 novembre 2026): misure orarie e previsione.

Il 15/11/2026 un controllo dell'andamento ha trovato Campione e Malcesine
spiaggia mute da nove giorni: "/forecast/..." rimandava a "/vorhersage/..." e
"?json=wind" restituiva una pagina. Qui sta fermo quello che si legge adesso.

I numeri delle misure sono quelli VERI, copiati il 15/11/2026 dalla risposta di
"/vorhersage/api/karte?ov=gardasee&d=..." letta dal browser, per tre giorni
scelti apposta: un giorno qualunque (5 novembre), il giorno dell'ora legale
(29 marzo, le 02 non esistono) e quello dell'ora solare (25 ottobre, le 02
esistono due volte e la risposta ha comunque 24 caselle). Le direzioni dei due
giorni del cambio dell'ora non sono state copiate e qui sono None: il lettore
la direzione non la usa.

Le righe della pagina di previsione sono il markup vero di Campione dello
stesso giorno, con i disegni svg tolti. Il tranello sta li': PRIMA delle righe
c'e' una tabella con le stesse classi e gli stessi numeri.
"""
import datetime as dt
import json
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwaddnuovo"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
shutil.rmtree("/tmp/gwaddnuovo", ignore_errors=True)

from gardawind import config, engine, store
from gardawind.sources import addicted as A
from gardawind.sources.http import FetchError

passati = 0


def ok(c, m):
    global passati
    passati += 1 if c else 0
    print(("PASS " if c else "FAIL ") + m)


UTC = dt.timezone.utc
store.init()
N = None


def stazione(nome, slug, giorno, medie, direzioni, raffiche, chiave="p0"):
    return {"key": chiave, "name": nome, "lat": 45.7, "lon": 10.8, "own": True,
            "opName": "", "stale": 30, "spot": nome, "region": "Lago di Garda",
            "country": "IT", "rk": "gardasee",
            "url": "/vorhersage/gardasee/%s/rueckblick/?d=%s" % (slug, giorno),
            "h": [medie, direzioni, raffiche]}


G5 = "2026-11-05"
MISURE_5 = {"date": G5, "stations": [
    stazione("Malcesine", "malcesine", G5,
             [N, 3, 3, 8, 12, 12, 10, 10, 9, 5, 8, 5, 4, 8, 9, 8, 4, 3, 3, 2, 4, 3, 4, 7],
             [N, 352, 337, 337, 337, 337, 337, 337, 337, 337, 337, 337, 253, 180,
              180, 172, 139, 124, 105, 75, 27, 337, 337, 337],
             [N, 8, 10, 17, 20, 18, 17, 17, 14, 10, 14, 11, 10, 12, 15, 14, 9, 7, 5,
              7, 11, 10, 10, 14], "p248"),
    stazione("Torbole", "torbole", G5,
             [4, 4, 3, 5, 7, 9, 8, 8, 7, 7, 7, 4, 1, 5, 8, 9, 5, 1, 1, 2, 4, 4, 6, 6],
             [0, 0, 0, 0, 0, 353, 7, 353, 0, 0, 0, 28, 191, 210, 210, 199, 241, 337,
              0, 0, 0, 0, 0, 353],
             [11, 11, 12, 14, 19, 20, 22, 17, 17, 18, 20, 17, 5, 15, 19, 20, 18, 5,
              4, 6, 10, 12, 13, 15], "p359"),
    stazione("Campione", "campione", G5,
             [6, 8, 5, 6, 6, 6, 6, 6, 5, 7, 6, 4, 2, 9, 11, 10, 5, 3, 7, 6, 5, 4, 5, 4],
             [0, 0, 356, 349, 353, 356, 349, 349, 349, 26, 23, 26, 34, 203, 210,
              221, 225, 315, 8, 12, 0, 353, 7, 8],
             [15, 16, 15, 15, 16, 15, 15, 13, 13, 14, 11, 9, 10, 12, 15, 15, 11, 9,
              14, 15, 12, 10, 13, 10], "p454"),
]}

# ---- 1. lo slug lo dice il sito ---------------------------------------------
ok(A.slug_da_url("/vorhersage/gardasee/campione/rueckblick/?d=2026-11-05") == "campione",
   "lo slug viene dall'indirizzo della stazione, non dalla chiave p454")
ok(A.slug_da_url("/vorhersage/gardasee/malcesine/") == "malcesine"
   and A.slug_da_url(None) is None and A.slug_da_url("") is None,
   "anche senza la retrospettiva in coda, e un indirizzo vuoto non e' uno slug")

# ---- 2. le misure di un giorno qualunque -------------------------------------
m = A.parse_misure(MISURE_5, G5)
ok(sorted(m) == ["campione", "malcesine", "torbole"],
   "una risposta, tutte le stazioni: %s" % sorted(m))
ok(len(m["campione"]) == 24 and len(m["malcesine"]) == 23,
   "24 ore a Campione; a Malcesine l'ora senza misura si salta, non va a zero")
# 5 novembre: ora solare, UTC+1. Le 14 locali sono le 13 UTC.
per_ts = {r[0]: r for r in m["campione"]}
ok(per_ts["2026-11-05T13:00:00Z"][1:3] == (11.0, 15.0),
   "l'indice e' l'ora LOCALE: le 14 di Campione (11 kn, raffica 15) sono le 13 UTC")
ok(m["campione"][0][0] == "2026-11-04T23:00:00Z",
   "e la mezzanotte locale e' le 23 UTC del giorno prima")
ok(all(r[3] is None for righe in m.values() for r in righe),
   "la direzione non entra: lo zero non distingue il nord dalla banderuola assente")

# ---- 3. i due giorni del cambio dell'ora -------------------------------------
G3 = "2026-03-29"
marzo = {"date": G3, "stations": [stazione(
    "Campione", "campione", G3,
    [7, 11, N, 13, 11, 9, 9, 10, 14, 15, 15, 13, 11, 10, 10, 10, 8, 4, 3, 3, 5, 3, 6, 7],
    [N] * 24,
    [21, 22, N, 23, 23, 20, 18, 26, 29, 32, 29, 23, 22, 22, 19, 20, 16, 9, 12, 13,
     12, 11, 18, 18])]}
r3 = A.parse_misure(marzo, G3)["campione"]
ok(len(r3) == 23 and len({r[0] for r in r3}) == 23,
   "29 marzo: 23 ore, tutte su istanti diversi")
ok(r3[1][0] == "2026-03-29T00:00:00Z" and r3[2][0] == "2026-03-29T01:00:00Z"
   and r3[2][1] == 13.0,
   "le 01 sono le 00 UTC e le 03 (13 kn) sono le 01 UTC: nessun buco, nessun doppione")
# Se un giorno le 02 di marzo arrivassero piene, non devono finire sopra le 03.
piena = json.loads(json.dumps(marzo))
piena["stations"][0]["h"][0][2] = 99 - 50
rp = A.parse_misure(piena, G3)["campione"]
ok(len(rp) == 23 and dict((r[0], r[1]) for r in rp)["2026-03-29T01:00:00Z"] == 13.0,
   "un valore nella casella delle 02 che non esistono si scarta, e le 03 restano le 03")

G10 = "2026-10-25"
ottobre = {"date": G10, "stations": [stazione(
    "Campione", "campione", G10,
    [4, 5, 4, 4, 5, 4, 4, 4, 4, 7, 6, 4, 2, 2, 6, 6, 6, 5, 2, 4, 3, 4, 9, 8], [N] * 24,
    [13, 14, 10, 10, 15, 12, 12, 12, 13, 14, 12, 8, 7, 8, 10, 9, 12, 9, 9, 12, 10,
     14, 22, 19])]}
r10 = A.parse_misure(ottobre, G10)["campione"]
ok(len(r10) == 24 and len({r[0] for r in r10}) == 24
   and r10[0][0] == "2026-10-24T22:00:00Z" and r10[-1][0] == "2026-10-25T22:00:00Z",
   "25 ottobre: 24 caselle, 24 istanti diversi, dalle 22 UTC alle 22 UTC")

# ---- 4. quello che non torna ferma la lettura --------------------------------
def rifiuta(dati, giorno=G5):
    try:
        A.parse_misure(dati, giorno)
        return False
    except FetchError:
        return True


ok(rifiuta({"date": G5, "stations": []}) and rifiuta([]) and rifiuta({"date": G5}),
   "senza stazioni: errore")
ok(rifiuta(MISURE_5, "2026-11-06"),
   "chiesto un giorno e risposto un altro: errore, non ore sotto la data sbagliata")
corta = json.loads(json.dumps(MISURE_5))
corta["stations"][2]["h"][0] = corta["stations"][2]["h"][0][:23]
ok(rifiuta(corta), "una serie di 23 caselle: errore, non un'ora indovinata")
fuori = json.loads(json.dumps(MISURE_5))
fuori["stations"][2]["h"][0][5] = 300
fuori["stations"][2]["h"][2][6] = 400
rf = A.parse_misure(fuori, G5)["campione"]
ok(len(rf) == 23 and rf[5][2] is None,
   "300 nodi di media si scartano, 400 di raffica diventano 'non lo so'")

# ---- 5. la lettura, con la provenienza ---------------------------------------
chiamate = []


def finta_rete(risposte):
    def _f(url, **k):
        chiamate.append(url)
        for pezzo, corpo in risposte.items():
            if pezzo in url:
                if isinstance(corpo, Exception):
                    raise corpo
                return corpo
        raise FetchError("indirizzo non previsto dal controllo: %s" % url)
    return _f


A.fetch_text = finta_rete({"d=" + G5: json.dumps(MISURE_5)})
per_slug, meta = A.fetch_misure(G5)
ok(chiamate == [config.URL_ADDICTED_MISURE + G5],
   "una richiesta sola, all'indirizzo che la mappa del sito usa da se'")
ok(meta["parser_version"] == "addicted-misure/1" and meta["channel"] == "misure"
   and meta["decimali"] is False and meta["direzione_misurata"] is False,
   "con la versione del lettore, e dichiarando che i valori sono interi")
A.fetch_text = finta_rete({"d=": "<!DOCTYPE html><html>"})
try:
    A.fetch_misure(G5)
    ok(False, "una pagina al posto del json deve fermare la lettura")
except FetchError:
    ok(True, "una pagina al posto del json ferma la lettura (e' il guasto del 6/11)")
reg = store.raw_fetches(source="addicted-sports", channel="misure")
ok(len(reg) == 2 and reg[0]["ok"] == 0 and reg[0]["ha_corpo"] == 1,
   "e la lettura fallita lascia il corpo nel registro")

# ---- 6. la pagina di previsione ----------------------------------------------
def riga(ora, media, raffica, classe=""):
    # Il markup vero di una riga oraria (Campione, 15/11/2026), svg tolti.
    return ('<div class="vh-row%s"><div class="vh-row-h"><b class="vh-night">%02d Ora</b>'
            '<span class="vh-mut"> N</span></div><div class="vh-row-w">'
            '<span class="vh-gbw vh-gbw-h"><span class="vh-gb vh-gb-h" style="width:26.4%%">'
            '<span class="windColor acht vh-gb-edge"></span>'
            '<span class="windColor acht vh-gb-g" style="flex:6.2"></span>'
            '<span class="windColor vh-calm vh-gb-m" style="flex:4.8"></span></span>'
            '<span class="vh-gb-out"><span class="vh-gb-mv"><span class="vh-v" '
            'data-kn="%s">%d</span></span><span class="vh-gb-gv"><span class="vh-v" '
            'data-kn="%s">%d</span></span></span></span></div><div class="vh-row-x">'
            '<span class="vh-t vh-t2">9°</span></div></div>'
            % (classe, ora, media, round(float(media)), raffica, round(float(raffica))))


def giornata(k, titolo, righe):
    # La testata vera, e PRIMA delle righe la tabella con le stesse classi.
    return ('<section class="vh-day" id="vh-d%d"><div class="vh-dayhead">'
            '<div class="vh-daytitle"><h2>%s</h2><span class="vh-rel">Oggi</span></div>'
            '<div class="vh-dayinfo vh-mut"><span class="vh-desk">Max. '
            '<span class="vh-v" data-kn="44.4">44</span> <span class="vh-unit">kn</span>'
            ' da S alle 15</span></div></div>'
            '<div class="vh-scroll"><table class="vh-tbl"><tr><td><span class="vh-gbw">'
            '<span class="vh-gb-gv"><span class="vh-v" data-kn="55.5">56</span></span>'
            '<span class="vh-gb-mv"><span class="vh-v" data-kn="33.3">33</span></span>'
            '</span></td></tr></table></div>'
            '<div class="vh-rows"><div class="vh-row vh-rowhead"><div class="vh-row-w">'
            '<b>Vento · <span class="vh-unit">kn</span></b></div></div>%s</div></section>'
            % (k, titolo, "".join(righe)))


ADESSO = dt.datetime(2026, 11, 15, 11, 10, tzinfo=UTC)
PAGINA = ('<main class="vh" id="vh" data-unit="kn"><div class="vh-meas-line vh-mut">'
          '<span>Misurato 12:00: <b><span class="vh-now-v"><span class="vh-v" '
          'data-kn="5.1">5</span></span></b>, Raffiche <span class="vh-v" '
          'data-kn="9.2">9</span> · da N</span></div>'
          + giornata(0, "domenica 15 nov",
                     [riga(0, "4.8", "11", " vh-off"), riga(1, "3.5", "10.9", " vh-off vh-h1"),
                      riga(14, "4.5", "9.9")])
          + giornata(1, "lunedì 16 nov", [riga(19, "4.7", "12")])
          + '</main>')
p = A.parse_pagina_previsione(PAGINA, adesso=ADESSO)
ok([(r[0], r[1]) for r in p] == [("2026-11-14T23:00:00Z", 4.8),
                                 ("2026-11-15T00:00:00Z", 3.5),
                                 ("2026-11-15T13:00:00Z", 4.5),
                                 ("2026-11-16T18:00:00Z", 4.7)],
   "la previsione: media con i decimali di data-kn, ora locale -> UTC (%d ore)" % len(p))
ok(all(w not in (33.3, 44.4, 55.5, 5.1, 9.2, 11.0) for _t, w, _l, _h in p),
   "mai i numeri della tabella prima delle righe, ne' il massimo del giorno, "
   "ne' il MISURATO, ne' la raffica")
ok(all(r[2] is None and r[3] is None for r in p),
   "la banda lo/hi non c'e' piu' e resta vuota: non si riempie con la raffica")

# Una pagina servita dalla cache attraverso la mezzanotte: i titoli dicono 15 e
# 16, ma oggi e' gia' il 16. Le sezioni non tornano e NON si archiviano.
dopo = dt.datetime(2026, 11, 15, 23, 30, tzinfo=UTC)
try:
    A.parse_pagina_previsione(PAGINA, adesso=dopo)
    ok(False, "una pagina del giorno prima non deve dare ore")
except FetchError:
    ok(True, "pagina di ieri letta oggi: nessuna ora archiviata sotto il giorno sbagliato")
try:
    A.parse_pagina_previsione("<html><main class='fc-wrap'>vecchio</main></html>")
    ok(False, "una pagina senza giornate deve fermare la lettura")
except FetchError:
    ok(True, "una pagina senza le giornate ferma la lettura")

A.fetch_text = finta_rete({"/vorhersage/gardasee/campione/": PAGINA})
_utc_now = A.utc_now
A.utc_now = lambda: ADESSO
chiamate[:] = []
righe, meta = A.fetch_previsione("campione")
ok(chiamate == ["https://it.addicted-sports.com/vorhersage/gardasee/campione/"]
   and len(righe) == 4 and meta["station"] == "campione"
   and meta["parser_version"] == "addicted-pagina/1",
   "la lettura della pagina: un indirizzo, la stazione e la versione nel registro")
# Cambia il vento (numeri e larghezze): la struttura no, e non scatta l'avviso.
A.fetch_text = finta_rete({"/vorhersage/gardasee/campione/":
                           PAGINA.replace("26.4%", "71.9%").replace('"4.8"', '"17.2"')})
_r, meta2 = A.fetch_previsione("campione")
ok(meta2["struttura_cambiata"] is False,
   "cambia il vento, non la struttura: nessun falso avviso a ogni giro")
A.fetch_text = finta_rete({"/vorhersage/gardasee/campione/":
                           PAGINA.replace('<span class="vh-mut"> N</span>',
                                          '<i class="vh-mut"> N</i>')})
_r, meta3 = A.fetch_previsione("campione")
ok(meta3["struttura_cambiata"] is True,
   "ma se rifanno la riga, l'impronta cambia e l'avviso arriva")

# ---- 7. dentro il motore ------------------------------------------------------
def misure_del(giorno, fino_a=24):
    d = json.loads(json.dumps(MISURE_5).replace(G5, giorno))
    for st in d["stations"]:
        for serie in st["h"]:
            serie[fino_a:] = [N] * (24 - fino_a)
    return json.dumps(d)


class ReteDelLago(dict):
    """Risponde a qualunque giorno: oggi fino alle 12, i giorni prima interi."""
    def items(self):
        return [("d=2026-11-15", misure_del("2026-11-15", 13))] + [
            ("d=2026-11-%02d" % g, misure_del("2026-11-%02d" % g)) for g in range(1, 15)
        ] + [("/vorhersage/gardasee/", PAGINA)]


engine.utc_now = lambda: ADESSO
A.fetch_text = finta_rete(ReteDelLago())

# Il giro veloce: una richiesta, solo campioni.
chiamate[:] = []
fatto = engine.leggi_addicted_vivo()
ok(chiamate == [config.URL_ADDICTED_MISURE + "2026-11-15"] and len(fatto) == 2,
   "giro veloce: UNA richiesta per le due centraline (%s)" % fatto)
camp = list(store.connect().execute(
    "SELECT station, source, COUNT(*) AS n, MAX(ts) AS ultimo FROM obs_sample "
    "GROUP BY station, source ORDER BY station"))
ok([(r["station"], r["source"]) for r in camp]
   == [("campione", "addicted-json"), ("malcesine_add", "addicted-json")],
   "con il nome delle NOSTRE stazioni e la fonte della serie oraria")
ok(camp[0]["n"] == 13 and camp[0]["ultimo"] == "2026-11-15T11:00:00Z",
   "le ore di oggi fino a quella in corso (le 12 locali)")
ok(not list(store.connect().execute("SELECT 1 FROM obs_hour")),
   "obs_hour non la tocca il giro veloce")
ok(not list(store.connect().execute(
    "SELECT 1 FROM obs_sample WHERE station LIKE 'torbole%' OR station='T0193'")),
   "e Torbole non entra: la sua pagina mostra Meteotrentino")
engine.leggi_addicted_vivo()
ok(list(store.connect().execute("SELECT COUNT(*) FROM obs_sample"))[0][0] == 13 + 12,
   "due giri sulla stessa ora non raddoppiano le righe")

# Il giro lungo, database vuoto: si torna indietro fino al limite, non oltre.
chiamate[:] = []
giorni = engine.giorni_da_leggere_addicted()
ok(giorni[0] == "2026-11-01" and giorni[-1] == "2026-11-15" and len(giorni) == 15,
   "senza nessuna ora in archivio si recuperano due settimane (%s..%s)"
   % (giorni[0], giorni[-1]))
store.upsert_obs_hours("campione", [{
    "hour": store.chiave_ora("2026-11-06T10:00:00Z"), "wind_mean": 7.0,
    "wind_max": None, "gust_max": 12.0, "gust_rec": None, "dir_deg": None,
    "dir_const": None, "n_samples": 6}])
giorni = engine.giorni_da_leggere_addicted()
ok(giorni[0] == "2026-11-06" and len(giorni) == 10,
   "ultima ora il 6 novembre: si rilegge dal 6 a oggi, il buco del sito rifatto")
fatto = engine.leggi_ore_addicted()
ok(len(chiamate) == 10 and all("api/karte" in u for u in chiamate),
   "dieci richieste per dieci giorni, qualunque sia il numero delle stazioni")
n_c = list(store.connect().execute(
    "SELECT COUNT(*) FROM obs_hour WHERE station='campione'"))[0][0]
n_m = list(store.connect().execute(
    "SELECT COUNT(*) FROM obs_hour WHERE station='malcesine_add'"))[0][0]
ok(n_c == 9 * 24 + 13 and n_m == 9 * 23 + 12,
   "il buco e' riempito: Campione %d ore, Malcesine %d" % (n_c, n_m))
giorni = engine.giorni_da_leggere_addicted()
ok(giorni == ["2026-11-14", "2026-11-15"],
   "e dal giro dopo si torna a ieri e oggi: %s" % giorni)

# Un giorno che non si legge non ferma gli altri, e finisce nel registro.
store.connect().execute("DELETE FROM obs_hour")
store.connect().commit()
rete = dict(ReteDelLago().items())
rete["d=2026-11-14"] = FetchError("HTTP 503")
A.fetch_text = finta_rete(rete)
store.upsert_obs_hours("campione", [{
    "hour": store.chiave_ora("2026-11-13T10:00:00Z"), "wind_mean": 7.0,
    "wind_max": None, "gust_max": 12.0, "gust_rec": None, "dir_deg": None,
    "dir_const": None, "n_samples": 6}])
fatto = engine.leggi_ore_addicted()
ok(len(fatto) == 2 and any("503" in (e["message"] or "")
                           for e in store.recent_events(10)),
   "un giorno in errore: gli altri si salvano e l'errore e' nel registro (%s)" % fatto)

# La loro previsione: archiviata con quando l'abbiamo letta.
A.fetch_text = finta_rete(ReteDelLago())
righe, _m = A.fetch_previsione("campione")
n = store.save_fc_altrui(A.SOURCE, "campione", righe)
ok(n == 4, "la previsione altrui entra in archivio (%d ore)" % n)
A.utc_now = _utc_now
print("%d controlli sul sito nuovo di Addicted" % passati)
