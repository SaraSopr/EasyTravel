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
    # When True, candidates are geographically pre-clustered into one group per day
    # (same clustering the greedy baseline uses) and each POI is pinned to its
    # cluster's day. Keeps each day spatially compact at the cost of the solver's
    # freedom to balance prize across days. Default off → global TOPTW (thesis A/B).
    toptw_pre_cluster: bool = False
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
