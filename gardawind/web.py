"""Cruscotto locale.

Due schermate:
  /              quello che serve per decidere se andare in acqua
  /diagnostica   quanto sbaglia il modello, misurato su dati mai visti

La seconda esiste perche' la prima sia credibile. Un numero senza un errore
dichiarato e' un'opinione.

L'impaginazione e' PER GIORNO, non per luogo: si sceglie prima quando andare
e poi dove. Dentro ogni giorno le sessioni sono in ordine di orologio:
prima il Peler, che e' un vento di mattina, poi l'Ora, che e' di pomeriggio.
"""

import html
import json
import math
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import (config, confidence, engine, giudizio, orari, store,
               verify)
from .util import (angle_diff, clamp, curva_monotona, local_day,
                   parse_dt_any, sampling_cadence, sustained_onset,
                   time_above, to_local, utc_now)

E = html.escape

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------
# Le due serie (Torbole / Malcesine) sono identita', non grandezze: colore
# categorico, assegnato una volta e mai riciclato. Coppia verificata con il
# validatore sulle superfici effettive di questa pagina:
#   chiaro  #2a78d6 / #eb6834 su #ffffff  -> tutti i controlli superati
#   scuro   #3987e5 / #d95926 su #161b22  -> tutti i controlli superati
# Lo sfondo marino sta sul piano della PAGINA, non sulla superficie dei
# grafici: le schede restano neutre, e la validazione resta valida.

CSS = """
/* Un tema solo, scuro. Non e' una preferenza estetica: la pagina si guarda in
   spiaggia all'alba e al tramonto, e un fondo chiaro a quell'ora e' una torcia
   in faccia. Committiamo al buio e lo dipingiamo bene, invece di mantenere due
   temi e curarne male entrambi.

   L'aspetto viene dal mockup di Gian (2026-09-18): un tramonto sul lago in
   testa, tutto il resto su schede scure semitrasparenti. La foto non c'e' -
   non e' nostra - al suo posto c'e' un cielo disegnato in vettoriale, che
   pesa due kilobyte e non ha diritti. */
:root{
  color-scheme:dark;
  --bg-1:#0a121c; --bg-2:#0d1826; --bg-3:#070e16;
  --card:#101a26; --card-2:#16222f; --card-3:#1b2937;
  --vetro:rgba(11,20,31,.78);
  --ink:#eef4fa; --ink-2:#a7b8ca; --ink-3:#74879e;
  --line:#22323f; --grid:#1a2734; --axis:#33455a;

  /* Identita' delle localita': colore categorico, assegnato una volta e mai
     riciclato. Validati col validatore sui sei controlli su questa superficie
     (#101a26), modalita' scura: tutti PASS.
       Torbole  #2e86e0   Malcesine #de7326 */
  --s1:#2e86e0; --s2:#de7326;
  --s1-soft:#1b3f63; --s2-soft:#4a2a12;
  --s1-glow:rgba(46,134,224,.22); --s2-glow:rgba(222,115,38,.20);
  --pc:var(--s1); --pc-soft:var(--s1-soft); --pc-glow:var(--s1-glow);

  /* La raffica non e' una terza localita': e' una seconda misura dello stesso
     posto. Ha un colore suo perche' compare in ogni grafico e deve dire sempre
     la stessa cosa, ma la distinzione dalla media NON dipende dal colore:
     tratteggio piu' etichetta diretta. */
  --gust:#e0559b;

  /* Stati: riservati, mai riusati per una serie, sempre con la parola scritta. */
  --good:#35c97a; --warn:#f0b429; --crit:#f2564d; --big:#5ad2ff;
  --accento:#4fd3ff;

  --shadow:0 1px 2px rgba(0,0,0,.55),0 14px 38px rgba(0,0,0,.45);
  --raggio:16px;
}
body.p2{--pc:var(--s2); --pc-soft:var(--s2-soft); --pc-glow:var(--s2-glow)}
/* Campione: terza localita', terzo colore, assegnato una volta. */
body.p3{--pc:#9b6fe0; --pc-soft:#3a2a5e; --pc-glow:rgba(155,111,224,.22)}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
img{max-width:100%}
[hidden]{display:none!important}
body{
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  color:var(--ink);
  background:linear-gradient(180deg, var(--bg-1) 0%, var(--bg-2) 40%, var(--bg-3) 100%);
  min-height:100vh;
  -webkit-font-smoothing:antialiased;
}
.display,.titolo,.nowbig .v,.gcard .gk,.rq-v,.rq-kn{
  font-family:"Avenir Next","Avenir",Futura,"Gill Sans","Trebuchet MS",system-ui,sans-serif;
}
a{color:var(--s1)}
.wrap{max-width:1040px;margin:0 auto;padding-left:16px;padding-right:16px}

/* ---------------- la testa: il cielo, il nome, le localita' ---------------- */
header.hero{position:relative;overflow:hidden;padding:14px 0 26px;min-height:300px;
  display:flex;align-items:flex-end;background:#0a121c}
header.hero>.wrap{width:100%;display:flex;flex-direction:column;min-height:260px;
  justify-content:space-between}
/* Con la foto: coperta e centrata, e un velo scuro in basso perche' il
   titolo e la striscia dell'adesso restino leggibili su qualunque cielo. */
header.hero.foto{background:#0a121c url(sfondo.jpg) center/cover no-repeat;min-height:360px}
header.hero.foto::after{content:"";position:absolute;inset:auto 0 0 0;height:55%;
  background:linear-gradient(180deg,transparent,rgba(7,14,22,.75))}
header.hero.foto>.wrap{z-index:1}
header.hero .cielo{position:absolute;inset:0;width:100%;height:100%;display:block}
header.hero .wrap{position:relative}
.hbar{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.live{font-size:12.5px;color:var(--ink-2);display:inline-flex;align-items:center;gap:7px;
  text-shadow:0 1px 2px rgba(0,0,0,.6)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--good);flex:none}
.dot.warn{background:var(--warn)}.dot.bad{background:var(--crit)}
/* Le localita' come pillole. Aggiungerne una e' una riga di config: qui non
   si tocca niente, e per questo la navigazione non puo' restare indietro. */
.luoghi{display:flex;gap:8px}
.luoghi a{padding:8px 18px;border-radius:12px;font-size:15px;font-weight:700;
  text-decoration:none;color:var(--ink);background:rgba(12,22,34,.55);
  border:1px solid rgba(255,255,255,.12);backdrop-filter:blur(6px)}
.luoghi a[aria-current="page"]{background:var(--pc);border-color:transparent;color:#fff}
.titolo{margin:26px 0 0;font-size:64px;line-height:1;font-weight:800;letter-spacing:-.03em;
  color:#fff;text-shadow:0 2px 14px rgba(0,0,0,.45)}
.titolo em{font-style:normal;color:var(--accento)}
.tag{margin:8px 0 0;font-size:19px;color:#dbe7f3;text-shadow:0 1px 6px rgba(0,0,0,.5)}

/* ---------------- adesso: una striscia di cinque celle ---------------- */
.adesso{margin-top:-18px;position:relative;z-index:1}
.costruita{margin:10px 2px 0;font-size:12px;color:var(--ink-3);line-height:1.45}
.costruita b{color:var(--ink-2);font-weight:600}
.nowblock{background:var(--vetro);border:1px solid var(--line);border-radius:var(--raggio);
  padding:10px 14px;box-shadow:var(--shadow);backdrop-filter:blur(10px)}
.nowobs,.nowstrip{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}
.nowobs{grid-template-columns:repeat(4,1fr);grid-column:1/5}
.cella{display:flex;align-items:center;gap:10px;min-width:0;padding:4px 8px 4px 0;
  border-right:1px solid var(--line)}
.cella:last-child,.nowstrip>.cella:last-child{border-right:0}
.cella .ic{flex:none;width:30px;height:30px;color:var(--ink-2)}
.cella .ic svg{width:100%;height:100%;display:block}
.cella>span:not(.ic){display:grid;min-width:0}
.cella .k{font-size:12px;color:var(--ink-2);line-height:1.2;white-space:nowrap}
.cella .v{font-size:22px;font-weight:800;line-height:1.15;color:var(--ink);
  font-variant-numeric:tabular-nums;white-space:nowrap}
.cella .v small{font-size:13px;font-weight:600;color:var(--ink-2)}
.nowbig .v{color:var(--ink)}
.nowmeta.stale .v,.nowmeta.stale .k{color:var(--warn)}
.novalue{font-size:16px;color:var(--ink-3);grid-column:1/-1;padding:6px 0}

/* ---------------- i cinque giorni ---------------- */
.giorni{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:14px 0 14px}
.gcard{appearance:none;font:inherit;color:inherit;cursor:pointer;text-align:center;
  background:var(--vetro);border:1px solid var(--line);border-radius:14px;
  padding:10px 4px 10px;display:grid;gap:1px;justify-items:center;
  transition:border-color .15s,background .15s}
.gcard:hover{border-color:var(--axis)}
.gcard[aria-current="true"]{border-color:var(--warn);box-shadow:0 0 0 1px var(--warn) inset}
.gcard .gg{font-size:13px;font-weight:700;text-transform:capitalize}
.gcard .gd{font-size:12px;color:var(--ink-2);font-variant-numeric:tabular-nums}
.gcard .gk{font-size:19px;font-weight:800;margin-top:4px}
.gcard .gk small{font-size:11px;color:var(--ink-2);font-weight:600}
/* Il voto e' una pillola piena: la parola c'e' sempre, il colore la rafforza. */
.gv,.pill{display:inline-block;margin-top:6px;padding:2px 10px;border-radius:8px;
  font-size:12px;font-weight:800;text-transform:capitalize;color:#0b1119;
  background:var(--ink-3)}
.pill{margin:0}
/* Il colore del testo sta QUI, nelle regole a due classi: piu' sotto .q-go
   da solo colora il testo di verde, e verde su verde e' una pillola vuota -
   e' successo. */
.q-no.gv,.q-no.pill{background:var(--crit);color:#fff}
.q-meh.gv,.q-meh.pill{background:var(--warn);color:#0b1119}
.q-go.gv,.q-go.pill{background:var(--good);color:#0b1119}
.q-big.gv,.q-big.pill{background:var(--big);color:#0b1119}
.q-off.gv,.q-off.pill{background:var(--card-3);color:var(--ink-2)}

/* ---------------- i due riquadri, identici ---------------- */
.rqgrid{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:stretch}
.rq{background:var(--vetro);border:1px solid var(--line);border-radius:var(--raggio);
  padding:14px 16px 14px;box-shadow:var(--shadow);display:flex;flex-direction:column;
  backdrop-filter:blur(10px)}
.rq-h{display:flex;justify-content:space-between;align-items:center;gap:10px}
.rq-t{font-size:22px;font-weight:800;letter-spacing:.02em;color:var(--ink)}
.rq-t span{color:var(--ink-2);font-weight:500;font-size:16px;letter-spacing:0}
.rq-b{display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:start;margin-top:12px}
.anello{display:grid;justify-items:center;gap:4px;font-size:12px;color:var(--ink-2)}
.anello svg{display:block}
.anello text{font-size:20px}
.rq-v{display:none}
.rq-kn{font-size:30px;font-weight:800;line-height:1.05;color:var(--ink);
  font-variant-numeric:tabular-nums;white-space:nowrap}
.rq-kn small{font-size:11px;color:var(--ink-2);font-weight:600;letter-spacing:.04em;
  text-transform:uppercase}
.rq-kn b{font-weight:800}.rq-kn b+small{margin:0 10px 0 4px}
.rq-d{margin:10px 0 0;display:grid;gap:7px;font-size:13.5px}
.rq-d div{display:flex;align-items:center;gap:9px}
.rq-d .ic{width:20px;height:20px;color:var(--ink-2);flex:none}
.rq-d .ic svg{width:100%;height:100%;display:block}
.rq-d dt{color:var(--ink-2);margin:0;flex:1}
.rq-d dd{margin:0;color:var(--ink);font-variant-numeric:tabular-nums;font-weight:700}
.rq-n{margin:8px 0 0;font-size:12px;color:var(--ink-3)}
.q-no{color:var(--crit)}.q-meh{color:var(--warn)}
.q-go{color:var(--good)}.q-big{color:var(--big)}.q-off{color:var(--ink-3)}
.rq.rq-off .rq-v{display:block;color:var(--ink-3);font-size:22px;margin-top:8px}

/* ---------------- la riga del meglio ---------------- */
.meglio{margin:14px 0 0;padding:12px 16px;display:flex;align-items:center;gap:12px;
  font-size:16px;color:var(--ink);line-height:1.4;border-radius:14px;
  border:1px solid currentColor;background:var(--vetro)}
.meglio .ic{width:26px;height:26px;flex:none}
.meglio .ic svg{width:100%;height:100%;display:block}
.meglio .tx{flex:1;color:var(--ink)}
.meglio .tx b{color:currentColor}
.meglio.no{color:var(--ink-3)}
.meglio.q-no{color:var(--crit)}.meglio.q-meh{color:var(--warn)}
.meglio.q-go{color:var(--good)}.meglio.q-big{color:var(--big)}

/* ---------------- il grafico, che e' il pezzo grosso ---------------- */
.grafico{margin-top:14px;background:var(--vetro);border:1px solid var(--line);
  border-radius:var(--raggio);padding:14px 14px 12px;box-shadow:var(--shadow)}
.gtesta{display:flex;justify-content:space-between;align-items:center;gap:12px;
  flex-wrap:wrap;margin-bottom:6px}
.gtesta h2{margin:0;font-size:20px;font-weight:800;letter-spacing:-.01em}
svg.chart{display:block;width:100%;height:auto;
  /* Le scritte del grafico in unita' di viewBox: su schermo grande il disegno
     e' scalato 2,4 volte, quindi il numero va ridotto della stessa quantita'
     perche' la scritta arrivi all'occhio della misura giusta. Un font scelto
     per il telefono, su desktop diventa un titolo. */
  --fs-xs:10; --fs-s:11; --fs-m:12.5}
@media (min-width:760px){svg.chart{--fs-xs:5.4; --fs-s:5.9; --fs-m:6.8}}
svg.chart .t-xs{font-size:calc(var(--fs-xs) * 1px)}
svg.chart .t-s{font-size:calc(var(--fs-s) * 1px)}
svg.chart .t-m{font-size:calc(var(--fs-m) * 1px)}
.chartwrap{position:relative}
.tip{position:absolute;pointer-events:none;opacity:0;transition:opacity .12s;
  background:var(--card-3);border:1px solid var(--line);border-radius:10px;padding:7px 10px;
  font-size:12px;box-shadow:var(--shadow);white-space:nowrap;z-index:3;color:var(--ink)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;color:var(--ink-2)}
.legend i{display:inline-block;width:18px;height:0;border-top:3px solid currentColor;
  margin-right:6px;vertical-align:middle}
.legend i.dash{border-top-style:dashed}
.legend i.box{height:11px;width:14px;border:0;border-radius:3px;vertical-align:-1px}
.scarto{margin:10px 0 0;font-size:13.5px;color:var(--ink-2);line-height:1.5}
.scarto b{color:var(--ink)}
details.tbl{margin-top:10px;font-size:13px}
details.tbl summary{cursor:pointer;color:var(--ink-3);font-size:12px}
details.tbl .scroller{overflow-x:auto}
.snote{font-size:12px;color:var(--warn);margin:10px 0 0;line-height:1.4}

/* ---------------- il cassetto dei dettagli ---------------- */
.dettagli{margin:14px 0 10px;background:var(--vetro);border:1px solid var(--line);
  border-radius:var(--raggio);padding:0 16px}
.dettagli summary{cursor:pointer;font-size:18px;font-weight:800;padding:14px 0;
  list-style:none;display:flex;justify-content:space-between;align-items:center}
.dettagli summary::-webkit-details-marker{display:none}
.dettagli summary::after{content:"";width:10px;height:10px;border-right:2px solid var(--ink-2);
  border-bottom:2px solid var(--ink-2);transform:rotate(45deg);margin-right:6px;
  transition:transform .15s}
.dettagli[open] summary::after{transform:rotate(-135deg)}
.dcont{padding:0 0 14px;max-width:66ch}
.dcont h3{margin:16px 0 2px;font-size:13.5px;color:var(--ink)}
.dcont p,.dcont li{color:var(--ink-2);font-size:13px;line-height:1.55;margin:4px 0 8px}
.dcont ul{margin:4px 0 8px;padding-left:18px}
.dcont b{color:var(--ink)}

/* ---------------- pannelli della diagnostica ---------------- */
.panel{background:var(--card);border-radius:20px;padding:18px;margin-bottom:18px;
  box-shadow:var(--shadow);border:1px solid var(--line)}
.panel h2{margin:0 0 8px;font-size:20px}
.panel h3{margin:18px 0 2px;font-size:13.5px}
.panel p{color:var(--ink-2);font-size:13px;margin:6px 0 10px}
.empty{padding:40px 10px;text-align:center;color:var(--ink-3)}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0 16px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-3);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.good{color:var(--good);font-weight:600}.bad{color:var(--crit);font-weight:600}
.cf{display:inline-flex;align-items:center;gap:6px;border-radius:999px;
  padding:3px 10px;font-size:12.5px;font-weight:800}
.cf::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor;flex:none}
.cf-alta{background:color-mix(in srgb,var(--good) 16%,transparent);color:var(--good)}
.cf-buona{background:color-mix(in srgb,var(--s1) 18%,transparent);color:var(--s1)}
.cf-tend{background:color-mix(in srgb,var(--warn) 18%,transparent);color:var(--warn)}
.cf-out{background:color-mix(in srgb,var(--ink-3) 16%,transparent);color:var(--ink-2)}
.cfline{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:6px}
.cf-why{font-size:12.5px;color:var(--ink-3)}
footer{padding-block:18px 40px;font-size:12px;color:var(--ink-3);text-align:center}
footer a{color:var(--ink-2)}

@media (max-width:700px){
  .wrap{padding-left:12px;padding-right:12px}
  header.hero{padding-bottom:18px}
  .luoghi a{padding:7px 13px;font-size:14px}
  .titolo{font-size:42px;margin-top:18px}
  .tag{font-size:15px}
  .nowstrip{grid-template-columns:repeat(3,1fr)}
  .nowobs{grid-template-columns:repeat(3,1fr);grid-column:1/-1}
  .nowobs .cella:nth-child(4){grid-column:1/3}
  .cella{border-right:0;padding-right:0}
  .cella .v{font-size:19px}
  .cella .ic{width:24px;height:24px}
  .giorni{gap:5px;margin:12px 0 12px}
  .gcard{padding:8px 2px 9px;border-radius:12px}
  .gcard .gg{font-size:11px}
  .gcard .gd{font-size:10.5px}
  .gcard .gk{font-size:16px;margin-top:3px}
  .gv{font-size:10px;padding:2px 6px}
  .rqgrid{grid-template-columns:1fr;gap:10px}
  .rq{padding:12px 12px 12px}
  .rq-t{font-size:19px}.rq-t span{font-size:14px}
  .rq-kn{font-size:26px}
  .rq-d{font-size:12.5px}
  .meglio{font-size:14px;padding:10px 12px}
  .grafico{padding:10px 6px 10px}
  .gtesta h2{font-size:17px;padding-left:6px}
  .legend{font-size:11.5px;gap:10px;padding-left:6px}
  .panel{padding:14px;border-radius:16px}
}
"""

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]

