import logging
import os
import shutil
from pathlib import Path
from tempfile import mkdtemp
from typing import Annotated

import typer
from pydantic import BaseModel, ValidationError

from exam_checker.tracing import traced, span, record
from exam_checker.config import Settings
from exam_checker.cloud.modal_client import CloudError, check_gpu, review_page
from exam_checker.cloud.review_schema import DEFAULT_MODEL, DocumentReviewResult
from exam_checker.pdf.extractor import PDFError
from exam_checker.pdf.pipeline import PageData, process_pdf

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


def _destination(pdf_path: Path, output: Path | None, modal_check: bool, review: bool,
                 model: str | None, text_only: bool) -> Path:
    """Validate CLI options before opening the PDF or calling Modal."""
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
    return destination


def _show_pages(pages: list[PageData], dpi: int) -> None:
    typer.echo(f"Pages: {len(pages)}")
    for page in pages:
        note = " (little/no usable text; visual review needed)" if page.needs_visual_review else ""
        typer.echo(f"Page {page.page_number}: {len(page.text)} text characters{note}")
    typer.echo(f"\nText characters: {sum(len(page.text) for page in pages)}")
    typer.echo(f"Rendered PNGs: {len(pages)} at {dpi} DPI")
    typer.echo(f"Pages needing visual review: {sum(page.needs_visual_review for page in pages)}")


def _keep_pages(pages: list[PageData], pdf_path: Path) -> Path:
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    files_dir = Path(mkdtemp(prefix=f"{pdf_path.stem}.pages-", dir=output_dir))
    for page in pages:
        name = f"page-{page.page_number}"
        (files_dir / f"{name}.txt").write_text(page.text, encoding="utf-8")
        shutil.copyfile(page.image_path, files_dir / f"{name}.png")
    return files_dir


def _save_report(result: BaseModel, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with span("report.write") as run:
        destination.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        record(run, metadata={"filename": destination.name})


def _run_gpu_check(page: PageData, destination: Path) -> None:
    typer.echo("Checking Modal GPU with the first page...")
    result = check_gpu(page)
    _save_report(result, destination)
    typer.echo(f"GPU check passed: {result.gpu_name}; CUDA result: {result.computation_result}")
    typer.echo(f"Connection check JSON (not an exam review): {destination}")


def _run_review(pages: list[PageData], destination: Path, model: str | None, text_only: bool) -> None:
    model_id = model or os.getenv("EXAM_CHECKER_MODEL", DEFAULT_MODEL)
    typer.echo(f"Reviewing {len(pages)} pages on Modal: {model_id} (initial download may take several minutes)...")
    results = []
    for page in pages:
        typer.echo(f"Reviewing page {page.page_number}/{len(pages)}...")
        results.append(review_page(page, model_id, text_only=text_only))
    result = DocumentReviewResult(page_count=len(pages), pages=results)
    _save_report(result, destination)
    issue_count = sum(len(page.review.issues) for page in results)
    typer.echo(f"Review complete: {issue_count} suspected issues across {len(pages)} pages (not independently verified).")
    typer.echo(f"Review JSON: {destination}")


# CLI의 진입점: 옵션 검사 → PDF 전처리 → 선택적 클라우드 호출 → 결과 저장을 조율한다.
@app.command()
@traced("exam_checker.run", root=True)
def main(
    pdf_path: Annotated[Path, typer.Argument(help="Local PDF path (for example: data/exam.pdf).")],
    dpi: Annotated[int | None, typer.Option(min=72, max=300, help="Render DPI; overrides EXAM_CHECKER_RENDER_DPI.")] = None,
    verbose: Annotated[bool, typer.Option(help="Show per-page processing logs.")] = False,
    modal_check: Annotated[bool, typer.Option(help="Send the first page to Modal for a CUDA connection check (no AI review).")] = False,
    review: Annotated[bool, typer.Option(help="Review every page with Qwen on Modal (unverified AI findings).")] = False,
    model: Annotated[str | None, typer.Option(help="Qwen3-VL checkpoint override; requires --review.")] = None,
    text_only: Annotated[bool, typer.Option(help="Send only native text for --review.")] = False,
    output: Annotated[Path | None, typer.Option(help="JSON destination for --modal-check or --review.")] = None,
    keep_files: Annotated[bool, typer.Option(help="Keep extracted text and page PNGs under output/.")] = False,
) -> None:
    """Extract PDF text and render temporary page images locally."""
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(message)s", force=True)
    destination = _destination(pdf_path, output, modal_check, review, model, text_only)
    try:
        settings = Settings.from_env(dpi)
        typer.echo(f"Exam Checker\n============\nPDF: {pdf_path.name}")
        # 이 블록이 끝날 때 PNG가 삭제되므로 전송과 저장도 블록 안에서 마친다.
        with process_pdf(pdf_path, settings) as pages:
            _show_pages(pages, settings.render_dpi)
            if keep_files:
                typer.echo(f"Saved page text and images: {_keep_pages(pages, pdf_path)}")
            # GPU 연결 확인은 첫 페이지로 수행하고, AI 검토는 모든 페이지를 각각 전송한다.
            if modal_check:
                _run_gpu_check(pages[0], destination)
            if review:
                _run_review(pages, destination, model, text_only)
        typer.echo("Temporary images cleaned up. Local preprocessing complete.")
    # 전처리·원격 호출에서 예외가 발생해도 with의 정리를 거친 뒤 여기서 안내한다.
    except ValidationError:
        typer.echo("Error: EXAM_CHECKER_RENDER_DPI must be an integer from 72 to 300.", err=True)
        raise typer.Exit(1)
    except (CloudError, PDFError, OSError, RuntimeError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
