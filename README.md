# Transcrição de Áudio

Transcreve arquivos de áudio e vídeo para texto usando o Google Speech Recognition,
com interface web (Streamlit) e linha de comando. A transcrição pode ser revisada
na tela antes de ser exportada em `.txt` ou `.pdf`.

Áudios longos são enviados ao Google em blocos, porque o endpoint gratuito rejeita
arquivos grandes. Uma falha de rede num bloco não descarta os já transcritos: o
bloco é repetido uma vez e, persistindo o erro, a tela avisa que o texto está
incompleto.

## Com Docker (recomendado)

Sobe a interface em http://localhost:8501:

```bash
docker compose up -d
```

Para acompanhar os logs e derrubar:

```bash
docker compose logs -f
docker compose down
```

A imagem inclui o `ffmpeg`, necessário para converter mp3, m4a, mp4 e afins em WAV.
O limite de upload é de 1 GB (o padrão do Streamlit, 200 MB, não cobre um vídeo de
reunião longa).

### CLI dentro do container

A pasta `./dados` do projeto é montada em `/app/dados` no container. Coloque os
arquivos ali e chame a CLI:

```bash
docker compose run --rm transcricao python audioTranscricao.py dados/reuniao.mp4
```

O resultado é gravado em `transcricao_audio.txt`, dentro do container. Para que ele
apareça no host, aponte a saída para a pasta montada:

```bash
docker compose run --rm transcricao \
  python audioTranscricao.py dados/reuniao.mp4 -o dados/reuniao.txt
```

## Sem Docker

Requer Python 3.12+ e o `ffmpeg` no PATH (ou o pacote `imageio-ffmpeg`, instalado
junto com o moviepy).

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Interface web:

```bash
streamlit run app.py
```

Linha de comando:

```bash
python audioTranscricao.py meu_audio.mp3
python audioTranscricao.py reuniao.mp4 -o ata.txt -l en-US -b 30
```

| Argumento | Descrição | Padrão |
|---|---|---|
| `entrada` | arquivo de áudio ou vídeo | `audio1.wav` ao lado do script |
| `-o`, `--saida` | arquivo `.txt` de saída | `transcricao_audio.txt` |
| `-l`, `--idioma` | idioma do áudio (`en-US`, `es-ES`, ...) | `pt-BR` |
| `-b`, `--bloco` | segundos por bloco enviado ao Google | `50` |

Sai com código 1 em caso de erro.

## Formatos aceitos

`mp3`, `wav`, `m4a`, `ogg`, `flac`, `aiff`, `mp4`, `mkv`, `avi`, `mov`.

Entradas que não sejam WAV/AIFF/FLAC são convertidas automaticamente para WAV mono
16 kHz antes do reconhecimento.

## Arquivos

| Arquivo | Papel |
|---|---|
| `app.py` | interface Streamlit |
| `audioTranscricao.py` | transcrição e CLI |
| `gerar_pdf.py` | exportação do texto revisado em PDF |
