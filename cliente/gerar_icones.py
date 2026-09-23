"""FERRAMENTA DE EMPACOTAMENTO -- nao faz parte da aplicacao.

Gera os dois icones dos atalhos da Area de Trabalho. Sao a mesma familia de
proposito: quem olha a Area de Trabalho precisa ver um programa so, nao dois.

O desenho e um MICROFONE: capsula, berco, haste e barra de apoio.

    principal  fundo teal, desenho creme    -- cheio, e o do dia a dia
    plano B    fundo creme, desenho salvia  -- contornado e mais apagado

O plano B e secundario e o icone diz isso sozinho: mesmo desenho, peso menor.
As cores saem do tema da aplicacao (.streamlit/config.toml), para o atalho e a
tela nao parecerem dois produtos.

Sobre as medidas: elas NAO foram desenhadas do zero. Saem do icone aprovado
que estava em b2b012f, medido pixel a pixel na grade de 256 px -- e por isso
que as medidas abaixo estao escritas como divisoes por 256, com casas
quebradas como 46.5, em vez de fracoes redondas: sao leitura de regua, nao
escolha de desenhista. Mexer nelas a esmo desfaz um desenho ja aprovado.

Houve uma tentativa de trocar este microfone por uma onda sonora virando
linhas de texto. Ela foi revertida: a onda nao dizia "audio" a quem olhava a
mesa de relance, e o microfone sim. Fica o registro para ninguem refazer a
troca achando que e melhoria.

Duas coisas que o desenho resolve no unico tamanho que importa -- 16 e 32 px,
que e onde o icone da Area de Trabalho vive de verdade:

    o berco encosta na base da capsula (os dois terminam em y=138 na grade de
    256), entao a silhueta fecha numa peca so em vez de virar capsula solta
    boiando sobre um risco;

    a haste e a barra tem a mesma grossura do berco, o que mantem o peso do
    traco uniforme quando o reamostrador espreme tudo para 16 px.

Uso:
    python cliente/gerar_icones.py
    python cliente/gerar_icones.py --previa    # gera tambem PNGs para olhar
"""

import argparse
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

RAIO_CAIXA = 0.22

# Todas as fracoes sao de L e saem da medicao do icone de b2b012f. O desenho
# inteiro e centrado na vertical do icone.
CAPSULA_LARGURA = 58 / 256.0
CAPSULA_TOPO = 51 / 256.0
CAPSULA_BASE = 138 / 256.0      # tambem e o centro do berco

# Meio pixel a mais no raio e um no traco: o `arc` desenhado em 512 e
# reduzido para 256 perde essa beirada para o antialias, e sem a folga o
# berco sai mais fino que o do icone aprovado. Numero conferido medindo o
# .ico gerado, nao estimado.
BERCO_RAIO = 47.5 / 256.0       # externo; o `arc` do Pillow cresce para dentro
BERCO_GROSSURA = 12 / 256.0

HASTE_LARGURA = 11 / 256.0
BARRA_TOPO = 202 / 256.0
BARRA_LARGURA = 66 / 256.0
BARRA_GROSSURA = 10 / 256.0


def _desenhar(fundo, tinta, contorno=None):
    """Monta um icone: microfone sobre fundo arredondado."""
    img = Image.new('RGBA', (L, L), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    raio_caixa = int(L * RAIO_CAIXA)
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

    meio = L / 2.0

    # --- capsula -------------------------------------------------------------
    # Raio igual a metade da largura: um estadio, e nao um retangulo de cantos
    # arredondados. E o que da a forma de microfone de mao.
    capsula_meia = L * CAPSULA_LARGURA / 2.0
    topo = L * CAPSULA_TOPO
    base = L * CAPSULA_BASE
    d.rounded_rectangle([meio - capsula_meia, topo, meio + capsula_meia, base],
                        radius=capsula_meia, fill=tinta)

    # --- berco ---------------------------------------------------------------
    # Meia circunferencia (0 a 180 graus = metade de baixo) centrada exatamente
    # na base da capsula. As pontas ficam em esquadria, encostando na capsula:
    # arredonda-las abriria uma fresta que a 16 px vira sujeira.
    raio = L * BERCO_RAIO
    grossura = max(1, int(round(L * BERCO_GROSSURA)))
    d.arc([meio - raio, base - raio, meio + raio, base + raio],
          start=0, end=180, fill=tinta, width=grossura)

    # --- haste ---------------------------------------------------------------
    # Vai do fundo do berco ate dentro da barra: a sobreposicao de 1 px evita
    # a costura clara que aparece entre duas figuras que apenas se tocam.
    haste_meia = L * HASTE_LARGURA / 2.0
    barra_topo = L * BARRA_TOPO
    d.rectangle([meio - haste_meia, base + raio - 1, meio + haste_meia, barra_topo + 1],
                fill=tinta)

    # --- barra de apoio ------------------------------------------------------
    barra_meia = L * BARRA_LARGURA / 2.0
    barra_grossura = L * BARRA_GROSSURA
    d.rounded_rectangle([meio - barra_meia, barra_topo,
                         meio + barra_meia, barra_topo + barra_grossura],
                        radius=barra_grossura / 2.0, fill=tinta)

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
