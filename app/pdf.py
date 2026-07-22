import faulthandler
import os
import signal
import tempfile
import traceback
from multiprocessing import Process, Queue
from queue import Empty

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

KOREAN_FONT_NAME = "HYSMyeongJo-Medium"
PDF_RENDER_TIMEOUT_SECONDS = 15


def register_korean_font():
    if KOREAN_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(KOREAN_FONT_NAME))


class PdfRenderError(RuntimeError):
    pass


def _build_text_pdf(path, title, body):
    register_korean_font()

    styles = getSampleStyleSheet()
    title_style = styles["Title"].clone("ClinicalDocumentTitle")
    title_style.fontName = KOREAN_FONT_NAME
    title_style.fontSize = 14
    title_style.leading = 18

    body_style = styles["BodyText"].clone("ClinicalDocumentBody")
    body_style.fontName = KOREAN_FONT_NAME
    body_style.fontSize = 10
    body_style.leading = 16

    story = [Paragraph(title, title_style), Spacer(1, 20)]
    for block in body.split("\n\n"):
        lines = block.splitlines()
        if not any(line.strip() for line in lines):
            continue
        story.append(Paragraph("<br/>".join(lines), body_style))
        story.append(Spacer(1, 10))

    document = SimpleDocTemplate(
        path,
        pagesize=A4,
        title=title,
        leftMargin=72,
        rightMargin=72,
        topMargin=72,
        bottomMargin=72,
    )
    document.build(story)


def _render_text_pdf_worker(path, title, body, result_queue, crash_log_path):
    try:
        with open(crash_log_path, "w") as crash_log:
            faulthandler.enable(file=crash_log, all_threads=True)
            _build_text_pdf(path, title, body)
    except Exception as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"))
    else:
        result_queue.put(("ok", ""))


def render_text_pdf(path, title, body):
    result_queue = Queue()
    crash_log = tempfile.NamedTemporaryFile(prefix="pdf-render-", suffix=".log", delete=False)
    crash_log_path = crash_log.name
    crash_log.close()

    process = Process(
        target=_render_text_pdf_worker,
        args=(path, title, body, result_queue, crash_log_path),
    )
    process.start()
    process.join(PDF_RENDER_TIMEOUT_SECONDS)

    try:
        if process.is_alive():
            process.terminate()
            process.join()
            raise PdfRenderError("PDF rendering timed out")

        if process.exitcode != 0:
            reason = f"PDF renderer exited with code {process.exitcode}"
            if process.exitcode and process.exitcode < 0:
                try:
                    reason = f"{reason} ({signal.Signals(-process.exitcode).name})"
                except ValueError:
                    pass
            with open(crash_log_path) as crash_log_file:
                crash_details = crash_log_file.read().strip()
            if crash_details:
                reason = f"{reason}\n{crash_details}"
            raise PdfRenderError(reason)

        try:
            status, message = result_queue.get_nowait()
        except Empty as exc:
            raise PdfRenderError("PDF renderer exited without a result") from exc

        if status != "ok":
            raise PdfRenderError(message)
    finally:
        try:
            os.unlink(crash_log_path)
        except OSError:
            pass
