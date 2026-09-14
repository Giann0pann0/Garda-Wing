"""I casi pre-registrati del LIVELLO MODELLO dell'orario: bias, causalita', leakage.

Risultato atteso scritto prima di eseguire il codice, come per t_orari.py. Qui
non si prova la logica di una giornata (quella e' in t_orari.py): si prova che
il banco di validazione sia onesto, cioe':

  - che misuri un bias che sappiamo di aver messo dentro;
  - che una correzione stimata SUL TRAINING migliori il validation, e che
    stimarla non richieda di guardare il futuro;
  - che la previsione di un giorno non cambi se cambiano i giorni dopo;
  - che un previsore senza nessuna informazione oltre al mese NON batta la
    climatologia mensile fuori campione. Se la battesse, ci sarebbe leakage;
  - e, dall'altro lato, che un previsore davvero informativo LA BATTA: un banco
    che non promuove mai niente non e' prudente, e' rotto.

Tutte le ore sono minuti dalla mezzanotte locale.
"""
import os, random, sys
os.environ["GARDAWIND_HOME"] = "/tmp/gwmodello"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import shutil
shutil.rmtree("/tmp/gwmodello", ignore_errors=True)

from gardawind.orari import (osservazioni, previsore_climatologico,
                             previsore_corretto, valida_ingressi)
from gardawind.util import mean, median

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)

GG_MESE = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def giornate(anni=(2016, 2017, 2018, 2019, 2020, 2021),
             mesi=(5, 6, 7, 8, 9), base=None, rumore=25.0, seed=3,
             stimabili=True):
    """Giornate finte nella forma di giudica_giornata(): solo i campi che servono.

    base(mese) da' l'ora vera del mese; il rumore e' uniforme e simmetrico,
    cosi' che la mediana del mese sia l'ora vera e non un artefatto.
    """
    base = base or (lambda m: 720.0)
    rng = random.Random(seed)
    out = []
    for anno in anni:
        for mese in mesi:
            for giorno in range(1, GG_MESE[mese - 1] + 1):
                vero = base(mese) + rng.uniform(-rumore, rumore)
                out.append({
                    "date": "%04d-%02d-%02d" % (anno, mese, giorno),
                    "estimable": stimabili, "reason": "ok",
                    "regime_onset": vero if stimabili else None,
                    "planing_onset": None,
                    "regime_onset_wind": vero if stimabili else None,
                })
    return out


# --------------------------------------------------------------------------
# 0. Il materiale di base: niente ore inventate
# --------------------------------------------------------------------------
misto = giornate(anni=(2018, 2019))
misto.append({"date": "2019-06-01", "estimable": False,
              "reason": "insufficient_coverage", "regime_onset": None,
              "planing_onset": None, "regime_onset_wind": None})
misto.append({"date": "2019-06-02", "estimable": True, "reason": "no_regime",
              "regime_onset": None, "planing_onset": None,
              "regime_onset_wind": None})
oss = osservazioni(misto)
ok(len(oss) == len(misto) - 2,
   "osservazioni: giornata non stimabile e giornata senza regime restano fuori")
ok(all(o[0] for o in oss) and oss == sorted(oss, key=lambda x: x[0]),
   "osservazioni: in ordine di data, sempre")

# --------------------------------------------------------------------------
# 1. Fold solo in avanti
# --------------------------------------------------------------------------
dati = giornate()
res = valida_ingressi(dati)
tagli = res["fold"]
ok(res["n_fold"] >= 3, "fold: almeno tre blocchi di validazione")
ok(all(a < b for a, b in tagli), "fold: ogni blocco non e' vuoto")
ok(all(tagli[i][1] == tagli[i + 1][0] for i in range(len(tagli) - 1)),
   "fold: blocchi contigui, nessuna giornata predetta due volte")
ok(tagli[0][0] >= 8, "fold: il primo blocco serve solo ad addestrare")

date_test = [r["date"] for r in res["previsori"]["climatologia"]["per_giorno"]]
ok(len(date_test) == len(set(date_test)),
   "fold: nessuna giornata predetta due volte")
ok(min(date_test) > osservazioni(dati)[tagli[0][0] - 1][0],
   "fold: nessuna giornata di test precede la fine del primo training")

# --------------------------------------------------------------------------
# 2. Bias noto: +30 minuti, in un mese solo
# --------------------------------------------------------------------------
# Un previsore che copia la climatologia ma sbaglia di mezz'ora in avanti a
# settembre. Atteso: bias di settembre ~ +30, bias degli altri mesi ~ 0,
# porta C (bias stagionale) NON superata.
clim = previsore_climatologico()


def storto(training, ctx):
    p, prov = clim(training, ctx)
    if p is None:
        return None, prov
    return (p + 30.0, prov) if ctx["mese"] == 9 else (p, prov)


