"""Interface Streamlit para transcrever áudio/vídeo e exportar o texto."""

import contextlib
import io
import os
import tempfile

import speech_recognition as sr
import streamlit as st

from audioTranscricao import DURACAO_BLOCO_PADRAO, transcribe_audio_to_text
from gerar_pdf import transcricao_para_pdf

FORMATOS_ACEITOS = ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aiff', 'mp4', 'mkv', 'avi', 'mov']

IDIOMAS = {
    'Português (Brasil)': 'pt-BR',
    'Português (Portugal)': 'pt-PT',
    'Inglês (EUA)': 'en-US',
    'Espanhol': 'es-ES',
    'Francês': 'fr-FR',
    'Italiano': 'it-IT',
    'Alemão': 'de-DE',
}


def _mmss(segundos):
    """Formata segundos como mm:ss."""
    segundos = int(segundos or 0)
    return "{0:02d}:{1:02d}".format(segundos // 60, segundos % 60)


def _nome_base(nome_arquivo):
    """'reuniao.mp4' -> 'reuniao'."""
    return os.path.splitext(os.path.basename(nome_arquivo or 'transcricao'))[0] or 'transcricao'


def _salvar_upload(upload):
    """Grava o upload num arquivo temporário preservando a extensão original.

    A extensão importa: é por ela que o transcritor decide se precisa converter
    o arquivo para WAV antes de enviá-lo ao reconhecedor.
    """
    sufixo = os.path.splitext(upload.name)[1] or '.wav'
    with tempfile.NamedTemporaryFile(delete=False, suffix=sufixo) as temporario:
        temporario.write(upload.getbuffer())
        return temporario.name


def _executar_transcricao(caminho, idioma, duracao_bloco):
    """Roda a transcrição alimentando a barra de progresso e o painel de status."""
    barra = st.progress(0.0, text="Preparando o áudio...")

    with st.status("Transcrevendo...", expanded=True) as status:
        def progresso(processado, total):
            if total:
                barra.progress(min(processado / total, 1.0),
                               text="{0} de {1}".format(_mmss(processado), _mmss(total)))
                status.update(label="Transcrevendo... {0} de {1}".format(
                    _mmss(processado), _mmss(total)))
            else:
                barra.progress(0.0, text="{0} processados".format(_mmss(processado)))
                status.update(label="Transcrevendo... {0} processados".format(_mmss(processado)))

        resultado = transcribe_audio_to_text(caminho, idioma=idioma,
                                             duracao_bloco=duracao_bloco,
                                             progresso=progresso)
        status.update(label="Transcrição concluída", state="complete")

    barra.progress(1.0, text="Concluído")
    return resultado


def _pdf_em_bytes(texto, nome_origem, idioma):
    """Gera o PDF em memória e devolve os bytes."""
    buffer = io.BytesIO()
    transcricao_para_pdf(texto, buffer, nome_origem=nome_origem, idioma=idioma)
    return buffer.getvalue()


st.set_page_config(page_title="Transcrição de Áudio", page_icon="🎙️", layout="centered")

st.title("🎙️ Transcrição de Áudio")
st.caption("Envie um arquivo de áudio ou vídeo e receba a transcrição em texto, "
           "pronta para revisar e exportar.")

upload = st.file_uploader("Arquivo de áudio ou vídeo", type=FORMATOS_ACEITOS)

with st.expander("Opções avançadas"):
    rotulo_idioma = st.selectbox("Idioma do áudio", list(IDIOMAS), index=0)
    idioma = IDIOMAS[rotulo_idioma]
    duracao_bloco = st.slider(
        "Duração de cada bloco (segundos)", min_value=10, max_value=60,
        value=DURACAO_BLOCO_PADRAO,
        help="O áudio é enviado ao Google em blocos. Blocos menores dão um progresso "
             "mais granular; maiores tendem a preservar melhor o contexto das frases.")

if st.button("Transcrever", type="primary", disabled=upload is None):
    caminho = _salvar_upload(upload)
    try:
        resultado = _executar_transcricao(caminho, idioma, duracao_bloco)
    except sr.RequestError as erro:
        st.error("Erro ao consultar o serviço de reconhecimento do Google: {0}".format(erro))
    except (OSError, ValueError, RuntimeError) as erro:
        st.error("Erro: {0}".format(erro))
    else:
        # Sem o session_state, qualquer interação na tela dispara um rerun e a
        # transcrição (que custou minutos) seria perdida.
        st.session_state['texto_editado'] = resultado.texto
        st.session_state['nome_origem'] = upload.name
        st.session_state['idioma'] = idioma
        st.session_state['blocos_falhados'] = resultado.blocos_falhados
        st.session_state['blocos_sem_fala'] = resultado.blocos_sem_fala
    finally:
        with contextlib.suppress(OSError):
            os.remove(caminho)

if 'texto_editado' in st.session_state:
    st.divider()

    falhados = st.session_state.get('blocos_falhados', 0)
    if falhados:
        st.warning("{0} bloco(s) não puderam ser transcritos por falha no serviço do "
                   "Google. O texto abaixo está incompleto.".format(falhados))

    sem_fala = st.session_state.get('blocos_sem_fala', 0)
    if sem_fala:
        st.info("{0} bloco(s) sem fala reconhecível (silêncio ou ruído) foram "
                "ignorados.".format(sem_fala))

    st.subheader("Transcrição")
    st.caption("O reconhecimento de fala erra nomes próprios e pontuação — corrija o "
               "texto aqui antes de exportar.")
    texto = st.text_area("Texto transcrito", height=400, key="texto_editado",
                         label_visibility="collapsed")

    nome_origem = st.session_state.get('nome_origem')
    idioma_usado = st.session_state.get('idioma')
    nome_base = _nome_base(nome_origem)

    coluna_txt, coluna_pdf = st.columns(2)
    with coluna_txt:
        st.download_button(
            "⬇️ Baixar .txt",
            data=texto.encode('utf-8'),
            file_name="{0}.txt".format(nome_base),
            mime='text/plain',
            disabled=not texto.strip(),
            use_container_width=True)
    with coluna_pdf:
        try:
            pdf = _pdf_em_bytes(texto, nome_origem, idioma_usado) if texto.strip() else b''
        except ValueError as erro:
            st.error("Erro ao gerar o PDF: {0}".format(erro))
        else:
            st.download_button(
                "⬇️ Baixar .pdf",
                data=pdf,
                file_name="{0}.pdf".format(nome_base),
                mime='application/pdf',
                disabled=not texto.strip(),
                use_container_width=True)
