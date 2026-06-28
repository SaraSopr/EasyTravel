# Generazione itinerario — Solver greedy (baseline)

> **Cos'è**: il pipeline storico `clustering geografico → MMR → scheduling greedy` che genera un
> itinerario multi-giorno. È il **baseline** del confronto di tesi contro il solver TOPTW
> (`docs/toptw-itinerary-solver-spec.md`). Entrambi ricevono gli stessi candidati, gli stessi tempi
> di viaggio reali e gli stessi pre-filtri → confronto equo.
>
> **File**: `backend/app/services/itinerary_planner.py` (tutte le `:NNN` sotto si riferiscono a
> questo file salvo diversa indicazione).
>
> **Entry point**: `async def plan(...)` (`:1620`). Dispatch sul solver in `:1741`:
> ```python
> chosen_solver = (solver or settings.itinerary_solver or "greedy").lower()
> ```
> `solver` è il parametro di request; `settings.itinerary_solver` ha default **`"toptw"`**
> (`config.py:54`); `"greedy"` è solo l'ultimo fallback se entrambi sono vuoti.

---

## 0. Rappresentazione dati

### Vettore feature (7 dim, ordine fisso) — `app/constants.py:13`
```
[nature, culture, food, adventure, nightlife, relax, family_friendly]
```
- `_poi_vec(poi)` (`:644`) = `np.array([getattr(poi, k) or 0.0 for k in FEATURE_NAMES])`.
- `_user_vec(prefs)` (`:648`) idem sulle colonne di `UserPreference`.
- `_cosine_sim(a, b)` (`:691`) = `dot(a,b) / (‖a‖·‖b‖)`, **0.0** se una delle norme è 0.

### `_Stop` (dataclass, `:279`) — unità di output
```python
poi, arrival, departure,
transport: str | None,            # None per la prima tappa del giorno
travel_minutes: float,
similarity_score: float,          # cosine grezza (NON lo score MMR)
visit_mode: str,                  # "indoor" | "outdoor"
visit_duration_minutes: int,
visit_note: str | None            # es. "Suggested as an exterior visit"
```

### `TravelLookup` (`:553`)
`dict[(origin_poi_id, dest_poi_id, db_mode)] → (minutes, meters)`, dove `db_mode ∈ {walking, driving}`.

---

## 1. Pre-processing condiviso (`plan`, `:1656-1738`)

Questi passi avvengono **prima** del dispatch, quindi valgono anche per il TOPTW.

1. **User vector** (`:1660-1661`):
   `uvec = _apply_mode_bias(_user_vec(prefs), travel_mode)`.
   `_apply_mode_bias` (`:682`): `biased = clip(uvec + bias, 0, None)`, poi **L2-normalizza**. Bias per
   modo (`_MODE_BIAS`, `:674`), nell'ordine feature:

   | mode | nature | culture | food | adventure | nightlife | relax | family |
   |---|---|---|---|---|---|---|---|
   | solo | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
   | couple | 0 | 0.05 | 0.1 | 0 | 0 | 0.15 | −0.1 |
   | friends | 0 | 0 | 0.05 | 0.15 | 0.2 | 0 | −0.1 |
   | family | 0.05 | 0 | 0.05 | 0.05 | −0.5 | 0 | 0.3 |

2. **Soglia cammino** (`:1666`): `walk_threshold_m = compute_walk_threshold_m(age_range, relax)`
   (`:515`). Se `walk_personalization` è off → `walk_threshold_base_m = 800`. Altrimenti:
   ```
   raw = 800 · age_factor · (walk_relax_base − walk_relax_slope · relax)
       = 800 · age_factor · (1.15 − 0.45 · relax)      relax ∈ [0,1]
   walk_threshold_m = clamp(raw, 350, 2000)
   ```
   `age_factor` (`_AGE_WALK_FACTOR`, `:159`): 18-25→1.6, 26-35→1.4, 36-45→1.2, 46-55→1.0,
   55-70→0.75, 70+→0.55, sconosciuto→1.0. **Deve** coincidere tra prefetch e scheduling, altrimenti
   il lookup dei tempi reali sbaglia chiave e ricade su haversine.

3. **`proximity_km`** (`:1662`, `_proximity_km_for_profile`, `:1110`): senior→2.5, con bambini→3.0,
   altrimenti→5.0. Usata nello scoring di prossimità.

