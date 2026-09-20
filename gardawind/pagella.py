"""La pagella: quello che abbiamo DETTO, contro quello che e' successo.

E' l'unico controllo che guarda il prodotto DA FUORI. Tutti gli altri guardano
i pezzi: il modello contro i suoi fold, un parser contro un input, una funzione
contro la sua definizione. Funzionano, e il 20/09/2026 hanno lasciato passare
per mesi una banda di incertezza costruita al rovescio - perche' nessuno
confrontava la frase pubblicata con la giornata vera.

Il materiale c'e' tutto da ieri e non lo leggeva nessuno:

  issued_profile   la curva che abbiamo pubblicato, ora per ora, con l'istante
                   in cui l'abbiamo emessa. Archiviata in storico/emesse.
  obs_hour         quello che la centralina ha misurato.

Da questi due si ricava il numero che il proprietario del sito vorrebbe sapere
per primo: "in queste ultime settimane, di quanto ho sbagliato, e da che
parte?". Non e' il MAE di un modello: e' lo scarto del PRODOTTO, quello che
l'utente ha letto prima di caricare la macchina.

Tre scelte dichiarate, perche' un confronto vale quanto le sue regole:

  LA RIDUZIONE E' LA STESSA delle due parti. Il picco della media oraria dentro
  la finestra del regime, e la finestra richiede la stessa copertura minima che
  chiede il resto del progetto (config.MIN_WINDOW_COVERAGE). Confrontare il
  massimo istantaneo previsto con la media oraria misurata farebbe sembrare che
  sovrastimiamo sempre.

  UNA SOLA EMISSIONE PER SCADENZA. Di una stessa giornata pubblichiamo la
  previsione quattro volte al giorno. Per ogni (giornata, scadenza) si tiene
  l'emissione PIU' RECENTE di quel giorno di emissione: e' quella che chi
  guardava la sera prima ha davvero letto.

  LO SCARTO E' PREVISTO MENO OSSERVATO, come in tutto il resto del progetto
  (util.regression_metrics). Positivo = abbiamo promesso piu' vento di quanto
  ne sia arrivato. E' il verso che conta piu' del numero: promettere troppo
  manda la gente in acqua per niente.
"""

from . import config, store
from .util import local_day, local_hour, mean, parse_dt_any

# Quante giornate guardare. Due mesi: abbastanza per vedere un verso, non tanto
# da mescolare una stagione con un'altra.
GIORNI = 60

# Sotto questo numero di giornate confrontabili non si scrive un numero: si dice
# quante ne mancano. Una media su tre giornate non e' una pagella, e' un aneddoto.
MIN_GIORNATE = 10


def osservato_giornaliero(spot_name):
    """{giorno locale: (picco della media oraria, ora locale del picco)}.

    La riduzione canonica dell'osservato dentro la finestra di un regime: ci
    passano sia la pagella sia la verifica dei singoli modelli (verify), che
    prima ne aveva una copia sua.
    """
    spot = config.SPOTS[spot_name]
    h0, h1 = spot["window"]
    need = max(3, int(config.MIN_WINDOW_COVERAGE * (h1 - h0 + 1)))
    per_giorno = {}
    for row in store.obs_hours(spot["station"]):
        dt = parse_dt_any(row["hour"])
        if dt is None or row["wind_mean"] is None:
            continue
        ora = local_hour(dt)
        if not (h0 <= ora <= h1):
            continue
        per_giorno.setdefault(local_day(dt), []).append((row["wind_mean"], ora))
    out = {}
    for giorno, valori in per_giorno.items():
        if len(valori) < need:
            continue
        picco, ora = max(valori)
        out[giorno] = (picco, ora)
    return out


def _emesse(place, da_giorno):
    """{(giorno valido, scadenza in giorni): [(ora locale, vento)]}.

    Una riga per (giornata, scadenza), dall'emissione piu' recente di quel
    giorno di emissione.
    """
    righe = store.connect().execute(
        "SELECT issued_at, valid_hour, wind_kn FROM issued_profile "
        "WHERE place=? AND valid_hour>=? AND wind_kn IS NOT NULL "
        "ORDER BY issued_at", (place, da_giorno))
    per_chiave = {}
    for r in righe:
        emesso = parse_dt_any(r["issued_at"])
        valido = parse_dt_any(r["valid_hour"])
        if emesso is None or valido is None:
            continue
        g_emissione = local_day(emesso)
        g_valido = local_day(valido)
        lead = _giorni_fra(g_emissione, g_valido)
        if lead is None or lead < 0:
            continue
        chiave = (g_valido, lead)
        precedente = per_chiave.get(chiave)
        if precedente is None or precedente[0] < r["issued_at"]:
            per_chiave[chiave] = (r["issued_at"], [])
        if per_chiave[chiave][0] == r["issued_at"]:
            per_chiave[chiave][1].append((local_hour(valido), r["wind_kn"]))
    return {k: v[1] for k, v in per_chiave.items()}


