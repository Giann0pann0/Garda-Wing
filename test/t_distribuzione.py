"""La distribuzione dentro la finestra utile: i numeri da cui si SCEGLIE.

Questa tabella esiste per una ragione sola: le soglie di planata non sono mai
state scelte, e la scelta va fatta guardando i numeri veri. Quindi i controlli
qui difendono quattro promesse, e ognuna e' un modo in cui una tabella di
questo tipo mente di solito.

  1. nessuna soglia e' privilegiata. La griglia c'e' tutta, e togliendo o
     aggiungendo una soglia candidata la tabella cambia senza che nessun
     calcolo cambi: se un giorno un coefficiente si infila qui dentro, questo
     controllo diventa rosso.
  2. "sostenuta" vuol dire sostenuta. Una giornata con un solo colpo di vento
     sopra soglia NON conta, una con mezz'ora di fila conta. E' la differenza
     fra "ho visto 14 nodi" e "ci ho navigato".
  3. si contano solo le giornate STIMABILI, e le altre si dichiarano col loro
     motivo. Una quota calcolata su un denominatore che include le giornate
     senza dato e' una quota piu' bassa del vero, e nessuno se ne accorge.
  4. la contabilita' dei due livelli sopravvive: questa tabella e' sul vento
     medio, e il numero di giornate con la ricorrente stimabile viaggia
     accanto. E' la difesa contro "abbiamo quattordici anni di planabilita'".
"""
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwdistr"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
shutil.rmtree("/tmp/gwdistr", ignore_errors=True)
os.makedirs("/tmp/gwdistr", exist_ok=True)

from gardawind import config, store
from gardawind.orari import (MIN_GG_MESE, PERSISTENZA_MIN, SOGLIE_CANDIDATE,
                             aggrega_finestre, distribuzione_finestra_utile,
                             giudica_finestra_utile)

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)

ASSE, SETTORE = 54.0, 70.0
DENTRO = 54.0
INIZIO, FINE = 360.0, 660.0          # 06:00 - 11:00


def giornata(valori, cad=10.0, direzione=DENTRO, da=INIZIO):
    return [(da + i * cad, w, direzione, g)
            for i, (w, g) in enumerate(valori)]


def esito(media, n=30, raffica=None):
    """Una finestra piena di vento costante: risposta nota a mano."""
    return giudica_finestra_utile(giornata([(media, raffica)] * n),
                                 ASSE, SETTORE, INIZIO, FINE)


# --------------------------------------------------------------------------
# 1. Il conteggio: giornate stimabili al denominatore, le altre dichiarate
# --------------------------------------------------------------------------
# Dieci giornate di gennaio a 15 kn costanti, piu' cinque senza dato.
finestre = {}
for i in range(1, 11):
    finestre["2020-01-%02d" % i] = esito(15.0)
for i in range(11, 16):
    finestre["2020-01-%02d" % i] = giudica_finestra_utile(
        [], ASSE, SETTORE, INIZIO, FINE)

D = aggrega_finestre(finestre)
G = D["mesi"][1]
ok(G["n_giorni"] == 15 and G["n_stimabili"] == 10,
   "quindici giornate, dieci stimabili (%d / %d)"
   % (G["n_giorni"], G["n_stimabili"]))
ok(G["motivi"].get("no_data") == 5,
   "e le cinque scartate sono dichiarate col loro motivo: %s" % G["motivi"])
ok(abs(G["soglie"][14.0]["quota"] - 1.0) < 1e-9,
   "a 14 kn la quota e' 10/10 = 100%%, non 10/15 (%.3f)"
   % G["soglie"][14.0]["quota"])
ok(G["soglie"][16.0]["quota"] == 0.0,
   "a 16 kn nessuna giornata: 15 nodi costanti non superano 16")
ok(G["sufficiente"] is True,
   "dieci giornate stimabili bastano (il minimo e' %d)" % MIN_GG_MESE)

nove = {k: v for k, v in finestre.items() if k <= "2020-01-09"}
ok(aggrega_finestre(nove)["mesi"][1]["sufficiente"] is False,
   "nove no: il mese si restituisce comunque, ma marcato fragile")