4. **Split food / attività** (`:1675-1676`):
   - food se `travel_category == "food"` **oppure** `is_actual_food_poi(p)` (`:188`: ha un tipo in
     `FOOD_SERVICE_TYPES`, primary non in `{night_club, casino}`, category ∈ `{food, None}`);
   - attività = tutto il resto.

5. **Filtro touristic** (`:1679-1680`): `is_touristic` (`:176`) — escluso se **un qualsiasi** tipo
   (non solo il primary) è in `EXCLUDED_TYPES`. Applicato a entrambi i pool (safety ridondante).

6. **Filtro raggio città** (`:1687-1699`, solo attività): `resolve_activity_radius_m` (`:467`):
   - `min_radius = clamp(activity_radius_km, 0, 20)·1000` (default `activity_radius_km=8` → 8 km),
     `max_radius = MAX_CITY_RADIUS_KM·1000 = 20 km`.
   - **`fixed`** → ritorna `min_radius`.
   - **`adaptive`** (default): ordina le distanze dei POI dal centro (scartando > 20 km), prende
     ```
     min_count   = max(num_days·2, num_days · activity_radius_min_pois_per_day)   # default 8/giorno
     share_count = ceil(len(distanze) · activity_radius_target_share)             # default 0.85
     target      = min(len, max(min_count, share_count))
     radius      = clamp(distanze[target-1], min_radius, max_radius)
     ```
   I food **non** sono filtrati per raggio.

7. **Famiglia** (`:1702-1703`): se `travel_mode == "family"` rimuove le attività `travel_category == "nightlife"`.

8. **Guard rail** (`:1710-1718`): se `len(activity_pois) < num_days·2` → `HTTPException(422)`.

9. **Popularity** (`:1728`, `compute_popularity_scores`, `:1062`): media bayesiana IMDb-style
   ```
   m = median(user_ratings_total)   C = mean(rating)        # solo su POI con entrambi
   raw(p) = (v·R + m·C) / (v + m)                           # v=ratings_total, R=rating
   ```
   poi **min-max normalizzata** su `[0,1]`; POI senza rating/conteggio → **0.5** neutro.

10. **Food ordinati** (`:1738`): `food_pois.sort` per cosine decrescente (pool globale condiviso tra i giorni).

---

## 2. Livello 1 — Clustering geografico (`_cluster_pois`, `:828`)

Partiziona le attività in `num_days` zone coese. **Casi speciali** (`:843`): `num_days == 1` o
`len < num_days·2` → unico cluster `{0: tutte}`.

### 2a. Leiden (primario, `_cluster_pois_leiden`, `:713`)

1. **Matrice distanze** Haversine completa `n×n` (`:735`).
2. **k-NN**: per ogni nodo i `k = min(10, n-1)` vicini più prossimi (escluso sé).
3. **Scala adattiva**: `σ = max(median(tutte le distanze k-NN), 1.0)` (`:756`).
4. **Grafo pesato non orientato** (`igraph`): per ogni arco `(i,j)` k-NN, peso `exp(−d_ij / σ)`
   (archi deduplicati, `:758-767`).
5. **Community detection**: `leidenalg.find_partition(g, ModularityVertexPartition, weights="weight", seed=42)`
   (`:773`). Il numero di comunità **non** è imposto.
6. Se `#comunità < num_days` → `ValueError` → fallback KMeans (`:791-794`).
7. **Merge gerarchico size-aware** (`:802-823`) finché `#comunità > num_days`. A ogni passo calcola i
   centroidi e fonde la coppia che minimizza:
   ```
   score(i,j) = haversine(centroid_i, centroid_j) · imbalance
   imbalance  = 1 + 2 · (merged_size − target_size)² / target_size²
   target_size = len(activity_pois) / num_days
   ```
   (penalità quadratica → impedisce a un cluster di fagocitare tutto.)

### 2b. KMeans (fallback, `:854-903`)
Attivato su `ImportError` (`leidenalg`/`igraph` assenti) o qualsiasi eccezione di Leiden.
- `KMeans(n_clusters=num_days, random_state=42, n_init=10)` su `(lat,lng)` grezzi (`:858`).
- Cluster con esattamente 1 POI → fusi nel cluster ≥2 più vicino per centroide (`:865-882`).
- Se `#cluster < num_days`: **split** ricorsivo del cluster più grande (KMeans k=2) finché possibile
  o finché il più grande ha < 4 POI (`:886-901`).