def _giorni_fra(a, b):
    import datetime as _dt
    try:
        return (_dt.date.fromisoformat(b) - _dt.date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return None


def confronto(giorni=None, adesso=None):
    """La pagella, per localita' e regime. Ritorna una lista di righe.

    Ogni riga: place, regime, spot, n (giornate confrontate), scarto_medio
    (previsto - osservato, in nodi), scarto_assoluto, scarto_ore (sull'ora del
    picco), e lo stesso per scadenza in `per_scadenza`.
    """
    from .util import utc_now, day_shift
    giorni = GIORNI if giorni is None else giorni
    oggi = local_day(adesso or utc_now())
    da = day_shift(oggi, -giorni)
    out = []
    for place in config.PLACES:
        emesse = _emesse(place, da)
        if not emesse:
            continue
        for spot_name, spot in sorted(config.SPOTS.items()):
            if spot.get("place") != place or spot.get("target") != "hourly":
                continue
            h0, h1 = spot["window"]
            osservato = osservato_giornaliero(spot_name)
            coppie = []
            for (giorno, lead), curva in sorted(emesse.items()):
                if giorno not in osservato or giorno >= oggi:
                    continue        # la giornata di oggi non e' ancora finita
                dentro = [(ora, v) for ora, v in curva if h0 <= ora <= h1]
                if len(dentro) < 3:
                    continue
                picco_p, ora_p = max((v, ora) for ora, v in dentro)
                picco_o, ora_o = osservato[giorno]
                coppie.append((lead, picco_p - picco_o, ora_p - ora_o))
            if not coppie:
                continue
            riga = {"place": place, "spot": spot_name, "regime": spot["regime"],
                    "n": len(coppie),
                    "scarto_medio": mean([d for _l, d, _h in coppie]),
                    "scarto_assoluto": mean([abs(d) for _l, d, _h in coppie]),
                    "scarto_ore": mean([h for _l, _d, h in coppie]),
                    "per_scadenza": {}}
            for lead in sorted({l for l, _d, _h in coppie}):
                q = [(d, h) for l, d, h in coppie if l == lead]
                riga["per_scadenza"][lead] = {
                    "n": len(q),
                    "scarto_medio": mean([d for d, _h in q]),
                    "scarto_assoluto": mean([abs(d) for d, _h in q]),
                }
            out.append(riga)
    return out


def in_parole(riga):
    """La pagella di una localita' in una frase, o cosa manca per averla.

    Le parole stanno qui accanto ai numeri, non nella pagina: sono la stessa
    idea, e una frase che interpreta un numero da un'altra parte prima o poi
    lo interpreta come non e' piu'.
    """
    if not riga or riga["n"] < MIN_GIORNATE:
        mancano = MIN_GIORNATE - (riga["n"] if riga else 0)
        return ("ancora poche giornate confrontabili: ne mancano %d perché il "
                "confronto significhi qualcosa" % mancano)
    d = riga["scarto_medio"]
    verso = ("abbiamo promesso in media %.1f kn IN PIÙ di quanto sia arrivato" % d
             if d > 0.4 else
             "abbiamo promesso in media %.1f kn in MENO di quanto sia arrivato" % -d
             if d < -0.4 else
             "in media abbiamo detto il vento giusto (%+.1f kn)" % d)
    ore = riga["scarto_ore"]
    quando = ""
    if abs(ore) >= 0.5:
        quando = (", e il picco lo abbiamo messo %.0f minuti %s"
                  % (abs(ore) * 60, "troppo tardi" if ore > 0 else "troppo presto"))
    return ("su %d giornate %s, con uno scarto tipico di %.1f kn%s"
            % (riga["n"], verso, riga["scarto_assoluto"], quando))
