"""FERRAMENTA DE EMPACOTAMENTO -- nao faz parte da aplicacao.

Transforma docs/GUIA-DO-CLIENTE.md no PDF que vai junto com a instalacao. O
guia vive em Markdown porque e la que ele e escrito e revisado; o cliente
recebe PDF porque e o que um leigo abre sem pensar.

O PDF nao e versionado (o .gitignore ja ignora *.pdf): e artefato de entrega,
gerado a partir da fonte. Por isso este script existe em vez de um binario no
repositorio.

Le so o subconjunto de Markdown que o guia usa -- titulo, secao, lista
numerada, lista com marcador, citacao, regua e negrito. Nao e um conversor de
Markdown de uso geral, e nao tenta ser: escopo fechado, comportamento previsivel.

Uso:
    python cliente/gerar_guia_pdf.py
    python cliente/gerar_guia_pdf.py --saida "C:\\entrega\\Guia.pdf"
"""

import argparse
import os
import re
import sys
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (HRFlowable, ListFlowable, ListItem, Paragraph,
                                SimpleDocTemplate)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTE = os.path.join(RAIZ, 'docs', 'GUIA-DO-CLIENTE.md')
SAIDA_PADRAO = os.path.join(RAIZ, 'cliente', 'Transcricao de audio - guia rapido.pdf')

# As mesmas cores do tema da aplicacao (.streamlit/config.toml), para o guia e a
# tela nao parecerem dois produtos.
TEAL = colors.HexColor('#0F766E')
GRAFITE = colors.HexColor('#1C2723')
SALVIA = colors.HexColor('#3F5B53')
MARGEM = 1.8 * cm


def _inline(texto):
    """Converte o negrito e o codigo do Markdown nas marcas do reportlab."""
    texto = escape(texto)
    texto = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', texto)
    texto = re.sub(r'\*(.+?)\*', r'<i>\1</i>', texto)
    texto = re.sub(r'`(.+?)`', r'<font face="Courier">\1</font>', texto)
    return texto


def _estilos():
    base = getSampleStyleSheet()
    comum = dict(fontName='Helvetica', textColor=GRAFITE)
    return {
        'titulo': ParagraphStyle('Titulo', parent=base['Normal'], fontName='Helvetica-Bold',
                                 fontSize=17, leading=21, textColor=TEAL, spaceAfter=7),
        'secao': ParagraphStyle('Secao', parent=base['Normal'], fontName='Helvetica-Bold',
                                fontSize=11.5, leading=15, textColor=TEAL,
                                spaceBefore=9, spaceAfter=4),
        'subsecao': ParagraphStyle('Subsecao', parent=base['Normal'], fontName='Helvetica-Bold',
                                   fontSize=10.5, leading=14, textColor=SALVIA,
                                   spaceBefore=10, spaceAfter=4),
        'corpo': ParagraphStyle('Corpo', parent=base['Normal'], fontSize=9, leading=12.4,
                                spaceAfter=5, **comum),
        'item': ParagraphStyle('Item', parent=base['Normal'], fontSize=9, leading=12.4,
                               spaceAfter=3, **comum),
        # Citacao: recuada e em salvia, que e como a tela marca o que e aviso.
        'nota': ParagraphStyle('Nota', parent=base['Normal'], fontName='Helvetica-Oblique',
                               fontSize=8.5, leading=11.8, textColor=SALVIA,
                               leftIndent=9, spaceBefore=3, spaceAfter=6),
    }


def _blocos(linhas, estilos):
    """Percorre as linhas do Markdown e devolve os flowables do reportlab."""
    saida = []
    pendentes = []       # itens de lista ainda nao fechados
    numerada = False

    def fechar_lista():
        nonlocal pendentes, numerada
        if not pendentes:
            return
        saida.append(ListFlowable(
            [ListItem(p, leftIndent=16) for p in pendentes],
            bulletType='1' if numerada else 'bullet',
            bulletFontName='Helvetica', bulletFontSize=9,
            bulletColor=TEAL, leftIndent=16, spaceAfter=8))
        pendentes = []

    for linha in linhas:
        crua = linha.rstrip('\n')
        texto = crua.strip()

        if not texto:
            fechar_lista()
            continue
        if texto.startswith('---'):
            fechar_lista()
            saida.append(HRFlowable(width='100%', thickness=0.6, color=SALVIA,
                                    spaceBefore=3, spaceAfter=6))
            continue
        if texto.startswith('### '):
            fechar_lista()
            saida.append(Paragraph(_inline(texto[4:]), estilos['subsecao']))
            continue
        if texto.startswith('## '):
            fechar_lista()
            saida.append(Paragraph(_inline(texto[3:]), estilos['secao']))
            continue
        if texto.startswith('# '):
            fechar_lista()
            saida.append(Paragraph(_inline(texto[2:]), estilos['titulo']))
            continue
        if texto.startswith('> '):
            fechar_lista()
            saida.append(Paragraph(_inline(texto[2:]), estilos['nota']))
            continue

        item_numerado = re.match(r'^(\d+)\.\s+(.*)', texto)
        item_marcado = texto.startswith('- ')
        if item_numerado or item_marcado:
            quer_numerada = bool(item_numerado)
            if pendentes and quer_numerada != numerada:
                fechar_lista()
            numerada = quer_numerada
            conteudo = item_numerado.group(2) if item_numerado else texto[2:]
            pendentes.append(Paragraph(_inline(conteudo), estilos['item']))
            continue

        # Continuacao indentada de um item de lista: gruda no item anterior.
        if pendentes and crua.startswith('   '):
            anterior = pendentes[-1]
            pendentes[-1] = Paragraph(anterior.text + ' ' + _inline(texto), estilos['item'])
            continue

        fechar_lista()
        saida.append(Paragraph(_inline(texto), estilos['corpo']))

    fechar_lista()
    return saida


def gerar(fonte=FONTE, saida=SAIDA_PADRAO):
    with open(fonte, encoding='utf-8') as arquivo:
        linhas = arquivo.readlines()

    documento = SimpleDocTemplate(
        saida, pagesize=A4,
        leftMargin=MARGEM, rightMargin=MARGEM,
        topMargin=MARGEM, bottomMargin=MARGEM,
        title="Transcricao de audio - guia rapido", author="Marcelo Viana de Araujo")
    documento.build(_blocos(linhas, _estilos()))
    return saida


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--fonte', default=FONTE, help="o Markdown de origem")
    parser.add_argument('--saida', default=SAIDA_PADRAO, help="o PDF a gerar")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.fonte):
        print("Nao encontrei {0}".format(args.fonte), file=sys.stderr)
        return 1
    caminho = gerar(args.fonte, args.saida)
    print("guia gerado: {0} ({1:.0f} KB)".format(caminho, os.path.getsize(caminho) / 1024.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
