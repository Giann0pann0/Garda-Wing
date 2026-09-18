"""I criteri di accettazione della pagina, come controlli e non come impressioni.

La resa grafica si guarda con gli occhi, ma le regole di prodotto no. "Una
pagina per localita'", "i due riquadri hanno la stessa struttura", "i giorni
portano la data e non 'domani'", "niente diagnostica nella pagina",
"l'affidabilita' e' una percentuale solo dove c'e' una misura dietro" sono
affermazioni verificabili sul documento prodotto. Se un domani qualcuno
rimette la riga tecnica in pagina, o riporta i sette giorni, o fa i due
riquadri di dimensioni diverse, questo file lo dice prima del deploy invece
che dopo.

Il prodotto viene costruito a mano: serve una pagina, non un modello, e
dipendere dal banco completo renderebbe questi controlli lenti e accoppiati a
un altro file.
"""
import os, sys, re
os.environ["GARDAWIND_HOME"] = "/tmp/gwui"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import shutil
shutil.rmtree("/tmp/gwui", ignore_errors=True)

from gardawind import store, config, engine, giudizio, web
store.init()
passati = 0


def ok(c, m):
    global passati
    if c:
        passati += 1
        print("PASS " + m)
    else:
        print("FAIL " + m)


def profilo(base):
    """Due gobbe: Peler al mattino, Ora nel pomeriggio, buco in mezzo."""
    out = []
    for h in range(4, 21):
        peler = 0.55 * base * max(0.0, 1 - abs(h - 7) / 3.2)
        ora = base * max(0.0, 1 - abs(h - 16) / 5.0)
        w = max(1.2, peler + ora)
        out.append({"hour": h, "key": "2026-09-14T%02d:00:00Z" % h,
                    "wind": w, "gust": w * 1.4, "lo": max(0.0, w - 2),
                    "hi": w + 2, "dir": 200 if h >= 11 else 20,
                    "t2m": 24.0, "cloud": 20.0, "precip": 0.0})
    return out


def fiducia(liv, cal=0.05):
    return {"livello": liv, "etichetta": ["outlook", "tendenza",
                                          "buona affidabilità",
                                          "alta affidabilità"][liv],
            "motivo": "motivo di prova", "uso": "uso di prova",
            "misurato": liv > 0,
            "componenti": {"timing_min": 83.0, "cal_err": cal,
                           "n_giorni": 300 if liv else 10}}


def sessione(speed, prob, liv, source="appreso"):
    return {"prob": prob, "speed": speed, "lo": speed - 2, "hi": speed + 2,
            "grade": "BUONO", "source": source, "peak_hour": 16.2,
            "peak_hour_mae_min": 83.0, "mae": 1.8, "validata": True,
            "band_source": "residui misurati", "n_models": 8,
            "weights": "verificato", "affidabilita": fiducia(liv),
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
                                   "ts": "2026-09-14T09:40:00Z",
                                   "age_min": 8.0, "stale": False}},
        },
    })

engine.by_day = lambda product=None: [dict(g) for g in GIORNI]
engine.ensure_update = lambda force=False: False
H = web.page_luogo("Torbole")
M = web.page_luogo("Malcesine")
D = web.page_diagnostics()

# --------------------------------------------------------------------------
# 1. Una pagina per localita'
# --------------------------------------------------------------------------
# La richiesta di Gian era esplicita sul PERCHE': "cosi' se volessimo
# aumentare il numero di localita' sarebbe piu' facile". Quindi il controllo
# non e' "ci sono due pagine": e' che pagina, navigazione e nome del file
# vengano tutti da config.PLACES, cosi' che una localita' in piu' non possa
# comparire in un posto e mancare nell'altro.
for place in config.PLACES:
    pagina = web.page_luogo(place)
    ok('aria-current="page">%s<' % place in pagina,
       "%s: la sua linguetta e' quella attiva" % place)
    altre = [p for p in config.PLACES if p != place]
    ok(all(a in pagina for a in altre),
       "%s: e le altre localita' sono raggiungibili" % place)
    ok(pagina.count('class="rq ') == 2 * web.MAX_GIORNI,
       "%s: due riquadri per ognuno dei cinque giorni (%d)"
       % (place, pagina.count('class="rq ')))
