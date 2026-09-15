"""La finestra utile: com'e' il vento quando si puo' uscire.

Per il Peler e' la domanda giusta: "alle 6-9 quanto sara' buono", non "a che
minuto e' nato". E le tre grandezze hanno tre ruoli che non vanno mescolati:

  vento medio         il fondo della sessione;
  raffica ricorrente  la spinta che TORNA, e che entra nella planabilita';
  raffica massima     NON decide la planata: descrive l'irregolarita'.

Il caso che questi controlli devono separare e' esattamente quello che
distingue una giornata navigabile da una sgradevole con gli stessi numeri
medi: 11 kn medi con la ricorrente a 16 si naviga, 11 kn medi con un solo
picco a 23 no. Se un domani qualcuno fa decidere la planata al massimo, questi
due casi tornano indistinguibili e il controllo fallisce.

E una cosa che questi controlli pretendono che NON ci sia: nessuna etichetta,
nessun coefficiente, nessuna soglia combinata. Quei numeri si scelgono
guardando la distribuzione vera, e la raffica nell'archivio lungo non c'e'.
"""
import os
import shutil
import sys

os.environ["GARDAWIND_HOME"] = "/tmp/gwfin"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
shutil.rmtree("/tmp/gwfin", ignore_errors=True)
os.makedirs("/tmp/gwfin", exist_ok=True)

from gardawind import config
from gardawind.orari import (MEDIA_MINIMA_RAPPORTO, SOGLIE_CANDIDATE,
                             finestra_utile_del_giorno, giudica_finestra_utile)

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)

ASSE, SETTORE = 54.0, 70.0          # Peler osservato a Torbole
DENTRO, FUORI = 54.0, 234.0
INIZIO, FINE = 360.0, 660.0          # 06:00 - 11:00


def giornata(valori, cad=10.0, direzione=DENTRO, da=INIZIO):
    """valori: [(media, raffica_o_None)] a cadenza cad, a partire da 'da'."""
    return [(da + i * cad, w, direzione, g)
            for i, (w, g) in enumerate(valori)]


# --------------------------------------------------------------------------
# 1. Copertura: sotto il minimo non si descrive, si dichiara
# --------------------------------------------------------------------------
F = giudica_finestra_utile([], ASSE, SETTORE, INIZIO, FINE)
ok(not F["estimable"] and F["reason"] == "no_data",
   "finestra vuota: no_data, e nessun numero")
F = giudica_finestra_utile(giornata([(12.0, 16.0)] * 3), ASSE, SETTORE,
                           INIZIO, FINE)
ok(not F["estimable"] and F["reason"] == "insufficient_coverage",
   "mezz'ora di dati su cinque ore: copertura insufficiente (%s)" % F["reason"])
ok(F["media_mediana"] is None,
   "e in quel caso non si stampa una mediana su tre campioni")

# Fuori dalla finestra i campioni non entrano.
fuori = giudica_finestra_utile(giornata([(20.0, 28.0)] * 24, da=60.0),
                               ASSE, SETTORE, INIZIO, FINE)
ok(fuori["reason"] == "no_data",
   "una giornata di vento tutta prima delle 06:00 non entra nella finestra utile")

# --------------------------------------------------------------------------
# 2. Il fondo: il vento medio, e la direzione che lo azzera
# --------------------------------------------------------------------------
piena = giornata([(12.0, 16.0)] * 30)          # cinque ore a cadenza 10'
F = giudica_finestra_utile(piena, ASSE, SETTORE, INIZIO, FINE)
ok(F["estimable"] and F["coverage_min"] >= 290,
   "cinque ore coperte (%s min)" % F["coverage_min"])
ok(F["media_mediana"] == 12.0 and F["media_max"] == 12.0,
   "il fondo e' 12 kn (%s)" % F["media_mediana"])
ok(F["cadence_min"] == 10.0, "cadenza dedotta dai dati")

storta = giudica_finestra_utile(
    giornata([(12.0, 16.0)] * 30, direzione=FUORI), ASSE, SETTORE, INIZIO, FINE)
