#!/usr/bin/env python3
"""Lancia tutti i controlli e dice si' o no con il codice di uscita.

Serve a due cose diverse:

  a mano, per non dover leggere seicento righe di PASS per trovare l'unica
  riga che dice FAIL;

  in cloud, come cancello prima di pubblicare: il sito e' generato dal
  codice, quindi un codice rotto pubblica un sito rotto. Meglio non
  pubblicare che pubblicare una cosa sbagliata con l'aria di essere giusta.

Un file che stampa SKIP non e' un fallimento: e' un controllo che qui non si
puo' fare (t_live_pagina ha bisogno di Playwright). Viene contato a parte e
dichiarato, perche' un controllo salto e' un controllo che non ha detto nulla,
e non deve sembrare verde.
"""
import glob
import os
import subprocess
import sys
import time

QUI = os.path.dirname(os.path.abspath(__file__))


def main():
    files = sorted(glob.glob(os.path.join(QUI, "t_*.py")))
    pass_tot = fail_tot = 0
    rotti, saltati = [], []
    t0 = time.time()
    for f in files:
        nome = os.path.basename(f)
        p = subprocess.run([sys.executable, f], capture_output=True, text=True)
        uscita = (p.stdout or "") + (p.stderr or "")
        righe = uscita.splitlines()
        passati = [r for r in righe if r.startswith("PASS")]
        falliti = [r for r in righe if r.startswith("FAIL")]
        skip = [r for r in righe if r.startswith("SKIP")]
        pass_tot += len(passati)
        fail_tot += len(falliti)
        stato = "ok"
        if falliti:
            stato = "FALLITO"
            rotti.append(nome)
        elif p.returncode != 0 or "Traceback" in uscita:
            stato = "ERRORE"
            rotti.append(nome)
        elif skip and not passati:
            stato = "saltato"
            saltati.append(nome)
        print("  %-22s %5d  %s" % (nome, len(passati), stato))
        for r in falliti:
            print("      " + r)
        if stato == "ERRORE":
            for r in righe[-12:]:
                print("      " + r)

    print("")
    print("  %d controlli, %d falliti, %.0f secondi"
          % (pass_tot, fail_tot, time.time() - t0))
    if saltati:
        print("  saltati (non provati, non verdi): %s" % ", ".join(saltati))
    if rotti:
        print("  DA SISTEMARE: %s" % ", ".join(rotti))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
