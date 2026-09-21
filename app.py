"""Interface Streamlit para transcrever áudio/vídeo e exportar o texto."""

import contextlib
import io
import os
import tempfile
import time

import streamlit as st

from audioTranscricao import (FASE_ANALISE, FASE_PREPARO, FASE_TRANSCRICAO,
                              LIMITE_TOKENS_VOCABULARIO, MODELOS, URL_PROJETO,
                              agrupar_em_paragrafos, em_demo,
                              inicio_dos_paragrafos, limite_horas,
                              modelo_padrao, modelos_disponiveis,
                              preparar_vocabulario, transcrever)
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

# Áudio de exemplo que acompanha o repositório: 24 s de "O Alienista", de
# Machado de Assis, em domínio público (veja exemplos/CREDITOS.md). É o que
# permite experimentar a ferramenta sem ter um arquivo à mão.
CAMINHO_EXEMPLO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'exemplos', 'exemplo-o-alienista.mp3')
NOME_EXEMPLO = 'exemplo-o-alienista.mp3'

# Tamanho aproximado do download de cada modelo, para avisar antes da espera.
TAMANHO_MODELO = {
    'tiny': '~75 MB',
    'base': '~145 MB',
    'small': '~480 MB',
    'medium': '~1,5 GB',
    'large-v3': '~3 GB',
}

# CSS injetado: entra aqui só o que o tema (.streamlit/config.toml) e as
# primitivas do Streamlit não resolvem. O seletor é [data-testid=...], que o
# Streamlit mantém entre versões -- as classes geradas (.st-emotion-cache-...)
# mudam a cada atualização e não servem de apoio.
#
# O que NÃO está aqui, de propósito: o menu e o botão Deploy saem pelo
# toolbarMode="minimal" do config.toml, e o empilhamento das colunas em tela
# estreita é nativo -- st.columns(wrap=True), que é o padrão, empilha sozinho
# em viewport de até 640 px.
ESTILO = """
<style>
/* Respiro do bloco principal. Sem a barra do topo, o padding existe para o
   título não nascer colado na borda e para o último botão não encostar embaixo;
   espaçamento de bloco não é exposto pelo tema. Até 640 px o Streamlit aplica
   um padding maior, que prevalece -- é o que a tela estreita pede. */
[data-testid="stMainBlockContainer"] { padding-top: 3rem; padding-bottom: 4rem; }

/* Instruções do uploader ("256MB per file - MP3, WAV, ..."). O Streamlit não
   traduz esse texto e não expõe parâmetro para trocá-lo: st.file_uploader só
   deixa escrever o label e o help. A linha em português logo abaixo do uploader
   diz a mesma coisa, com o limite lido de server.maxUploadSize. */
[data-testid="stFileUploaderDropzoneInstructions"] { display: none; }

/* Legenda (st.caption). O Streamlit apaga a legenda com opacity: 0.6 sobre a
   cor do texto, e sobre o fundo creme da paleta isso cai para 4,08:1 -- abaixo
   dos 4,5:1 que texto precisa. Não há opção de tema para essa opacidade, e
   mexer nela em vez de fixar uma cor mantém o ajuste válido nos dois modos:
   0,72 dá 5,92:1 no claro e 8,32:1 no escuro, e a legenda continua mais leve
   que o corpo do texto. */
[data-testid="stCaptionContainer"] { opacity: 0.72; }
</style>
"""