ok(web._slug(config.PLACES[0]) == "index",
   "la prima localita' e' la pagina d'ingresso")
ok(web._slug("Malcesine") == "malcesine",
   "e le altre portano il proprio nome (%s)" % web._slug("Malcesine"))
# Nessun nome di localita' scritto a mano nel corpo della pagina: se ce ne
# fosse uno, aggiungerne una terza lo lascerebbe indietro.
ok(H.count(">Torbole</a>") == 1 and H.count(">Malcesine</a>") == 1,
   "ogni localita' compare una volta sola in navigazione")

# --------------------------------------------------------------------------
# 2. Quanti giorni, e con che nome
# --------------------------------------------------------------------------
ok(H.count('class="gcard') == 5,
   "cinque giorni, non otto (%d)" % H.count('class="gcard'))
ok("Tra 6 giorni" not in H and "Tra 7 giorni" not in H,
   "nessun giorno oltre il quinto")
# Gian: "vorrei che le previsioni dei giorni futuri avessero semplicemente la
# data, non domani dopodomani etc". "Domani" e "Dopodomani" non sono solo
# ridondanti: a due giorni di distanza costringono a fare il conto per sapere
# se e' il sabato in cui si e' liberi.
ok("Domani" not in H and "Dopodomani" not in H and "Tra 3 giorni" not in H,
   "via 'domani', 'dopodomani' e 'tra N giorni'")
date = re.findall(r'<span class="gd">(\d\d/\d\d)</span>', H)
ok(len(date) == 5, "ogni giorno porta la sua data (%s)" % date)
ok(H.count('<span class="gg">oggi</span>') == 1,
   "e uno solo dice 'oggi', che e' l'unico ancoraggio che serve")
ok(H.count("hidden") >= 4, "solo il giorno scelto e' visibile")

# --------------------------------------------------------------------------
# 3. I due riquadri sono IDENTICI per costruzione
# --------------------------------------------------------------------------
# "riquadri ora e peler della stessa dimensione (sono importanti uguali)".
# Della stessa dimensione non si controlla su uno screenshot: si controlla che
# vengano dalla stessa funzione e dicano le stesse voci. Se un domani uno dei
# due prendesse una voce in piu', tornerebbero a essere due schede diverse -
# ed e' esattamente come erano prima, con quattro numeri per il Peler e due
# per l'Ora.
sezione = H[H.index('class="rqgrid"'):H.index('class="meglio')]
riquadri = [("<div class=\"rq " + p) for p in sezione.split('<div class="rq ')[1:]]
ok(len(riquadri) == 2, "due riquadri nella sezione del giorno (%d)"
   % len(riquadri))
# Le voci si confrontano con i NUMERI normalizzati: "sopra 10 kn" e "sopra
# 11 kn" sono la stessa voce, perche' la soglia del regime entrato e' diversa
# fra Peler e Ora ed e' giusto che lo sia. Pretendere le stesse parole esatte
# costringerebbe a scrivere la stessa soglia per i due regimi, cioe' a dire
# una cosa falsa per far passare un controllo.
voci = [sorted(re.sub(r"\d+", "N", v)
               for v in re.findall(r"<dt>([^<]+)</dt>", r)) for r in riquadri]
ok(voci[0] and voci[0] == voci[1],
   "le stesse voci in entrambi, a meno delle soglie: %s" % voci[0])
strutture = [re.findall(r'class="(rq-[a-z]+)"', r) for r in riquadri]
ok(strutture[0] == strutture[1],
   "e la stessa struttura di elementi: %s" % strutture[0])
ok('grid-template-columns:1fr 1fr' in H,
   "la griglia dei riquadri e' a due colonne uguali")
ok("PEL" in sezione and "ORA" in sezione, "uno per regime")

# --------------------------------------------------------------------------
# 4. Il voto: intensita' e durata, con le soglie dello spot
# --------------------------------------------------------------------------
spot = config.SPOTS["Torbole-Ora"]
ok(giudizio.voto(spot["min_kn"] - 1, 200, spot)[0] == "pessimo",
   "sotto la soglia del regime il voto e' pessimo, per quanto duri")
ok(giudizio.voto(25.0, None, spot)[0] == "pessimo",
   "e senza la mezz'ora sostenuta il voto e' pessimo, per forte che sia")