SOURCE_LABEL = {
    "appreso": "modello addestrato sullo storico della centralina",
    "misto": "probabilità addestrata, intensità ancora dalla stima fisica",
    "prior": "stima fisica di partenza, non ancora calibrata sui dati",
}

# Quali fonti meritano un avviso in home. "appreso" no: e' il caso normale, e
# scriverlo sarebbe rumore. Le altre due si', perche' il numero grande sullo
# schermo in quel caso NON e' calibrato sui dati di quella centralina, e chi
# guarda ha il diritto di saperlo prima di decidere se caricare la macchina.
# Non e' un dettaglio tecnico da mandare in diagnostica: e' un'avvertenza.
FONTI_DA_DICHIARARE = ("prior", "misto")


# --------------------------------------------------------------------------
# Pezzi riutilizzabili
# --------------------------------------------------------------------------

def day_title(day, lead):
    """Titolo del giorno in italiano, senza sigle.

    Niente D+1 / D+3: la scadenza si dice come la si dice a voce. Il giorno
    della settimana resta accanto, perche' "tra 5 giorni" e' comodo per capire
    la distanza e inutile per capire se e' sabato.
    """
    dt = parse_dt_any(day + " 12:00:00")
    return (confidence.lead_label(lead),
            "%s %d %s" % (GIORNI[dt.weekday()], dt.day, MESI[dt.month - 1]))


# Quanto ci si puo' fidare, in una parola sola e con un colore. L'etichetta non
# viene dalla scadenza ma dalle misure fatte a quella scadenza su quello spot:
# due giorni identici sul calendario possono meritare due etichette diverse.
CONF_CLASS = {3: "cf-alta", 2: "cf-buona", 1: "cf-tend", 0: "cf-out"}


def confidence_badge(val, compact=False):
    if not val:
        return ""
    cls = CONF_CLASS.get(val["livello"], "cf-out")
    label = val["etichetta"]
    title = val.get("motivo") or val.get("uso") or ""
    if compact:
        return ('<span class="cf %s" title="%s">%s</span>'
                % (cls, E(title), E(label[0].upper() + label[1:])))
    extra = ('<span class="cf-why">%s</span>'
             % E(val.get("motivo") or val.get("uso") or "")) if title else ""
    return ('<div class="cfline"><span class="cf %s">%s</span>%s</div>'
            % (cls, E(label[0].upper() + label[1:]), extra))


def hhmm(minutes, step=10):
    """Minuti dalla mezzanotte -> HH:MM, arrotondati al passo.

    L'arrotondamento non e' estetica: scrivere 08:07 suggerirebbe una
    precisione al minuto che l'interpolazione di un profilo orario non ha. Il
    passo di default e' dieci minuti; gli estremi della finestra di ingresso
    usano cinque, perche' vengono da un quantile misurato e non da
    un'interpolazione, e con dieci un intervallo simmetrico si sbilancia.
    Mezzo passo si arrotonda sempre verso l'alto: il round di Python va al
    pari piu' vicino, e su una coppia di estremi si vedeva.
    """
    m = int(math.floor(clamp(minutes, 0.0, 24 * 60 - 1) / float(step) + 0.5) * step)
    return "%02d:%02d" % (m // 60, m % 60)


def timing_badge(val):
    """La seconda voce della scheda: l'orario, separato dalla prima."""
    if not val:
        return ""
    return ('<span class="tm tm-%d">Timing: <b>%s</b>%s</span>'
            % (val["livello"], E(val["etichetta"]),
               (" · ±%d min" % round(val["minuti"])) if val.get("minuti") else ""))


def compass(deg):
    if deg is None:
        return ""
    names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]
    return names[int((deg % 360) / 22.5 + 0.5) % 16]


def arrow(deg, size=24, color="currentColor"):
    """Freccia che punta dove VA il vento, ruotata dalla sua provenienza."""
    if deg is None:
        return ""
    return ('<svg width="%d" height="%d" viewBox="0 0 24 24" aria-hidden="true" '
            'style="flex:none"><g transform="rotate(%.0f 12 12)">'
            '<path d="M12 3 L12 21 M12 21 L7.6 15.6 M12 21 L16.4 15.6" fill="none" '
            'stroke="%s" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>'
            '</g></svg>' % (size, size, (deg or 0) % 360, color))


def verdict_chip(grade, speed, prob):
    if prob is not None and prob < 0.25:
        cls = "no"
    elif speed >= 23:
        cls = "big"
    elif speed >= 16:
        cls = "go"
    elif speed >= 12:
        cls = "ok"
    elif speed >= 9:
        cls = "meh"
    else:
        cls = "no"
    mark = {"go": "✓", "big": "!", "ok": "~", "meh": "~", "no": "✕"}[cls]
    return '<span class="chip %s">%s %s</span>' % (cls, mark, E(grade))


# --------------------------------------------------------------------------
# Home: una sezione per luogo, il grafico prima di ogni card
# --------------------------------------------------------------------------

# Quali regimi ha un luogo. Solo i modelli orari: quello della raffica di
# giornata (Malcesine-Giorno) e' un'altra grandezza - un picco, non una media -
# e teneva in fondo alla pagina un riquadro che diceva la stessa cosa con
# numeri non confrontabili. Vive in diagnostica, dove il confronto e' il punto.
def place_spots(place):
    out = {}
    for name in config.SPOT_ORDER:
        spot = config.SPOTS[name]
        if spot["place"] == place and spot["target"] == "hourly":
            out[spot["regime"]] = name
    return out


META_REGIME = [("PELER", "Pel\u00e8r", "mattina"), ("ORA", "Ora", "pomeriggio")]


def live_regime_state(live, spot, today=False):
    """Stato OSSERVATO del regime attivo, solo se il campione e' fresco.

    Non e' un nowcast e non sposta la curva futura - quel banco e' chiuso, il
    guadagno contro la persistenza non passa la porta. Serve soltanto a
    evitare una contraddizione di prodotto: se alle 16:40 la centralina misura
    17 kn di Ora, la card di oggi non puo' continuare a dire "discreto"
    perche' la previsione emessa stanotte era piu' bassa.

    Per attribuire il campione a un regime servono TUTTE le condizioni:
    giorno odierno, dato fresco, ora dentro la finestra di quel regime, e
    direzione dentro il settore osservato. Diciassette nodi da nord non
    diventano "Ora buona" - sarebbero un'altra cosa con lo stesso numero.
    """
    if not today or not live or live.get("wind") is None:
        return None
    age = live.get("age_min")
    if age is not None and age > ETA_STANTIA_MIN:
        return None
    dt = parse_dt_any(live.get("ts") or "")
    if dt is None:
        return None
    loc = to_local(dt)
    ora = loc.hour + loc.minute / 60.0
    h0, h1 = spot["window"]
    if ora < h0 or ora >= h1 + 1:
        return None
    direzione = live.get("dir")
    if direzione is None:
        return None
    if angle_diff(float(direzione), float(spot["axis_obs"])) > config.REGIME_SECTOR_DEG:
        return None
    vento = float(live["wind"])
    if vento >= spot["planing_kn"]:
        cls, word = "go", "Buono"
    elif vento >= spot["min_kn"]:
        cls, word = "meh", "Discreto"
    else:
        cls, word = "no", "Scarso"
    return {"wind": vento, "cls": cls, "word": word, "hour": ora}


def quality(data, spot, live=None, today=False):
    """Tre livelli, una parola ciascuno, piu' il colore.

    La soglia non e' estetica: "Scarso" vuol dire che il vento non arriva a
    quello che noi stessi chiamiamo "regime entrato", oppure che la probabilita'
    e' cosi' bassa che l'intensita' e' condizionata a un evento che non capita.
    "Buono" richiede DUE cose insieme: sopra la soglia di planata e una
    probabilita' che regga. Fra i due c'e' tutto il resto, che e' "Discreto".

    Oggi, e solo oggi, il dato misurato ha la precedenza: una previsione
    emessa stanotte non puo' smentire un anemometro che sta misurando adesso.
    """
    misurato = live_regime_state(live, spot, today)
    if misurato:
        return misurato["cls"], misurato["word"]
    if not data:
        return "off", "\u2014"
    prob, speed = data.get("prob") or 0.0, data.get("speed") or 0.0
    if prob < 0.35 or speed < spot["min_kn"]:
        return "no", "Scarso"
    if speed >= spot["planing_kn"] and prob >= 0.55:
        return "go", "Buono"
    return "meh", "Discreto"


RING_WORD = {3: "Alta", 2: "Buona", 1: "Tendenza", 0: "Outlook"}
RING_COLOR = {3: "var(--good)", 2: "var(--s1)", 1: "var(--warn)", 0: "var(--ink-3)"}


def reliability_ring(conf, size=54):
    """Quattro tacche, non una percentuale.

    Il riferimento grafico mostrava "80%". Non lo scriviamo, perche' non
    esiste: quello che misuriamo e' se il modello batte i riferimenti banali a
    quella scadenza, non la probabilita' che la previsione sia giusta. Un
    numero col segno di percentuale verrebbe letto come la seconda cosa.
    Quattro tacche piene su quattro dicono quanto sappiamo, e la parola sta
    accanto - dentro non ci sta, e "Tendenza" tagliato a meta' e' peggio che
    non averla.
    """
    liv = int((conf or {}).get("livello") or 0)
    color = RING_COLOR[liv]
    r = size / 2.0 - 5
    cx = cy = size / 2.0
    circ = 2 * math.pi * r
    seg = circ / 4.0
    dash = seg * 0.74                       # un quarto di giro, meno lo stacco
    parts = []
    for i in range(4):
        on = i <= liv
        parts.append(
            '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" '
            'stroke-width="5.5" stroke-linecap="round" stroke-dasharray="%.2f %.2f" '
            'stroke-dashoffset="%.2f"/>'
            % (cx, cy, r, color if on else "var(--line)",
               dash, circ - dash, -(i * seg + (seg - dash) / 2.0)))
    return ('<svg class="ring" width="%d" height="%d" viewBox="0 0 %d %d" '
            'role="img" aria-label="Affidabilit\u00e0 %s" '
            'style="transform:rotate(-90deg)">%s</svg>'
            % (size, size, size, size, E(RING_WORD[liv]), "".join(parts)))


PAROLE_DIR = ["nord", "nord-est", "est", "sud-est",
              "sud", "sud-ovest", "ovest", "nord-ovest"]


def direzione_parole(deg):
    """La provenienza a parole, per chi non legge le sigle a colpo d'occhio."""
    if deg is None:
        return ""
    return PAROLE_DIR[int((deg % 360) / 45.0 + 0.5) % 8]


def sky_words(profile):
    """Cielo e temperatura dai modelli, in due parole e un numero."""
    clouds = [r["cloud"] for r in profile if r.get("cloud") is not None]
    temps = [r["t2m"] for r in profile if r.get("t2m") is not None]
    rain = [r["precip"] for r in profile if r.get("precip") is not None]
    out = {}
    if temps:
        out["tmax"] = max(temps)
    if rain and sum(rain) > 1.0:
        out["sky"] = "pioggia"
    elif clouds:
        c = sum(clouds) / len(clouds)
        out["sky"] = ("sereno" if c < 25 else "poco nuvoloso" if c < 55
                      else "nuvoloso" if c < 85 else "coperto")
    return out


# Le parole dell'eta' del dato, in un posto solo. Le usa Python per costruire
# la pagina e le usa il browser per riscriverle mentre il dato invecchia: se
# stessero in due posti, prima o poi direbbero due cose diverse. Il primo
# limite che l'eta' non supera vince; l'ultimo vale per tutto il resto.
ETA_PAROLE = ((12.0, "adesso"), (180.0, "%d min fa"),
              (None, "dato non recente"))

# Oltre questa eta' il dato non e' piu' "adesso" e la riga si ingiallisce.
ETA_STANTIA_MIN = 45.0


def eta_parole(minuti):
    if minuti is None:
        return "orario sconosciuto"
    for limite, parola in ETA_PAROLE:
        if limite is None or minuti < limite:
            return (parola % round(minuti)) if "%d" in parola else parola
    return ETA_PAROLE[-1][1]


# Le icone: tratti semplici, un colore (currentColor), nessuna libreria. Sono
# decorazione che aiuta l'occhio a trovare la cella, non portano informazione
# da sole: accanto c'e' sempre la parola.
_IC = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
       'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
       'aria-hidden="true">%s</svg>')
ICONE = {
    "manica": _IC % ('<path d="M4 3v18"/><path d="M4 5h13l3 3-3 3H4"/>'
                     '<path d="M9 5v6M13 5v6"/>'),
    "freccia": _IC % '<path d="M12 3v18M6 9l6-6 6 6"/>',
    "raffica": _IC % ('<path d="M3 8h10a2.5 2.5 0 1 0-2.5-2.5"/>'
                      '<path d="M3 12h14a3 3 0 1 1-3 3"/><path d="M3 16h7"/>'),
    "cielo": _IC % ('<path d="M7 17a4 4 0 0 1-.5-7.97A6 6 0 0 1 18 8a4.5 4.5 0 0 1 0 9H7z"/>'),
    "orologio": _IC % '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "finestra": _IC % '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "termo": _IC % ('<path d="M10 4.5a2 2 0 0 1 4 0v9.3a3.5 3.5 0 1 1-4 0z"/>'
                    '<path d="M12 10v6"/>'),
    "pressione": _IC % ('<circle cx="12" cy="12" r="8.5"/><path d="M12 12l3.5-3.5"/>'
                        '<path d="M8 15.5h8"/>'),
    "sole": _IC % ('<circle cx="12" cy="13" r="4"/><path d="M12 4v2M4 13h2M18 13h2'
                   'M6.3 7.3l1.4 1.4M17.7 7.3l-1.4 1.4M4 19h16"/>'),
}


def icona(nome, classe="ic"):
    return '<span class="%s">%s</span>' % (classe, ICONE[nome])


def cielo_svg():
    """Il tramonto sul lago, disegnato: cielo, sole, due file di montagne, acqua.

    Al posto della foto del mockup, che non e' nostra. E' vettoriale, pesa
    come un paragrafo, e non ha diritti: e' il nostro. Le montagne sono
    poligoni a mano, un profilo qualunque - non e' un ritratto del Baldo.
    """
    return (
        '<svg class="cielo" viewBox="0 0 1200 420" preserveAspectRatio="xMidYMax slice" '
        'aria-hidden="true">'
        '<defs>'
        '<linearGradient id="hc" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#0b1a2e"/><stop offset=".45" stop-color="#1d3352"/>'
        '<stop offset=".72" stop-color="#b4562a"/><stop offset=".82" stop-color="#f2a04a"/>'
        '<stop offset="1" stop-color="#ffd27a"/></linearGradient>'
        '<linearGradient id="ha" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#d98a3c"/><stop offset=".35" stop-color="#3b3a46"/>'
        '<stop offset="1" stop-color="#0a121c"/></linearGradient>'
        '<radialGradient id="hs" cx=".5" cy=".5" r=".5">'
        '<stop offset="0" stop-color="#fff2c4"/><stop offset=".55" stop-color="#ffb347"/>'
        '<stop offset="1" stop-color="#ffb347" stop-opacity="0"/></radialGradient>'
        '</defs>'
        '<rect width="1200" height="330" fill="url(#hc)"/>'
        '<circle cx="640" cy="318" r="120" fill="url(#hs)" opacity=".85"/>'
        '<circle cx="640" cy="318" r="22" fill="#fff4cc"/>'
        '<path d="M0 330 L0 200 L90 150 L170 215 L260 120 L340 190 L430 145 L520 235 '
        'L600 205 L700 240 L790 160 L880 210 L960 130 L1050 200 L1130 150 L1200 190 '
        'L1200 330 Z" fill="#1a2c44" opacity=".85"/>'
        '<path d="M0 330 L0 250 L80 225 L150 268 L240 205 L330 262 L410 232 L500 285 '
        'L590 260 L680 292 L760 245 L850 282 L930 228 L1020 275 L1110 240 L1200 270 '
        'L1200 330 Z" fill="#101d2e"/>'
        '<rect y="330" width="1200" height="90" fill="url(#ha)"/>'
        '<ellipse cx="640" cy="352" rx="80" ry="7" fill="#ffc46a" opacity=".35"/>'
        '<ellipse cx="640" cy="372" rx="130" ry="6" fill="#ff9d3f" opacity=".18"/>'
        '</svg>')


