#!/bin/sh
# Monta a linha de comando do Streamlit a partir do ambiente, para a MESMA imagem
# servir a instalação pessoal e uma demo pública. Nada aqui é específico de um
# provedor além do bloco marcado, e todos os valores podem ser sobrescritos por
# variável de ambiente antes de o container subir.
set -e

PORTA="${PORT:-8501}"
UPLOAD="${TRANSCRICAO_MAX_UPLOAD_MB:-256}"
EXTRA=""

if [ -n "$SPACE_ID" ]; then
    # Hugging Face Spaces define SPACE_ID em todo container que roda lá. O que
    # muda aqui é só o que a demo pública exige, e cada valor cede a uma variável
    # de ambiente explícita (`:=` só atribui quando a variável está vazia):
    #
    # - modelo `base`: em 2 vCPU compartilhadas o `small` deixa a espera longa
    #   demais para uma demo; ele continua selecionável na tela.
    # - teto de 5 min: ninguém espera mais que isso numa demo, e um teto de 4 h
    #   numa página pública é convite a abuso.
    # - upload de 50 MB: cobre um áudio de 5 min com folga.
    : "${TRANSCRICAO_MODELO:=base}"
    : "${TRANSCRICAO_MAX_MINUTOS:=5}"
    UPLOAD="${TRANSCRICAO_MAX_UPLOAD_MB:-50}"
    export TRANSCRICAO_MODELO TRANSCRICAO_MAX_MINUTOS

    # O Streamlit protege contra XSRF com cookie, e o cookie não sobrevive ao
    # iframe em que o Spaces serve a aplicação: com a proteção ligada, o
    # st.file_uploader simplesmente não funciona lá. Desligar vale para a demo,
    # que é pública e sem sessão a proteger, e NÃO vale para a instalação local,
    # onde a proteção continua ligada porque esta linha não roda.
    EXTRA="--server.enableXsrfProtection=false --server.enableCORS=false"
fi

exec streamlit run app.py \
    --server.address=0.0.0.0 \
    --server.port="$PORTA" \
    --server.headless=true \
    --browser.gatherUsageStats=false \
    --server.maxUploadSize="$UPLOAD" \
    $EXTRA