storto.nome = "climatologia, ma a settembre mezz'ora tardi"
corretto = previsore_corretto(storto, nome="lo stesso, bias del mese corretto")

r2 = valida_ingressi(dati, previsori={"storto": storto, "corretto": corretto})
b_set = r2["previsori"]["storto"]["bias_per_mese"][9]["bias"]
b_giu = r2["previsori"]["storto"]["bias_per_mese"][6]["bias"]
ok(b_set is not None and 25.0 <= b_set <= 35.0,
   "bias noto: a settembre si misura +30 (%s)" % round(b_set or -999, 1))
ok(b_giu is not None and abs(b_giu) <= 8.0,
   "bias noto: negli altri mesi resta a zero (giugno %s)" % round(b_giu or -999, 1))

c_set = r2["previsori"]["corretto"]["bias_per_mese"][9]["bias"]
ok(c_set is not None and abs(c_set) <= 10.0,
   "correzione: dopo la correzione settembre torna a zero (%s)" % round(c_set or -999, 1))
ok(r2["previsori"]["corretto"]["mae"] < r2["previsori"]["storto"]["mae"],
   "correzione: il validation migliora (%.1f -> %.1f min)"
   % (r2["previsori"]["storto"]["mae"], r2["previsori"]["corretto"]["mae"]))

# La correzione e' stimata sul training: se la si stimasse sul validation,
# funzionerebbe anche su un bias che nel training non c'e'. Verifichiamolo al
# contrario: un previsore storto SOLO nelle giornate finali (quelle di test)
# non deve essere corretto da una stima fatta sul training.
finali = set(d["date"] for d in res["previsori"]["climatologia"]["per_giorno"])


def storto_solo_dopo(training, ctx):
    # Storto in base alla LUNGHEZZA del training, cioe' solo nei fold finali:
    # un bias che nel training non si e' mai visto.
    p, prov = clim(training, ctx)
    if p is None:
        return None, prov
    return (p + 45.0, prov) if len(training) > 700 else (p, prov)


storto_solo_dopo.nome = "storto solo nei fold finali"
r2b = valida_ingressi(dati, previsori={
    "tardi": storto_solo_dopo,
    "tardi_corretto": previsore_corretto(storto_solo_dopo)})
_rapporto = (r2b["previsori"]["tardi_corretto"]["mae"]
             / r2b["previsori"]["tardi"]["mae"])
ok(0.85 <= _rapporto <= 1.15,
   "correzione: un bias che nel training non c'e' resta li' (MAE x%.2f): la "
   "correzione e' stimata sul training, non sul validation" % _rapporto)

