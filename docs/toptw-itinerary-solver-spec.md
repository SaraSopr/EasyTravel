# Spec — Solver itinerari TOPTW (Team Orienteering Problem with Time Windows)

> **Obiettivo**: sostituire il pipeline attuale `clustering → MMR → scheduling greedy` con un
> **unico solver di ottimizzazione** che, su tutti i giorni insieme, massimizza la rilevanza
> totale dei POI inclusi rispettando orari di apertura, durate di visita, budget tempo giornaliero
> e tempi di viaggio **reali**.
>
> **Problema risolto**: cause #5–#8 di `docs/itinerary-quality-analysis.md` — clustering cieco
> alla rilevanza, nessuna garanzia must-see, giorni greedy e indipendenti, deferral per orari che
> taglia tappe. Il TOPTW le elimina tutte by design.
>
> **Modello accademico**: Team Orienteering Problem with Time Windows (Vansteenwegen, Souffriau,
> Van Oudheusden — survey "The Orienteering Problem", 2011; Gunawan et al. survey 2016). È *il*
> modello standard per il Tourist Trip Design Problem.
>
> **Implementazione**: OR-Tools routing solver (`pywrapcp`) — lo stesso già usato per il TSP in
> `backend/app/services/itinerary_planner.py:431` (`_solve_tsp`). Continuità tecnologica.

---

## ⚠️ Dipendenza dura

Questo solver **consuma i tempi di viaggio reali** prodotti da
`docs/routes-api-travel-times-spec.md` (cache `poi_travel_times`). Implementare PRIMA quella spec.
Senza, il TOPTW ottimizzerebbe su tempi finti e perderebbe gran parte del valore. In assenza di
cache deve comunque funzionare con fallback haversine (degradato ma non rotto).

---

## Decisioni già prese (non rimetterle in discussione)

1. **Pasti**: gestiti con **post-inserimento sul percorso ottimizzato** (NON come nodi del solver).
   Il solver riserva un blocco di tempo nel budget e ottimizza solo le attività; un post-pass
   inserisce il ristorante migliore aperto nella finestra pasto lungo la rotta già ottimizzata.
2. **Depot opzionale**: input `start_location` / `end_location` (indirizzo o hotel). Se assenti →
   centro città (`city_lat/lng`). Supportati start/end diversi per giorno via OR-Tools.
3. **Il sistema attuale (cluster→MMR→greedy) NON si elimina**: diventa il **baseline** per la
   evaluation. Il TOPTW è un percorso parallelo selezionabile via flag.

---

## 0. Switch e baseline

In `app/config.py`:
```python
itinerary_solver: str = "greedy"   # "greedy" (attuale, baseline) | "toptw" (nuovo)
```
La funzione pubblica `generate()` in `itinerary_planner.py` dispatcha sul solver scelto. Entrambi
ricevono gli stessi input (prefs, candidati, depot, tempi reali) → confronto equo nella evaluation.
Esporre anche come parametro opzionale del request `GenerateItineraryRequest.solver` per poter
generare i due bracci dallo stesso utente/città.

---

## 1. Input: depot opzionale

In `app/schemas/itinerary.py` → `GenerateItineraryRequest` aggiungere:
```python
start_location: str | None = None   # indirizzo o nome hotel; None → centro città
end_location: str | None = None     # None → uguale a start_location, se anch'esso None → centro
```
Nel router `itineraries.py`:
- se valorizzati, geocodificare l'indirizzo → (lat, lng). Riusare il geocoding Google
  (`GOOGLE_GEOCODING_URL` in `pipeline/fetcher.py`) o Nominatim (`geocode()` in `pipeline/pipeline.py`).
- passare a `generate()`: `start_lat/lng`, `end_lat/lng` (entrambi default = city center).

I depot sono **nodi virtuali** nel grafo (non POI): hanno coordinate ma prize 0, service time 0,
nessuna time window oltre quella di inizio/fine giornata.

---

## 2. Pre-filtro candidati (bound del problema)

Il solver NON riceve l'intera città. Selezionare i **top-N candidati attività** per prize
(default `N = 80`), calcolato su tutta la città relativamente al depot/centro:
- riusare la logica di `_combined_score` ma **senza** il termine di prossimità al cluster (qui non
  ci sono cluster — la geografia la gestisce il solver via costi di viaggio). Prize ≈
  `w_sim * cosine + w_pop * popularity + landmark_boost`, default `w_sim=0.7, w_pop=0.3`.
- applicare la **novelty penalty** esistente (`apply_novelty_penalty`) sul prize.
- mantenere i filtri attuali (touristic, raggio città, family) già applicati a monte in
  `generate()`.

Food POI restano in un **pool separato** (come oggi) per il post-inserimento pasti — NON entrano
nel solver.

`N` è un iperparametro: più alto = soluzioni potenzialmente migliori ma solve più lento. Tenerlo
configurabile per gli esperimenti di tesi.

---

## 3. Costruzione del modello OR-Tools

