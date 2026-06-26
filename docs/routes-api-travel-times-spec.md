# Spec — Tempi di viaggio reali via Google Routes API + cache su DB

> **Obiettivo**: sostituire i tempi di spostamento finti (haversine ÷ velocità fissa) con
> tempi reali su strada calcolati da Google Routes API, con una cache persistente su DB
> in modo da pagarli una sola volta per coppia di POI.
>
> **Problema risolto**: oggi `select_transport()` in
> `backend/app/services/itinerary_planner.py:362` usa la distanza in linea d'aria diviso una
> velocità costante. Sottostima i tempi reali → itinerari sovraccarichi e irrealistici. Vedi
> `docs/itinerary-quality-analysis.md` (causa #1).
>
> **Decisione presa** (giugno 2026, tesi in consegna a dicembre 2026):
> Google **Routes API – Compute Route Matrix**, non il legacy Distance Matrix (deprecato).
> Con la cache la differenza di prezzo è irrilevante e non si costruisce su un'API in dismissione.

---

## Principi guida (non violarli)

1. **Le coordinate dei POI sono statiche** → il tempo A→B per un dato modo non cambia mai.
   Si calcola **una volta** e si salva. Il costo è limitato dalla dimensione della città, non
   dal numero di itinerari generati.
2. **Lookup cache PRIMA, chiamata API solo per le coppie mancanti.**
3. **Fallback obbligatorio**: se la API non risponde o la chiave manca, si ricade
   sull'haversine attuale. La generazione dell'itinerario non deve MAI fallire per colpa del routing.
4. **Calcola solo il modo che serve**, non tutti i modi per coppia (dimezza gli elementi).
5. **Non fare l'N×N dell'intera città**: si calcolano solo le coppie effettivamente richieste
   dallo scheduler (i ~25 POI del giorno), in modo lazy.

---

## 1. Modello + migrazione: tabella `poi_travel_times`

Nuovo file `backend/app/models/poi_travel_time.py`:

```python
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PoiTravelTime(Base):
    __tablename__ = "poi_travel_times"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    origin_poi_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pois.id", ondelete="CASCADE"), nullable=False)
    dest_poi_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pois.id", ondelete="CASCADE"), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)   # "walking" | "transit" | "driving"
    seconds: Mapped[int] = mapped_column(Integer, nullable=False)   # durata reale
    meters: Mapped[int] = mapped_column(Integer, nullable=False)    # distanza reale su strada
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="routes_api")  # "routes_api" | "haversine_fallback"
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("origin_poi_id", "dest_poi_id", "mode", name="uq_travel_origin_dest_mode"),
    )
```

- Aggiungere l'import in `backend/app/models/__init__.py` (Alembic lo richiede per l'autogenerate).
- Generare la migrazione:
  `alembic revision --autogenerate -m "add poi_travel_times cache table"` poi `alembic upgrade head`.
- Indice extra consigliato sulla lookup: `(origin_poi_id, dest_poi_id, mode)` è già coperto dalla
  UniqueConstraint. Aggiungere eventualmente un indice su `origin_poi_id` per le query batch.

**Nota mode**: lo scheduler attuale usa `walking | transit | taxi`. Mappare `taxi` → modo Routes
`DRIVE` e salvarlo come `mode="driving"`. Vedi §4 per la mappatura.

---

## 2. Config

In `backend/app/config.py` aggiungere a `Settings`:

```python
google_routes_api_key: str = ""        # può riusare google_places_api_key se sulla stessa key è abilitata Routes API
routes_api_enabled: bool = False        # master switch: se False → sempre haversine
```

La Routes API va abilitata sulla Google Cloud Console per la stessa API key. Se si vuole una key
unica, leggere `google_routes_api_key or google_places_api_key` nel client.

---

## 3. Client Routes API

Nuovo file `backend/app/services/routes_client.py`.

Endpoint: `POST https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix`