# --------------------------------------------------------------------------
# 3. Causalita': cambiare il futuro non cambia il passato
# --------------------------------------------------------------------------
dati_futuro_storto = [dict(r) for r in dati]
meta = dati_futuro_storto[len(dati_futuro_storto) // 2:]
for r in meta:
    if r["regime_onset"] is not None:
        r["regime_onset"] = r["regime_onset"] + 300.0

r3 = valida_ingressi(dati_futuro_storto,
                     previsori={"climatologia": clim, "corretto": previsore_corretto(clim)})
primo_fold = tagli[0][1]
date_primo = set(o[0] for o in osservazioni(dati)[tagli[0][0]:primo_fold])

for nome in ("climatologia", "corretto"):
    a = {d["date"]: d["previsto"] for d in res["previsori"]["climatologia"]["per_giorno"]
         if d["date"] in date_primo} if nome == "climatologia" else None
    prima = {d["date"]: d["previsto"]
             for d in valida_ingressi(dati, previsori={nome: (
                 clim if nome == "climatologia" else previsore_corretto(clim))}
             )["previsori"][nome]["per_giorno"] if d["date"] in date_primo}
    dopo = {d["date"]: d["previsto"]
            for d in r3["previsori"][nome]["per_giorno"] if d["date"] in date_primo}
    uguali = (prima and set(prima) == set(dopo)
              and all(abs((prima[k] or 0) - (dopo[k] or 0)) < 1e-9 for k in prima))
    ok(uguali, "causalita' (%s): le previsioni del primo fold non cambiano se "
               "si stravolgono le giornate successive" % nome)

# --------------------------------------------------------------------------
# 4. Leakage: senza informazione oltre al mese, non si batte la climatologia
# --------------------------------------------------------------------------
# Dati in cui l'ora dipende SOLO dal mese, piu' rumore. Un previsore
# "sofisticato" che stima una mediana per (mese, giorno della settimana) ha
# sette volte piu' parametri e nessuna informazione in piu'. Atteso: non batte
# la climatologia mensile fuori campione. Se la batte, c'e' leakage.
solo_mese = giornate(base=lambda m: 660.0 + 20.0 * m, rumore=40.0, seed=11)


def _dow(data):
    y, m, d = int(data[:4]), int(data[5:7]), int(data[8:10])
    import datetime
    return datetime.date(y, m, d).weekday()


def sofisticato(training, ctx):
    """Mediana per (mese, giorno della settimana): sette volte i parametri.

    Il giorno della settimana e' una feature vera, nota prima, e il banco la
    passa: e' proprio il caso pericoloso. Informazione sull'ora di ingresso,
    pero', non ne contiene nessuna - e quindi non deve vincere.
    """
    per_gruppo = {}
    for data, mm, obs in training:
        per_gruppo.setdefault((mm, _dow(data)), []).append(obs)
    xs = per_gruppo.get((ctx["mese"], _dow(ctx["date"])), [])
    if len(xs) < 5:
        return clim(training, ctx)
    return median(xs), "mese+dow"


sofisticato.nome = "mediana per mese e giorno della settimana"
r4 = valida_ingressi(solo_mese, previsori={"sofisticato": sofisticato})
g, lo, hi = r4["previsori"]["sofisticato"]["guadagno"]
ok(g is not None, "leakage: il confronto appaiato col riferimento esiste")
ok(not (lo is not None and lo > 0.0),
   "leakage: senza informazione oltre al mese NON batte la climatologia "
   "(guadagno %s%%, IC %s..%s)"
   % (round(g or 0, 1), round(lo or 0, 1), round(hi or 0, 1)))
ok(r4["porte"]["guadagno"]["passa"] is not True,
   "leakage: la porta del guadagno non si apre")
ok(r4["esito"] == "incerto", "leakage: l'esito resta 'incerto'")

# --------------------------------------------------------------------------
# 5. Il banco sa anche dire si': un previsore informativo passa
# --------------------------------------------------------------------------
# Meta' delle giornate sono "di gradiente forte" ed entrano un'ora prima. Il
# mese non lo sa. Il gradiente e' noto all'ora di emissione, quindi il banco lo
# passa nel ctx: un previsore che lo usa DEVE battere la climatologia mensile,
# e le tre porte devono aprirsi. Un banco che non promuove mai niente non e'
# prudente, e' rotto, e questo caso serve a scoprirlo.
rng = random.Random(5)
con_segnale, gradiente = [], {}
for r in giornate(base=lambda m: 780.0, rumore=20.0, seed=7):
    forte = rng.random() < 0.5
    r = dict(r)
    r["regime_onset"] = r["regime_onset"] - (60.0 if forte else 0.0)
    r["regime_onset_wind"] = r["regime_onset"]
    con_segnale.append(r)
    gradiente[r["date"]] = forte


def informato(training, ctx):
    """Usa il gradiente della giornata da prevedere; i due livelli dal training."""
    forti = [o for d, _m, o in training if gradiente.get(d)]
    deboli = [o for d, _m, o in training if not gradiente.get(d)]
    if len(forti) < 10 or len(deboli) < 10:
        return clim(training, ctx)
    xs = forti if gradiente.get(ctx["date"]) else deboli
    return median(xs), "gradiente"


informato.nome = "due livelli per gradiente, stimati sul training"
r5 = valida_ingressi(con_segnale, previsori={"informato": informato})
g5, lo5, hi5 = r5["previsori"]["informato"]["guadagno"]
ok(r5["previsori"]["informato"]["mae"] < r5["previsori"]["climatologia"]["mae"],
   "banco: un previsore informativo batte la climatologia (%.0f vs %.0f min)"
   % (r5["previsori"]["informato"]["mae"], r5["previsori"]["climatologia"]["mae"]))
ok(lo5 is not None and lo5 > 0.0,
   "banco: e il guadagno regge al bootstrap (%.0f%%, IC %.0f..%.0f)"
   % (g5 or 0, lo5 or 0, hi5 or 0))
ok(r5["porte"]["guadagno"]["passa"] is True, "banco: porta B aperta")
ok(r5["porte"]["semiampiezza"]["passa"] is True, "banco: porta A aperta")
ok(r5["porte"]["bias_stagionale"]["passa"] is True, "banco: porta C aperta")
ok(r5["esito"] == "affidabile",
   "banco: esito 'affidabile' quando l'informazione c'e' davvero")
ok(r5["valutato"] == "informato",
   "banco: il previsore valutato e' il candidato, non il riferimento")

# Lo stesso previsore, ma col gradiente mescolato: la feature diventa rumore e
# il verdetto deve tornare 'incerto'. E' il controllo che il si' di prima
# dipendesse dall'informazione e non dalla forma del previsore.
_rimescolato = dict(gradiente)
_chiavi = sorted(_rimescolato)
_valori = [_rimescolato[k] for k in _chiavi]
random.Random(99).shuffle(_valori)
finto = dict(zip(_chiavi, _valori))


def finto_informato(training, ctx):
    forti = [o for d, _m, o in training if finto.get(d)]
    deboli = [o for d, _m, o in training if not finto.get(d)]
    if len(forti) < 10 or len(deboli) < 10:
        return clim(training, ctx)
    return median(forti if finto.get(ctx["date"]) else deboli), "gradiente finto"


r5b = valida_ingressi(con_segnale, previsori={"finto": finto_informato})
ok(r5b["porte"]["guadagno"]["passa"] is not True,
   "banco: con la stessa forma ma la feature mescolata, la porta B non si apre")

# --------------------------------------------------------------------------
# 6. La porta della semiampiezza morde
# --------------------------------------------------------------------------
larghi = giornate(rumore=120.0, seed=21)
r6 = valida_ingressi(larghi)
ok(r6["porte"]["semiampiezza"]["passa"] is False,
   "porta A: con ingressi sparsi su quattro ore la finestra da 45 min non tiene "
   "(semiampiezza %s min)" % round(r6["porte"]["semiampiezza"]["valore"] or -1))
ok(r6["esito"] == "incerto", "porta A: esito 'incerto' quando la finestra non tiene")

stretti = giornate(rumore=20.0, seed=22)
r7 = valida_ingressi(stretti)
ok(r7["porte"]["semiampiezza"]["passa"] is True,
   "porta A: con ingressi stretti la finestra tiene (semiampiezza %s min)"
   % round(r7["porte"]["semiampiezza"]["valore"] or -1))
ok(r7["porte"]["guadagno"]["passa"] is None,
   "porta B: senza modello da confrontare la porta del guadagno non si finge aperta")

# --------------------------------------------------------------------------
# 7. Il riferimento e' MENSILE, e si vede
# --------------------------------------------------------------------------
stagionale = giornate(base=lambda m: 600.0 + 45.0 * (m - 5), rumore=25.0, seed=31)
r8 = valida_ingressi(stagionale, previsori={
    "annuale": previsore_climatologico(mensile=False)})
ok(r8["previsori"]["annuale"]["mae"] > r8["previsori"]["climatologia"]["mae"],
   "riferimento: la mediana annuale e' peggiore di quella mensile "
   "(%.0f vs %.0f min) - per questo il baseline e' mensile"
   % (r8["previsori"]["annuale"]["mae"], r8["previsori"]["climatologia"]["mae"]))

# --------------------------------------------------------------------------
# 8. Quota di giornate con timing stimabile
# --------------------------------------------------------------------------
meta_mute = giornate(anni=(2018, 2019, 2020))
for i, r in enumerate(meta_mute):
    if i % 3 == 0:
        r["regime_onset"] = None
        r["reason"] = "no_regime"
r9 = valida_ingressi(meta_mute)
ok(abs(r9["quota_stimabile"] - 2.0 / 3.0) < 0.05,
   "quota: due terzi delle giornate hanno un ingresso, e il numero lo dice "
   "(%.2f)" % r9["quota_stimabile"])
ok(r9["n_stimabili"] == len(meta_mute),
   "quota: 'stimabile' e 'ha un ingresso' restano due cose diverse")

# --------------------------------------------------------------------------
# 9. La porta C distingue un bias da "il piu' storto di sedici gruppi"
# --------------------------------------------------------------------------
# Il bias di settembre e' vero e grande: la porta deve chiudersi e dire dove.
r10 = valida_ingressi(dati, previsori={"storto": storto})
p10 = r10["porte"]["bias_stagionale"]
ok(p10["passa"] is False, "porta C: un bias vero di mezz'ora la chiude")
ok(p10["sistematico_dove"] in ("mese 9", "stagione autunno"),
   "porta C: e dice dove (%s)" % p10["sistematico_dove"])

# Nessun bias, ma molto rumore e sedici gruppi da guardare: il gruppo piu'
# storto sara' storto di venti minuti per caso. La porta NON deve chiudersi.
falsi_allarmi = 0
for seme in range(8):
    rumorosi = giornate(mesi=(4, 5, 6, 7, 8, 9, 10), rumore=110.0, seed=100 + seme)
    rr = valida_ingressi(rumorosi)
    if rr["porte"]["bias_stagionale"]["passa"] is False:
        falsi_allarmi += 1
ok(falsi_allarmi == 0,
   "porta C: su otto campioni senza bias nessun falso allarme (%d)" % falsi_allarmi)

# E la porta C, da sola, non deve poter promuovere: se la finestra e' larga,
# l'esito resta incerto anche con bias zero.
ok(valida_ingressi(giornate(rumore=110.0, seed=77))["esito"] == "incerto",
   "porte: bias zero non basta, la finestra deve anche essere stretta")
