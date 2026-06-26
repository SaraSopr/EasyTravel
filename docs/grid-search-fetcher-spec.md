# Spec: Hexagonal Grid Search per il fetch dei POI

## Problema: copertura incompleta con raggio fisso

L'implementazione originale di `fetch_city_pois` eseguiva tutte le ricerche di Google Places partendo da un **singolo punto** (le coordinate del centro città) con `radius=5000`:

```python
"location": f"{city.lat},{city.lng}",
"radius": 5000,
```

Questo approccio funziona bene per città dense e compatte (Roma, Barcellona) dove la maggior parte dei POI turistici si concentra entro 5 km dal centro. Fallisce per città **policentriche o estese** (Madrid, Berlino, Los Angeles) dove quartieri di interesse — Retiro, Malasaña, Salamanca per Madrid — si trovano oltre il raggio di ricerca o ai margini di esso.

**Effetto osservato:** Madrid mostra ~450 POI rispetto agli ~900 di Roma a parità di esecuzione, nonostante Madrid abbia un'area metropolitana comparabile e un'offerta turistica abbondante. Il problema principale è che l'API di Google Places restituisce al massimo 60 risultati per tipo per richiesta (3 pagine × 20 risultati): con un unico punto di ricerca, i risultati più distanti dal centro vengono scalzati da quelli centrali anche se rientrano nel raggio.

---

## Soluzione: griglia esagonale sulla bounding box della città

### Step 1 — Bounding box da Google Geocoding API

Prima di avviare il fetch, si interroga la **Google Geocoding API** con il nome della città:

```
GET https://maps.googleapis.com/maps/api/geocode/json
    ?address=Madrid,Spain&key=<API_KEY>
```

La risposta include `geometry.viewport`, un rettangolo che Google fornisce come estensione ottimale per mostrare la città su una mappa:

```json
"viewport": {
  "southwest": { "lat": 40.312, "lng": -3.836 },
  "northeast": { "lat": 40.560, "lng": -3.524 }
}
```

Questo bounding box è più accurato e aggiornato di qualsiasi stima basata su raggio fisso. Viene estratto dalla funzione `_get_city_bbox(city_name, country, api_key)` che restituisce `(sw_lat, sw_lng, ne_lat, ne_lng)`.

### Step 2 — Generazione della griglia esagonale

Dato il bounding box, si genera una griglia di punti di ricerca con `_generate_hex_grid(sw_lat, sw_lng, ne_lat, ne_lng, step_m)`.

