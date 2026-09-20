"""Punto d'ingresso.

    python3 -m gardawind                 avvia il cruscotto
    python3 -m gardawind --backfill      scarica gli archivi storici e addestra
    python3 -m gardawind --train         riaddestra dai dati gia' scaricati
    python3 -m gardawind --verify        rimisura la skill dei singoli modelli
    python3 -m gardawind --report        stampa lo stato senza avviare nulla
    python3 -m gardawind --validate      tabella per spot x regime x scadenza
    python3 -m gardawind --bands         confronta i tagli di fascia di scadenza
    python3 -m gardawind --direzioni     da dove viene il vento, per settore
    python3 -m gardawind --raffiche      media, raffica ricorrente, raffica massima
    python3 -m gardawind --orari         quando entra il vento: regime e planata
    python3 -m gardawind --poll-once     legge le centraline una volta ed esce
    python3 -m gardawind --live-json F   legge le centraline e scrive F (solo osservato)
    python3 -m gardawind --addicted [N]  legge addicted-sports (N giorni indietro)
    python3 -m gardawind --nowcast-validazione  valida persistenza intraday senza attivarla
    python3 -m gardawind --analoghi-validazione  valida la forma da analoghi storici
    python3 -m gardawind --confronta-bersaglio   bersaglio: finestra del regime vs utile
    python3 -m gardawind --export DIR    scrive il cruscotto come sito statico
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import webbrowser

from . import analogs, config, engine, indagini, store, web
from .util import local_day, local_hour, parse_dt_any, to_local


def _open_browser(url):
    """Apre il cruscotto nel browser predefinito.

    Su macOS il modulo webbrowser puo' non fare nulla quando il processo non
    e' una vera applicazione con interfaccia (come qui: siamo uno script
    dentro un bundle .app dichiarato LSUIElement). Il comando `open` del
    sistema funziona sempre, quindi si prova prima quello.
    """
    if sys.platform == "darwin" and os.path.exists("/usr/bin/open"):
        try:
            subprocess.Popen(["/usr/bin/open", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass
    try:
        return webbrowser.open(url)
    except Exception:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gardawind", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=config.RUNTIME_PORT)
    ap.add_argument("--backfill", action="store_true",
                    help="scarica gli archivi storici delle centraline e riaddestra")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--validate", action="store_true",
                    help="tabella per spot x regime x scadenza: giorni di prova, "
                         "MAE/bias, Brier e calibrazione, errore di orario, "
                         "riferimenti banali e intervalli bootstrap")
    ap.add_argument("--periodo-comune", action="store_true",
                    help="con --validate: misura tutte le scadenze sugli stessi "
                         "giorni, cosi' le righe sono confrontabili fra loro")
    ap.add_argument("--validate-json", metavar="FILE",
                    help="scrive il dettaglio completo della validazione in FILE")
    ap.add_argument("--spot", metavar="NOME", action="append",
                    help="limita --validate/--bands a uno spot (ripetibile)")
    ap.add_argument("--direzioni", action="store_true",
                    help="istogramma delle provenienze osservate: verifica se "
                         "l'asse del regime e' messo nel posto giusto")
    ap.add_argument("--distribuzione", action="store_true",
                    help="dentro la finestra utile: quanto vento, per quanto, "
                         "per ogni soglia candidata. Serve a scegliere le "
                         "soglie guardando i numeri veri.")
    ap.add_argument("--orari", action="store_true",
                    help="climatologia osservata dell'orario di ingresso: regime "
                         "e planata, con e senza filtro di direzione, per mese")
    ap.add_argument("--raffiche", action="store_true",
                    help="analisi descrittiva di media, raffica ricorrente e "
                         "raffica massima: serve a scegliere le soglie sui dati")
    ap.add_argument("--bands", action="store_true",
                    help="confronta tagli di fascia alternativi sul periodo di "
                         "addestramento")
    ap.add_argument("--poll-once", action="store_true",
                    help="interroga le centraline una volta sola ed esce "
                         "(usato dall'agente di raccolta in background)")
    ap.add_argument("--addicted", nargs="?", const=1, type=int, metavar="GIORNI",
                    help="legge la pagina di addicted-sports per Torbole e "
                         "salva la serie oraria misurata (GIORNI indietro, "
                         "compreso oggi; per difetto 1)")
    ap.add_argument("--addicted-audit", action="store_true",
                    help="sonda l'archivio addicted-sports stazione per "
                         "stazione: periodo, cadenza, buchi, unita', semantica "
                         "di mavg/mmax. Salva il grezzo e non ingerisce niente")
    ap.add_argument("--addicted-censimento", action="store_true",
                    help="cammina l'archivio addicted e conta quante giornate "
                         "complete si riesce davvero a scaricare, per stazione")
    ap.add_argument("--addicted-importa", action="store_true",
                    help="ingerisce i raw addicted gia' scaricati nella tabella "
                         "dedicata addicted_hour; non usa la rete")
    ap.add_argument("--addicted-validazione", action="store_true",
                    help="confronta Addicted con T0193 e segnala le parti sicure "
                         "e quelle che non devono ancora entrare nel modello")
    ap.add_argument("--nowcast-validazione", action="store_true",
                    help="valida persistenza intraday e gate del nowcast senza attivarlo")
    ap.add_argument("--confronta-bersaglio", action="store_true",
                    help="valida il modello con il bersaglio nella finestra del "
                         "regime e in quella utile, uno dopo l'altro")
    ap.add_argument("--analoghi-validazione", action="store_true",
                    help="riproduce la porta della forma analogica Torbole D+1..D+3")
    ap.add_argument("--massimo", type=int, metavar="N",
                    help="limita il censimento alle ultime N richieste "
                         "(per provare senza scaricare dodici anni)")
    ap.add_argument("--stazione", action="append", metavar="SLUG",
                    help="limita l'audit a queste stazioni (ripetibile)")
    ap.add_argument("--live-json", metavar="FILE",
                    help="legge le centraline e scrive SOLO il dato osservato "
                         "in FILE: nessun modello, nessuna previsione. E' il "
                         "processo veloce che tiene aggiornato l'\"adesso\"")
    ap.add_argument("--export", metavar="DIR",
                    help="scrive il cruscotto come pagine statiche in DIR")
    ap.add_argument("--salute", action="store_true",
                    help="dice se quello che il sito mostra e' il risultato di "
                         "questo giro o roba vecchia con una data nuova. Esce "
                         "con 1 se qualcosa non torna: e' il passo che rende il "
                         "pallino verde di GitHub una informazione")
    ap.add_argument("--salva-storico", action="store_true",
                    dest="salva_storico",
                    help="porta le serie irripetibili nei file del progetto")
    ap.add_argument("--recupera-storico", action="store_true",
                    dest="recupera_storico",
                    help="rimette nel database le serie irripetibili dai file")
    ap.add_argument("--ci", action="store_true",
                    help="ciclo completo non interattivo: raccogli, addestra, esporta "
                         "(pensato per girare in cloud senza il Mac acceso)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    store.init()

    if args.report:
        indagini.cmd_report()
        return 0

    if args.validate:
        indagini.cmd_validate(spots=args.spot, out_json=args.validate_json,
                     periodo_comune=args.periodo_comune)
        return 0

    if args.orari:
        indagini.cmd_orari(args.spot[0] if args.spot else None)
        return 0

    if args.distribuzione:
        indagini.cmd_distribuzione(args.spot[0] if args.spot else None)
        return 0

    if args.raffiche:
        indagini.cmd_raffiche(args.spot[0] if args.spot else None)
        return 0

    if args.direzioni:
        indagini.cmd_direzioni(args.spot[0] if args.spot else None)
        return 0

    if args.bands:
        indagini.cmd_bands(args.spot[0] if args.spot else None)
        return 0

    if args.poll_once:
        for line in engine.update_stations():
            print(line)
        return 0

    if args.addicted:
        indagini.cmd_addicted(args.addicted)
        return 0

    if args.addicted_censimento:
        indagini.cmd_addicted_censimento(stazioni=args.stazione, massimo=args.massimo)
        return 0

    if args.addicted_importa:
        indagini.cmd_addicted_importa(stazioni=args.stazione)
        return 0

    if args.nowcast_validazione:
        indagini.cmd_nowcast_validazione()
        return 0

    if args.analoghi_validazione:
        indagini.cmd_analoghi_validazione()
        return 0

    if args.confronta_bersaglio:
        indagini.cmd_confronta_bersaglio()
        return 0

    if args.addicted_validazione:
        indagini.cmd_addicted_validazione()
        return 0

    if args.addicted_audit:
        indagini.cmd_addicted_audit(stazioni=args.stazione)
        return 0

    if args.salute:
        # Sta DOPO il giro, in un passo suo, e non dentro --ci: se facesse
        # uscire --ci con un codice d'errore, il passo che pubblica il sito non
        # partirebbe - e un sito vecchio pubblicato e' meglio di nessun sito,
        # purche' qualcuno lo sappia. Cosi' il sito esce e il pallino diventa
        # rosso: le due cose non sono in conflitto.
        from . import salute as S
        stato = S.stato()
        for riga in S.righe_da_stampare(stato):
            print(riga, flush=True)
        return 0 if stato["ok"] else 1

    if args.live_json:
        # Il processo veloce: legge le centraline e scrive il dato osservato.
        # Separato dalla previsione perche' hanno due tempi diversi - le
        # centraline ogni dieci minuti, i modelli globali ogni sei ore - e
        # finche' stavano insieme il numero dell'"adesso" invecchiava insieme
        # alla previsione, dicendo "adesso" quando erano passate cinque ore.
        from . import live as live_mod
        # SOLO le letture che servono all'adesso: vedi
        # engine.aggiorna_centraline_vive. Qui si chiamava update_stations, che
        # scarica anche le serie orarie e le previsioni altrui - otto richieste
        # ogni dieci minuti invece di tre, alle due fonti da cui dipende tutto.
        for line in engine.aggiorna_centraline_vive():
            print(line)
        dati = live_mod.scrivi(args.live_json)
        # E accanto, i campioni del canale vivo: e' l'unico modo perche'
        # arrivino al processo lento, che ha un database suo. Vedi
        # archivio.scrivi_vivo_recente.
        from . import archivio
        import os as _os
        vivo = _os.path.join(_os.path.dirname(_os.path.abspath(args.live_json)),
                             "vivo.csv.gz")
        try:
            print("  scritti %d campioni del canale vivo in %s"
                  % (archivio.scrivi_vivo_recente(vivo), vivo))
        except archivio.PonteNonLetto as e:
            # Il file pubblicato non si e' letto, quindi non si riscrive: un
            # ponte piu' corto e' peggio di un ponte vecchio. Il passo che
            # pubblica il ramo aggiunge vivo.csv.gz solo se c'e'.
            if _os.path.exists(vivo):
                _os.remove(vivo)
            print("  canale vivo: il file pubblicato non si e' potuto leggere "
                  "(%s), quindi NON lo riscrivo piu' corto: riprovo al prossimo "
                  "giro" % e)
        except Exception as e:                    # noqa: BLE001
            print("campioni vivi: errore non fatale (%s: %s)" % (type(e).__name__, e))
        for nome, v in sorted(dati["luoghi"].items()):
            print("  %-10s %s  vento %s kn  raffica %s  ricorrente %s (%s)"
                  % (nome, v["ts"] or "-",
                     "-" if v["wind"] is None else "%.1f" % v["wind"],
                     "-" if v["gust"] is None else "%.1f kn" % v["gust"],
                     "-" if v["gust_rec"] is None else "%.1f kn" % v["gust_rec"],
                     v["gust_rec_stato"]))
        print("scritto %s" % args.live_json)
        # E gli avvisi, dallo stesso giro: la misura e' appena stata fatta.
        #
        # Dentro un try che non lascia passare niente, di proposito: il file
        # e' GIA' scritto qui sopra, e il passo successivo del flusso lo
        # pubblica. Se un errore negli avvisi facesse uscire il comando con
        # un codice diverso da zero, il passo di pubblicazione non
        # partirebbe, e il sito resterebbe con il dato vecchio per colpa di
        # un messaggio Telegram. L'errore si stampa, cosi' si vede nel
        # registro, ma non ferma la pubblicazione di una misura buona.
        try:
            from . import avvisi
            for line in avvisi.esegui():
                print(line)
        except Exception as e:                    # noqa: BLE001
            print("avvisi: errore non fatale (%s: %s)" % (type(e).__name__, e))
        return 0

    if args.ci:
        from . import archivio, export as exporter
        print("Ciclo completo non interattivo.", flush=True)
        # PRIMA di tutto: rimettere nel database quello che sta nei file del
        # progetto e nel database non c'e'. Se la cache di GitHub e' stata
        # sfrattata, il ciclo riparte da un database vuoto - e queste tre
        # serie non si riscaricano da nessuna parte. Qui tornano a posto.
        for f, n in archivio.recupera():
            print("  ripreso da %s: %d righe" % (f, n), flush=True)
        # I campioni a dieci minuti li raccoglie il processo veloce, che ha un
        # database suo: qui si rileggono dal ramo dove li pubblica.
        try:
            print("  campioni dal canale vivo pubblicato: %d"
                  % archivio.leggi_vivo_pubblicato(), flush=True)
        except Exception as e:                    # noqa: BLE001
            print("  campioni pubblicati non letti (%s: %s) - si riprova al "
                  "prossimo giro" % (type(e).__name__, str(e)[:80]), flush=True)
        engine.update_cycle(force=False, deep=True)
        for line in engine.backfill_station_history(
                force=False, on_progress=lambda m: print(m, flush=True)):
            print("  " + line, flush=True)
        for r in engine.train_all():
            print("  " + json.dumps(r, default=str, ensure_ascii=False), flush=True)
        # La forma analogica non entra nel sito per semplice presenza del codice:
        # il database cloud deve riprodurre il blocco cieco validato.
        ar = analogs.validation_report()
        opened, reasons, _ = analogs.promote_from_validation(ar)
        print("  analoghi: PORTA %s%s" %
              ("APERTA" if opened else "CHIUSA",
               "" if opened else " - " + "; ".join(reasons or [str(ar.get("diagnostic") or ar.get("reason"))])),
              flush=True)
        target = args.export or "site"
        for path in exporter.export(target):
            print("  scritto " + path, flush=True)
        # E alla fine, DOPO aver costruito il sito: le serie irripetibili
        # escono dalla cache e vanno nei file del progetto, che git tiene per
        # sempre. Non si rimpiccioliscono mai: vedi archivio.py.
        #
        # L'ordine non e' estetico. Le curve che pubblichiamo nascono DENTRO la
        # costruzione del sito (engine.by_day -> store.save_issued_profile):
        # archiviando prima, ogni giro salvava le curve del giro PRECEDENTE e
        # mai le proprie. Le piu' recenti restavano nella sola cache di
        # Actions - cioe' esattamente nel posto da cui questo archivio serve a
        # metterle al sicuro.
        # PRIMA di esportare: e' l'unico momento in cui sul disco c'e' quello
        # che git ha davvero. Un attimo dopo, esporta() riscrive quei file dal
        # database e la loro data diventa "adesso" qualunque cosa sia successo
        # al push - cioe' il controllo sull'archivio direbbe sempre di si'.
        from . import salute as S
        _curva_di_git = S.ultima_curva_nei_file()
        for path, n, nuove in archivio.esporta():
            if nuove:
                print("  archivio %s: %d righe (+%d)" % (path, n, nuove), flush=True)
        for riga in S.righe_da_stampare(S.stato(ultima_curva=_curva_di_git)):
            print(riga, flush=True)
        if engine.STATE["errors"]:
            print("Errori durante il ciclo:", flush=True)
            for e in engine.STATE["errors"]:
                print("  " + e, flush=True)
        return 0

    if args.export:
        from . import export as exporter
        for path in exporter.export(args.export):
            print("scritto " + path)
        return 0

    if args.backfill:
        print("Scarico gli archivi storici delle centraline…")
        for line in engine.backfill_station_history(
                force=True, on_progress=lambda m: print(m, flush=True)):
            print("  " + line)
        print("Scarico i predittori storici…")
        for line in engine.backfill_archive_features():
            print("  " + line)
        print("Scarico la rianalisi ERA5 (piu' anni, sola superficie)…")
        for line in engine.backfill_era5_features():
            print("  " + line)
        print("Scarico i predittori per scadenza (run precedenti)…")
        for line in engine.backfill_lead_features():
            print("  " + line)
        print("Addestro…")
        for r in engine.train_all():
            print("  " + json.dumps(r, default=str, ensure_ascii=False))
        return 0

    if args.salva_storico:
        from . import archivio
        for path, n, nuove in archivio.esporta():
            print("%-52s %7d righe (+%d)" % (path, n, nuove))
        return 0

    if args.recupera_storico:
        from . import archivio
        for f, n in archivio.recupera():
            print("ripreso da %s: %d righe" % (f, n))
        return 0

    if args.verify:
        print("Verificati %d accoppiamenti modello/scadenza" % engine.verify_all())
        return 0

    if args.train:
        for r in engine.train_all():
            print(json.dumps(r, default=str, ensure_ascii=False))
        return 0

    httpd = web.serve(args.port)
    threading.Thread(target=engine.poller_loop, daemon=True).start()
    engine.ensure_update(False)
    url = "http://127.0.0.1:%d/" % args.port
    print("%s %s in ascolto su %s" % (config.APP_NAME, config.APP_VERSION, url), flush=True)
    if not args.no_browser:
        _open_browser(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
