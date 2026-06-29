# Spec — Evaluation harness + dashboard di valutazione umana

> **Obiettivo**: misurare in modo riproducibile la qualità degli itinerari su due assi —
> **selezione/rilevanza** (i POI giusti per il profilo?) e **realismo** (la giornata è davvero
> fattibile?) — confrontando il sistema attuale (`greedy`, baseline) col nuovo solver (`toptw`).
> È la parte che trasforma il lavoro in una tesi difendibile.
>
> **Riferimenti**: `docs/itinerary-quality-analysis.md` (cause), `docs/toptw-itinerary-solver-spec.md`
> (il braccio nuovo), `docs/routes-api-travel-times-spec.md` (tempi reali per la metrica overrun).

## Architettura a due livelli

1. **Metriche automatiche** → calcolate su **TUTTO** il test set (216 itinerari). Veloci, oggettive.
2. **Valutazione umana** → su un **sottoinsieme campionato** di itinerari/coppie (il tempo umano è
   il collo di bottiglia). Dashboard dedicata, cieca e randomizzata.

## Dipendenze e fasatura

- Il braccio `toptw` richiede che `docs/toptw-itinerary-solver-spec.md` sia implementato.
- La metrica **overrun** richiede la cache tempi reali (`docs/routes-api-travel-times-spec.md`).
- **Si può iniziare subito** con: fixtures profili, seeding, generazione del braccio `greedy`,
  metriche automatiche, pair-builder e dashboard. Il braccio `toptw` si aggancia quando pronto.

---

## 1. Profili di test (fixtures congelati)

File: `backend/evaluation/profiles.py` (o JSON in `backend/evaluation/profiles.json`). **Congelati
nel repo** per riproducibilità. Vettore a 7 dim nell'ordine di `app/constants.py:FEATURE_NAMES`
(`nature, culture, food, adventure, nightlife, relax, family_friendly`). Valori = intensità 0–1; il
planner normalizza e somma `_MODE_BIAS`.

```python
PROFILES = [
  # key, label, travel_mode, age_range, travel_with_children, vector
  {"key":"senior_solo_culture","label":"Anziano solo, culturale","travel_mode":"solo","age_range":"70+","children":False,
   "vector":{"nature":0.2,"culture":0.9,"food":0.5,"adventure":0.05,"nightlife":0.0,"relax":0.7,"family_friendly":0.1}},
  {"key":"couple_foodie","label":"Coppia foodie-romantica","travel_mode":"couple","age_range":"26-35","children":False,
   "vector":{"nature":0.3,"culture":0.6,"food":0.9,"adventure":0.2,"nightlife":0.3,"relax":0.7,"family_friendly":0.0}},
  {"key":"young_solo_outdoor","label":"Giovane solo, outdoor/avventura","travel_mode":"solo","age_range":"18-25","children":False,
   "vector":{"nature":0.8,"culture":0.4,"food":0.5,"adventure":0.9,"nightlife":0.5,"relax":0.2,"family_friendly":0.0}},
  {"key":"friends_nightlife","label":"Gruppo di amici, nightlife/social","travel_mode":"friends","age_range":"18-25","children":False,
   "vector":{"nature":0.2,"culture":0.3,"food":0.7,"adventure":0.7,"nightlife":0.9,"relax":0.2,"family_friendly":0.0}},
  {"key":"family_toddlers","label":"Famiglia, bimbi piccoli","travel_mode":"family","age_range":"36-45","children":True,
   "vector":{"nature":0.7,"culture":0.4,"food":0.5,"adventure":0.4,"nightlife":0.0,"relax":0.6,"family_friendly":1.0}},
  {"key":"family_teen","label":"Famiglia, adolescente","travel_mode":"family","age_range":"36-45","children":True,
   "vector":{"nature":0.5,"culture":0.6,"food":0.6,"adventure":0.7,"nightlife":0.1,"relax":0.3,"family_friendly":0.5}},
  {"key":"couple_museums","label":"Coppia 'solo musei' (monotematico)","travel_mode":"couple","age_range":"46-55","children":False,
   "vector":{"nature":0.1,"culture":1.0,"food":0.4,"adventure":0.1,"nightlife":0.1,"relax":0.4,"family_friendly":0.0}},
  {"key":"young_solo_relax","label":"Giovane solo, relax/benessere","travel_mode":"solo","age_range":"26-35","children":False,
   "vector":{"nature":0.6,"culture":0.3,"food":0.6,"adventure":0.2,"nightlife":0.2,"relax":0.9,"family_friendly":0.0}},
  {"key":"couple_generalist","label":"Coppia generalista (turista medio)","travel_mode":"couple","age_range":"26-35","children":False,
   "vector":{"nature":0.5,"culture":0.6,"food":0.6,"adventure":0.4,"nightlife":0.3,"relax":0.5,"family_friendly":0.0}},
]
```