ok(aggrega_finestre(nove)["mesi"][1]["n_stimabili"] == 9,
   "e i numeri ci sono: nascondere un mese scarso e' diverso da dirlo")

# --------------------------------------------------------------------------
# 2. Nessuna soglia privilegiata: la griglia e' un parametro
# --------------------------------------------------------------------------
tutte = set(aggrega_finestre(finestre)["mesi"][1]["soglie"])
ok(tutte == set(SOGLIE_CANDIDATE),
   "per difetto ci sono tutte e sole le soglie candidate: %s" % sorted(tutte))
sola = aggrega_finestre(finestre, soglie=(13.0,))
ok(set(sola["mesi"][1]["soglie"]) == {13.0},
   "passando una griglia diversa la tabella cambia, il calcolo no")
# Ma una soglia che le giornate non hanno calcolato non diventa uno zero.
ok(sola["mesi"][1]["soglie"][13.0]["non_calcolata"] is True
   and sola["mesi"][1]["soglie"][13.0]["quota"] is None,
   "chiedere una soglia che le giornate non hanno calcolato da' 'non lo"
   " sappiamo', non 'mai': quota %s"
   % sola["mesi"][1]["soglie"][13.0]["quota"])
tredici = {g: giudica_finestra_utile(giornata([(15.0, None)] * 30), ASSE,
                                     SETTORE, INIZIO, FINE, soglie=(13.0,))
           for g in ("2020-01-%02d" % i for i in range(1, 11))}
ok(abs(aggrega_finestre(tredici, soglie=(13.0,))["mesi"][1]["soglie"][13.0]["quota"]
       - 1.0) < 1e-9,
   "calcolata per davvero, una soglia mai vista prima (13 kn) funziona come"
   " le altre")

# --------------------------------------------------------------------------
# 3. "Sostenuta" vuol dire sostenuta: il colpo di vento non conta
# --------------------------------------------------------------------------
# Venti minuti sopra 16 in mezzo a una giornata da 12: sotto la persistenza.
colpo = [(12.0, None)] * 10 + [(18.0, None)] * 2 + [(12.0, None)] * 18
picco_breve = giudica_finestra_utile(giornata(colpo), ASSE, SETTORE,
                                     INIZIO, FINE)
# Mezz'ora piena sopra 16, nello stesso posto.
lungo = [(12.0, None)] * 10 + [(18.0, None)] * 4 + [(12.0, None)] * 16
picco_lungo = giudica_finestra_utile(giornata(lungo), ASSE, SETTORE,
                                     INIZIO, FINE)
A = aggrega_finestre({"2020-03-01": picco_breve})["mesi"][3]
B = aggrega_finestre({"2020-03-01": picco_lungo})["mesi"][3]
ok(A["soglie"][16.0]["n_sostenute"] == 0,
   "venti minuti sopra 16 non fanno una giornata da 16: e' un colpo di vento")
ok(B["soglie"][16.0]["n_sostenute"] == 1,
   "mezz'ora di fila si': %g minuti sono la persistenza" % PERSISTENZA_MIN)
ok(A["soglie"][12.0]["n_sostenute"] == 1
   and B["soglie"][12.0]["n_sostenute"] == 1,
   "entrambe contano a 12 kn, che e' il fondo di tutte due")
ok(A["soglie"][16.0]["durata_mediana"] is None,
   "e senza giornate sostenute non si stampa una durata (%s)"
   % A["soglie"][16.0]["durata_mediana"])

# La durata e' quella del tempo sopra soglia, non della finestra.
ok(B["soglie"][16.0]["durata_mediana"] and
   B["soglie"][16.0]["durata_mediana"] < (FINE - INIZIO),
   "la durata sopra 16 e' una parte della finestra, non la finestra: %s"
   % B["soglie"][16.0]["durata_mediana"])
ok(B["soglie"][12.0]["durata_mediana"] > B["soglie"][16.0]["durata_mediana"],
   "e sopra una soglia piu' bassa si resta piu' a lungo")

