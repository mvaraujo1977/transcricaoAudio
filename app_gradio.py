"""Interface Gradio, usada na demo pública do Hugging Face Spaces.

É uma camada de tela sobre `audioTranscricao`: nada da lógica de transcrição
mora aqui. O que vale lá vale aqui -- temperature=0.0, initial_prompt, a sonda
de duração, a contagem de amostras durante a decodificação via PyAV --, porque
esta interface chama exatamente a mesma função `transcrever`.

A versão local continua sendo o `app.py` (Streamlit). Existem duas telas porque
as duas plataformas pedem coisas diferentes: a conta gratuita do Spaces não
libera SDK Docker, e o Gradio é o SDK que ela libera.

Não importa o módulo `spaces` nem usa @spaces.GPU: o ZeroGPU só acelera PyTorch,
e o motor aqui é CTranslate2. A transcrição roda na CPU do Space, sem consumir
cota de GPU.
"""

import os
import tempfile

import gradio as gr

from audioTranscricao import (DuracaoExcedida, FASE_PREPARO, MODELOS,
                              limite_horas, modelo_padrao, transcrever)
from gerar_pdf import transcricao_para_pdf

RAIZ = os.path.dirname(os.path.abspath(__file__))
CAMINHO_EXEMPLO = os.path.join(RAIZ, 'exemplos', 'exemplo-o-alienista.mp3')

FORMATOS_ACEITOS = ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aiff',
                    '.mp4', '.mkv', '.avi', '.mov']

# Os mesmos rótulos do app.py. A lista é de tela, não de motor: quem traduz a
# etiqueta regional para o ISO 639-1 que o Whisper entende é o codigo_idioma().
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

# Limites da demo pública. O Spaces define SPACE_ID em todo container que roda
# lá; fora dele esta tela herda os padrões da instalação local. Cada valor cede a
# uma variável de ambiente explícita, que é como o Dockerfile/entrypoint já fazem
# no caminho Streamlit.
NA_DEMO = bool(os.environ.get('SPACE_ID'))
if NA_DEMO:
    # `base` em vez de `small`: a CPU do Space é compartilhada e o small deixaria
    # a espera longa demais. O modelo continua selecionável na tela.
    os.environ.setdefault('TRANSCRICAO_MODELO', 'base')
    # 5 min: ninguém espera mais que isso numa demo, e um teto de horas numa
    # página pública é convite a abuso.
    os.environ.setdefault('TRANSCRICAO_MAX_MINUTOS', '5')

MAX_UPLOAD_MB = int(os.environ.get('TRANSCRICAO_MAX_UPLOAD_MB', 50 if NA_DEMO else 256))

# Exigência do hardware ZeroGPU, não do projeto. O Space recusou subir com
# "No @spaces.GPU function detected during startup": a plataforma verifica, na
# inicialização, que existe ao menos uma função decorada -- mesmo que a
# aplicação nunca peça GPU. A função abaixo existe só para essa checagem: não é
# chamada, não consome cota, e a transcrição continua inteira na CPU, porque o
# motor é CTranslate2 e o ZeroGPU só acelera PyTorch.
#
# Remover este bloco depende de o Space sair do ZeroGPU, o que hoje exige conta
# PRO: a Hugging Face recusa o downgrade de ZeroGPU para CPU básica sem ela.
# Enquanto isso não mudar, o bloco e a dependência `spaces` ficam. O caso, com o
# que foi tentado, está em docs/DEPLOY.md.
if NA_DEMO:
    try:
        import spaces

        @spaces.GPU(duration=1)
        def _exigido_pelo_zerogpu():
            """Nunca chamada; ver o comentário acima."""
            return None
    except ImportError:
        pass


def _minutos_do_teto():
    """Teto de duração em minutos, para escrever na tela."""
    return int(round(limite_horas() * 60))


def _tamanho_mb(caminho):
    return os.path.getsize(caminho) / (1024.0 * 1024.0)


def _nome_base(caminho):
    return os.path.splitext(os.path.basename(caminho or 'transcricao'))[0] or 'transcricao'


def transcrever_arquivo(caminho, rotulo_idioma, nome_modelo, vocabulario,
                        progresso=gr.Progress()):
    """Transcreve o arquivo e devolve (texto, aviso) para a tela.

    Erros de entrada viram gr.Error, que o Gradio mostra como aviso na tela em
    vez de traceback: arquivo grande demais, áudio mais longo que o teto, mídia
    ilegível.
    """
    if not caminho:
        raise gr.Error("Escolha um arquivo de áudio ou vídeo, ou use o exemplo.")

    extensao = os.path.splitext(caminho)[1].lower()
    if extensao not in FORMATOS_ACEITOS:
        raise gr.Error("Formato não aceito ({0}). Use: {1}.".format(
            extensao or 'sem extensão', ', '.join(f.lstrip('.') for f in FORMATOS_ACEITOS)))

    tamanho = _tamanho_mb(caminho)
    if tamanho > MAX_UPLOAD_MB:
        raise gr.Error("O arquivo tem {0:.0f} MB e o limite é {1} MB.".format(
            tamanho, MAX_UPLOAD_MB))

    def progresso_da_transcricao(processado, total, fase=None):
        if fase == FASE_PREPARO:
            progresso(0.0, desc="Preparando o áudio…")
        elif total:
            progresso(min(processado / total, 1.0),
                      desc="Transcrevendo… {0:.0f}%".format(100.0 * processado / total))

    try:
        resultado = transcrever(caminho, idioma=IDIOMAS.get(rotulo_idioma),
                                modelo=nome_modelo, progresso=progresso_da_transcricao,
                                vocabulario=vocabulario or None)
    except DuracaoExcedida as erro:
        raise gr.Error(str(erro))
    except (OSError, ValueError, RuntimeError) as erro:
        raise gr.Error("Não foi possível transcrever: {0}".format(erro))

    minutos, segundos = divmod(int(resultado.duracao or 0), 60)
    resumo = "{0:02d}:{1:02d} de áudio · idioma {2} · {3} segmentos · {4} palavras".format(
        minutos, segundos, resultado.idioma_detectado or '—',
        len(resultado.segmentos), len(resultado.texto.split()))
    return resultado.texto, resumo