def now_observed_html(live):
    """La parte OSSERVATA delle condizioni attuali: vento, direzione, raffica, ora.

    Sta in una funzione sua perche' e' anche il contenuto che viaggia dentro
    live.json: il processo veloce la costruisce, la pagina la sostituisce, e
    cosi' le parole - i punti cardinali, "da nord-est", "raffica non
    disponibile" - restano definite in un posto solo, qui, invece di essere
    riscritte in JavaScript dove divergerebbero.

    L'eta' non e' inclusa come testo definitivo: c'e' l'ORARIO del campione,
    e l'eta' la calcola chi guarda, quando guarda.
    """
    if not live or live.get("wind") is None:
        return '<div class="novalue nowempty">nessuna lettura</div>'
    hhmm_txt = ""
    dt = parse_dt_any(live.get("ts") or "")
    if dt:
        hhmm_txt = to_local(dt).strftime("%H:%M")
    # Quattro celle, nell'ordine del mockup: vento, direzione, raffica, e per
    # ultimo l'orario del dato. Le classi di prima (nowbig .v, compass,
    # nowgust, nowmeta/nowage) restano sugli stessi elementi: sono quelle che
    # il browser aggiorna e che le prove cercano.
    gust = ('<span class="v">%.0f <small>kn</small></span>' % live["gust"]
            if live.get("gust") else
            '<span class="v" style="color:var(--ink-3);font-size:14px">'
            'non disponibile</span>')
    dir_deg = live.get("dir")
    return (
        '<div class="cella nowbig">%s<span><span class="k">Vento ora</span>'
        '<span class="v">%.0f <small>kn</small></span></span></div>'
        '<div class="cella compass">%s<span><span class="k">Direzione</span>'
        '<span class="v"><b>%s</b> <small>%s</small></span></span></div>'
        '<div class="cella nowgust">%s<span><span class="k">Raffica</span>%s'
        '</span></div>'
        '<div class="cella nowmeta">%s<span><span class="k nowage">%s</span>'
        '<span class="v">%s</span></span></div>'
        % (icona("manica"), live["wind"],
           ('<span class="ic">%s</span>'
            % arrow(dir_deg, 30, "currentColor")) if dir_deg is not None
           else icona("freccia"),
           E(compass(dir_deg) or "—"),
           E("da " + direzione_parole(dir_deg)) if dir_deg is not None else "",
           icona("raffica"), gust,
           icona("orologio"), E(eta_parole(live.get("age_min"))),
           E(hhmm_txt) if hhmm_txt else "—"))


# La finestra utile non e' la finestra del regime, e non e' la finestra del
# vento migliore previsto: e' quella in cui si puo' davvero essere in acqua.
# Tre vincoli, il piu' stretto vince - finestra del regime, ora pratica, luce -
# e la calcola orari.finestra_utile_del_giorno(), che e' l'unico posto dove
# quella definizione vive. Al Peler di dicembre la differenza non e' un
# dettaglio: la finestra del regime comincia alle 04:00 e il sole si alza alle
# 07:50. Una card che promettesse vento dalle 04:00 prometterebbe di navigare
# al buio.
PASSO_CARD_MIN = 10.0


def _serie_finestra(profile, inizio, fine, passo=PASSO_CARD_MIN):
    """La curva prevista dentro la finestra, su griglia di dieci minuti.

    Qui si interpola, e va detto: il profilo ha un punto per ora. Non e'
    inventare un campione osservato - la curva del modello e' un campo
    continuo campionato ogni ora, ed e' esattamente come la disegna il
    grafico sopra - ma serve perche' la finestra utile ha estremi al minuto
    (08:30, non le 08) e senza griglia fine quegli estremi non esisterebbero.
    """
    punti = sorted((float(r["hour"]) * 60.0, float(r["wind"])) for r in profile
                   if r.get("hour") is not None and r.get("wind") is not None)
    if len(punti) < 2 or fine <= inizio:
        return []

    def a_minuto(m):
        if m < punti[0][0] or m > punti[-1][0]:
            return None
        for i in range(len(punti) - 1):
            xa, ya = punti[i]
            xb, yb = punti[i + 1]
            if xa <= m <= xb:
                if xb == xa:
                    return ya
                return ya + (m - xa) / (xb - xa) * (yb - ya)
        return punti[-1][1]

    out = []
    m = float(inizio)
    while m <= fine + 1e-9:
        v = a_minuto(m)
        if v is not None:
            out.append((m, v))
        m += passo
    return out


def _durata_soglia(serie, soglia, passo=PASSO_CARD_MIN):
    """Minuti sopra soglia, e se quel numero e' un limite inferiore.

    Le due funzioni sono quelle di util, le stesse che usano il report e la
    climatologia: sostenuta vuol dire che la soglia regge per almeno mezz'ora
    consecutiva (sustained_onset), i minuti sono il tempo sopra soglia
    (time_above). Una terza implementazione delle stesse due idee dentro la
    pagina vorrebbe dire che fra sei mesi la card e la tabella diranno numeri
    diversi sulla stessa giornata.

    Il limite e' la censura della finestra: se il vento e' gia' sopra soglia
    al primo punto, o ancora sopra all'ultimo, il periodo comincia prima o
    continua dopo e i minuti dentro la finestra sono un ">=".
    """
    if not serie:
        return None, False
    if sustained_onset(serie, float(soglia), persist_min=PERSISTENZA_CARD_MIN,
                       cadence_min=passo) is None:
        return None, False
    minuti = time_above(serie, float(soglia), passo)
    limite = serie[0][1] >= soglia or serie[-1][1] >= soglia
    return minuti, limite


# La mezz'ora della scheda e' la mezz'ora della climatologia: una definizione
# sola, nel posto dove e' definita. Qui c'era una seconda copia del numero 30,
# ed era l'ultima rimasta - la stessa doppia scrittura che nel motore
# analogico aveva prodotto una porta che misurava venti minuti credendone
# trenta. Un numero scritto due volte prima o poi diventa due numeri.
PERSISTENZA_CARD_MIN = orari.PERSISTENZA_MIN


def _durata_parole(minuti, limite=False):
    if not minuti:
        return "—"
    pre = "&ge;" if limite else ""
    h, m = divmod(int(round(minuti)), 60)
    if h and m:
        return "%s%dh %02d" % (pre, h, m)
    if h:
        return "%s%dh" % (pre, h)
    return "%s%d min" % (pre, m)


def sessione_numeri(name, profile, giorno, live=None, today=False):
    """I numeri di UNA sessione dentro la sua finestra utile.

    Un solo percorso per i due regimi. Prima ce n'erano due - peler_card per
    la mattina, half_cards per il pomeriggio - e dicevano la stessa giornata
    con due livelli di dettaglio diversi: il Peler aveva quattro numeri e
    l'Ora ne aveva due, e nessuno dei due era confrontabile con l'altro. Gian
    ha chiesto riquadri della stessa dimensione perche' i due regimi contano
    uguale; per essere della stessa dimensione devono prima dire le stesse
    cose, e per dire le stesse cose devono venire dalla stessa funzione.

    Tutto viene dalla FINESTRA UTILE, cioe' da quando si puo' davvero essere
    in acqua: regime, ora pratica e luce, il vincolo piu' stretto vince. Il
    picco della finestra del regime - che al Peler comincia alle 04:00 -
    scriveva "12-16 kn" accanto a "sopra 10 kn: -", perche' i dodici nodi
    c'erano alle cinque del mattino, al buio.
    """
    spot = config.SPOTS[name]
    giorno = giorno or local_day(utc_now())
    try:
        inizio, fine = orari.finestra_utile_del_giorno(name, giorno)
    except (KeyError, ValueError, TypeError):
        return None
    if fine <= inizio:
        return None
    serie = _serie_finestra(profile, inizio, fine)
    if not serie:
        return None
    minuti, limite = _durata_soglia(serie, spot["min_kn"])
    dentro = [r for r in profile
              if r.get("hour") is not None and r.get("wind") is not None
              and inizio <= float(r["hour"]) * 60.0 <= fine]
    migliore = max(dentro, key=lambda r: float(r["wind"])) if dentro else None
    kn = float(migliore["wind"]) if migliore else max(v for _m, v in serie)
    # Niente "lo-hi" qui: quel range era la DISPERSIONE DELL'ENSEMBLE - quanto
    # i modelli litigano fra loro - e la scheda la stampava come previsione.
    # In una giornata termica veniva "1-29 kn", che Gian ha letto giusto: "non
    # da' immediatezza, confonde". La banda calibrata sui residui esiste ed e'
    # un'altra cosa (sta nella sessione); qui si scrivono i due numeri che si
    # sentono in acqua, il medio e la raffica.
    raffica = (migliore or {}).get("gust")
    # Oggi il dato MISURATO ha la precedenza sul giudizio emesso stanotte: se
    # la centralina sta leggendo diciassette nodi di Ora, la scheda non puo'
    # continuare a dire "mediocre" perche' la previsione di stanotte era piu'
    # bassa. Non e' un nowcast - la curva futura non si tocca, quel banco e'
    # chiuso - e' solo il divieto di contraddire un anemometro.
    misurato = live_regime_state(live, spot, today)
    if misurato:
        kn = max(kn, misurato["wind"])
    if raffica is None or raffica < kn:
        raffica = kn
    return {"nome": name, "spot": spot, "inizio": inizio, "fine": fine,
            "kn": kn, "raffica": raffica, "minuti": minuti, "limite": limite,
            "misurato": bool(misurato)}


def card_regime(place, regime, label, quando, profile, sessions,
                giorno=None, live=None, today=False):
    """Un riquadro. I due regimi ne hanno uno identico, per costruzione."""
    name = place_spots(place).get(regime)
    data = sessions.get(name) if name else None
    num = sessione_numeri(name, profile, giorno, live, today) if name else None
    if not name or data is None or num is None:
        return ('<div class="rq rq-off"><div class="rq-t">%s</div>'
                '<div class="rq-v">\u2014</div>'
                '<p class="rq-n">nessuna previsione</p></div>'
                % E(label.upper()))
    parola, classe = giudizio.voto(num["kn"], num["minuti"], num["spot"])
    conf = data.get("affidabilita")
    pct = giudizio.affidabilita(data.get("prob"), conf)
    motori = motori_valori(place, sessions)
    righe_motori = ""
    if motori:
        pg, tg, verso = motori
        righe_motori = (
            '<div title="temperatura in pianura meno temperatura in valle">'
            '%s<dt>Contrasto termico</dt><dd>%+.1f °C</dd></div>'
            '<div title="pressione media a nord del lago meno pressione media '
            'a sud: %s">%s<dt>ΔP nord – sud</dt><dd>%+.1f hPa</dd></div>'
            % (icona("termo"), tg, E(verso), icona("pressione"), pg))
    return (
        '<div class="rq q-%s">'
        '<div class="rq-h"><div class="rq-t">%s <span>· %s</span></div>'
        '<span class="pill q-%s">%s</span></div>'
        # Il voto resta anche come testo semplice, nascosto: e' quello che le
        # prove leggono e che uno screen reader dice per primo.
        '<div class="rq-v">%s</div>'
        '<div class="rq-b">%s<div>'
        '<div class="rq-kn"><b>%.0f</b><small>medio</small> '
        '<b>%.0f</b><small>raffica</small> <small>kn</small></div>'
        '<dl class="rq-d">'
        '<div>%s<dt>Finestra</dt><dd>%s – %s</dd></div>'
        '<div>%s<dt>Sopra %.0f kn</dt><dd>%s</dd></div>'
        '%s</dl></div></div></div>'
        % (classe, E(label.upper()), E(quando), classe, E(parola), E(parola),
           anello_pct(pct, classe),
           num["kn"], num["raffica"],
           icona("finestra"), hhmm(num["inizio"]), hhmm(num["fine"]),
           icona("raffica"), num["spot"]["min_kn"],
           _durata_parole(num["minuti"], num["limite"]),
           righe_motori))


def riquadri(place, profile, sessions, giorno=None, live=None, today=False):
    """I due riquadri, nella stessa griglia e della stessa larghezza."""
    cards = [card_regime(place, key, lab, quando, profile, sessions,
                         giorno, live, today)
             for key, lab, quando in META_REGIME]
    return '<div class="rqgrid">%s</div>' % "".join(cards)


def riga_meglio(place, profile, sessions, giorno=None, live=None, today=False):
    """Quando la giornata e' migliore: una riga, e solo se c'e' una differenza.

    Confronta le due sessioni sul VOTO, non su un punteggio continuo: il voto
    e' quello che la pagina mostra, e una riga che dicesse "meglio il
    pomeriggio" accanto a due riquadri che dicono la stessa parola sarebbe una
    contraddizione a dieci centimetri di distanza.
    """
    ordine = {p: i for i, p in enumerate(giudizio.VOTI)}
    voti = []
    for key, lab, quando in META_REGIME:
        name = place_spots(place).get(key)
        if not name or name not in sessions:
            continue
        num = sessione_numeri(name, profile, giorno, live, today)
        if not num:
            continue
        parola, classe = giudizio.voto(num["kn"], num["minuti"], num["spot"])
        if parola:
            voti.append((ordine[parola], parola, classe, lab, quando, num))
    if not voti:
        return ""
    voti.sort(reverse=True)
    top = voti[0]
    if top[0] == 0:                  # il voto piu' basso di giudizio.VOTI
        return ('<p class="meglio no">%s<span class="tx">Niente da fare: '
                'né la mattina né il pomeriggio arrivano a vento '
                'navigabile.</span></p>' % icona("sole"))
    if len(voti) > 1 and voti[1][0] == top[0]:
        return ('<p class="meglio q-%s">%s<span class="tx">Mattina e pomeriggio '
                'si equivalgono: <b>%s</b> in entrambe.</span></p>'
                % (top[2], icona("sole"), E(top[1])))
    _o, parola, classe, lab, quando, num = top
    return ('<p class="meglio q-%s">%s<span class="tx">Meglio <b>%s</b>: '
            '%s %s, dalle <b>%s</b>.</span></p>'
            % (classe, icona("sole"), E(quando), E(lab), E(parola),
               hhmm(num["inizio"])))


def motori_valori(place, sessions):
    """I due motori dei venti del lago: DP nord-sud e contrasto termico.

    E' il numero che ogni windsurfista del Garda guarda da trent'anni - il
    "Bolzano meno Ghedi" delle tabelle di profiwetter, che ventogarda.it e
    wwwind mostrano come primo indicatore - e noi lo avevamo gia', in forma
    piu' generale: sei punti su 150 km invece di una coppia, piu' il contrasto
    termico pianura-valle che e' il motore vero della brezza e che gli altri
    non hanno.

    Mostrarlo non e' decorazione: e' l'unico numero della pagina che chi
    legge puo' confrontare con la propria esperienza ("con meno tre entra
    sempre"), ed e' il modo piu' onesto di far vedere DA COSA viene la
    previsione invece di chiedere di fidarsi. Nel mockup sta dentro i
    riquadri, in due righe con l'icona; qui si calcola una volta e i due
    riquadri lo scrivono.

    Ritorna (dp_hpa, contrasto_c, verso) o None.
    """
    feats = None
    for name in place_spots(place).values():
        f = (sessions.get(name) or {}).get("features")
        if f and f.get("pgrad") is not None:
            feats = f
            break
    if not feats:
        return None
    pg, tg = float(feats["pgrad"]), float(feats.get("tgrad") or 0.0)
    # pgrad > 0: pressione piu' alta a nord, spinge verso sud lungo il lago,
    # favorisce il Peler; < 0 favorisce l'Ora (features._gradients).
    verso = ("spinge il Pelèr" if pg > 0.3 else
             "spinge l’Ora" if pg < -0.3 else "neutro")
    return pg, tg, verso


def anello_pct(pct, classe, size=76):
    """L'affidabilita' come anello con il numero dentro, dal mockup.

    Quando non c'e' (None: non verificata) l'anello e' vuoto e dentro c'e' un
    trattino, non uno zero: "non sappiamo" e "zero" sono due cose diverse.
    """
    r = size / 2.0 - 6
    circ = 2 * math.pi * r
    pieno = circ * (max(0, min(100, pct or 0)) / 100.0)
    colore = {"no": "var(--crit)", "meh": "var(--warn)", "go": "var(--good)",
              "big": "var(--big)"}.get(classe, "var(--ink-3)")
    return (
        '<div class="anello">'
        '<svg width="%d" height="%d" viewBox="0 0 %d %d" role="img" '
        'aria-label="Affidabilità %s">'
        '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="var(--line)" '
        'stroke-width="7"/>'
        '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" '
        'stroke-width="7" stroke-linecap="round" stroke-dasharray="%.2f %.2f" '
        'transform="rotate(-90 %.1f %.1f)"/>'
        '<text x="50%%" y="50%%" dy=".36em" text-anchor="middle" '
        'font-weight="800" fill="var(--ink)">%s</text></svg>'
        '<span>Affidabilità</span></div>'
        % (size, size, size, size,
           ("%d%%" % pct) if pct is not None else "non verificata",
           size / 2.0, size / 2.0, r,
           size / 2.0, size / 2.0, r, colore, pieno, circ - pieno,
           size / 2.0, size / 2.0,
           ("%d%%" % pct) if pct is not None else "—"))


def adesso_riquadro(place, live, profile):
    """Quanto tira ADESSO in questa localita', e di quando e' il dato.

    Vale per Torbole e per Malcesine allo stesso modo: la centralina della
    Fraglia Vela e' letta e salvata da sempre, e non compariva in pagina per
    una ragione che non era una ragione - la vecchia impaginazione teneva le
    due localita' nella stessa schermata e il riquadro dell'adesso era uno per
    entrambe. Con una pagina per localita' la domanda "quanto tira qui" ha una
    risposta sola, e ce l'hanno tutte e due.
    """
    cond = sky_words(profile)
    testo = []
    if cond.get("tmax") is not None:
        testo.append("<b>%.0f °C</b>" % cond["tmax"])
    if cond.get("sky"):
        testo.append(E(cond["sky"]))
    cella_cielo = ""
    if testo:
        cella_cielo = ('<div class="cella nowcond">%s<span>'
                       '<span class="k">%s</span><span class="v">%s</span>'
                       '</span></div>'
                       % (icona("cielo"), E(cond.get("sky") or "cielo")
                          if cond.get("tmax") is not None else "cielo",
                          ("%.0f <small>°C</small>" % cond["tmax"])
                          if cond.get("tmax") is not None
                          else E(cond.get("sky") or "")))
    return (
        '<section class="adesso">'
        '<div class="nowblock" data-live-place="%s" data-ts="%s">'
        '<div class="nowstrip"><div class="nowobs">%s</div>%s</div>'
        '</div></section>'
        % (E(place), E((live or {}).get("ts") or ""),
           now_observed_html(live), cella_cielo))