ok(giudizio.voto(spot["planing_kn"] + 1, 30, spot)[0] == "mediocre",
   "vento da planata per mezz'ora e' mediocre: e' una sessione che non c'e'")
ok(giudizio.voto(spot["planing_kn"] + 1, 120, spot)[0] == "buono",
   "da planata per due ore e' buono")
ok(giudizio.voto(30.0, 300, spot)[0] == "fantastico",
   "molto sopra la planata per tutto il giorno e' fantastico")
ok(giudizio.voto(30.0, 45, spot)[0] == "mediocre",
   "ma trenta nodi per quarantacinque minuti non sono una giornata")
ok(list(giudizio.VOTI) == ["pessimo", "mediocre", "buono", "fantastico"],
   "quattro voti, in ordine crescente")
ok(len(set(giudizio.CLASSE.values())) == 4,
   "e un colore distinto per ciascuno, con la parola sempre scritta accanto")
for parola in giudizio.VOTI:
    ok(giudizio.CLASSE[parola] in ("no", "meh", "go", "big"),
       "il voto %s ha una classe dichiarata" % parola)

# --------------------------------------------------------------------------
# 5. L'affidabilita': una percentuale, ma solo dove c'e' una misura
# --------------------------------------------------------------------------
# Questa regola e' l'opposto di quella di prima, e il motivo va scritto.
# Prima la pagina NON scriveva percentuali di affidabilita', e aveva ragione:
# quello che misuravamo era se il modello batte i riferimenti banali, non una
# probabilita', e un numero col segno di percento sarebbe stato letto come la
# seconda cosa. Adesso la percentuale c'e' perche' la domanda e' cambiata: non
# "quanto e' giusta la previsione" - che non e' nemmeno una domanda ben posta -
# ma "qual e' la probabilita' che il verdetto si-naviga/non-si-naviga sia
# quello giusto". Quella ha una risposta esatta, max(p, 1-p), e p e' la
# probabilita' del regime, che e' addestrata e verificata.
val_misurata = fiducia(2, cal=0.04)
ok(giudizio.affidabilita(0.90, val_misurata) == 86,
   "p=0,90 con 4 punti di errore di calibrazione da' 86%% (%s)"
   % giudizio.affidabilita(0.90, val_misurata))
ok(giudizio.affidabilita(0.10, val_misurata) == 86,
   "e p=0,10 da' lo stesso: dire 'non si naviga' e azzeccarlo e' un merito")
ok(giudizio.affidabilita(0.50, val_misurata) == 50,
   "una giornata in bilico da' il 50%%: e' la verita', e la pagina la dice")
ok(giudizio.affidabilita(0.90, fiducia(0)) is None,
   "dove non c'e' verifica non si scrive un numero")
ok(giudizio.affidabilita(None, val_misurata) is None,
   "e senza probabilita' del regime nemmeno")
alta = giudizio.affidabilita(0.99, fiducia(3, cal=0.0))
ok(alta is not None and alta <= 99,
   "il 100%% non si scrive mai (%s)" % alta)
ok("non misurata" in giudizio.affidabilita_parole(None, fiducia(0)),
   "e la spiegazione dice che non e' misurata, col motivo")
ok("verdetto" in giudizio.affidabilita_parole(80, val_misurata),
   "mentre dove c'e' dice di cosa e' la probabilita'")
# Dal mockup: la percentuale sta dentro un anello, con la parola sotto.
ok(re.search(r'aria-label="Affidabilità \d+%"', H) is not None
   and re.search(r'fill="var\(--ink\)">\d+%</text>', H) is not None,
   "in pagina la percentuale compare come tale, dentro l'anello")
ok('aria-label="Affidabilità non verificata"' in M
   and 'fill="var(--ink)">—</text>' in M,
   "e a Malcesine, dove la verifica non c'e', c'e' un trattino, non uno zero")

# --------------------------------------------------------------------------
# 6. Quando e' meglio, mattina o pomeriggio
# --------------------------------------------------------------------------
# "mi piace che si scriva quando è più valido tra mattina e pomeriggio".
riga = re.search(r'<p class="meglio[^"]*">(.*?)</p>', H, re.S)
ok(riga is not None, "la riga del meglio c'e'")
ok(riga and ("mattina" in riga.group(1) or "pomeriggio" in riga.group(1)
             or "equivalgono" in riga.group(1)
             or "Niente da fare" in riga.group(1)),
   "e dice quale delle due meta' della giornata: %s"
   % (riga.group(1)[:70] if riga else ""))