Il packing **esagonale** (a nido d'ape) è ottimale per coprire un'area con cerchi di raggio fisso: minimizza le sovrapposizioni rispetto a una griglia rettangolare garantendo che ogni punto della bounding box sia coperto da almeno una cella. In una griglia rettangolare con passo `d`, i punti agli angoli delle celle distano `d√2` dal centro più vicino; nella griglia esagonale il massimo è esattamente `d`.

**Geometria:**
- Passo orizzontale: `dx = arctan(step_m / (R · cos(lat)))` (varia con la latitudine)
- Passo verticale: `dy_vert = dx · (√3 / 2)` ≈ `0.866 · dy_orizzontale`
- Righe dispari sfalsate di `dx / 2` verso destra

```
Row 0:  ●   ●   ●   ●   ●   ●
Row 1:    ●   ●   ●   ●   ●
Row 2:  ●   ●   ●   ●   ●   ●
```

Per Madrid (bbox ~28 × 27 km, `step_m=3000`):
- ~9 colonne per riga
- ~13 righe
- **~120 punti di ricerca**

### Step 3 — Nearby Search da ogni cella

Per ogni punto della griglia si esegue una Nearby Search con `radius=step_m` per ciascun tipo in `GRID_SEARCH_TYPES`, con massimo `MAX_PAGES_GRID=2` pagine:

```python
GRID_SEARCH_TYPES = [
    "tourist_attraction",
    "museum",
    "restaurant",
    "park",
    "night_club",
    "spa",
    "amusement_park",
]
```

Questi 7 tipi sono scelti come rappresentativi di ciascuna delle 7 categorie di `TYPE_GROUPS`. Usare tutti i ~36 tipi originali moltiplicherebbe le chiamate API di 5×.

**Stima chiamate API per Madrid:**
```
120 grid points × 7 types × 2 pages = 1 680 chiamate
+ 1 chiamata Geocoding
= ~1 681 chiamate totali
```

Rispetto al metodo originale (1 punto × 36 tipi × 3 pagine = 108 chiamate), il grid search fa ~15× più chiamate ma copre un'area ~35× più grande in modo sistematico.

### Step 4 — Deduplicazione

Il set `seen: set[str]` accumula tutti i `google_place_id` già processati. Poiché celle adiacenti si sovrappongono per costruzione (overlap ~13% perimetrale), ogni POI in zona di sovrapposizione viene trovato più volte ma inserito una sola volta. La funzione `_upsert_poi` usa `ON CONFLICT DO UPDATE` come ulteriore garanzia di idempotenza a livello DB.

### Step 5 — Fallback

Se la Geocoding API fallisce (errore di rete, chiave non valida, città non trovata), `_get_city_bbox` restituisce `None` e `fetch_city_pois` torna all'**algoritmo originale**: ricerca dal centro con `radius=5000` e tutti i `TYPE_GROUPS`. Il comportamento precedente è completamente preservato.

---

## Parametri

| Parametro | Valore default | Descrizione |
|-----------|---------------|-------------|
| `GRID_STEP_M` | 3 000 m | Passo della griglia = raggio di ogni cella |
| `MAX_PAGES_GRID` | 2 | Pagine Google Places per punto per tipo |
| `GRID_SEARCH_TYPES` | 7 tipi | Tipi cercati in ogni cella |
| `grid_step_m` | `GRID_STEP_M` | Override per call singole (es. `--grid-step 4000`) |

### Scelta di GRID_STEP_M: copertura vs costo API

La condizione di copertura completa per una griglia esagonale è `radius ≥ step`: il punto più svantaggiato (equidistante da tre celle adiacenti) dista esattamente `step` dal centro più vicino. Poiché nel codice si passa `radius = grid_step_m`, la copertura è **sempre garantita** indipendentemente dal valore scelto.

Il vero tradeoff è sul costo API (**Google Places Nearby Search: $0.032/richiesta, free tier $200/mese**):

| `GRID_STEP_M` | Punti (Madrid) | Chiamate | Costo/città | Città/mese nel free tier |
|---|---|---|---|---|
| 3 000 m | 120 | 1 680 | ~$54 | 3 |
| **4 000 m** | **~68** | **~950** | **~$30** | **6** |
| 5 000 m | ~40 | ~560 | ~$18 | 11 |
| 6 000 m | ~28 | ~390 | ~$13 | 15 |

**Valore consigliato: 4 000 m.** Il problema di Madrid non era la granularità del raggio, ma il fatto che dal centro fisso si ottenevano al massimo 60 POI per tipo e i quartieri periferici venivano sistematicamente esclusi. Con la griglia, anche a passi più grandi, ogni cella perimetrale restituisce i POI più prominenti della propria zona — il problema della copertura incompleta è già risolto strutturalmente. Un passo di 4 000 m permette di fetchare 6+ città al mese restando nel free tier, sufficiente per un progetto di tesi con 5–8 destinazioni distribuite su 1–2 mesi.

---

## Confronto con l'approccio originale

| Aspetto | Centro fisso (originale) | Griglia esagonale |
|---------|--------------------------|-------------------|
| Punti di ricerca | 1 | ~95 (Madrid) |
| Raggio per punto | 5 000 m | 3 000 m |
| Tipi ricercati | ~36 (tutti) | 7 (rappresentativi) |
| Chiamate API | ~108 | ~1 330 |
| Copertura geografica | Cerchio centrale | Intera città |
| Risultati attesi Madrid | ~450 POI | ~1 200–1 500 POI (stima) |
| Deduplicazione | `seen` set | `seen` set + DB upsert |
| Fallback | — | Centro fisso se Geocoding fallisce |

---

## Implementazione

### File modificati

- **`backend/pipeline/fetcher.py`**
  - Aggiunto `import math`
  - Aggiunte costanti: `GOOGLE_GEOCODING_URL`, `GRID_STEP_M`, `MAX_PAGES_GRID`, `GRID_SEARCH_TYPES`
  - Aggiunta funzione `_get_city_bbox(city_name, country, api_key) → tuple | None`
  - Aggiunta funzione `_generate_hex_grid(sw_lat, sw_lng, ne_lat, ne_lng, step_m) → list[tuple]`
  - Modificata `fetch_city_pois`: aggiunto parametro `country: str = ""` e `grid_step_m: int = GRID_STEP_M`; logica grid search se bbox disponibile, altrimenti fallback

- **`backend/pipeline/pipeline.py`**
  - Aggiunto `country=country` alla chiamata `fetch_city_pois`

### Come eseguire il grid fetch

```bash
# Fetch completo con grid search (Madrid)
python pipeline/pipeline.py --city "Madrid" --country "Spain" --force-refetch

# Test con limite
python pipeline/pipeline.py --city "Madrid" --country "Spain" --force-refetch --limit 200

# Solo classificazione POI già fetchati
python pipeline/pipeline.py --city "Madrid" --country "Spain" --classify-only
```

---

## Integrazione nella tesi

Questa strategia di fetching rientra nella sezione di **acquisizione dati** e può essere descritta come:

> *"Per garantire copertura geografica completa della destinazione, il sistema determina il bounding box della città tramite Google Geocoding API e genera una griglia di punti di ricerca con packing esagonale (Honeycomb Tessellation) con passo configurabile (default 3 km). Ogni cella della griglia viene interrogata tramite Google Places Nearby Search in modo indipendente; la deduplicazione avviene tramite il campo `google_place_id`. Rispetto all'approccio a raggio fisso, il grid search garantisce che ogni punto dell'area urbana disti al più `step_m` dal centro di ricerca più vicino, eliminando sistematicamente le zone non coperte nei quartieri periferici."*

---

## Riferimenti

- Google Places Nearby Search API: [developers.google.com/maps/documentation/places/web-service/search-nearby](https://developers.google.com/maps/documentation/places/web-service/search-nearby)
- Google Geocoding API: [developers.google.com/maps/documentation/geocoding/overview](https://developers.google.com/maps/documentation/geocoding/overview)
- Honeycomb tessellation: Conway, J.H., Sloane, N.J.A. (1999). *Sphere Packings, Lattices and Groups*. Springer.