def _mmss(segundos):
    """Formata segundos como mm:ss."""
    segundos = int(segundos or 0)
    return "{0:02d}:{1:02d}".format(segundos // 60, segundos % 60)


def _nome_base(nome_arquivo):
    """'reuniao.mp4' -> 'reuniao'."""
    return os.path.splitext(os.path.basename(nome_arquivo or 'transcricao'))[0] or 'transcricao'


def _limite_de_duracao():
    """Teto de duração do áudio, por extenso, para a tela anunciar.

    Vem de limite_horas(), não de um número escrito à mão: o mesmo código serve a
    instalação pessoal (4 horas) e a demo pública (20 minutos), e a tela precisa
    dizer o teto que está mesmo valendo. Por extenso e com o plural certo porque
    isto é texto de interface, não a forma curta das mensagens de erro.

    Devolve None quando o teto não é legível. limite_horas() recusa uma variável
    de ambiente mal escrita com ValueError, e isto aqui roda ao DESENHAR a tela,
    não ao transcrever: deixar subir trocaria a página inteira por um traceback
    do Streamlit por causa de um valor que ainda nem foi usado. A recusa continua
    acontecendo na hora da transcrição, que é onde ela tem sentido e onde a tela
    já sabe mostrá-la como erro.
    """
    try:
        horas = limite_horas()
    except ValueError:
        return None

    if horas < 1:
        minutos = horas * 60
        return "1 minuto" if round(minutos) == 1 else "{0:.0f} minutos".format(minutos)
    if abs(horas - round(horas)) < 0.05:
        inteiro = int(round(horas))
        return "1 hora" if inteiro == 1 else "{0} horas".format(inteiro)
    return "{0:.1f} horas".format(horas)


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


def _pedir_cancelamento():
    """Marca o pedido de cancelamento, antes do rerun que interrompe o script.

    Callback de widget roda no começo do rerun, antes do corpo do script, então
    a marca já está posta quando a tela decide o que fazer. O `execucao_ativa`
    evita transformar em cancelamento um clique que chegou tarde: se a
    transcrição terminou antes de o Streamlit processar o clique, não há o que
    cancelar, e o resultado completo não pode virar parcial.
    """
    if st.session_state.get('execucao_ativa'):
        st.session_state['cancelado'] = True


def _salvar_parcial(upload, idioma, motivo):
    """Transforma os segmentos já reconhecidos num resultado normal da tela.

    Serve aos DOIS jeitos de uma transcrição acabar antes da hora, que por dentro
    são o mesmo evento: o script é interrompido no meio e a pilha desmontada. Um
    é o clique em Cancelar; o outro é a queda da conexão, que o servidor do
    Streamlit trata chamando `request_script_stop()` na sessão desconectada
    (`runtime/websocket_session_manager.py`) -- ou seja, perder o websocket mata
    a transcrição em andamento, não só a tela.

    O que sobra nos dois casos é o que foi guardado segmento a segmento no
    session_state. `motivo` só decide a frase do aviso; o resultado é igual.

    Devolve True quando havia algo a salvar.
    """
    st.session_state['execucao_ativa'] = False
    parciais = st.session_state.pop('segmentos_parciais', None) or []
    if not parciais:
        return False

    st.session_state['texto_editado'] = '\n\n'.join(agrupar_em_paragrafos(parciais))
    st.session_state['segmentos'] = parciais
    st.session_state['duracao'] = st.session_state.get('duracao_audio')
    st.session_state['idioma_detectado'] = None
    st.session_state['nome_origem'] = (
        NOME_EXEMPLO if st.session_state.get('usar_exemplo')
        else (upload.name if upload is not None else None))
    st.session_state['idioma_escolhido'] = idioma
    st.session_state['parcial_ate'] = parciais[-1].end
    st.session_state['motivo_parcial'] = motivo
    return True


def _executar_transcricao(caminho, idioma, modelo, vocabulario=None):
    """Roda a transcrição desenhando o painel de progresso.

    Esta é a tela que a pessoa encara por vários minutos, então mostra três
    números além da barra: quanto tempo já passou, onde a transcrição está no
    áudio e quanto falta. A estimativa sai do ritmo observado nesta execução --
    segundos de relógio por segundo de áudio --, porque o ritmo real depende da
    máquina, do modelo e do próprio áudio.

    O script do Streamlit roda numa thread só e fica preso aqui dentro: o clique
    em Cancelar só é processado quando o script passa por uma chamada do
    Streamlit, e é por isso que o callback de progresso atualiza a tela também
    durante a decodificação, que não transcreve nada.
    """
    inicio = time.monotonic()
    # Lista no session_state, não local: quando o cancelamento desmonta a pilha,
    # a lista local iria junto e os minutos já transcritos se perderiam.
    st.session_state['segmentos_parciais'] = []

    with st.status("Preparando o áudio...", expanded=True) as status:
        if not _modelo_baixado(modelo):
            st.write("Baixando o modelo **{0}** ({1}). Isso acontece só na primeira "
                     "execução.".format(modelo, TAMANHO_MODELO.get(modelo, '')))

        barra = st.progress(0.0, text="Lendo o arquivo...")

        # A coluna do meio é a mais larga porque o valor dela tem dois relógios
        # ("08:17 de 37:27") e, em três colunas iguais, invade a vizinha.
        coluna_a, coluna_b, coluna_c = st.columns([1, 1.6, 1])
        campo_decorrido = coluna_a.empty()
        campo_posicao = coluna_b.empty()
        campo_restante = coluna_c.empty()
        campo_decorrido.metric("Decorrido", _mmss(0))
        campo_posicao.metric("Posição no áudio", "--")
        campo_restante.metric("Restante (estimado)", "--")

        # Secundário de propósito: cancelar é desistir, não corrigir um erro.
        # Fica desenhado antes de o trabalho começar, senão não existiria na
        # tela justamente enquanto o script está ocupado.
        st.button("Cancelar", key='cancelar', on_click=_pedir_cancelamento,
                  help="Interrompe a transcrição. O que já tiver sido "
                       "reconhecido é mantido na tela.")

        anunciou_transcricao = False

        def progresso(processado, total, fase=FASE_TRANSCRICAO):
            nonlocal anunciou_transcricao
            decorrido = time.monotonic() - inicio
            campo_decorrido.metric("Decorrido", _mmss(decorrido))

            if fase == FASE_ANALISE:
                # A detecção de voz roda dentro do transcribe(), sem devolver o
                # controle: nesta janela o botão Cancelar não responde (veja
                # FASE_ANALISE). Sem dizer isso, o painel fica parado no fim do
                # preparo e parece travado -- e num áudio de 20 min a janela
                # passa de alguns segundos. A barra não é mexida de propósito:
                # zerá-la ou enchê-la aqui seria inventar um progresso que não
                # existe, e a virada de rótulo já conta a mudança de fase.
                status.update(label="Analisando o áudio (detecção de voz)...",
                              expanded=True)
                return

            if fase == FASE_PREPARO:
                # Ainda não há transcrição: posição e estimativa continuam em
                # "--". A barra mostra o quanto do arquivo já foi lido, contra a
                # duração declarada no cabeçalho -- que pode não existir.
                if total:
                    barra.progress(min(processado / total, 1.0),
                                   text="Preparando o áudio — {0} de {1} lidos".format(
                                       _mmss(processado), _mmss(total)))
                else:
                    barra.progress(0.0, text="Preparando o áudio — {0} lidos".format(
                        _mmss(processado)))
                return

            if not anunciou_transcricao:
                # `expanded=True` é obrigatório aqui: st.status.update() sem ele
                # recolhe o painel, e recolhido o Streamlit tira o conteúdo do
                # DOM -- barra, números e o próprio botão de cancelar sumiriam
                # da tela justamente enquanto a transcrição corre. Anunciar uma
                # vez, na virada de fase, também evita refazer isso a cada
                # segmento.
                status.update(label="Transcrevendo com o modelo {0}...".format(modelo),
                              expanded=True)
                anunciou_transcricao = True
            if not total:
                barra.progress(0.0, text="{0} processados".format(_mmss(processado)))
                return
            st.session_state['duracao_audio'] = total
            fracao = min(processado / total, 1.0)
            barra.progress(fracao, text="{0:.0f}% do áudio".format(100 * fracao))
            campo_posicao.metric("Posição no áudio", "{0} de {1}".format(
                _mmss(processado), _mmss(total)))
            if processado > 0:
                restante = decorrido * (total - processado) / processado
                campo_restante.metric("Restante (estimado)", "~{0}".format(_mmss(restante)))

        def guardar_segmento(segmento):
            st.session_state['segmentos_parciais'].append(segmento)

        resultado = transcrever(caminho, idioma=idioma, modelo=modelo,
                                progresso=progresso, vocabulario=vocabulario,
                                ao_segmento=guardar_segmento)
        status.update(label="Transcrição concluída", state="complete", expanded=False)

    return resultado


def _transcrever_upload(upload, idioma, modelo, vocabulario=None, caminho_pronto=None):
    """Grava o upload, transcreve e apaga o temporário aconteça o que acontecer.

    O `finally` cobre o erro, o rerun e também o cancelamento: o Streamlit
    interrompe o script levantando uma exceção que herda de BaseException, e por
    isso ela passa direto pelos `except` da tela -- mas não pelo `finally`.

    _salvar_upload fica DENTRO do try: um nome de arquivo hostil vira st.error
    em vez de um traceback do Streamlit expondo caminhos do sistema.

    `caminho_pronto` é o áudio de exemplo que vem no repositório: já está no
    disco, não passou por upload e não deve ser apagado no fim.
    """
    if caminho_pronto:
        return _executar_transcricao(caminho_pronto, idioma, modelo, vocabulario)

    caminho = None
    try:
        caminho = _salvar_upload(upload)
        return _executar_transcricao(caminho, idioma, modelo, vocabulario)
    finally:
        if caminho:
            with contextlib.suppress(OSError):
                os.remove(caminho)


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


def _painel_de_entrada(processando, mostrar_exemplo=False):
    """Desenha o uploader e as opções; devolve o que foi escolhido.

    Os widgets continuam na tela durante o processamento, desabilitados: fazê-los
    sumir deslocaria a página inteira, e deixá-los ativos permitiria trocar o
    modelo no meio de uma transcrição que já está rodando com o anterior.
    """
    upload = st.file_uploader("Arquivo de áudio ou vídeo", type=FORMATOS_ACEITOS,
                              key='upload', disabled=processando)
    # Substitui as instruções em inglês do próprio uploader, escondidas no ESTILO.
    # São DOIS tetos, e eles não são equivalentes: o de tamanho vem de
    # server.maxUploadSize e o de duração de limite_horas(). Um `.wav` de 20 min
    # bate no de tamanho muito antes do de duração, então anunciar só um deixaria
    # a recusa sem explicação. Ambos lidos, nunca escritos à mão, porque mudam
    # entre a instalação pessoal e a demo pública.
    duracao = _limite_de_duracao()
    st.caption("Arraste o arquivo ou clique em Upload — até {0}. "
               "Formatos aceitos: {1}.".format(
                   "{0} MB e {1} de áudio".format(
                       st.get_option('server.maxUploadSize'), duracao)
                   if duracao else "{0} MB".format(
                       st.get_option('server.maxUploadSize')),
                   ', '.join(FORMATOS_ACEITOS)))

    with st.expander("Opções avançadas", expanded=False):
        rotulo_idioma = st.selectbox("Idioma do áudio", list(IDIOMAS), index=0,
                                     key='rotulo_idioma', disabled=processando)
        # A lista oferecida pode ser menor que MODELOS: veja modelos_disponiveis().
        modelos = modelos_disponiveis()
        modelo = st.selectbox("Modelo", modelos, index=modelos.index(modelo_padrao()),
                              key='modelo', disabled=processando)
        if len(modelos) < len(MODELOS):
            # Com a lista restrita, citar `medium` e `large-v3` mandaria a pessoa
            # procurar no seletor duas opções que não estão lá.
            st.caption("Modelos maiores são mais precisos e mais lentos. A lista "
                       "aqui é curta de propósito: a CPU é compartilhada, e os "
                       "modelos maiores dariam uma espera de dezenas de minutos.")
        else:
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
            key='vocabulario',
            disabled=processando,
            help="Semear o reconhecimento com o jargão do assunto corrige siglas e "
                 "termos técnicos que o modelo erraria por não esperá-los.")

        if vocabulario.strip():
            # A contagem exata depende do tokenizador do modelo, então o corte é
            # calculado aqui mesmo para o aviso aparecer antes de rodar.
            _, truncado = preparar_vocabulario(vocabulario, modelo)
            if truncado:
                st.warning("O vocabulário passou de {0} tokens, que é o limite do "
                           "Whisper. O excedente será ignorado -- deixe os termos "
                           "mais importantes no começo.".format(LIMITE_TOKENS_VOCABULARIO))

    if mostrar_exemplo:
        # Quem abre a demo pública raramente tem um arquivo de áudio à mão. O
        # exemplo vem no repositório e entra pelo mesmo caminho da transcrição,
        # sem upload -- é o que separa ver a ferramenta funcionando de fechar a
        # aba. Fica ao lado do botão principal, e some assim que há resultado.
        coluna_transcrever, coluna_exemplo = st.columns([2, 1])
        clicou = coluna_transcrever.button(
            "Transcrever", type="primary", width="stretch",
            disabled=processando or upload is None)
        exemplo = coluna_exemplo.button(
            "Testar com exemplo", width="stretch", disabled=processando,
            help="Transcreve um trecho de 24 s de 'O Alienista', de Machado de "
                 "Assis, em domínio público. Não envia arquivo nenhum.")
    else:
        clicou = st.button("Transcrever", type="primary", width="stretch",
                           disabled=processando or upload is None)
        exemplo = False

    return upload, IDIOMAS[rotulo_idioma], modelo, vocabulario, clicou, exemplo


