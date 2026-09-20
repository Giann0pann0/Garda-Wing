"""Le ragioni di una giornata: quello che il sito dice di sapere.

Un cassetto "Perche'?" e' la cosa piu' facile da riempire di parole vere che
non significano niente. Questi controlli difendono le due regole che lo
distinguono da una decorazione: che ogni riga esca da un numero che abbiamo
DAVVERO, e che dove non lo abbiamo la riga non ci sia - invece di diventare
"neutro", che chi conosce il lago legge come "non ne capisce niente".
"""
import os
import re
import sys

QUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(QUI, ".."))
os.environ["GARDAWIND_HOME"] = "/tmp/gwperche"

from gardawind import config, perche, web  # noqa: E402

passati = 0


def ok(c, m):
    global passati
    if c:
        passati += 1
        print("PASS " + m)
    else:
        print("FAIL " + m)


def testo(voci):
    return " | ".join(t for _s, t in voci)


PELER = "Torbole-Peler"
ORA = "Torbole-Ora"

# ---- 1. il verso del gradiente dipende dal REGIME, non dal segno -----------
# +2 hPa (pressione piu' alta a nord) spinge verso sud: favorisce il Peler e
# contrasta l'Ora. La stessa giornata, due ragioni opposte.
nord = {"features": {"pgrad": 2.0, "contesto_noto": 1.0}, "speed": 15.0}
rp = perche.ragioni(PELER, nord)
ro = perche.ragioni(ORA, nord)
ok(rp and rp[0][0] == "+" and "spinge il Pelèr" in rp[0][1],
   "con +2 hPa il Pelèr ha una ragione a favore: \"%s\"" % rp[0][1])
ok(ro and ro[0][0] == "-",
   "e l'Ora, lo stesso numero, come ragione CONTRO (%s)" % ro[0][0])
sud = {"features": {"pgrad": -2.0, "contesto_noto": 1.0}, "speed": 15.0}
ok(perche.ragioni(ORA, sud)[0][0] == "+"
   and perche.ragioni(PELER, sud)[0][0] == "-",
   "e con il gradiente rovesciato si scambiano, come la fisica del lago")

# ---- 2. quello che non sappiamo non si scrive ------------------------------
ignoto = {"features": {"pgrad": 0.0, "tgrad": 0.0, "contesto_noto": 0.0,
                       "w10_win": 11.0}, "speed": 12.0}
v = perche.ragioni(ORA, ignoto)
ok("gradiente" not in testo(v) and "contrasto termico" not in testo(v),
   "senza contesto sinottico quelle due righe MANCANO, non diventano \"neutro\"")
ok("i modelli, da soli" in testo(v),
   "ma quello che sappiamo si dice comunque: \"%s\"" % testo(v))

# ---- 3. il vento in quota: lungo l'asse o contro --------------------------
lungo = {"features": {"along925": 6.0}, "speed": 15.0}
contro = {"features": {"along925": -6.0}, "speed": 15.0}
ok(perche.ragioni(ORA, lungo)[0][0] == "+" and "lungo l" in perche.ragioni(ORA, lungo)[0][1],
   "a 925 hPa lungo l'asse e' una ragione a favore")
ok(perche.ragioni(ORA, contro)[0][0] == "-" and "contro l" in perche.ragioni(ORA, contro)[0][1],
   "e contro l'asse e' una ragione contraria")
debole = {"features": {"along925": 0.4}, "speed": 15.0}
ok("925" not in testo(perche.ragioni(ORA, debole)),
   "mezzo nodo di componente non e' una ragione: non si scrive")

# ---- 4. le soglie non sono nuove: vengono da dove esistono gia' -----------
src = open(os.path.join(QUI, "..", "gardawind", "perche.py"), encoding="utf-8").read()
ok("MAX_SPREAD_KN" in src and "spot[\"min_kn\"]" in src,
   "l'accordo fra i modelli usa la soglia dell'affidabilita' e gli analoghi "
   "quella dello spot: nessun numero nuovo")
ok(not re.search(r"\b(1[0-9]|2[0-9])\.0 kn\b", src),
   "e non c'e' nessuna soglia in nodi scritta a mano nelle frasi")

# ---- 5. la pioggia passa davanti a tutto ---------------------------------
molte = {"features": {"pgrad": 2.0, "tgrad": 6.0, "along925": 5.0,
                      "cloud_cool": 0.1, "contesto_noto": 1.0, "precip": 4.0,
                      "w10_win": 9.0},
         "speed": 18.0, "spread": 1.0, "n_models": 8}
v = perche.ragioni(PELER, molte)
ok(len(v) == perche.MAX_RAGIONI, "al massimo %d ragioni (%d)" % (perche.MAX_RAGIONI, len(v)))
ok("pioggia" in v[0][1],
   "e la pioggia sta in cima: e' l'unica che annulla una giornata")

# ---- 6. una frase sola per il verso del gradiente, non due ---------------
ok("verso_pgrad" in open(os.path.join(QUI, "..", "gardawind", "web.py"),
                         encoding="utf-8").read(),
   "la scheda chiede a perche.verso_pgrad la frase del verso, non se la riscrive")
ok(perche.verso_pgrad(2.0) == "spinge il Pelèr"
   and perche.verso_pgrad(-2.0).endswith("Ora")
   and perche.verso_pgrad(0.0) == "neutro"
   and perche.verso_pgrad(None) is None,
   "e quella frase ha un valore per ogni caso, compreso \"non lo so\"")

# ---- 7. in pagina: un cassetto, e niente cassetto se non c'e' niente -----
h = web.perche_html(PELER, molte, "2026-09-21")
ok("<details" in h and "Perch" in h and h.count("<li") == perche.MAX_RAGIONI,
   "il cassetto in pagina ha le sue righe (%d)" % h.count("<li"))
ok(web.perche_html(PELER, {"features": {}}, "2026-09-21") == "",
   "e una giornata senza nessuna ragione non produce un cassetto vuoto")
ok(web.perche_html(None, None, None) == "",
   "ne' un cassetto senza previsione")
# Le frasi non devono poter iniettare HTML: passano da E()
sporca = {"features": {"w10_win": 9.0}, "speed": 1.0, "cattivo": "<script>"}
ok("<script>" not in web.perche_html(ORA, sporca, "2026-09-21"),
   "e il testo e' sempre passato dall'escape")

# ---- 8. ogni regime ha la sua ragione di stagione ------------------------
notte = {"features": {"cloud_cool": 0.1}, "speed": 15.0}
sole = {"features": {"rad_pre": 0.8}, "speed": 15.0}
ok("raffreddamento" in testo(perche.ragioni(PELER, notte))
   and "raffreddamento" not in testo(perche.ragioni(ORA, notte)),
   "il cielo della notte e' una ragione del Pelèr, non dell'Ora")
ok("sole della mattina" in testo(perche.ragioni(ORA, sole))
   and "sole della mattina" not in testo(perche.ragioni(PELER, sole)),
   "e il sole del mattino una ragione dell'Ora, non del Pelèr")

print("%d controlli sulle ragioni" % passati)
