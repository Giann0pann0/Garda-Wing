# SportAddicted: semantica e ingestione

Stato: 15 settembre 2026.

## Cosa significano i campi

- `avg` / `boe`: canale di previsione della pagina.
- `mavg`: media oraria del canale storico/osservativo.
- `mmax`: massimo dell'ora del canale storico/osservativo.
- `dir`: direzione prevista; non viene salvata come osservazione.
- `mmax` non e' `gust_rec`: la raffica ricorrente di GardaWind resta la mediana mobile a 30 minuti ed e' stimabile solo con campionamento abbastanza fitto.

## Perche' il primo censimento sembrava impossibile

La pagina `/historie/` espone due contatori diversi:

- `Messtage`: giorni con copertura dati;
- `Windtage`: giorni che superano il criterio predefinito `Grundwind >= 12 kn` per almeno 2 ore.

Il primo audit aveva letto i Windtage come "giornate misurate". Per questo Torbole risultava 4267 / 959 = 445%. Con la semantica corretta, 4267 giorni recuperati sono circa il 99% dei Messtage dello snapshot del sito.

## Audit sui raw scaricati

Con i raw del censimento completo:

| stazione | giorni con dato | ore importabili | massimo mmax |
|---|---:|---:|---:|
| Torbole | 4267 | 101156 | 66.4 kn |
| Capo Reamol / Limone | 3805 | 90891 | 56.0 kn |
| Malcesine storica | 4127 | 95191 | 44.3 kn |
| Malcesine Nord | 1277 | 30518 | 34.6 kn |
| Campione | 2915 | 66453 | 52.9 kn |
| Brenzone | 2915 | 66454 | 52.9 kn |

Totale: 450663 ore sorgente. Il totale non equivale a 450663 osservazioni indipendenti.

Campione e Brenzone coincidono praticamente punto per punto nello storico scaricato. Sono quindi conservati come due stazioni, ma condividono `series_group=campione_brenzone_shared` e non devono valere doppio in un modello.

## Ingestione

Lo storico SportAddicted viene scritto nella tabella dedicata `addicted_hour`:

- `wind_mean_kn` <- `mavg`
- `hourly_max_kn` <- `mmax`
- `series_group` conserva l'indipendenza della sorgente
- `raw_origin` conserva il file grezzo scelto

Non viene scritto in `obs_sample` e non produce automaticamente `gust_rec`. Questo impedisce che un massimo orario venga confuso con la raffica ricorrente a 30 minuti.

Comando:

```bash
python3 -m gardawind --addicted-importa
```

Il comando usa solo la cache gia' scaricata e non accede alla rete.