def _painel_de_apresentacao():
    """Faixa "Como funciona", só no estado vazio.

    Quem abre o link sem conhecer o projeto precisa entender o fluxo antes de
    enviar qualquer coisa. São três passos, uma frase cada, na mesma ordem em
    que a tela acontece -- e some assim que houver uma transcrição em andamento
    ou pronta, que é quando a orientação vira ruído.
    """
    st.divider()
    st.subheader("Como funciona")

    # Títulos curtos de propósito: em três colunas de ~224 px, um título de duas
    # linhas empurra a frase dele para baixo e desalinha a faixa inteira.
    passo_a, passo_b, passo_c = st.columns(3)
    with passo_a:
        st.markdown("**:gray[1.] Envie o arquivo**")
        st.caption("Áudio ou vídeo de aula, reunião ou entrevista. De um vídeo, "
                   "só a trilha de áudio é lida.")
    with passo_b:
        # Mesmo cuidado dos selos: "nesta máquina" é lido como "no meu
        # computador", e na demo isso é falso. O que não muda entre os dois casos
        # -- e é o que a ferramenta de fato promete -- é a ausência de terceiro.
        if em_demo():
            st.markdown("**:gray[2.] Roda no servidor da demo**")
            st.caption("O modelo Whisper processa o áudio aqui mesmo, sem conta, "
                       "sem chave de API e sem requisição de saída. Rodando local, "
                       "esse servidor é a sua máquina.")
        else:
            st.markdown("**:gray[2.] Roda nesta máquina**")
            st.caption("O modelo Whisper processa o áudio localmente, sem conta, "
                       "sem chave de API e sem requisição de saída.")
    with passo_c:
        st.markdown("**:gray[3.] Revise e baixe**")
        st.caption("O texto sai em parágrafos, editável na tela, e exporta em "
                   ".txt ou em .pdf com marcação de tempo.")


