from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

KOREAN_FONT_NAME = "HYSMyeongJo-Medium"


def register_korean_font():
    if KOREAN_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(KOREAN_FONT_NAME))


def render_text_pdf(path, title, body):
    register_korean_font()

    pdf = canvas.Canvas(path, pagesize=A4)
    _, height = A4
    y = height - 72
    pdf.setTitle(title)
    pdf.setFont(KOREAN_FONT_NAME, 14)
    pdf.drawString(72, y, title)
    y -= 32
    pdf.setFont(KOREAN_FONT_NAME, 10)
    for raw_line in body.splitlines():
        line = raw_line[:110]
        if y < 72:
            pdf.showPage()
            pdf.setFont(KOREAN_FONT_NAME, 10)
            y = height - 72
        pdf.drawString(72, y, line)
        y -= 16
    pdf.save()