Header obbligatori:
- `X-Goog-Api-Key: <key>`
- `Content-Type: application/json`
- `X-Goog-FieldMask: originIndex,destinationIndex,duration,distanceMeters,condition`
  (il field mask è OBBLIGATORIO; senza, la API rifiuta o fattura di più)

Body (esempio per N origini × M destinazioni):
```json
{
  "origins": [
    {"waypoint": {"location": {"latLng": {"latitude": 41.89, "longitude": 12.49}}}}
  ],
  "destinations": [
    {"waypoint": {"location": {"latLng": {"latitude": 41.90, "longitude": 12.50}}}}
  ],
  "travelMode": "WALK"
}
```

- `travelMode`: `"WALK"` | `"DRIVE"` | `"TRANSIT"` (vedi mappatura §4).
- Per `DRIVE` si può aggiungere `"routingPreference": "TRAFFIC_UNAWARE"` per restare nello SKU
  Essentials (più economico) — il traffico real-time non serve per tempi cacheable e statici.
- **Limite**: max **625 elementi** per richiesta (origini × destinazioni ≤ 625). Una matrice
  25×25 entra in una sola chiamata. Se le coppie mancanti superano 625, spezzare in più richieste.
- La risposta è uno stream di oggetti `{originIndex, destinationIndex, duration, distanceMeters, condition}`.
  `duration` è una stringa tipo `"412s"` → parsare il numero. Scartare gli elementi con
  `condition != "ROUTE_EXISTS"` (lì si usa il fallback haversine).

Firma consigliata:
```python
async def compute_route_matrix(
    origins: list[tuple[float, float]],     # (lat, lng)
    destinations: list[tuple[float, float]],
    mode: str,                              # "walking" | "transit" | "driving"
) -> list[tuple[int, int, int, int]]:       # (origin_idx, dest_idx, seconds, meters)
```

Riuso pattern esistente: retry/backoff come `_request_with_retry` in
`backend/pipeline/fetcher.py` (httpx async, max 3 retry, gestione errori → ritorna None/[]).

---

## 4. Mappatura modo scheduler ↔ Routes API

Lo scheduler decide il modo per soglia di distanza in
`select_transport()` (`itinerary_planner.py:362`):
`< 800 m → walking`, `< 5000 m → transit`, `≥ 5000 m → taxi`.

Mappatura verso Routes:

| scheduler | mode salvato in DB | Routes `travelMode` |
|-----------|--------------------|---------------------|
| walking   | `walking`          | `WALK`              |
| transit   | `transit`          | `TRANSIT`           |
| taxi      | `driving`          | `DRIVE`             |

**Mantenere `select_transport()` come selettore del modo** (decide QUALE modo in base alla
distanza haversine, che va benissimo come euristica per scegliere walk/transit/drive). Quello che
cambia è il **tempo**: non più `distanza_haversine / velocità`, ma il valore reale dalla cache/API.

---

## 5. Funzione di accesso con cache

Nuovo modulo o dentro `routes_client.py`:

```python
async def get_travel_time(
    session: AsyncSession,
    origin: Poi,
    dest: Poi,
    mode: str,                 # "walking" | "transit" | "driving"
) -> tuple[float, int]:        # (minutes, meters)
    ...
```

Logica:
1. Se `origin.id == dest.id` → `(0.0, 0)`.
2. Lookup in `poi_travel_times` su `(origin_id, dest_id, mode)`. Se presente → ritorna.
3. Se assente e `settings.routes_api_enabled` e key presente:
   - chiama `compute_route_matrix([origin], [dest], mode)`,
   - se `ROUTE_EXISTS` → salva la riga in cache (`source="routes_api"`) e ritorna.
