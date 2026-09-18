"""Gera um PDF formatado a partir do texto de uma transcrição."""

from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

MARGEM = 2.5 * cm


def _rodape(canvas, doc):
    """Escreve a numeração de página no rodapé."""
    canvas.saveState()
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(colors.grey)
    canvas.drawCentredString(A4[0] / 2.0, MARGEM / 2.0, "Página {0}".format(doc.page))
    canvas.restoreState()


def _dividir_paragrafos(texto):
    """Separa o texto em parágrafos, por linha em branco ou, na falta dela, por linha."""
    paragrafos = [p.strip() for p in texto.split('\n\n') if p.strip()]
    if len(paragrafos) <= 1:
        paragrafos = [p.strip() for p in texto.split('\n') if p.strip()]
    return paragrafos or [texto.strip()]


def _estilos():
    base = getSampleStyleSheet()
    corpo = ParagraphStyle(
        'CorpoTranscricao',
        parent=base['Normal'],
        fontName='Helvetica',
        fontSize=11,
        leading=16,
        alignment=TA_JUSTIFY,
        spaceAfter=10,
    )
    titulo = ParagraphStyle(
        'TituloTranscricao',
        parent=base['Title'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        spaceAfter=6,
    )
    meta = ParagraphStyle(
        'MetaTranscricao',
        parent=base['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.grey,
    )
    return titulo, meta, corpo


def _linhas_cabecalho(nome_origem, idioma):
    """Monta as linhas de metadados do cabeçalho, já escapadas."""
    linhas = []
    if nome_origem:
        linhas.append("Origem: {0}".format(escape(str(nome_origem))))
    linhas.append("Gerado em: {0}".format(datetime.now().strftime('%d/%m/%Y às %H:%M')))
    if idioma:
        linhas.append("Idioma: {0}".format(escape(str(idioma))))
    return linhas


def transcricao_para_pdf(texto, caminho_pdf, nome_origem=None, idioma=None):
    """Grava `texto` como PDF em `caminho_pdf` (caminho ou objeto tipo arquivo)."""
    if not texto or not texto.strip():
        raise ValueError("Não há texto para gerar o PDF")

    titulo, meta, corpo = _estilos()

    documento = SimpleDocTemplate(
        caminho_pdf,
        pagesize=A4,
        leftMargin=MARGEM,
        rightMargin=MARGEM,
        topMargin=MARGEM,
        bottomMargin=MARGEM,
        title="Transcrição",
        author="transcricaoAudio",
    )

    historia = [Paragraph("Transcrição", titulo)]
    historia.append(Paragraph(' &nbsp;·&nbsp; '.join(_linhas_cabecalho(nome_origem, idioma)), meta))
    historia.append(Spacer(1, 0.8 * cm))

    # O Paragraph interpreta o conteúdo como markup: um "&" ou "<" solto vindo da
    # transcrição quebraria a geração, por isso tudo passa por escape().
    for paragrafo in _dividir_paragrafos(texto):
        historia.append(Paragraph(escape(paragrafo), corpo))

    documento.build(historia, onFirstPage=_rodape, onLaterPages=_rodape)
    return caminho_pdf
