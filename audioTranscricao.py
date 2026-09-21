"""Transcreve áudio (ou a trilha de um vídeo) para texto usando o faster-whisper, local."""

import argparse
import collections
import functools
import math
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
# antes de transcrever, e só então expõe a duração. Isso torna a duração inútil
# como defesa: a memória já foi gasta. Um Opus com 2 h de áudio ocupa 2,7 MB em
# disco e vira 461 MB de float32 -- 170x --, com pico de 1.209 MB no processo. O
# teto abaixo é aplicado por nós, durante a decodificação, contando amostras.
#
# Custo do teto padrão: 4 h = 230,4 M amostras = 461 MB em s16 e 922 MB em
# float32. O pico transitório da conversão fica em ~1,4 GB. Abaixe
# TRANSCRICAO_MAX_HORAS numa maquina apertada.
LIMITE_HORAS_PADRAO = 4.0
VARIAVEL_LIMITE = 'TRANSCRICAO_MAX_HORAS'
VARIAVEL_LIMITE_MINUTOS = 'TRANSCRICAO_MAX_MINUTOS'

# Folga na comparação com o teto. O teto é anunciado em minutos inteiros e as
# durações aparecem em mm:ss, mas a comparação é em ponto flutuante contra o que
# o arquivo declara -- e todo encoder mp3/aac acrescenta padding no fim. Um corte
# de exatos 20 min exportado em mp3 chega aqui com 1200,000979 s e era recusado
# por UM MILISSEGUNDO, com a mensagem dizendo "tem 20 min, acima do limite de
# 20 min". Um segundo de folga custa 16 k amostras (32 KB) e elimina essa classe
# inteira de recusa, em que o arquivo é do tamanho anunciado e mesmo assim volta.
TOLERANCIA_LIMITE_SEGUNDOS = 1.0

# O modelo pré-selecionado também é configurável: a mesma imagem serve a máquina
# pessoal e uma demo pública, que roda em CPU compartilhada e pede um modelo mais
# leve. Veja modelo_padrao().
VARIAVEL_MODELO = 'TRANSCRICAO_MODELO'

# Quais modelos podem ser ESCOLHIDOS, que é diferente de qual vem pré-selecionado.
# Numa demo pública os grandes precisam sair da lista: `medium` e `large-v3` nem
# estão na imagem (o Dockerfile embute só `base` e `small`), então escolhê-los
# dispararia um download de 1,5 GB ou 3 GB para disco efêmero no meio da
# transcrição. Veja modelos_disponiveis().
VARIAVEL_MODELOS = 'TRANSCRICAO_MODELOS'

# Marca que a execução é uma demo pública, para as mensagens de erro falarem a
# língua de quem está lá: quem abre a demo não tem shell, não define variável de
# ambiente e não conhece as opções da linha de comando. É genérica de propósito
# -- quem a define é o entrypoint, e o motor não precisa saber em que provedor
# está rodando. Veja _mensagem_limite().
VARIAVEL_DEMO = 'TRANSCRICAO_DEMO'

# Para onde a demo manda quem esbarrou num limite dela.
URL_PROJETO = 'https://github.com/mvaraujo1977/transcricaoAudio'

# O Whisper trabalha internamente a 16 kHz mono; decodificar direto nesse
# formato evita uma reamostragem depois.
TAXA_WHISPER = 16000

# As duas fases que o callback de progresso distingue. A decodificação vem antes
# da transcrição e pode levar dezenas de segundos num arquivo longo; sem avisar
# dela, quem espera não vê nada acontecer -- e, na interface, o botão de cancelar
# fica sem resposta, porque o Streamlit só processa o clique quando o script
# passa por uma chamada dele.
FASE_PREPARO = 'preparo'
FASE_TRANSCRICAO = 'transcricao'

# Entre as duas há uma terceira, curta e cega: o faster-whisper roda a detecção
# de voz e monta o espectrograma DENTRO do transcribe(), antes de devolver o
# gerador, sem passar por nenhuma chamada de quem o chamou. Medido com `base`:
# 1,9 s para 5 min de áudio e 7,0 s para 20 min -- cresce com a duração. Nessa
# janela o cancelamento não tem como responder; o aviso abaixo existe para a tela
# ao menos dizer o que está acontecendo, em vez de parecer travada no fim do
# preparo. Vale poucos segundos: o teto de 20 min inteiro sai em ~2,5 min na CPU
# do Space (veja docs/DEPLOY.md), então esta fase é uma fração pequena da espera.
FASE_ANALISE = 'analise'

