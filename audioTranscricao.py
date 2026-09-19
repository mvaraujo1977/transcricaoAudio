"""Transcreve áudio (ou a trilha de um vídeo) para texto usando o faster-whisper, local."""

import argparse
import collections
import functools
import os
import sys

MODELOS = ('tiny', 'base', 'small', 'medium', 'large-v3')
MODELO_PADRAO = 'small'

# O Whisper identifica idiomas por ISO 639-1 ("pt"), não pelas etiquetas regionais
# que a interface usa ("pt-BR"). O mapa aceita as duas formas.
IDIOMAS_WHISPER = {
    'pt-br': 'pt', 'pt-pt': 'pt', 'pt': 'pt',
    'en-us': 'en', 'en-gb': 'en', 'en': 'en',
    'es-es': 'es', 'es-mx': 'es', 'es': 'es',
    'fr-fr': 'fr', 'fr': 'fr',
    'it-it': 'it', 'it': 'it',
    'de-de': 'de', 'de': 'de',
}

# Um parágrafo fecha no primeiro segmento terminado em pontuação forte depois
# deste tamanho, para o PDF não virar um bloco único de texto.
TAMANHO_PARAGRAFO = 500
FIM_DE_FRASE = ('.', '!', '?')

# O Whisper reserva metade do seu contexto de 448 tokens para o initial_prompt e
# descarta silenciosamente o que passar disso; o excedente é cortado por nós.
LIMITE_TOKENS_VOCABULARIO = 224

Segmento = collections.namedtuple('Segmento', 'start end text')

Transcricao = collections.namedtuple(
    'Transcricao', 'texto segmentos duracao idioma_detectado')


@functools.lru_cache(maxsize=2)
def carregar_modelo(nome_modelo=MODELO_PADRAO):
    """Devolve o WhisperModel, reaproveitando a instância entre chamadas.

    Instanciar o modelo lê centenas de MB do disco; o cache evita pagar isso a
    cada transcrição.
    """
    from faster_whisper import WhisperModel
    return WhisperModel(nome_modelo, device="cpu", compute_type="int8")


def codigo_idioma(idioma):
    """Converte 'pt-BR' em 'pt'. None significa deixar o Whisper detectar."""
    if not idioma:
        return None
    return IDIOMAS_WHISPER.get(idioma.strip().lower(), idioma.split('-')[0].lower())


def preparar_vocabulario(vocabulario, modelo=MODELO_PADRAO):
    """Devolve (texto, foi_truncado) pronto para virar initial_prompt.

    O Whisper corta o prompt em 224 tokens sem avisar; aqui o corte é explícito,
    para a tela poder dizer que parte do vocabulário ficou de fora.
    """
    if not vocabulario or not vocabulario.strip():
        return None, False

    texto = ' '.join(vocabulario.split())
    tokenizer = carregar_modelo(modelo).hf_tokenizer
    ids = tokenizer.encode(texto, add_special_tokens=False).ids
    if len(ids) <= LIMITE_TOKENS_VOCABULARIO:
        return texto, False

    cortado = tokenizer.decode(ids[:LIMITE_TOKENS_VOCABULARIO]).strip()
    if ' ' in cortado:  # não termina no meio de uma palavra
        cortado = cortado.rsplit(' ', 1)[0]
    return cortado, True


def agrupar_em_paragrafos(segmentos):
    """Agrupa segmentos em parágrafos separados por linha em branco.

    gerar_pdf.py divide o texto justamente por '\\n\\n', então este é o formato
    que faz o PDF sair paginado em parágrafos em vez de um bloco corrido.
    """
    paragrafos = []
    atual = []
    tamanho = 0

    for segmento in segmentos:
        texto = segmento.text.strip()
        if not texto:
            continue
        atual.append(texto)
        tamanho += len(texto) + 1
        if tamanho >= TAMANHO_PARAGRAFO and texto.endswith(FIM_DE_FRASE):
            paragrafos.append(' '.join(atual))
            atual = []
            tamanho = 0

    if atual:
        paragrafos.append(' '.join(atual))
    return paragrafos


def inicio_dos_paragrafos(segmentos):
    """Devolve o `start` do primeiro segmento de cada parágrafo, na mesma ordem."""
    inicios = []
    tamanho = 0
    aberto = False

    for segmento in segmentos:
        texto = segmento.text.strip()
        if not texto:
            continue
        if not aberto:
            inicios.append(segmento.start)
            aberto = True
        tamanho += len(texto) + 1
        if tamanho >= TAMANHO_PARAGRAFO and texto.endswith(FIM_DE_FRASE):
            aberto = False
            tamanho = 0

    return inicios


