FROM python:3.12-slim

# O usuário não-root é criado antes do modelo: assim o download já nasce com o
# dono certo e evita um "chown -R" depois, que duplicaria os ~460 MB do modelo
# numa camada nova.
RUN useradd --create-home --shell /bin/bash transcricao

WORKDIR /app

# As dependências entram antes do código: assim uma alteração em app.py não
# invalida a camada de instalação, que é a cara.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV HF_HOME=/app/.cache/huggingface

RUN mkdir -p /app/dados /app/.cache && chown -R transcricao:transcricao /app
USER transcricao

# O modelo é baixado no build para a imagem ficar autocontida: nada de esperar
# centenas de MB na primeira transcrição. Fica antes do COPY do código para que
# alterações em app.py não refaçam este download.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

COPY --chown=transcricao:transcricao . .

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health').read()" || exit 1

# Todas as flags são necessárias:
#   --server.address=0.0.0.0     sem isso o Streamlit escuta só em localhost DENTRO
#                                do container e o mapeamento de porta não funciona
#   --server.headless=true       evita abrir navegador e o prompt de e-mail inicial
#   --browser.gatherUsageStats   desliga a telemetria
#   --server.maxUploadSize=256   o default de 200 MB nao cobre um video de reuniao
#                                longa; 256 MB cobre com folga (uma aula de 37 min
#                                tem 35 MB) sem virar munição para exaurir a máquina.
#                                O teto de DURAÇÃO fica em audioTranscricao.py: o
#                                tamanho do arquivo não limita o áudio decodificado.
CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.port=8501", \
     "--browser.gatherUsageStats=false", \
     "--server.maxUploadSize=256"]
