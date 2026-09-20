"""Transcreve áudio (ou a trilha de um vídeo) para texto usando o faster-whisper, local."""

import argparse
import collections
import functools
import os
import sys

import av
import numpy as np

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

# O faster-whisper decodifica o arquivo inteiro para um array float32 de 16 kHz
# antes de transcrever, e so entao expoe a duracao. Isso torna a duracao inutil
# como defesa: a memoria ja foi gasta. Um Opus de 6 kbps com 2 h de audio ocupa
# 2,7 MB em disco e 1,1 GB ao decodificar -- 170x. O teto abaixo e aplicado por
# nos, durante a decodificacao, contando amostras.
#
# Custo do teto padrao: 4 h = 230,4 M amostras = 461 MB em s16 e 922 MB em
# float32. O pico transitorio da conversao fica em ~1,4 GB. Abaixe
# TRANSCRICAO_MAX_HORAS numa maquina apertada.
LIMITE_HORAS_PADRAO = 4.0
VARIAVEL_LIMITE = 'TRANSCRICAO_MAX_HORAS'

# O Whisper trabalha internamente a 16 kHz mono; decodificar direto nesse
# formato evita uma reamostragem depois.
TAXA_WHISPER = 16000

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


class DuracaoExcedida(ValueError):
    """Audio mais longo que o teto configurado.

    Herda de ValueError para ser capturada pelo mesmo `except` que ja trata os
    demais erros de entrada, na CLI e na interface.
    """


def limite_horas():
    """Teto de duracao em horas, configuravel por TRANSCRICAO_MAX_HORAS."""
    bruto = os.environ.get(VARIAVEL_LIMITE)
    if not bruto or not bruto.strip():
        return LIMITE_HORAS_PADRAO
    try:
        valor = float(bruto)
    except ValueError:
        raise ValueError("{0} precisa ser um numero em horas; veio {1!r}".format(
            VARIAVEL_LIMITE, bruto))
    if valor <= 0:
        raise ValueError("{0} precisa ser maior que zero; veio {1!r}".format(
            VARIAVEL_LIMITE, bruto))
    return valor


def sondar_duracao(caminho):
    """Duracao declarada no arquivo, em segundos, sem decodificar nada.

    Custa milissegundos: le so o cabecalho do container. Devolve None quando o
    formato nao declara duracao. O valor vem do arquivo, ou seja, de quem o
    enviou -- serve para recusar cedo o caso obvio, nunca como unica defesa.
    """
    with av.open(caminho) as container:
        if container.duration is not None:
            return float(container.duration) / av.time_base
        for trilha in container.streams.audio:
            if trilha.duration is not None and trilha.time_base:
                return float(trilha.duration * trilha.time_base)
    return None


