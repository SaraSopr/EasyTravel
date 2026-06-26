# Spec: Leiden-based Geographic Clustering for Itinerary Planning

## Problema

L'attuale implementazione usa **KMeans** sulle coordinate (lat, lng) dei POI per suddividere i punti di interesse in `num_days` cluster geografici, uno per giorno.

KMeans ottimizza la compattezza interna dei cluster ma non garantisce bilanciamento numerico. In città con distribuzione disomogenea dei POI (es. centro storico denso + periferia rada), produce cluster con pochissimi POI che non riescono a riempire una giornata. Il `_rebalance_clusters` tampona il problema ma compromette la coerenza geografica rubando POI da cluster vicini.

---

## Approccio proposto: Leiden su grafo k-NN geografico

### Idea centrale

Invece di forzare `k = num_days` cluster su dati geografici, si costruisce un **grafo di prossimità** tra i POI e si applica l'algoritmo di **Leiden** (Traag et al., 2019) per scoprire comunità geografiche naturali — i "quartieri" della città. Le comunità trovate (tipicamente più di `num_days`) vengono poi aggregate in esattamente `num_days` gruppi bilanciati.

L'intuizione è che Leiden trova i confini naturali del territorio (es. centro storico, zona museale, quartiere moderno), mentre il passo di aggregazione garantisce il vincolo operativo sul numero di giorni.

### Perché Leiden e non altri algoritmi di community detection

- **Leiden vs Louvain**: Leiden garantisce che ogni community sia internamente ben connessa (no subset disconnessi), problema noto di Louvain. Questo è importante per la coerenza geografica.
- **Leiden vs DBSCAN**: DBSCAN richiede la scelta di `eps` (raggio) ed è sensibile ai parametri; Leiden è più robusto tramite il parametro di risoluzione `γ`.
- **Leiden vs KMeans**: KMeans forza cluster isotropi e richiede `k` come input; Leiden trova strutture arbitrarie e il numero di community emerge dai dati.

---

## Pipeline di implementazione

### Step 1 — Costruzione del grafo k-NN

Per ogni POI `i`, si collegano i `k` POI più vicini (default `k = 10`) con un arco pesato:

```
w(i, j) = exp(−d(i,j) / σ)
```

dove `d(i,j)` è la distanza di Haversine in metri e `σ` è la distanza mediana tra tutti i vicini (scala adattiva). Il peso tende a 1 per POI molto vicini e a 0 per POI lontani.

Questo produce un grafo sparso dove i POI geograficamente prossimi sono fortemente connessi.

### Step 2 — Rilevamento delle community con Leiden

Si esegue l'algoritmo Leiden con la **Modularity** come funzione obiettivo e un parametro di risoluzione `γ` (default `γ = 1.0`). Leiden massimizza:

```
Q = Σ_{c} [e_c / m − γ · (a_c / 2m)²]
```

dove `e_c` è il peso degli archi interni alla community `c`, `m` il peso totale degli archi, `a_c` la somma dei gradi dei nodi in `c`.

Valori più alti di `γ` producono più community (quartieri più fini); valori più bassi ne producono meno (aree più ampie). Se il numero di community trovate è troppo basso rispetto a `num_days`, si aumenta `γ` iterativamente.

### Step 3 — Aggregazione delle community in `num_days` giorni

Le community trovate da Leiden vengono aggregate in esattamente `num_days` gruppi tramite **merge gerarchico**:

1. Si calcola il centroide geografico di ogni community.
2. Si costruisce un secondo grafo tra community, dove il peso dell'arco è la distanza tra centroidi.
3. Si eseguono `n_communities − num_days` merge successivi, unendo ad ogni passo le due community geograficamente più vicine (equivalente a **single-linkage agglomerative clustering** tra community).

Questo garantisce che i giorni risultanti siano geograficamente contigui e che il numero finale sia esattamente `num_days`.

### Step 4 — Rebalancing opzionale

Se dopo il merge alcuni giorni hanno ancora troppo pochi POI (< `_MIN_CLUSTER_SIZE`), si applica il rebalancing esistente. Con Leiden il rebalancing dovrebbe intervenire molto meno frequentemente rispetto a KMeans, perché la distribuzione di partenza è più naturale.

---

## Parametri

| Parametro | Default | Descrizione |
|-----------|---------|-------------|
| `k_neighbors` | 10 | Vicini per costruire il grafo k-NN |
| `leiden_resolution` | 1.0 | Risoluzione γ di Leiden (↑ = più community) |
| `sigma_scale` | mediana distanze | Scala per la funzione peso degli archi |

---

## Dipendenze da aggiungere

```
leidenalg>=0.10.0
python-igraph>=0.11.0
```

`leidenalg` richiede `python-igraph` come backend per la rappresentazione del grafo.

---

## Confronto con l'approccio attuale

| Aspetto | KMeans attuale | Leiden proposto |
|---------|---------------|-----------------|
| Numero cluster | Fissato a `num_days` | Emerge dai dati, poi aggregato |
| Forma dei cluster | Isotropa (sferica) | Arbitraria (segue la struttura urbana) |
| Bilanciamento numerico | Non garantito | Migliore per costruzione |
| Coerenza geografica | Può degradare con rebalancing | Preservata nel merge gerarchico |
| Robustezza a outlier | Bassa | Alta (outlier formano community proprie) |
| Complessità implementativa | Bassa | Media |
| Interpretabilità | Alta | Alta (community = quartieri reali) |

---

## Riferimenti

- Traag, V.A., Waltman, L., van Eck, N.J. (2019). *From Louvain to Leiden: guaranteeing well-connected communities*. Scientific Reports, 9, 5233.
- Blondel, V.D. et al. (2008). *Fast unfolding of communities in large networks*. Journal of Statistical Mechanics.
- sklearn documentation: `AgglomerativeClustering`, `NearestNeighbors`