# Non puo' contraddire i riquadri: se dice "meglio il pomeriggio", il voto
# del pomeriggio deve essere quello piu' alto. E' la ragione per cui confronta
# i VOTI e non un punteggio continuo suo.
voti_pagina = re.findall(r'<div class="rq-v">([a-zA-Z]+)</div>', sezione)
if riga and "pomeriggio" in riga.group(1) and len(voti_pagina) == 2:
    ok(giudizio.VOTI.index(voti_pagina[1].lower())
       >= giudizio.VOTI.index(voti_pagina[0].lower()),
       "e il voto del pomeriggio non e' piu' basso di quello della mattina"
       " (%s)" % voti_pagina)

# --------------------------------------------------------------------------
# 7. Le scritte: via tutte, tranne quelle che reggono la fiducia
# --------------------------------------------------------------------------
# "vorrei che eliminassimo tutte le scritte inutili, sono troppe, lo voglio
# piu' essenziale." Le spiegazioni non sono state cancellate: stanno dietro
# una riga sola. Chi non tocca non legge niente.
ok(H.count('<details class="dettagli">') == 1, "un solo cassetto dei dettagli")
testa = H[:H.index('<details class="dettagli">')]
ok("Da dove arriva la previsione" not in testa,
   "il pannello delle fonti non e' nella parte aperta della pagina")
ok("Da dove arriva la previsione" in D, "vive in diagnostica")
ok("MAE fuori campione" not in H, "nessun MAE nella pagina")
ok("MAE fuori campione" in D, "il MAE resta in diagnostica")
ok("pesi verificato" not in H and "modelli disponibili a questa scadenza" not in H,
   "via la riga tecnica sulle fonti dell'ensemble")
ok(not re.search(r"Timing:.{0,40}±", H),
   "nessun '±NN min' come intervallo utente")
ok("83 min" not in H, "l'errore medio del picco non compare in pagina")
ok("Orario <b>incerto</b>" not in H,
   "via il messaggio 'orario incerto', che era costante e quindi muto")
ok("Ingresso più probabile" not in H,
   "e via l'ora di ingresso, che quella porta non l'ha mai aperta")
cassetto = H[H.index('<details class="dettagli">'):]
for atteso in ("Il voto", "affidabilit", "mattina", "dove arrivano i numeri"):
    ok(atteso.lower() in cassetto.lower(),
       "ma nel cassetto c'e' la spiegazione di '%s'" % atteso)
ok("diagnostica" in cassetto, "e il rimando a dove si misura l'errore")

# --------------------------------------------------------------------------
# 8. Il grafico e' l'elemento grosso, e viene dopo il verdetto
# --------------------------------------------------------------------------
# "vorrei grafici predominanti". Grande si', ma non prima del verdetto: chi
# guarda sta in piedi col telefono in mano e prima vuole sapere se si va.
i_rq = H.index('class="rqgrid"')
i_chart = H.index('<svg class="chart"')
ok(i_rq < i_chart, "prima il verdetto, poi il grafico")
ok(H.count('<svg class="chart"') == 5,
   "un grafico per giorno, di questa localita' sola (%d)"
   % H.count('<svg class="chart"'))
ok('class="grafico"' in H, "il grafico ha un riquadro suo")
# Le scritte dentro il disegno scalano col viewBox: un viewBox solo non puo'
# servire telefono e desktop, quindi la loro dimensione vive nel CSS e cambia
# con la larghezza. Senza questo, su desktop le etichette del grafico
# diventavano dei titoli.
ok("@media (min-width:760px){svg.chart{--fs-" in H,
   "e le scritte del grafico cambiano misura con lo schermo")
ok(not re.search(r'<text[^>]*font-size="', H),
   "nessun font-size scritto a mano dentro il disegno")

