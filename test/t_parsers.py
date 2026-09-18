import os, sys, json, zipfile, io
os.environ["GARDAWIND_HOME"]="/tmp/gwparse"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from gardawind.sources import meteotrentino as MT, malcesine as MC, openmeteo as OM, http as H
from gardawind.sources import davis_csv as DC
from gardawind import store
from gardawind.util import KN_PER_MS
ok=lambda c,m: print(("PASS " if c else "FAIL ")+m)

# ---- 1. Meteotrentino realtime: payload con la forma REALE ----
real = {"type":"FeatureCollection","features":[
 {"type":"Feature","properties":{"idente":"PATUP","staz":"Torbole (Belvedere)","quota":"90 m","code":"T0193",
   "datetime":"2026-09-13T10:15:00+01","prec(mm)":"0.0","ta(°C)":"23.3","tamin(°C)":"23.1","tamax(°C)":"23.6",
   "vvmed(m/s)":"","vvmax(m/s)":"","dvmed(gN)":"","umid(%)":"55","press(hPa)":"1013.0",
   "radsg(W/mq)":"614","radsn(W/mq)":"","hs(cm)":""},"geometry":{"type":"Point","coordinates":[10.877355,45.870095]}},
 {"type":"Feature","properties":{"datetime":"2026-09-13T10:10:00+01","vvmed(m/s)":"1.8","vvmax(m/s)":"3.2","dvmed(gN)":"340"}},
 {"type":"Feature","properties":{"datetime":"2026-09-13T09:00:00+01","vvmed(m/s)":"3.2","vvmax(m/s)":"5.5","dvmed(gN)":"38"}},
 {"type":"Feature","properties":{"datetime":"2026-09-13T08:40:00+01","vvmed(m/s)":"3.5","vvmax(m/s)":"6.7","dvmed(gN)":"38"}},
 {"type":"Feature","properties":{"datetime":"2026-09-13T08:30:00+01","vvmed(m/s)":"99","vvmax(m/s)":"120","dvmed(gN)":"10"}},
]}
MT.fetch_json = lambda *a, **k: real
rows = MT.fetch_realtime()
ok(len(rows)==3, "righe senza vento e fuori scala scartate: %d valide su 5"%len(rows))
ts,w,g,d = [r for r in rows if r[0].startswith("2026-09-13T09:10")][0]
ok(ts=="2026-09-13T09:10:00Z", "10:10+01 -> 09:10 UTC (%s)"%ts)
ok(abs(w-1.8*KN_PER_MS)<1e-6, "m/s -> nodi (%.2f)"%w)
ok(abs(g-3.2*KN_PER_MS)<1e-6 and d==340.0, "raffica e direzione")
ok(all(0<=r[1]<=70 for r in rows), "controllo di plausibilita' applicato")

# ---- 2. CSV Hydstra: formato REALE dell'archivio ----
csv_real = '''"Time","T0193",""\r
"and","515.00",""\r
"Date","Vel. Vento (m/s)",""\r
"","Point","Qual"\r
00:00:00 01/08/2026,         2.8,    145,Sites:\r
00:10:00 01/08/2026,         3.3,    145,T0193 - Torbole (Belvedere) Lat:45.870095\r
00:20:00 01/08/2026,         3.1,    145,\r
00:30:00 01/08/2026,         5.1,    255\r
13:00:00 13/07/2021,        22.0,    145\r
'''
parsed = MT._parse_hydstra_csv(csv_real)
ok(len(parsed)==4, "righe dati estratte, intestazione e note ignorate: %d"%len(parsed))
ok("2026-07-31T23:00:00Z" in parsed, "00:00 CET del 01/08 -> 23:00 UTC del 31/07")
ok(parsed["2026-07-31T23:00:00Z"]==2.8, "valore letto nonostante gli spazi")
ok(not any(v==5.1 for v in parsed.values()), "qualita' 255 (nessun dato) scartata")
ok(parsed.get("2021-07-13T12:00:00Z")==22.0, "record storico del 2021 (22 m/s = 42.8 kn)")

