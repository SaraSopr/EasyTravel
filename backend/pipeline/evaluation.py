"""
Evaluation utilities for thesis prompt validation.
Run directly: python pipeline/evaluation.py --city Roma
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter

import numpy as np
from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.classification_log import PoiClassificationLog
from app.models.tourism_validation_log import PoiTourismValidationLog


async def get_agreement_stats(
    city_name: str | None = None,
    pipeline_run_id: str | None = None,
) -> dict:
    """
    Compute inter-rater agreement statistics between LLM1 and LLM2.

    Returns:
    - total_classified: int
    - category_agreement_rate: float (0-1)
    - mean_cosine_distance: float (0=identical, 1=opposite)
    - std_cosine_distance: float
    - disagreement_by_category: dict {category: count}
    - failed_count: int
    - confidence_distribution: dict {high/medium/failed: count}
    """
    async with AsyncSessionLocal() as session:
        query = select(PoiClassificationLog)
        if city_name:
            query = query.where(PoiClassificationLog.city_name == city_name)
        if pipeline_run_id:
            query = query.where(PoiClassificationLog.pipeline_run_id == pipeline_run_id)

        result = await session.execute(query)
        logs = result.scalars().all()

        if not logs:
            return {"error": "No logs found"}

        total = len(logs)
        agreements = [l for l in logs if l.category_agreement is True]
        disagreements = [l for l in logs if l.category_agreement is False]
        failed = [l for l in logs if l.final_confidence == "failed"]

        distances = [
            l.vector_cosine_distance
            for l in logs
            if l.vector_cosine_distance is not None
        ]

        # Which category pairs disagree most
        disagreement_cats = Counter()
        for l in disagreements:
            pair = tuple(sorted([
                l.llm1_category or "unknown",
                l.llm2_category or "unknown",
            ]))
            disagreement_cats[f"{pair[0]} vs {pair[1]}"] += 1

        confidence_dist = Counter(l.final_confidence for l in logs)

        return {
            "total_classified": total,
            "category_agreement_rate": len(agreements) / total,
            "mean_cosine_distance": float(np.mean(distances)) if distances else None,
            "std_cosine_distance": float(np.std(distances)) if distances else None,
            "disagreement_count": len(disagreements),
            "top_disagreements": dict(disagreement_cats.most_common(5)),
            "failed_count": len(failed),
            "failed_rate": len(failed) / total,
            "confidence_distribution": dict(confidence_dist),
        }


async def get_vector_consistency(
    city_name: str | None = None,
) -> dict:
    """
    Analyze consistency of feature vectors across LLM1 and LLM2
    for POIs where category agreed.

    Returns per-category statistics:
    - mean cosine distance between LLM1 and LLM2 vectors
    - identifies which dimensions vary most
    """
    async with AsyncSessionLocal() as session:
        query = select(PoiClassificationLog).where(
            PoiClassificationLog.category_agreement == True  # noqa: E712
        )
        if city_name:
            query = query.where(PoiClassificationLog.city_name == city_name)

        result = await session.execute(query)
        logs = result.scalars().all()

        DIMS = ["nature", "culture", "food", "adventure", "nightlife", "relax", "family_friendly"]

        by_category: dict[str, list] = {}
        for log in logs:
            cat = log.llm1_category or "unknown"
            v1 = log.llm1_vector or []
            v2 = log.llm2_vector or []
            if len(v1) == 7 and len(v2) == 7:
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append({
                    "dim_diffs": [abs(a - b) for a, b in zip(v1, v2)],
                    "cosine_dist": log.vector_cosine_distance,
                })

        stats = {}
        for cat, entries in by_category.items():
            dim_diffs = np.array([e["dim_diffs"] for e in entries])
            valid_dists = [e["cosine_dist"] for e in entries if e["cosine_dist"] is not None]
            stats[cat] = {
                "count": len(entries),
                "mean_cosine_distance": float(np.mean(valid_dists)) if valid_dists else 0.0,
                "most_variable_dimension": DIMS[int(np.mean(dim_diffs, axis=0).argmax())],
                "per_dimension_mean_diff": {
                    dim: float(np.mean(dim_diffs[:, i]))
                    for i, dim in enumerate(DIMS)
                },
            }

        return stats


async def get_category_distribution(
    city_name: str | None = None,
) -> dict:
    """Distribution of final categories assigned."""
    async with AsyncSessionLocal() as session:
        query = select(
            PoiClassificationLog.final_category,
            func.count().label("count"),
        ).group_by(PoiClassificationLog.final_category)

        if city_name:
            query = query.where(PoiClassificationLog.city_name == city_name)

        result = await session.execute(query)
        return {row.final_category: row.count for row in result}


async def get_tourism_validation_stats(
    city_name: str | None = None,
    pipeline_run_id: str | None = None,
) -> dict:
    """
    Statistics on tourism validation decisions.

    Returns:
    - total_validated: int
    - touristic_rate: float
    - llm2_needed_rate: float (how often LLM1 was uncertain)
    - disagreement_rate: float (LLM1 low + LLM2 disagreed)
    - visit_type_distribution: dict
    - duration_stats: dict {indoor_mean_minutes, outdoor_mean_minutes}
    """
    async with AsyncSessionLocal() as session:
        query = select(PoiTourismValidationLog)
        if city_name:
            query = query.where(PoiTourismValidationLog.city_name == city_name)
        if pipeline_run_id:
            query = query.where(PoiTourismValidationLog.pipeline_run_id == pipeline_run_id)

        result = await session.execute(query)
        logs = result.scalars().all()

        if not logs:
            return {"error": "No tourism validation logs found"}

        total = len(logs)
        touristic = [l for l in logs if l.final_is_touristic is True]
        llm2_needed = [l for l in logs if l.llm2_was_needed]
        disagreements = [l for l in logs if l.decision_source == "disagreement"]

        indoor = [
            l for l in touristic
            if l.final_visit_type == "indoor" and l.final_duration_minutes
        ]
        outdoor = [
            l for l in touristic
            if l.final_visit_type == "outdoor" and l.final_duration_minutes
        ]

        return {
            "total_validated": total,
            "touristic_count": len(touristic),
            "touristic_rate": len(touristic) / total,
            "non_touristic_count": total - len(touristic),
            "llm2_needed_count": len(llm2_needed),
            "llm2_needed_rate": len(llm2_needed) / total,
            "disagreement_count": len(disagreements),
            "disagreement_rate": (
                len(disagreements) / len(llm2_needed) if llm2_needed else 0
            ),
            "visit_type_distribution": {
                vt: sum(1 for l in touristic if l.final_visit_type == vt)
                for vt in ["indoor", "outdoor", "both"]
            },
            "duration_stats": {
                "indoor_mean_minutes": (
                    int(np.mean([l.final_duration_minutes for l in indoor]))
                    if indoor else None
                ),
                "outdoor_mean_minutes": (
                    int(np.mean([l.final_duration_minutes for l in outdoor]))
                    if outdoor else None
                ),
            },
        }


async def print_evaluation_report(city_name: str | None = None) -> None:
    """Print a formatted evaluation report to stdout."""
    print(f"\n{'=' * 60}")
    print(f"PROMPT EVALUATION REPORT — {city_name or 'ALL CITIES'}")
    print(f"{'=' * 60}\n")

    stats = await get_agreement_stats(city_name=city_name)
    if "error" in stats:
        print(f"Error: {stats['error']}")
        return

    print(f"Total POIs classified: {stats['total_classified']}")
    print(
        f"Category agreement rate (LLM1 vs LLM2): "
        f"{stats['category_agreement_rate']:.1%}"
    )
    if stats["mean_cosine_distance"] is not None:
        print(
            f"Mean cosine distance between vectors: "
            f"{stats['mean_cosine_distance']:.4f} "
            f"(±{stats['std_cosine_distance']:.4f})"
        )
    print(
        f"Failed classifications: "
        f"{stats['failed_count']} ({stats['failed_rate']:.1%})"
    )

    print(f"\nConfidence distribution:")
    for conf, count in stats["confidence_distribution"].items():
        pct = count / stats["total_classified"]
        print(f"  {conf:10s}: {count:4d} ({pct:.1%})")

    print(f"\nTop disagreement pairs (LLM1 vs LLM2):")
    for pair, count in stats["top_disagreements"].items():
        print(f"  {pair}: {count}")

    print(f"\nVector consistency by category:")
    consistency = await get_vector_consistency(city_name=city_name)
    for cat, data in sorted(consistency.items()):
        print(
            f"  {cat:15s}: {data['count']:3d} POIs, "
            f"mean distance={data['mean_cosine_distance']:.4f}, "
            f"most variable dim={data['most_variable_dimension']}"
        )

    print(f"\nCategory distribution:")
    dist = await get_category_distribution(city_name=city_name)
    for cat, count in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"  {cat:15s}: {count}")

    print(f"\nTourism Validation Stats:")
    tv_stats = await get_tourism_validation_stats(city_name=city_name)
    if "error" not in tv_stats:
        print(f"  Total validated:    {tv_stats['total_validated']}")
        print(
            f"  Touristic:          {tv_stats['touristic_count']} "
            f"({tv_stats['touristic_rate']:.1%})"
        )
        print(
            f"  LLM2 needed:        {tv_stats['llm2_needed_count']} "
            f"({tv_stats['llm2_needed_rate']:.1%})"
        )
        print(
            f"  Disagreements:      {tv_stats['disagreement_count']} "
            f"({tv_stats['disagreement_rate']:.1%} of uncertain cases)"
        )
        print(f"  Duration stats:     {tv_stats['duration_stats']}")
    else:
        print(f"  {tv_stats['error']}")

    print(f"\n{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate POI classification prompt quality")
    parser.add_argument("--city", default=None)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    asyncio.run(print_evaluation_report(city_name=args.city))


if __name__ == "__main__":
    main()
