# Spec: Miglioramenti al motore di generazione itinerari

## Stato attuale — problemi identificati dai log

Generazione di Madrid, 3 giorni, 152 POI attività disponibili:

```
total_scheduled=18  (6 stop/giorno in media)
Day 1 ends at 15:52  (finestra 09:00–22:00 = 13h, usate ~7h)
Day 2 ends at 12:37  (solo 3h37min di attività)
Day 3 ends at 14:02
Dinner not inserted — 3 giorni su 3
```

Con 152 POI e 13 ore di finestra giornaliera ci si aspettano 8–10 stop/giorno. Il motore ne produce 6 perché si svuota prematuramente. Di seguito i 4 bug e 1 miglioramento strutturale che causano questo comportamento.

---

## Bug 1 — MMR buffer hardcoded a k=15 (causa principale)

### Problema

In `generate()`, il buffer MMR è fisso:

```python
candidates = _mmr_select(..., k=15, ...)
```

Il buffer serve come riserva: alcuni POI saranno chiusi quel giorno e verranno saltati dallo scheduler. Con k=15 e molte chiusure (musei chiusi il lunedì, chiese a orari ridotti), il giorno finisce con 4–6 attività invece di 8–10.

L'assunzione implicita è che ~50% dei candidati sia aperto. Se il tasso di chiusura è più alto (es. giorno feriale con molti musei), il buffer si svuota prima di riempire la giornata.

### Fix proposto

Calcolare k dinamicamente in base alla durata della finestra giornaliera:

```python
day_hours = (eh * 60 + em - sh * 60 - sm) / 60          # ore disponibili
avg_stop_minutes = 75                                      # stima media per stop
estimated_stops = int(day_hours * 60 / avg_stop_minutes)  # ~10 per 13h
k = min(len(candidate_pois_only), max(25, estimated_stops * 3))
```

Il fattore ×3 garantisce una riserva sufficiente anche con tasso di chiusura 60–70%.

**Impatto atteso:** giorni che si riempiono fino a 19:00–22:00 invece di fermarsi a 12:37.

---

## Bug 2 — Food reuse tra giorni diversi

### Problema

Il flag `used_food_ids` viene aggiornato solo per i ristoranti effettivamente inseriti nell'itinerario finale:

```python
# In generate(), dopo _schedule_day():
for s in stops:
    if any(t in FOOD_TYPES for t in (s.poi.types or [])):
        used_food_ids.add(s.poi.id)
```

Se un ristorante viene pre-selezionato come cena per il Giorno 1 ma non viene mai inserito (perché il giorno finisce troppo presto), rimane disponibile nel pool del Giorno 3. Nei log:

```
Cluster 0: Dinner pre-selected = FIERA → not inserted (arrives 15:58, before DINNER_MIN_H)
Cluster 2: Lunch selected = FIERA  ← stesso ristorante
```

### Fix proposto

`_schedule_day` deve restituire anche i ristoranti pre-selezionati ma non inseriti. `generate` li marca come usati indipendentemente dall'inserimento:

```python
# Modifica firma _schedule_day:
def _schedule_day(...) -> tuple[list[_Stop], list[tuple[Poi, float]], set]:
    # terzo elemento: reserved_food_ids (pre-selected ma non inseriti)
    ...
    reserved_food_ids = set()
    if lunch_poi and not lunch_inserted:
        reserved_food_ids.add(lunch_poi.id)
    if dinner_poi and not dinner_inserted:
        reserved_food_ids.add(dinner_poi.id)
    return final_stops, deferred_activities, reserved_food_ids

# In generate():
stops, deferred, reserved = await loop.run_in_executor(...)
used_food_ids.update(reserved)
for s in stops:
    if any(t in FOOD_TYPES for t in (s.poi.types or [])):
        used_food_ids.add(s.poi.id)
```

---

## Bug 3 — Deferred POI geograficamente lontani dal giorno successivo

### Problema

I POI saltati per orari di apertura vengono preposti al pool del giorno successivo senza filtraggio geografico:

```python
all_candidates = global_deferred + cluster_scored
```

Un POI del Cluster 0 (centro=(40.4438, -3.6906)) viene portato nel Cluster 2 (centro=(40.4169, -3.7199)), a ~3 km di distanza. Questo:
1. Inquina la selezione MMR con POI lontani dal cluster del giorno
2. Spreca slot del buffer (k=15) su POI che, se schedulati, creerebbero tratte di trasferimento lunghe