ok(storta["media_mediana"] == 0.0 and storta["ric_mediana"] is None,
   "fuori settore la media va a zero e la ricorrente non esiste: quel vento "
   "non e' il Peler")

ignota = giudica_finestra_utile(
    [(INIZIO + i * 10.0, 12.0, None, 16.0) for i in range(30)],
    ASSE, SETTORE, INIZIO, FINE)
ok(ignota["media_mediana"] == 0.0 and ignota["dir_unknown_frac"] == 1.0,
   "direzione ignota non vale come coerente, e la quota ignota e' dichiarata")

# --------------------------------------------------------------------------
# 3. La ricorrente esce solo dove la cadenza la sostiene
# --------------------------------------------------------------------------
ok(F["ric_stimabile"] and F["ric_mediana"] == 16.0,
   "a cadenza 10' la ricorrente a 30' e' stimabile (%s)" % F["ric_mediana"])
rada = giudica_finestra_utile(giornata([(12.0, 16.0)] * 10, cad=30.0),
                              ASSE, SETTORE, INIZIO, FINE)
ok(rada["estimable"] and not rada["ric_stimabile"]
   and rada["ric_mediana"] is None,
   "a cadenza 30' non e' stimabile, e non viene allargata la finestra")
ok(rada["cadenza_raffica_min"] == 30.0 and rada["raffica_max"] == 16.0,
   "il massimo invece si misura comunque: non ha bisogno di una finestra")
ok(rada["media_mediana"] == 12.0,
   "e il fondo resta misurato: la raffica non filtra la giornata")

senza = giudica_finestra_utile(
    [(INIZIO + i * 10.0, 12.0, DENTRO, None) for i in range(30)],
    ASSE, SETTORE, INIZIO, FINE)
ok(senza["estimable"] and senza["raffica_max"] is None
   and senza["ric_stimabile"] is False and senza["media_mediana"] == 12.0,
   "senza raffica la giornata resta descritta nel fondo, e la raffica e' None")

# --------------------------------------------------------------------------
# 4. IL CASO CHE CONTA: stessa media, due giornate diverse
# --------------------------------------------------------------------------
# A: 11 kn medi con la spinta che torna a 16 -> navigabile col wing.
# B: 11 kn medi con un solo picco a 23 e il resto a 12 -> non navigabile.
# La media non le distingue. Il massimo le distingue AL CONTRARIO (B sembra
# piu' ventosa). Solo la ricorrente le mette nel verso giusto.
A = giudica_finestra_utile(giornata([(11.0, 16.0)] * 30),
                           ASSE, SETTORE, INIZIO, FINE)
raffiche_B = [12.0] * 30
raffiche_B[15] = 23.0
B = giudica_finestra_utile(
    giornata([(11.0, g) for g in raffiche_B]), ASSE, SETTORE, INIZIO, FINE)

ok(A["media_mediana"] == B["media_mediana"] == 11.0,
   "le due giornate hanno lo stesso fondo (11 kn)")
ok(B["raffica_max"] > A["raffica_max"],
   "il massimo dice che B e' piu' ventosa (%s contro %s): da solo, mente"
   % (B["raffica_max"], A["raffica_max"]))
ok(A["ric_mediana"] > B["ric_mediana"] + 3.0,
   "la ricorrente dice il contrario, ed e' quella giusta: A %s, B %s"
   % (A["ric_mediana"], B["ric_mediana"]))
ok(A["rapporto_ric_media"] > B["rapporto_ric_media"],
   "il rapporto ricorrente/media e' la potenza utile: A %.2f, B %.2f"
   % (A["rapporto_ric_media"], B["rapporto_ric_media"]))
ok(B["rapporto_max_media"] > A["rapporto_max_media"],
   "il rapporto massimo/media e' l'irregolarita': B %.2f, A %.2f"
   % (B["rapporto_max_media"], A["rapporto_max_media"]))