4. Fallback con l'haversine corrente (`haversine_m` + `SPEED_MS[mode]`).
   **Distinguere TRE casi, non due** — `compute_route_matrix` ritorna `list | None`:
   - **rotta reale** (`condition == ROUTE_EXISTS`) → cache `source="routes_api"`;
   - **no-route esplicito** (la API risponde ma la coppia non ha rotta: isola pedonale,
     transit assente…) → cache `source="haversine_fallback"`, così non si ritenta a ogni run;
   - **errore API** (HTTP/timeout/eccezione, `compute_route_matrix` → `None`) → usa l'haversine
     **al volo SENZA cacharlo**, così la coppia viene ritentata al run successivo.

   ⚠️ Il rischio è confondere il no-route vero (caso 2) con l'errore transitorio (caso 3): cachare
   un errore congelerebbe un valore finto anche quando la rotta reale esiste. Quindi il fallback si
   cacha **solo** sul segnale esplicito `condition != ROUTE_EXISTS`, mai su exception/HTTP error.
   Ad API spenta (`routes_api_enabled=False`) non si scrive nulla (vedi DoD: nessuna regressione).

### Versione batch (preferita per performance)
Aggiungere `get_travel_times_batch(session, pairs)` che:
- raggruppa le coppie mancanti per `mode`,
- per ogni modo costruisce UNA `compute_route_matrix` (≤625 elementi, altrimenti chunk),
- fa un solo `INSERT` bulk in cache.

Lo scheduler conosce in anticipo i POI del giorno → si può **pre-popolare** la matrice del giorno
con una sola chiamata batch prima di iniziare `_schedule_day`, invece di chiamate singole nel loop.

### Scope del pre-fetch: solo attività, NON food (scelta motivata)
La matrice pre-caricata copre solo le coppie tra le **attività MMR del giorno** (~25 POI, bounded).
Le tratte da/verso i ristoranti restano su haversine, per due motivi:
1. **Le tratte food sono corte per costruzione**: `_pick_nearest_open_food` sceglie il ristorante
   aperto più vicino → la gamba attività→ristorante è quasi sempre breve. L'errore assoluto
   dell'haversine scala con la distanza: su 300 m sbagli pochi minuti, su una attività→attività di
   3 km sbagli parecchio. I tempi reali vanno quindi messi dove l'errore è grande (lo *spine* della
   giornata) e l'approssimazione lasciata dove è piccola.
2. **Il food pool è di centinaia di POI** → un N×N attività×food sarebbe ingestibile e pagherebbe
   coppie quasi mai usate (se ne usano ~2/giorno, lunch + dinner).

**Criterio oggettivo per rivedere la scelta**: se la metrica *overrun* dell'evaluation mostrasse che
le gambe food pesano, aggiungere un pre-fetch **bounded K-nearest** (per ogni attività i 2–3 food più
vicini → ~50–75 elementi), dietro un flag. Da fare solo se i numeri lo chiedono, non "a sentimento".

---

## 6. Integrazione nello scheduler

File: `backend/app/services/itinerary_planner.py`.

Problema: `_schedule_day` gira dentro un `ThreadPoolExecutor`
(`run_in_executor`, `itinerary_planner.py:1502`) e usa `haversine_m` in modo sincrono in molti
punti (`_pick_nearest_open_food`, Pass-1 loop, `_add_activity_stop`, `_add_food_stop`, TSP).

Strategia consigliata (minimizza il refactor):
1. **Pre-fetch della matrice del giorno**, async, PRIMA di entrare nell'executor: dato l'insieme
   dei POI candidati del giorno (attività MMR + food disponibili + depot), chiamare
   `get_travel_times_batch` per riempire la cache. A questo punto tutti i tempi necessari sono in DB.
2. Passare a `_schedule_day` un **dizionario in memoria** `travel_lookup: dict[(origin_id, dest_id, mode), (minutes, meters)]`
   già risolto dalla cache, così la funzione resta sincrona e non fa I/O.
