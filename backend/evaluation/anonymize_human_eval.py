"""Export evaluation_ratings / evaluation_likert with evaluator identities anonymized.

evaluator_id is a free-text field the frontend fills from a URL query param, so it
currently holds participants' real first names rather than opaque IDs.
This script reads the two tables read-only and writes anonymized CSV/JSON copies
for use in the thesis dataset — it never modifies the database.

Each distinct evaluator_id is mapped to a sequential number (1, 2, 3, ...) in the
order it's first seen, so the same person gets the same number in both output
files (needed for the sign-test / Wilcoxon pairing in human_eval_stats.py). The
name -> number correspondence is written to mapping.txt so it can be recovered
later if needed; keep that file out of anything shared publicly.

Usage:
    python -m evaluation.anonymize_human_eval
    python -m evaluation.anonymize_human_eval --out-dir evaluation/anonymized
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path

from sqlalchemy import text

from app.database import AsyncSessionLocal


def _anonymize(evaluator_id: str, mapping: dict[str, int]) -> int:
    if evaluator_id not in mapping:
        mapping[evaluator_id] = len(mapping) + 1
    return mapping[evaluator_id]


async def _fetch(query: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(query))
        return [dict(row._mapping) for row in result.fetchall()]


def _write(rows: list[dict], out_dir: Path, name: str) -> None:
    if not rows:
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{name}.csv"
    json_path = out_dir / f"{name}.json"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, default=str, indent=2, ensure_ascii=False)

    print(f"wrote {len(rows)} rows -> {csv_path}, {json_path}")


def _write_mapping(mapping: dict[str, int], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = out_dir / "mapping.txt"
    with mapping_path.open("w", encoding="utf-8") as f:
        for name, number in sorted(mapping.items(), key=lambda kv: kv[1]):
            f.write(f"{number}\t{name}\n")
    print(f"wrote correspondence -> {mapping_path}")


async def main(out_dir: Path) -> None:
    mapping: dict[str, int] = {}

    ratings = await _fetch(
        "SELECT id, pair_id, evaluator_id, choice, created_at FROM evaluation_ratings"
    )
    likert = await _fetch(
        "SELECT id, itinerary_id, evaluator_id, realism, completeness, profile_fit, overall, created_at "
        "FROM evaluation_likert"
    )

    for row in ratings:
        row["evaluator_id"] = _anonymize(row["evaluator_id"], mapping)
    for row in likert:
        row["evaluator_id"] = _anonymize(row["evaluator_id"], mapping)

    _write(ratings, out_dir, "evaluation_ratings_anon")
    _write(likert, out_dir, "evaluation_likert_anon")
    _write_mapping(mapping, out_dir)

    print(f"\n{len(mapping)} distinct evaluators anonymized.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("evaluation/anonymized"),
        help="directory to write anonymized CSV/JSON/mapping into (default: evaluation/anonymized)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.out_dir))