ok(A["planata_sostenuta_ric"][14.0] and not B["planata_sostenuta_ric"][14.0],
   "sulla ricorrente a 14 kn: A tiene per mezz'ora, B no")
ok(not A["planata_sostenuta_media"][14.0]
   and not B["planata_sostenuta_media"][14.0],
   "e sulla sola media nessuna delle due passa: e' il motivo per cui la "
   "planabilita' non puo' essere solo la media")

# La seconda componente della stabilita': quanto oscilla il rapporto.
osc = giudica_finestra_utile(
    giornata([(11.0, g) for g in ([13.0, 20.0] * 15)]),
    ASSE, SETTORE, INIZIO, FINE)
ok(osc["rapporto_disp"] is not None
   and osc["rapporto_disp"] > (A["rapporto_disp"] or 0.0),
   "una mattina che alterna 13 e 20 ha il rapporto piu' ballerino di una "
   "regolare (%.2f contro %.2f)"
   % (osc["rapporto_disp"], A["rapporto_disp"] or 0.0))

# Con la media sotto il minimo il rapporto non si calcola: 2 kn medi e 6 di
# raffica non sono una giornata rafficata, sono una giornata senza vento.
calma = giudica_finestra_utile(giornata([(2.0, 6.0)] * 30),
                               ASSE, SETTORE, INIZIO, FINE)
ok(calma["rapporto_ric_media"] is None and calma["rapporto_max_media"] is None,
   "sotto %g kn di media il rapporto non viene dichiarato" % MEDIA_MINIMA_RAPPORTO)
ok(calma["media_mediana"] == 2.0,
   "ma la giornata calma resta misurata, non scartata")

# --------------------------------------------------------------------------
# 5. Nessuna etichetta, nessun coefficiente
# --------------------------------------------------------------------------
vietate = [k for k in A
           if any(t in k for t in ("giudizio", "planabile", "etichetta",
                                   "forte", "marginale", "debole", "score"))]
ok(not vietate,
   "la struttura non contiene nessun giudizio ne' punteggio: %s" % vietate)
ok(set(A["minuti_sopra_media"]) == set(SOGLIE_CANDIDATE),
   "il tempo sopra soglia arriva per una griglia di soglie CANDIDATE")
sopra = [A["minuti_sopra_media"][t] for t in sorted(SOGLIE_CANDIDATE)]
ok(all(sopra[i] >= sopra[i + 1] for i in range(len(sopra) - 1)),
   "e il tempo sopra soglia non cresce con la soglia: %s" % sopra)

