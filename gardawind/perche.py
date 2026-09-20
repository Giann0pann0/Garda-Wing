"""Perche' il sito prevede questo. Le ragioni, non una giustificazione.

Ogni riga nasce da un numero che il programma ha GIA' calcolato per decidere: il
gradiente barico nord-sud, il contrasto termico fra pianura e valle, il vento in
quota rispetto all'asse del regime, la notte serena o coperta, la pioggia, il
vento grezzo dei modelli, il loro accordo, e - dove gli analoghi sono promossi -
quante delle giornate storicamente piu' simili hanno davvero dato vento.

Due regole, e sono quelle che distinguono una spiegazione da una decorazione:

  NIENTE AGGETTIVI SENZA UNA DISTRIBUZIONE. Non si scrive "gradiente molto
  favorevole": non abbiamo una soglia misurata per dirlo. Si scrive il valore e
  il suo VERSO, che e' un fatto fisico ("+2,1 hPa: spinge il Pelèr"), oppure si
  confronta con una soglia che esiste davvero da un'altra parte del progetto -
  la soglia di regime dello spot, il limite di dispersione dell'affidabilita'.

  UNA RAGIONE CHE NON SAPPIAMO NON SI SCRIVE. Se il contesto sinottico non e'
  arrivato, quella riga manca: non diventa "neutro". Uno zero inventato in una
  spiegazione e' peggio che in un calcolo, perche' chi legge lo confronta con la
  propria esperienza e ne conclude che il sito non capisce niente.

A cosa serve davvero: a far vedere le assurdita'. Un numero sbagliato dentro una
previsione e' invisibile; lo stesso numero dentro la frase "il vento in quota
soffia contro l'asse dell'Ora" salta agli occhi di chi conosce il lago.
"""

from . import config
from .util import mean

# Quante ragioni al massimo. Cinque si leggono; dieci sono un rapporto, e un
# rapporto non lo legge nessuno prima di andare in acqua.
MAX_RAGIONI = 5


def verso_pgrad(pg):
    """Cosa spinge un gradiente nord-sud. UN posto solo: la usano la scheda e
    le ragioni, e sono la stessa frase."""
    if pg is None:
        return None
    return ("spinge il Pelèr" if pg > 0.3 else
            "spinge l’Ora" if pg < -0.3 else "neutro")


def _segno_per_regime(valore, regime, soglia=0.3):
    """+1 se quel numero favorisce QUESTO regime, -1 se lo contrasta, 0 se no.

    Il gradiente positivo (pressione piu' alta a nord) spinge verso sud lungo il
    lago, cioe' favorisce il Pelèr; negativo favorisce l'Ora.
    """
    if valore is None or abs(valore) <= soglia:
        return 0
    verso_peler = valore > 0
    return 1 if (verso_peler == (regime == "PELER")) else -1


