# Piano: realismo dei piani generati — bug fix, migliorie, eval

> Stato: **proposto** (analisi del 2026-07-02, bug B1–B6 riprodotti con test manuale).
> Obiettivo: eliminare le cause note dei piani "poco realistici", rendere il realismo
> misurabile nell'harness, e rirunnare l'eval 2×2 una sola volta a fix completati.
> Riferimenti: [toptw-itinerary-solver-spec.md](toptw-itinerary-solver-spec.md),
> [evaluation-harness-spec.md](evaluation-harness-spec.md), tesi cap. 5 §Limitations e cap. 6 §Limitations.

## Regola d'oro per l'eval

I fix delle Fasi 1–2 cambiano i risultati di **entrambi** i bracci (greedy e TOPTW).
Non rirunnare il 2×2 a metà: completare almeno tutta la Fase 1, poi una singola run
documentata ("versione valutata = post-fix orari", da scrivere nel cap. 6).

---

## Fase 1 — Correttezza (bug confermati) — effort S/M, impatto alto

### 1.1 Orari overnight e 24/7 (B1, B2) — `_is_open` + `time_window_seconds`

**Problema (riprodotto):**
- Periodo con `close.day != open.day` (es. ven 19:30 → sab 00:30): il locale risulta
  chiuso a qualunque ora ≥ apertura (`1930 <= t <= 0030` mai vero). Colpisce la cena a
  Madrid/Roma dove i ristoranti chiudono dopo mezzanotte.
- POI 24/7 (Google New API: unico periodo `{open: {day: 0, time: "0000"}}` senza
  `close`): risulta chiuso 6 giorni su 7 (aperto solo domenica).

**Fix proposto:** helper condiviso in `itinerary_planner`:

```python
def opening_intervals_for_day(opening_hours: dict, google_day: int) -> list[tuple[int, int]] | None:
    """Intervalli [open_min, close_min) in minuti-da-mezzanotte per il weekday dato.
    None = nessun dato (trattare come sempre aperto). Lista vuota = chiuso quel giorno.
    Gestisce:
    - sentinella 24/7: unico periodo, open day 0 time 0000, senza close -> [(0, 1440)] per ogni giorno
    - periodo same-day: (open, close)
    - periodo overnight che APRE quel giorno: (open, 1440)
    - periodo overnight che apre il giorno PRIMA e chiude quel giorno: (0, close)
    - close mancante su un periodo non-24/7: close = 1440 (fino a fine giornata)
    """
```

Poi:
- `_is_open(poi, dt)` = appartenenza a uno degli intervalli del weekday di `dt`.
- `time_window_seconds` usa gli stessi intervalli, clampati alla finestra del giorno.
  Per il modello a intervallo singolo di OR-Tools resta il bounding box
  `[min open, max close]` (superato in Fase 2.1), ma su base intervalli corretti.

**Test da aggiungere** (`tests/test_opening_hours.py`): overnight ven→sab (aperto 20:30,
aperto 00:15 di sabato, chiuso 02:00), 24/7 su tutti i weekday, split/siesta, periodo
senza close, `periods` vuoto/malformato, POI senza `opening_hours`.

### 1.2 Metriche di realismo nell'harness (rende visibili B1/B4/B5)

In `evaluation/metrics.py::compute_metrics` aggiungere:
- **`tw_violation_rate`**: quota di stop con arrivo *o fine visita* fuori dagli
  intervalli di apertura del POI (usa `opening_intervals_for_day`, quindi va fatta
  dopo 1.1). Oggi l'harness misura solo overrun di budget: le violazioni di orario
  sono invisibili.
- **`meal_timing_deviation_min`**: media di |arrivo pranzo − 13:00| e |arrivo cena − 20:00|.
- **`walk_km_per_day`**: km a piedi/giorno (somma metri delle tratte walking dalla
  cache; fallback haversine). Serve anche per la Fase 3.3 e per RQ2 (profili senior).

### 1.3 Greedy Pass-3: ri-check apertura dopo il TSP (B4)

`_schedule_day` → `_add_activity_stop` (Pass 3) non chiama mai `_is_open`: dopo il
riordino TSP un POI verificato aperto nel Pass 1 può finire schedulato quando è chiuso.
Fix: replicare la logica del TOPTW (`toptw_solver.schedule_day_route`): se chiuso
all'arrivo, attendere a passi di 5' fino ad apertura (entro `end_dt`), altrimenti "skip".
Nota tesi: correzione di fairness del baseline, da menzionare nel cap. 6.

