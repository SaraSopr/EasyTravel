# Analisi qualità itinerari — perché escono incompleti/irrealistici e come dare la svolta

> Documento di analisi per la tesi. Obiettivo: capire le cause dei problemi attuali
> nella generazione degli itinerari e definire un piano di miglioramento + evaluation.

## Come funziona oggi (in breve)

Due fasi:

1. **Pipeline offline** (`backend/pipeline/pipeline.py`): Google Places grid-search → tourism
   validation LLM → classificazione LLM (vettore a 7 feature + categoria + indoor/outdoor) →
   opening hours.
2. **Generazione online** (`backend/app/services/itinerary_planner.py:1308`): filtro candidati →
   vettore utente + mode bias → split food/attività → **clustering geografico** in N cluster
   (Leiden, fallback KMeans) → per giorno: **MMR** (rilevanza+diversità) → scheduling greedy con
   pasti → **TSP** → ricalcolo orari con check opening hours.

È un'architettura *cluster-then-route* classica. Impianto solido, ma con punti precisi che
generano i due problemi: irrealismo e incompletezza.

---

## Perché gli itinerari escono IRREALISTICI

**1. I tempi di spostamento sono finti.** `select_transport` (`itinerary_planner.py:362`) usa
distanza **in linea d'aria** (haversine) divisa per velocità fissa: walking 1.39 m/s, transit
5.56 m/s (=20 km/h *senza attese*), taxi 8.33. Tre problemi sommati:
- la distanza reale a piedi/in auto è ~1.3–1.5× la linea d'aria (detour factor);
- il transit ignora attese, cambi, frequenza → 5 fermate "vicine" diventano 40 min reali, non 10;
- zero buffer per code, biglietti, parcheggio.

Risultato: il planner crede che la giornata regga 8 tappe, nella realtà ne reggi 5.
**Causa #1 dell'irrealismo.**

**2. Durate di visita statiche.** Le lookup table (`VISIT_DURATION_INDOOR`, `itinerary_planner.py:95`)
danno "museo = 120 min" sia al Louvre che a un museo civico. Il `tourism_duration_minutes`
dell'LLM ha priorità ed è la cosa giusta, ma la copertura dipende da quanto bene è girata la
pipeline. Nessun tempo-coda per le attrazioni iconiche.

**3. Detour del pasto post-TSP.** Il ristorante viene scelto in Pass-1 vicino alla posizione
greedy (`_pick_nearest_open_food`, `itinerary_planner.py:962`), ma poi il TSP riordina le attività
(Pass-2) e il pasto viene inserito in Pass-3 in una posizione diversa → può finire
geograficamente fuori rotta. Pranzi/cene "a zig-zag".

**4. Orari pasto rigidi** (13:00 / 20:00 hardcoded): non si adattano alle abitudini locali
(Spagna cena alle 21:30) né al ritmo della giornata.

---

## Perché gli itinerari escono INCOMPLETI (giornate corte/vuote)

**5. Il clustering è SOLO geografico e ignora la rilevanza.** `_cluster_pois`
(`itinerary_planner.py:592`) divide la città in N zone per prossimità, poi ogni giorno pesca solo
dal proprio cluster. Conseguenza grave: un giorno può capitare su una zona povera di must-see e
ricca di POI mediocri → giornata "completa" di cose insignificanti, mentre il Colosseo compete
solo dentro il *suo* cluster e può non entrare. Non c'è **nessuna garanzia che i top landmark
della città finiscano nell'itinerario**, e non c'è ottimizzazione cross-day.

**6. Il deferral per orari taglia tappe.** I POI chiusi all'arrivo vengono rimandati al giorno
dopo *solo se entro 4 km* dal cluster successivo (`itinerary_planner.py:1455`), altrimenti
spariscono in silenzio. Se mancano gli opening hours o la zona è chiusa quel giorno → giornata
che finisce alle 16.

**7. Penalità MMR troppo aggressive per il viaggiatore "monotematico".**
`SAME_CATEGORY_PENALTY 0.3` (`itinerary_planner.py:131`) + redundancy sul vettore: due grandi
musei si penalizzano a vicenda. Per un amante della cultura l'itinerario diventa "vario" ma
sbagliato, e salta gli ovvi.

**8. Vettore a 7 dimensioni troppo grezzo** (`backend/app/constants.py`). Cosine su 7 feature non
distingue due POI molto diversi della stessa macro-categoria: la rilevanza è approssimativa, e il
segnale che riempie la giornata è debole.

**9. Copertura dati a monte.** `rating ≥ 3.5` + `user_ratings_total ≥ 200`
(`app/routers/itineraries.py:119`) taglia la coda lunga: nelle città piccole rimani sotto soglia →
"Not enough POIs" o giorni vuoti.

---

## Le idee per la "svolta" (ordinate per impatto/sforzo)

