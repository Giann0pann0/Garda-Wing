import os, sys
os.environ["GARDAWIND_HOME"]="/tmp/gwpatch"
import shutil; shutil.rmtree("/tmp/gwpatch", ignore_errors=True)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from gardawind.sources import malcesine as MC, meteotrentino as MT
from gardawind import config, store, web, engine
ok=lambda c,m: print(("PASS " if c else "FAIL ")+m)
store.init()

ok(config.URL_MALCESINE_LIVE.endswith("index.php"), "la pagina live di Malcesine ora e' index.php")

# testo REALE di index.php catturato dal Mac
page=("dati Dati aggiornati il 13/09/26 alle ore 15.32 Temperatura Vento Precipitazioni "
      "Temperatura: 24.8 °C Umidità: 62 % Percepita: 26 °C Confortevole Estremi Oggi: 24.9°C (14.35) "
      "18.9°C (06.55) Dew Point: 17.2°C Pressione: 1021.7 hPa Velocità attuale: 8.7 kts SW "
      "Media: 7.0 kts Brezza tesa Raffica giornaliera: 13.9 kts Ora Raffica: 13.28 Wind Chill: 24.4°C")
MC.fetch_text = lambda *a, **k: "<html><body>"+page+"</body></html>"
sample, gust_day = MC.fetch_live()
ok(sample[1]==7.0, "media 10 minuti letta: %.1f kn"%sample[1])
ok(sample[3]==225.0, "direzione SW -> 225 gradi (l'Ora a Malcesine)")
ok(sample[0]=="2026-09-13T13:32:00Z", "15:32 locali -> 13:32 UTC (%s)"%sample[0])
ok(gust_day==13.9, "raffica giornaliera separata: %.1f kn"%gust_day)

# messaggio d'errore diagnosticabile
MC.fetch_text = lambda *a, **k: "<html><body>Manutenzione in corso, riprovare</body></html>"
try:
    MC.fetch_live(); ok(False,"doveva fallire")
except Exception as e:
    ok("Manutenzione" in str(e), "l'errore riporta un estratto della pagina: %s"%str(e)[:70])

# archivio Hydstra consegnato anno per anno + ripresa
csv_2013='"Time","T0193",""\n"Date","Vel. Vento (m/s)",""\n00:00:00 05/03/2013,  3.0,  145\n'
csv_2014='"Time","T0193",""\n"Date","Vel. Vento (m/s)",""\n00:00:00 05/03/2014,  4.0,  145\n'
calls=[]
def fake_extract(var, a, b):
    calls.append((var, a, b))
    return csv_2013 if a.startswith("2013") else csv_2014
MT._hydstra_extract = fake_extract
MT._hydstra_userid = lambda: "123"
got=[]
MT.fetch_archive("2013-01-01","2014-12-31", on_year=lambda y,rows,err: got.append((y,len(rows),err)))
ok(got==[(2013,1,None),(2014,1,None)], "consegna anno per anno: %s"%got)
ok(all(c[1][:4]==c[2][:4] for c in calls), "ogni richiesta copre un solo anno")

calls.clear(); got.clear()
MT.fetch_archive("2013-01-01","2014-12-31", on_year=lambda y,rows,err: got.append((y,len(rows),err)), from_year=2014)
ok([g[0] for g in got]==[2014], "ripresa da from_year: scaricato solo %s"%[g[0] for g in got])

# spegnimento
ok("/spegni" in web.Handler.do_GET.__doc__ if web.Handler.do_GET.__doc__ else True, "")
src=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','gardawind','web.py'),encoding='utf-8').read()
ok('u.path == "/spegni"' in src and 'chiudi Garda Wind' in src, "endpoint di spegnimento e link nel piede")
ok('LSUIElement' in open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','mac','Info.plist')).read(), "Info.plist: niente rimbalzo nel Dock")
