from pydantic import AliasChoices, ConfigDict, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080
    google_places_api_key: str = ""
    google_places_enabled: bool = False
    # Google Routes API (Compute Route Matrix) for real road travel times.
    # May reuse google_places_api_key if Routes API is enabled on the same key.
    google_routes_api_key: str = ""
    routes_api_enabled: bool = False  # master switch: if False → always haversine
    # Itinerary solver selection (see docs/toptw-itinerary-solver-spec.md):
    #   "greedy" — current cluster→MMR→greedy pipeline (baseline)
    #   "toptw"  — Team Orienteering Problem with Time Windows (OR-Tools)
    itinerary_solver: str = "toptw"
    # TOPTW hyperparameters (exposed for the thesis ablation/sweep).
    toptw_num_candidates: int = 80       # N: top-N activity candidates fed to the solver
    toptw_prize_scale: int = 100_000     # scales prize vs travel-seconds in the objective
    toptw_time_limit_s: int = 20         # solver wall-clock budget
    toptw_meal_reserve_min: int = 150    # time reserved in the day budget for post-inserted meals
    toptw_w_sim: float = 0.7             # prize weight: cosine similarity
    toptw_w_pop: float = 0.3             # prize weight: popularity
    # Meal selection quality (shared by both solvers). The meal post-pass no longer
    # picks the strictly nearest open food; it scores open candidates within a
    # walkable radius by proximity + rating and penalises takeaway/snack joints, so a
    # proper trattoria beats a closer fast-food/takeaway. Falls back to nearest if
    # nothing sits within the radius (never fails to place a meal). A/B-able.
    food_pick_radius_m: float = 700.0    # consideration radius around the route point
    food_w_distance: float = 0.6         # weight on proximity (0..1, higher = closer wins)
    food_w_rating: float = 0.4           # weight on Google rating
    food_takeaway_penalty: float = 0.3   # score penalty for takeaway/delivery-primary POIs
    # Activity selection radius from city centre. In "fixed" mode this is the
    # exact radius. In "adaptive" mode it is the compact-city minimum: the planner
    # expands only when the candidate POI distribution is sparse/extended.
    # Food POIs are NOT affected.
    activity_radius_mode: str = Field(
        "adaptive",
        validation_alias=AliasChoices("ITINERARY_ACTIVITY_RADIUS_MODE", "ACTIVITY_RADIUS_MODE"),
    )
    activity_radius_km: float = Field(
        8.0,
        validation_alias=AliasChoices("ITINERARY_ACTIVITY_RADIUS_KM", "ACTIVITY_RADIUS_KM"),
    )
    activity_radius_target_share: float = Field(
        0.85,
        validation_alias=AliasChoices("ITINERARY_ACTIVITY_RADIUS_TARGET_SHARE", "ACTIVITY_RADIUS_TARGET_SHARE"),
    )
    activity_radius_min_pois_per_day: int = Field(
        8,
        validation_alias=AliasChoices("ITINERARY_ACTIVITY_RADIUS_MIN_POIS_PER_DAY", "ACTIVITY_RADIUS_MIN_POIS_PER_DAY"),
    )
    # Geographic pre-clustering: candidates are grouped into one cluster per day and
    # each POI pinned to its cluster's day, keeping each day spatially compact. Works
    # well once the activity-radius filter has removed far outliers — then both Madrid
    # and Roma cluster into balanced halves and pre-clustering helps both (it fixes
    # Roma's badly-balanced days). Without the radius filter, outliers form a degenerate
    # periphery cluster and pre-clustering backfires; "auto" guards against that.
    #   "off"  — never pre-cluster → global TOPTW (thesis A/B arm / baseline).
    #   "on"   — always pre-cluster (thesis A/B arm).
    #   "auto" — pre-cluster only when the day-clusters are geographically balanced;
    #            a degenerate split (one dominant cluster + a sparse tail) falls back
    #            to global TOPTW. Best-of-both, the default.
    toptw_pre_cluster_mode: str = Field(
        "auto",
        validation_alias=AliasChoices("TOPTW_PRE_CLUSTER_MODE", "ITINERARY_TOPTW_PRE_CLUSTER_MODE"),
    )
    # "auto" threshold: pre-cluster only if the smallest day-cluster holds at least
    # this fraction of an even share (size / (N/num_days)). 1.0 = perfectly balanced;
    # Madrid ≈ 0.01 (degenerate), Roma ≈ 0.84 (balanced). 0.35 separates them.
    toptw_cluster_balance_min: float = 0.35
    cache_ttl_days: int = 30
    cloudflare_r2_access_key_id: str | None = None
    cloudflare_r2_secret_access_key: str | None = None
    cloudflare_r2_account_id: str | None = None
    cloudflare_r2_bucket_name: str | None = None
    cloudflare_r2_public_url: str | None = None
    resend_api_key: str | None = None
    from_email: str = "onboarding@resend.dev"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    pipeline_llm_backend: str = "openai"
    pipeline_llm_model: str = "gpt-5.4-mini"
    # OpenAI reasoning models bill reasoning tokens as output. Classification is a
    # simple task → keep this low. "none" is cheapest; bump to "low" if the model
    # rejects "none". Ignored by the Anthropic backend.
    pipeline_reasoning_effort: str = "none"
    # OpenAI native structured outputs (json_schema strict) for classification +
    # tourism validation → guarantees valid JSON, removes parse-failure retries.
    # Default off so the base run is unchanged; flip to true after a small test.
    openai_structured_output: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]
    dev_mode: bool = False
    dev_user_email: str = ""

    model_config = ConfigDict(env_file=".env")


settings = Settings()