def scarto_line(profile, osservato):
    """Quanto la realta' sta seguendo la previsione, in una riga.

    Confronta l'ultima ora MISURATA con la previsione della stessa ora - non
    con la previsione del picco, non con la media del giorno: la stessa ora,
    altrimenti si confrontano due cose diverse e lo scarto non vuol dire
    niente.

    Dice due cose e si ferma: di quanti nodi si discosta, e se l'osservato
    sta salendo o scendendo. NON dice "in ritardo di quaranta minuti": un
    ritardo e' una stima di timing, e il timing su questo lago ha appena
    mostrato una semiampiezza di sessanta minuti fuori campione. Quel numero
    va guadagnato con le stesse porte, non scritto perche' suona bene.
    """
    righe = (osservato or {}).get("righe") or []
    if not righe:
        return None
    ultimo = righe[-1]
    if ultimo.get("wind") is None:
        return None
    prev = next((r for r in profile if r.get("hour") == ultimo["hour"]
                 and r.get("wind") is not None), None)
    if prev is None:
        return None
    diff = ultimo["wind"] - prev["wind"]
    tendenza = None
    if len(righe) >= 2 and righe[-2].get("wind") is not None:
        d = ultimo["wind"] - righe[-2]["wind"]
        tendenza = "sale" if d >= 1.0 else ("scende" if d <= -1.0 else "stabile")
    return {"hour": ultimo["hour"], "previsto": prev["wind"],
            "misurato": ultimo["wind"], "scarto": diff, "tendenza": tendenza,
            "raffica_fonte": (osservato or {}).get("raffica_fonte")}


def scarto_words(sc):
    """La riga dello scarto, in italiano. Solo traduzione."""
    if not sc:
        return ""
    verso = ("in linea con la previsione" if abs(sc["scarto"]) < 1.5
             else "%.0f kn %s previsione" % (abs(sc["scarto"]),
                                             "sopra" if sc["scarto"] > 0 else "sotto"))
    coda = {"sale": ", e sta salendo", "scende": ", e sta scendendo",
            "stabile": ", stabile"}.get(sc["tendenza"] or "", "")
    return ("alle %02d:00 previsti <b>%.0f kn</b>, misurati <b>%.0f kn</b>: %s%s"
            % (sc["hour"], sc["previsto"], sc["misurato"], verso, coda))


# Lo spessore delle quattro curve, in un posto solo.
#
# Serve perche' il rapporto fra questi numeri E' l'informazione: quale linea
# si legge per prima non e' decorazione. Il misurato deve stare davanti al
# previsto, e la raffica dietro alla media, ma nessuno dei quattro deve essere
# grosso: su una serie a dieci minuti una linea spessa non e' marcata, e'
# una lama - il vento reale oscilla, e ogni oscillazione diventa uno spigolo.
# L'evidenza si prende col CONTRASTO, cioe' sbiadendo la previsione, non
# ingrossando la misura. Scritto qui una volta, i controlli lo leggono da qui
# invece di inseguire dei numeri magici.
TRATTO = {"previsto": 2.8, "previsto_raffica": 2.0,
          "misurato": 2.2, "misurato_raffica": 1.8}
# E quanto si sbiadisce la previsione quando accanto c'e' una misura.
OPACITA_PREVISTO = 0.34


def _soglie_fasce(place):
    """Le due soglie che contano, dallo spot dell'Ora (o dal primo che c'e')."""
    spots = place_spots(place)
    name = spots.get("ORA") or (list(spots.values())[0] if spots else None)
    if not name:
        return []
    spot = config.SPOTS[name]
    return [(spot["min_kn"], "si esce"), (spot["planing_kn"], "si plana")]


def place_chart(place, profile, bands, chart_id, oggi=False, osservato=None):
    """La giornata di un luogo: vento medio e raffica.

    oggi: se e' la giornata di oggi, il grafico porta anche una riga verticale
    sull'ora corrente, messa dal browser. Nasce da una domanda che si e'
    rivelata piu' importante della risposta: "perche' il pallino e' alle 7
    mentre ora sono le 14.25?". Il pallino e' il PICCO previsto, ma un punto
    con un numero accanto, su una curva del tempo, si legge come "sei qui" -
    e senza un "sei qui" vero non c'era modo di accorgersi che non lo fosse.

    Due curve, distinte da tratto e da etichetta diretta oltre che dal colore -
    la raffica e' tratteggiata, e resta leggibile anche per chi non separa il
    rosa dall'arancione. Lo sfondo porta le finestre dei due regimi, con il
    nome scritto: "meglio fra le 14 e le 18" si capisce prima guardando dove
    sta la campana che leggendo una riga di testo.
    """
    rows = sorted([r for r in profile if r.get("wind") is not None],
                  key=lambda r: r["hour"])
    if len(rows) < 3:
        return ""
    hours = [r["hour"] for r in rows]
    # Il disegno e' vettoriale e si adatta alla colonna, ma il TESTO dentro si
    # adatta con lui: con un viewBox largo 760 dentro una colonna da 370 px di
    # telefono, un font 11 arriva a schermo a 5 px. La tela e' dimensionata
    # vicino alla larghezza reale sul telefono, cosi' su desktop il grafico si
    # ingrandisce - e le scritte con lui - invece di rimpicciolirsi.
    W, H = 440.0, 280.0
    # pr tiene la parola "raffica" dentro la tela: a 50 usciva dal bordo.
    pl, pr, pt, pb = 28.0, 58.0, 26.0, 50.0
    # L'osservato entra nella scala insieme alla previsione: una raffica
    # misurata piu' alta del previsto deve stare DENTRO il disegno, altrimenti
    # la curva che conta di piu' e' quella che esce dal grafico.
    oss_righe = [r for r in ((osservato or {}).get("righe") or [])
                 if rows[0]["hour"] <= r["hour"] <= rows[-1]["hour"]]
    # Nella scala entrano anche i campioni fini, non solo le medie orarie: una
    # punta misurata a dieci minuti e' piu' alta della media della sua ora, e
    # se la scala non la conosce la riga del misurato esce dal disegno.
    oss_fini = [r for r in ((osservato or {}).get("fini") or [])
                if rows[0]["hour"] <= r.get("hour", -1) <= rows[-1]["hour"]]
    peak = max([r["gust"] for r in rows]
               + [r[k] for r in oss_righe + oss_fini for k in ("wind", "gust")
                  if r.get(k) is not None]
               + [12.0])
    top = max(15.0, 5 * math.ceil(peak / 5.0))
    step = 5 if top <= 30 else 10

    def x(h):
        return pl + (W - pl - pr) * ((h - hours[0]) / max(1, hours[-1] - hours[0]))

    def y(v):
        return H - pb - (H - pb - pt) * (max(0.0, min(top, v)) / top)

    p = ['<defs><linearGradient id="%s-g" x1="0" y1="0" x2="0" y2="1">'
         '<stop offset="0%%" stop-color="var(--pc)" stop-opacity=".33"/>'
         '<stop offset="100%%" stop-color="var(--pc)" stop-opacity="0"/>'
         '</linearGradient>'
         # Il riquadro del disegno, per la curva del misurato che il browser
         # riscrive: quella arriva dopo, e puo' portare una punta piu' alta
         # della scala decisa quando la pagina e' stata costruita. Tagliata al
         # bordo si vede che tocca il tetto - che e' vero - invece di uscire
         # sopra le scritte del titolo.
         '<clipPath id="%s-clip"><rect x="%g" y="%g" width="%g" height="%g"/>'
         '</clipPath></defs>'
         % (chart_id, chart_id, pl, pt, W - pl - pr, H - pb - pt)]

    disegnata_utile = False
    for band in bands:
        a, b = max(band["from"], hours[0]), min(band["to"], hours[-1])
        if b <= a:
            continue
        p.append('<rect x="%.1f" y="%g" width="%.1f" height="%.1f" fill="%s" rx="6"/>'
                 % (x(a), pt, x(b) - x(a), H - pb - pt, band["fill"]))
        # Un bordo verticale al confine: due riquadri quasi dello stesso grigio
        # si distinguono male, e sapere DOVE finisce il Peler e comincia l'Ora
        # e' mezza informazione della giornata.
        p.append('<line x1="%.1f" y1="%g" x2="%.1f" y2="%g" stroke="var(--axis)" '
                 'stroke-width="1" stroke-dasharray="3 4" opacity=".7"/>'
                 % (x(a), pt, x(a), H - pb))
        p.append('<text x="%.1f" y="%g" class="t-s" font-weight="800" '
                 'letter-spacing=".1em" fill="var(--ink-2)">%s</text>'
                 % (x(a) + 7, pt - 9, E(band["label"].upper())))
        p.append('<text x="%.1f" y="%g" class="t-xs" fill="var(--ink-3)">'
                 '%02d\u2013%02d</text>'
                 % (x(a) + 7, pt + 14, band["from"], band["to"]))
        # Dentro la banda del regime, la fetta in cui si puo' davvero uscire.
        # Non sostituisce il regime - sapere quando quel vento PUO' soffiare e'
        # un'informazione - ma e' quella su cui si decide, quindi e' la piu'
        # chiara delle due e porta l'orario scritto.
        utile = band.get("utile")
        if utile:
            ua = max(utile[0] / 60.0, hours[0])
            ub = min(utile[1] / 60.0, hours[-1])
            if ub > ua:
                disegnata_utile = True
                p.append('<rect x="%.1f" y="%g" width="%.1f" height="%.1f" '
                         'fill="#ffffff" opacity=".045" rx="4"/>'
                         % (x(ua), pt + 2, x(ub) - x(ua), H - pb - pt - 4))
                p.append('<line x1="%.1f" y1="%g" x2="%.1f" y2="%g" '
                         'stroke="var(--ink-3)" stroke-width="1" '
                         'stroke-dasharray="2 3" opacity=".55"/>'
                         % (x(ua), pt + 2, x(ua), H - pb - 2))
                # L'etichetta si accorcia invece di sbordare sulla banda
                # accanto: "utile 07:10-11:00" sotto la banda del Peler
                # finiva addosso a quella dell'Ora, e due scritte sovrapposte
                # non dicono nessuna delle due.
                largo = x(ub) - x(ua)
                testo = None
                if largo >= 92:
                    testo = "utile %s\u2013%s" % (hhmm(utile[0]), hhmm(utile[1]))
                elif largo >= 52:
                    testo = "utile da %s" % hhmm(utile[0])
                elif largo >= 34:
                    testo = hhmm(utile[0])
                if testo:
                    p.append('<text x="%.1f" y="%g" class="t-xs" '
                             'fill="var(--ink-3)">%s</text>'
                             % (x(ua) + 5, pt + 27, E(testo)))

    # Le fasce dei nodi, dietro a tutto: le soglie che decidono - regime
    # entrato, planata - vengono dallo spot, non da una scala di Beaufort
    # scritta a mano. Due righe sottili, non un arcobaleno: dicono "da qui
    # si esce" e "da qui si plana", che sono le uniche due cose che un
    # rider cerca con l'occhio prima di leggere qualunque numero.
    for soglia, nome in _soglie_fasce(place):
        if soglia < top:
            p.append('<line x1="%g" y1="%.1f" x2="%g" y2="%.1f" '
                     'stroke="var(--good)" stroke-width="1" opacity=".38" '
                     'stroke-dasharray="1 4"/>'
                     % (pl, y(soglia), W - pr, y(soglia)))
            p.append('<text x="%g" y="%.1f" text-anchor="end" class="t-xs" '
                     'fill="var(--good)" opacity=".8">%s</text>'
                     % (W - pr - 3, y(soglia) - 3, E(nome)))
    for v in range(0, int(top) + 1, step):
        yy = y(v)
        p.append('<line x1="%g" y1="%.1f" x2="%g" y2="%.1f" stroke="var(--grid)" '
                 'stroke-width="1"/>' % (pl, yy, W - pr, yy))
        # Lo zero non si scrive: sta alla stessa altezza delle ore e alla
        # stessa ascissa della prima, e le due scritte si leggevano insieme -
        # "004" al posto di "0" e "04". Che la linea di base sia zero si vede
        # dalla scala, e una scritta in meno non toglie niente.
        if v == 0:
            continue
        p.append('<text x="%g" y="%.1f" text-anchor="end" class="t-s" '
                 'fill="var(--ink-3)">%d</text>' % (pl - 7, yy + 4, v))

    # Con l'osservato in scena la previsione si fa piu' tenue: le due linee
    # dicono cose diverse - una e' un'ipotesi, l'altra e' una misura - e la
    # misura deve essere quella che si legge per prima.
    #
    # L'opacita' sta sul GRUPPO e non sulle singole righe perche' non e' piu'
    # una decisione presa solo alla costruzione: se la pagina e' stata fatta
    # all'alba non c'era niente di misurato, e la previsione era giustamente
    # piena; poi arriva la curva del misurato e la previsione deve farsi da
    # parte anche allora. Il browser cambia un numero su un gruppo, e nessuna
    # riga viene ridisegnata.
    curva_w = curva_monotona([(x(r["hour"]), y(r["wind"])) for r in rows])
    curva_g = curva_monotona([(x(r["hour"]), y(r["gust"])) for r in rows])
    p.append('<g id="%s-prev" opacity="%g">' % (chart_id, OPACITA_PREVISTO
                                                if oss_righe else 1))
    p.append('<path d="%s L%.1f,%.1f L%.1f,%.1f Z" fill="url(#%s-g)"/>'
             % (curva_w, x(hours[-1]), H - pb, x(hours[0]), H - pb, chart_id))
    p.append('<path d="%s" fill="none" stroke="var(--gust)" stroke-width="%g" '
             'stroke-dasharray="7 5" stroke-linecap="round"/>'
             % (curva_g, TRATTO["previsto_raffica"]))
    p.append('<path d="%s" fill="none" stroke="var(--pc)" stroke-width="%g" '
             'stroke-linecap="round"/>'
             % (curva_w, TRATTO["previsto"]))
    p.append('</g>')

    # L'OSSERVATO: piu' marcato, e si ferma dove finisce il dato. Non viene
    # prolungato fino a "adesso" ne' interpolato sui buchi: il senso di questa
    # curva e' il confronto, e un confronto con un dato inventato non e' un
    # confronto.
    if oss_righe:
        # Tutto il misurato in un gruppo con un nome: e' la roba che il
        # browser spegne quando ha una curva piu' recente da mettere al suo
        # posto. Spegnere un gruppo e' un'operazione; cancellare sei
        # elementi cercandoli uno per uno sarebbe sei occasioni di
        # sbagliarne uno e lasciare in pagina mezza curva vecchia.
        inizio_oss = len(p)
        # Si DISEGNANO i campioni veri, non le medie orarie. La media oraria
        # nasconde proprio quello che la misura serve a mostrare: misurato su
        # 2.769 inversioni di regime, il fondo del buco fra Peler e Ora sta al
        # 25% del livello coi campioni e al 40% con le medie - 2,6 kn contro
        # 4,2 - e nel 25% dei giri in cui il buco c'e' la media lo cancella.
        # Il CONFRONTO con la previsione resta invece sull'asse orario, dove
        # e' stato validato: scarto_line continua a leggere `righe`.
        serie = oss_fini if len(oss_fini) >= 12 else oss_righe
        w_oss = [(r["hour"], r["wind"]) for r in serie if r.get("wind") is not None]
        g_oss = [(r["hour"], r["gust"]) for r in serie if r.get("gust") is not None]
        if len(g_oss) >= 2:
            p.append('<path d="%s" fill="none" stroke="var(--gust)" '
                     'stroke-width="%g" stroke-dasharray="4 3" '
                     'stroke-linecap="round"/>'
                     % (curva_monotona([(x(h), y(v)) for h, v in g_oss]),
                        TRATTO["misurato_raffica"]))
        if len(w_oss) >= 2:
            p.append('<path d="%s" fill="none" stroke="var(--pc)" '
                     'stroke-width="%g" stroke-linecap="round"/>'
                     % (curva_monotona([(x(h), y(v)) for h, v in w_oss]),
                        TRATTO["misurato"]))
        # Un punto pieno sull'ultima misura: e' il "fin qui" della realta'.
        if w_oss:
            hh, vv = w_oss[-1]
            p.append('<circle cx="%.1f" cy="%.1f" r="3.6" fill="var(--pc)" '
                     'stroke="var(--card)" stroke-width="2"/>' % (x(hh), y(vv)))
            # Sopra il punto, non accanto: a destra ci sono le etichette di
            # fine linea, e due scritte sovrapposte non dicono nessuna delle
            # due. Verso l'alto c'e' sempre spazio, perche' sopra l'ultimo
            # misurato non passa nessuna curva.
            # Sotto il punto se sta nella meta' alta della tela, sopra
            # altrimenti: cosi' non finisce mai addosso al picco previsto,
            # che porta la sua scritta sopra di se'.
            alto = y(vv) < (pt + H - pb) / 2.0
            p.append('<text x="%.1f" y="%.1f" class="t-s" font-weight="800" '
                     'fill="var(--pc)" text-anchor="middle">misurato</text>'
                     % (min(max(x(hh), pl + 24), W - pr - 24),
                        y(vv) + (19 if alto else -11)))
        p.insert(inizio_oss, '<g id="%s-oss">' % chart_id)
        p.append('</g>')

    # Il posto dove il browser mette la curva del misurato appena riletta.
    # Vuoto alla costruzione, e vuoto resta se il file non arriva: in quel
    # caso in pagina rimane il gruppo qui sopra, cioe' la misura che c'era
    # quando la pagina e' stata fatta. Non si perde niente, si invecchia.
    #
    # Le due righe sono ritagliate, il pallino e la scritta no: una scritta
    # tagliata a meta' da un riquadro si legge peggio di una scritta
    # appoggiata un po' fuori.
    if oggi:
        p.append('<g id="%s-live" opacity="0">'
                 '<g clip-path="url(#%s-clip)">'
                 '<path id="%s-live-g" fill="none" stroke="var(--gust)" '
                 'stroke-width="%g" stroke-dasharray="4 3" '
                 'stroke-linecap="round" d=""/>'
                 '<path id="%s-live-w" fill="none" stroke="var(--pc)" '
                 'stroke-width="%g" stroke-linecap="round" d=""/>'
                 '</g>'
                 '<circle id="%s-live-dot" cx="-99" cy="-99" r="3.6" '
                 'fill="var(--pc)" stroke="var(--card)" stroke-width="2"/>'
                 '<text id="%s-live-lab" x="-99" y="-99" class="t-s" '
                 'font-weight="800" fill="var(--pc)" text-anchor="middle">'
                 'misurato</text></g>'
                 % (chart_id, chart_id, chart_id,
                    TRATTO["misurato_raffica"], chart_id,
                    TRATTO["misurato"], chart_id, chart_id))

    hi = max(rows, key=lambda r: r["wind"])
    op_picco = ' opacity=".55"' if oss_righe else ""
    p.append('<circle cx="%.1f" cy="%.1f" r="4.5" fill="var(--pc)" '
             'stroke="var(--card)" stroke-width="2.5"%s/>'
             % (x(hi["hour"]), y(hi["wind"]), op_picco))
    p.append('<text x="%.1f" y="%.1f" class="t-m" font-weight="800" '
             'fill="var(--pc)"%s>%.0f kn</text>'
             % (x(hi["hour"]) + 8, y(hi["wind"]) - 8, op_picco, hi["wind"]))
    # Etichette dirette a fine linea. A fine giornata medio e raffica possono
    # arrivare quasi allo stesso valore: le due scritte si sovrapponevano e
    # diventavano illeggibili. Se sono piu' vicine di una riga di testo le
    # separo, tenendo la raffica sopra perche' e' sempre la maggiore.
    last = rows[-1]
    ly_w, ly_g = y(last["wind"]) + 4, y(last["gust"]) + 4
    if abs(ly_w - ly_g) < 13:
        mid = (ly_w + ly_g) / 2.0
        ly_g, ly_w = mid - 6.5, mid + 6.5
    lx = x(last["hour"]) + 6
    p.append('<text x="%.1f" y="%.1f" class="t-s" font-weight="700" '
             'fill="var(--pc)">medio</text>' % (lx, ly_w))
    p.append('<text x="%.1f" y="%.1f" class="t-s" font-weight="700" '
             'fill="var(--gust)">raffica</text>' % (lx, ly_g))

    ay = H - pb + 22
    for r in rows:
        if r["hour"] % 2 or r.get("dir") is None:
            continue
        p.append('<g transform="translate(%.1f %g) rotate(%.0f) scale(.6)" opacity=".7">'
                 '<path d="M0 -9 L0 9 M0 9 L-4.4 3.4 M0 9 L4.4 3.4" fill="none" '
                 'stroke="var(--ink-2)" stroke-width="2.8" stroke-linecap="round" '
                 'stroke-linejoin="round"/></g>'
                 % (x(r["hour"]), ay, (r["dir"] or 0) % 360))

    for h in hours:
        if h % 2 == 0:
            p.append('<text x="%.1f" y="%g" text-anchor="middle" class="t-s" '
                     'fill="var(--ink-3)">%02d</text>' % (x(h), H - pb + 4, h))

    p.append('<line id="%s-cross" x1="0" y1="%g" x2="0" y2="%g" stroke="var(--axis)" '
             'stroke-width="1.5" opacity="0"/>' % (chart_id, pt, H - pb))

    # Il segno dell'ora corrente. Viene disegnato invisibile e lo posiziona il
    # browser: la pagina e' statica e puo' essere vecchia di ore, quindi un
    # "adesso" scritto al momento della costruzione sarebbe un "adesso" falso -
    # lo stesso errore che la Fase 2 ha tolto dalle condizioni attuali.
    if oggi:
        p.append('<line id="%s-now" x1="0" y1="%g" x2="0" y2="%g" '
                 'stroke="var(--ink-2)" stroke-width="1.5" '
                 'stroke-dasharray="2 3" opacity="0"/>' % (chart_id, pt, H - pb))
        p.append('<text id="%s-nowlab" x="0" y="%g" text-anchor="middle" '
                 'class="t-xs" font-weight="800" letter-spacing=".08em" '
                 'fill="var(--ink-2)" opacity="0">ADESSO</text>'
                 % (chart_id, H - pb + 36))

    _sc = scarto_line(rows, osservato) if oss_righe else None
    payload = [{"h": r["hour"],
                place: [round(r["wind"], 1), round(r["gust"], 1),
                        compass(r.get("dir"))]} for r in rows]
    # L'ora non e' piu' per forza intera: con la forma analogica il profilo ha
    # un punto ogni dieci minuti, e "%02d:00" troncava - sei righe di fila che
    # dicevano tutte 13:00 con quattro numeri diversi. Si scrive l'ora vera.
    body = "".join(
        "<tr><td>%s</td><td class='num'>%.0f</td><td class='num'>%.0f</td>"
        "<td class='num'>%s</td></tr>"
        % (hhmm(float(r["hour"]) * 60.0), r["wind"], r["gust"],
           E(compass(r.get("dir")) or "\u2014"))
        for r in rows)
    passo_fine = any(abs(float(r["hour"]) - round(float(r["hour"]))) > 1e-9
                     for r in rows)

    return (
        # Titolo e legenda sopra il disegno, sulla stessa riga: e' la prima
        # cosa che si legge, e dice cosa sono le due curve prima che l'occhio
        # le cerchi.
        '<div class="gtesta"><h2>Vento previsto e misurato</h2>'
        '<div class="legend">'
        '<span style="color:var(--pc)"><i></i>vento medio</span>'
        '<span style="color:var(--gust)"><i class="dash"></i>raffica</span>'
        '<span style="color:var(--ink-3)"><i class="box" '
        'style="background:currentColor;opacity:.5"></i>finestra del regime</span>'
        '%s%s</div></div>'
        '<div class="chartwrap">'
        # I numeri della mappa del disegno, scritti addosso al disegno.
        # Servono al browser per due cose: la riga di "adesso" e la curva del
        # misurato riletta. Sono gli stessi numeri con cui sono state
        # disegnate le curve qui sopra - non una seconda copia scritta a
        # mano da qualche parte - quindi la mappa del browser e' per
        # costruzione la stessa della pagina.
        '<svg class="chart" id="%s" viewBox="0 0 %g %g" role="img" '
        'data-today="%d" data-w="%g" data-pl="%g" data-pr="%g" '
        'data-h0="%g" data-h1="%g" data-h="%g" data-pt="%g" data-pb="%g" '
        'data-top="%g" data-tenue="%g" data-place="%s" '
        'aria-label="Vento previsto a %s, ora per ora">%s</svg>'
        '<div class="tip" id="%s-tip"></div></div>'
        '%s'
        '<details class="tbl"><summary>i numeri, %s</summary>'
        '<div class="scroller"><table><tr><th>Ora</th><th class="num">Medio</th>'
        '<th class="num">Raffica</th><th class="num">Da</th></tr>%s</table></div>'
        '</details>'
        # In coda, non chiamata diretta: questo <script> sta nel corpo e
        # gwChart e' definita in fondo alla pagina, quindi una chiamata qui
        # arriva prima della definizione. Era rotto da sempre - "gwChart is
        # not defined" dieci volte per pagina, e il tooltip dei grafici non
        # ha mai funzionato. La coda viene svuotata quando la funzione esiste.
        '<script>(window.gwq=window.gwq||[]).push([%s,%s,%g,%g,%g,%g,%g]);</script>'
        % (
           # La voce della finestra utile compare solo quando la fetta chiara
           # e' davvero disegnata: una legenda che spiega un segno assente
           # fa cercare una cosa che non c'e'.
           ('<span style="color:var(--ink-3)"><i class="box" '
            'style="background:currentColor;opacity:1"></i>finestra utile'
            '</span>') if disegnata_utile else "",
           ('<span>pieno: misurato &middot; tenue: previsto%s</span>'
            % (" &middot; raffica misurata: quella dei 30&prime; della centralina"
               if (osservato or {}).get("raffica_fonte_fine") == "raffica della centralina"
               else ""))
           if oss_righe else "",
           chart_id, W, H, 1 if oggi else 0, W, pl, pr, hours[0], hours[-1],
           H, pt, pb, top, OPACITA_PREVISTO, E(place),
           E(place), "".join(p), chart_id,
           ('<p class="scarto">%s</p>' % scarto_words(_sc)) if _sc else "",
           "passo per passo" if passo_fine else "ora per ora",
           body,
           json.dumps(chart_id), json.dumps(payload), W, pl, pr, hours[0], hours[-1]))


