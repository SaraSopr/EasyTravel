#!/usr/bin/env python3
"""Generate baked demo trace JSON files for the thesis defense visualiser.

Usage (from backend/):
    source .venv/bin/activate
    python scripts/generate_demo_traces.py --city Roma --days 3

The script calls POST /api/demo/plan-trace for each persona (plus
GET /api/demo/ingestion once) and saves the responses to
frontend/public/demo-traces/{persona_id}.json and ingestion.json.

Re-run whenever POI data changes AND whenever the trace schema changes
(TRACE_VERSION in app/services/demo_trace.py) — the frontend rejects baked
traces with a stale version instead of rendering them.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add backend root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def generate(
    city: str,
    num_days: int,
    base_url: str | None = None,
    ingestion_only: bool = False,
) -> None:
    # Keep HTTP mode stdlib-only: importing the backend service here would require
    # all Python dependencies even when a remote API is doing the actual work.
    personas = [] if ingestion_only else [
        "couple_museums",
        "young_solo_outdoor",
        "couple_generalist",
        "family_with_kids",
    ]
    out_dir = (
        Path(__file__).parent.parent.parent
        / "frontend" / "public" / "demo-traces"
    )

    def save(name: str, payload: dict) -> None:
        out_path = out_dir / f"{name}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"saved → {out_path}")

    if base_url:
        # HTTP mode: call the running server (stdlib only, no extra deps)
        import urllib.parse
        import urllib.request

        for persona_id in personas:
            print(f"  Fetching {persona_id} …", end=" ", flush=True)
            payload = {
                "city": city,
                "persona_id": persona_id,
                "num_days": num_days,
                "solver": "both",
            }
            req = urllib.request.Request(
                f"{base_url}/api/demo/plan-trace",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                trace = json.load(resp)
            save(persona_id, trace)

        print("  Fetching ingestion summary …", end=" ", flush=True)
        query = urllib.parse.urlencode({"city": city})
        with urllib.request.urlopen(
            f"{base_url}/api/demo/ingestion?{query}", timeout=300,
        ) as resp:
            save("ingestion", json.load(resp))
    else:
        # Direct mode: import and call service directly (requires DB env)
        from app.database import AsyncSessionLocal
        from app.services.demo_ingestion import build_ingestion_summary
        from app.services.demo_trace import build_trace

        async with AsyncSessionLocal() as db:
            for persona_id in personas:
                print(f"  Building trace for {persona_id} …", end=" ", flush=True)
                trace = await build_trace(
                    db=db,
                    city_name=city,
                    persona_id=persona_id,
                    num_days=num_days,
                    solver="both",
                )
                save(persona_id, trace)

            print("  Building ingestion summary …", end=" ", flush=True)
            save("ingestion", await build_ingestion_summary(db, city))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate demo trace JSON files")
    parser.add_argument("--city", default="Roma", help="City name (must exist in DB)")
    parser.add_argument("--days", type=int, default=3, help="Number of days")
    parser.add_argument(
        "--url", default=None,
        help="Base URL of running server (e.g. http://localhost:8000). "
             "If omitted, calls the service layer directly.",
    )
    parser.add_argument(
        "--ingestion-only", action="store_true",
        help="Regenerate only ingestion.json (skip the slow persona traces). "
             "Use when only INGESTION_VERSION changed.",
    )
    args = parser.parse_args()

    print(f"Generating demo traces: city={args.city!r} days={args.days}")
    asyncio.run(generate(args.city, args.days, args.url, args.ingestion_only))
    print("Done.")