### Nodi
Indice 0..D-1 = depot(s), poi i candidati attività. Per depot unico (hotel/centro) basta 1 nodo
depot riusato come start/end di tutti i veicoli. Per start/end distinti servono nodi depot distinti.

### Veicoli = giorni
`num_vehicles = num_days`. Ogni veicolo è un giorno con il suo budget tempo.

```python
manager = pywrapcp.RoutingIndexManager(num_nodes, num_days, starts, ends)
routing = pywrapcp.RoutingModel(manager)
```
- `starts` / `ends`: liste di lunghezza `num_days`. Caso depot unico → tutte uguali. Caso
  arrivo/partenza distinti → `starts[0]` = punto arrivo, `ends[-1]` = punto partenza, gli altri = hotel.

### Matrice tempi (secondi)
`travel_seconds[i][j]` per ogni coppia di nodi (depot + candidati). Costruirla da:
- modo scelto per la coppia via `select_transport(haversine(i,j))` (walk/transit/drive),
- tempo reale dalla cache `poi_travel_times` (pre-fetch batch — vedi routes spec §5),
- fallback haversine se mancante.
Pre-popolare la cache con UNA chiamata batch prima di costruire il modello (i nodi sono ≤ N+D ≈ 82,
le coppie ≈ 82² ma si calcolano solo le mancanti, in chunk ≤625 elementi).

### Callback costo = tempo di transito + service time
```python
def time_cb(from_index, to_index):
    f = manager.IndexToNode(from_index)
    t = manager.IndexToNode(to_index)
    return travel_seconds[f][t] + service_seconds[f]   # tempo per "lasciare" f e arrivare a t
transit_idx = routing.RegisterTransitCallback(time_cb)
routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)
```
`service_seconds[node]` = durata visita del POI (da `resolve_visit_mode`/`tourism_duration_minutes`,
in secondi). Depot → 0.

### Dimensione tempo + budget giornaliero + finestre
```python
routing.AddDimension(
    transit_idx,
    slack_max=3600*4,                  # attesa max consentita (per arrivare all'apertura)
    capacity=day_end_seconds,          # secondi dall'inizio giornata: tetto del cumul
    fix_start_cumul_to_zero=False,
    "Time",
)
time_dim = routing.GetDimensionOrDie("Time")
```
- Lavorare in "secondi dall'inizio giornata" (start = `start_time_str`, es. 09:00).
- **Budget attività** = `(day_end - day_start) - meal_reserve`. `meal_reserve` ≈
  `lunch_duration + dinner_duration + buffer` (default ~150–180 min) per lasciare spazio ai pasti
  post-inseriti. Impostare il tetto del cumul / la finestra del nodo end a `budget_attività`.
- **Time windows POI**: intersezione tra orario di apertura del POI (quel giorno della settimana,
  da `opening_hours`, stessa logica di `_is_open`) e la finestra giornaliera. Convertite in secondi:
  ```python
  time_dim.CumulVar(node_index).SetRange(open_s, close_s)
  ```
  POI senza `opening_hours` (outdoor) → finestra = intera giornata.
- Start cumul di ogni veicolo = 0 (= day_start).

### Nodi opzionali + prize (il cuore dell'orienteering)
Ogni candidato attività è **opzionale**: si modella con una disjunction la cui penalità = prize.
Saltare un nodo costa il suo prize → il solver preferisce includere i POI ad alto prize che
"entrano" nel tempo.
```python
for node in candidate_nodes:
    routing.AddDisjunction([manager.NodeToIndex(node)], penalty=int(prize[node] * PRIZE_SCALE))
```
`PRIZE_SCALE` va scelto grande rispetto ai costi di viaggio in secondi, così l'obiettivo
"massimizza rilevanza" domina e "minimizza viaggio" fa da tie-breaker secondario. (Obiettivo del
solver = `Σ costi_arco + Σ penalità_nodi_saltati`, minimizzato.)
I depot NON hanno disjunction (sono obbligatori).

### Cap per tipo (diversità) — opzionale
Per evitare "5 chiese nello stesso giorno" si può:
- (semplice, consigliato fase 1) applicarlo come **filtro nel post-pass** riusando
  `_PRIMARY_TYPE_DAY_CAP`, scartando le tappe in eccesso e ricompattando i tempi; oppure
- (più elegante, fase 2) aggiungere una dimensione di conteggio per tipo con upper bound per veicolo.
Tenere la diversità come **metrica di evaluation** esplicita (intra-list diversity, entropia
categoria) per confrontare TOPTW vs baseline.

### Parametri di ricerca
```python
params = pywrapcp.DefaultRoutingSearchParameters()
params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
params.time_limit.seconds = 20        # iperparametro; 10–30s ragionevole
solution = routing.SolveWithParameters(params)
```

---

## 4. Estrazione soluzione → giorni

