FROM python:3.12-slim

# O usuário não-root é criado antes do modelo: assim o download já nasce com o
# dono certo e evita um "chown -R" depois, que duplicaria os ~460 MB do modelo
# numa camada nova.
RUN useradd --create-home --shell /bin/bash transcricao

WORKDIR /app

# As dependências entram antes do código: assim uma alteração em app.py não
# invalida a camada de instalação, que é a cara.
#
# Instala o .lock, não o requirements.txt: este último só traz pisos (>=1.0) e
# cada build resolveria para o que estivesse no PyPI naquele dia -- build não
# reproduzível, e uma versão comprometida de qualquer dependência transitiva
# entraria sem aviso. O lock é gerado dentro desta mesma imagem; veja o README.
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt

ENV HF_HOME=/app/.cache/huggingface

RUN mkdir -p /app/dados /app/.cache && chown -R transcricao:transcricao /app
USER transcricao

# Os modelos são baixados no build para a imagem ficar autocontida: nada de
# esperar centenas de MB na primeira transcrição. Fica antes do COPY do código
# para que alterações em app.py não refaçam este download.
#
# São dois porque a mesma imagem serve os dois cenários sem baixar nada em tempo
# de execução: `small` na máquina pessoal e `base` numa demo em CPU
# compartilhada, onde o small demora demais. Em plataforma de disco efêmero
# (Hugging Face Spaces, por exemplo) isso é obrigatório: o que for baixado
# depois some no primeiro reinício.
RUN python -c "from faster_whisper import WhisperModel;     WhisperModel('small', device='cpu', compute_type='int8');     WhisperModel('base', device='cpu', compute_type='int8')"

COPY --chown=transcricao:transcricao . .

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health').read()" || exit 1

# A linha do Streamlit é montada pelo entrypoint, que lê o ambiente. As flags
# fixas valem sempre: `--server.address=0.0.0.0` (sem isso o Streamlit escuta só
# no localhost DENTRO do container e o mapeamento de porta não funciona),
# `--server.headless=true` (não abre navegador nem pede e-mail) e a telemetria
# desligada. O que muda entre a instalação pessoal e uma demo pública -- teto de
# upload, modelo padrão, teto de duração e a proteção XSRF -- sai de variável de
# ambiente, e o entrypoint documenta cada caso.
#
# `sh entrypoint.sh` em vez de executá-lo direto: o repositório é editado no
# Windows, que não guarda o bit de execução.
#
# O teto de DURAÇÃO continua em audioTranscricao.py: o tamanho do arquivo não
# limita o áudio decodificado.
CMD ["sh", "/app/entrypoint.sh"]