# La finestra si mostra con i suoi estremi in orologio, non come "±35 min", e
# la sua qualita' con una parola. La percentuale di copertura e' corretta ed e'
# la cosa sbagliata da mettere in home: chiede a chi si sta vestendo di fare
# statistica. Vive in diagnostica, accanto all'errore medio.
# 25 minuti e' il confine fra "posso programmare l'uscita" e "devo tenermi
# largo"; 45 e' la soglia operativa oltre la quale non mostriamo niente.
TIMING_PAROLA = ((25.0, "buona"), (45.0, "moderata"))


def timing_words(half_min):
    """La parola per una semiampiezza, o None se oltre la soglia operativa."""
    for soglia, parola in TIMING_PAROLA:
        if half_min <= soglia:
            return parola
    return None


def regime_bands(place, giorno=None):
    """Le finestre dei due regimi, senza sovrapposizioni.

    Con un giorno, ogni banda porta anche la sua finestra UTILE: quella in cui
    si puo' davvero essere in acqua, cioe' il regime stretto dall'ora pratica
    e dalla luce. Le due cose non sono la stessa e la differenza non e' piccola:
    al Peler il regime comincia alle 04:00 e a dicembre il sole si alza alle
    07:50. Finche' il disegno mostrava solo il regime, diceva una cosa e la
    scheda accanto ne diceva un'altra a dieci centimetri di distanza.
    """
    O = orari

    spots = place_spots(place)
    fills = {"PELER": "#1a2635", "ORA": "#20303f"}
    out = []
    for key, lab, _when in META_REGIME:
        name = spots.get(key)
        if not name:
            continue
        h0, h1 = config.SPOTS[name]["window"]
        if out and h0 < out[-1]["to"]:
            out[-1]["to"] = h0
        banda = {"from": h0, "to": h1 + 1, "label": lab, "fill": fills[key]}
        if giorno:
            try:
                inizio, fine = O.finestra_utile_del_giorno(name, giorno)
            except (KeyError, ValueError, TypeError):
                inizio = fine = None
            # La finestra utile si disegna solo se e' davvero piu' stretta:
            # quando coincide col regime, un secondo riquadro identico sarebbe
            # rumore.
            if (inizio is not None and fine is not None and fine > inizio
                    and (inizio > h0 * 60 + 1 or fine < (h1 + 1) * 60 - 1)):
                banda["utile"] = (inizio, fine)
        out.append(banda)
    return out


def source_note(place, sessions):
    """Se il numero non e' ancora calibrato su quella centralina, lo si dice."""
    fonti = [sessions[n].get("source") for n in place_spots(place).values()
             if n in sessions]
    for key in FONTI_DA_DICHIARARE:
        if key in fonti:
            return '<div class="snote">%s</div>' % E(SOURCE_LABEL[key])
    return ""


def sezione_giorno(place, entry, visible):
    """Un giorno: i due riquadri, la riga del meglio, poi il grafico grande.

    L'ordine non e' casuale. Prima il verdetto, perche' e' quello che si legge
    stando in piedi col telefono in mano; poi il grafico, che e' l'elemento
    piu' grande della pagina e quello che risponde alla domanda dopo - non "si
    naviga" ma "a che ora, e per quanto".
    """
    pl = entry["places"].get(place) or {}
    today = (entry.get("day") == local_day(utc_now()))
    live = pl.get("live")
    profile = pl.get("profile") or []
    return (
        '<section class="giorno" data-day="%d"%s>'
        '%s%s'
        '<div class="grafico">%s</div>'
        '%s</section>'
        % (entry["_i"], "" if visible else " hidden",
           riquadri(place, profile, entry["sessions"], entry.get("day"),
                    live, today),
           riga_meglio(place, profile, entry["sessions"], entry.get("day"),
                       live, today),
           place_chart(place, profile,
                       regime_bands(place, entry.get("day")),
                       "c%s%d" % (_slug(place), entry["_i"]),
                       oggi=today, osservato=pl.get("osservato")),
           source_note(place, entry["sessions"])))


def _data_breve(day):
    """sab 20/09. Niente "domani" e niente "dopodomani".

    Era la scritta piu' letta della pagina ed era la meno utile: "domani" lo
    sa gia' chi guarda, e a due giorni di distanza "dopodomani" costringe a
    fare il conto per capire se e' il sabato in cui si e' liberi. La data lo
    dice e non chiede niente. "Oggi" resta, perche' quello e' un ancoraggio:
    dice da dove si conta.
    """
    dt = parse_dt_any(day + " 12:00:00")
    oggi = local_day(utc_now())
    if day == oggi:
        return "oggi", "%02d/%02d" % (dt.day, dt.month)
    return (GIORNI[dt.weekday()][:3], "%02d/%02d" % (dt.day, dt.month))


def striscia_giorni(place, days):
    """I cinque giorni, con la data. Cliccando si cambia il giorno mostrato."""
    cards = []
    for i, entry in enumerate(days):
        pl = entry["places"].get(place) or {}
        profile = pl.get("profile") or []
        today = (entry.get("day") == local_day(utc_now()))
        migliore, kn = None, None
        for key, _lab, _quando in META_REGIME:
            name = place_spots(place).get(key)
            if not name or name not in entry["sessions"]:
                continue
            num = sessione_numeri(name, profile, entry.get("day"),
                                  pl.get("live"), today)
            if not num:
                continue
            parola, classe = giudizio.voto(num["kn"], num["minuti"],
                                           num["spot"])
            rango = giudizio.VOTI.index(parola) if parola else -1
            if migliore is None or rango > migliore[0]:
                migliore, kn = (rango, parola, classe), num["kn"]
        giorno_txt, data_txt = _data_breve(entry["day"])
        cards.append(
            '<button class="gcard%s" type="button" data-goto="%d" '
            'aria-current="%s"><span class="gg">%s</span>'
            '<span class="gd">%s</span>'
            '<span class="gk">%s</span>'
            '<span class="gv q-%s">%s</span></button>'
            % (" oggi" if today else "", i, "true" if i == 0 else "false",
               E(giorno_txt), E(data_txt),
               ("%.0f <small>kn</small>" % kn) if kn is not None else "\u2014",
               migliore[2] if migliore else "off",
               E(migliore[1]) if migliore else "\u2014"))
    return '<nav class="giorni" aria-label="giorni">%s</nav>' % "".join(cards)


def sources_panel():
    """Da dove arriva la previsione: centraline, modelli, pesi effettivi."""
    r = ['<div class="panel"><h2 class="display">Da dove arriva la previsione</h2>']

    r.append("<h3>Centraline · la verità contro cui è calibrato tutto</h3><table>"
             "<tr><th>Stazione</th><th>Fornitore</th><th class='num'>Dati raccolti</th>"
             "<th>Periodo</th></tr>")
    stations = [
        ("T0193", "Torbole (Belvedere), 90 m", "Meteotrentino",
         "https://dati.meteotrentino.it/service.asmx"),
        ("malcesine", "Fraglia Vela Malcesine, 65 m", "MeteoProject",
         "https://stazioni.meteoproject.it/dati/malcesine/"),
    ]
    for station, nome, prov, url in stations:
        st = store.obs_stats(station)
        span = "%s → %s" % ((st["hour_from"] or st["day_from"] or "—")[:10],
                            (st["hour_to"] or st["day_to"] or "—")[:10])
        quanti = ("{:,} ore".format(st["hours"]).replace(",", ".") if st["hours"]
                  else "%d giorni" % st["days"])
        r.append("<tr><td>%s</td><td><a href='%s' target='_blank' rel='noopener'>%s</a></td>"
                 "<td class='num'>%s</td><td>%s</td></tr>"
                 % (E(nome), E(url), E(prov), E(quanti), E(span)))
    r.append("</table>")

    ref = config.SPOT_ORDER[0]
    weights, origin = verify.compute_weights(ref, 1)
    skills = store.skills(ref)
    r.append("<h3>Modelli meteo nell'ensemble</h3><p>%s</p><table>"
             "<tr><th>Modello</th><th>Centro</th><th class='num'>Griglia</th>"
             "<th class='num'>Giorni</th><th class='num'>Peso</th>"
             "<th class='num'>MAE verificato</th></tr>"
             % ("I pesi sono <b>misurati</b>: ogni modello conta quanto ha dimostrato di "
                "valere sulla centralina di Torbole." if origin == "verificato"
                else "I pesi vengono ancora da un prior sulla risoluzione: servono almeno "
                     "%d giorni verificati per misurarli sui dati."
                     % verify.MIN_DAYS_FOR_SKILL))
    centri = {
        "ECMWF IFS": "ECMWF", "ECMWF AIFS": "ECMWF (IA)", "ICON-D2": "DWD",
        "ICON-EU": "DWD", "ICON-2I": "ItaliaMeteo · Arpae",
        "AROME Austria": "GeoSphere Austria", "ICON-CH2": "MeteoSvizzera",
        "ARPEGE Europe": "Météo-France", "HARMONIE": "KNMI", "GFS": "NOAA",
        "UKMO": "Met Office", "GEM": "ECCC",
    }
    reach = {True: "1-3 gg", False: "7 gg"}
    for name, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        m = config.MODELS[name]
        sk = skills.get((name, 1))
        r.append("<tr><td>%s</td><td>%s</td><td class='num'>%s km</td>"
                 "<td class='num'>%s</td><td class='num'>%.0f%%</td>"
                 "<td class='num'>%s</td></tr>"
                 % (E(name), E(centri.get(name, "")), m["res_km"],
                    reach[m["res_km"] < 6], w * 100,
                    ("%.2f kn" % sk["mae"]) if sk and sk.get("mae") else "—"))
    r.append("</table>")

    r.append(
        "<h3>Servizi interrogati</h3><table><tr><th>Servizio</th><th>A cosa serve</th></tr>"
        "<tr><td><a href='https://open-meteo.com/' target='_blank' rel='noopener'>"
        "Open-Meteo · Forecast</a></td>"
        "<td>le previsioni correnti dei %d modelli, ogni ~25 minuti</td></tr>"
        "<tr><td><a href='https://open-meteo.com/en/docs/historical-forecast-api' "
        "target='_blank' rel='noopener'>Open-Meteo · Historical Forecast</a></td>"
        "<td>i predittori storici su cui il modello è addestrato</td></tr>"
        "<tr><td><a href='https://open-meteo.com/en/docs/previous-runs-api' "
        "target='_blank' rel='noopener'>Open-Meteo · Previous Runs</a></td>"
        "<td>misura la skill di ogni modello alle varie scadenze</td></tr>"
        "<tr><td><a href='http://storico.meteotrentino.it/' target='_blank' rel='noopener'>"
        "Meteotrentino · archivio Hydstra</a></td>"
        "<td>la serie a 10 minuti di Torbole dal luglio 2012</td></tr>"
        "<tr><td><a href='https://stazioni.meteoproject.it/dati/malcesine/archivio.php' "
        "target='_blank' rel='noopener'>MeteoProject · archivio intraday</a></td>"
        "<td>Malcesine ogni 15-30 minuti da marzo 2026, vento e raffica in nodi</td></tr>"
        "<tr><td><a href='https://stazioni.meteoproject.it/dati/malcesine/report.php' "
        "target='_blank' rel='noopener'>MeteoProject · report mensili</a></td>"
        "<td>l'archivio giornaliero di Malcesine da agosto 2024</td></tr>"
        "</table>" % len(config.MODELS))

    r.append(
        "<h3>Sulle raffiche</h3><p>Le raffiche <b>previste</b> ci sono per entrambi gli "
        "spot: vengono dai modelli. Quelle <b>misurate</b> sono asimmetriche, e la "
        "ragione è nelle fonti. L'archivio storico di Torbole (2012→) espone solo la "
        "velocità media e la direzione, non il massimo: per Torbole un modello di "
        "raffica addestrato non esiste ancora, e si sta accumulando dal canale in tempo "
        "reale, che invece la raffica ce l'ha. Malcesine ha sia la raffica giornaliera "
        "dal 2024 sia quella intraday dal marzo 2026.</p>")

    r.append("<p>Nessuna previsione altrui viene ricopiata: i modelli grezzi entrano come "
             "ingredienti, la previsione che leggi è ricalcolata qui sul tuo computer e "
             "corretta con lo storico misurato delle due centraline. Di quanto sbaglia "
             "si parla in <a href='/diagnostica'>diagnostica</a>.</p></div>")
    return "".join(r)