# --------------------------------------------------------------------------
# 4. I mesi sono mesi, e l'anno e' la somma
# --------------------------------------------------------------------------
misto = {}
for i in range(1, 13):
    misto["2021-01-%02d" % i] = esito(20.0)     # gennaio forte
for i in range(1, 13):
    misto["2021-07-%02d" % i] = esito(8.0)      # luglio debole
M = aggrega_finestre(misto)
ok(set(M["mesi"]) == {1, 7},
   "ci sono solo i mesi con giornate: %s" % sorted(M["mesi"]))
ok(M["mesi"][1]["soglie"][18.0]["quota"] == 1.0
   and M["mesi"][7]["soglie"][18.0]["quota"] == 0.0,
   "gennaio a 20 kn passa i 18, luglio a 8 no: i mesi non si mescolano")
ok(M["anno"]["n_stimabili"] == 24,
   "l'anno ha tutte le giornate (%d)" % M["anno"]["n_stimabili"])
ok(abs(M["anno"]["soglie"][18.0]["quota"] - 0.5) < 1e-9,
   "e la quota annuale e' la media vera delle due meta': %.3f"
   % M["anno"]["soglie"][18.0]["quota"])
ok(M["anno"]["media_mediana"] == 14.0,
   "la mediana annuale sta fra 8 e 20 (%.1f)" % M["anno"]["media_mediana"])
ok(M["mesi"][1]["media_q25"] == 20.0 and M["mesi"][1]["media_q75"] == 20.0,
   "con vento costante i quartili collassano sul valore: nessun rumore finto")
ok(aggrega_finestre({})["mesi"] == {}
   and aggrega_finestre({})["anno"]["n_stimabili"] == 0,
   "un insieme vuoto non esplode e non inventa un mese")

# --------------------------------------------------------------------------
# 4b. Le stagioni d'uso: non si naviga dodici mesi l'anno
# --------------------------------------------------------------------------
# Luglio (primaria) debole, gennaio (diagnostica) forte: se le stagioni
# funzionano, la quota della primaria NON deve ereditare gennaio. E' il caso
# che conta davvero, perche' il Peler e' un regime invernale: mediare le due
# stagioni farebbe sembrare utilizzabile un vento che arriva quando non si
# naviga.
S = aggrega_finestre(misto, stagioni=config.STAGIONI_USO)
ok(set(S["stagioni"]) == {"primaria", "transizione", "diagnostica"},
   "le tre stagioni ci sono: %s" % sorted(S["stagioni"]))
ok(S["stagioni"]["primaria"]["n_stimabili"] == 12
   and S["stagioni"]["diagnostica"]["n_stimabili"] == 12,
   "luglio finisce nella primaria e gennaio nella diagnostica (%d / %d)"
   % (S["stagioni"]["primaria"]["n_stimabili"],
      S["stagioni"]["diagnostica"]["n_stimabili"]))
ok(S["stagioni"]["transizione"]["n_stimabili"] == 0,
   "marzo e novembre non hanno giornate qui, e la stagione lo dice con zero")
ok(S["stagioni"]["primaria"]["soglie"][18.0]["quota"] == 0.0,
   "nella stagione in cui si naviga, a 18 kn: nessuna giornata (%.2f)"
   % S["stagioni"]["primaria"]["soglie"][18.0]["quota"])
ok(S["stagioni"]["diagnostica"]["soglie"][18.0]["quota"] == 1.0,
   "in inverno tutte: ed e' esattamente il numero che non va usato per"
   " scegliere la soglia")
ok(S["anno"]["soglie"][18.0]["quota"] == 0.5,
   "la media annuale (50%) non descrive nessuna delle due stagioni")
ok(S["stagioni"]["primaria"]["mesi_inclusi"] == (4, 5, 6, 7, 8, 9, 10),
   "e ogni stagione dichiara quali mesi contiene: %s"
   % (S["stagioni"]["primaria"]["mesi_inclusi"],))

senza = aggrega_finestre(misto, stagioni=None)
ok(senza["stagioni"] == {} and senza["ordine_stagioni"] == (),
   "senza stagioni passate la tabella resta mensile: il raggruppamento e'"
   " una decisione di chi chiama, non della funzione")