# --------------------------------------------------------------------------
# 9. Il dato misurato, per ENTRAMBE le localita'
# --------------------------------------------------------------------------
# "vorrei raffiche in tempo reale anche per malcesine". La centralina della
# Fraglia Vela era letta e salvata da sempre: non compariva perche' la vecchia
# pagina teneva un solo riquadro "adesso" per tutte le localita'.
for pagina, nome, vento in ((H, "Torbole", "14"), (M, "Malcesine", "8")):
    ok(pagina.count('class="nowblock"') == 1,
       "%s: un blocco del dato osservato" % nome)
    ok('data-live-place="%s"' % nome in pagina,
       "%s: intestato alla sua localita', cosi' il browser lo aggiorna" % nome)
    ok(re.search(r'<span class="k">Vento ora</span>'
                 r'<span class="v">%s <small>kn</small>' % vento, pagina)
       is not None, "%s: col suo vento misurato" % nome)
    ok(re.search(r'<span class="k">Raffica</span><span class="v">\d+ <small>kn',
                 pagina) is not None, "%s: e la sua raffica" % nome)
    ok("ultimo dato" in pagina, "%s: con l'orario del campione" % nome)
ok("11:42" in H or "09:42" in H,
   "l'ora e' quella vera del campione, convertita in locale")

# --------------------------------------------------------------------------
# 10. Oggi il dato misurato prevale sul giudizio emesso stanotte
# --------------------------------------------------------------------------
# Non e' un nowcast: non sposta la curva futura, che e' il banco chiuso.
# Serve a non dire "mediocre" mentre l'anemometro misura diciassette nodi.
live_ora = {"wind": 17.0, "gust": 22.0,
            "dir": config.SPOTS["Torbole-Ora"]["axis_obs"],
            "ts": GIORNI[0]["day"] + "T13:00:00Z", "age_min": 5.0,
            "stale": False}
st = web.live_regime_state(live_ora, config.SPOTS["Torbole-Ora"], today=True)
ok(st and st["cls"] == "go", "17 kn di Ora osservata sono un regime buono")
num = web.sessione_numeri("Torbole-Ora", profilo(8.0), GIORNI[0]["day"],
                          live_ora, today=True)
ok(num and num["kn"] >= 17.0,
   "e il riquadro di oggi non scende sotto il misurato (%.0f kn)"
   % (num["kn"] if num else -1))
ok(web.live_regime_state(live_ora, config.SPOTS["Torbole-Ora"],
                         today=False) is None,
   "ma un giorno futuro non lo tocca: la previsione resta quella")
vecchio = dict(live_ora, age_min=90.0)
ok(web.live_regime_state(vecchio, config.SPOTS["Torbole-Ora"],
                         today=True) is None,
   "un campione stantio non decide niente")
da_nord = dict(live_ora,
               dir=(config.SPOTS["Torbole-Ora"]["axis_obs"] + 180.0) % 360)
ok(web.live_regime_state(da_nord, config.SPOTS["Torbole-Ora"],
                         today=True) is None,
   "e fuori dal settore non e' quel regime, per forte che sia")
presto = dict(live_ora, ts=GIORNI[0]["day"] + "T04:00:00Z")
ok(web.live_regime_state(presto, config.SPOTS["Torbole-Ora"],
                         today=True) is None,
   "e fuori dall'orario del regime non e' quel regime")

# --------------------------------------------------------------------------
# 11. Il riquadro parla di UNA finestra sola
# --------------------------------------------------------------------------
# Il caso che questo controllo difende e' reale ed era il primo difetto della
# scheda: il picco della sessione e' quello della finestra del REGIME, che al
# Peler comincia alle 04:00. Con un Peler forte alle cinque del mattino e
# debole dalle sette in poi, la scheda scriveva "10-14 kn" accanto a
# "sopra 10 kn: -" nello stesso riquadro.
def _profilo(valori):
    return [{"hour": h, "wind": w, "gust": w * 1.4, "lo": w - 1.0,
             "hi": w + 1.0} for h, w in sorted(valori.items())]


_sess = {"Torbole-Peler": dict(GIORNI[0]["sessions"]["Torbole-Peler"],
                               speed=14.0, lo=12.0, hi=16.0, prob=0.8)}
_oggi = GIORNI[0]["day"]
buio = web.card_regime("Torbole", "PELER", "Pelèr", "mattina",
                       _profilo({4: 15.0, 5: 15.0, 6: 9.0, 7: 6.0, 8: 6.0,
                                 9: 6.0, 10: 6.0, 11: 5.0}), _sess, _oggi)
ok("q-no" in buio or "q-meh" in buio,
   "vento forte solo prima dell'alba: il riquadro non dice buono")
