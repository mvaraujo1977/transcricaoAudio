"""FERRAMENTA DE EMPACOTAMENTO -- nao faz parte da aplicacao.

Gera os dois icones dos atalhos da Area de Trabalho. Sao a mesma familia de
proposito: quem olha a Area de Trabalho precisa ver um programa so, nao dois.

O desenho e uma onda sonora virando linhas de texto -- em cima as barras do
audio, embaixo as linhas do paragrafo. Empilhado, e nao lado a lado, porque num
icone de 32 px (o tamanho que a Area de Trabalho usa de verdade) qualquer
composicao horizontal vira borrao.

    principal  fundo teal, desenho creme    -- cheio, e o do dia a dia
    plano B    fundo creme, desenho salvia  -- contornado e mais apagado

O plano B e secundario e o icone diz isso sozinho: mesmo desenho, peso menor.
As cores saem do tema da aplicacao (.streamlit/config.toml), para o atalho e a
tela nao parecerem dois produtos.

Uso:
    python cliente/gerar_icones.py
    python cliente/gerar_icones.py --previa    # gera tambem PNGs para olhar
"""

import argparse
import math
import os
import sys

from PIL import Image, ImageDraw

AQUI = os.path.dirname(os.path.abspath(__file__))

TEAL = (15, 118, 110, 255)      # primaryColor do tema claro
CREME = (250, 248, 244, 255)    # backgroundColor
SALVIA = (63, 91, 83, 255)      # grayColor

# Desenhado grande e reduzido por LANCZOS: e o que da borda limpa nos tamanhos
# pequenos, que sao os que o Windows realmente mostra.
L = 512
TAMANHOS = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

# A onda e um TRACO CONTINUO, e nao barras. O caminho ate aqui foi por teste,
# no unico tamanho que importa -- 16 px, que e onde o icone da Area de Trabalho
# vive:
#
#   sete barras finas  -> mancha cinza; cada barra ficava com 1,3 px
#   tres barras grossas -> legivel, mas o icone lia como um ROSTO: tres
#                          elementos em cima e barra horizontal embaixo e
#                          composicao facial, por mais que se ajuste proporcao
#   traco continuo      -> le como onda em qualquer tamanho, e nao tem como
#                          virar olhos
#
# Tres meias-ondas (1,5 ciclo): com mais ciclos as cristas se aproximam e o
# reamostrador as funde de novo.
CICLOS = 3.0
AMPLITUDE = 0.135       # fracao de L
GROSSURA_ONDA = 0.085
EIXO_ONDA = 0.33

# Duas linhas de texto. A segunda e curta: e o que faz duas barras horizontais
# serem lidas como paragrafo, e nao como sinal de igual.
LINHAS = [1.0, 0.52]
GROSSURA_LINHA = 0.095
TOPO_LINHAS = 0.60

MARGEM = 0.15


def _desenhar(fundo, tinta, contorno=None):
    """Monta um icone: onda sonora em cima, linhas de texto embaixo."""
    img = Image.new('RGBA', (L, L), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    raio_caixa = int(L * 0.22)
    d.rounded_rectangle([0, 0, L - 1, L - 1], radius=raio_caixa, fill=fundo)
    if contorno is not None:
        # O contorno e o que distingue o icone secundario de longe, antes mesmo
        # de a pessoa notar que o fundo e claro. Fino: a 16 px um contorno
        # grosso come o desenho de dentro.
        largura = int(L * 0.042)
        d.rounded_rectangle([largura // 2, largura // 2,
                             L - 1 - largura // 2, L - 1 - largura // 2],
                            radius=raio_caixa - largura // 4,
                            outline=contorno, width=largura)

    margem = int(L * MARGEM)
    util = L - 2 * margem

    # --- onda ----------------------------------------------------------------
    eixo = int(L * EIXO_ONDA)
    amplitude = int(L * AMPLITUDE)
    grossura = int(L * GROSSURA_ONDA)

    pontos = []
    for passo in range(49):
        t = passo / 48.0
        pontos.append((margem + int(util * t),
                       eixo - int(amplitude * math.sin(t * math.pi * CICLOS))))
    d.line(pontos, fill=tinta, width=grossura, joint='curve')
    # O `line` do Pillow deixa as pontas em esquadria; os circulos as arredondam,
    # para a onda casar com o acabamento das linhas de texto.
    for ponta in (pontos[0], pontos[-1]):
        d.ellipse([ponta[0] - grossura // 2, ponta[1] - grossura // 2,
                   ponta[0] + grossura // 2, ponta[1] + grossura // 2], fill=tinta)

    # --- linhas de texto -----------------------------------------------------
    grossura_linha = int(L * GROSSURA_LINHA)
    passo_linha = int(grossura_linha * 1.85)
    topo = int(L * TOPO_LINHAS)

    for indice, fracao in enumerate(LINHAS):
        y = topo + indice * passo_linha
        d.rounded_rectangle([margem, y, margem + int(util * fracao), y + grossura_linha],
                            radius=grossura_linha // 2, fill=tinta)

    return img


def gerar(previa=False):
    """Grava os dois .ico e devolve os caminhos."""
    pecas = (
        ('transcricao.ico', _desenhar(TEAL, CREME)),
        ('transcricao-planoB.ico', _desenhar(CREME, SALVIA, contorno=TEAL)),
    )
    caminhos = []
    for nome, img in pecas:
        alvo = os.path.join(AQUI, nome)
        img.resize((256, 256), Image.LANCZOS).save(alvo, format='ICO', sizes=TAMANHOS)
        caminhos.append(alvo)
        if previa:
            # Duas escalas: 128 px para olhar o desenho, 32 px para conferir que
            # ele sobrevive ao tamanho em que o Windows vai mostra-lo.
            for lado in (128, 32):
                png = alvo.replace('.ico', '-previa-{0}.png'.format(lado))
                fundo = Image.new('RGB', (lado, lado), (255, 255, 255))
                fundo.paste(img.resize((lado, lado), Image.LANCZOS),
                            (0, 0), img.resize((lado, lado), Image.LANCZOS))
                fundo.save(png)
                caminhos.append(png)
    return caminhos


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--previa', action='store_true',
                        help="grava tambem PNGs de 128 e 32 px para inspecao")
    args = parser.parse_args(argv)
    for caminho in gerar(previa=args.previa):
        print("  {0} ({1:.0f} KB)".format(os.path.basename(caminho),
                                          os.path.getsize(caminho) / 1024.0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