alt = aggrega_finestre(misto, stagioni=(("solo-luglio", (7,)),))
ok(alt["stagioni"]["solo-luglio"]["n_stimabili"] == 12,
   "e un raggruppamento diverso funziona senza toccare nessun calcolo")

# --------------------------------------------------------------------------
# 5. La finestra dichiarata e' quella usata
# --------------------------------------------------------------------------
F = aggrega_finestre({"2022-05-01": esito(14.0)})["mesi"][5]
ok(F["inizio_mediano"] == INIZIO and F["fine_mediana"] == FINE,
   "inizio e fine mediani sono quelli della finestra passata (%s-%s)"
   % (F["inizio_mediano"], F["fine_mediana"]))
ok(F["durata_mediana"] == FINE - INIZIO,
   "e la durata e' la loro differenza, non un numero a parte")

# Due finestre diverse nello stesso mese: la mediana sta in mezzo, non a caso.
larga = giudica_finestra_utile(giornata([(14.0, None)] * 42), ASSE, SETTORE,
                               300.0, 720.0)
due = aggrega_finestre({"2022-05-01": esito(14.0), "2022-05-02": larga})["mesi"][5]
ok(min(INIZIO, 300.0) <= due["inizio_mediano"] <= max(INIZIO, 300.0),
   "con finestre diverse l'inizio mediano sta fra le due (%s)"
   % due["inizio_mediano"])

# --------------------------------------------------------------------------
# 6. Il livello del dato: media si, planabilita' no
# --------------------------------------------------------------------------
con_raffica = {}
for i in range(1, 11):
    con_raffica["2023-02-%02d" % i] = esito(14.0, raffica=19.0)
for i in range(11, 21):
    con_raffica["2023-02-%02d" % i] = esito(14.0)          # senza raffica
R = aggrega_finestre(con_raffica)["mesi"][2]
ok(R["n_stimabili"] == 20 and R["n_ric_stimabile"] == 10,
   "venti giornate stimabili, dieci con la ricorrente stimabile (%d / %d)"
   % (R["n_stimabili"], R["n_ric_stimabile"]))
ok(R["soglie"][12.0]["quota"] == 1.0,
   "la quota sulla MEDIA usa tutte e venti: la media c'e' anche senza raffica")

# --------------------------------------------------------------------------
# 7. Dal database: la finestra si ricalcola giorno per giorno
# --------------------------------------------------------------------------
store.init()
ST = config.SPOTS["Torbole-Peler"]["station"]
from gardawind.util import iso_utc, local_naive_to_utc
import datetime as dt


def salva(giorno, minuti0, n, media, cad=10):
    righe = []
    for i in range(n):
        m = minuti0 + i * cad
        naive = dt.datetime.fromisoformat(giorno + "T00:00:00") \
            + dt.timedelta(minutes=m)
        righe.append((ST, iso_utc(local_naive_to_utc(naive)), media,
                      None, 54.0, "t"))
    store.connect().executemany(
        "INSERT OR REPLACE INTO obs_sample(station,ts,wind_kn,gust_kn,dir_deg,"
        "source) VALUES(?,?,?,?,?,?)", righe)
    store.connect().commit()


# Giugno: alba presto, la finestra parte dall'ora pratica (06:00).
# Dicembre: alba tardi, la finestra parte dopo. Stesso vento, finestre diverse.
for i in range(1, 13):
    salva("2024-06-%02d" % i, 300, 48, 16.0)
    salva("2024-12-%02d" % i, 300, 48, 16.0)

DD = distribuzione_finestra_utile("Torbole-Peler")
giu, dic = DD["mesi"][6], DD["mesi"][12]
ok(giu["n_stimabili"] == 12 and dic["n_stimabili"] == 12,
   "dodici giornate stimabili in ognuno dei due mesi (%d / %d)"
   % (giu["n_stimabili"], dic["n_stimabili"]))
ok(dic["inizio_mediano"] > giu["inizio_mediano"],
   "a dicembre la finestra utile comincia dopo che a giugno (%s vs %s): e' la"
   " luce, e non viene mediata via"
   % (dic["inizio_mediano"], giu["inizio_mediano"]))
