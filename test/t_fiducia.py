"""Affidabilita': etichetta derivata dalle misure, non dall'orizzonte.

La proprieta' da difendere e' una sola, ed e' la ragione per cui questo modulo
esiste: a parita' di scadenza, due spot con skill diversa devono ricevere due
etichette diverse. Se il test passasse anche legando l'etichetta al numero di
giorni, non servirebbe a niente.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from gardawind import confidence as C, config, web
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)


def metriche(n=300, mae=1.2, mae_raw=4.0, brier=0.12, brier_base=0.25,
             cal=0.03, timing=22.0, sig_int=True, sig_prob=True):
    return {
        "lead": 2, "n_test_days": n,
        "intensity": {"mae": mae, "mae_raw": mae_raw, "mae_clim": mae_raw,
                      "bias": 0.0, "n": n},
        "prob": {"brier": brier, "brier_base": brier_base,
                 "calibration_error": cal, "base_rate": 0.4, "n": n},
        "timing": {"mae_min": timing, "bias_min": 2.0, "p30": 0.7, "n": n},
        "gain_int": {"punto": 70.0, "ic_lo": 60.0, "ic_hi": 78.0,
                     "significativo": sig_int},
        "gain_prob": {"punto": 52.0, "ic_lo": 40.0, "ic_hi": 60.0,
                      "significativo": sig_prob},
    }


# --------------------------------------------------------------------------
# 1. Le etichette di scadenza sono in italiano, senza sigle
# --------------------------------------------------------------------------
etichette = [C.lead_label(l) for l in range(0, 8)]
print("   " + " | ".join(etichette))
ok(etichette[0] == "Oggi" and etichette[1] == "Domani"
   and etichette[2] == "Dopodomani" and etichette[3] == "Tra 3 giorni"
   and etichette[7] == "Tra 7 giorni", "scadenze in parole: %s" % etichette[3])
import re
sigle = [e for e in etichette if re.match(r"^D\s*\+?\s*\d", e)]
ok(not sigle, "nessuna sigla D1/D2/D3 raggiunge l'interfaccia")

# --------------------------------------------------------------------------
# 2. LA PROPRIETA' CENTRALE: stessa scadenza, skill diversa, etichetta diversa
# --------------------------------------------------------------------------
buono = C.assess("Torbole-Peler", 2, metriche())
scarso = C.assess("Malcesine-Ora", 2, metriche(
    n=80, mae=3.4, mae_raw=3.6, brier=0.245, brier_base=0.25, cal=0.13,
    timing=150.0, sig_int=False, sig_prob=False))
print("   D+2 Torbole-Pelèr  -> %s" % buono["etichetta"])
print("   D+2 Malcesine-Ora  -> %s  (%s)" % (scarso["etichetta"], scarso["motivo"]))
ok(buono["livello"] > scarso["livello"],
   "a D+2 il Pelèr di Torbole batte l'Ora di Malcesine: %s contro %s"
   % (buono["etichetta"], scarso["etichetta"]))
ok(buono["scadenza"] == scarso["scadenza"] == "Dopodomani",
   "eppure la scadenza mostrata e' la stessa per entrambi")
ok(scarso["motivo"], "e per quello basso c'e' scritto il perche': %s" % scarso["motivo"])

# Lo stesso spot a scadenza lontana ma ben misurata NON deve essere penalizzato
# solo per la distanza.
lontano_buono = C.assess("Torbole-Peler", 6, metriche())
ok(lontano_buono["livello"] == buono["livello"],
   "a D+6 con le stesse misure l'etichetta resta %s: la distanza da sola non "
   "declassa" % lontano_buono["etichetta"])
ok(lontano_buono["scadenza"] == "Tra 6 giorni", "ma la scadenza e' dichiarata")

# --------------------------------------------------------------------------
# 3. Senza misure a quella scadenza -> outlook, e lo dice
# --------------------------------------------------------------------------
niente = C.assess("Torbole-Ora", 4, None)
ok(niente["livello"] == C.OUTLOOK and niente["misurato"] is False,
   "nessuna misura a D+4 -> outlook (%s)" % niente["motivo"])
poche = C.assess("Torbole-Ora", 4, metriche(n=12))
ok(poche["livello"] == C.OUTLOOK, "dodici giornate di verifica non bastano: outlook")

# --------------------------------------------------------------------------
# 4. Ogni componente, da sola, sa far scendere l'etichetta
# --------------------------------------------------------------------------
base = C.assess("Torbole-Peler", 1, metriche())
ok(base["livello"] == C.ALTA, "caso pieno -> alta affidabilita'")

casi = [
    ("pochi giorni di verifica", metriche(n=70), {}),
    ("guadagno non significativo", metriche(sig_int=False), {}),
    ("probabilita' mal calibrata", metriche(cal=0.09), {}),
    ("errore di intensita' oltre il margine", metriche(mae=6.0), {}),
]
for nome, m, kw in casi:
    v = C.assess("Torbole-Peler", 1, m, **kw)
    ok(v["livello"] < C.ALTA and v["motivo"],
       "%s -> scende a %s, col motivo scritto: %s" % (nome, v["etichetta"], v["motivo"]))

v = C.assess("Torbole-Peler", 1, metriche(), spread_kn=9.0)
ok(v["livello"] < C.ALTA, "modelli in disaccordo (±9 kn) -> scende a %s" % v["etichetta"])
v = C.assess("Torbole-Peler", 1, metriche(), dir_penalty=0.2, dir_offset=95.0)
ok(v["livello"] <= C.TENDENZA,
   "direzione fuori settore -> al massimo tendenza (%s)" % v["motivo"])
v = C.assess("Torbole-Peler", 1, metriche(), ambiguo=True)
ok(v["livello"] < C.ALTA, "regime ambiguo -> un gradino in meno (%s)" % v["etichetta"])

# Le retrocessioni di giornata non possono essere compensate da una statistica
# storica eccellente: sono condizioni di oggi.
v = C.assess("Torbole-Peler", 1, metriche(mae=0.4, cal=0.005, timing=8.0),
             dir_penalty=0.1, dir_offset=110.0)
ok(v["livello"] <= C.TENDENZA,
   "nemmeno metriche perfette salvano una direzione sbagliata (%s)" % v["etichetta"])

# --------------------------------------------------------------------------
# 5. Il giorno prende il livello piu' basso fra le sue sessioni
# --------------------------------------------------------------------------
s = C.sintesi_giorno([buono, scarso])
ok(s["livello"] == scarso["livello"],
   "l'intestazione del giorno non promette piu' della riga piu' debole (%s)"
   % s["etichetta"])
ok(C.sintesi_giorno([]) is None, "nessuna sessione -> nessuna etichetta")

# --------------------------------------------------------------------------
# 6. Resa in pagina
# --------------------------------------------------------------------------
h = web.confidence_badge(buono)
ok("cf-" in h and buono["etichetta"].capitalize()[:5] in h,
   "il distintivo porta il colore E la parola scritta")
ok(web.confidence_badge(None) == "", "senza valutazione non si inventa un distintivo")
hc = web.confidence_badge(scarso, compact=True)
ok("title=" in hc and "cf-" in hc, "la versione compatta tiene il motivo nel titolo")
ok(web.hhmm(487.4) == "08:10" and web.hhmm(620.0) == "10:20",
   "orari arrotondati a dieci minuti: %s-%s" % (web.hhmm(487.4), web.hhmm(620.0)))
ok(web.hhmm(487.0) == "08:10" and web.hhmm(484.0) == "08:00",
   "l'arrotondamento non finge la precisione al minuto")

# L'orario NON declassa l'etichetta: e' una domanda diversa, con una riga sua.
v = C.assess("Torbole-Peler", 1, metriche(timing=95.0))
ok(v["livello"] == C.ALTA,
   "un orario incerto non declassa l'etichetta: resta %s" % v["etichetta"])
# La seconda voce ha una scala propria: tre livelli piu' "non misurato".
tv = [C.timing_voice(metriche(timing=t)) for t in (18, 45, 95)]
print("   voci sull'orario: " + " | ".join(v["testo"] for v in tv))
ok([v["livello"] for v in tv] == [3, 2, 1],
   "l'orario ha la sua scala: %s" % ", ".join(v["etichetta"] for v in tv))
ok(C.orario_affidabile(metriche(timing=95.0)) is False
   and "bassa precisione" in C.nota_orario(metriche(timing=95.0)),
   "a 95 minuti: \"%s\"" % C.nota_orario(metriche(timing=95.0)))
ok(C.orario_affidabile(metriche(timing=30.0)) is True
   and "±30" in C.nota_orario(metriche(timing=30.0)),
   "a 30 minuti si scrive il numero: \"%s\"" % C.nota_orario(metriche(timing=30.0)))
ok(C.timing_voice(None)["livello"] == 0 and "non misurato" in C.nota_orario(None),
   "senza misura lo dice invece di tacere")
# Le due voci sono davvero indipendenti: stessa scheda, giudizi diversi.
alta_ma_lenta = C.assess("Torbole-Peler", 1, metriche(timing=95.0))
ok(alta_ma_lenta["etichetta"] == "alta affidabilità"
   and C.timing_voice(metriche(timing=95.0))["etichetta"] == "bassa precisione",
   "una scheda puo' dire \"alta affidabilità\" E \"bassa precisione\" sull'orario: "
   "sono due domande")
b = web.timing_badge(C.timing_voice(metriche(timing=95.0)))
ok("tm-1" in b and "bassa precisione" in b and "95" in b,
   "e la seconda voce arriva in pagina con il suo livello e i suoi minuti")

nota = C.nota_tecnica(buono)
print("   nota tecnica: " + nota)
ok("giornate" in nota and "MAE" in nota,
   "la parte tecnica resta disponibile per la diagnostica")

# --------------------------------------------------------------------------
# 7. Le quattro etichette sono quelle concordate
# --------------------------------------------------------------------------
ok(set(C.ETICHETTE.values()) == {"alta affidabilità", "buona affidabilità",
                                 "tendenza", "outlook"},
   "le quattro etichette: %s" % ", ".join(C.ETICHETTE[k] for k in (3, 2, 1, 0)))
ok(all(C.USO[k] for k in C.ETICHETTE),
   "ognuna dice a cosa serve, non quanto e' bravo il modello")
