"""
Pytest test suite for prompt evaluation.
Tests are data-driven: they query the DB and assert quality thresholds.

Requirements: pip install pytest pytest-asyncio

Run: pytest tests/test_classifier_evaluation.py -v
"""
import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from jinja2 import Environment, FileSystemLoader

from pipeline.evaluation import (
    get_agreement_stats,
    get_category_distribution,
    get_tourism_validation_stats,
    get_vector_consistency,
)

# ── Quality thresholds (tune for your thesis) ──────────────────────
MIN_AGREEMENT_RATE = 0.70        # LLM1 vs LLM2 agree at least 70%
MAX_MEAN_COSINE_DISTANCE = 0.35  # vectors are not too different
MAX_FAILED_RATE = 0.10           # at most 10% failed classifications
MIN_CATEGORY_COVERAGE = 5        # at least 5 distinct categories used
MIN_HIGH_CONFIDENCE_RATE = 0.50  # at least 50% high confidence
# ───────────────────────────────────────────────────────────────────

CITY = "Roma"  # change to test other cities


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def stats():
    return await get_agreement_stats(city_name=CITY)


@pytest_asyncio.fixture(scope="session")
async def consistency():
    return await get_vector_consistency(city_name=CITY)


@pytest_asyncio.fixture(scope="session")
async def distribution():
    return await get_category_distribution(city_name=CITY)


@pytest_asyncio.fixture(scope="session")
async def tv_stats():
    return await get_tourism_validation_stats(city_name=CITY)


class TestAgreementRates:

    def test_has_classified_pois(self, stats):
        """Pipeline must have classified at least some POIs."""
        assert "error" not in stats, f"No logs found: {stats}"
        assert stats["total_classified"] > 0

    def test_category_agreement_rate(self, stats):
        """
        LLM1 and LLM2 must agree on travel_category at least
        MIN_AGREEMENT_RATE of the time.
        """
        rate = stats["category_agreement_rate"]
        assert rate >= MIN_AGREEMENT_RATE, (
            f"Agreement rate {rate:.1%} below threshold "
            f"{MIN_AGREEMENT_RATE:.1%}. "
            f"Top disagreements: {stats['top_disagreements']}"
        )

    def test_mean_cosine_distance(self, stats):
        """
        Even when categories agree, vectors should not diverge too much.
        """
        dist = stats["mean_cosine_distance"]
        assert dist is not None
        assert dist <= MAX_MEAN_COSINE_DISTANCE, (
            f"Mean cosine distance {dist:.4f} exceeds threshold "
            f"{MAX_MEAN_COSINE_DISTANCE}. "
            f"Vectors are too inconsistent between LLM1 and LLM2."
        )

    def test_failed_rate(self, stats):
        """Failed classifications must stay below MAX_FAILED_RATE."""
        rate = stats["failed_rate"]
        assert rate <= MAX_FAILED_RATE, (
            f"Failed rate {rate:.1%} exceeds threshold "
            f"{MAX_FAILED_RATE:.1%}."
        )

    def test_high_confidence_rate(self, stats):
        """Most POIs should be classified with high confidence."""
        total = stats["total_classified"]
        high = stats["confidence_distribution"].get("high", 0)
        rate = high / total if total > 0 else 0
        assert rate >= MIN_HIGH_CONFIDENCE_RATE, (
            f"High confidence rate {rate:.1%} below threshold "
            f"{MIN_HIGH_CONFIDENCE_RATE:.1%}."
        )


class TestCategoryDistribution:

    def test_minimum_category_coverage(self, distribution):
        """
        At least MIN_CATEGORY_COVERAGE distinct categories must be used.
        A good classifier shouldn't put everything in 'culture'.
        """
        valid_cats = [c for c in distribution if c and c != "failed"]
        assert len(valid_cats) >= MIN_CATEGORY_COVERAGE, (
            f"Only {len(valid_cats)} categories used: {valid_cats}. "
            f"Classifier may be over-specializing."
        )

    def test_no_dominant_category(self, distribution):
        """
        No single category should represent more than 60% of all POIs.
        Indicates over-classification bias.
        """
        total = sum(distribution.values())
        if total == 0:
            pytest.skip("No data")
        for cat, count in distribution.items():
            rate = count / total
            assert rate <= 0.60, (
                f"Category '{cat}' dominates at {rate:.1%} of all POIs. "
                f"Possible prompt bias."
            )

    def test_food_pois_classified_correctly(self, distribution):
        """
        'food' category must exist — food POIs should be recognized.
        """
        assert "food" in distribution, (
            "No POIs classified as 'food'. "
            "Check if food-related POIs are being classified correctly."
        )


