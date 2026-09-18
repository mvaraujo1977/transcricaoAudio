FROM python:3.12-slim

# O moviepy precisa do ffmpeg para converter mp3/m4a/mp4 em WAV. O binário do
# imageio-ffmpeg costuma bastar, mas depurar essa falha dentro do container é
# pior do que carregar os ~100 MB do pacote do sistema.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# As dependências entram antes do código: assim uma alteração em app.py não
# invalida a camada de instalação, que é a cara.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# O app roda sem privilégios; /app/dados é o ponto de montagem do volume.
RUN useradd --create-home --shell /bin/bash transcricao \
    && mkdir -p /app/dados \
    && chown -R transcricao:transcricao /app
USER transcricao

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health').read()" || exit 1

# Todas as flags são necessárias:
#   --server.address=0.0.0.0     sem isso o Streamlit escuta só em localhost DENTRO
#                                do container e o mapeamento de porta não funciona
#   --server.headless=true       evita abrir navegador e o prompt de e-mail inicial
#   --browser.gatherUsageStats   desliga a telemetria
#   --server.maxUploadSize=1024  o default de 200 MB não cobre um vídeo de reunião
CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.port=8501", \
     "--browser.gatherUsageStats=false", \
     "--server.maxUploadSize=1024"]
