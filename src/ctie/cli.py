"""Typer CLI entrypoint for CTIE."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog
import typer
from rich.console import Console
from rich.table import Table

from ctie.config import Settings, get_settings
from ctie.graph.runner import ResearchPipeline
from ctie.llm.factory import create_llm_client
from ctie.models.app import AppInput
from ctie.report.generator import ReportGenerator
from ctie.retrieval.fetcher import Fetcher
from ctie.search.factory import create_search_provider
from ctie.storage.sqlite import SQLiteStore

app = typer.Typer(help="Composio Toolkit Intelligence Engine")
console = Console()
logger = structlog.get_logger()


def _load_apps(path: Path) -> list[AppInput]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("apps", data) if isinstance(data, dict) else data
    return [AppInput.model_validate(item) for item in items]


def _get_settings() -> Settings:
    try:
        return get_settings()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Failed to load settings: {exc}[/red]")
        raise typer.Exit(code=1) from exc


def _validate_startup(settings: Settings) -> None:
    """Validate required credentials and print errors."""
    validation = settings.validate_required_credentials()

    if validation["errors"]:
        console.print("[red]❌ Configuration errors:[/red]")
        for error in validation["errors"]:
            console.print(f"  [red]• {error}[/red]")
        console.print("\n[yellow]Please set the required environment variables in your .env file.[/yellow]")
        raise typer.Exit(code=1)

    console.print("[green]✅ Configuration OK[/green]\n")


@app.command()
def healthcheck() -> None:
    """Check connectivity and configuration for all services."""
    settings = _get_settings()
    console.print("[bold]CTIE Health Check[/bold]\n")
    
    # Check configuration
    validation = settings.validate_required_credentials()
    console.print(f"[bold]Configuration:[/bold] {'✅ OK' if not validation['errors'] else '❌ Errors'}")
    if validation["errors"]:
        for error in validation["errors"]:
            console.print(f"  [red]• {error}[/red]")
    if validation["warnings"]:
        for warning in validation["warnings"]:
            console.print(f"  [yellow]• {warning}[/yellow]")
    console.print()
    
    # Check LLM connectivity
    async def check_llm() -> None:
        try:
            llm = create_llm_client(settings,enable_fallback=False)
            result = await llm.healthcheck()
            status_emoji = "✅" if result["status"] == "ok" else "❌"
            console.print(f"[bold]LLM Provider ({llm.provider_name}):[/bold] {status_emoji} {result['status'].upper()}")
            if result.get("error"):
                console.print(f"  [red]Error: {result['error']}[/red]")
        except Exception as exc:
            console.print(f"[bold]LLM Provider:[/bold] ❌ FAILED")
            console.print(f"  [red]Error: {exc}[/red]")
    
    asyncio.run(check_llm())
    console.print()
    
    # Check search provider
    try:
        search_provider = create_search_provider(settings)
        console.print(f"[bold]Search Provider:[/bold] ✅ {search_provider.provider_name}")
    except Exception as exc:
        console.print(f"[bold]Search Provider:[/bold] ❌ FAILED")
        console.print(f"  [red]Error: {exc}[/red]")
    console.print()
    
    # Check database
    console.print(f"[bold]Database:[/bold] {settings.ctie_db_path}")
    console.print(f"  Exists: {'✅ Yes' if settings.ctie_db_path.exists() else '⚠️ Will be created on first run'}")
    console.print()
    
    console.print("[green]✅ Health check complete![/green]")


@app.command()
def run(
    resume: bool = typer.Option(False, help="Resume from last run state in SQLite."),
    apps: Path = typer.Option(Path("data/apps.json"), help="Path to apps JSON file."),  # noqa: B008
    output_dir: Path = typer.Option(Path("outputs"), help="Directory for outputs."),  # noqa: B008
) -> None:
    """Run the full research pipeline."""
    settings = _get_settings()
    _validate_startup(settings)
    
    try:
        llm = create_llm_client(settings)
    except Exception as exc:
        console.print(f"[red]Failed to create LLM client: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    app_list = _load_apps(apps)
    store = SQLiteStore(settings.ctie_db_path)
    search_provider = create_search_provider(settings)
    fetcher = Fetcher(settings, store=store)
    pipeline = ResearchPipeline(settings, llm, search_provider, fetcher, store)

    try:
        results = asyncio.run(pipeline.run(app_list, resume=resume))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Pipeline failed: {exc}[/red]")
        logger.exception("pipeline_run_failed")
        raise typer.Exit(code=1) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    ReportGenerator().generate(results, run_id=pipeline.run_id, output_path=output_dir / "report.html")
    (output_dir / "results.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    completed = sum(1 for r in results if not r.error)
    console.print(f"[green]Pipeline finished: {completed}/{len(results)} apps completed.[/green]")
    console.print(f"Report: [blue]{output_dir / 'report.html'}[/blue]")


@app.command()
def report(
    db_path: Path = typer.Option(None, help="Path to SQLite database."),  # noqa: B008
    output_dir: Path = typer.Option(Path("outputs"), help="Directory for outputs."),  # noqa: B008
) -> None:
    """Regenerate reports from existing results in SQLite."""
    settings = _get_settings()
    store = SQLiteStore(db_path or settings.ctie_db_path)
    apps = asyncio.run(store.list_apps())
    results = [a.result for a in apps if a.result is not None]
    if not results:
        console.print("[yellow]No completed results found in database.[/yellow]")
        raise typer.Exit(code=1)

    output_dir.mkdir(parents=True, exist_ok=True)
    ReportGenerator().generate(results, run_id="report", output_path=output_dir / "report.html")
    (output_dir / "results.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    console.print(f"[green]Report regenerated: {output_dir / 'report.html'}[/green]")


@app.command()
def search(query: str) -> None:
    """Debug: search the web for a query."""
    settings = _get_settings()
    provider = create_search_provider(settings)

    async def _search() -> None:
        results = await provider.search(query, max_results=5)
        table = Table(title=f"Search results for: {query}")
        table.add_column("#", justify="right")
        table.add_column("Title")
        table.add_column("URL")
        table.add_column("Source")
        for idx, r in enumerate(results, start=1):
            table.add_row(str(idx), r.title or "", str(r.url), r.source_type.value)
        console.print(table)

    try:
        asyncio.run(_search())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Search failed: {exc}[/red]")
        logger.exception("search_command_failed")
        raise typer.Exit(code=1) from exc


@app.command()
def fetch(url: str) -> None:
    """Debug: fetch and parse a URL."""
    settings = _get_settings()
    store = SQLiteStore(settings.ctie_db_path)
    fetcher = Fetcher(settings, store=store)

    async def _fetch() -> None:
        await store.initialize()
        doc = await fetcher.fetch(url, app_id=0)
        console.print(f"Title: {doc.title}")
        console.print(f"Method: {doc.fetch_method}")
        console.print(f"Length: {doc.content_length} bytes")
        console.print("--- Snippet ---")
        console.print(doc.cleaned_text[:1000])

    try:
        asyncio.run(_fetch())
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Fetch failed: {exc}[/red]")
        logger.exception("fetch_command_failed")
        raise typer.Exit(code=1) from exc


@app.command()
def export_db(target: Path) -> None:
    """Export the SQLite database to ``target``."""
    settings = _get_settings()
    store = SQLiteStore(settings.ctie_db_path)
    asyncio.run(store.export_to(target))
    console.print(f"[green]Database exported to {target}[/green]")


@app.command()
def import_db(source: Path) -> None:
    """Replace the SQLite database with ``source``."""
    settings = _get_settings()
    store = SQLiteStore(settings.ctie_db_path)
    asyncio.run(store.import_from(source))
    console.print(f"[green]Database imported from {source}[/green]")


if __name__ == "__main__":
    app()