3. Introdurre un helper sincrono che sostituisce il calcolo del tempo:
   ```python
   def _travel(origin_id, origin_lat, origin_lng, dest_id, dest_lat, dest_lng, travel_lookup):
       mode, _ = select_transport(haversine_m(origin_lat, origin_lng, dest_lat, dest_lng))
       hit = travel_lookup.get((origin_id, dest_id, mode))
       if hit:
           return mode, hit[0]   # (mode, minutes) — tempo reale
       # fallback haversine
       _, minutes = select_transport(haversine_m(origin_lat, origin_lng, dest_lat, dest_lng))
       return mode, minutes
   ```
4. Sostituire tutte le occorrenze di `select_transport(dist)` usate per ottenere
   `travel_min` nello scheduling (Pass-1, Pass-3, `_add_activity_stop`, `_add_food_stop`,
   `_pick_nearest_open_food`) con `_travel(...)`. **Il TSP** (`_solve_tsp`) può restare su
   haversine per l'ordinamento (ottimizzazione interna, non mostra tempi all'utente) — oppure,
   meglio, usare la matrice reale come cost matrix del solver OR-Tools (vedi §8, opzionale).

> ⚠️ Anche `app/routers/itineraries.py` ricalcola i tempi in `get_itinerary` (riga ~309) con
> `select_transport(haversine...)`. Aggiornare anche lì per coerenza dei tempi mostrati quando si
> rilegge un itinerario salvato (lookup cache, fallback haversine).

---

## 7. Costo & limiti (per dimensionare)

- Prezzo Routes – Route Matrix: **$5 / 1.000 elementi** (Essentials, TRAFFIC_UNAWARE).
- Con cache: si paga ogni coppia (origin, dest, mode) **una volta**. Esempio città ~500 POI, ma si
  calcolano solo le coppie usate (~25²=625 per giorno-cluster, molte condivise tra itinerari) →
  poche migliaia di elementi totali per città → ben dentro il credito gratuito mensile (~$200).
- Limite hard: ≤625 elementi/richiesta → chunkare se necessario.
- `routingPreference: TRAFFIC_UNAWARE` per restare nello SKU economico.

---

## 8. (Opzionale, fase 2) Cost matrix reale nel TSP/solver

Oggi `_solve_tsp` (`itinerary_planner.py:431`) usa una dist-matrix haversine in OR-Tools. Una volta
disponibile la matrice reale in cache, la si può passare direttamente come cost matrix al solver →
ordinamento delle tappe basato sui tempi veri di percorrenza, non sulla linea d'aria. Migliora il
realismo del *percorso*, non solo dei *tempi mostrati*. Da fare dopo che §1–6 sono validati.

---

## Definition of done

- [ ] Tabella `poi_travel_times` creata + migrazione applicata + import in `models/__init__.py`.
- [ ] Config `google_routes_api_key` / `routes_api_enabled` aggiunte.
- [ ] `routes_client.py` con `compute_route_matrix` (field mask, parsing `"412s"`, retry/backoff).
- [ ] `get_travel_time` + `get_travel_times_batch` con lookup-cache-first e fallback haversine.
- [ ] Pre-fetch batch della matrice del giorno prima di `_schedule_day`; `travel_lookup` passato
      sincrono.
- [ ] Tutti i punti di scheduling usano i tempi reali; fallback haversine mai bloccante.
- [ ] `get_itinerary` (router) usa la cache per i tempi in lettura.
- [ ] Con `routes_api_enabled=False` il comportamento è identico a oggi (nessuna regressione).
- [ ] Log: numero di cache-hit vs API-call vs fallback per generazione (per monitorare il costo).

## Test minimi
- Unit: parsing risposta Routes (`"412s"` → 412), gestione `condition != ROUTE_EXISTS`.
- Unit: `get_travel_time` ritorna dalla cache senza chiamare la API se la riga esiste.
- Unit: con `routes_api_enabled=False` usa haversine e non chiama la rete.
- Integrazione: generare un itinerario con API spenta (deve funzionare come oggi) e con API
  finta/mock (deve popolare la cache e usarne i valori).