### 2c. Rebalance (`_rebalance_clusters`, `:911`)
`_MIN_CLUSTER_SIZE = 10`. Per ogni cluster sotto soglia (ordine di id), in ordine di distanza dal suo
centroide, **sposta** (non copia) i POI più vicini da cluster donatori, ma solo se il donatore resta
`> 10` dopo il trasferimento. Se nessun donatore può cedere, prende quanti ne può. Garantisce
candidati a sufficienza per riempire la giornata.

> Dopo questi passi `actual_days = len(clusters)`; se `< num_days` viene emesso un warning (`:1788`).

---

## 3. Loop per-giorno (`plan`, `:1815-1931`)

Cluster ordinati per id; `day_idx` → data progressiva da oggi (00:00 + `day_idx` giorni), orari
giornata da `start_time_str`/`end_time_str`.

### 3a. Candidati del giorno
- **Scoring cosine** dei POI del cluster (`:1821-1823`).
- **Centro** = `_cluster_center` (`:1055`, media aritmetica lat/lng) sui soli POI del giorno; se il
  cluster ha 1 POI → centro città (`:1827-1830`).
- **Deferred dal giorno prima** (`global_deferred`): POI saltati ieri per orari, riproposti oggi solo
  se entro `_MAX_DEFERRED_M = 4000 m` dal centro odierno (`:1832-1838`). `all_candidates = filtered_deferred + cluster_scored`; `global_deferred` viene azzerato.

### 3b. Livello 2 — MMR (`_mmr_select`, `:1174`)
**Buffer** (`:1853-1855`):
```
day_minutes     = (eh·60+em) − (sh·60+sm)
estimated_stops = max(1, day_minutes // 75)            # ~75 min per tappa
mmr_k           = min(len(all_candidates), max(25, estimated_stops · 3))   # sovra-campiona
```
**Rilevanza** di un POI = `apply_novelty_penalty(_combined_score(...))`:
- `_combined_score` (`:1122`):
  ```
  score = 0.5·cosine + 0.3·proximity + 0.2·popularity   (+0.15 se landmark), poi min(·,1.0)
  proximity = 1 − min(dist_dal_centro / (proximity_km·1000), 1)
  popularity = popularity_scores[id]  (default 0.5)
  landmark   = user_ratings_total ≥ 10000  →  +LANDMARK_BOOST (0.15)
  ```
- `apply_novelty_penalty` (`:427`): confirmed-visited → **×0.0** (in fondo, non escluso); suggerito
  negli ultimi `IMPLICIT_WINDOW_DAYS = 365` giorni e **non** landmark → **×0.6**; altrimenti invariato.

**Algoritmo MMR** (`:1191-1210`):
- **Primo**: `argmax` della rilevanza penalizzata (nessuna penalità di diversità).
- **Successivi**: `argmax  λ·rilevanza − (1−λ)·ridondanza`, con `λ = MMR_LAMBDA = 0.6`.
  - **Penalità dura** (`:1200-1202`): se il candidato è entro `MMR_MIN_DISTANCE_M = 150 m` da un POI
    già scelto → score `−1.0` (duplicati tipo Bernabéu + Tour Bernabéu).
  - `_poi_redundancy` (`:1150`): `max` su tutti i selezionati di `min(cosine + category_penalty, 1)`,
    con `category_penalty = SAME_CATEGORY_PENALTY = 0.3` se stessa `travel_category` (non None).
- Ritorna `[(poi, cosine_grezza)]` — la cosine, non lo score MMR, serve dopo in `resolve_visit_mode`.

### 3c. Prefetch tempi reali (`:1879-1890`, `prefetch_travel_matrix`, `:586`)
Solo se `session is not None` e `routes_api_enabled`. Per **ogni coppia diretta** dei candidati MMR
decide il modo con `select_transport(haversine, walk_threshold_m)`, raggruppa per `db_mode` e fa una
chiamata batch per modo a `routes_client.get_travel_times_batch` (cache-first). Errori → log + fallback
haversine (mai bloccante). Così `_schedule_day` resta sincrono e senza I/O.

---

## 4. Scheduling di una giornata (`_schedule_day`, `:1219`)

Tre pass. Ritorna `(final_stops, deferred_activities, reserved_food_ids)`.

### Modello di viaggio (`_travel`, `:556` + `select_transport`, `:533`)
- **Modo** dalla distanza Haversine e dalla soglia: `< walk_threshold_m`→`walking`;
  `< TAXI_THRESHOLD_M (5000)`→`transit`; altrimenti→`taxi`.