Per ogni veicolo `v` (giorno `v+1`):
```python
index = routing.Start(v)
ordered_pois = []
while not routing.IsEnd(index):
    node = manager.IndexToNode(index)
    if node not in depot_nodes:
        ordered_pois.append(candidate_by_node[node])
    index = solution.Value(routing.NextVar(index))
```
Da `ordered_pois` costruire la lista `_Stop` (riusare `resolve_visit_mode` per durata/visit_mode/note,
i tempi di arrivo/partenza si possono leggere dal `time_dim.CumulVar` della soluzione oppure
ricalcolare propagando dai travel reali — usare i cumul del solver è più coerente).

Se un giorno risulta vuoto (solver non ha assegnato POI a quel veicolo) → warning come oggi.

---

## 5. Post-inserimento pasti (decisione #1)

Per ogni giorno, sulla rotta `_Stop` già ordinata e temporizzata:
- riusare la logica esistente di `_schedule_day` per pranzo/cena (`_pick_nearest_open_food`,
  finestre `LUNCH_TARGET_H`/`DINNER_TARGET_H`), ma operando **sulla sequenza ottimizzata** invece
  che sulla greedy. Il ristorante scelto è quello aperto più vicino **alla posizione reale nella
  rotta** a quell'ora → niente detour del pasto (fix causa #3).
- inserire il pasto tra le due tappe la cui finestra temporale contiene l'orario target;
  ricalcolare i tempi delle tappe successive con i travel reali.
- se l'inserimento sfora `day_end`, spostare il pasto o (raro) droppare l'ultima attività.
- food pool condiviso tra giorni con `used_food_ids` come oggi.

`meal_reserve` nel budget del solver (§3) garantisce che lo spazio per i pasti di norma ci sia.

---

## 6. Output & persistenza

Identici a oggi: `generate()` ritorna `(all_days, warnings)`, il router persiste `ItineraryItem` e
costruisce `ItineraryOut`. Nessun cambiamento a valle del solver. I `warnings` vanno adattati
(non più "deferred per orari": gli orari sono vincoli hard, quindi semmai "POI X non inseribile
negli orari di apertura nel budget disponibile").

---

## 7. Protocollo di evaluation (baseline vs TOPTW)

Per ogni `(città, profilo_utente, num_days)` del set di test, generare **entrambi** i bracci con
gli stessi input e gli stessi tempi reali, e misurare:

| Metrica | Cosa misura | Come |
|---------|-------------|------|
| Rilevanza totale raccolta | Σ prize dei POI inclusi | somma diretta |
| Landmark coverage | % dei top-N landmark città inclusi | confronto con ranking popolarità |
| Tempo morto / giorno | minuti vuoti nel budget | budget − tempo occupato |
| Overrun temporale reale | giornate che NON entrano nel budget reale | ricalcolo con Routes API (fair: stessi tempi) |
| # tappe attività / giorno | densità utile | conteggio |
| Diversità intra-lista | varietà categorie | entropia / intra-list diversity |
| Pasti completi | % itinerari con pranzo+cena | conteggio |
| Solve time | costo computazionale | wall-clock |

Attesi: TOPTW ≥ baseline su rilevanza, landmark coverage, tempo morto (minore), a parità di overrun;
baseline più veloce. È esattamente l'ablation "euristica greedy vs ottimizzazione" da mettere in tesi.

---

## Definition of done

- [ ] Config `itinerary_solver` + parametro request `solver`; dispatch in `generate()`.
- [ ] Input depot opzionale (`start_location`/`end_location`) + geocoding nel router; default centro.
- [ ] Pre-filtro top-N candidati con prize (cosine+popolarità+landmark+novelty), food pool separato.
- [ ] Pre-fetch batch matrice tempi reali (dipendenza routes spec) + fallback haversine.
- [ ] Modello OR-Tools: veicoli=giorni, time dimension con budget e time windows da orari,
      disjunction con penalty=prize, depot start/end (anche distinti).
- [ ] Estrazione rotte per giorno → `_Stop` con tempi dai cumul del solver.
- [ ] Post-inserimento pasti sulla rotta ottimizzata (riuso logica esistente).
- [ ] (Opz.) cap per tipo nel post-pass per diversità.
- [ ] `itinerary_solver="greedy"` → comportamento identico a oggi (baseline intatto, nessuna regressione).
- [ ] Script/notebook di evaluation che genera entrambi i bracci e produce la tabella §7.

## Test minimi
- Unit: costruzione time windows da `opening_hours` (giorno settimana corretto, POI outdoor = full day).
- Unit: prize = 0 e disjunction assente per i depot; presente per i candidati.
- Unit: con 1 solo giorno e pochi POI il solver ritorna una rotta valida entro il budget.
- Integrazione: stesso input su `greedy` vs `toptw` → entrambi producono itinerari non vuoti;
  il TOPTW non viola time windows né budget.
- Regressione: `solver="greedy"` identico all'output attuale.

## Iperparametri da esporre per la tesi
`N` (candidati), `PRIZE_SCALE`, `time_limit`, `meal_reserve`, `w_sim`/`w_pop`. Tutti soggetti ad
ablation/sweep nel capitolo sperimentale.
