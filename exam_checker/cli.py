import logging
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from exam_checker.config import Settings
from exam_checker.pdf.extractor import PDFError
from exam_checker.pdf.pipeline import process_pdf

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


@app.command()
def main(
    pdf_path: Annotated[Path, typer.Argument(help="Local PDF path (inside Docker: /data/exam.pdf).")],
    dpi: Annotated[int | None, typer.Option(min=72, max=300, help="Render DPI; overrides EXAM_CHECKER_RENDER_DPI.")] = None,
    verbose: Annotated[bool, typer.Option(help="Show per-page processing logs.")] = False,
) -> None:
    """Extract PDF text and render temporary page images locally."""
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(message)s", force=True)
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
        typer.echo("Temporary images cleaned up. Local preprocessing complete.")
    except ValidationError:
        typer.echo("Error: EXAM_CHECKER_RENDER_DPI must be an integer from 72 to 300.", err=True)
        raise typer.Exit(1)
    except (PDFError, OSError, RuntimeError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
