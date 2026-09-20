"""Il livello HTTP ritenta, e ritenta le cose giuste.

Questo file nasce da un difetto che si e' visto solo sul sito pubblicato, e
per un motivo che vale piu' del difetto: il ripiego su curl, che sta in fondo
a `fetch` e serve ai certificati incompleti del Python di sistema di macOS,
porta `--retry 2`. Quindi sul Mac ogni chiamata aveva tre possibilita' e su
Linux una sola. Il ciclo di aggiornamento fa una ventina di richieste di fila,
e nel runner di GitHub l'ultima - le condizioni per gli analoghi - cadeva ogni
volta con un timeout dell'handshake SSL. Sul Mac la porta era aperta e la
curva affilata c'era; sul sito no, e nessuno dei 1.068 controlli lo vedeva.

Quanto e' robusta un'applicazione non lo decide il sistema operativo su cui
gira. Qui si pretende che il ritentativo esista, che non si applichi a un
errore che non migliora ritentando, e che non costi dodici minuti sulle
chiamate lunghe.
"""
import os
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from gardawind.sources import http as H

passati = 0


def ok(cond, msg):
    global passati
    if cond:
        passati += 1
        print("PASS " + msg)
    else:
        print("FAIL " + msg)


class Risposta(object):
    def __init__(self, corpo):
        self.corpo = corpo

    def read(self):
        return self.corpo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FintoOpener(object):
    """Fallisce le prime `quanti` volte, poi risponde."""

    def __init__(self, errore, quanti):
        self.errore = errore
        self.quanti = quanti
        self.chiamate = 0

    def open(self, req, timeout=None):
        self.chiamate += 1
        if self.chiamate <= self.quanti:
            raise self.errore
        return Risposta(b'{"ok":1}')


def con_opener(op, **kw):
    # La piattaforma si FORZA. Prima si salvava sys.platform e non si toccava
    # mai: su macOS - il solo computer su cui Gian lancia i controlli a mano -
    # http.fetch arriva in fondo e chiama curl DAVVERO, due volte per
    # esecuzione, e senza rete il file si impianta. Un test che si blocca e' un
    # test che non gira, cioe' che non difende niente.
    vecchio_o, vecchia_attesa, vecchia_piattaforma = H._OPENER, H.ATTESA_S, sys.platform
    sys.platform = "linux"
    H._OPENER = op
    H.ATTESA_S = (0.0, 0.0)          # nei controlli non si aspetta davvero
    try:
        return H.fetch("https://esempio.invalid/x", **kw), None
    except H.FetchError as e:
        return None, e
    finally:
        H._OPENER, H.ATTESA_S = vecchio_o, vecchia_attesa
        sys.platform = vecchia_piattaforma


# --------------------------------------------------------------------------
# Un errore di rete transitorio si supera
# --------------------------------------------------------------------------
op = FintoOpener(OSError("_ssl.c:999: The handshake operation timed out"), 2)
corpo, err = con_opener(op)
ok(corpo == b'{"ok":1}' and err is None,
   "due timeout di handshake di fila non fanno perdere la chiamata")
ok(op.chiamate == 3,
   "ci sono voluti tre tentativi, e tre e' il massimo dichiarato (%d)"
   % op.chiamate)

op = FintoOpener(OSError("timeout"), 99)
corpo, err = con_opener(op)
ok(corpo is None and err is not None,
   "ma se cade sempre l'errore arriva, non si ritenta all'infinito")
ok(op.chiamate == H._tentativi(60),
   "e i tentativi sono esattamente quelli dichiarati (%d)" % op.chiamate)

# --------------------------------------------------------------------------
# Un errore che non migliora ritentando non si ritenta
# --------------------------------------------------------------------------
class Http(urllib.error.HTTPError):
    def __init__(self, code):
        urllib.error.HTTPError.__init__(self, "u", code, "motivo", {}, None)

    def read(self):
        return b""


op = FintoOpener(Http(404), 99)
corpo, err = con_opener(op)
ok(corpo is None and op.chiamate == 1,
   "un 404 si ferma al primo tentativo: la richiesta e' sbagliata, non la"
   " rete (%d chiamate)" % op.chiamate)
ok(err is not None and "404" in str(err),
   "e l'errore dice quale codice, non un timeout generico")

op = FintoOpener(Http(429), 1)
corpo, err = con_opener(op)
ok(corpo == b'{"ok":1}' and op.chiamate == 2,
   "un 429 invece si' - e' il servizio che chiede di aspettare")

op = FintoOpener(Http(503), 1)
corpo, err = con_opener(op)
ok(corpo == b'{"ok":1}',
   "e anche un 503")

ok(not H._ritentabile(Http(400)) and H._ritentabile(Http(500))
   and H._ritentabile(OSError("x")),
   "la regola in una riga: 4xx no, 5xx e rete si'")

# --------------------------------------------------------------------------
# Il ritentativo non puo' costare dodici minuti
# --------------------------------------------------------------------------
# Le chiamate all'archivio hanno timeout di 180 e 240 secondi. Tre tentativi
# da 240 sono dodici minuti di build per una chiamata che il piu' delle volte
# non tornera' comunque: sulle lunghe si prova due volte.
ok(H._tentativi(60) == 3 and H._tentativi(240) == 2,
   "tre tentativi sulle chiamate brevi, due su quelle lunghe (%d, %d)"
   % (H._tentativi(60), H._tentativi(240)))
op = FintoOpener(OSError("timeout"), 99)
corpo, err = con_opener(op, timeout=240)
ok(op.chiamate == 2,
   "e una chiamata da 240 secondi non viene provata tre volte (%d)"
   % op.chiamate)

print("%d controlli di rete" % passati)
