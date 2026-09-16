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

# ---- nuova gerarchia home: adesso in alto, poi Torbole/Malcesine previsione ----
ok(H.count('id="current-panel"') == 1, "un solo riquadro vento attuale in alto")
first_current = H.index('id="current-panel"')
first_place = H.index('class="place p1"')
ok(first_current < first_place, "il vento attuale viene prima delle previsioni")
current = H[first_current:first_place]
ok("Torbole" in current and "Malcesine" in current,
   "il riquadro attuale contiene entrambe le localita'")
ok('grid-template-columns:minmax(0,1fr) 320px' in H,
   "nelle previsioni il grafico ha la colonna principale")
ok(H.count('class="peler-card"') == 10,
   "una scheda Peler per luogo e per giorno (%d)" % H.count('class="peler-card"'))
ok("Finestra utile" in H and "Intensità" in H
   and "Sopra 10 kn" in H and "Sopra 12 kn" in H,
   "la scheda mostra finestra utile, intensita' e le due soglie che contano")
ok("Continuità" in H and "Affidabilità" in H,
   "e in fondo continuita' e affidabilita'")
ok("Pelèr utile" not in H and "≥8:" not in H,
   "via la vecchia riga e via gli 8 kn dalla vista: qualificavano troppo")
# La finestra della scheda e' la finestra UTILE, non quella del regime: al
# Peler il regime comincia alle 04:00 e nessuno naviga al buio. Il controllo
# guarda l'ora stampata, non la funzione che la calcola.
import re as _re2
finestre = _re2.findall(r"<span>Finestra utile</span><b>(\d\d):(\d\d)", H)
ok(bool(finestre), "la finestra utile viene stampata (%d schede)" % len(finestre))
ok(all(int(h) * 60 + int(m) >= 6 * 60 for h, m in finestre),
   "e non comincia mai prima delle 06:00, che e' l'ora pratica: %s"
   % sorted(set("%s:%s" % f for f in finestre)))
ok("04:00–" not in H.split('class="peler-card"')[1][:400],
   "in particolare non e' la finestra del regime che parte alle 04:00")
ok("current.hidden = (i!=='0')" in H,
   "scegliendo un altro giorno il riquadro attuale scompare")

# ---- i grafici prima delle card descrittive ----
for place in config.PLACES:
    i_place = H.index(">%s</h2>" % place)
    resto = H[i_place:]
    i_chart = resto.index('<svg class="chart"')
    i_call = resto.index('class="callout')
    i_peler = resto.index('class="peler-card"')
    i_half = resto.index('class="half"')
    ok(i_chart < i_call and i_chart < i_peler and i_chart < i_half,
       "%s: il grafico resta il primo elemento, prima di commento, Peler e Ora"
       % place)
    ok(i_peler < i_half, "%s: e il Peler viene prima dell'Ora" % place)

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
# La riga "orario incerto" e' uscita dalla home: diceva sempre la stessa cosa,
# perche' nessuno spot passa la porta dei 45 minuti. Il gate NON e' stato
# tolto - vive in orari.py e nel report - ma la home non lo ripete piu'.
ok("Orario <b>incerto</b>" not in H,
   "via il messaggio 'orario incerto', che era costante e quindi muto")
ok(not re.search(r"Ingresso pi\u00f9 probabile", H),
   "e via anche l'ora di ingresso, che quella porta non l'ha mai aperta")

# ---- oggi: il dato misurato prevale sul giudizio emesso stanotte ----
# Non e' un nowcast: non sposta la curva futura, che e' il banco chiuso.
# Serve a non dire "discreto" mentre l'anemometro misura diciassette nodi.
live_ora = {"wind": 17.0, "gust": 22.0,
            "dir": config.SPOTS["Torbole-Ora"]["axis_obs"],
            "ts": GIORNI[0]["day"] + "T13:00:00Z", "age_min": 5.0,
            "stale": False}
st = web.live_regime_state(live_ora, config.SPOTS["Torbole-Ora"], today=True)
ok(st and st["cls"] == "go", "17 kn di Ora osservata diventano Buono")
cls_l, word_l = web.quality(GIORNI[0]["sessions"]["Torbole-Ora"],
                            config.SPOTS["Torbole-Ora"], live_ora, True)
ok(cls_l == "go" and word_l == "Buono",
   "il giudizio di oggi segue il dato fresco (%s / %s)" % (cls_l, word_l))
ok(web.live_regime_state(live_ora, config.SPOTS["Torbole-Ora"],
                         today=False) is None,
   "ma un giorno futuro non lo tocca: la previsione resta quella")
