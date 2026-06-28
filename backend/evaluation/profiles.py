"""Frozen evaluation profiles (see docs/evaluation-harness-spec.md §1).

Each profile fixes everything the planner reads: the 7-dim preference vector
(order = app.constants.FEATURE_NAMES), travel_mode, age_range and whether
travelling with children. The vectors are intensities in [0, 1]; the planner
normalises them and adds the per-mode bias. Frozen here for reproducibility —
the harness writes them straight into an in-memory UserPreference, bypassing the
LLM-driven onboarding so the same profile always yields the same input.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    travel_mode: str          # "solo" | "couple" | "friends" | "family"
    age_range: str
    children: bool
    vector: dict[str, float] = field(default_factory=dict)
    note: str = ""              # internal: what this profile stresses in the harness
    description: str = ""       # human-facing persona shown to evaluators in the dashboard


PROFILES: list[Profile] = [
    Profile(
        key="senior_solo_culture",
        label="Anziano solo, culturale",
        travel_mode="solo", age_range="70-80", children=False,
        vector={"nature": 0.2, "culture": 0.9, "food": 0.5, "adventure": 0.05,
                "nightlife": 0.0, "relax": 0.7, "family_friendly": 0.1},
        note="Senior mobility (tight radius) + culture relevance",
        description=(
            "Un viaggiatore over 70 in giro da solo, appassionato di musei, monumenti e storia. "
            "Cammina volentieri ma a ritmo tranquillo e ama le pause; poco interessato a vita "
            "notturna e avventura."
        ),
    ),
    Profile(
        key="couple_foodie",
        label="Coppia foodie-romantica",
        travel_mode="couple", age_range="30-40", children=False,
        vector={"nature": 0.3, "culture": 0.6, "food": 0.9, "adventure": 0.2,
                "nightlife": 0.3, "relax": 0.7, "family_friendly": 0.0},
        description=(
            "Una coppia sui 30-40 anni in fuga romantica: la priorità è mangiare benissimo e "
            "godersi atmosfere intime. Ama rilassarsi e un po' di cultura, con qualche locale la "
            "sera — ma niente di troppo turistico o frenetico."
        ),
    ),
    Profile(
        key="young_solo_outdoor",
        label="Giovane solo, outdoor/avventura",
        travel_mode="solo", age_range="20-30", children=False,
        vector={"nature": 0.8, "culture": 0.4, "food": 0.5, "adventure": 0.9,
                "nightlife": 0.5, "relax": 0.2, "family_friendly": 0.0},
        description=(
            "Un ventenne in viaggio da solo a caccia di natura, panorami e attività all'aperto. "
            "Vuole esperienze attive e un po' di movimento serale; la cultura va bene, ma musei e "
            "relax lo annoiano in fretta."
        ),
    ),
    Profile(
        key="friends_nightlife",
        label="Gruppo di amici, nightlife/social",
        travel_mode="friends", age_range="20-30", children=False,
        vector={"nature": 0.2, "culture": 0.3, "food": 0.7, "adventure": 0.7,
                "nightlife": 0.9, "relax": 0.2, "family_friendly": 0.0},
        note="Exercises the 'friends' bias branch (nightlife/adventure)",
        description=(
            "Un gruppo di amici ventenni in cerca di vita notturna, locali e socialità. Cibo e "
            "attività movimentate sì, ma la serata è il cuore del viaggio; cultura e relax sono "
            "in secondo piano."
        ),
    ),
    Profile(
        key="family_toddlers",
        label="Famiglia, bimbi piccoli",
        travel_mode="family", age_range="35-45", children=True,
        vector={"nature": 0.7, "culture": 0.4, "food": 0.5, "adventure": 0.4,
                "nightlife": 0.0, "relax": 0.6, "family_friendly": 1.0},
        note="suitable_for_children filter + no-nightlife + tight radius",
        description=(
            "Una famiglia con bambini piccoli: servono luoghi adatti ai più piccoli, spazi aperti "
            "e ritmi morbidi. Niente vita notturna, distanze contenute e attività "
            "family-friendly prima di tutto."
        ),
    ),
    Profile(
        key="family_teen",
        label="Famiglia, adolescente",
        travel_mode="family", age_range="40-50", children=True,
        vector={"nature": 0.5, "culture": 0.6, "food": 0.6, "adventure": 0.7,
                "nightlife": 0.1, "relax": 0.3, "family_friendly": 0.5},
        note="Edge case: system does not distinguish kid age → future work",
        description=(
            "Una famiglia con un figlio adolescente: un mix di cultura, avventura e buon cibo per "
            "accontentare grandi e ragazzi. Vogliono giornate varie e stimolanti, senza eccessi "
            "notturni."
        ),
    ),
    Profile(
        key="couple_museums",
        label="Coppia 'solo musei' (monotematico)",
        travel_mode="couple", age_range="50-60", children=False,
        vector={"nature": 0.1, "culture": 1.0, "food": 0.4, "adventure": 0.1,
                "nightlife": 0.1, "relax": 0.4, "family_friendly": 0.0},
        note="Probes whether MMR diversity penalty hurts a mono-thematic user",
        description=(
            "Una coppia matura appassionata d'arte e storia: vogliono musei, gallerie e siti "
            "storici, praticamente nient'altro. Natura, avventura e vita notturna sono quasi "
            "irrilevanti per loro."
        ),
    ),
    Profile(
        key="young_solo_relax",
        label="Giovane solo, relax/benessere",
        travel_mode="solo", age_range="25-35", children=False,
        vector={"nature": 0.6, "culture": 0.3, "food": 0.6, "adventure": 0.2,
                "nightlife": 0.2, "relax": 0.9, "family_friendly": 0.0},
        note="Low sightseeing intensity → stresses completeness (empty days?)",
        description=(
            "Un giovane in viaggio da solo per staccare: cerca relax, benessere, natura tranquilla "
            "e buon cibo. Poco sightseeing intenso, nessuna fretta — il viaggio è una pausa, non "
            "una maratona."
        ),
    ),
    Profile(
        key="couple_generalist",
        label="Coppia generalista (turista medio)",
        travel_mode="couple", age_range="30-40", children=False,
        vector={"nature": 0.5, "culture": 0.6, "food": 0.6, "adventure": 0.4,
                "nightlife": 0.3, "relax": 0.5, "family_friendly": 0.0},
        note="Neutral reference profile",
        description=(
            "Una coppia sui 30-40 anni, turisti \"medi\": vogliono un po' di tutto in modo "
            "equilibrato — cultura, buon cibo, natura e qualche attività. Il profilo di "
            "riferimento, senza preferenze estreme."
        ),
    ),
]

PROFILES_BY_KEY: dict[str, Profile] = {p.key: p for p in PROFILES}
