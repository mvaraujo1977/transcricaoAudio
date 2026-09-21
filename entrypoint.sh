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
    # - lista restrita a `base` e `small`: são os dois que o Dockerfile embute.
    #   `medium` e `large-v3` no seletor seriam um download de 1,5 GB ou 3 GB
    #   para o disco efêmero do Space, disparado no meio da transcrição, e
    #   depois dezenas de minutos de espera num teto de 20 min de áudio.
    # - teto de 20 min: o que uma aula ou reunião curta ocupa, e ainda dentro do
    #   que a CPU compartilhada entrega numa espera tolerável. Um teto de 4 h
    #   numa página pública é convite a abuso.
    # - upload de 100 MB: cobre 20 min de mp3/m4a com folga. Não cobre 20 min de
    #   `.wav` 44,1 kHz estéreo (~211 MB), que bate neste teto antes do de
    #   duração -- por isso a tela anuncia os dois.
    # - marca de demo: muda a mensagem do limite de duração, que no padrão manda
    #   ajustar variável de ambiente e usar --sem-limite -- nada que o visitante
    #   de uma página pública possa fazer.
    : "${TRANSCRICAO_MODELO:=base}"
    : "${TRANSCRICAO_MODELOS:=base,small}"
    : "${TRANSCRICAO_MAX_MINUTOS:=20}"
    : "${TRANSCRICAO_DEMO:=1}"
    UPLOAD="${TRANSCRICAO_MAX_UPLOAD_MB:-100}"
    export TRANSCRICAO_MODELO TRANSCRICAO_MODELOS TRANSCRICAO_MAX_MINUTOS TRANSCRICAO_DEMO

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