ok("15" not in buio.split('class="rq-kn"')[1][:40],
   "e l'intensita' non e' quella dei quindici nodi al buio: %s"
   % buio.split('class="rq-kn"')[1][:40])
ok("<dd>—</dd>" in buio,
   "e sopra la soglia non c'e' niente, perche' dentro la finestra non arriva")
pieno = web.card_regime("Torbole", "PELER", "Pelèr", "mattina",
                        _profilo({h: 14.0 for h in range(4, 13)}), _sess, _oggi)
ok("q-go" in pieno or "q-big" in pieno,
   "vento forte per tutta la finestra: buono")
ok("&ge;" in pieno,
   "e la durata e' marcata come limite, perche' tocca i bordi della finestra")
inverno = web.card_regime("Torbole", "PELER", "Pelèr", "mattina",
                          _profilo({h: 12.0 for h in range(4, 13)}), _sess,
                          "2026-12-21")
ok("<dd>08:" in inverno,
   "al solstizio d'inverno la finestra utile comincia dopo le otto")
estate = web.card_regime("Torbole", "PELER", "Pelèr", "mattina",
                         _profilo({h: 12.0 for h in range(4, 13)}), _sess,
                         "2026-06-21")
ok("<dd>06:00" in estate,
   "e al solstizio d'estate dall'ora pratica, le sei")

# --------------------------------------------------------------------------
# 12. Raffica, tema, e il resto che non e' cambiato
# --------------------------------------------------------------------------
ok("raffica" in H, "la parola raffica e' scritta per esteso")
ok(not re.search(r"\braff\b", H), "mai abbreviata in 'raff'")
ok(H.count("stroke-dasharray") >= 5,
   "curva della raffica tratteggiata in ogni grafico")
ok("prefers-color-scheme" not in H, "nessun secondo tema mezzo curato")
ok('content="dark"' in H, "il tema scuro e' dichiarato al browser")
# Il colore della localita' si sceglie una volta, sul corpo: con una pagina
# per localita' non ha senso ripeterlo su ogni sezione.
ok('<body class="p1">' in H and '<body class="p2">' in M,
   "ogni pagina porta il colore della sua localita'")

# --------------------------------------------------------------------------
# 13. La riga del MISURATO si disegna coi campioni, non con le medie orarie
# --------------------------------------------------------------------------
# Domanda di Gian, guardando la pagina di una centralina: "loro hanno una
# precisione live pazzesca, com'e' possibile che non la consideriamo". Le
# misure le usiamo per tutto - il modello e' addestrato su 123.661 ore - ma le
# DISEGNAVAMO per ore, e la media oraria nasconde proprio cio' che la misura
# serve a mostrare: misurato su 2.769 inversioni di regime, il fondo del buco
# fra Peler e Ora sta al 25% del livello coi campioni e al 40% con le medie.
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
for h in range(4, 21):
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
pl = {k: dict(v) for k, v in GIORNI[0]["places"].items()}
pl["Torbole"] = dict(pl["Torbole"], osservato=OSS)
GG_OSS = [dict(GIORNI[0], places=pl, lead=0)]
_vecchio_by_day = engine.by_day
engine.by_day = lambda product=None: GG_OSS
try:
    H_OSS = web.page_luogo("Torbole")
finally:
    engine.by_day = _vecchio_by_day

# La curva del misurato e' un percorso cubico monotono: i vertici veri sono i
# punti di arrivo dei segmenti C, che per costruzione sono i dati. Si contano
# quelli, non i punti di controllo.
misurate = re.findall(r'<path d="([^"]+)" fill="none" '
                      r'stroke="var\(--pc\)" stroke-width="%g"'
                      % web.TRATTO["misurato"], H_OSS)


def vertici(d):
    fuori = []
    for pezzo in d.replace("M", " ").replace("L", " ").split("C"):
        coppie = pezzo.split()
        if coppie:
            fuori.append(tuple(float(v) for v in coppie[-1].split(",")))
    return fuori


ok(misurate and max(len(vertici(d)) for d in misurate) > 60,
   "la riga del misurato ha i vertici dei campioni, non diciotto (%s)"
   % [len(vertici(d)) for d in misurate][:3])