class TestVectorConsistency:

    def test_cultura_vector_consistency(self, consistency):
        """
        For 'culture' POIs where both LLMs agree on category,
        their vectors should be similar (low cosine distance).
        """
        if "culture" not in consistency:
            pytest.skip("No culture POIs with agreement")

        data = consistency["culture"]
        assert data["mean_cosine_distance"] <= 0.30, (
            f"Cultura vectors too inconsistent: "
            f"mean distance={data['mean_cosine_distance']:.4f}. "
            f"Most variable dimension: {data['most_variable_dimension']}"
        )

    def test_all_categories_have_some_agreement(self, consistency):
        """Each category present should have at least 3 agreed POIs."""
        for cat, data in consistency.items():
            assert data["count"] >= 3, (
                f"Category '{cat}' has only {data['count']} agreed POIs. "
                f"Too few samples for reliable evaluation."
            )


class TestReportGeneration:

    def test_generate_html_report(self, stats, consistency, distribution, tv_stats):
        """
        Generate an HTML evaluation report using Jinja2.
        The report is saved to reports/evaluation_{city}.html.
        """
        template_dir = Path("tests/templates")
        template_dir.mkdir(parents=True, exist_ok=True)

        template_path = template_dir / "evaluation_report.html.j2"
        if not template_path.exists():
            template_path.write_text(_DEFAULT_TEMPLATE)

        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("evaluation_report.html.j2")

        html = template.render(
            city=CITY,
            stats=stats,
            consistency=consistency,
            distribution=distribution,
            tv_stats=tv_stats,
            thresholds={
                "min_agreement_rate": MIN_AGREEMENT_RATE,
                "max_mean_cosine_distance": MAX_MEAN_COSINE_DISTANCE,
                "max_failed_rate": MAX_FAILED_RATE,
                "min_category_coverage": MIN_CATEGORY_COVERAGE,
                "min_high_confidence_rate": MIN_HIGH_CONFIDENCE_RATE,
            },
        )

        report_dir = Path("reports")
        report_dir.mkdir(exist_ok=True)
        report_path = report_dir / f"evaluation_{CITY.lower()}.html"
        report_path.write_text(html)

        assert report_path.exists()
        assert len(html) > 100
        print(f"\nReport generated: {report_path}")


class TestTourismValidation:

    def test_has_tourism_logs(self, tv_stats):
        assert "error" not in tv_stats, f"No logs: {tv_stats}"
        assert tv_stats["total_validated"] > 0

    def test_touristic_rate_reasonable(self, tv_stats):
        """
        Between 40% and 85% of fetched POIs should be touristic.
        Too low = over-filtering, too high = under-filtering.
        """
        rate = tv_stats["touristic_rate"]
        assert 0.40 <= rate <= 0.85, (
            f"Touristic rate {rate:.1%} outside expected range [40%, 85%]. "
            f"Check validation prompt strictness."
        )

    def test_llm2_needed_rate_reasonable(self, tv_stats):
        """
        LLM2 should be needed for 10-40% of POIs.
        Too low = LLM1 never uncertain (overconfident).
        Too high = LLM1 always uncertain (bad prompt).
        """
        rate = tv_stats["llm2_needed_rate"]
        assert 0.10 <= rate <= 0.40, (
            f"LLM2 needed rate {rate:.1%} outside expected range [10%, 40%]."
        )

    def test_indoor_duration_reasonable(self, tv_stats):
        """Indoor visits should average 45-180 min."""
        mean = tv_stats["duration_stats"].get("indoor_mean_minutes")
        if mean is None:
            pytest.skip("No indoor duration data")
        assert 45 <= mean <= 180, (
            f"Indoor mean duration {mean} min outside expected range."
        )

    def test_outdoor_duration_reasonable(self, tv_stats):
        """Outdoor visits should average 15-75 min."""
        mean = tv_stats["duration_stats"].get("outdoor_mean_minutes")
        if mean is None:
            pytest.skip("No outdoor duration data")
        assert 15 <= mean <= 75, (
            f"Outdoor mean duration {mean} min outside expected range."
        )