def _painel_de_resultado():
    """Desenha as métricas, o texto editável e os dois downloads."""
    segmentos = st.session_state.get('segmentos') or []
    texto_atual = st.session_state.get('texto_editado') or ''

    parcial_ate = st.session_state.get('parcial_ate')
    if parcial_ate is not None:
        # O aviso fica enquanto o texto for parcial, não só no rerun seguinte à
        # interrupção: quem voltar à tela depois precisa saber o que tem em mãos.
        duracao_total = st.session_state.get('duracao_audio')
        if st.session_state.get('motivo_parcial') == 'interrupcao':
            # Quem perdeu a conexão não sabe que perdeu: a aba dele continuou
            # aberta. Sem dizer a causa provável, o texto pela metade parece erro
            # da ferramenta -- e ele repetiria a transcrição inteira sem motivo.
            abertura = ("A transcrição foi interrompida antes do fim, em geral "
                        "porque a conexão com esta página caiu.")
        else:
            abertura = "Transcrição cancelada."
        st.warning("{0} O texto abaixo cobre o áudio até **{1}**{2} — o restante "
                   "não chegou a ser transcrito.".format(
                       abertura, _mmss(parcial_ate),
                       ", de {0}".format(_mmss(duracao_total)) if duracao_total else ""))

    coluna_a, coluna_b, coluna_c, coluna_d = st.columns(4)
    coluna_a.metric("Duração", _mmss(st.session_state.get('duracao')))
    coluna_b.metric("Idioma", st.session_state.get('idioma_detectado') or '--')
    coluna_c.metric("Segmentos", len(segmentos))
    coluna_d.metric("Palavras", len(texto_atual.split()))

    st.subheader("Transcrição")
    st.caption("O reconhecimento pode errar nomes próprios e siglas -- corrija o "
               "texto aqui antes de exportar.")
    texto = st.text_area("Texto transcrito", height=420, key='texto_editado',
                         label_visibility="collapsed")

    com_tempo = st.checkbox(
        "Incluir marcação de tempo no PDF",
        help="Prefixa cada parágrafo com [MM:SS], para voltar ao ponto exato do áudio.")

    nome_origem = st.session_state.get('nome_origem')
    nome_base = _nome_base(nome_origem)
    idioma_usado = st.session_state.get('idioma_escolhido')
    texto_pdf = _com_marcacao_de_tempo(texto, segmentos) if com_tempo else texto

    coluna_txt, coluna_pdf = st.columns(2)
    with coluna_txt:
        st.download_button(
            "Baixar .txt",
            data=texto.encode('utf-8'),
            file_name="{0}.txt".format(nome_base),
            mime='text/plain',
            disabled=not texto.strip(),
            width="stretch")
    with coluna_pdf:
        try:
            pdf = _pdf_em_bytes(texto_pdf, nome_origem, idioma_usado) if texto.strip() else b''
        except ValueError as erro:
            st.error("Erro ao gerar o PDF: {0}".format(erro))
        else:
            st.download_button(
                "Baixar .pdf",
                data=pdf,
                file_name="{0}.pdf".format(nome_base),
                mime='application/pdf',
                disabled=not texto.strip(),
                width="stretch")