### 1.4 Last entry (B5)

Oggi il vincolo di finestra riguarda solo l'**arrivo**: si può "entrare" 5' prima della
chiusura con visita di 2h.
- TOPTW: `SetRange(open_s, min(close_s - service_s, ...))` (in `_solve` e
  `_reorder_day_tsptw`), con guard `close_s - service_s > open_s` altrimenti nessuna replica.
- Ri-propagazione e greedy: nuovo check `fits_open(poi, arrival, departure)` che
  richiede arrivo E fine visita dentro lo stesso intervallo di apertura.
- Opzionale: `settings.last_entry_margin_min` (default 0) per modellare "ultimo
  ingresso 30/60' prima della chiusura" dei musei.

### 1.5 Pasti: attendere l'apertura del ristorante (B6)

`_try_insert_meal`/`_add_food_stop` (toptw) e l'inserimento in-loop del greedy fissano
`arrival = cur + travel` anche se il locale apre più tardi (probe a `max(cur, target)`).
Fix: se il locale è chiuso all'arrivo calcolato, clampare l'arrivo all'apertura
(`forced_arrival`), entro `end_dt`. Vale per pranzo e cena, entrambi i solver.

### 1.6 Data di viaggio + timezone (B3)

- `GenerateItineraryRequest.start_date: date | None = None` (default oggi) →
  `generate(...)`/`toptw_solver.plan(...)` usano `start_date` come giorno 1 per i
  weekday delle finestre. Senza data, i musei "chiusi il lunedì" sono calcolati sul
  giorno sbagliato per qualunque viaggio futuro.
- Persistere `start_date` su `Itinerary` (colonna nullable + migrazione Alembic) così
  GET può mostrare date reali e l'eval è riproducibile.
- Timezone: il server (Railway) è UTC → `datetime.today()` la sera può essere il giorno
  prima di quello locale. Minimo: interpretare `start_date` come data locale città
  senza conversioni. Meglio (S+): colonna `timezone` su `cities` (IANA name,
  compilata una tantum) e `datetime.now(ZoneInfo(tz))` come default.

### 1.7 Marcatura food usato coerente (B8)

In `generate` (greedy) il pool cibo condiviso marca gli usati con `FOOD_TYPES` sui
Google types; un POI `travel_category="food"` con primary type `point_of_interest`
sfugge e può essere riproposto il giorno dopo. Fix: usare lo stesso predicato di
`evaluation/metrics._is_food_stop` (`travel_category == "food" or is_actual_food_poi`).

**Acceptance Fase 1:** test 1.1 verdi; `tw_violation_rate ≈ 0` per TOPTW e misurato per
greedy; nessuna cena schedulata prima dell'apertura; run 2×2 completa post-fix.

---

## Fase 2 — Modello più realistico — effort M, impatto medio/alto (contributi tesi)

### 2.1 Finestre split vere con `RemoveInterval`

La tesi dichiara il collasso `[min open, max close]` come limite del modello
OR-Tools — ma su un `CumulVar` si può fare `cumul.RemoveInterval(close1_s, open2_s)`
per scavare il buco della siesta. Applicare in `_solve` e `_reorder_day_tsptw` usando
gli intervalli di 1.1. Rimuove una Limitation dichiarata (aggiornare cap. 5 §Limitations).

### 2.2 Type-cap (e diversità) dentro il solver (B7)

