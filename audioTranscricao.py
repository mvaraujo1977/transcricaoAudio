"""Transcreve áudio (ou a trilha de um vídeo) para texto usando o Google Speech Recognition."""

import argparse
import contextlib
import os
import sys
import tempfile

import speech_recognition as sr

# Extensões que o speech_recognition lê diretamente; as demais são convertidas.
FORMATOS_NATIVOS = {'.wav', '.aiff', '.aifc', '.flac'}

# O endpoint gratuito do Google rejeita/trunca áudios longos, então o arquivo
# é enviado em blocos e as transcrições são concatenadas.
DURACAO_BLOCO_PADRAO = 50


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


def transcrever_blocos(recognizer, source, idioma, duracao_bloco):
    """Percorre o áudio em blocos e devolve a lista de trechos transcritos."""
    trechos = []
    offset = 0.0
    total = source.DURATION or 0.0

    while True:
        audio = recognizer.record(source, duration=duracao_bloco)
        if not audio.frame_data:
            break
        try:
            trechos.append(recognizer.recognize_google(audio, language=idioma))
        except sr.UnknownValueError:
            print("Aviso: trecho a partir de {0:.0f}s não foi compreendido".format(offset), file=sys.stderr)
        offset += duracao_bloco
        if total and offset >= total:
            break

    return trechos


def transcribe_audio_to_text(audio_path, text_output_path, idioma="pt-BR",
                             duracao_bloco=DURACAO_BLOCO_PADRAO):
    """Transcreve `audio_path` e grava o resultado em `text_output_path`."""
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
        trechos = transcrever_blocos(recognizer, source, idioma, duracao_bloco)

    if not trechos:
        raise RuntimeError("Nenhum trecho do áudio pôde ser transcrito")

    texto = ' '.join(trechos)
    with open(text_output_path, 'w', encoding='utf-8') as arquivo:
        arquivo.write(texto)

    print("Transcrição salva em: {0}".format(text_output_path))
    return texto


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
        transcribe_audio_to_text(args.entrada, args.saida, args.idioma, args.bloco)
    except sr.RequestError as erro:
        print("Erro ao consultar o serviço do Google: {0}".format(erro), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as erro:
        print("Erro: {0}".format(erro), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