vecchio = dict(live_ora, age_min=90.0)
ok(web.live_regime_state(vecchio, config.SPOTS["Torbole-Ora"], today=True) is None,
   "un campione stantio non decide niente")
# Diciassette nodi da nord NON sono Ora buona: il settore e' una condizione.
da_nord = dict(live_ora, dir=(config.SPOTS["Torbole-Ora"]["axis_obs"] + 180.0) % 360)
ok(web.live_regime_state(da_nord, config.SPOTS["Torbole-Ora"], today=True) is None,
   "e fuori dal settore non e' quel regime, per forte che sia")
# Fuori dalla finestra del regime, nemmeno: l'Ora alle 6 del mattino non c'e'.
presto = dict(live_ora, ts=GIORNI[0]["day"] + "T04:00:00Z")
ok(web.live_regime_state(presto, config.SPOTS["Torbole-Ora"], today=True) is None,
   "e fuori dall'orario del regime non e' quel regime")

# ---- la scheda parla di UNA finestra sola ----
# Il caso che questo controllo difende e' reale ed era il primo difetto della
# scheda: il picco della sessione e' quello della finestra del REGIME, che al
# Peler comincia alle 04:00. Con un Peler forte alle cinque del mattino e
# debole dalle sette in poi, la card scriveva "Intensita' 10-14 kn" accanto a
# "Sopra 10 kn: -" nello stesso riquadro. Due finestre in una scheda.
def _profilo(valori):
    """valori: {ora: vento}. lo/hi stretti attorno, come fa l'ensemble."""
    return [{"hour": h, "wind": w, "gust": w * 1.4, "lo": w - 1.0, "hi": w + 1.0}
            for h, w in sorted(valori.items())]


_sess = {"Torbole-Peler": dict(GIORNI[0]["sessions"]["Torbole-Peler"],
                               speed=14.0, lo=12.0, hi=16.0, prob=0.8)}
_oggi = GIORNI[0]["day"]
# Forte alle 5 (fuori finestra), debole dalle 7: la scheda deve dire debole.
buio = web.peler_card("Torbole", _profilo({4: 15.0, 5: 15.0, 6: 9.0, 7: 6.0,
                                           8: 6.0, 9: 6.0, 10: 6.0, 11: 5.0}),
                      _sess, _oggi)
ok("q-no" in buio or "q-meh" in buio,
   "vento forte solo prima dell'alba: la scheda non dice Buono")
ok("15" not in buio.split("Intensit")[1][:60],
   "e l'intensita' non e' quella dei quindici nodi al buio: %s"
   % buio.split("Intensit")[1][:60].replace("\u00e0", ""))
ok("Sopra 10 kn</span><b>\u2014</b>" in buio
   or "Sopra 10 kn</span><b>&mdash;</b>" in buio,
   "e sopra i 10 non c'e' niente, perche' dentro la finestra non ci arriva")

# Lo specchio: forte per tutta la finestra utile. Qui la durata TOCCA i bordi,
# quindi e' un limite inferiore e la scheda deve scriverlo.
pieno = web.peler_card("Torbole", _profilo({h: 14.0 for h in range(4, 13)}),
                       _sess, _oggi)
ok("q-go" in pieno, "vento forte per tutta la finestra: Buono")
ok("&ge;" in pieno,
   "e la durata e' marcata come limite, perche' tocca i bordi della finestra")
ok("Continuit\u00e0 <b>100%</b>" in pieno
   or "Continuità <b>100%</b>" in pieno,
   "con vento sempre sopra soglia la continuita' e' cento per cento")

# Un giorno d'inverno: la finestra utile comincia dopo, e la scheda lo dice.
inverno = web.peler_card("Torbole", _profilo({h: 12.0 for h in range(4, 13)}),
                         _sess, "2026-12-21")
ok("<b>08:" in inverno,
   "al solstizio d'inverno la finestra utile comincia dopo le otto: %s"
   % (re.search(r"Finestra utile</span><b>([^<]+)", inverno) or ["?"])[0][-14:])
estate = web.peler_card("Torbole", _profilo({h: 12.0 for h in range(4, 13)}),
                        _sess, "2026-06-21")
ok("<b>06:00" in estate,
   "e al solstizio d'estate dall'ora pratica, le sei")

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

# ---- affidabilita': una parola; percentuale solo dove esiste ----
# La distinzione regge ancora, ed e' la ragione per cui l'anello non e' stato
# buttato via ma spostato dentro la scheda: l'affidabilita' alla scadenza
# ("quanto sappiamo a tre giorni") e la probabilita' del regime ("quanto e'
# probabile che il Peler ci sia") sono due grandezze diverse. La prima non ha
# una percentuale perche' non la misuriamo; la seconda si', ed e' del modello.
ok(not re.search(r"Affidabilità\s*<b>\s*\d+\s*%", H),
   "l'affidabilita' non diventa mai una percentuale")