def transcrever(caminho, text_output_path=None, idioma="pt-BR", modelo=MODELO_PADRAO,
                progresso=None, vocabulario=None):
    """Transcreve `caminho` e devolve um Transcricao.

    `progresso`, quando informado, é chamado a cada segmento reconhecido como
    progresso(segundos_processados, duracao_total).

    `vocabulario` semeia o reconhecimento com termos e siglas do domínio, o que
    corrige jargão que o modelo erraria por não esperar aquelas palavras.
    """
    if not os.path.isfile(caminho):
        raise FileNotFoundError("Arquivo não encontrado: {0}".format(caminho))

    model = carregar_modelo(modelo)
    prompt, truncado = preparar_vocabulario(vocabulario, modelo)
    if truncado:
        print("Aviso: o vocabulário passou de {0} tokens e foi cortado.".format(
            LIMITE_TOKENS_VOCABULARIO), file=sys.stderr)

    # vad_filter descarta o silêncio: acelera a transcrição e evita o modo de
    # falha do Whisper de repetir a mesma frase em loop em trechos mudos.
    segmentos_brutos, info = model.transcribe(
        caminho,
        language=codigo_idioma(idioma),
        beam_size=5,
        vad_filter=True,
        initial_prompt=prompt,
    )

    # `segmentos_brutos` é um gerador: a transcrição só ocorre ao iterar, o que
    # dá progresso real sem dividir o áudio em blocos artificiais.
    segmentos = []
    for segmento in segmentos_brutos:
        segmentos.append(Segmento(segmento.start, segmento.end, segmento.text))
        if progresso is not None:
            progresso(min(segmento.end, info.duration), info.duration)

    if not segmentos:
        raise RuntimeError("Nenhuma fala foi reconhecida no arquivo")

    texto = '\n\n'.join(agrupar_em_paragrafos(segmentos))

    if text_output_path is not None:
        with open(text_output_path, 'w', encoding='utf-8') as arquivo:
            arquivo.write(texto)
        print("Transcrição salva em: {0}".format(text_output_path))

    if progresso is not None:
        progresso(info.duration, info.duration)

    return Transcricao(texto, segmentos, info.duration, info.language)


def transcribe_audio_to_text(audio_path, text_output_path=None, idioma="pt-BR",
                             modelo=MODELO_PADRAO, progresso=None, vocabulario=None):
    """Alias mantido para não quebrar importações existentes."""
    return transcrever(audio_path, text_output_path, idioma, modelo, progresso, vocabulario)


def _mmss(segundos):
    segundos = int(segundos or 0)
    return "{0:02d}:{1:02d}".format(segundos // 60, segundos % 60)


def main(argv=None):
    script_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(description="Transcreve um arquivo de áudio ou vídeo para texto.")
    parser.add_argument('entrada', nargs='?', default=os.path.join(script_dir, 'audio1.wav'),
                        help="arquivo de áudio ou vídeo (padrão: audio1.wav ao lado do script)")
    parser.add_argument('-o', '--saida', default=os.path.join(script_dir, 'transcricao_audio.txt'),
                        help="arquivo .txt de saída")
    parser.add_argument('-l', '--idioma', default='pt-BR',
                        help="idioma do áudio (ex.: en-US); vazio deixa o Whisper detectar")
    parser.add_argument('-m', '--modelo', default=MODELO_PADRAO, choices=MODELOS,
                        help="modelo Whisper: maiores são mais precisos e mais lentos")
    parser.add_argument('-v', '--vocabulario', default=None,
                        help="termos e siglas do domínio, para o modelo acertar o jargão")
    args = parser.parse_args(argv)

    def progresso(processado, total):
        if total:
            print("\r  {0} de {1} ({2:.0f}%)".format(
                _mmss(processado), _mmss(total), 100.0 * processado / total),
                end='', file=sys.stderr)

    try:
        resultado = transcrever(args.entrada, args.saida, args.idioma, args.modelo,
                                progresso, args.vocabulario)
    except (OSError, ValueError, RuntimeError) as erro:
        print("Erro: {0}".format(erro), file=sys.stderr)
        return 1

    print("", file=sys.stderr)
    print("Duração: {0} | idioma detectado: {1} | {2} segmentos".format(
        _mmss(resultado.duracao), resultado.idioma_detectado, len(resultado.segmentos)),
        file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
