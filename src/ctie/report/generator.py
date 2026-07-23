"""HTML report generator."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import structlog
from jinja2 import Template

from ctie.models.result import AppResearchResult
from ctie.report.insights import compute_distribution, generate_insights

logger = structlog.get_logger()

DEFAULT_TEMPLATE = Path(__file__).with_name("template.html")


class ReportGenerator:
    """Generate a self-contained interactive HTML report."""

    def __init__(self, template_path: Path | None = None) -> None:
        self.template_path = template_path or DEFAULT_TEMPLATE

    def generate(
        self,
        results: list[AppResearchResult],
        *,
        run_id: str = "",
        output_path: Path = Path("outputs/report.html"),
    ) -> Path:
        """Render the report to ``output_path``.

        Args:
            results: Research results for all apps.
            run_id: Optional run identifier.
            output_path: Destination HTML file path.

        Returns:
            The rendered file path.
        """
        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        insights = generate_insights(results)
        distribution = compute_distribution(results)

        context = {
            "run_id": run_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "total_apps": len(results),
            "completed_apps": sum(1 for r in results if not r.error),
            "failed_apps": sum(1 for r in results if r.error),
            "insights": insights,
            "distribution": distribution,
            "results_json": json.dumps(
                [r.model_dump(mode="json") for r in results],
                ensure_ascii=False,
                default=str,
            ),
            "results": results,
        }

        template_text = self.template_path.read_text(encoding="utf-8")
        html = Template(template_text).render(context)
        output_path.write_text(html, encoding="utf-8")
        logger.info("report_generated", output=str(output_path), apps=len(results))
        return output_path
