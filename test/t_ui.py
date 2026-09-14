"""I criteri di accettazione della Priorita' 1, come controlli e non come
impressioni.

La resa grafica si guarda con gli occhi, ma le regole di prodotto no: "i
grafici prima delle card", "massimo cinque giorni", "niente diagnostica in
home", "raffica scritta per esteso", "nessun +-80 min mostrato all'utente"
sono affermazioni verificabili sul documento prodotto. Se un domani qualcuno
rimette la riga tecnica in home o riporta la pagina a sette giorni, questo
file lo dice prima del deploy invece che dopo.

Il prodotto viene costruito a mano: serve una pagina, non un modello, e
dipendere dal banco di prova completo renderebbe questi controlli lenti e
accoppiati a un altro file.
"""
import os, sys, re
os.environ["GARDAWIND_HOME"] = "/tmp/gwui"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import shutil
shutil.rmtree("/tmp/gwui", ignore_errors=True)

from gardawind import store, config, engine, web
store.init()
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)


def profilo(base):
    out = []
    for h in range(4, 21):
        w = base * (0.3 + 0.7 * max(0.0, 1 - abs(h - 16) / 6.0))
        out.append({"hour": h, "key": "2026-09-14T%02d:00:00Z" % h,
                    "wind": w, "gust": w * 1.4, "lo": max(0.0, w - 2), "hi": w + 2,
                    "dir": 200, "t2m": 24.0, "cloud": 20.0, "precip": 0.0})
    return out


def fiducia(liv):
    return {"livello": liv, "etichetta": ["outlook", "tendenza", "buona affidabilità",
                                          "alta affidabilità"][liv],
            "motivo": "motivo di prova", "uso": "uso di prova",
            "componenti": {"timing_min": 83.0}}


def sessione(speed, prob, liv, source="appreso"):
    return {"prob": prob, "speed": speed, "lo": speed - 2, "hi": speed + 2,
            "grade": "BUONO", "source": source, "peak_hour": 16.2,
            "peak_hour_mae_min": 83.0, "mae": 1.8, "validata": True,
            "band_source": "residui misurati", "n_models": 8, "weights": "verificato",
            "affidabilita": fiducia(liv),
            "window": {"from": 14, "to": 18, "gust": speed * 1.4,
                       "from_min": 14 * 60 + 10, "to_min": 18 * 60}}


GIORNI = []
for lead in range(8):
    GIORNI.append({
        "day": "2026-09-%02d" % (14 + lead), "lead": lead,
        "sessions": {
            "Torbole-Ora": sessione(18.0, 0.86, 2),
            "Torbole-Peler": sessione(12.0, 0.55, 1),
            "Malcesine-Ora": sessione(11.0, 0.5, 0, source="prior"),
            "Malcesine-Peler": sessione(7.0, 0.3, 0, source="prior"),
            "Malcesine-Giorno": sessione(24.0, 0.4, 1),
        },
        "places": {
            "Torbole": {"profile": profilo(20.0),
                        "live": {"wind": 14.0, "gust": 20.0, "dir": 20.0,
                                 "ts": "2026-09-14T09:42:00Z", "age_min": 6.0,
                                 "stale": False}},
            "Malcesine": {"profile": profilo(13.0),
                          "live": {"wind": 8.0, "gust": 12.0, "dir": 30.0,
                                   "ts": "2026-09-14T09:40:00Z", "age_min": 8.0,
                                   "stale": False}},
        },
    })

engine.by_day = lambda product=None: [dict(g) for g in GIORNI]
engine.ensure_update = lambda force=False: False
H = web.page_home()
D = web.page_diagnostics()

# ---- quanti giorni ----
ok(H.count('class="dcard"') == 5, "cinque card giorno, non otto (%d)" % H.count('class="dcard"'))
ok("Tra 6 giorni" not in H and "Tra 7 giorni" not in H,
   "nessun giorno oltre il quinto")