Note:
- `family_teen` (key `family_teen`) è un **probe edge-case**: il sistema oggi non distingue l'età
  dei figli (`travel_with_children` booleano). Tenuto apposta per documentare il limite → "future work".
- `couple_museums` serve a far emergere se la penalità MMR danneggia il monotematico (causa #7).
- `young_solo_relax` è il caso "stress completezza" (poco interesse sightseeing → giorni a rischio vuoto).

---

## 2. Matrice di test

- **Città** (3): `Roma` e `Madrid` (capitali dense) + **`Porto`** come città media, per stressare
  la scarsità di POI (dove la differenza greedy vs TOPTW è massima). Ogni città deve essere stata
  ingestita dalla pipeline (POI classificati + orari).
- **Durate** (2): `num_days = 2` (stress prioritizzazione must-see) e `num_days = 4` (stress
  completezza/varietà).
- **Solver** (2): `greedy` (baseline), `toptw` (nuovo).
- **Routing** (2): `real` (tempi reali su strada, cache) vs `estimated` (haversine). Incrociato con
  i solver isola il cambio di algoritmo da quello di routing (ablazione 2×2).

Totale: 9 × 3 × 2 × 2 × 2 = **216 itinerari** generati. Tutti passano per le metriche automatiche.

Config in `backend/evaluation/config.py`: liste `CITIES`, `DURATIONS`, `SOLVERS`, `depot=None`
(centro città per tutti, per non introdurre una variabile in più nel confronto).

---

## 3. Harness di generazione

Script `backend/evaluation/run_eval.py`.

Per ogni profilo:
1. **Crea/aggiorna un utente di test** `eval+<key>@easytravel.test` con `age_range` dal profilo.
2. **Scrive il vettore preferenze DIRETTAMENTE** in `UserPreference` (bypassa l'onboarding e le
   experience LLM — è il punto chiave per la riproducibilità; il planner legge solo `UserPreference`,
   quindi un vettore impostato a mano è identico a uno "vero").

Per ogni (profilo × città × durata × solver):
3. Chiama `itinerary_planner.generate(...)` (o l'endpoint `/itineraries/generate` con `solver`),
   con `travel_mode`, `age_range`, `travel_with_children` dal profilo.
4. **Salva uno snapshot JSON congelato** dell'output + il contesto, in tabella `evaluation_itineraries`
   (vedi §5). Lo snapshot serve perché la dashboard deve mostrare ESATTAMENTE ciò che è stato
   generato, immune a futuri cambi dei dati POI.
5. Salva anche, per il pair-builder, la **lista completa dei candidati con il loro prize/score e il
   flag incluso/escluso** (campo `candidates_json`). Questo è indispensabile per costruire le coppie
   margine e "il sistema ha rankato A sopra B".

L'harness è idempotente: ri-eseguibile, sovrascrive lo snapshot della stessa cella `(profile, city,
duration, solver, run_id)`.

---

## 4. Metriche automatiche

Modulo `backend/evaluation/metrics.py`. Calcolate per ogni itinerario e aggregate per
`(solver)`, `(solver × città)`, `(solver × profilo)`.

| Metrica | Definizione | Asse |
|---------|-------------|------|
| `total_relevance` | Σ prize dei POI inclusi (stesso prize del planner) | selezione |
| `landmark_coverage` | % dei top-N landmark città (per popolarità bayesiana) inclusi nel viaggio | selezione |
| `idle_minutes_per_day` | budget giornaliero − tempo occupato (visite+viaggi+pasti), medio | completezza |
| `budget_fill_rate` | % di giornate che riempiono ≥X% del budget | completezza |
| `real_overrun` | % di giornate che NON entrano nel budget se ricalcolate coi **tempi reali** (Routes API) — confronto equo tra i due bracci | **realismo** |
| `stops_per_day` | n. tappe attività/giorno | densità |
| `intra_list_diversity` | 1 − similarità media a coppie sui vettori POI (o entropia categorie) | varietà |
| `meals_complete_rate` | % itinerari con pranzo+cena ogni giorno | completezza |
| `solve_time_ms` | wall-clock del solver | costo |

`real_overrun` è la metrica chiave di realismo: si prende l'itinerario (di ENTRAMBI i bracci),
si ricalcolano i tempi delle tratte con la cache reale, e si verifica se la sequenza pianificata
sfora `end_time`. Mostra quanto era irrealistico il pacing.

Output: un CSV/JSON `evaluation_results.csv` (una riga per itinerario) + un riepilogo aggregato per
i grafici della tesi.

---

## 5. Modello dati (tabelle evaluation)

Nuovi model in `backend/app/models/evaluation.py` (+ import in `models/__init__.py`, migrazione Alembic).

```
evaluation_itineraries
  id (uuid, pk)
  run_id (uuid)              # raggruppa una run completa
  profile_key (str)
  city (str)
  num_days (int)
  solver (str)              # "greedy" | "toptw"
  payload_json (jsonb)      # snapshot ItineraryOut congelato (giorni, tappe, orari, mappa)
  candidates_json (jsonb)   # [{poi_id, name, types, prize, included(bool), day}]
  metrics_json (jsonb)      # metriche §4 di questo itinerario
  created_at

evaluation_pairs            # coppie A(incluso) vs B(scartato), pre-generate (§6)
  id (uuid, pk)
  itinerary_id (fk -> evaluation_itineraries)
  pair_type (str)           # "substitutable" | "famous_skipped" | "margin"
  poi_a_id (uuid)           # incluso nel viaggio
  poi_b_id (uuid)           # scartato / non visto
  poi_a_snapshot (jsonb)    # nome, foto, tipi, rating, day/orario — congelati per la UI
  poi_b_snapshot (jsonb)
  profile_key, city         # denormalizzati per filtrare in dashboard

evaluation_ratings          # voto pairwise umano
  id (uuid, pk)
  pair_id (fk -> evaluation_pairs)
  evaluator_id (str)        # link con ?evaluator=<id>, niente auth
  choice (str)              # "a" | "b" | "equal"
  created_at

evaluation_likert           # giudizio whole-itinerary (realismo & co., complemento)
  id (uuid, pk)
  itinerary_id (fk -> evaluation_itineraries)
  evaluator_id (str)
  realism (int 1-5)
  completeness (int 1-5)
  profile_fit (int 1-5)
  overall (int 1-5)
  created_at
```

---

## 6. Pair-builder (le 3 tipologie di coppia)

Modulo `backend/evaluation/pairs.py`. Per ogni itinerario, dato `candidates_json` (con prize +
incluso/escluso) e gli snapshot POI, genera coppie A(incluso)–B(escluso). Cap configurabile di
coppie per tipo per itinerario (default 3) per non saturare i valutatori.

**Trappola da rispettare** (rilevanza ≠ fattibilità): un POI può essere escluso per logistica, non
per minor rilevanza. Le tipologie sono progettate per controllare questo.

1. **`substitutable`** (test forte sulla *rilevanza*): per ogni A incluso, scegli B escluso nella
   **stessa zona/giorno** (entro un raggio, default 1 km) e con **costo-tempo simile** → la logistica
   è ~uguale, l'unica differenza è quanto è adatto al profilo. Domanda UI:
   *"Per questo viaggiatore, quale posto è più adatto?"*
2. **`famous_skipped`** (test sulla *coverage must-see*): B = landmark famoso della città (alto
   `user_ratings_total`) **NON** incluso nel viaggio; A = un POI incluso di fama minore nello stesso
   viaggio. Domanda: *"Quale di questi due merita di più il posto nel viaggio?"* Se gli umani
   preferiscono il famoso saltato → buco di coverage.
3. **`margin`** (i casi *borderline*, i più informativi sul ranking): A = incluso col **prize più
   basso** (appena sopra soglia); B = escluso col **prize più alto** (appena sotto soglia).
   Domanda: *"Quale dei due avrebbe dovuto essere nel viaggio?"*

Ogni coppia salva gli snapshot POI (nome, foto, tipi, rating, eventuale giorno/orario di A) così la
UI è congelata e indipendente dai dati live.

---

## 7. Dashboard di valutazione umana

Nuova vista frontend (riusa lo stack React+Vite). **Separata dal flusso utente normale**; accesso
via link `?/eval?evaluator=<id>` (niente auth, solo un `evaluator_id` per tracciare l'accordo).

Regole metodologiche (non negoziabili):
- **Cieco**: il valutatore NON vede il nome del solver né quale POI è "del sistema". Per le coppie,
  A e B sono mostrati in **posizione randomizzata** (sinistra/destra) per ogni rendering.
- **Ordine randomizzato** delle coppie/itinerari per valutatore.
- **Contesto profilo sempre visibile**: card "Per chi è questo viaggio" (label + interessi del
  profilo) così il giudizio è "adatto a *questa* persona", non "mi piace a me".

Due sezioni:

### 7a. Pairwise (risultato principale)
Mostra la **descrizione del profilo** + due card POI (A e B, snapshot: foto, nome, tipi, rating;
per il tipo `substitutable`/`margin` indicare che entrambi sono nella stessa zona). Pulsanti:
*"Il primo" / "Il secondo" / "Equivalenti"*. Salva in `evaluation_ratings` con `choice` rimappato
ad a/b in base alla randomizzazione. Una coppia per schermata, avanzamento progressivo.

### 7b. Likert whole-itinerary (complemento per il realismo)
Per un itinerario campionato, mostra timeline + mappa (riusa `ItineraryTimeline`, `ItineraryMap`),
con i tempi di spostamento. Quattro slider 1–5: **realismo, completezza, aderenza al profilo,
soddisfazione**. Salva in `evaluation_likert`. Serve a coprire l'asse realismo, che il pairwise
sui POI non misura.

### Endpoint backend (router `app/routers/evaluation.py`)
- `GET /api/evaluation/pairs?evaluator=<id>` → prossime coppie non ancora votate da quel valutatore
  (ordine randomizzato).
- `POST /api/evaluation/ratings` → salva un voto pairwise.
- `GET /api/evaluation/itineraries?evaluator=<id>` → itinerari da valutare in Likert.
- `POST /api/evaluation/likert` → salva un giudizio.
- `GET /api/evaluation/export` → dump CSV di ratings+likert+metriche per l'analisi.

### Analisi degli esiti
- **Agreement rate**: % di coppie dove la scelta del sistema (A incluso) = preferenza umana.
- **Must-see gap**: sulle coppie `famous_skipped`, % in cui gli umani preferiscono B (il famoso saltato).
- **Win-rate solver**: confronto greedy vs toptw, sia via Likert (medie per dimensione) sia, sulle
  coppie dove i due solver differiscono nelle inclusioni, via preferenza umana.
- **Inter-rater agreement**: Krippendorff α / Fleiss κ con ≥3 valutatori per coppia.

---

## 8. Campionamento per la valutazione umana

Metriche automatiche su tutti i 144; valutazione umana su un **sottoinsieme** per tenere il carico
umano gestibile (target ~60–120 coppie per valutatore):
- prioritizza gli itinerari/coppie **dove `greedy` e `toptw` differiscono** (massima informatività
  sul confronto solver);
- garantisci uno **spread bilanciato** su profili e città (almeno 1 cella per profilo e per città);
- per ogni itinerario campionato, max 3 coppie per tipo.
Parametri di campionamento in `evaluation/config.py` (`HUMAN_SAMPLE_SIZE`, `PAIRS_PER_TYPE`).

---

## Definition of done

- [ ] `profiles.py` congelato (9 profili) + `config.py` (città, durate, solver, sampling).
- [ ] `run_eval.py`: seeding utenti + vettore diretto in `UserPreference`; genera le celle e salva
      snapshot + candidati in `evaluation_itineraries`.
- [ ] `metrics.py`: tutte le metriche §4 + export CSV/JSON aggregato. `real_overrun` usa la cache reale.
- [ ] Model + migrazione per le 4 tabelle evaluation.
- [ ] `pairs.py`: generazione delle 3 tipologie con il controllo rilevanza-vs-fattibilità.
- [ ] Router `evaluation.py` con gli endpoint §7.
- [ ] Dashboard FE: pairwise (cieco+randomizzato) + Likert, card profilo sempre visibile, export.
- [ ] Funziona col solo braccio `greedy` (TOPTW si aggancia dopo); nessun impatto sul flusso utente.

## Test minimi
- Unit: seeding scrive il vettore atteso in `UserPreference` (normalizzazione coerente).
- Unit: `substitutable` sceglie B nello stesso raggio/costo (logistica controllata).
- Unit: `famous_skipped` sceglie solo landmark NON inclusi nel viaggio.
- Unit: randomizzazione A/B nella UI mappa correttamente il `choice` salvato.
- Integrazione: run completa su 1 città × 2 profili × 1 durata × 1 solver → snapshot + coppie + metriche.

## Parametri esposti per la tesi
`top_N_landmark` (coverage), `budget_fill_threshold`, `substitutable_radius_m`, `PAIRS_PER_TYPE`,
`HUMAN_SAMPLE_SIZE`, lista città/durate. Tutti documentati per le ablation.