### Alto impatto, sforzo medio — fai questi
1. **Tempi di viaggio realistici.** Minimo: detour factor 1.4 sulla distanza a piedi + overhead
   fisso transit (es. +8 min attesa). Meglio: una vera **distance matrix** (Google Distance Matrix,
   o **OSRM/Valhalla self-hosted** = gratis e citabile in tesi) calcolata sulle ~15-25 tappe
   candidate del giorno. È il singolo cambiamento che più alza il realismo.
2. **Garanzia must-see + selezione globale cross-day.** Prima del clustering, riserva i top-K
   landmark della città (per popolarità bayesiana × rilevanza) e *assegnali* ai giorni; poi riempi
   attorno. Così il Colosseo c'è sempre e i giorni sono bilanciati per qualità, non solo per
   geografia. Trasforma il problema da "cluster indipendenti" a "Orienteering Problem multi-giorno".
3. **Buffer realistici nel budget giornaliero**: tempo-coda scalato sulla popolarità per le
   attrazioni top, +10-15 min di "frizione" per tappa. Riduce il numero di tappe, ma è proprio ciò
   che rende l'itinerario *fattibile* davvero.

### Alto impatto, sforzo alto — la svolta concettuale per la tesi
4. **Riformula come Orienteering Problem / Team Orienteering with Time Windows (TOPTW).** È *il*
   modello accademico per il tourist trip design (Vansteenwegen et al.). Hai già OR-Tools per il
   TSP: estendilo a un VRP con time windows e "prize" = rilevanza, su tutti i giorni insieme.
   Sostituisce cluster→greedy→TSP con un'unica ottimizzazione che massimizza rilevanza totale
   rispettando orari di apertura e budget tempo reale. **Questo è il contributo "forte" tesabile.**
5. **Rappresentazione POI più ricca.** Sostituisci/affianca il vettore a 7 dim con **embedding**
   (da descrizione/recensioni/tipi). Rilevanza e diversità diventano molto più fini. Ottimo
   capitolo di tesi: ablation "7-feature vs embedding".

### Quick win (poche ore, alzano subito completezza)
6. Scegli il ristorante **dopo** il TSP, sulla posizione finale, non prima (fix del detour pasto).
7. Alza il raggio di deferral o ri-inserisci i deferred come pool globale invece di scartarli.
8. Rendi gli orari pasto **locali/configurabili** e abbassa `SAME_CATEGORY_PENALTY` quando l'utente
   ha una preferenza fortemente sbilanciata.
9. Attiva di default `--text-search` e abbassa la soglia ratings per città piccole, così la coda
   lunga non svuota le giornate.
10. **Partenza/arrivo dall'hotel**: chiedi l'alloggio e usalo come depot del TSP invece del centro
    città — più realistico e i giorni si "chiudono".

---

## Come fare una EVALUATION seria (la parte che dà la tesi)

Molte critiche qui sopra sono *misurabili*. Tre livelli:

### A. Metriche offline automatiche (su un set di città × profili utente)
- **Realismo temporale**: ricalcola i tempi reali delle tappe pianificate con Google Directions e
  misura l'**overrun** (% di giornate che NON entrano nel budget reale). È la "prima misura del
  problema" e il baseline per dimostrare il miglioramento.
- **Completezza**: tempo morto medio/giorno, % giornate che riempiono il budget, % itinerari con
  tutti i pasti, **landmark coverage** (% dei top-N POI città inclusi).
- **Rilevanza**: nDCG / precision@k dei POI inclusi vs preferenze utente.
- **Diversità & novelty**: intra-list diversity, entropia di categoria.

### B. Ablation studies (cuore metodologico)
- routing reale vs haversine (mostra il salto di realismo)
- TOPTW globale vs cluster→greedy attuale
- MMR λ sweep; embedding vs 7-feature
- con/senza buffer.

### C. Validazione umana (anche piccola N basta)
- user study 10–20 persone: Likert su *realismo / completezza / soddisfazione*; **SUS** per l'app.
- baseline forte e attuale: **itinerario generato da un LLM** ("pianifica 3 giorni a Roma per questo
  profilo") come confronto — buona discussione "sistema strutturato vs LLM puro".

Baseline da battere: (1) ranking solo-popolarità, (2) greedy nearest-neighbor, (3) LLM puro.

---

## Raccomandazione, in una riga

Se devi scegliere *una* svolta: **routing reale (OSRM) + riformulazione come TOPTW multi-giorno con
garanzia must-see**. Risolve in un colpo sia irrealismo (tempi veri + buffer) sia incompletezza
(ottimizzazione globale invece di cluster ciechi), ed è esattamente il tipo di contributo che regge
una tesi e una evaluation con ablation. Il passaggio vettore→embedding è il secondo capitolo,
opzionale ma elegante.

### Prossimo passo suggerito
Tre opzioni di partenza:
- **(a)** strumento di misura dell'overrun temporale — quantifica subito quanto sono irrealistici
  gli itinerari attuali e fornisce il baseline per la tesi;
- **(b)** quick-win 6–10;
- **(c)** prototipo del solver TOPTW su OR-Tools.
