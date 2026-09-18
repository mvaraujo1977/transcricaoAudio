"""Mede a qualidade de uma transcrição: pontuação, jargão e repetição em loop.

Uso: python verificar_transcricao.py dados/arquivo.mp3 [modelo]
"""

import collections
import re
import sys
import time

from audioTranscricao import transcrever

# Siglas e termos cujo acerto indica que o jargão do domínio sobreviveu.
JARGAO = ['LIMPE', 'legalidade', 'impessoalidade', 'moralidade', 'publicidade', 'eficiência']


def repeticoes_em_loop(texto, minimo=3):
    """Encontra frases repetidas em sequência, falha típica do Whisper no silêncio."""
    frases = [f.strip().lower() for f in re.split(r'[.!?]+', texto) if len(f.strip()) > 15]
    repetidas = []
    atual, contagem = None, 0
    for frase in frases:
        if frase == atual:
            contagem += 1
        else:
            if contagem >= minimo:
                repetidas.append((atual, contagem))
            atual, contagem = frase, 1
    if contagem >= minimo:
        repetidas.append((atual, contagem))
    return repetidas


def main():
    caminho = sys.argv[1]
    modelo = sys.argv[2] if len(sys.argv) > 2 else 'small'

    inicio = time.time()
    resultado = transcrever(caminho, idioma='pt-BR', modelo=modelo)
    decorrido = time.time() - inicio

    texto = resultado.texto
    palavras = len(texto.split())
    pontos = texto.count('.')
    virgulas = texto.count(',')
    paragrafos = len([p for p in texto.split('\n\n') if p.strip()])

    print("=" * 60)
    print("arquivo .........: {0}".format(caminho))
    print("modelo ..........: {0}".format(modelo))
    print("duracao do audio : {0:.0f}s ({1:.1f} min)".format(resultado.duracao, resultado.duracao / 60))
    print("tempo de proc. ..: {0:.0f}s ({1:.1f} min) | {2:.2f}x tempo real".format(
        decorrido, decorrido / 60, resultado.duracao / decorrido if decorrido else 0))
    print("idioma detectado : {0}".format(resultado.idioma_detectado))
    print("-" * 60)
    print("palavras ........: {0}".format(palavras))
    print("pontos finais ...: {0}".format(pontos))
    print("virgulas ........: {0}".format(virgulas))
    print("paragrafos ......: {0}".format(paragrafos))
    print("segmentos .......: {0}".format(len(resultado.segmentos)))
    print("-" * 60)

    for termo in JARGAO:
        ocorrencias = len(re.findall(re.escape(termo), texto, re.IGNORECASE))
        print("{0:.<17}: {1}".format(termo, ocorrencias or 'AUSENTE'))

    print("-" * 60)
    loops = repeticoes_em_loop(texto)
    if loops:
        print("REPETICAO EM LOOP detectada:")
        for frase, vezes in loops:
            print("  {0}x: {1!r}".format(vezes, frase[:70]))
    else:
        print("repeticao em loop: nenhuma")

    frequentes = collections.Counter(
        f.strip().lower() for f in re.split(r'[.!?]+', texto) if len(f.strip()) > 15)
    repetidas = [(f, n) for f, n in frequentes.most_common(3) if n > 2]
    if repetidas:
        print("frases repetidas (nao consecutivas):")
        for frase, vezes in repetidas:
            print("  {0}x: {1!r}".format(vezes, frase[:70]))

    print("=" * 60)
    print("PRIMEIROS 2 PARAGRAFOS:")
    for paragrafo in [p for p in texto.split('\n\n') if p.strip()][:2]:
        print("  " + paragrafo[:300])
    return 0


if __name__ == '__main__':
    sys.exit(main())