ok(re.search(r"Affidabilità\s*<b>(alta|buona|tendenza|outlook)</b>", H)
   is not None,
   "resta una parola, dentro la scheda Peler")
ok(re.search(r"Probabilità\s*<b>\d+%</b>", H) is not None,
   "e la percentuale che si mostra e' la probabilita' del regime, che esiste")

# --------------------------------------------------------------------------
# La riga del MISURATO si disegna coi campioni, non con le medie orarie
# --------------------------------------------------------------------------
# Domanda di Gian, guardando la pagina di una centralina: "loro hanno una
# precisione live pazzesca, com'e' possibile che non la consideriamo". Le
# misure le usiamo per tutto - il modello e' addestrato su 123.661 ore - ma le
# DISEGNAVAMO per ore, e la media oraria nasconde proprio cio' che la misura
# serve a mostrare. Misurato su 2.769 inversioni di regime in quattordici
# anni: il fondo del buco fra Peler e Ora sta al 25% del livello coi campioni
# veri e al 40% con le medie orarie, e nel 25% dei giri in cui il buco c'e' la
# media lo cancella del tutto.
#
# Qui si costruisce quella situazione: una giornata con un crollo a 1 kn per
# venti minuti alle 07:40, che l'ora 07:00-08:00 mediata a 9 kn nasconde.
FINI = []
for i in range(4 * 6, 21 * 6 + 1):
    m = i * 10.0
    if 7 * 60 + 30 <= m <= 7 * 60 + 50:
        w = 1.0                       # il buco vero, venti minuti
    elif m < 11 * 60:
        w = 11.0
    else:
        w = 16.0
    FINI.append({"hour": m / 60.0, "wind": w, "gust": w * 1.4})
ORARIE = []
for h in range(4, 21):        # la stessa finestra del profilo di prova
    dentro = [r["wind"] for r in FINI if h <= r["hour"] < h + 1]
    if dentro:
        media = sum(dentro) / len(dentro)
        ORARIE.append({"hour": h, "wind": media, "gust": media * 1.4})
media_del_buco = next(r["wind"] for r in ORARIE if r["hour"] == 7)
ok(media_del_buco >= 5.0,
   "il caso e' costruito bene: il fondo vero e' 1 kn e l'ora che lo contiene,"
   " mediata, ne dichiara %.1f - sei volte tanto" % media_del_buco)

OSS = {"righe": ORARIE, "fini": FINI, "raffica_fonte": "ricorrente 30'",
       "ultima_ora": 20}
GG_OSS = [dict(GIORNI[0])]
pl = {k: dict(v) for k, v in GIORNI[0]["places"].items()}
pl["Torbole"] = dict(pl["Torbole"], osservato=OSS)
GG_OSS[0] = dict(GIORNI[0], places=pl, lead=0)
_vecchio_by_day = engine.by_day
engine.by_day = lambda product=None: GG_OSS
try:
    H_OSS = web.page_home()
finally:
    engine.by_day = _vecchio_by_day

misurate = re.findall(r'<polyline points="([^"]+)" fill="none" '
                      r'stroke="var\(--pc\)" stroke-width="3.6"', H_OSS)
ok(misurate and max(len(p.split()) for p in misurate) > 60,
   "la riga del misurato ha i vertici dei campioni, non diciotto (%s)"
   % [len(p.split()) for p in misurate][:3])

# E il buco deve arrivare in fondo al disegno: si controlla sulle ORDINATE,
# perche' e' quello che l'occhio legge. La y cresce verso il basso, quindi il
# punto piu' basso in velocita' e' quello con la y piu' grande.
ys = [float(v.split(",")[1]) for p in misurate for v in p.split()]
ok(ys and max(ys) - min(ys) > 40,
   "e un crollo a 1 kn si vede come tale, non appiattito (escursione %.0f"
   " punti di disegno)" % (max(ys) - min(ys) if ys else 0))

# Il CONFRONTO con la previsione resta orario: e' l'asse su cui e' stato
# validato, e spostarlo a dieci minuti vorrebbe dire confrontare due cose
# diverse senza dirlo.
_sc = web.scarto_line(profilo(20.0), OSS)
ok(_sc is not None and float(_sc["hour"]) == int(_sc["hour"]),
   "la riga dello scarto continua a confrontare su un'ora intera (%s)"
   % (_sc and _sc["hour"]))