- **Minuti**: dalla cache se c'è hit su `(origin_id, dest_id, _SCHED_TO_DB_MODE[mode])` — dove
  `transit` e `taxi` mappano entrambi su `driving`; per `transit` i minuti driving sono scalati per
  `transit_driving_factor = 1.5`. Senza hit → stima haversine `(dist / SPEED_MS[mode]) / 60`, con
  `SPEED_MS = {walking 1.39, transit 5.56, taxi 8.33} m/s`.

### Apertura (`_is_open`, `:617`)
Nessun `opening_hours` o nessun `periods` → **sempre aperto**. Altrimenti, mappa il giorno Python
(`weekday()` 0=lun) su Google (`google_day = (py_day+1) % 7`, 0=dom), confronta `HHMM`
(`hour·100+minute`) contro i `periods` del giorno; close mancante → `2359`. Parsing in errore → True.

### Durata visita (`resolve_visit_mode`, `:331`)
Priorità a `tourism_duration_minutes`/`tourism_visit_type` se presenti (per `both`: se
`cosine < 0.3` → outdoor con durata `min(dur, 30)` e nota "exterior visit"). Altrimenti:
- food → `indoor`, `get_food_duration`;
- `is_indoor_visitable is False` → `outdoor`;
- indoor (esplicito o inferito da `_NEEDS_HOURS_TYPES`) con `cosine ≥ OUTDOOR_VISIT_THRESHOLD (0.3)`
  → `indoor`; sotto soglia → `outdoor` + nota "Suggested as an exterior visit";
- altrimenti → `outdoor`.

`get_*_duration` (`:296-328`) prendono il **massimo** sulla tabella per tutti i tipi del POI:

| tabella | valori (min) |
|---|---|
| INDOOR | museum 120, art_gallery 90, church 45, library 45, aquarium 90, zoo 150, amusement_park 180, stadium 120, tourist_attraction 90, **default 60** |
| OUTDOOR | park 45, campground 60, natural_feature 20, tourist_attraction 45, point_of_interest 30, **default 30** |
| FOOD | restaurant 75, cafe 30, bakery 20, bar 45, meal_takeaway 15, **default 45** |

### Pass 1 — Selezione greedy + ancore pasti (`:1294-1383`)
Stato: `current` (tempo), `(current_lat, current_lng, current_id)` partendo dal **centro città**
(depot). Scorre `activity_candidates` in **ordine MMR**:

1. **Finestre pasto** (in cima a ogni iterazione, prima il pranzo poi la cena): quando
   `current ≥ target − MEAL_WINDOW_MIN`, con `LUNCH_TARGET_H=13`, `DINNER_TARGET_H=20`,
   `MEAL_WINDOW_MIN=30` (→ apertura 12:30 / 19:30), seleziona il ristorante con
   `_pick_nearest_open_food(meal_only=True)`; se None ritenta `meal_only=False`. Avanza `current` di
   `get_food_duration` e sposta la posizione sul ristorante. Flag `lunch_done`/`dinner_done` evitano
   ripetizioni.
   - `_pick_nearest_open_food` (`:1262`) filtra i food non usati, aperti a `t`, (eventualmente
     `is_meal_poi`), con `is_food_price_acceptable`, e delega a `pick_best_food`.
   - `pick_best_food` (`:251`): tra gli `eligible (poi, dist)` entro `food_pick_radius_m=700` prende
     l'**argmax** di `score_food_candidate`; se nessuno entro il raggio → il **più vicino**.
     `score = food_w_distance·proximity + food_w_rating·rating − [takeaway] food_takeaway_penalty + 0.01·pop`
     = `0.6·proximity + 0.4·(rating/5) − 0.3·takeaway + 0.01·pop`, `proximity = max(0, 1 − dist/700)`,
     rating mancante → 3.5/5.
   - **Cap prezzo** (`food_price_level_limit`, `:652`): interesse food `<0.35`→max level 2,
     `<0.70`→3, altrimenti nessun cap.
2. **Viaggio** al POI (`_travel`) → `arrival`.
3. **Apertura**: se chiuso, prova ad attendere a passi di 5 min fino a +90 min (interrompendo se
   supera `end_dt`); se non apre → **defer** (`deferred_activities.append`, `continue`); altrimenti
   `arrival = wait_arrival` (`:1357-1371`).
