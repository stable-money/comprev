"""Command-line interface.

  comprev run <video> [--product mutual_funds] [--stub] [--skip-visual] [--skip-audio]
  comprev eval <folder>
  comprev checks            # list the loaded check library
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import (
    DEFAULT_CHECKS_PATH,
    DEFAULT_ENGINE_PATH,
    checks_path_for,
    load_checks,
    load_engine_config,
    resolve_product,
)
from .engine import run_video
from .report import write_report
from .schemas import Product

_PRODUCTS = [p.value for p in Product]

app = typer.Typer(add_completion=False, help="MF Video Compliance Engine (Phase 1)")
console = Console()

_STATUS_STYLE = {"pass": "green", "fail": "bold red", "uncertain": "yellow", "needs_review": "yellow"}


@app.command()
def run(
    video: Path = typer.Argument(..., exists=False, help="Path to the marketing video."),
    product: str = typer.Option("mutual_funds", help="Product to review against: mutual_funds | bonds."),
    out: Path = typer.Option(Path("out"), help="Output root directory."),
    checks_path: Optional[Path] = typer.Option(None, "--checks", help="Check library YAML (default: the product's library from engine.yaml)."),
    engine_path: Path = typer.Option(DEFAULT_ENGINE_PATH, "--engine-config", help="Engine config YAML."),
    stub: bool = typer.Option(False, "--stub", help="Scaffold mode: no ML deps / no API; all checks uncertain."),
    fast: bool = typer.Option(False, "--fast", help="Faster iteration: downscale frames + mobile OCR detector + Whisper 'medium'. Trades some accuracy for speed."),
    skip_visual: bool = typer.Option(False, help="Skip the visual pipeline."),
    skip_audio: bool = typer.Option(False, help="Skip the audio pipeline."),
):
    """Review a single video and emit out/<video_id>.json and .md."""
    if product not in _PRODUCTS:
        raise typer.BadParameter(f"Unknown product {product!r}. Choose from: {', '.join(_PRODUCTS)}.")
    if not stub and not video.exists():
        raise typer.BadParameter(f"Video not found: {video}")

    cfg = load_engine_config(engine_path)
    pc = resolve_product(cfg, product)
    checks = load_checks(checks_path or checks_path_for(pc))

    if fast:
        # Speed overrides for iteration — NOT the trustworthy-verdict config.
        cfg.visual.ocr_detection_model = "PP-OCRv5_mobile_det"
        cfg.visual.ocr_max_width = 720
        cfg.audio.model = "medium"
        console.print("[yellow]--fast: mobile OCR detector + 720px frames + Whisper 'medium' (lower fidelity).[/yellow]")

    # Cap OCR native threads before the pipelines import the native libs, so a
    # concurrent OCR pool + Whisper stay within the core budget (see engine.yaml).
    import os
    os.environ.setdefault("OMP_NUM_THREADS", str(cfg.visual.ocr_cpu_threads))
    os.environ.setdefault("MKL_NUM_THREADS", str(cfg.visual.ocr_cpu_threads))

    console.print(f"[bold]Reviewing[/bold] {video}  ({len(checks)} checks, model={cfg.model})")
    if stub:
        console.print("[yellow]Running in --stub mode (no pipelines / no API).[/yellow]")

    report = run_video(
        video, checks, cfg, product=product, out_root=out,
        skip_visual=skip_visual, skip_audio=skip_audio, stub=stub,
    )
    json_path, md_path = write_report(report, out)

    _print_report(report)
    console.print(f"\nWrote [cyan]{json_path}[/cyan] and [cyan]{md_path}[/cyan]")


@app.command(name="eval")
def eval_cmd(
    folder: Path = typer.Argument(..., help="Folder with videos + labels.jsonl."),
    labels: Optional[Path] = typer.Option(None, help="Labels file (default: <folder>/labels.jsonl)."),
    out: Path = typer.Option(Path("out"), help="Output root for per-video artifacts."),
    report_path: Path = typer.Option(Path("eval/report.md"), help="Where to write the eval report."),
    checks_path: Path = typer.Option(DEFAULT_CHECKS_PATH, "--checks", help="Check library YAML."),
    engine_path: Path = typer.Option(DEFAULT_ENGINE_PATH, "--engine-config", help="Engine config YAML."),
    stub: bool = typer.Option(False, "--stub", help="Stub mode (for harness smoke-testing)."),
):
    """Run the engine over a labeled folder and write eval/report.md."""
    from .eval_harness import run_eval

    summary = run_eval(
        folder=folder,
        labels_path=labels,
        out_root=out,
        report_path=report_path,
        checks_path=checks_path,
        engine_path=engine_path,
        stub=stub,
    )
    console.print(summary)
    console.print(f"\nWrote eval report to [cyan]{report_path}[/cyan]")


@app.command()
def checks(
    product: str = typer.Option("mutual_funds", help="Product whose library to list: mutual_funds | bonds."),
    checks_path: Optional[Path] = typer.Option(None, "--checks", help="Check library YAML (default: the product's library)."),
    engine_path: Path = typer.Option(DEFAULT_ENGINE_PATH, "--engine-config", help="Engine config YAML."),
):
    """List the loaded compliance checks."""
    if product not in _PRODUCTS:
        raise typer.BadParameter(f"Unknown product {product!r}. Choose from: {', '.join(_PRODUCTS)}.")
    pc = resolve_product(load_engine_config(engine_path), product)
    loaded = load_checks(checks_path or checks_path_for(pc))
    table = Table(title=f"{pc.label} check library ({len(loaded)} checks)")
    for col in ("id", "surface", "severity", "applies_when", "method"):
        table.add_column(col)
    for c in loaded:
        table.add_row(c.id, c.surface.value, c.severity.value, c.applies_when, c.method)
    console.print(table)


def _print_report(report) -> None:
    table = Table(title=f"{report.video_id} — overall: {report.overall_status.value.upper()}")
    for col in ("check", "status", "severity", "conf", "low-conf"):
        table.add_column(col)
    for c in report.checks:
        na = " (n/a)" if c.not_applicable else ""
        style = _STATUS_STYLE.get(c.status.value, "")
        table.add_row(
            c.check_id,
            f"[{style}]{c.status.value}{na}[/{style}]" if style else f"{c.status.value}{na}",
            c.severity.value,
            f"{c.confidence:.2f}",
            "yes" if c.low_confidence_inputs else "no",
        )
    console.print(table)
    if report.review_reasons:
        console.print("[yellow]Review reasons:[/yellow] " + "; ".join(report.review_reasons))


if __name__ == "__main__":
    app()