def decodificar_audio(caminho, limite_segundos):
    """Decodifica para float32 mono 16 kHz, abortando ao passar do teto.

    Este e o portao que de fato fecha: conta amostras durante a decodificacao e
    para no instante em que o teto e ultrapassado, sem depender do cabecalho.
    Um arquivo que minta sobre a propria duracao e interrompido do mesmo jeito.

    O formato de saida (float32 normalizado a partir de s16) e identico ao que
    o faster_whisper.audio.decode_audio produz, para a transcricao nao mudar.
    """
    maximo = int(limite_segundos * TAXA_WHISPER)
    resampler = av.AudioResampler(format='s16', layout='mono', rate=TAXA_WHISPER)
    blocos = []
    total = 0

    def acumular(quadros):
        nonlocal total
        for convertido in quadros or []:
            bloco = convertido.to_ndarray().reshape(-1)
            total += bloco.shape[0]
            if total > maximo:
                raise DuracaoExcedida(
                    "O audio passa do limite de {0:.1f} h. Aumente {1} ou use "
                    "--sem-limite na linha de comando se o arquivo for seu.".format(
                        limite_segundos / 3600.0, VARIAVEL_LIMITE))
            blocos.append(bloco)

    with av.open(caminho) as container:
        if not container.streams.audio:
            raise RuntimeError("O arquivo nao tem trilha de audio")
        for quadro in container.decode(audio=0):
            quadro.pts = None
            acumular(resampler.resample(quadro))
        acumular(resampler.resample(None))

    if not blocos:
        raise RuntimeError("Nao foi possivel decodificar audio do arquivo")

    amostras = np.concatenate(blocos)
    blocos.clear()  # libera os pedacos antes de alocar o float32, que e o dobro
    return amostras.astype(np.float32) / 32768.0


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
                progresso=None, vocabulario=None, max_horas=None):
    """Transcreve `caminho` e devolve um Transcricao.

    `progresso`, quando informado, é chamado a cada segmento reconhecido como
    progresso(segundos_processados, duracao_total).

    `vocabulario` semeia o reconhecimento com termos e siglas do domínio, o que
    corrige jargão que o modelo erraria por não esperar aquelas palavras.

    `max_horas` sobrepõe o teto de duração; use float('inf') para não ter teto.
    Levanta DuracaoExcedida quando o áudio passa do limite.
    """
    if not os.path.isfile(caminho):
        raise FileNotFoundError("Arquivo não encontrado: {0}".format(caminho))

    limite_segundos = (limite_horas() if max_horas is None else float(max_horas)) * 3600.0

    # Dois portões. A sonda recusa em milissegundos o arquivo que se declara
    # longo demais; a decodificação contada pega o que mente no cabeçalho.
    declarada = sondar_duracao(caminho)
    if declarada is not None and declarada > limite_segundos:
        raise DuracaoExcedida(
            "O áudio tem {0:.1f} h, acima do limite de {1:.1f} h. Aumente {2} ou "
            "use --sem-limite na linha de comando se o arquivo for seu.".format(
                declarada / 3600.0, limite_segundos / 3600.0, VARIAVEL_LIMITE))

    audio = decodificar_audio(caminho, limite_segundos)

    model = carregar_modelo(modelo)
    prompt, truncado = preparar_vocabulario(vocabulario, modelo)
    if truncado:
        print("Aviso: o vocabulário passou de {0} tokens e foi cortado.".format(
            LIMITE_TOKENS_VOCABULARIO), file=sys.stderr)

    # vad_filter descarta o silêncio: acelera a transcrição e evita o modo de
    # falha do Whisper de repetir a mesma frase em loop em trechos mudos.
    #
    # temperature=0.0 desliga o fallback por amostragem. O padrão do
    # faster-whisper é [0.0, 0.2, ..., 1.0]: quando um segmento estoura os
    # limiares de compression_ratio ou log_prob, ele é reprocessado com
    # temperatura crescente, o que é não-determinístico. Duas execuções do mesmo
    # áudio divergiam em dezenas de palavras (e chegavam a perder um item de uma
    # enumeração), o que impede comparar transcrições — por exemplo, para medir
    # se o vocabulário do domínio ajudou. Com 0.0 o segmento difícil sai pior,
    # mas sai igual toda vez, e a diferença entre duas execuções passa a ser
    # atribuível ao que mudou de fato.
    # `audio` já vem decodificado: o faster-whisper só chama o próprio decode
    # quando não recebe um ndarray, e info.duration é calculado a partir do
    # array, então a duração e o progresso seguem corretos.
    segmentos_brutos, info = model.transcribe(
        audio,
        language=codigo_idioma(idioma),
        beam_size=5,
        vad_filter=True,
        initial_prompt=prompt,
        temperature=0.0,
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
                             modelo=MODELO_PADRAO, progresso=None, vocabulario=None,
                             max_horas=None):
    """Alias mantido para não quebrar importações existentes."""
    return transcrever(audio_path, text_output_path, idioma, modelo, progresso,
                       vocabulario, max_horas)


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
    parser.add_argument('--max-horas', type=float, default=None, metavar='H',
                        help="teto de duração em horas (padrão: {0:g}, ou {1})".format(
                            LIMITE_HORAS_PADRAO, VARIAVEL_LIMITE))
    parser.add_argument('--sem-limite', action='store_true',
                        help="desliga o teto de duração; use só em arquivo de origem confiável")
    args = parser.parse_args(argv)

    def progresso(processado, total):
        if total:
            print("\r  {0} de {1} ({2:.0f}%)".format(
                _mmss(processado), _mmss(total), 100.0 * processado / total),
                end='', file=sys.stderr)

    try:
        max_horas = float('inf') if args.sem_limite else args.max_horas
        resultado = transcrever(args.entrada, args.saida, args.idioma, args.modelo,
                                progresso, args.vocabulario, max_horas)
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