ok(H.count('class="place p') == 10, "cinque giorni per due luoghi (%d sezioni)"
   % H.count('class="place p'))
ok(H.count("hidden") >= 8, "solo il giorno scelto e' visibile")

# ---- i grafici prima delle card descrittive ----
for place in config.PLACES:
    i_place = H.index(">%s</h2>" % place)
    resto = H[i_place:]
    i_chart = resto.index('<svg class="chart"')
    i_call = resto.index('class="callout')
    i_half = resto.index('class="half"')
    ok(i_chart < i_call and i_chart < i_half,
       "%s: il grafico viene prima di callout e mezze giornate" % place)

# ---- nessun dettaglio tecnico in home ----
ok("Da dove arriva la previsione" not in H, "il pannello delle fonti non e' in home")
ok("Da dove arriva la previsione" in D, "il pannello delle fonti e' in diagnostica")
ok("MAE fuori campione" not in H, "nessun MAE in home")
ok("MAE fuori campione" in D, "il MAE resta in diagnostica")
ok("Tutto il giorno" not in H, "via il riquadro ridondante di Malcesine")
ok("pesi verificato" not in H and "modelli disponibili a questa scadenza" not in H,
   "via la riga tecnica sulle fonti dell'ensemble")

# ---- timing: nessun intervallo di errore mostrato all'utente ----
ok(not re.search(r"Timing:.{0,40}±", H), "nessun '±NN min' come intervallo utente")
ok("83 min" not in H, "l'errore medio del picco non compare in home")
ok("incerto" in H, "quando la finestra non e' misurata, l'orario si dichiara incerto")

# con una finestra di ingresso misurata, invece, i minuti compaiono con la copertura
G2 = [dict(g) for g in GIORNI]
s = dict(G2[0]["sessions"])
t = dict(s["Torbole-Ora"])
t["ingresso"] = {"min": 12 * 60 + 40, "half_min": 35.0, "coverage": 0.68}
s["Torbole-Ora"] = t
G2[0] = dict(G2[0], sessions=s)
engine.by_day = lambda product=None: G2
H2 = web.page_home()
ok("Ingresso più probabile" in H2 and "12:40" in H2, "finestra di ingresso mostrata")
ok("copre il 68%" in H2, "la copertura e' dichiarata accanto alla finestra")

# ---- raffica: la parola per esteso, e la curva nel grafico ----
ok("raffica" in H, "la parola raffica e' scritta per esteso")
ok(not re.search(r"\braff\b", H), "mai abbreviata in 'raff'")
ok(H.count("stroke-dasharray") >= 10, "curva della raffica tratteggiata in ogni grafico")

# ---- il dato live porta la sua ora ----
ok("ultimo dato" in H, "l'orario dell'ultima lettura e' mostrato")
ok("11:42" in H or "09:42" in H, "e' l'ora vera del campione, convertita in locale")

# ---- distinzione fra i due luoghi, senza tab in alto ----
ok('class="place p1"' in H and 'class="place p2"' in H,
   "ogni luogo ha la propria cornice colorata")
# Solo il markup visibile: il foglio di stile nomina i due luoghi in un
# commento sulla palette, e non e' quello che il criterio vuole escludere.
head = H[H.index("</style>"):H.index("<main")]
ok("Torbole" not in head and "Malcesine" not in head,
   "nessun tab Torbole/Malcesine nella testa della pagina")

# ---- un tema solo, dichiarato ----
ok("prefers-color-scheme" not in H, "nessun secondo tema mezzo curato")
ok('content="dark"' in H, "il tema scuro e' dichiarato al browser")

# ---- affidabilita': niente percentuali inventate ----
ok(not re.search(r"Affidabilità[^<]*</p>\s*<div[^>]*>\s*\d+\s*%", H),
   "nessuna percentuale di affidabilita' inventata")
ok("Tendenza" in H or "Buona" in H or "Alta" in H or "Outlook" in H,
   "l'affidabilita' e' una parola, non un numero")
