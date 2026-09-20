"""Interface Streamlit para transcrever áudio/vídeo e exportar o texto."""

import contextlib
import io
import os
import tempfile
import time

import streamlit as st

from audioTranscricao import (LIMITE_TOKENS_VOCABULARIO, MODELO_PADRAO, MODELOS,
                              inicio_dos_paragrafos, preparar_vocabulario, transcrever)
from gerar_pdf import transcricao_para_pdf

FORMATOS_ACEITOS = ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aiff', 'mp4', 'mkv', 'avi', 'mov']

# O prefixo marca os temporários como nossos, para a varredura de órfãos não
# tocar em arquivos de outros programas.
PREFIXO_TEMPORARIO = 'transcricaoAudio_'
IDADE_MAXIMA_TEMPORARIO = 24 * 3600

IDIOMAS = {
    'Português (Brasil)': 'pt-BR',
    'Português (Portugal)': 'pt-PT',
    'Inglês (EUA)': 'en-US',
    'Espanhol': 'es-ES',
    'Francês': 'fr-FR',
    'Italiano': 'it-IT',
    'Alemão': 'de-DE',
    'Detectar automaticamente': None,
}

PLACEHOLDER_VOCABULARIO = (
    "Princípios da administração pública: LIMPE, legalidade, impessoalidade, "
    "moralidade, publicidade, eficiência. Gabarito, questão, banca."
)

# Tamanho aproximado do download de cada modelo, para avisar antes da espera.
TAMANHO_MODELO = {
    'tiny': '~75 MB',
    'base': '~145 MB',
    'small': '~480 MB',
    'medium': '~1,5 GB',
    'large-v3': '~3 GB',
}