st.set_page_config(page_title="Transcrição de áudio", page_icon="🎙️", layout="centered")

_varrer_uma_vez()
st.markdown(ESTILO, unsafe_allow_html=True)

# A tela tem três estados e mostra um de cada vez: VAZIO (só a entrada),
# PROCESSANDO (entrada desabilitada mais o painel de progresso) e RESULTADO
# (entrada mais o texto transcrito). O session_state é o que os separa -- e
# também o que preserva uma transcrição que custou minutos, já que qualquer
# interação na tela dispara um rerun.
processando = st.session_state.get('processando', False)

st.title("Transcrição de áudio")
# A descrição e o que a diferencia ficam em texto normal, não em legenda: rodar
# local é a informação mais importante da página e estava no tom mais apagado
# dela.
#
# Os selos são `gray`, que no config.toml é a sálvia da paleta (escura no modo
# claro, clara no escuro) -- e não `primary`. O texto do selo é pintado com a
# própria cor, sobre um fundo que é ela a 10%: com o teal do botão, que precisa
# ser profundo para o branco por cima dele passar, esse par cai para 3,16:1 no
# modo escuro. A sálvia é definida por modo justamente para o selo, que é texto,
# nunca ficar em tom pastel.
st.markdown("Transcreve arquivos de áudio e vídeo em texto editável, para revisar "
            "na tela e exportar em .txt ou .pdf.")
