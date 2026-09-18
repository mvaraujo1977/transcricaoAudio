"""Transcreve áudio (ou a trilha de um vídeo) para texto usando o Google Speech Recognition."""

import argparse
import collections
import contextlib
import os
import sys
import tempfile
import time

import speech_recognition as sr

# Extensões que o speech_recognition lê diretamente; as demais são convertidas.
FORMATOS_NATIVOS = {'.wav', '.aiff', '.aifc', '.flac'}

# O endpoint gratuito do Google rejeita/trunca áudios longos, então o arquivo
# é enviado em blocos e as transcrições são concatenadas.
DURACAO_BLOCO_PADRAO = 50

# Pausa antes de repetir um bloco que falhou por erro de rede/serviço.
PAUSA_NOVA_TENTATIVA = 2

# Blocos sem fala reconhecível são normais (silêncio, ruído); blocos perdidos por
# falha de rede indicam transcrição incompleta. Os dois são contados à parte.
BlocosTranscritos = collections.namedtuple(
    'BlocosTranscritos', 'trechos blocos_falhados blocos_sem_fala')

Transcricao = collections.namedtuple(
    'Transcricao', 'texto blocos_falhados blocos_sem_fala')


def _carregar_moviepy():
    """Importa o moviepy tratando a mudança de API entre a 1.x e a 2.x."""
    try:
        from moviepy import VideoFileClip, AudioFileClip  # moviepy >= 2.0
    except ImportError:
        from moviepy.editor import VideoFileClip, AudioFileClip  # moviepy 1.x
    return VideoFileClip, AudioFileClip


def extract_audio_from_video(video_path, audio_path):
    """Extrai a trilha de áudio de um vídeo para um arquivo .wav."""
    VideoFileClip, _ = _carregar_moviepy()
    with VideoFileClip(video_path) as video:
        if video.audio is None:
            raise ValueError("O vídeo '{0}' não possui trilha de áudio".format(video_path))
        video.audio.write_audiofile(audio_path, logger=None)


def converter_para_wav(caminho_entrada, caminho_wav):
    """Converte qualquer mídia suportada pelo ffmpeg em .wav mono 16 kHz."""
    VideoFileClip, AudioFileClip = _carregar_moviepy()
    try:
        clip = AudioFileClip(caminho_entrada)
    except Exception:  # arquivo de vídeo: pega a trilha de áudio
        extract_audio_from_video(caminho_entrada, caminho_wav)
        return
    with clip:
        clip.write_audiofile(caminho_wav, fps=16000, nbytes=2, ffmpeg_params=['-ac', '1'], logger=None)


def _reconhecer_bloco(recognizer, audio, idioma, offset):
    """Envia um bloco ao Google e devolve (texto, motivo_da_falha).

    Uma falha de rede não aborta mais a transcrição inteira: o bloco é repetido
    uma vez e, persistindo o erro, vira apenas um aviso, para que os blocos já
    transcritos não sejam perdidos.
    """
    for tentativa in (1, 2):
        try:
            return recognizer.recognize_google(audio, language=idioma), None
        except sr.UnknownValueError:
            print("Aviso: trecho a partir de {0:.0f}s não foi compreendido".format(offset),
                  file=sys.stderr)
            return None, 'sem_fala'
        except sr.RequestError as erro:
            if tentativa == 1:
                time.sleep(PAUSA_NOVA_TENTATIVA)
                continue
            print("Aviso: trecho a partir de {0:.0f}s perdido por falha no serviço: {1}".format(
                offset, erro), file=sys.stderr)
            return None, 'falha'


def transcrever_blocos(recognizer, source, idioma, duracao_bloco, progresso=None):
    """Percorre o áudio em blocos e devolve um BlocosTranscritos.

    `progresso`, quando informado, é chamado ao fim de cada bloco como
    progresso(segundos_processados, duracao_total).
    """
    trechos = []
    blocos_falhados = 0
    blocos_sem_fala = 0
    offset = 0.0
    total = source.DURATION or 0.0

    while True:
        audio = recognizer.record(source, duration=duracao_bloco)
        if not audio.frame_data:
            break

        texto, motivo = _reconhecer_bloco(recognizer, audio, idioma, offset)
        if texto:
            trechos.append(texto)
        elif motivo == 'falha':
            blocos_falhados += 1
        else:
            blocos_sem_fala += 1

        offset += duracao_bloco
        if progresso is not None:
            progresso(min(offset, total) if total else offset, total)
        if total and offset >= total:
            break

    return BlocosTranscritos(trechos, blocos_falhados, blocos_sem_fala)


def transcribe_audio_to_text(audio_path, text_output_path=None, idioma="pt-BR",
                             duracao_bloco=DURACAO_BLOCO_PADRAO, progresso=None):
    """Transcreve `audio_path` e devolve um Transcricao.

    O resultado só é gravado em disco quando `text_output_path` é informado.
    """
    if not os.path.isfile(audio_path):
        raise FileNotFoundError("Arquivo de áudio não encontrado: {0}".format(audio_path))

    with contextlib.ExitStack() as stack:
        extensao = os.path.splitext(audio_path)[1].lower()
        if extensao not in FORMATOS_NATIVOS:
            temporario = os.path.join(tempfile.mkdtemp(), 'audio_convertido.wav')
            stack.callback(lambda: _remover_silencioso(temporario))
            print("Convertendo '{0}' para WAV...".format(os.path.basename(audio_path)))
            converter_para_wav(audio_path, temporario)
            audio_path = temporario

        recognizer = sr.Recognizer()
        source = stack.enter_context(sr.AudioFile(audio_path))
        blocos = transcrever_blocos(recognizer, source, idioma, duracao_bloco, progresso)

    if not blocos.trechos:
        raise RuntimeError("Nenhum trecho do áudio pôde ser transcrito")

    texto = ' '.join(blocos.trechos)
    if text_output_path is not None:
        with open(text_output_path, 'w', encoding='utf-8') as arquivo:
            arquivo.write(texto)
        print("Transcrição salva em: {0}".format(text_output_path))

    return Transcricao(texto, blocos.blocos_falhados, blocos.blocos_sem_fala)


def _remover_silencioso(caminho):
    with contextlib.suppress(OSError):
        os.remove(caminho)
    with contextlib.suppress(OSError):
        os.rmdir(os.path.dirname(caminho))


def main(argv=None):
    script_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(description="Transcreve um arquivo de áudio ou vídeo para texto.")
    parser.add_argument('entrada', nargs='?', default=os.path.join(script_dir, 'audio1.wav'),
                        help="arquivo de áudio ou vídeo (padrão: audio1.wav ao lado do script)")
    parser.add_argument('-o', '--saida', default=os.path.join(script_dir, 'transcricao_audio.txt'),
                        help="arquivo .txt de saída")
    parser.add_argument('-l', '--idioma', default='pt-BR', help='idioma do áudio (ex.: en-US)')
    parser.add_argument('-b', '--bloco', type=int, default=DURACAO_BLOCO_PADRAO,
                        help="duração de cada bloco enviado ao Google, em segundos")
    args = parser.parse_args(argv)

    try:
        resultado = transcribe_audio_to_text(args.entrada, args.saida, args.idioma, args.bloco)
    except sr.RequestError as erro:
        print("Erro ao consultar o serviço do Google: {0}".format(erro), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as erro:
        print("Erro: {0}".format(erro), file=sys.stderr)
        return 1

    if resultado.blocos_falhados:
        print("Atenção: {0} bloco(s) perdidos por falha no serviço; a transcrição "
              "está incompleta.".format(resultado.blocos_falhados), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