# --------------------------------------------------------------------------
# 6. I tre vincoli della finestra utile, e il piu' stretto vince
# --------------------------------------------------------------------------
def hhmm(m):
    return "%02d:%02d" % (int(m // 60), int(round(m % 60)))


i_giu, f_giu = finestra_utile_del_giorno("Torbole-Peler", "2026-06-21")
i_dic, f_dic = finestra_utile_del_giorno("Torbole-Peler", "2026-12-21")
# A giugno alba + 30 minuti da' 06:01: la luce vince anche in estate, per un
# minuto. Arrotondato a cinque, coincide con l'ora pratica - ed e' giusto che
# coincida, perche' un minuto non esiste in dati a cadenza dieci.
ok(i_giu == 6 * 60.0,
   "Peler a giugno: 06:00, con luce e ora pratica che combaciano (%s)"
   % hhmm(i_giu))
ok(i_giu % 5 == 0 and i_dic % 5 == 0 and f_dic % 5 == 0,
   "i limiti che vengono dalla luce sono arrotondati a cinque minuti")
ok(i_dic > 8 * 60.0,
   "Peler a dicembre: vince la luce, dopo le 08:00 (%s)" % hhmm(i_dic))
ok(f_giu == f_dic == 11 * 60.0,
   "e la fine resta quella del regime, che al mattino la luce non tocca")

o_giu = finestra_utile_del_giorno("Torbole-Ora", "2026-06-21")
o_dic = finestra_utile_del_giorno("Torbole-Ora", "2026-12-21")
ok(o_giu[1] == 20 * 60.0, "Ora a giugno: fine alle 20:00, la finestra del regime")
ok(o_dic[1] < 17 * 60.0,
   "Ora a dicembre: la fine scende col tramonto (%s), e sono quasi quattro "
   "ore in meno di finestra nominale" % hhmm(o_dic[1]))
ok(o_giu[0] == o_dic[0] == 11 * 60.0,
   "e l'inizio dell'Ora non dipende dall'alba: a quell'ora c'e' luce sempre")

# L'ora pratica esiste solo dove ha senso: l'Ora non ne ha una.
ok(config.SPOTS["Torbole-Peler"].get("ora_pratica") == 6.0
   and config.SPOTS["Torbole-Ora"].get("ora_pratica") is None,
   "l'ora pratica e' dichiarata nella configurazione, e solo per il Peler")

# --------------------------------------------------------------------------
# 7. La contabilita' che impedisce "quattordici anni di planabilita'"
# --------------------------------------------------------------------------
from gardawind.orari import copertura_dataset

giorni = {}
for i in range(100):                      # storico lungo: solo vento medio
    giorni["2020-%02d-%02d" % (i // 28 + 1, i % 28 + 1)] = [
        (360 + k * 10, 12.0, DENTRO, None) for k in range(30)]
for i in range(12):                       # raffica a 10': ricorrente stimabile
    giorni["2026-09-%02d" % (i + 1)] = [
        (360 + k * 10, 12.0, DENTRO, 16.0) for k in range(30)]
for i in range(8):                        # raffica a 30': NON stimabile
    giorni["2026-08-%02d" % (i + 1)] = [
        (360 + k * 30, 12.0, DENTRO, 16.0) for k in range(10)]

C = copertura_dataset(giorni)
ok(C["n_days_total"] == 120, "n_days_total conta tutte le giornate (%d)"
   % C["n_days_total"])
ok(C["n_days_with_gust"] == 20,
   "n_days_with_gust conta solo quelle con la raffica (%d)"
   % C["n_days_with_gust"])
ok(C["n_days_recurrent_ready"] == 12,
   "e la ricorrente a 30' e' stimabile solo su dodici: le otto a cadenza 30 "
   "hanno la raffica ma non la sostengono (%d)" % C["n_days_recurrent_ready"])
ok(abs(C["quota_recurrent_ready"] - 0.1) < 1e-9,
   "la quota e' il 10%%, non il 17%% delle giornate con raffica")
ok(C["periodo"] == ("2020-01-01", "2026-09-12")
   and C["periodo_recurrent"] == ("2026-09-01", "2026-09-12"),
   "i due periodi sono diversi e vengono dichiarati entrambi")
ok(C["planability_ready"] is False
   and "prospettico" in C["livello_planabilita"],
   "con dodici giornate la planabilita' e' dichiarata prospettica, non "
   "pronta: %s" % C["livello_planabilita"])
# Dodici giornate a 10' e otto a 30': la mediana delle cadenze della raffica
# e' 10, non 20. E' la mediana, non la media fra i due regimi di cadenza - e
# per questo il numero che conta resta il CONTEGGIO per giornata (12 su 20),
# non questo riassunto.
ok(C["cadenza_raffica_mediana"] == 10.0,
   "la cadenza della raffica e' la mediana delle sue, non quella del vento "
   "(%s)" % C["cadenza_raffica_mediana"])

# Con abbastanza giornate diventa pronta, e la soglia e' un parametro
# dichiarato, non un numero nascosto.
ok(copertura_dataset(giorni, soglia_planability=10)["planability_ready"] is True,
   "abbassando la soglia dichiarata diventa pronta: la soglia e' un parametro")

vuoto = copertura_dataset({})
ok(vuoto["n_days_total"] == 0 and vuoto["quota_with_gust"] is None
   and vuoto["planability_ready"] is False,
   "su zero giornate non si divide per zero e non si dichiara niente di pronto")
