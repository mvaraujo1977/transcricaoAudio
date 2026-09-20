# Transcrição de Áudio

Transcreve arquivos de áudio e vídeo para texto usando o [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
que roda **localmente** — nada é enviado para serviços externos. Tem interface web
(Streamlit) e linha de comando, e o texto pode ser revisado na tela antes de ser
exportado em `.txt` ou `.pdf`.

A saída vem com pontuação, capitalização e parágrafos, além de timestamps por
segmento, que permitem marcar cada parágrafo do PDF com `[MM:SS]` para voltar ao
ponto exato do áudio.

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

### Acesso pela rede

A porta é publicada em `127.0.0.1:8501:8501`, ou seja, **a tela só abre na própria
máquina**. Isso é deliberado: a aplicação não tem autenticação nenhuma, e sem o
prefixo `127.0.0.1` o Docker escuta em todas as interfaces — em wifi de café ou de
hotel, qualquer um no mesmo segmento abriria a interface, enviaria arquivos e
consumiria a CPU da máquina.

Para alcançar a tela de outro aparelho da LAN, troque em `docker-compose.yml`:

```yaml
    ports:
      - "8501:8501"      # escuta em todas as interfaces
```

Faça isso apenas em rede confiável e sabendo que **não há login**: quem alcança a
porta tem acesso completo. Para uso legítimo fora da máquina, o caminho seguro é um
túnel SSH, que dispensa expor a porta:

```bash
ssh -L 8501:127.0.0.1:8501 usuario@maquina
```

O `--server.address=0.0.0.0` do `Dockerfile` é outra coisa e deve continuar como
está: ele é o bind *dentro* do container, sem o qual o mapeamento de porta não
funciona. Quem controla a exposição no host é só a linha `ports`.

O modelo `small` já vem embutido na imagem, então a primeira transcrição não
espera download nenhum e o container funciona sem rede. O limite de upload é de
1 GB (o padrão do Streamlit, 200 MB, não cobre um vídeo de reunião longa).

### CLI dentro do container

A pasta `./dados` do projeto é montada em `/app/dados`. Coloque os arquivos ali:

```bash
docker compose run --rm transcricao \
  python audioTranscricao.py dados/aula.mp3 -o dados/aula.txt
```

Apontar a saída para `dados/` faz o `.txt` aparecer no host.

## Sem Docker

Requer Python 3.12+. Não é necessário ter ffmpeg instalado: o faster-whisper
decodifica mp3, mp4, mkv e afins via PyAV, que traz os próprios codecs.

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
python audioTranscricao.py aula.mp3
python audioTranscricao.py reuniao.mp4 -o ata.txt -l en-US -m medium
```

| Argumento | Descrição | Padrão |
|---|---|---|
| `entrada` | arquivo de áudio ou vídeo | `audio1.wav` ao lado do script |
| `-o`, `--saida` | arquivo `.txt` de saída | `transcricao_audio.txt` |
| `-l`, `--idioma` | idioma do áudio (`en-US`, `es-ES`, ...) | `pt-BR` |
| `-m`, `--modelo` | `tiny`, `base`, `small`, `medium`, `large-v3` | `small` |
| `-v`, `--vocabulario` | termos e siglas do domínio, para o modelo acertar o jargão | nenhum |

Sai com código 1 em caso de erro.

Na primeira execução fora do Docker, o modelo escolhido é baixado para o cache do
Hugging Face (`~/.cache/huggingface`) — são centenas de MB.

## Escolha do modelo

| Modelo | Download | Precisão | Velocidade |
|---|---|---|---|
| `tiny` | ~75 MB | baixa | muito rápida |
| `base` | ~145 MB | razoável | rápida |
| `small` | ~480 MB | boa | ~1,6x o tempo real em CPU |
| `medium` | ~1,5 GB | alta | várias vezes mais lenta |
| `large-v3` | ~3 GB | melhor | mais lenta ainda |

Modelos maiores acertam mais jargão, siglas e nomes próprios. Se termos do seu
domínio saírem errados, subir de `small` para `medium` costuma resolver.

## Formatos aceitos

`mp3`, `wav`, `m4a`, `ogg`, `flac`, `aiff`, `mp4`, `mkv`, `avi`, `mov`.

## Medindo a qualidade de uma transcrição

`verificar_transcricao.py` transcreve um arquivo e relata contagem de palavras,
pontuação, parágrafos, presença de termos do domínio e repetições em loop:

```bash
python verificar_transcricao.py dados/aula.mp3 small
```

## Arquivos

| Arquivo | Papel |
|---|---|
| `app.py` | interface Streamlit |
| `audioTranscricao.py` | motor de transcrição e CLI |
| `gerar_pdf.py` | exportação do texto revisado em PDF |
| `verificar_transcricao.py` | métricas de qualidade da transcrição |