# ---- 3. Malcesine: CSV NOAA REALE ----
noaa = ('Data;Avg;Min;"Ora Min";Max;"Ora Max";"Avg UR";"Avg Rad";Pioggia;"Avg Vento";Raffica;"Dir Dom"\n'
        '1;27.7;21.4;6.0;32.9;16:00;65;;2.8;8.0;26.1;ENE\n'
        '2;28.1;24.1;7.0;33.0;15:00;60;;0.0;9.3;26.9;ENE\n'
        '4;29.8;25.9;3.0;35.5;19:00;53;;0.0;4.7;17.4;SW\n'
        '32;1;1;1;1;1;1;;1;1;1;N\n')
DC.fetch_text = lambda *a, **k: noaa
days = MC.fetch_month(8, 2026)
ok(len(days)==3, "giorno 32 scartato: %d righe valide"%len(days))
ok(days[0]==("2026-08-01",8.0,26.1,67.5), "prima riga: %s"%(days[0],))
ok(days[2][3]==225.0, "direzione SW -> 225 gradi")

# ---- 4. Malcesine live: testo REALE della pagina ----
page = ("65 m. s.l.m., Malcesine, Veneto, Italy - 45.7646N; 10.8119E Osservatorio Meteorologico "
        "Dati aggiornati il 13/09/26 alle ore 11.28 Temperatura Temperatura: 22.9 °C Umidità: 66 % "
        "Vento Velocità attuale: 3.5 kts NE Media: 1.7 kts Brezza leggera Raffica giornaliera: 9.6 kts "
        "Ora Raffica: 08.40 Wind Chill: 22.8°C")
MC.fetch_text = lambda *a, **k: "<html><body>"+page+"</body></html>"
sample, gust_day = MC.fetch_live()
ok(sample[1]==1.7, "usa la MEDIA a 10 minuti (%.1f kn), non l'istantanea"%sample[1])
ok(sample[3]==45.0, "direzione NE -> 45 gradi")
ok(sample[0]=="2026-09-13T09:28:00Z", "11:28 ora legale italiana -> 09:28 UTC (%s)"%sample[0])
ok(gust_day==9.6, "raffica giornaliera tenuta a parte, non come raffica del campione")
ok(sample[2] is None, "il campione non eredita la raffica del giorno")

# ---- 5. Open-Meteo: forma REALE della risposta ----
om = {"latitude":45.87,"longitude":10.88,"elevation":72.0,"hourly":{
  "time":["2026-09-13T00:00","2026-09-13T01:00"],
  "wind_speed_10m":[4.1,5.2],"wind_direction_10m":[204,210],"wind_gusts_10m":[7.0,8.1],
  "temperature_2m":[18.2,17.9],"wind_speed_925hPa":[11.0,12.0],"wind_direction_925hPa":[200,205],
  "shortwave_radiation":[0,0],"cloud_cover_low":[0,5],"pressure_msl":[1015.2,1015.0],
  "variabile_ignota":[1,2]}}
OM.fetch_json = lambda *a, **k: om
rows, elev = OM.fetch_forecast(45.87,10.88,"icon_d2",True)
ok(elev==72.0 and len(rows)==2, "risposta letta, elevazione %s"%elev)
valid, vals = rows[0]
ok(valid=="2026-09-13T00:00:00Z", "timezone=UTC: nessuna riconversione (%s)"%valid)
ok(vals["w10"]==4.1 and vals["w925"]==11.0 and vals["cloud_low"]==0, "colonne mappate, zero preservato")
ok("variabile_ignota" not in vals, "variabili non previste ignorate senza errori")

# previous-runs: il suffisso deve essere rimosso
om2 = {"hourly":{"time":["2026-09-13T00:00"],"wind_speed_10m_previous_day2":[6.6],
                 "wind_direction_10m_previous_day2":[190],"wind_gusts_10m_previous_day2":[9.9]}}
OM.fetch_json = lambda *a, **k: om2
rows2 = OM.fetch_previous_run(45.87,10.88,"icon_eu",2,"2026-08-01","2026-08-02")
ok(rows2[0][1]["w10"]==6.6 and rows2[0][1]["d10"]==190, "suffisso _previous_dayN rimosso correttamente")