4. **Durata** = `resolve_visit_mode`; `departure = arrival + visit_dur`.
5. **Se `departure > end_dt` → `continue`** (non `break`): un POI lungo non chiude la giornata,
   candidati successivi più brevi/vicini possono ancora entrare *(miglioramento §6)*.
6. Altrimenti accetta: aggiorna `used_activity`, `selected_activities`, posizione e `current`.

**Pre-selezione pasti mancati** (`:1379-1402`): se a fine loop pranzo/cena non sono stati scelti
(es. tutte le attività finite prima dell'ora pasto), si pre-seleziona comunque il ristorante migliore
all'ora target, da inserire in Pass 3.

### Pass 2 — TSP (`_solve_tsp`, `:696`, chiamato `:1407`)
Riordina le **sole attività** selezionate per minimizzare il viaggio dal depot. OR-Tools
`RoutingIndexManager(n, 1, 0)` (1 veicolo, depot = nodo 0), matrice costi = Haversine in **metri
interi**, `FirstSolutionStrategy.PATH_CHEAPEST_ARC`, `time_limit = 5 s`. Se nessuna soluzione →
ordine invariato. I pasti **non** entrano nel TSP.

### Pass 3 — Ri-propagazione tempi (`:1411-1542`)
Ricostruisce gli orari lungo l'ordine TSP partendo di nuovo dal depot. Due helper:
- `_add_food_stop(poi, forced_arrival=None)` (`:1421`): viaggio (0 se prima tappa), durata food,
  `similarity_score = 1.0`, append, avanza stato.
- `_add_activity_stop(poi, sim)` (`:1449`): viaggio, `arrival`, `resolve_visit_mode`, `departure`.
  Ritorna **False** (non inserisce) se:
  1. `departure > end_dt`;
  2. **protezione cena**: `dinner_poi` non ancora inserita e `departure + 15 + get_food_duration(dinner) > end_dt`;
  3. **cap per tipo**: `_PRIMARY_TYPE_DAY_CAP` raggiunto — `church 2`, `place_of_worship 2`,
     `tourist_attraction 5` (anti "church fatigue").

  Su successo incrementa `type_counts[primary]` e avanza lo stato.

Loop principale (`:1507-1521`): per ogni attività nell'ordine TSP inserisce pranzo/cena se la finestra
è entrata (`cur ≥ target − 30`), poi `_add_activity_stop`; se torna False → `break`.

**Refill post-TSP** *(miglioramento §6, `:1523-1542`)*: poiché il TSP accorcia il viaggio rispetto a
Pass 1, spesso avanza tempo. Si ripescano, in ordine MMR, le attività **non** usate e **non** deferite,
ri-controllando l'apertura all'orario di arrivo reale (`_is_open(cur + travel)`) e delegando gli altri
vincoli a `_add_activity_stop`. Inserito prima dei pasti post-loop → la cena resta l'ultima tappa.

**Pasti post-loop** (`:1544-1574`): solo se la giornata ha ≥1 attività. Pranzo inserito se entra entro
`end_dt`. Cena: se l'arrivo è prima di `DINNER_MIN_H = 18` viene **forzata** a 18:00 (se entra),
altrimenti inserita all'orario calcolato se entra. Food pre-selezionati ma non inseriti →
`reserved_food_ids` (per non riusarli il giorno dopo).

---

## 5. Aggregazione e warning (`plan`, `:1909-1946`)

- `deferred` del giorno → `global_deferred` per il giorno successivo (filtrato in 3a).
- `used_food_ids` accumula food **inseriti** + `reserved` → condivisi tra i giorni (`:1914-1917`).
- Giorni senza tappe → warning + skip (`:1919-1921`).
- Warning aggiuntivi: meno giorni di attività del richiesto; >60% dei POI già visti/suggeriti
  (`:1799`); giornata che finisce > 2 h prima di `end_dt` (`:1925`); "Some POIs could not be scheduled
  due to opening hours" se ci sono stati deferral (`:1933`).
- Output: `(all_days, warnings)` con `all_days: list[list[_Stop]]`.

---

## 6. Miglioramenti applicati al baseline

In `_schedule_day`, due interventi a basso rischio che rendono il baseline *equo*:

1. **`continue` invece di `break` in Pass 1** (`:1375-1378`): il primo POI che sfora `end_dt` non
   interrompe più l'intera giornata.
2. **Refill post-TSP in Pass 3** (`:1523-1542`): sfrutta il tempo liberato dal riordino TSP per
   inserire altre attività rimaste fuori, rispettando apertura, cap per tipo e slot cena.

Entrambi riducono l'*under-fill* senza cambiare la natura greedy del solver.

### Limiti residui noti (by design — sono ciò che il TOPTW supera)
- **Selezione in ordine di rilevanza, non geografico** (Pass 1): il percorso può zigzagare; il TSP
  corregge l'ordine *dopo* che il numero di tappe è già deciso (il refill mitiga, non elimina).
- **Giorni indipendenti**: il clustering è cieco alla rilevanza e ogni giorno è ottimizzato in
  isolamento; nessuna garanzia globale sui must-see.
- **Disallineamento ristorante**: il meal-POI è scelto sulla posizione di Pass 1 ma inserito sul
  percorso riordinato dal TSP (orario valido, ma possibile deviazione).

Vedi `docs/itinerary-quality-analysis.md` (cause #5–#8) e `docs/toptw-itinerary-solver-spec.md`.

---

## 7. Costanti e parametri

### In `itinerary_planner.py` (`:110-167`)
| Costante | Valore | Significato |
|---|---|---|
| `MMR_LAMBDA` | 0.6 | peso rilevanza vs diversità in MMR |
| `MMR_MIN_DISTANCE_M` | 150 m | sotto questa distanza due POI = duplicati (score −1) |
| `SAME_CATEGORY_PENALTY` | 0.3 | extra ridondanza per stessa `travel_category` |
| `_MIN_CLUSTER_SIZE` | 10 | soglia sotto cui un cluster prende in prestito |
| `_MAX_DEFERRED_M` | 4000 m | distanza max per riproporre un deferred |
| `LUNCH_TARGET_H` / `DINNER_TARGET_H` | 13 / 20 | ore target pasti |
| `MEAL_WINDOW_MIN` | 30 | anticipo apertura finestra pasto |
| `DINNER_MIN_H` | 18 | la cena post-loop non scatta/forza prima |
| `OUTDOOR_VISIT_THRESHOLD` | 0.3 | sotto questa cosine → visita esterna |
| `LANDMARK_THRESHOLD` / `LANDMARK_BOOST` | 10000 / +0.15 | landmark globale e bonus |
| `_PRIMARY_TYPE_DAY_CAP` | church 2 / place_of_worship 2 / tourist_attraction 5 | cap per tipo/giorno |
| `CONFIRMED_VISITED_SCORE` | 0.0 | moltiplicatore POI già visitati |
| `IMPLICIT_SUGGESTED_PENALTY` | 0.6 | moltiplicatore POI suggeriti negli ultimi 12 mesi |
| `IMPLICIT_WINDOW_DAYS` | 365 | finestra del segnale "suggerito" |
| `MAX_CITY_RADIUS_KM` | 20 | tetto duro raggio città |
| `DEFAULT_WALK_THRESHOLD_M` / `TAXI_THRESHOLD_M` | 800 / 5000 | soglie modo di trasporto |
| `SPEED_MS` | walk 1.39 / transit 5.56 / taxi 8.33 | velocità haversine (m/s) |

### In `app/config.py` (settings — A/B-abili via env)
| Setting | Default | Uso |
|---|---|---|
| `itinerary_solver` | `"toptw"` | scelta solver (`"greedy"` per questo path) |
| `walk_personalization` | True | attiva la soglia cammino personalizzata |
| `walk_threshold_base_m` / `_min_m` / `_max_m` | 800 / 350 / 2000 | base e clamp soglia |
| `walk_relax_base` / `_slope` | 1.15 / 0.45 | `relax_factor = base − slope·relax` |
| `transit_driving_factor` | 1.5 | scala minuti driving → transit |
| `activity_radius_mode` | `"adaptive"` | `fixed` \| `adaptive` |
| `activity_radius_km` | 8 | raggio fisso / floor compatto |
| `activity_radius_target_share` | 0.85 | quota POI coperta in adaptive |
| `activity_radius_min_pois_per_day` | 8 | minimo POI/giorno in adaptive |
| `food_pick_radius_m` | 700 | raggio di considerazione ristorante |
| `food_w_distance` / `food_w_rating` / `food_takeaway_penalty` | 0.6 / 0.4 / 0.3 | pesi scoring pasto |