def status_line():
    if engine.STATE["running"]:
        return "Aggiornamento · %s" % engine.STATE["phase"], "warn"
    last = store.meta_get("last_update")
    if not last:
        return "Primo avvio: raccolta dati", "warn"
    dt = parse_dt_any(last)
    return ("Aggiornato alle %s" % to_local(dt).strftime("%H:%M"),
            "bad" if engine.STATE["errors"] else "")


# La previsione visibile si ferma a cinque giorni. Non e' una semplificazione
# grafica: a sette giorni il Brier del Pel\u00e8r misurato e' 0,240 contro 0,238
# climatologici, cioe' zero. Mostrare quei due giorni sarebbe riempire spazio
# con qualcosa che non sa niente.
MAX_GIORNI = 5


# La riga in testa alla pagina: quanto e' fresco il dato osservato piu' fresco.
# Come per ETA_PAROLE, la tabella sta in un posto solo, perche' la riscrive
# anche il browser mentre il dato invecchia - e se l'intestazione dicesse
# "aggiornati adesso" mentre la scheda sotto dice "tre ore fa", una delle due
# frasi sarebbe una bugia, e chi legge non saprebbe quale.
# (limite in minuti, frase, classe del pallino, unita' del numero)
BANNER_PAROLE = (
    (12.0, "dati reali aggiornati adesso", "", None),
    (60.0, "dati reali aggiornati %d min fa", "", "min"),
    (24 * 60.0, "ultimo dato reale %d ore fa", "warn", "ore"),
    (None, "dati reali non aggiornati", "bad", None),
)

# E quando e' la RILETTURA a non arrivare, non il dato a mancare.
#
# Senza questa frase i due guasti si presentano identici - un numero che
# invecchia - e sono due cose diverse da fare: se le centraline sono zitte non
# c'e' niente da aggiustare e "ultimo dato reale cinque ore fa" e' la verita';
# se invece e' la pagina che non raggiunge il file del dato osservato, il dato
# fresco esiste e non arriva, e chi guarda non ha modo di saperlo. Ha
# incolpato la centralina, o ha pensato che il sito fosse fermo.
#
# Succede anche per cose fuori dal nostro controllo - una rete che blocca
# raw.githubusercontent, un proxy aziendale - e proprio per quelle serve
# dirlo: sono le uniche che non possiamo scoprire da soli.
BANNER_NON_RAGGIUNGIBILE = "dati reali non raggiungibili da questa pagina"
# Dopo quante riletture mancate di fila si dichiara. Una puo' essere un
# passaggio di rete; tre di fila, a cinque minuti l'una, sono un guasto.
LIVE_MANCATE_PRIMA_DI_DIRLO = 3


def banner_parole(minuti):
    """(frase, classe) per l'eta' del dato piu' fresco. None = nessuna lettura."""
    if minuti is None:
        return "nessuna lettura dalle centraline", "bad"
    for limite, frase, classe, unita in BANNER_PAROLE:
        if limite is None or minuti < limite:
            if unita == "min":
                return frase % round(minuti), classe
            if unita == "ore":
                return frase % round(minuti / 60.0), classe
            return frase, classe
    return BANNER_PAROLE[-1][1], BANNER_PAROLE[-1][2]


def live_summary(days):
    """Eta' del dato osservato piu' fresco fra le due centraline."""
    if not days:
        return "nessun dato dalle centraline", "bad"
    ages = [pl["live"]["age_min"] for pl in days[0]["places"].values()
            if pl.get("live") and pl["live"].get("age_min") is not None]
    return banner_parole(min(ages) if ages else None)


# Dove la pagina va a cercare il dato osservato. Con un server dietro - l'app
# sul Mac - e' una richiesta a se stessi. Nel sito pubblicato non puo' esserlo:
# GitHub Pages si pubblica tutto insieme, quindi il live.json che sta accanto
# alla pagina si aggiorna solo quando si ricostruisce il sito. L'esportazione
# sostituisce questo valore con l'indirizzo del ramo dedicato.
LIVE_URL = "/live.json"


def _live_vars(attivo=True):
    """I valori che il modello di pagina passa al pezzo di JavaScript dell'adesso.

    Le parole dell'eta' vengono da ETA_PAROLE, che e' anche quello che usa
    Python per scrivere la pagina: una definizione, due consumatori. Il limite
    None diventa null, cioe' "per tutto il resto".
    """
    # Piu' di un indirizzo, provati in ordine. Il primo e' il ramo dedicato,
    # che e' l'unico che si aggiorna fra due ricostruzioni del sito; l'ultimo
    # e' il file accanto alla pagina, scritto quando la pagina e' stata
    # costruita. Se il primo non e' raggiungibile - rete, CORS, ramo non
    # ancora creato - si finisce sul secondo, che e' vecchio ma vero, e la sua
    # eta' si vede. Non ho potuto verificare da qui che raw.githubusercontent
    # mandi l'intestazione CORS giusta: e' documentato che lo faccia, ma
    # "documentato" non e' "provato", e questa catena fa in modo che, se non
    # lo facesse, la pagina peggiori invece di rompersi.
    indirizzi = []
    if attivo:
        indirizzi.append(LIVE_URL)
        if LIVE_URL != "live.json" and not LIVE_URL.startswith("/"):
            indirizzi.append("live.json")
    return {
        "liveurls": json.dumps(indirizzi),
        "livems": int(config.LIVE_REFRESH_MIN * 60000) if attivo else 0,
        "etawords": json.dumps([[lim, parola] for lim, parola in ETA_PAROLE]),
        "bannerwords": json.dumps([[lim, frase, classe, unita]
                                   for lim, frase, classe, unita in BANNER_PAROLE]),
        "noreach": json.dumps(BANNER_NON_RAGGIUNGIBILE),
        "mancate": LIVE_MANCATE_PRIMA_DI_DIRLO,
        "stale": ETA_STANTIA_MIN,
    }


def _slug(place):
    """Il nome del file di una localita'. Torbole -> index, le altre -> nome.

    La prima di config.PLACES e' la pagina d'ingresso: aggiungere una
    localita' vuol dire aggiungere una riga a config.PLACES, e la pagina, la
    navigazione e il file nascono da la'. Era il senso della richiesta di
    Gian - "cosi' se volessimo aumentare il numero di localita' sarebbe piu'
    facile" - e non e' una comodita' di scrittura: e' che una localita' in
    piu' non deve poter comparire in navigazione e non avere una pagina, o
    avere una pagina che nessun collegamento raggiunge.
    """
    if place == config.PLACES[0]:
        return "index"
    return (place.lower().replace(" ", "-")
            .replace("\u00e0", "a").replace("\u00e8", "e").replace("\u00ec", "i")
            .replace("\u00f2", "o").replace("\u00f9", "u"))


def testa_sfondo():
    """(classe, svg): la foto di Gian se c'e', altrimenti il cielo disegnato.

    Ritorna (" foto", "") con la foto - il CSS la mette come sfondo della
    testa e l'export la copia accanto alla pagina - oppure ("", <svg>) senza.
    Le due cose non si sommano: con la foto il cielo disegnato non serve, e
    disegnarlo sotto sarebbe un kilobyte e mezzo che nessuno vede.
    """
    if config.sfondo_path():
        return " foto", ""
    return "", cielo_svg()


def titolo_html(nome):
    """"Time to <em>Foil</em>": l'ultima parola nel colore d'accento, dal
    mockup. Si ricava dal nome in config, non si riscrive qui: se il nome
    cambia, cambia anche la testa della pagina."""
    parole = nome.split()
    if len(parole) < 2:
        return E(nome)
    return "%s <em>%s</em>" % (E(" ".join(parole[:-1])), E(parole[-1]))


def nav_luoghi(corrente, suffisso=""):
    """Le localita' come linguette. Una sola riga, nessuna parola in piu'."""
    voci = []
    for place in config.PLACES:
        href = ("/" if _slug(place) == "index"
                else "/" + _slug(place)) if not suffisso else (
            _slug(place) + suffisso)
        voci.append('<a href="%s"%s>%s</a>'
                    % (E(href),
                       ' aria-current="page"' if place == corrente else "",
                       E(place)))
    return '<nav class="luoghi">%s</nav>' % "".join(voci)


def dettagli_panel(place, days):
    """Tutto quello che prima stava sparso nella pagina, chiuso in un cassetto.

    Gian: "eliminiamo tutte le scritte inutili, sono troppe". Aveva ragione, e
    il modo di dargliela non e' cancellare: le frasi che tenevano in piedi la
    fiducia - da dove vengono i numeri, quanto valgono, perche' la mattina si
    giudica in un altro modo - erano le stesse che rendevano la pagina un
    muro. Qui stanno dietro una riga sola: chi non tocca non legge niente, chi
    vuole sapere trova tutto.
    """
    entry = days[0] if days else None
    righe = []
    for key, lab, _quando in META_REGIME:
        name = place_spots(place).get(key)
        data = (entry or {}).get("sessions", {}).get(name) if name else None
        if not data:
            continue
        conf = data.get("affidabilita")
        pct = giudizio.affidabilita(data.get("prob"), conf)
        righe.append("<li><b>%s</b>: %s</li>"
                     % (E(lab), giudizio.affidabilita_parole(pct, conf)))
    spot = config.SPOTS[place_spots(place).get("ORA")
                        or list(place_spots(place).values())[0]]
    return (
        '<details class="dettagli"><summary>Dettagli</summary>'
        '<div class="dcont">'
        '<h3>Il voto</h3>'
        '<p>Viene da due cose: quanti nodi e per quanto tempo, dentro la '
        'finestra in cui si pu\u00f2 davvero essere in acqua \u2014 regime, ora '
        'praticabile e luce, il vincolo pi\u00f9 stretto vince. '
        '%s '
        'La rafficosit\u00e0 non entra nel voto: il rapporto raffica/media non '
        '\u00e8 ancora validato su questo lago, e un ingrediente non validato '
        'che sposta un voto \u00e8 un voto che non sappiamo difendere.</p>'
        '<h3>L\u2019affidabilit\u00e0</h3>'
        '<p>Non \u00e8 \u201cquanto \u00e8 giusta la previsione\u201d, che non '
        '\u00e8 nemmeno una domanda ben posta. \u00c8 la probabilit\u00e0 che il '
        'verdetto <i>si naviga / non si naviga</i> sia quello giusto, e viene '
        'dalla probabilit\u00e0 del regime \u2014 che \u00e8 addestrata sullo '
        'storico della centralina e verificata fuori campione \u2014 meno '
        'l\u2019errore di calibrazione misurato a quella scadenza. Dove non '
        'c\u2019\u00e8 verifica non scriviamo un numero.</p>'
        '<ul>%s</ul>'
        '<h3>La mattina e il pomeriggio</h3>'
        '<p>Il Pel\u00e8r e l\u2019Ora sono due venti diversi con due modelli '
        'diversi, e nella pagina hanno riquadri uguali perch\u00e9 contano '
        'uguale. Quello che li distingue \u00e8 che la <i>forma</i> della curva '
        'dice com\u2019\u00e8 fatta una giornata, non quale giornata sar\u00e0: '
        'quella la decide il livello.</p>'
        '<h3>Il misurato</h3>'
        '<p>Nel grafico di oggi la linea piena \u00e8 la centralina, campione '
        'per campione; la previsione dietro si sbiadisce. La raffica misurata '
        '\u00e8 quella <i>ricorrente</i> sui trenta minuti \u2014 la raffica che '
        'torna, non il colpo singolo \u2014 perch\u00e9 \u00e8 la stessa grandezza '
        'della scheda, e due righe con lo stesso nome e due definizioni fanno '
        'leggere un numero per un altro. Si usa una fonte sola per giornata: '
        'un cambio di canale a met\u00e0 giornata si vede come un salto che '
        'non \u00e8 vento.</p>%s'
        '<h3>La raffica prevista</h3>'
        '<p>Non viene dal modello: il rapporto raffica/medio che i modelli '
        'danno ora per ora non ha relazione con quello vero (misurato: '
        'correlazione 0,2 con l\u2019Ora, zero col Pel\u00e8r). \u00c8 il medio '
        'previsto per il rapporto <i>misurato</i> a questa centralina, per '
        'regime e per livello di vento \u2014 sul lago la raffica vale 1,5\u20132 '
        'volte il medio, e il rapporto scende quando il vento sale. %s</p>'
        '<h3>Da dove arrivano i numeri</h3>'
        '<p>Nessuna previsione altrui viene ricopiata: i modelli grezzi entrano '
        'come ingredienti, e la previsione \u00e8 ricalcolata e corretta con lo '
        'storico misurato delle centraline. Centraline, modelli, pesi e '
        'quanto sbaglia: <a href="/diagnostica">dati e modelli</a>.</p>'
        '</div></details>'
        % (giudizio.scala_parole(spot), "".join(righe), prestito_parole(place),
           raffica_parole(place)))


def prestito_parole(place):
    """Se la centralina non misura la direzione e la prende in prestito, la
    pagina lo dice: e' l'unica cosa del misurato che non e' misurata qui."""
    spot = next((config.SPOTS[n] for n in place_spots(place).values()), None)
    donatrici = (spot or {}).get("direzione_da") or ()
    if not donatrici:
        return ""
    nomi = [next((config.SPOTS[n]["place"] for n in config.SPOTS
                  if config.SPOTS[n]["station"] == d), d) for d in donatrici]
    return ('<p>La centralina di %s non misura la <i>direzione</i>: la si '
            'prende in prestito, ora per ora, da %s. Misurato su 4.600 ore in '
            'comune: quando c\u2019\u00e8 vento le centraline dell\u2019alto lago '
            'concordano sul settore il 99\u2013100%% delle volte. La serie \u00e8 '
            'oraria, non a dieci minuti.</p>'
            % (E(place), E(" e, prima, ".join(nomi))))


def raffica_parole(place):
    """Quante ore ha imparato la centralina, e i rapporti: cosi' si vede
    crescere. Se non ha ancora insegnato niente, lo dice."""
    pezzi = []
    for key, lab, _q in META_REGIME:
        name = place_spots(place).get(key)
        if not name:
            continue
        rel = engine.relazione_raffica(name)
        if rel["scalini"]:
            pezzi.append("%s: %s (%d ore)" % (
                lab, ", ".join("da %.0f kn \u00d7%.2f" % (k, v)
                               for k, v in sorted(rel["scalini"].items())),
                rel["ore"]))
    if not pezzi:
        return ("La centralina non ha ancora abbastanza ore di raffica: "
                "intanto si usa \u00d7%.1f, la mediana di tutto il misurato."
                % engine.RAFFICA_PREDEFINITO)
    return "Imparato qui \u2014 " + "; ".join(pezzi) + "."