# Dois dos selos só são verdade fora da demo. "Sem envio para a nuvem" é
# literalmente falso num Space público -- o arquivo sobe para o servidor do
# Hugging Face --, e "Processamento local" é lido por qualquer visitante como "no
# meu computador". Anunciar isso na mesma tela que pede um arquivo, logo acima do
# aviso de não mandar material sigiloso, seria a página se contradizendo.
selos = [":gray-badge[Sem API de terceiros]",
         ":gray-badge[Modelo Whisper]",
         ":gray-badge[Português e mais 5 idiomas]"]
if not em_demo():
    selos = [":gray-badge[Processamento local]",
             ":gray-badge[Sem envio para a nuvem]"] + selos
st.markdown(" ".join(selos))

# Para quem a ferramenta serve, logo abaixo dos selos. Quem chega por um link não
# sabe o que a distingue de qualquer transcritor online, e a distinção é uma só:
# o áudio não passa por serviço de terceiro. A frase evita dizer "na sua máquina"
# de propósito -- na demo não é, e é exatamente aí que a promessa poderia virar
# armadilha.
st.markdown("Feito para material que não pode ir para a nuvem — audiência, sessão "
            "clínica, reunião interna, entrevista. O áudio é processado pelo modelo "
            "na própria máquina que roda a aplicação, sem chamada a nenhuma API de "
            "terceiros.")

if em_demo():
    # Esta ressalva não é opcional: sem ela, o parágrafo acima vira convite para
    # alguém subir material sigiloso num servidor público. Fica em st.warning, e
    # não em texto corrido, porque precisa ser lida antes do upload, não depois.
    st.warning("**Nesta demo pública, essa máquina é o servidor do Hugging Face — "
               "não o seu computador. Não envie material confidencial aqui.** Para "
               "ter a garantia de verdade, rode o projeto na sua máquina com "
               "Docker: [{0}]({1}).".format(URL_PROJETO.split('//')[-1], URL_PROJETO))

upload, idioma, modelo, vocabulario, clicou, exemplo = _painel_de_entrada(
    processando, mostrar_exemplo='texto_editado' not in st.session_state)