def _mmss(segundos):
    """Formata segundos como mm:ss."""
    segundos = int(segundos or 0)
    return "{0:02d}:{1:02d}".format(segundos // 60, segundos % 60)


def _nome_base(nome_arquivo):
    """'reuniao.mp4' -> 'reuniao'."""
    return os.path.splitext(os.path.basename(nome_arquivo or 'transcricao'))[0] or 'transcricao'


def _modelo_baixado(nome_modelo):
    """Diz se o modelo já está no cache local, para avisar sobre o download."""
    raiz = os.environ.get('HF_HOME') or os.path.join(os.path.expanduser('~'), '.cache', 'huggingface')
    pasta = os.path.join(raiz, 'hub', 'models--Systran--faster-whisper-{0}'.format(nome_modelo))
    return os.path.isdir(pasta)


def _limpar_temporarios_orfaos():
    """Remove temporários nossos com mais de 24 h.

    O `finally` da transcrição cobre erro e rerun, mas não um SIGKILL -- que já
    aconteceu com esta aplicação, morta pelo sistema por falta de memória. Sem
    a varredura, cada morte dessas deixa para trás um arquivo do tamanho de um
    vídeo de reunião.
    """
    pasta = tempfile.gettempdir()
    limite = time.time() - IDADE_MAXIMA_TEMPORARIO
    with contextlib.suppress(OSError):
        for nome in os.listdir(pasta):
            if not nome.startswith(PREFIXO_TEMPORARIO):
                continue
            caminho = os.path.join(pasta, nome)
            with contextlib.suppress(OSError):
                if os.path.isfile(caminho) and os.path.getmtime(caminho) < limite:
                    os.remove(caminho)


@st.cache_resource
def _varrer_uma_vez():
    """Roda a varredura uma vez por processo, não a cada rerun da tela."""
    _limpar_temporarios_orfaos()
    return True


def _salvar_upload(upload):
    """Grava o upload num arquivo temporário, com extensão vinda da lista branca.

    O nome enviado é controlado por quem envia e nunca vira caminho: só a
    extensão é aproveitada, e mesmo ela é conferida contra FORMATOS_ACEITOS
    antes de virar sufixo. Repassar o sufixo cru deixava passar uma extensão
    com byte nulo, que rebentava o tempfile com um ValueError não tratado.
    """
    extensao = os.path.splitext(upload.name or '')[1].lower().lstrip('.')
    if extensao not in FORMATOS_ACEITOS:
        raise ValueError(
            "Extensão não aceita: {0!r}. Use um destes formatos: {1}.".format(
                extensao or '(sem extensão)', ', '.join(FORMATOS_ACEITOS)))
    with tempfile.NamedTemporaryFile(delete=False, prefix=PREFIXO_TEMPORARIO,
                                     suffix='.' + extensao) as temporario:
        temporario.write(upload.getbuffer())
        return temporario.name


def _executar_transcricao(caminho, idioma, modelo, vocabulario=None):
    """Roda a transcrição alimentando a barra de progresso e o painel de status."""
    barra = st.progress(0.0, text="Preparando o áudio...")

    with st.status("Transcrevendo...", expanded=True) as status:
        if not _modelo_baixado(modelo):
            st.write("Baixando o modelo **{0}** ({1}). Isso acontece só na primeira "
                     "execução.".format(modelo, TAMANHO_MODELO.get(modelo, '')))

        def progresso(processado, total):
            if total:
                barra.progress(min(processado / total, 1.0),
                               text="{0} de {1}".format(_mmss(processado), _mmss(total)))
                status.update(label="Transcrevendo... {0} de {1}".format(
                    _mmss(processado), _mmss(total)))
            else:
                barra.progress(0.0, text="{0} processados".format(_mmss(processado)))

        resultado = transcrever(caminho, idioma=idioma, modelo=modelo,
                                progresso=progresso, vocabulario=vocabulario)
        status.update(label="Transcrição concluída", state="complete")

    barra.progress(1.0, text="Concluído")
    return resultado


def _com_marcacao_de_tempo(texto, segmentos):
    """Prefixa cada parágrafo com [MM:SS] do seu primeiro segmento."""
    paragrafos = [p for p in texto.split('\n\n') if p.strip()]
    inicios = inicio_dos_paragrafos(segmentos)
    marcados = []
    for indice, paragrafo in enumerate(paragrafos):
        if indice < len(inicios):
            marcados.append("[{0}] {1}".format(_mmss(inicios[indice]), paragrafo))
        else:
            marcados.append(paragrafo)
    return '\n\n'.join(marcados)


def _pdf_em_bytes(texto, nome_origem, idioma):
    """Gera o PDF em memória e devolve os bytes."""
    buffer = io.BytesIO()
    transcricao_para_pdf(texto, buffer, nome_origem=nome_origem, idioma=idioma)
    return buffer.getvalue()


st.set_page_config(page_title="Transcrição de Áudio", page_icon="🎙️", layout="centered")

_varrer_uma_vez()

st.title("🎙️ Transcrição de Áudio")
st.caption("Envie um arquivo de áudio ou vídeo e receba a transcrição em texto, "
           "pronta para revisar e exportar. O reconhecimento roda localmente.")

upload = st.file_uploader("Arquivo de áudio ou vídeo", type=FORMATOS_ACEITOS)

with st.expander("Opções avançadas"):
    rotulo_idioma = st.selectbox("Idioma do áudio", list(IDIOMAS), index=0)
    idioma = IDIOMAS[rotulo_idioma]
    modelo = st.selectbox("Modelo", MODELOS, index=MODELOS.index(MODELO_PADRAO))
    st.caption("Modelos maiores são mais precisos e mais lentos. `small` costuma "
               "equilibrar bem; `medium` e `large-v3` ganham em jargão e nomes "
               "próprios, ao custo de várias vezes o tempo de processamento.")
    if not _modelo_baixado(modelo):
        st.info("O modelo **{0}** ({1}) será baixado na primeira transcrição.".format(
            modelo, TAMANHO_MODELO.get(modelo, '')))

    vocabulario = st.text_area(
        "Vocabulário do domínio (termos e siglas que aparecem no áudio)",
        placeholder=PLACEHOLDER_VOCABULARIO,
        height=100,
        help="Semear o reconhecimento com o jargão do assunto corrige siglas e "
             "termos técnicos que o modelo erraria por não esperá-los.")

    if vocabulario.strip():
        # A contagem exata depende do tokenizador do modelo, então o corte é
        # calculado aqui mesmo para o aviso aparecer antes de rodar.
        _, truncado = preparar_vocabulario(vocabulario, modelo)
        if truncado:
            st.warning("O vocabulário passou de {0} tokens, que é o limite do "
                       "Whisper. O excedente será ignorado — deixe os termos mais "
                       "importantes no começo.".format(LIMITE_TOKENS_VOCABULARIO))

if st.button("Transcrever", type="primary", disabled=upload is None):
    # _salvar_upload fica DENTRO do try: um nome de arquivo hostil vira st.error
    # em vez de um traceback do Streamlit expondo caminhos do sistema.
    caminho = None
    try:
        caminho = _salvar_upload(upload)
        resultado = _executar_transcricao(caminho, idioma, modelo, vocabulario)
    except (OSError, ValueError, RuntimeError) as erro:
        st.error("Erro: {0}".format(erro))
    else:
        # Sem o session_state, qualquer interação na tela dispara um rerun e a
        # transcrição (que custou minutos) seria perdida.
        st.session_state['texto_editado'] = resultado.texto
        st.session_state['segmentos'] = resultado.segmentos
        st.session_state['duracao'] = resultado.duracao
        st.session_state['idioma_detectado'] = resultado.idioma_detectado
        st.session_state['nome_origem'] = upload.name
        st.session_state['idioma'] = idioma or resultado.idioma_detectado
    finally:
        if caminho:
            with contextlib.suppress(OSError):
                os.remove(caminho)

if 'texto_editado' in st.session_state:
    st.divider()

    coluna_a, coluna_b, coluna_c = st.columns(3)
    coluna_a.metric("Duração", _mmss(st.session_state.get('duracao')))
    coluna_b.metric("Idioma detectado", st.session_state.get('idioma_detectado') or '—')
    coluna_c.metric("Segmentos", len(st.session_state.get('segmentos') or []))

    st.subheader("Transcrição")
    st.caption("O reconhecimento pode errar nomes próprios e siglas — corrija o "
               "texto aqui antes de exportar.")
    texto = st.text_area("Texto transcrito", height=400, key="texto_editado",
                         label_visibility="collapsed")

    com_tempo = st.checkbox(
        "Incluir marcação de tempo no PDF",
        help="Prefixa cada parágrafo com [MM:SS], para voltar ao ponto exato do áudio.")

    nome_origem = st.session_state.get('nome_origem')
    idioma_usado = st.session_state.get('idioma')
    nome_base = _nome_base(nome_origem)
    segmentos = st.session_state.get('segmentos') or []

    texto_pdf = _com_marcacao_de_tempo(texto, segmentos) if com_tempo else texto

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
            pdf = _pdf_em_bytes(texto_pdf, nome_origem, idioma_usado) if texto.strip() else b''
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