def anteprima_link(place, days):
    """I tag che una chat legge per fare l'anteprima del link.

    Una previsione si condivide: "guarda domenica" in un gruppo WhatsApp e'
    il modo in cui un sito del genere gira, e un link che arriva con scritto
    sotto "Torbole - oggi Ora fantastico, 18-22 kn, dalle 11:00" e' un link
    che si apre. Uno che arriva nudo no. Il titolo e' il verdetto di OGGI,
    quindi si riscrive a ogni ricostruzione, quattro volte al giorno.
    """
    # Senza giornate (archivio vuoto, localita' appena aggiunta) i tag
    # restano: descrizione e indirizzo canonico non dipendono dal verdetto.
    entry = days[0] if days else {"places": {}, "sessions": {}}
    pl = entry["places"].get(place) or {}
    profile = pl.get("profile") or []
    pezzi = []
    for key, lab, _quando in META_REGIME:
        name = place_spots(place).get(key)
        if not name or name not in entry["sessions"]:
            continue
        num = sessione_numeri(name, profile, entry.get("day"))
        if not num:
            continue
        parola, _c = giudizio.voto(num["kn"], num["minuti"], num["spot"])
        if parola:
            pezzi.append("%s %s, %.0f kn (raffiche %.0f)"
                         % (lab, parola, num["kn"], num["raffica"]))
    titolo = "%s \u00b7 oggi: %s" % (place, " \u00b7 ".join(pezzi) or "vento")
    descr = ("Pel\u00e8r e Ora previsti sulla centralina, con il vento misurato "
             "adesso. Cinque giorni, affidabilit\u00e0 misurata.")
    base = (config.SITE_URL or "").rstrip("/")
    img = ('<meta property="og:image" content="%s/icona-512.png">\n'
           % E(base)) if base else ""
    # Il minimo per un motore di ricerca: descrizione e indirizzo canonico.
    # Non e' una campagna SEO - prima il prodotto - ma sono due righe che
    # costano niente e senza le quali Google indicizza un titolo a caso.
    canon = ('<link rel="canonical" href="%s">\n'
             % E(url_pagina(place))) if base else ""
    return ('<meta name="description" content="%s">\n%s'
            '<meta property="og:type" content="website">\n'
            '<meta property="og:title" content="%s">\n'
            '<meta property="og:description" content="%s">\n%s'
            '<meta property="og:site_name" content="%s">\n'
            '<meta name="twitter:card" content="summary">\n'
            % (E(descr), canon, E(titolo), E(descr), img, E(config.APP_NAME)))


def url_pagina(place):
    """L'indirizzo pubblico della pagina di una localita'."""
    base = (config.SITE_URL or "").rstrip("/")
    if not base:
        return ""
    slug = _slug(place)
    return base + "/" if slug == "index" else "%s/%s.html" % (base, slug)


def page_luogo(place=None):
    """La pagina di UNA localita'.

    Prima era una pagina sola con dentro tutte le localita', una sotto
    l'altra, e ogni giorno moltiplicava le sezioni: cinque giorni per due
    luoghi erano dieci sezioni nello stesso documento, di cui nove nascoste.
    Con una pagina per localita' restano cinque, e la terza localita' non
    raddoppia niente.
    """
    place = place or config.PLACES[0]
    engine.ensure_update(False)
    days = engine.by_day()[:MAX_GIORNI]
    for i, entry in enumerate(days):
        entry["_i"] = i
    live_txt, live_cls = live_summary(days)

    if not days:
        body = ('<div class="panel"><div class="empty">Sto raccogliendo i '
                'dati\u2026</div></div>')
    else:
        pl = days[0]["places"].get(place) or {}
        body = (adesso_riquadro(place, pl.get("live"), pl.get("profile") or [])
                + striscia_giorni(place, days)
                + "".join(sezione_giorno(place, entry, visible=(i == 0))
                          for i, entry in enumerate(days))
                + dettagli_panel(place, days))

    valori = {
        "title": "%s \u00b7 %s" % (place, config.APP_NAME),
        "css": CSS, "place": E(place), "titolo": titolo_html(config.APP_NAME),
        "tag": E(config.APP_TAGLINE), "cielo": testa_sfondo()[1],
        "foto": testa_sfondo()[0],
        "pcls": "p%d" % (config.PLACES.index(place) + 1),
        "anteprima": anteprima_link(place, days),
        "luoghi": nav_luoghi(place),
        "live": E(live_txt), "livecls": live_cls,
        "body": body,
        "reload": 8000 if engine.STATE["running"] else 900000,
    }
    valori.update(_live_vars(True))
    return TEMPLATE % valori


# Il nome vecchio resta come porta d'ingresso: la prima localita'.
def page_home():
    return page_luogo(config.PLACES[0])


# --------------------------------------------------------------------------
# Diagnostica
# --------------------------------------------------------------------------

def page_diagnostics():
    def fmt(v, d=2):
        return ("%.*f" % (d, v)) if isinstance(v, (int, float)) else "—"

    r = ['<div class="panel"><h2 class="display">Quanto sbaglia</h2>'
         '<p>Tutti i numeri sono misurati su giorni che il modello non aveva mai visto. '
         'Le metriche calcolate sugli stessi dati usati per imparare sarebbero una '
         'promessa che il modello non può mantenere.</p>'
         "<table><tr><th>Spot</th><th>Addestrato su</th><th>Livello</th>"
         "<th class='num'>Giorni</th>"
         "<th class='num'>MAE fuori campione</th><th class='num'>MAE riferimento</th>"
         "<th class='num'>Brier</th><th class='num'>Climatologia</th>"
         "<th class='num'>Copertura</th><th>In uso</th></tr>"]
    for name in config.SPOT_ORDER:
        L = store.load_learned(name, "daily")
        label = config.SPOTS[name]["label"]
        if not L:
            r.append("<tr><td>%s</td><td colspan='9'>non ancora addestrato</td></tr>" % E(label))
            continue
        m = L["metrics"]
        used = ("<span class='good'>sì</span>" if m.get("usable") else
                "<span class='bad'>solo probabilità</span>" if m.get("usable_occurrence")
                else "<span class='bad'>no, stima fisica</span>")
        src = {"era5": "rianalisi ERA5", "forecast": "archivio previsioni"}.get(
            m.get("source"), m.get("source") or "—")
        r.append("<tr><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td>"
                 "<td class='num'>%s</td>"
                 "<td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                 "<td class='num'>%s</td><td>%s</td></tr>"
                 % (E(label), E(src), E(str(m.get("tier"))), m.get("n") or 0,
                    fmt(m.get("mae")), fmt(m.get("mae_base")),
                    fmt(m.get("brier"), 4), fmt(m.get("brier_base"), 4),
                    ("%.0f%%" % (m["coverage"] * 100)) if m.get("coverage") else "—", used))
    r.append("</table>"
             "<p>Ogni spot mette in gara due addestramenti: uno sull'archivio delle "
             "previsioni (ha i livelli isobarici ma copre ~5 anni) e uno sulla "
             "rianalisi ERA5 (solo superficie, ma dal 2012). Vincono sullo stesso "
             "metro: entrambi vengono valutati dando loro gli ingressi <i>previsti</i>, "
             "quelli che avranno in esercizio. Valutare quello ERA5 sulla rianalisi lo "
             "farebbe sembrare molto più bravo di quanto sia.</p>")

    # --- la tabella per spot x regime x scadenza -------------------------
    # E' il tavolo su cui poggiano le etichette di affidabilita' della prima
    # pagina. Tenerla qui, e non li', e' deliberato: chi deve decidere se
    # caricare la macchina vuole una parola, chi vuole controllare quella parola
    # vuole i numeri, e sono due bisogni diversi. Ma i numeri devono esserci,
    # altrimenti la parola non e' verificabile.
    band_rows = []
    for name in config.SPOT_ORDER:
        for band, _rng in config.LEAD_BANDS:
            L = store.load_learned(name, "daily@" + band)
            if not L:
                continue
            per = (L.get("metrics") or {}).get("per_lead") or {}
            for lead in sorted(per, key=lambda x: int(x)):
                band_rows.append((name, band, int(lead), per[lead]))
    if band_rows:
        r.append(
            "<h3>Scadenza per scadenza: da dove viene l'etichetta di affidabilità</h3>"
            "<p>Ogni riga è una scadenza misurata a sé, con forward chaining "
            "(si addestra sul passato, si prova sul futuro), lambda scelto dentro "
            "il solo periodo di addestramento e calibrazione tarata fuori dal blocco "
            "di prova. <b>ns</b> significa che l'intervallo di confidenza del "
            "guadagno attraversa lo zero: il miglioramento non si distingue dal "
            "rumore e non viene contato.</p>"
            "<table><tr><th>Spot</th><th>Quando</th><th class='num'>Giorni provati</th>"
            "<th class='num'>MAE</th><th class='num'>Grezzo</th>"
            "<th class='num'>Brier</th><th class='num'>Clim.</th>"
            "<th class='num'>Calibr.</th><th class='num'>Orario</th>"
            "<th>Guadagno intensità</th><th>Affidabilità</th></tr>")
        for name, band, lead, e in band_rows:
            inten = e.get("intensity") or {}
            prob = e.get("prob") or {}
            tim = e.get("timing") or {}
            gi = e.get("gain_int") or {}
            val = confidence.assess(name, lead, e)
            gtxt = "—"
            if gi.get("punto") is not None:
                gtxt = "%+.0f%%" % gi["punto"]
                if gi.get("ic_lo") is not None:
                    gtxt += " [%+.0f,%+.0f]" % (gi["ic_lo"], gi["ic_hi"])
                if not gi.get("significativo"):
                    gtxt += " <b>ns</b>"
            r.append("<tr><td>%s</td><td>%s</td><td class='num'>%s</td>"
                     "<td class='num'>%s</td><td class='num'>%s</td>"
                     "<td class='num'>%s</td><td class='num'>%s</td>"
                     "<td class='num'>%s</td><td class='num'>%s</td>"
                     "<td>%s</td><td>%s</td></tr>"
                     % (E(config.SPOTS[name]["label"]),
                        E(confidence.lead_label(lead)), e.get("n_test_days") or 0,
                        fmt(inten.get("mae")), fmt(inten.get("mae_raw")),
                        fmt(prob.get("brier"), 3), fmt(prob.get("brier_base"), 3),
                        fmt(prob.get("calibration_error"), 3),
                        ("±%d min" % round(tim["mae_min"])) if tim.get("mae_min") else "—",
                        gtxt, confidence_badge(val, compact=True)))
        r.append("</table><p>Le etichette non dipendono dall'orizzonte ma da queste "
                 "misure: la stessa scadenza può meritare <i>buona affidabilità</i> su "
                 "uno spot e <i>tendenza</i> su un altro. Le soglie che separano i "
                 "quattro livelli sono una scelta di prodotto, dichiarata in "
                 "<code>confidence.py</code>, ancorata al margine di nodi che cambia "
                 "davvero la decisione di andare in acqua.</p>")
    else:
        r.append("<h3>Scadenza per scadenza</h3><p>Nessuna scadenza è ancora stata "
                 "misurata: serve l'archivio dei predittori per scadenza "
                 "(<code>--backfill</code>), poi <code>--validate</code>. Finché manca, "
                 "ogni giorno oltre oggi è dichiarato <i>outlook</i>.</p>")

    cand_rows = []
    for name in config.SPOT_ORDER:
        L = store.load_learned(name, "daily")
        cands = (L or {}).get("metrics", {}).get("candidates") or []
        for c in cands:
            cand_rows.append((config.SPOTS[name]["label"], c))
    if cand_rows:
        r.append("<h3>I candidati in gara</h3><table><tr><th>Spot</th><th>Sorgente</th>"
                 "<th>Livello</th><th class='num'>Giorni</th><th class='num'>MAE</th>"
                 "<th class='num'>Brier</th><th>Adottabile</th></tr>")
        for label, c in cand_rows:
            r.append("<tr><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td>"
                     "<td class='num'>%s</td><td class='num'>%s</td><td>%s</td></tr>"
                     % (E(label), E(str(c.get("source"))), E(str(c.get("tier"))),
                        c.get("n") or 0, fmt(c.get("mae")), fmt(c.get("brier"), 4),
                        "sì" if c.get("usable") else "no"))
        r.append("</table>")

    tim = []
    for name in config.SPOT_ORDER:
        T = store.load_learned(name, "timing")
        if T:
            tim.append((config.SPOTS[name]["label"], T["metrics"]))
    if tim:
        r.append("<h3>Orario del picco</h3><p>Quanto sbaglia l'ora in cui il regime "
                 "tocca il massimo, contro i due riferimenti: l'ora media stagionale e "
                 "l'ora in cui il vento grezzo d'ensemble mette il proprio massimo.</p>"
                 "<table><tr><th>Spot</th><th class='num'>Giorni</th>"
                 "<th class='num'>Errore</th><th class='num'>Climatologia</th>"
                 "<th class='num'>Ensemble grezzo</th><th>In uso</th></tr>")
        for label, m in tim:
            mm = lambda h: ("%d min" % round(h * 60)) if isinstance(h, (int, float)) else "—"
            r.append("<tr><td>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                     "<td class='num'>%s</td><td class='num'>%s</td><td>%s</td></tr>"
                     % (E(label), m.get("n") or 0, mm(m.get("mae_hours")),
                        mm(m.get("base_clim_hours")), mm(m.get("base_raw_hours")),
                        "<span class='good'>sì</span>" if m.get("usable")
                        else "<span class='bad'>no</span>"))
        r.append("</table>")
    r.append("</div>")

    r.append('<div class="panel"><h2 class="display">Le probabilità sono oneste?</h2>'
             '<p>Quando l\'app dichiara 70%, il vento deve essere entrato circa 70 volte '
             'su 100.</p>')
    for name in config.SPOT_ORDER:
        L = store.load_learned(name, "daily")
        rel = (L or {}).get("metrics", {}).get("reliability") or []
        if not rel:
            continue
        r.append("<h3>%s</h3><table><tr><th>Dichiarato</th><th class='num'>Osservato</th>"
                 "<th class='num'>Giorni</th></tr>" % E(config.SPOTS[name]["label"]))
        for b in rel:
            r.append("<tr><td>%.0f–%.0f%%</td><td class='num'>%.0f%%</td>"
                     "<td class='num'>%d</td></tr>"
                     % (b["lo"] * 100, b["hi"] * 100, b["observed"] * 100, b["n"]))
        r.append("</table>")
    r.append("</div>")

    r.append('<div class="panel"><h2 class="display">Skill dei singoli modelli</h2>')
    found = False
    for name in config.SPOT_ORDER:
        sk = store.skills(name)
        if not sk:
            continue
        found = True
        r.append("<h3>%s</h3><table><tr><th>Modello</th><th class='num'>Scad.</th>"
                 "<th class='num'>Giorni</th><th class='num'>MAE</th>"
                 "<th class='num'>Bias</th><th class='num'>Pendenza</th></tr>"
                 % E(config.SPOTS[name]["label"]))
        for (m, lead), s in sorted(sk.items(),
                                   key=lambda kv: (kv[0][1], kv[1].get("mae") or 99)):
            r.append("<tr><td>%s</td><td class='num'>D+%d</td><td class='num'>%d</td>"
                     "<td class='num'>%.2f</td><td class='num'>%+.2f</td>"
                     "<td class='num'>%.2f</td></tr>"
                     % (E(m), lead, s["n"] or 0, s["mae"] or 0, s["bias"] or 0,
                        s["slope"] or 0))
        r.append("</table>")
    if not found:
        r.append("<p>Servono almeno %d giorni di osservazioni verificate. Finché non ci "
                 "sono, i pesi vengono da un prior sulla risoluzione dei modelli.</p>"
                 % verify.MIN_DAYS_FOR_SKILL)
    r.append("</div>")

    r.append('<div class="panel"><h2 class="display">Dati e registro</h2><table>'
             "<tr><th>Centralina</th><th class='num'>Campioni</th><th class='num'>Ore</th>"
             "<th>Da</th><th>A</th><th class='num'>Giorni</th></tr>")
    for station in sorted({s["station"] for s in config.SPOTS.values()}):
        st = store.obs_stats(station)
        r.append("<tr><td>%s</td><td class='num'>%d</td><td class='num'>%d</td>"
                 "<td>%s</td><td>%s</td><td class='num'>%d</td></tr>"
                 % (E(station), st["samples"], st["hours"],
                    (st["hour_from"] or "—")[:10], (st["hour_to"] or "—")[:10], st["days"]))
    r.append("</table><table><tr><th>Quando</th><th>Livello</th><th>Ambito</th>"
             "<th>Messaggio</th></tr>")
    for e in store.recent_events(40):
        dt = parse_dt_any(e["ts"])
        r.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                 % (to_local(dt).strftime("%d/%m %H:%M") if dt else "—",
                    E(e["level"] or ""), E(e["scope"] or ""), E(e["message"] or "")))
    r.append("</table></div>")

    text, _cls = status_line()
    valori = {
        "title": "Diagnostica \u00b7 %s" % config.APP_NAME,
        "css": CSS, "place": "Diagnostica", "pcls": "", "anteprima": "",
        "titolo": titolo_html(config.APP_NAME), "tag": "Diagnostica",
        "cielo": testa_sfondo()[1], "foto": testa_sfondo()[0],
        "luoghi": nav_luoghi(None),
        "live": E(text), "livecls": "",
        "body": sources_panel() + "".join(r),
        "reload": 600000,
    }
    # La diagnostica non ha blocchi "adesso" da aggiornare: nessuna richiesta.
    valori.update(_live_vars(False))
    return TEMPLATE % valori