### Fix proposto

Filtrare i deferred per distanza massima dal centro del giorno successivo prima di prependerli:

```python
MAX_DEFERRED_DISTANCE_M = 4000  # 4 km dal centro del cluster

# Prima del loop MMR nel giorno successivo:
filtered_deferred = [
    (p, score) for p, score in global_deferred
    if haversine_m(p.lat, p.lng, center_lat, center_lng) <= MAX_DEFERRED_DISTANCE_M
]
truly_lost = [
    (p, score) for p, score in global_deferred
    if haversine_m(p.lat, p.lng, center_lat, center_lng) > MAX_DEFERRED_DISTANCE_M
]
all_candidates = filtered_deferred + cluster_scored
# I truly_lost vengono scartati (erano chiusi il giorno giusto e troppo lontani per il giorno dopo)
```

---

## Bug 4 — Cena non inserita quando il giorno finisce presto

### Problema

La cena viene pre-selezionata ma non inserita perché il giorno finisce prima delle 18:00 (DINNER_MIN_H). Il post-loop check è:

```python
if arrival < dinner_min_dt:
    logger.warning("Dinner not inserted ... arrival %s is before minimum dinner hour", ...)
```

Quando il giorno finisce alle 12:37 (Bug 1), la cena arriverebbe alle 14:06 — troppo presto. La logica è corretta (non si cena alle 14), ma la causa a monte è il buffer insufficiente che svuota il giorno troppo presto.

Risolvendo Bug 1 il giorno si riempie fino alle 19:00–22:00 e la cena viene inserita naturalmente. Tuttavia, come safety net aggiuntivo, se le attività finiscono prima di DINNER_MIN_H ma c'è ancora tempo utile prima di end_dt:

```python
# Dopo il loop attività, se dinner_poi non è stato inserito:
if has_activities and dinner_poi and not dinner_inserted:
    # Prova a forzare la cena al primo slot valido dopo DINNER_MIN_H
    dinner_min_dt = day_date.replace(hour=DINNER_MIN_H, minute=0)
    candidate_arrival = max(cur + timedelta(minutes=15), dinner_min_dt)
    if candidate_arrival + timedelta(minutes=get_food_duration(dinner_poi)) <= end_dt:
        _add_food_stop_at(dinner_poi, candidate_arrival)  # versione che accetta orario forzato
        dinner_inserted = True
```

Questo richiederebbe un helper `_add_food_stop_at(poi, forced_arrival)` che bypassa il calcolo del tempo corrente.

---

## Miglioramento strutturale — Leiden: bilanciamento merge

### Problema residuo

Dopo il fix con penalità size-aware, il merge produce ancora cluster sbilanciati (38 / 54 / 77) perché la penalità `min(merged_size / target_size, 3.0)` è lineare e non abbastanza forte per distribuzioni molto asimmetriche.

### Fix proposto

Usare una penalità quadratica e considerare anche la dimensione del cluster ricevente (non solo quella del merge):

```python
# Score = geo_dist * (1 + alpha * (merged_size - target_size)^2 / target_size^2)
alpha = 2.0  # peso della penalità di sbilanciamento
imbalance = 1.0 + alpha * ((merged_size - target_size) ** 2) / (target_size ** 2)
score = geo_dist * imbalance
```

Con target_size=50 (152/3):
- Merge da 38+19=57: imbalance = 1 + 2*(7/50)² ≈ 1.04 → quasi neutro
- Merge da 77+38=115: imbalance = 1 + 2*(65/50)² ≈ 4.38 → fortemente penalizzato

---

## Priorità di implementazione

| # | Fix | Impatto | Complessità |
|---|-----|---------|-------------|
| 1 | MMR buffer dinamico | Alto — risolve giorni vuoti | Bassa (2 righe) |
| 2 | Food reuse | Medio — correttezza dati | Media (refactor firma) |
| 3 | Deferred filtering | Medio — qualità geografica | Bassa (5 righe) |
| 4 | Dinner safety net | Basso — dipende dal fix #1 | Media |
| 5 | Leiden penalty quadratica | Basso — già migliorato | Bassa (1 riga) |

**Raccomandazione:** implementare #1 e #3 subito (massimo impatto, minima complessità). #2 e #5 nella stessa sessione. #4 solo dopo aver verificato che #1 non risolva già il problema della cena.