Oggi `_PRIMARY_TYPE_DAY_CAP` è applicato solo in ri-propagazione: il solver spende
budget su 5 chiese, 3 vengono droppate come "skip" → tempo morto (concausa degli idle
76'/giorno). Fix: per ogni tipo cappato una dimensione unaria OR-Tools
(`AddDimensionWithVehicleCapacity`: +1 sui nodi di quel tipo, capacità = cap per
veicolo/giorno). Estensione diversità: cap morbido per `travel_category` (es. max 4
stessa categoria/giorno) o penalità di ridondanza MMR-style nel prize di
`select_candidates` — il TOPTW oggi non ha alcun termine di diversità (il greedy sì, via MMR).

### 2.3 Buffer di transizione

Tempi tratta e durate esatti al minuto = piani "da robot" e overrun reale. Aggiungere
`settings.transition_buffer_min` (default 8–10') al tempo di servizio di ogni stop
(in `time_cb` del solver e nella propagazione di entrambi gli scheduler). A/B-abile
per l'eval (env alias, come gli altri switch).

### 2.4 Transit con costo fisso di accesso

`transit = driving × φ` sottostima le tratte brevi (attesa + camminata alla fermata
sono costi fissi). Passare a `transit = driving × φ + settings.transit_boarding_min`
(default ~8'). Un parametro in `_travel`/`_build_travel_seconds`, documentare in tesi
(§Real Travel Times).

### 2.5 Soglia camminata su distanza reale (S, opzionale)

`select_transport` decide il mezzo sulla distanza in linea d'aria: 750 m crow-fly
attraverso il fiume possono essere 2 km a piedi. Quando la cache ha i metri reali
walking per la coppia, usare quelli per il confronto con la soglia (fallback haversine).
Attenzione alla coerenza prefetch/lookup (il mode decide la chiave di cache).

**Acceptance Fase 2:** idle medio TOPTW in calo misurabile vs post-Fase-1;
`tw_violation_rate` = 0 anche con finestre split; nessun "skip" da type-cap in
ri-propagazione (il cap è rispettato a monte).

---

## Fase 3 — Ambiziosi / future work (L — valutare cosa entra in tesi)

1. **Meal nodes nel solver**: pranzo/cena come nodi opzionali con disjunction
   obbligatoria per finestra pasto → elimina la riserva fissa 150' e il fill degli
   underfull come workaround. È il refactoring più profondo; farlo solo se resta tempo.
2. **Durate per-POI**: audit copertura di `tourism_duration_minutes` (query: % POI per
   città); dove manca, arricchire via pipeline LLM. Le tabelle statiche
   (museo=120' per il Prado come per un museo minore) diventano solo fallback.
3. **Budget camminata giornaliero per profilo**: dimensione cumulativa OR-Tools sui
   metri walking con capacità per veicolo dipendente da età/relax (la soglia per-tratta
   esiste già; manca il vincolo cumulativo). Si aggancia alla metrica `walk_km_per_day` (1.2).
4. **GTFS / OpenTripPlanner per il transit** (citare come future work, non implementare).
5. **Refactor**: `itinerary_planner.py` (2050 righe) → moduli `filters.py`, `scoring.py`,
   `clustering.py`, `scheduling.py`, `opening_hours.py`. Solo dopo le fasi 1–2 (i diff
   restano leggibili).
6. **Family teen vs toddler** (già in Limitations cap. 6): granularità età bambini.

---

## Fase 4 — Evaluation e tesi

1. **Re-run 2×2 unica post-Fase-1(+2)** con `toptw_solution_limit > 0` per il
   determinismo; annotare in cap. 6 la versione valutata.
2. **Effect sizes**: rank-biserial (o Cliff's delta) + CI bootstrap accanto ai Wilcoxon
   in `evaluation/paired_tests.py` — risponde alla Limitation "limited inferential
   analysis" a basso costo.
3. **Nuove metriche nei risultati**: `tw_violation_rate` (nuova evidenza per RQ1b),
   `meal_timing_deviation`, `walk_km_per_day` (per RQ2, profili senior/family).
4. **Human eval anticipata** (decisione 2026-06-29): lanciarla sui piani post-fix, non
   su quelli attuali.
5. **Benchmark già promessi nelle Limitations**: cold-cache e sweep di
   `toptw_num_candidates` (2 script sull'harness esistente).
6. **Aggiornamenti tesi**: cap. 5 §Limitations (split windows risolte con
   `RemoveInterval`, last-entry modellato); cap. 5 §Meal Insertion (attesa apertura);
   cap. 6 §Protocol (start_date, versione valutata, nuove metriche).

---

## Ordine consigliato

| # | Item | Effort | Perché in quest'ordine |
|---|------|--------|------------------------|
| 1 | 1.1 orari overnight/24-7 + test | S | Massimo impatto/effort; sblocca 1.2 e 2.1 |
| 2 | 1.2 metriche realismo | S | Da qui in poi ogni fix è misurabile |
| 3 | 1.3–1.5 greedy recheck, last-entry, attesa pasti | S/M | Correttezza percepita dei piani |
| 4 | 1.6 start_date (+1.7) | S | Weekday corretti; riproducibilità eval |
| 5 | 2.1 RemoveInterval | M | Rimuove una Limitation dichiarata |
| 6 | 2.2 type-cap nel solver | M | Attacca gli idle 76' alla radice |
| 7 | 2.3–2.4 buffer + transit fisso | S | Realismo tempi, A/B-abile |
| 8 | Fase 4 re-run + effect sizes | M | Una sola run, numeri finali per la tesi |

Fase 3: solo dopo, in base al tempo rimasto verso la consegna (ottobre 2026).