def gerar_pdf(texto, caminho_origem):
    """Gera o PDF do texto que está na tela -- já revisado, se foi editado."""
    if not texto or not texto.strip():
        raise gr.Error("Não há texto para exportar.")

    nome = _nome_base(caminho_origem)
    destino = os.path.join(tempfile.mkdtemp(), "{0}.pdf".format(nome))
    transcricao_para_pdf(texto, destino, nome_origem=os.path.basename(caminho_origem or ''),
                         idioma=None)
    return gr.update(value=destino, visible=True)


def gerar_txt(texto, caminho_origem):
    """Mesma ideia do PDF, para quem só quer o texto puro."""
    if not texto or not texto.strip():
        raise gr.Error("Não há texto para exportar.")

    destino = os.path.join(tempfile.mkdtemp(), "{0}.txt".format(_nome_base(caminho_origem)))
    with open(destino, 'w', encoding='utf-8') as arquivo:
        arquivo.write(texto)
    return gr.update(value=destino, visible=True)


def _descricao():
    linhas = [
        "Transcreve áudio e vídeo em texto editável, com o modelo Whisper "
        "rodando na própria máquina que serve esta página — o arquivo não vai "
        "para nenhum serviço externo.",
        "",
        "**Transcreve, não traduz**: o texto sai no idioma falado no áudio.",
    ]
    if NA_DEMO:
        linhas += [
            "",
            "Limites desta demo pública: **{0} minutos** de áudio, **{1} MB** por "
            "arquivo e modelo **{2}** pré-selecionado (a CPU aqui é compartilhada). "
            "Rodando local, o padrão é `small` e o teto é de 4 horas.".format(
                _minutos_do_teto(), MAX_UPLOAD_MB, modelo_padrao()),
        ]
    return "\n".join(linhas)


with gr.Blocks(title="Transcrição de áudio") as demo:
    gr.Markdown("# Transcrição de áudio")
    gr.Markdown(_descricao())

    with gr.Row():
        with gr.Column(scale=1):
            entrada = gr.Audio(label="Arquivo de áudio ou vídeo", type="filepath",
                               sources=["upload"])
            with gr.Accordion("Opções avançadas", open=False):
                idioma = gr.Dropdown(list(IDIOMAS), value=list(IDIOMAS)[0],
                                     label="Idioma do áudio",
                                     info="Diz ao modelo o que esperar; não traduz.")
                modelo = gr.Dropdown(list(MODELOS), value=modelo_padrao(),
                                     label="Modelo",
                                     info="Maiores são mais precisos e mais lentos.")
                vocabulario = gr.Textbox(
                    label="Vocabulário do domínio", lines=2,
                    placeholder="Siglas e termos que aparecem no áudio: LIMPE, RDC, CRM…",
                    info="Semear o reconhecimento corrige jargão que o modelo erraria.")
            with gr.Row():
                transcrever_botao = gr.Button("Transcrever", variant="primary")
                exemplo_botao = gr.Button("Testar com exemplo")
            gr.Markdown(
                "O exemplo são 24 s de *O Alienista*, de Machado de Assis, em "
                "domínio público (LibriVox).", elem_id="nota-exemplo")

        with gr.Column(scale=1):
            resumo = gr.Markdown("")
            texto = gr.Textbox(label="Transcrição", lines=18,
                               placeholder="O texto aparece aqui, editável antes de exportar.")
            with gr.Row():
                baixar_txt = gr.Button("Gerar .txt")
                baixar_pdf = gr.Button("Gerar .pdf")
            arquivo_txt = gr.File(label="Texto (.txt)", visible=False)
            arquivo_pdf = gr.File(label="PDF", visible=False)

    gr.Markdown(
        "Código, decisões técnicas e auditoria de segurança: "
        "[github.com/mvaraujo1977/transcricaoAudio]"
        "(https://github.com/mvaraujo1977/transcricaoAudio)")

    transcrever_botao.click(transcrever_arquivo,
                            inputs=[entrada, idioma, modelo, vocabulario],
                            outputs=[texto, resumo])

    # O exemplo carrega o arquivo do repositório no campo e já transcreve: quem
    # abre a demo sem um áudio à mão vê a ferramenta funcionando em um clique.
    exemplo_botao.click(lambda: CAMINHO_EXEMPLO, outputs=entrada).then(
        transcrever_arquivo, inputs=[entrada, idioma, modelo, vocabulario],
        outputs=[texto, resumo])

    baixar_txt.click(gerar_txt, inputs=[texto, entrada], outputs=arquivo_txt)
    baixar_pdf.click(gerar_pdf, inputs=[texto, entrada], outputs=arquivo_pdf)


if __name__ == '__main__':
    # No Spaces este arquivo roda como __main__, então é este launch que sobe a
    # demo. `theme` vive aqui desde o Gradio 6; `max_file_size` corta o upload
    # grande antes de ele chegar ao disco, além da conferência no handler.
    demo.launch(theme=gr.themes.Soft(), max_file_size="{0}mb".format(MAX_UPLOAD_MB))