# Um aviso de progresso a cada minuto de áudio decodificado. A decodificação
# corre bem mais rápido que o tempo real (minutos de áudio por segundo), então
# isso dá alguns avisos por segundo: o suficiente para o cancelamento responder
# sem encher a tela de atualizações.
INTERVALO_PREPARO = 60.0

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
    """Áudio mais longo que o teto configurado.

    Herda de ValueError para ser capturada pelo mesmo `except` que já trata os
    demais erros de entrada, na CLI e na interface.
    """


def _duracao_legivel(segundos):
    """Formata uma duração para mensagem de erro, sem virar '0.0 h'."""
    if segundos < 3600:
        return "{0:.0f} min".format(segundos / 60.0)
    return "{0:.1f} h".format(segundos / 3600.0)


def _duracao_exata(segundos):
    """A mesma duração em h:mm:ss, para quando a forma arredondada não serve.

    É a forma que a tela já usa em toda parte, e a única que distingue um áudio
    de 20:01 de um teto de 20:00 -- em minutos arredondados os dois viram
    "20 min", e a mensagem sai dizendo que 20 min está acima de 20 min.
    """
    total = int(round(segundos))
    if total >= 3600:
        return "{0}:{1:02d}:{2:02d}".format(total // 3600, (total % 3600) // 60,
                                            total % 60)
    return "{0}:{1:02d}".format(total // 60, total % 60)


def em_demo():
    """Diz se esta execução é a demo pública, conforme TRANSCRICAO_DEMO.

    Quem liga a marca é o entrypoint; o motor não precisa saber em que provedor
    está. Serve às mensagens de erro e à tela, que dizem coisas diferentes para
    quem roda na própria máquina e para quem abre um link público -- em especial
    sobre para onde o áudio vai, que é o ponto em que os dois casos divergem de
    verdade.
    """
    return bool((os.environ.get(VARIAVEL_DEMO) or '').strip())


def _mensagem_limite(limite_segundos, declarada=None):
    """Monta o texto do DuracaoExcedida conforme quem vai lê.

    A mensagem padrão fala com quem controla a máquina: cita a variável de
    ambiente e a opção da linha de comando. Numa demo pública nada disso existe
    para o visitante -- ele não tem shell nem acesso ao container --, e mandá-lo
    "aumentar TRANSCRICAO_MAX_HORAS" é um beco sem saída. Lá a saída é outra:
    dizer que o teto é da demo e apontar onde rodar o projeto sem esse teto.
    """
    if declarada is not None:
        # Arredondadas para minutos, uma duração logo acima do teto sai idêntica
        # a ele. Nesse caso as duas passam para h:mm:ss, senão a frase se
        # contradiz -- "tem 20 min, acima do limite de 20 min".
        texto_declarada = _duracao_legivel(declarada)
        texto_limite = _duracao_legivel(limite_segundos)
        if texto_declarada == texto_limite:
            texto_declarada = _duracao_exata(declarada)
            texto_limite = _duracao_exata(limite_segundos)
        abertura = "O áudio tem {0}, acima do limite de {1}".format(
            texto_declarada, texto_limite)
    else:
        abertura = "O áudio passa do limite de {0}".format(
            _duracao_legivel(limite_segundos))

    if em_demo():
        return ("{0} desta demo pública. Para transcrever um arquivo maior, rode "
                "o projeto na sua própria máquina, onde o teto é configurável: "
                "{1}".format(abertura, URL_PROJETO))

    return ("{0}. Aumente {1} ou use --sem-limite na linha de comando se o "
            "arquivo for seu.".format(abertura, VARIAVEL_LIMITE))


def _numero_positivo(bruto, variavel, unidade):
    """Converte o valor de uma variável de ambiente, exigindo número > 0."""
    try:
        valor = float(bruto)
    except ValueError:
        raise ValueError("{0} precisa ser um número em {1}; veio {2!r}".format(
            variavel, unidade, bruto))
    if valor <= 0:
        raise ValueError("{0} precisa ser maior que zero; veio {1!r}".format(
            variavel, bruto))
    return valor


def limite_horas():
    """Teto de duração em horas.

    Configurável por TRANSCRICAO_MAX_HORAS ou, quando o teto é curto demais para
    ser escrito em horas -- uma demo pública com 20 min, por exemplo --, por
    TRANSCRICAO_MAX_MINUTOS, que tem precedência.
    """
    minutos = os.environ.get(VARIAVEL_LIMITE_MINUTOS)
    if minutos and minutos.strip():
        return _numero_positivo(minutos, VARIAVEL_LIMITE_MINUTOS, 'minutos') / 60.0

    horas = os.environ.get(VARIAVEL_LIMITE)
    if not horas or not horas.strip():
        return LIMITE_HORAS_PADRAO
    return _numero_positivo(horas, VARIAVEL_LIMITE, 'horas')


def modelos_disponiveis():
    """Modelos que a tela e a CLI oferecem, configurável por TRANSCRICAO_MODELOS.

    Recebe uma lista separada por vírgula e devolve os nomes válidos na ordem de
    MODELOS -- do mais leve ao mais pesado --, que é a ordem que a tela mostra.
    Nomes desconhecidos são descartados, e uma lista que não sobre nada válido
    cai no conjunto completo: uma variável mal escrita não pode deixar a
    aplicação sem nenhum modelo para escolher.

    Restringir a lista é o que uma demo pública precisa e uma instalação pessoal
    não: veja o comentário de VARIAVEL_MODELOS.
    """
    bruto = (os.environ.get(VARIAVEL_MODELOS) or '').strip()
    if not bruto:
        return MODELOS
    pedidos = {nome.strip() for nome in bruto.split(',') if nome.strip()}
    validos = tuple(nome for nome in MODELOS if nome in pedidos)
    return validos or MODELOS


def modelo_padrao():
    """Modelo pré-selecionado na tela e na CLI, configurável por TRANSCRICAO_MODELO.

    Existe para a mesma imagem servir a máquina pessoal, onde o `small` compensa,
    e uma demo em CPU compartilhada, onde ele deixa a espera longa demais. Valor
    fora de MODELOS é ignorado: qual modelo está valendo fica visível na tela, e
    derrubar a aplicação por causa de uma variável mal escrita seria pior.

    O resultado é sempre um item de modelos_disponiveis(), porque a tela procura
    o padrão dentro da lista que oferece para achar o índice inicial: um padrão
    fora dela seria um ValueError na abertura da página.
    """
    disponiveis = modelos_disponiveis()
    escolhido = (os.environ.get(VARIAVEL_MODELO) or '').strip()
    if escolhido in disponiveis:
        return escolhido
    if MODELO_PADRAO in disponiveis:
        return MODELO_PADRAO
    return disponiveis[0]


def sondar_duracao(caminho):
    """Duração declarada no arquivo, em segundos, sem decodificar nada.

    Custa milissegundos: lê só o cabeçalho do container. Devolve None quando o
    formato não declara duração. O valor vem do arquivo, ou seja, de quem o
    enviou -- serve para recusar cedo o caso óbvio, nunca como única defesa.
    """
    with av.open(caminho) as container:
        if container.duration is not None:
            return float(container.duration) / av.time_base
        for trilha in container.streams.audio:
            if trilha.duration is not None and trilha.time_base:
                return float(trilha.duration * trilha.time_base)
    return None


def decodificar_audio(caminho, limite_segundos, progresso=None, total_estimado=None):
    """Decodifica para float32 mono 16 kHz, abortando ao passar do teto.

    Este é o portão que de fato fecha: conta amostras durante a decodificação e
    para no instante em que o teto é ultrapassado, sem depender do cabeçalho.
    Um arquivo que minta sobre a própria duração é interrompido do mesmo jeito.

    O formato de saída (float32 normalizado a partir de s16) é idêntico ao que
    o faster_whisper.audio.decode_audio produz, para a transcrição não mudar.

    `progresso`, quando informado, é chamado a cada INTERVALO_PREPARO segundos de
    áudio lidos como progresso(segundos_lidos, total_estimado, FASE_PREPARO).
    `total_estimado` é a duração declarada no cabeçalho, que pode ser mentira ou
    não existir -- serve para a barra, nunca como limite; quem limita é a
    contagem de amostras abaixo.
    """
    # --sem-limite chega aqui como infinito, que não vira int: nesse caso não há
    # teto a comparar e a contagem serve só para saber se veio algum áudio.
    maximo = (int((limite_segundos + TOLERANCIA_LIMITE_SEGUNDOS) * TAXA_WHISPER)
              if math.isfinite(limite_segundos) else None)
    resampler = av.AudioResampler(format='s16', layout='mono', rate=TAXA_WHISPER)
    blocos = []
    total = 0
    proximo_aviso = INTERVALO_PREPARO

    def acumular(quadros):
        nonlocal total, proximo_aviso
        for convertido in quadros or []:
            bloco = convertido.to_ndarray().reshape(-1)
            total += bloco.shape[0]
            if maximo is not None and total > maximo:
                raise DuracaoExcedida(_mensagem_limite(limite_segundos))
            blocos.append(bloco)
            segundos = total / float(TAXA_WHISPER)
            if progresso is not None and segundos >= proximo_aviso:
                progresso(segundos, total_estimado, FASE_PREPARO)
                proximo_aviso = segundos + INTERVALO_PREPARO

    with av.open(caminho) as container:
        if not container.streams.audio:
            raise RuntimeError("O arquivo não tem trilha de áudio")
        for quadro in container.decode(audio=0):
            quadro.pts = None
            acumular(resampler.resample(quadro))
        acumular(resampler.resample(None))

    if not blocos:
        raise RuntimeError("Não foi possível decodificar áudio do arquivo")

    amostras = np.concatenate(blocos)
    blocos.clear()  # libera os pedaços antes de alocar o float32, que é o dobro
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
                progresso=None, vocabulario=None, max_horas=None, ao_segmento=None):
    """Transcreve `caminho` e devolve um Transcricao.

    `progresso`, quando informado, é chamado como
    progresso(segundos_processados, duracao_total, fase): durante o preparo, a
    cada trecho decodificado, com fase=FASE_PREPARO; depois, a cada segmento
    reconhecido, com fase=FASE_TRANSCRICAO.

    `ao_segmento`, quando informado, recebe cada Segmento assim que ele fica
    pronto. Serve para quem precisa guardar o trabalho parcial: se a chamada for
    interrompida no meio, o que já saiu continua nas mãos de quem chamou.

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
    if declarada is not None and declarada > limite_segundos + TOLERANCIA_LIMITE_SEGUNDOS:
        raise DuracaoExcedida(_mensagem_limite(limite_segundos, declarada))

    audio = decodificar_audio(caminho, limite_segundos, progresso=progresso,
                              total_estimado=declarada)

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
    #
    # O aviso vem ANTES da chamada porque é a última oportunidade: veja
    # FASE_ANALISE. Também é o último ponto em que um cancelamento pedido durante
    # a decodificação ainda é processado sem esperar a detecção de voz terminar.
    if progresso is not None:
        progresso(0.0, None, FASE_ANALISE)

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
        pronto = Segmento(segmento.start, segmento.end, segmento.text)
        segmentos.append(pronto)
        if ao_segmento is not None:
            ao_segmento(pronto)
        if progresso is not None:
            progresso(min(segmento.end, info.duration), info.duration, FASE_TRANSCRICAO)

    if not segmentos:
        raise RuntimeError("Nenhuma fala foi reconhecida no arquivo")

    texto = '\n\n'.join(agrupar_em_paragrafos(segmentos))

    if text_output_path is not None:
        with open(text_output_path, 'w', encoding='utf-8') as arquivo:
            arquivo.write(texto)
        print("Transcrição salva em: {0}".format(text_output_path))

    if progresso is not None:
        progresso(info.duration, info.duration, FASE_TRANSCRICAO)

    return Transcricao(texto, segmentos, info.duration, info.language)


def transcribe_audio_to_text(audio_path, text_output_path=None, idioma="pt-BR",
                             modelo=MODELO_PADRAO, progresso=None, vocabulario=None,
                             max_horas=None, ao_segmento=None):
    """Alias mantido para não quebrar importações existentes."""
    return transcrever(audio_path, text_output_path, idioma, modelo, progresso,
                       vocabulario, max_horas, ao_segmento)


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
    parser.add_argument('-m', '--modelo', default=modelo_padrao(),
                        choices=modelos_disponiveis(),
                        help="modelo Whisper: maiores são mais precisos e mais lentos "
                             "(padrão: {0}, ou {1})".format(modelo_padrao(), VARIAVEL_MODELO))
    parser.add_argument('-v', '--vocabulario', default=None,
                        help="termos e siglas do domínio, para o modelo acertar o jargão")
    parser.add_argument('--max-horas', type=float, default=None, metavar='H',
                        help="teto de duração em horas (padrão: {0:g}, ou {1})".format(
                            LIMITE_HORAS_PADRAO, VARIAVEL_LIMITE))
    parser.add_argument('--sem-limite', action='store_true',
                        help="desliga o teto de duração; use só em arquivo de origem confiável")
    args = parser.parse_args(argv)

    def progresso(processado, total, fase=FASE_TRANSCRICAO):
        if fase == FASE_PREPARO:
            print("\r  preparando: {0} lidos".format(_mmss(processado)),
                  end='', file=sys.stderr)
        elif fase == FASE_ANALISE:
            print("\r  detectando as falas...          ", end='', file=sys.stderr)
        elif total:
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