ys = [v[1] for d in misurate for v in vertici(d)]
ok(ys and max(ys) - min(ys) > 40,
   "e un crollo a 1 kn si vede come tale, non appiattito (escursione %.0f"
   " punti di disegno)" % (max(ys) - min(ys) if ys else 0))
_sc = web.scarto_line(profilo(20.0), OSS)
ok(_sc is not None and float(_sc["hour"]) == int(_sc["hour"]),
   "la riga dello scarto continua a confrontare su un'ora intera (%s)"
   % (_sc and _sc["hour"]))

# --------------------------------------------------------------------------
# 12. L'aspetto del mockup (2026-09-18): "Time to Foil"
# --------------------------------------------------------------------------
# Gian ha mandato un'immagine di come vuole la pagina. Qui non si controlla
# l'estetica - quella si guarda - ma le cose che il mockup dice e che il
# codice deve fare, e i due difetti trovati guardando la prima resa.
ok(config.APP_NAME == "Time to Foil",
   "il nome e' quello scelto sul mockup")
ok("<h1 class=\"titolo\">Time to <em>Foil</em></h1>" in H,
   "e in testa e' scritto con l'ultima parola nel colore d'accento")
ok('<p class="tag">%s</p>' % web.E(config.APP_TAGLINE) in H,
   "con la riga sotto, che viene da config e non e' riscritta qui")
ok(web.titolo_html("Solo") == "Solo",
   "un nome di una parola sola non si spezza")
ok('<header class="hero' in H and ('class="cielo"' in H or 'hero foto' in H),
   "la testa porta il cielo: disegnato, o la foto se c'e'")
# Il primo difetto: le pillole verdi e azzurre venivano vuote, perche' .q-go
# da solo colora il testo di verde e vinceva sulla regola della pillola.
css = web.CSS
ok(".q-go.gv,.q-go.pill{background:var(--good);color:" in css
   and ".q-big.gv,.q-big.pill{background:var(--big);color:" in css,
   "le pillole del voto dichiarano il colore del testo nella regola a due classi")
ok(re.search(r'<span class="gv q-\w+">\w+</span>', H) is not None,
   "e nei giorni la parola del voto c'e' dentro la pillola")
ok(re.search(r'<span class="pill q-\w+">\w+</span>', H) is not None,
   "come nel riquadro del regime")
# Il secondo difetto: etichetta e numero della cella dell'adesso sulla
# stessa riga. Il contenitore deve essere una griglia.
ok(".cella>span:not(.ic){display:grid" in css,
   "nelle celle dell'adesso l'etichetta sta sopra il numero")
ok(H.count('<div class="cella') == 5,
   "cinque celle nell'adesso: vento, direzione, raffica, orario, cielo (%d)"
   % H.count('<div class="cella'))
ok(H.count('<div class="anello">') == H.count('class="rq '),
   "ogni riquadro porta l'anello dell'affidabilita' (%d su %d)"
   % (H.count('<div class="anello">'), H.count('class="rq ')))
# I motori stanno nei riquadri, quando la sessione li ha: qui la sessione di
# prova non li porta, quindi si costruisce un riquadro con i motori a mano.
_prof = [{"hour": h, "wind": 14.0 if 13 <= h <= 17 else 6.0,
          "gust": 21.0 if 13 <= h <= 17 else 9.0, "dir": 190}
         for h in range(4, 21)]
_card = web.card_regime("Torbole", "ORA", "Ora", "pomeriggio", _prof,
                        {"Torbole-Ora": {"prob": 0.7, "affidabilita": None,
                                         "features": {"pgrad": 0.7, "tgrad": 3.0}}},
                        "2026-07-10")
ok("Contrasto termico</dt><dd>+3.0 \u00b0C" in _card
   and "\u0394P nord \u2013 sud</dt><dd>+0.7 hPa" in _card,
   "e i due motori, con l'icona, quando la sessione li ha")
ok('<p class="motori">' not in H,
   "e la vecchia riga dei motori sotto i riquadri non c'e' piu'")
ok(H.index('<div class="gtesta"><h2>Vento previsto e misurato</h2>')
   < H.index('<svg class="chart"'),
   "titolo e legenda del grafico stanno SOPRA il disegno")
ok('<summary>Dettagli</summary>' in H, "il cassetto si chiama Dettagli")

print("%d controlli di pagina" % passati)