SHUTDOWN_PAGE = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<title>%(nome)s</title><style>body{font:16px/1.6 system-ui,-apple-system,sans-serif;
padding:70px 20px;text-align:center;color:#0c1722;background:#dbe9f4}</style></head><body>
<h2>%(nome)s: app chiusa.</h2><p>I dati raccolti restano salvati.<br>
Riaprila quando vuoi dall’icona dell’app.</p></body></html>"""


TEMPLATE = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#0a121c">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icona-192.png">
<link rel="icon" type="image/png" href="icona-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
%(anteprima)s<title>%(title)s</title><style>%(css)s</style></head>
<body class="%(pcls)s">
<header class="hero%(foto)s">%(cielo)s<div class="wrap">
<div class="hbar">%(luoghi)s
<span class="live"><span class="dot %(livecls)s" id="gwdot"></span
><span id="gwlive">%(live)s</span></span>
</div>
<h1 class="titolo">%(titolo)s</h1>
<p class="tag">%(tag)s</p>
</div></header>
<main class="wrap">%(body)s</main>
<footer class="wrap"><a href="/diagnostica">dati e modelli</a>
&nbsp;·&nbsp; <a href="/spegni">chiudi</a></footer>
<script>
function gwChart(id,data,W,pl,pr,h0,h1){
  var svg=document.getElementById(id); if(!svg||!data.length) return;
  var tip=document.getElementById(id+'-tip'), cross=document.getElementById(id+'-cross');
  var keys=[]; data.forEach(function(d){Object.keys(d).forEach(function(k){
    if(k!=='h'&&keys.indexOf(k)<0) keys.push(k);});});
  function xOf(h){return pl+(W-pl-pr)*((h-h0)/Math.max(1,h1-h0));}
  function show(pt){
    var r=svg.getBoundingClientRect();
    var sx=(pt.clientX-r.left)/r.width*W, best=data[0], bd=1e9;
    data.forEach(function(d){var dd=Math.abs(xOf(d.h)-sx); if(dd<bd){bd=dd;best=d;}});
    cross.setAttribute('x1',xOf(best.h)); cross.setAttribute('x2',xOf(best.h));
    cross.setAttribute('opacity','.5');
    /* L'ora del campione non e' piu' intera: sulla griglia analogica da
       dieci minuti best.h vale 13.166666..., e stampata come prima diceva
       "13.166666666666666:00". Si formatta dai minuti. */
    var tm=Math.round(best.h*60), hh=Math.floor(tm/60), mm=tm-hh*60;
    var h='<b>'+(hh<10?'0':'')+hh+':'+(mm<10?'0':'')+mm+'</b>';
    keys.forEach(function(k){ if(best[k]) h+='<br>medio <b>'+best[k][0]+' kn</b>'+
      ' <span style="opacity:.65">raffica '+best[k][1]+' &middot; '+best[k][2]+'</span>';});
    tip.innerHTML=h; tip.style.opacity='1';
    var px=xOf(best.h)/W*r.width;
    tip.style.left=Math.min(Math.max(px-tip.offsetWidth/2,0),r.width-tip.offsetWidth)+'px';
    tip.style.top='0px';
  }
  function hide(){tip.style.opacity='0'; cross.setAttribute('opacity','0');}
  svg.addEventListener('mousemove',show);
  svg.addEventListener('mouseleave',hide);
  svg.addEventListener('touchstart',function(e){show(e.touches[0]);},{passive:true});
  svg.addEventListener('touchmove',function(e){show(e.touches[0]);},{passive:true});
  svg.addEventListener('touchend',hide);
}
/* Svuota la coda dei grafici gia' emessi nel corpo, poi accetta le chiamate
   successive come se la funzione fosse sempre stata li'. */
(window.gwq||[]).forEach(function(a){gwChart.apply(null,a)});
window.gwq={push:function(a){gwChart.apply(null,a)}};
/* La striscia dei giorni scopre la sezione di quel giorno. Tutti i giorni
   sono gia' nella pagina: nessuna richiesta, funziona anche senza rete. */
document.addEventListener('click',function(ev){
  var b=ev.target.closest ? ev.target.closest('.gcard') : null;
  if(!b) return;
  var i=b.getAttribute('data-goto');
  var cards=document.querySelectorAll('.gcard');
  for(var c=0;c<cards.length;c++)
    cards[c].setAttribute('aria-current', cards[c]===b ? 'true':'false');
  var secs=document.querySelectorAll('.giorno');
  for(var s=0;s<secs.length;s++)
    secs[s].hidden = (secs[s].getAttribute('data-day')!==i);
});
/* ----------------------------------------------------------------------
   L'ADESSO, separato dalla previsione.

   Due tempi diversi: le centraline ogni dieci minuti, i modelli globali ogni
   sei ore. La pagina nasce con dentro il dato osservato del momento in cui e'
   stata costruita, poi si tiene aggiornata da sola rileggendo un file
   piccolo. Due regole:

     l'eta' si ricalcola sempre dall'ORARIO del campione, ogni mezzo minuto,
     anche senza rete: un dato vecchio deve VEDERSI invecchiare;

     se la richiesta non riesce, non si svuota niente: restano i valori con
     cui la pagina e' nata, con la loro eta' che cresce.

   Le parole dell'eta' arrivano da Python (GW_ETA), non sono riscritte qui:
   due copie della stessa frase prima o poi dicono due cose diverse.
   ---------------------------------------------------------------------- */
var GW_LIVE_URLS=%(liveurls)s, GW_LIVE_MS=%(livems)d, GW_ETA=%(etawords)s,
    GW_BANNER=%(bannerwords)s, GW_NOREACH=%(noreach)s,
    GW_MANCATE_MAX=%(mancate)d, gwMancate=0, gwCurvaGen=0;
function gwEtaParole(min){
  if(min===null||isNaN(min)) return 'orario sconosciuto';
  for(var i=0;i<GW_ETA.length;i++){
    var lim=GW_ETA[i][0], w=GW_ETA[i][1];
    if(lim===null||min<lim) return w.indexOf('%%d')>=0
      ? w.replace('%%d',String(Math.round(min))) : w;
  }
  return GW_ETA[GW_ETA.length-1][1];
}
function gwBanner(min){
  var el=document.getElementById('gwlive'), dot=document.getElementById('gwdot');
  if(!el) return;
  /* La rilettura mancata viene PRIMA dell'eta': se il file non arriva, dire
     "ultimo dato reale cinque ore fa" e' vero e fuorviante - sembra che le
     centraline siano zitte, mentre il dato fresco c'e' e non arriva qui. */
  if(GW_LIVE_MS>0&&gwMancate>=GW_MANCATE_MAX){
    el.textContent=GW_NOREACH;
    if(dot) dot.className='dot bad';
    return;
  }
  if(min===null){ el.textContent='nessuna lettura dalle centraline';
                  if(dot) dot.className='dot bad'; return; }
  for(var i=0;i<GW_BANNER.length;i++){
    var lim=GW_BANNER[i][0], f=GW_BANNER[i][1], c=GW_BANNER[i][2], u=GW_BANNER[i][3];
    if(lim===null||min<lim){
      var n = (u==='ore') ? Math.round(min/60) : Math.round(min);
      el.textContent = u ? f.replace('%%d',String(n)) : f;
      if(dot) dot.className='dot'+(c?' '+c:'');
      return;
    }
  }
}
/* L'ora corrente sul grafico di oggi. La calcola il browser, e la calcola
   nell'ora del LAGO: un telefono in un altro fuso mostrerebbe altrimenti una
   riga verticale spostata di ore su un grafico che parla di ore locali. Se il
   browser non sa fare i fusi si ripiega sull'ora locale del dispositivo, che
   per chi e' sul posto e' la stessa. */
function gwOraLago(){
  var d=new Date();
  try{
    var p=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Rome',hour:'2-digit',
      minute:'2-digit',hour12:false}).format(d).split(':');
    var h=parseInt(p[0],10), m=parseInt(p[1],10);
    if(!isNaN(h)&&!isNaN(m)) return h+m/60;
  }catch(e){}
  return d.getHours()+d.getMinutes()/60;
}
function gwNowLine(){
  var ora=gwOraLago();
  var g=document.querySelectorAll('svg.chart[data-today="1"]');
  for(var i=0;i<g.length;i++){
    var svg=g[i];
    var W=parseFloat(svg.getAttribute('data-w')),
        pl=parseFloat(svg.getAttribute('data-pl')),
        pr=parseFloat(svg.getAttribute('data-pr')),
        h0=parseFloat(svg.getAttribute('data-h0')),
        h1=parseFloat(svg.getAttribute('data-h1'));
    var linea=document.getElementById(svg.id+'-now'),
        lab=document.getElementById(svg.id+'-nowlab');
    if(!linea) continue;
    /* Fuori dalla finestra disegnata non si mette una riga al bordo: si
       nasconde. Una riga incollata al margine sinistro alle sei del mattino
       direbbe "sei qui" nel punto sbagliato. */
    if(ora<h0||ora>h1){
      linea.setAttribute('opacity','0');
      if(lab) lab.setAttribute('opacity','0');
      continue;
    }
    var xx=pl+(W-pl-pr)*((ora-h0)/Math.max(1,h1-h0));
    linea.setAttribute('x1',xx.toFixed(1));
    linea.setAttribute('x2',xx.toFixed(1));
    linea.setAttribute('opacity','.85');
    if(lab){ lab.setAttribute('x',xx.toFixed(1)); lab.setAttribute('opacity','.9'); }
  }
}
function gwPaintAge(){
  var now=Date.now(), b=document.querySelectorAll('.nowblock'), fresca=null;
  for(var i=0;i<b.length;i++){
    var el=b[i].querySelector('.nowage'); if(!el) continue;
    var ts=b[i].getAttribute('data-ts'), t=ts?Date.parse(ts):NaN;
    if(isNaN(t)){ el.textContent='orario sconosciuto'; continue; }
    var min=(now-t)/60000;
    if(fresca===null||min<fresca) fresca=min;
    el.textContent=gwEtaParole(min);
    /* La cella dell'orario: un antenato, non per forza il genitore. Si
       aggiunge o toglie SOLO 'stale', senza riscrivere le altre classi. */
    var meta=el.closest?el.closest('.nowmeta'):null;
    if(meta){ if(min>%(stale)g) meta.classList.add('stale'); else meta.classList.remove('stale'); }
  }
  /* L'intestazione dice la stessa cosa della scheda piu' fresca, con le sue
     parole: due frasi diverse sullo stesso dato sarebbero una bugia e mezza. */
  if(b.length) gwBanner(fresca);
}
function gwMappa(d,tx,sx,ty,sy){
  /* Riscrive SOLO le coppie di numeri di un percorso SVG, lasciando in pace
     le lettere dei comandi. Il percorso arriva gia' curvo da Python: qui non
     si interpola niente, si moltiplica. E' questo che tiene la matematica
     della curva in un posto solo - se il browser dovesse costruirla, la
     cubica monotona avrebbe due residenze e prima o poi disegnerebbero due
     curve diverse per gli stessi campioni. */
  return d.replace(/(-?[0-9.]+),(-?[0-9.]+)/g,function(_m,a,b){
    return (tx+sx*parseFloat(a)).toFixed(1)+','+(ty+sy*parseFloat(b)).toFixed(1);
  });
}
function gwCurveLive(dati){
  /* Mai tornare indietro: un file pubblicato in ritardo non deve rimettere
     in pagina una curva piu' corta di quella che c'e' gia'. E' la stessa
     regola del numerone, applicata al file invece che al campione. */
  var gen=Date.parse(dati.generato||'');
  if(!isNaN(gen)){ if(gen<gwCurvaGen) return; gwCurvaGen=gen; }
  var g=document.querySelectorAll('svg.chart[data-today="1"]');
  for(var i=0;i<g.length;i++){
    var svg=g[i];
    var vivo=document.getElementById(svg.id+'-live');
    if(!vivo) continue;
    var v=dati.luoghi[svg.getAttribute('data-place')], c=v&&v.curve;
    /* Niente curva nel file: NON si spegne quella della costruzione. Una
       centralina muta non deve cancellare la misura di stamattina. */
    if(!c||!c.media) continue;
    var W=parseFloat(svg.getAttribute('data-w')),
        H=parseFloat(svg.getAttribute('data-h')),
        pl=parseFloat(svg.getAttribute('data-pl')),
        pr=parseFloat(svg.getAttribute('data-pr')),
        pt=parseFloat(svg.getAttribute('data-pt')),
        pb=parseFloat(svg.getAttribute('data-pb')),
        top=parseFloat(svg.getAttribute('data-top')),
        h0=parseFloat(svg.getAttribute('data-h0')),
        h1=parseFloat(svg.getAttribute('data-h1'));
    var Wp=W-pl-pr, Hp=H-pb-pt, span=Math.max(1,h1-h0);
    /* Da 0-1 alle coordinate del disegno. In x: l'unita' vale l'intervallo
       di ore del file, e l'origine sta dove cadrebbe la sua prima ora.
       In y si va all'incontrario, perche' nel disegno lo zero sta in basso. */
    var TX=pl+Wp*(c.ora_da-h0)/span, SX=Wp*(c.ora_a-c.ora_da)/span,
        TY=H-pb, SY=-Hp*c.ymax/top;
    var pw=document.getElementById(svg.id+'-live-w'),
        pg=document.getElementById(svg.id+'-live-g'),
        dot=document.getElementById(svg.id+'-live-dot'),
        lab=document.getElementById(svg.id+'-live-lab');
    if(pw) pw.setAttribute('d',gwMappa(c.media,TX,SX,TY,SY));
    if(pg) pg.setAttribute('d',c.raffica?gwMappa(c.raffica,TX,SX,TY,SY):'');
    if(c.ultimo&&dot){
      var cx=TX+SX*c.ultimo.x, cy=TY+SY*c.ultimo.y;
      dot.setAttribute('cx',cx.toFixed(1));
      dot.setAttribute('cy',cy.toFixed(1));
      if(lab){
        /* Sotto il pallino se sta in alto, sopra se sta in basso: la
           scritta non deve mai finire addosso al picco previsto, che porta
           la sua etichetta sopra di se'. Stessa regola della costruzione. */
        var alto=cy<(pt+H-pb)/2;
        lab.setAttribute('x',Math.min(Math.max(cx,pl+24),W-pr-24).toFixed(1));
        lab.setAttribute('y',(cy+(alto?19:-11)).toFixed(1));
      }
    }
    vivo.setAttribute('opacity','1');
    /* Ora che c'e' la curva nuova: si spegne quella vecchia e la previsione
       si fa da parte. Se la pagina e' stata costruita all'alba la previsione
       era ancora piena, e da sola non si sarebbe mai tirata indietro. */
    var vecchio=document.getElementById(svg.id+'-oss');
    if(vecchio) vecchio.setAttribute('opacity','0');
    var prev=document.getElementById(svg.id+'-prev'),
        tenue=svg.getAttribute('data-tenue');
    if(prev&&tenue) prev.setAttribute('opacity',tenue);
  }
}
function gwApplyLive(d){
  if(!d||!d.luoghi) return;
  var b=document.querySelectorAll('.nowblock');
  for(var i=0;i<b.length;i++){
    var v=d.luoghi[b[i].getAttribute('data-live-place')];
    if(!v||!v.ts||!v.html) continue;
    /* Non si sostituisce mai con qualcosa di piu' vecchio di quello che c'e'
       gia': un file pubblicato in ritardo non deve far tornare indietro la
       pagina. */
    var vecchio=Date.parse(b[i].getAttribute('data-ts')||''), nuovo=Date.parse(v.ts);
    if(isNaN(nuovo)) continue;
    if(!isNaN(vecchio)&&nuovo<=vecchio) continue;
    var box=b[i].querySelector('.nowobs');
    if(box){ box.innerHTML=v.html; b[i].setAttribute('data-ts',v.ts); }
  }
  gwCurveLive(d);
  gwPaintAge();
}
function gwFetchLive(i){
  i=i||0;
  if(!window.fetch||i>=GW_LIVE_URLS.length){
    /* Esauriti tutti gli indirizzi: questa rilettura non e' arrivata. */
    if(window.fetch){ gwMancate++; gwPaintAge(); }
    return;
  }
  var b=GW_LIVE_URLS[i];
  var u=b+(b.indexOf('?')<0?'?':'&')+'t='+Math.floor(Date.now()/60000);
  fetch(u,{cache:'no-store'}).then(function(r){
    if(!r.ok) throw new Error('http');
    return r.json();
  }).then(function(d){
    if(d&&d.luoghi){ gwMancate=0; gwApplyLive(d); } else gwFetchLive(i+1);
  }).catch(function(){ gwFetchLive(i+1); });
}
gwPaintAge();
gwNowLine();
setInterval(function(){gwPaintAge();gwNowLine();},30000);
if(GW_LIVE_MS>0&&GW_LIVE_URLS.length){
  gwFetchLive(0);
  setInterval(function(){gwFetchLive(0);},GW_LIVE_MS);
  document.addEventListener('visibilitychange',function(){
    if(!document.hidden) gwFetchLive(0);});
}
setTimeout(function(){location.reload()},%(reload)d);
</script></body></html>"""



# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "GardaWind/" + config.APP_VERSION

    def log_message(self, *_a):
        pass

    def handle_one_request(self):
        try:
            BaseHTTPRequestHandler.handle_one_request(self)
        finally:
            # Un thread per richiesta: la connessione SQLite va chiusa qui,
            # altrimenti si accumulano handle aperti a ogni ricarica.
            store.close()

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/health":
            return self._send(200, "ok", "text/plain; charset=utf-8")
        if u.path == "/aggiorna":
            engine.ensure_update(True)
            self.send_response(302)
            self.send_header("Location", "/diagnostica" if q.get("deep") else "/")
            self.end_headers()
            return
        if u.path == "/spegni":
            self._send(200, SHUTDOWN_PAGE % {"nome": E(config.APP_NAME)})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if u.path == "/diagnostica":
            return self._send(200, page_diagnostics())
        if u.path == "/manifest.webmanifest":
            from . import icona
            return self._send(200, icona.manifest(config.APP_NAME, config.APP_SHORT_NAME),
                              "application/manifest+json; charset=utf-8")
        if u.path in ("/icona-192.png", "/icona-512.png"):
            from . import icona
            lato = 192 if "192" in u.path else 512
            data = icona.png(lato)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if u.path == "/live.json":
            from . import live as live_mod
            return self._send(200, json.dumps(live_mod.snapshot(), default=str,
                                              ensure_ascii=False),
                              "application/json; charset=utf-8")
        if u.path == "/api/previsione":
            return self._send(200, json.dumps(engine.full_product(), default=str),
                              "application/json; charset=utf-8")
        if u.path == "/":
            return self._send(200, page_luogo(config.PLACES[0]))
        # Una rotta per localita', ricavata da config.PLACES come tutto il
        # resto: aggiungerne una non richiede di aggiungere un indirizzo.
        for place in config.PLACES:
            if u.path == "/" + _slug(place):
                return self._send(200, page_luogo(place))
        return self._send(404, "non trovato", "text/plain; charset=utf-8")


def serve(port=None):
    port = port or config.RUNTIME_PORT
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
