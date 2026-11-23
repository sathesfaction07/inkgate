import logging
from pathlib import Path

import click

from . import __version__
from .config import Settings
from .core.guidelines import Guidelines
from .core.pipeline import Pipeline, summarise
from .io import load_cases, write_csv, write_excel, write_json
from .models import Case, Decision, Status
from .providers import PROVIDERS, all_providers
from .templates.registry import TemplateRegistry


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("botocore", "boto3", "urllib3", "google"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _settings(**overrides) -> Settings:
    return Settings(**{k: v for k, v in overrides.items() if v is not None})


STATUS_COLOUR = {
    Status.READY: "green",
    Status.NEEDS_REVIEW: "yellow",
    Status.FAILED: "red",
}


@click.group()
@click.version_option(__version__)
def main() -> None:
    """Generate merchant-facing decision blurbs from versioned templates, then score them."""


@main.command()
@click.option("--case-id", required=True)
@click.option("--decision", type=click.Choice([d.value for d in Decision]), required=True)
@click.option("--merchant", "merchant_name", default="Merchant")
@click.option("--product-id", default="")
@click.option("--category", default="")
@click.option("--reason", default="")
@click.option("--provider", type=click.Choice(PROVIDERS), default=None)
@click.option("--templates", "templates_path", type=click.Path(path_type=Path), default=None)
@click.option("--guidelines", "guidelines_path", type=click.Path(path_type=Path), default=None)
@click.option("--quality-threshold", type=float, default=None)
@click.option("--show-criteria", is_flag=True, help="Print the per-criterion score breakdown.")
def generate(
    case_id: str,
    decision: str,
    merchant_name: str,
    product_id: str,
    category: str,
    reason: str,
    provider: str | None,
    templates_path: Path | None,
    guidelines_path: Path | None,
    quality_threshold: float | None,
    show_criteria: bool,
) -> None:
    """Generate one blurb and print it with its quality verdict."""
    cfg = _settings(
        provider=provider,
        templates_path=templates_path,
        guidelines_path=guidelines_path,
        quality_threshold=quality_threshold,
    )
    _configure_logging(cfg.log_level)

    case = Case(
        case_id=case_id,
        merchant_name=merchant_name,
        product_id=product_id,
        category=category,
        reason=reason,
        decision=Decision(decision),
    )

    pipeline = Pipeline(cfg)
    blurb = pipeline.generate(case)

    click.secho(f"status          {blurb.status.value}", fg=STATUS_COLOUR[blurb.status], bold=True)
    click.echo(f"template        {blurb.template_id} (v{blurb.template_version})")
    click.echo(
        f"classification  {blurb.classification_confidence:.0f} "
        f"via {blurb.classification_source}"
    )
    click.echo(f"quality         {blurb.quality_score:.0f} via {blurb.scored_by}")

    if blurb.error:
        click.secho(f"error           {blurb.error}", fg="red")

    for issue in blurb.issues:
        click.secho(f"issue           {issue}", fg="yellow")

    if show_criteria:
        report = pipeline.provider.score(
            blurb.text, pipeline.registry.get(blurb.template_id), pipeline.guidelines
        ) or pipeline.fallback.score(
            blurb.text, pipeline.registry.get(blurb.template_id), pipeline.guidelines
        )
        click.echo("")
        for criterion in report.criteria:
            mark = "pass" if criterion.passed else "FAIL"
            click.echo(f"  [{mark}] {criterion.criterion} (weight {criterion.weight:g})")
            if criterion.detail and not criterion.passed:
                click.echo(f"         {criterion.detail}")

    if blurb.text:
        click.echo("")
        click.echo("-" * 72)
        click.echo(blurb.text)
        click.echo("-" * 72)


@main.command()
@click.argument("input_path", type=click.Path(path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), default=Path("output"))
@click.option("--format", "fmt", type=click.Choice(["csv", "json", "excel"]), default=None)
@click.option("--provider", type=click.Choice(PROVIDERS), default=None)
@click.option("--templates", "templates_path", type=click.Path(path_type=Path), default=None)
@click.option("--guidelines", "guidelines_path", type=click.Path(path_type=Path), default=None)
@click.option("--quality-threshold", type=float, default=None)
@click.option("--ready-only", is_flag=True, help="Write only blurbs that passed the gate.")
def batch(
    input_path: Path,
    output: Path,
    fmt: str | None,
    provider: str | None,
    templates_path: Path | None,
    guidelines_path: Path | None,
    quality_threshold: float | None,
    ready_only: bool,
) -> None:
    """Generate blurbs for every case in INPUT_PATH (CSV or JSON)."""
    cfg = _settings(
        provider=provider,
        templates_path=templates_path,
        guidelines_path=guidelines_path,
        quality_threshold=quality_threshold,
        output_format=fmt,
    )
    _configure_logging(cfg.log_level)

    cases = load_cases(input_path)
    blurbs = Pipeline(cfg).generate_batch(cases)
    summary = summarise(blurbs)

    emitted = [b for b in blurbs if b.status is Status.READY] if ready_only else blurbs

    if cfg.output_format == "csv":
        written = [write_csv(emitted, output / "blurbs.csv")]
    elif cfg.output_format == "excel":
        written = [write_excel(emitted, output / "blurbs.xlsx")]
    else:
        written = [write_json(emitted, summary, output / "blurbs.json")]

    written.append(write_json(blurbs, summary, output / "full_report.json"))

    click.echo("")
    click.echo(f"total         {summary['total']}")
    click.secho(f"ready         {summary['ready']}", fg="green")
    click.secho(f"needs review  {summary['needs_review']}", fg="yellow")
    click.secho(f"failed        {summary['failed']}", fg="red")
    click.echo(f"mean quality  {summary['mean_quality']}")
    click.echo(f"templates     {', '.join(summary['templates_used']) or 'none'}")
    for path in written:
        click.echo(f"wrote         {path}")


@main.command()
@click.option("--templates", "templates_path", type=click.Path(path_type=Path), default=None)
@click.option("--validate", is_flag=True, help="Check the template file for problems and exit.")
def templates(templates_path: Path | None, validate: bool) -> None:
    """List templates with their versions, or validate the template file."""
    cfg = _settings(templates_path=templates_path)
    registry = TemplateRegistry.load(cfg.templates_path)

    if validate:
        problems = registry.validate()
        if not problems:
            click.secho(
                f"{len(registry.all())} templates, set version {registry.version}: no problems",
                fg="green",
            )
            return
        for problem in problems:
            click.secho(f"  {problem}", fg="red")
        raise SystemExit(1)

    click.echo(f"set version {registry.version}, {len(registry.all())} templates")
    click.echo("")
    for template in registry.all():
        applies = template.applies_to
        conditions = [f"decision={applies.decision.value}"]
        if applies.reasons:
            conditions.append(f"reasons={','.join(applies.reasons)}")
        if applies.categories:
            conditions.append(f"categories={','.join(applies.categories)}")
        click.echo(f"  {template.id}  (v{template.version})")
        click.echo(f"    applies when   {'; '.join(conditions)}")
        click.echo(f"    variables      {', '.join(template.required_variables) or 'none'}")
        click.echo(
            f"    length         {template.length.min_chars}-{template.length.max_chars} chars"
        )


@main.command()
@click.option("--guidelines", "guidelines_path", type=click.Path(path_type=Path), default=None)
def providers(guidelines_path: Path | None) -> None:
    """Show which providers are usable in this environment."""
    cfg = _settings(guidelines_path=guidelines_path)
    for provider in all_providers(cfg):
        available = provider.is_available()
        click.secho(
            f"{provider.name:<10} {'ready' if available else 'unavailable'}",
            fg="green" if available else "yellow",
        )
    guidelines = Guidelines.load(cfg.guidelines_path)
    click.echo("")
    click.echo(
        f"guidelines v{guidelines.version}: "
        f"{len(guidelines.banned_phrases)} banned phrases, "
        f"{len(guidelines.required_elements)} required elements"
    )