ok(giu["durata_mediana"] > dic["durata_mediana"],
   "e dura piu' a lungo (%s vs %s minuti)"
   % (giu["durata_mediana"], dic["durata_mediana"]))
ok(giu["soglie"][14.0]["quota"] == 1.0 and dic["soglie"][14.0]["quota"] == 1.0,
   "con 16 kn costanti entrambi i mesi passano i 14")
ok(giu["soglie"][14.0]["durata_mediana"] > dic["soglie"][14.0]["durata_mediana"],
   "ma il tempo sopra soglia a dicembre e' minore: la finestra e' piu' corta")
ok(DD["copertura"]["n_days_total"] == 24,
   "la copertura del dataset viaggia con la distribuzione (%d giornate)"
   % DD["copertura"]["n_days_total"])
ok(DD["copertura"]["n_days_with_gust"] == 0
   and DD["copertura"]["planability_ready"] is False,
   "e dichiara che senza raffica non c'e' planabilita': %s"
   % DD["copertura"]["livello_planabilita"])
ok(DD["asse"] == config.SPOTS["Torbole-Peler"].get(
        "axis_obs", config.SPOTS["Torbole-Peler"]["axis"]),
   "l'asse usato e' quello osservato della centralina, non quello nominale")

# --------------------------------------------------------------------------
# 8. Il rendering: traduce e non decide
# --------------------------------------------------------------------------
import io
import contextlib
from gardawind import __main__ as M2

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    M2.cmd_distribuzione("Torbole-Peler")
testo = buf.getvalue()
ok("DENTRO LA FINESTRA UTILE" in testo and "Torbole-Peler" in testo,
   "il comando stampa la sua intestazione")
ok("LIMITE INFERIORE" in testo,
   "e dichiara che la quota sulla media e' un limite inferiore, non la"
   " planabilita'")
ok("COPERTURA DEL DATO" in testo,
   "la copertura sta in testa all'analisi, non in fondo")
for t in SOGLIE_CANDIDATE:
    ok(("%g kn" % t) in testo, "la colonna della soglia %g kn c'e'" % t)
ok("dic" in testo and "giu" in testo,
   "i mesi con dato compaiono col loro nome")
# Le colonne del totale devono cadere dove cadono quelle dei mesi. Scritte a
# mano separatamente si scollano di un carattere, e una tabella storta non fa
# fallire niente: si legge male e basta, che e' il modo peggiore di rompersi.
righe_t = testo.splitlines()
mese_r = [r for r in righe_t if r.startswith("  giu ") and ":" in r]
anno_r = [r for r in righe_t if r.startswith("  anno") and ":" in r]
ok(bool(mese_r) and bool(anno_r)
   and mese_r[0].index(":") == anno_r[0].index(":"),
   "la riga del totale e quelle dei mesi hanno le colonne allineate (%s vs %s)"
   % (mese_r[0].index(":") if mese_r else None,
      anno_r[0].index(":") if anno_r else None))
perc_m = [r for r in righe_t if r.startswith("  giu ") and "%" in r]
perc_a = [r for r in righe_t if r.startswith("  anno") and "%" in r]
ok(bool(perc_m) and bool(perc_a)
   and perc_m[0].index("%") == perc_a[0].index("%"),
   "e lo stesso vale nella tabella delle soglie")

ok("forte" not in testo and "debole" not in testo,
   "e nessuna etichetta di giudizio: la scelta non e' del codice")
ok("STAGIONE D'USO" in testo and "primaria" in testo
   and "diagnostica" in testo,
   "la tabella per stagione d'uso viene stampata")
ok("non la usi" in testo,
   "e spiega perche' l'inverno non tara il prodotto")
ok("tua ala, non del mese" in testo,
   "dicendo anche che la soglia non la sceglie la stagione ma l'attrezzatura")
ok("ricorrente 30' era stimabile: 0 su 24" in testo,
   "in fondo dice quante giornate hanno la ricorrente: %s"
   % ("trovato" if "era stimabile: 0 su 24" in testo else "NON trovato"))