def ragioni(spot_name, entry, analoghi=None):
    """[(segno, frase)] per una sessione. segno: "+", "-", "" (neutro).

    `entry` e' la riga del prodotto (engine.full_product), quindi porta con se'
    le feature con cui la previsione e' stata fatta: le ragioni non ricalcolano
    niente, leggono.
    """
    spot = config.SPOTS[spot_name]
    regime = spot["regime"]
    f = (entry or {}).get("features") or {}
    out = []

    # 1. Il gradiente nord-sud: il numero che ogni windsurfista del Garda
    #    guarda da trent'anni. Solo se il contesto e' arrivato davvero.
    if f.get("contesto_noto", 1.0) and f.get("pgrad") is not None:
        pg = float(f["pgrad"])
        s = _segno_per_regime(pg, regime)
        if s:
            out.append((1, "+" if s > 0 else "-",
                        "il gradiente nord–sud è di %+.1f hPa e %s"
                        % (pg, verso_pgrad(pg))))
        else:
            out.append((1, "", "il gradiente nord–sud è quasi piatto (%+.1f hPa)" % pg))

    # 2. Il contrasto termico pianura-valle: il motore della brezza. Il verso
    #    non dipende dal regime - il contrasto alimenta entrambi - quindi qui si
    #    dice solo quanto vale, con il segno del motore.
    if f.get("contesto_noto", 1.0) and f.get("tgrad"):
        tg = float(f["tgrad"])
        out.append((2, "+" if tg > 1.0 else "-" if tg < -1.0 else "",
                    "il contrasto termico pianura–valle è di %+.1f °C, "
                    "ed è il motore della brezza" % tg))

    # 3. Il vento in quota rispetto all'ASSE del regime: along925 e' gia'
    #    proiettato sull'asse (features.along_axis), quindi il segno e' la
    #    risposta - concorde o contrario.
    a925 = f.get("along925")
    if a925 is not None and abs(a925) > 1.0:
        out.append((3, "+" if a925 > 0 else "-",
                    "a 925 hPa il vento soffia %s del regime (%.0f kn di "
                    "componente)" % ("lungo l’asse" if a925 > 0 else "contro l’asse", abs(a925))))

    # 4. Notte e sole: il Peler nasce dal raffreddamento notturno, l'Ora dal
    #    riscaldamento del mattino. Le parole del cielo sono quelle della
    #    pagina (sky_words), non una seconda scala.
    if regime == "PELER" and f.get("cloud_cool") is not None:
        cl = float(f["cloud_cool"]) * 100.0
        out.append((4, "+" if cl < 25 else "-" if cl > 55 else "",
                    "nelle ore del raffreddamento il cielo è al %.0f%% di "
                    "nuvolosità" % cl))
    if regime == "ORA" and f.get("rad_pre") is not None:
        rad = float(f["rad_pre"])
        out.append((4, "+" if rad > 0.6 else "-" if rad < 0.25 else "",
                    "il sole della mattina scalda %s (%.0f W/m² medi prima "
                    "della finestra)" % ("bene" if rad > 0.6 else "poco", rad * 500.0)))

    # 5. La pioggia: non e' un dettaglio, e la soglia e' quella con cui la
    #    pagina decide di scrivere "pioggia" (web.sky_words: piu' di 1 mm).
    if (f.get("precip") or 0.0) > 1.0:
        out.append((0, "-", "sono previsti %.0f mm di pioggia nella finestra"
                    % float(f["precip"])))

    # 6. Il vento grezzo dei modelli, prima di qualunque nostra correzione: e'
    #    il riferimento che il nostro modello deve battere, ed e' onesto
    #    mostrarlo accanto al numero che pubblichiamo.
    if f.get("w10_win") is not None and entry.get("speed") is not None:
        w = float(f["w10_win"])
        out.append((7, "", "i modelli, da soli, danno %.0f kn nella finestra; noi "
                    "pubblichiamo %.0f" % (w, float(entry["speed"]))))

    # 7. L'accordo fra i modelli, con la soglia che l'affidabilita' usa
    #    davvero (confidence.MAX_SPREAD_KN), non con un numero nuovo.
    sp = entry.get("spread")
    if sp is not None and entry.get("n_models"):
        from .confidence import MAX_SPREAD_KN
        limite = MAX_SPREAD_KN.get(3)
        if limite:
            out.append((6, "+" if sp <= limite else "-",
                        "i modelli (%d) %s: si discostano di %.1f kn (il limite "
                        "dell’alta affidabilità è %.1f)"
                        % (int(entry["n_models"]),
                           "sono d’accordo" if sp <= limite
                           else "non sono d’accordo", sp, limite)))

    # 8. Gli analoghi: quante delle giornate storicamente piu' simili hanno
    #    davvero dato vento utile. La soglia e' quella dello spot, non una
    #    nuova. Arriva da fuori (chi la calcola sa leggere l'osservato) perche'
    #    qui non si fanno interrogazioni all'archivio.
    if analoghi and analoghi.get("n"):
        out.append((5, "+" if analoghi["sopra"] * 2 >= analoghi["n"] else "-",
                    "delle %d giornate storicamente più simili, %d hanno "
                    "dato almeno %.0f kn" % (analoghi["n"], analoghi["sopra"],
                                             spot["min_kn"])))
    # Il taglio a cinque non sceglie per importanza apparente ma per priorita'
    # dichiarata: la pioggia prima di tutto - e' l'unica che annulla una
    # giornata - poi i due motori, la quota, il cielo, gli analoghi, l'accordo
    # fra i modelli, e per ultimo il vento grezzo.
    out.sort(key=lambda x: x[0])
    return [(segno, frase) for _pr, segno, frase in out[:MAX_RAGIONI]]


def giornate_simili(spot_name, day, lead, osservato=None):
    """{n, sopra, giorni}: quante giornate analoghe hanno superato la soglia.

    Ritorna None dove gli analoghi non sono in uso: a quel punto la riga non si
    scrive, invece di scriverne una vuota. Non e' un secondo previsore - la
    scelta dei vicini resta in analogs, qui si contano i loro esiti.
    """
    from . import analogs, pagella
    spot = config.SPOTS[spot_name]
    if spot.get("place") != "Torbole" or not analogs.promoted():
        return None
    try:
        if int(lead) not in analogs.LEADS:
            return None
        _template, meta = analogs.choose(day, int(lead))
    except Exception:                                  # noqa: BLE001
        return None
    if not meta or not meta.get("days"):
        return None
    picchi = osservato if osservato is not None else pagella.osservato_giornaliero(spot_name)
    esiti = [picchi[g][0] for g in meta["days"] if g in picchi]
    if not esiti:
        return None
    return {"n": len(esiti),
            "sopra": sum(1 for v in esiti if v >= spot["min_kn"]),
            "mediana": mean(esiti),
            "giorni": meta["days"]}
