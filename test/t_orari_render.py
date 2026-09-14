"""Due smoke test del RENDERING degli orari. Non della logica.

La tabella formattata e' una rappresentazione finale: qui si verifica solo che
non esploda e che traduca i codici. Tutto quello che potrebbe essere sbagliato
nel merito (ingressi, climatologia, bimodalita') e' provato in t_orari.py
contro la logica pura, dove una regex su una colonna non c'entra niente.

Il secondo caso e' quello che conta davvero: se qualcuno introduce un codice
di "reason" nuovo senza aggiungerlo a REASONS e a MOTIVI, la tabella deve
dirlo a voce alta invece di stampare una riga vuota.
"""
import io, os, sys
os.environ["GARDAWIND_HOME"] = "/tmp/gwrender"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import shutil
shutil.rmtree("/tmp/gwrender", ignore_errors=True)

from gardawind import orari as O
from gardawind import __main__ as M

ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)


def finta_climatologia(codici, mediana=760.0, modi=None):
    """Una climatologia inventata, nella forma esatta che il livello 2 produce."""
    per_mese, annuale = {}, {}
    for b in O.BERSAGLI:
        for l in O.LETTURE:
            for m in range(1, 13):
                pieno = (m == 6)
                per_mese[(b, l, m)] = {
                    "n": 20 if pieno else 2,
                    "mediana": mediana if pieno else None,
                    "disp": 35.0 if pieno else None,
                    "durata": 180.0 if pieno else None,
                    "modi": (modi if (pieno and l == "regime") else None),
                    "dip": (0.2 if (modi and pieno and l == "regime") else None),
                }
            annuale[(b, l)] = {"n": 20 if l == "vento" else 14,
                               "mediana": mediana, "disp": 40.0,
                               "durata": None, "modi": None, "dip": None}
    per_giorno = {}
    for i, c in enumerate(codici):
        per_giorno["2020-06-%02d" % (i + 1)] = {"reason": c}
    return {"spot": "Torbole-Ora", "asse": 191.0, "settore": 70.0,
            "soglie": {"regime": 11.0, "planata": 14.0},
            "n_giorni": len(codici), "n_dir_ignota": 3,
            "n_non_stimabili": 1, "per_mese": per_mese,
            "annuale": annuale, "ingressi": {}, "per_giorno": per_giorno}


def stampa(clim):
    vera = O.climatologia
    O.climatologia = lambda *a, **k: clim
    buf, vecchio = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        M.cmd_orari("Torbole-Ora")
    finally:
        sys.stdout = vecchio
        O.climatologia = vera
    return buf.getvalue()


# 1. Gira, traduce i codici, e la nota sui due picchi compare dove ci sono.
t = stampa(finta_climatologia(["ok", "ok", "no_regime",
                               "direction_outside_sector", "gap_too_large"],
                              modi=[700.0, 880.0]))
ok("ORARI DI INGRESSO" in t and "Torbole-Ora" in t, "render: intestazione")
ok("soglia mai superata" in t, "render: no_regime tradotto")
ok("direzione fuori settore" in t, "render: direction_outside_sector tradotto")
ok("orario = limite" in t, "render: gap_too_large dichiarato come limite")
ok("12:40" in t, "render: la mediana 760 min diventa 12:40")
ok("DUE PICCHI" in t and "11:40" in t and "14:40" in t,
   "render: i due picchi annotati sul mese giusto")
ok("ATTENZIONE" in t and "riferimento povero" in t,
   "render: avviso di bimodalita' in chiusura")
ok("INGRESSO REGIME" in t and "INGRESSO PLANATA" in t,
   "render: i due bersagli restano separati")
ok(t.count("VENTO (solo intensita')") == 2
   and t.count("REGIME (intensita' + direzione)") == 2,
   "render: le due letture affiancate per ciascun bersaglio")
ok("taglia 6 ingressi su 20 (30%)" in t,
   "render: quanto taglia la direzione, calcolato sui due n")

# 2. Un mese senza due picchi non deve inventare l'avviso.
t2 = stampa(finta_climatologia(["ok"] * 12))
ok("DUE PICCHI" not in t2 and "mediana mensile e' un riassunto" in t2,
   "render: nessun avviso se nessun mese e' bimodale")

# 3. Un codice non previsto non passa in silenzio.
t3 = stampa(finta_climatologia(["ok", "boh_inventato"]))
ok("codici non previsti" in t3 and "boh_inventato" in t3,
   "render: un reason fuori da REASONS viene denunciato")
ok(all(c in M.MOTIVI for c in O.REASONS),
   "render: ogni codice di REASONS ha la sua traduzione")