# ── Default Jinja2 HTML template ───────────────────────────────────
_DEFAULT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Prompt Evaluation Report — {{ city }}</title>
<style>
  body { font-family: sans-serif; max-width: 900px; margin: 2rem auto; }
  h1, h2 { color: #2c3e50; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
  th { background: #f4f4f4; }
  .pass { color: #27ae60; font-weight: bold; }
  .fail { color: #e74c3c; font-weight: bold; }
  .metric { font-size: 2rem; font-weight: bold; margin: 0.5rem 0; }
  .card { border: 1px solid #ddd; border-radius: 8px;
          padding: 1.5rem; margin: 1rem 0; }
</style>
</head>
<body>
<h1>Prompt Evaluation Report</h1>
<p><strong>City:</strong> {{ city }} &nbsp;|&nbsp;
   <strong>Total POIs:</strong> {{ stats.total_classified }}</p>

<h2>Inter-Rater Agreement (LLM1 vs LLM2)</h2>
<div class="card">
  <p>Category agreement rate</p>
  <div class="metric
    {% if stats.category_agreement_rate >= thresholds.min_agreement_rate %}
      pass{% else %}fail{% endif %}">
    {{ "%.1f"|format(stats.category_agreement_rate * 100) }}%
  </div>
  <small>Threshold: ≥
    {{ "%.0f"|format(thresholds.min_agreement_rate * 100) }}%</small>
</div>

<div class="card">
  <p>Mean cosine distance between vectors</p>
  <div class="metric
    {% if stats.mean_cosine_distance <= thresholds.max_mean_cosine_distance %}
      pass{% else %}fail{% endif %}">
    {{ "%.4f"|format(stats.mean_cosine_distance) }}
  </div>
  <small>Threshold: ≤ {{ thresholds.max_mean_cosine_distance }}</small>
</div>

<h2>Confidence Distribution</h2>
<table>
  <tr><th>Confidence</th><th>Count</th><th>Rate</th></tr>
  {% for conf, count in stats.confidence_distribution.items() %}
  <tr>
    <td>{{ conf }}</td>
    <td>{{ count }}</td>
    <td>{{ "%.1f"|format(count / stats.total_classified * 100) }}%</td>
  </tr>
  {% endfor %}
</table>

<h2>Top Disagreements (LLM1 vs LLM2)</h2>
<table>
  <tr><th>Category pair</th><th>Count</th></tr>
  {% for pair, count in stats.top_disagreements.items() %}
  <tr><td>{{ pair }}</td><td>{{ count }}</td></tr>
  {% endfor %}
</table>

<h2>Category Distribution</h2>
<table>
  <tr><th>Category</th><th>Count</th><th>Share</th></tr>
  {% for cat, count in distribution.items()|sort(attribute='1', reverse=True) %}
  <tr>
    <td>{{ cat }}</td>
    <td>{{ count }}</td>
    <td>{{ "%.1f"|format(count / stats.total_classified * 100) }}%</td>
  </tr>
  {% endfor %}
</table>

<h2>Vector Consistency by Category</h2>
<table>
  <tr>
    <th>Category</th><th>POIs</th>
    <th>Mean distance</th><th>Most variable dim</th>
  </tr>
  {% for cat, data in consistency.items()|sort %}
  <tr>
    <td>{{ cat }}</td>
    <td>{{ data.count }}</td>
    <td>{{ "%.4f"|format(data.mean_cosine_distance) }}</td>
    <td>{{ data.most_variable_dimension }}</td>
  </tr>
  {% endfor %}
</table>

{% if tv_stats and tv_stats.total_validated %}
<h2>Tourism Validation</h2>
<div class="card">
  <p>Touristic rate (accepted / total fetched)</p>
  <div class="metric">
    {{ "%.1f"|format(tv_stats.touristic_rate * 100) }}%
  </div>
</div>
<table>
  <tr><th>Metric</th><th>Value</th></tr>
  <tr>
    <td>LLM2 needed (uncertain cases)</td>
    <td>{{ "%.1f"|format(tv_stats.llm2_needed_rate * 100) }}%</td>
  </tr>
  <tr>
    <td>Disagreements (LLM1 vs LLM2)</td>
    <td>{{ tv_stats.disagreement_count }}</td>
  </tr>
  <tr>
    <td>Mean indoor duration</td>
    <td>{{ tv_stats.duration_stats.indoor_mean_minutes }} min</td>
  </tr>
  <tr>
    <td>Mean outdoor duration</td>
    <td>{{ tv_stats.duration_stats.outdoor_mean_minutes }} min</td>
  </tr>
</table>
{% endif %}

<hr>
<small>Generated by thesis evaluation pipeline</small>
</body>
</html>
"""