if clicou or exemplo:
    # O clique só liga o estado e volta: a transcrição roda no rerun seguinte,
    # que já desenha os controles desabilitados antes de começar o trabalho.
    st.session_state['processando'] = True
    st.session_state['usar_exemplo'] = bool(exemplo)
    st.session_state.pop('erro', None)
    st.session_state.pop('aviso', None)
    st.rerun()

if processando:
    # Desligado antes de rodar: se a transcrição falhar, a tela volta ao estado
    # de entrada em vez de ficar presa em "processando".
    st.session_state['processando'] = False
    # Ligado enquanto o trabalho está no ar. Se o cancelamento interromper o
    # script, esta marca fica de pé e é o que diz ao callback do botão que havia
    # mesmo uma execução para cancelar.
    st.session_state['execucao_ativa'] = True
    do_exemplo = st.session_state.get('usar_exemplo', False)
    try:
        resultado = _transcrever_upload(
            upload, idioma, modelo, vocabulario,
            caminho_pronto=CAMINHO_EXEMPLO if do_exemplo else None)
    except (OSError, ValueError, RuntimeError) as erro:
        # O erro viaja pelo session_state porque o rerun logo abaixo apagaria
        # qualquer st.error escrito aqui.
        st.session_state['execucao_ativa'] = False
        st.session_state['erro'] = str(erro)
    else:
        st.session_state['execucao_ativa'] = False
        st.session_state['texto_editado'] = resultado.texto
        st.session_state['segmentos'] = resultado.segmentos
        st.session_state['duracao'] = resultado.duracao
        st.session_state['idioma_detectado'] = resultado.idioma_detectado
        st.session_state['nome_origem'] = (
            NOME_EXEMPLO if do_exemplo else upload.name)
        st.session_state['idioma_escolhido'] = idioma or resultado.idioma_detectado
        st.session_state.pop('parcial_ate', None)
        st.session_state.pop('motivo_parcial', None)
        st.session_state.pop('segmentos_parciais', None)
    st.rerun()

if st.session_state.pop('cancelado', False):
    # A execução foi interrompida no meio: o temporário já saiu no `finally` de
    # _transcrever_upload, e o que sobrou para decidir é o trabalho parcial.
    if not _salvar_parcial(upload, idioma, 'cancelamento'):
        # Cancelado antes do primeiro segmento (em geral ainda no preparo): não
        # há texto a mostrar, e a tela volta ao estado de entrada -- com o
        # arquivo enviado ainda no uploader, para recomeçar sem reenviar.
        st.session_state['aviso'] = "Transcrição cancelada."
elif st.session_state.get('execucao_ativa'):
    # A marca ficou de pé sem ninguém ter pedido cancelamento: o script foi
    # parado de FORA. Na prática isso é a conexão caindo -- trocar de app no
    # celular, uma oscilação de rede, a tampa do notebook --, porque o servidor
    # do Streamlit para o script da sessão que perde o websocket.
    #
    # Sem este ramo a perda era silenciosa: o script recomeçava do topo, não
    # encontrava `texto_editado` e a tela voltava ao estado vazio como se nada
    # tivesse acontecido, com os minutos já transcritos presos no session_state
    # e ninguém para mostrá-los.
    #
    # Chegar aqui depende de a sessão ainda existir quando o navegador reconecta:
    # é o que `server.disconnectedSessionTTL` decide, e é por isso que o
    # config.toml não deixa esse valor no padrão de 2 minutos.
    if not _salvar_parcial(upload, idioma, 'interrupcao'):
        st.session_state['aviso'] = (
            "A transcrição foi interrompida antes de reconhecer qualquer trecho. "
            "O arquivo continua no campo acima, para tentar de novo.")

if st.session_state.get('erro'):
    st.error("Erro: {0}".format(st.session_state['erro']))

if st.session_state.get('aviso'):
    st.info(st.session_state['aviso'])

if 'texto_editado' in st.session_state:
    st.divider()
    _painel_de_resultado()
else:
    # O estado PROCESSANDO não chega aqui: o bloco acima termina em st.rerun().
    _painel_de_apresentacao()

st.divider()
# A URL sai de URL_PROJETO, a mesma que a mensagem do teto de duração usa na
# demo: dois lugares apontando para o repositório, um valor só.
st.caption("Projeto pessoal — código em [{0}]({1}).".format(
    URL_PROJETO.split('//')[-1], URL_PROJETO))
