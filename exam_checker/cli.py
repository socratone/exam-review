import logging
import os
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from exam_checker.config import Settings
from exam_checker.cloud.modal_client import CloudError, check_gpu, review_page
from exam_checker.cloud.review_schema import DEFAULT_MODEL
from exam_checker.pdf.extractor import PDFError
from exam_checker.pdf.pipeline import process_pdf

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


@app.command()
def main(
    pdf_path: Annotated[Path, typer.Argument(help="Local PDF path (inside Docker: /data/exam.pdf).")],
    dpi: Annotated[int | None, typer.Option(min=72, max=300, help="Render DPI; overrides EXAM_CHECKER_RENDER_DPI.")] = None,
    verbose: Annotated[bool, typer.Option(help="Show per-page processing logs.")] = False,
    modal_check: Annotated[bool, typer.Option(help="Send the first page to Modal for a CUDA connection check (no AI review).")] = False,
    review: Annotated[bool, typer.Option(help="Review the first page with Qwen on Modal (unverified AI findings).")] = False,
    model: Annotated[str | None, typer.Option(help="Qwen3-VL checkpoint override; requires --review.")] = None,
    text_only: Annotated[bool, typer.Option(help="Send only native text for --review.")] = False,
    output: Annotated[Path | None, typer.Option(help="JSON destination for --modal-check or --review.")] = None,
) -> None:
    """Extract PDF text and render temporary page images locally."""
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(message)s", force=True)
    if modal_check and review:
        raise typer.BadParameter("Choose either --modal-check or --review")
    if (model is not None or text_only) and not review:
        raise typer.BadParameter("--model and --text-only require --review")
    if output is not None and not (modal_check or review):
        raise typer.BadParameter("--output requires --modal-check or --review")
    suffix = "page-review" if review else "gpu-check"
    destination = output or Path("output") / f"{pdf_path.stem}.{suffix}.json"
    if (modal_check or review) and destination.resolve() == pdf_path.resolve():
        raise typer.BadParameter("Output must not overwrite the input PDF")
    try:
        settings = Settings.from_env(dpi)
        typer.echo(f"Exam Checker\n============\nPDF: {pdf_path.name}")
        with process_pdf(pdf_path, settings) as pages:
            typer.echo(f"Pages: {len(pages)}")
            for page in pages:
                note = " (little/no usable text; visual review needed)" if page.needs_visual_review else ""
                typer.echo(f"Page {page.page_number}: {len(page.text)} text characters{note}")
            typer.echo(f"\nText characters: {sum(len(page.text) for page in pages)}")
            typer.echo(f"Rendered PNGs: {len(pages)} at {settings.render_dpi} DPI")
            typer.echo(f"Pages needing visual review: {sum(page.needs_visual_review for page in pages)}")
            if modal_check:
                typer.echo("Checking Modal GPU with the first page...")
                result = check_gpu(pages[0])
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
                typer.echo(f"GPU check passed: {result.gpu_name}; CUDA result: {result.computation_result}")
                typer.echo(f"Connection check JSON (not an exam review): {destination}")
            if review:
                model_id = model or os.getenv("EXAM_CHECKER_MODEL", DEFAULT_MODEL)
                typer.echo(f"Reviewing first page on Modal: {model_id} (initial download may take several minutes)...")
                result = review_page(pages[0], model_id, text_only=text_only)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
                typer.echo(f"First-page review complete: {len(result.review.issues)} suspected issues (not independently verified).")
                typer.echo(f"Review JSON: {destination}")
        typer.echo("Temporary images cleaned up. Local preprocessing complete.")
    except ValidationError:
        typer.echo("Error: EXAM_CHECKER_RENDER_DPI must be an integer from 72 to 300.", err=True)
        raise typer.Exit(1)
    except (CloudError, PDFError, OSError, RuntimeError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
