"""FERRAMENTA DE MEDICAO -- nao faz parte da aplicacao.

Nada aqui e importado por app.py, audioTranscricao.py ou gerar_pdf.py, e o
arquivo NAO sobe para o Space: deploy/publicar_space.py trabalha com uma lista
explicita de arquivos, e este nao esta nela. Fica no repositorio ao lado dos
verificadores porque responde a uma pergunta que so o hardware real responde --
quanto tempo uma transcricao leva na CPU compartilhada da demo.

Por que falar o protocolo em vez de abrir o navegador
-----------------------------------------------------
A demo e uma pagina Streamlit: nao ha API para chamar, e o numero que interessa
e o do caminho do visitante, do clique em Transcrever ate o texto na tela. Este
cliente faz exatamente esse caminho pelo websocket que a propria pagina usa:

1. conecta em /_stcore/stream com o subprotocolo "streamlit";
2. pede a URL de upload por um `file_urls_request` (BackMsg);
3. envia o arquivo em multipart, que e o que o handler do Streamlit espera;
4. manda um rerun com o estado do file_uploader preenchido, o que habilita o
   botao -- e depois outro com `trigger_value` no widget do botao, que E o
   clique;
5. le os ForwardMsg ate aparecer o text_area do resultado.

O cronometro comeca no envio do clique e para quando o texto chega. As metricas
que a propria tela desenha (duracao, segmentos, palavras) sao lidas junto e
servem de conferencia: sem elas, uma transcricao truncada passaria por rapida.

Duas armadilhas que custaram tentativas, registradas para nao se repetirem:

- o upload precisa sair do laco de eventos (asyncio.to_thread). Enviado de forma
  bloqueante, o websocket para de responder ao ping, o servidor derruba a sessao
  e o upload volta com 400 "Invalid session_id" -- que parece erro de sessao e e
  erro de concorrencia;
- `script_finished` chega varias vezes numa transcricao, porque a tela faz
  st.rerun() duas vezes no caminho. So o codigo 0 (FINISHED_SUCCESSFULLY) fecha
  a conta; os reruns chegam como 2 (FINISHED_EARLY_FOR_RERUN).

Uso:
    python medir_demo.py aula.mp3
    python medir_demo.py aula.mp3 --repeticoes 3
    python medir_demo.py aula.mp3 --host meu-space.hf.space

A primeira medicao de um container frio sai mais lenta: o modelo ainda nao esta
no lru_cache de carregar_modelo(). Com --repeticoes, descarte a primeira.
"""

import argparse
import asyncio
import os
import sys
import time
import uuid

import requests
import websockets
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from streamlit.proto.Markdown_pb2 import Markdown

HOST_PADRAO = 'mvaraujo1977-transcricao-audio.hf.space'

# O rotulo do campo de texto do resultado, em app.py. E o que marca "o resultado
# apareceu na tela", que e onde o cronometro para.
ROTULO_RESULTADO = 'Texto transcrito'

# Codigo de ScriptFinishedStatus que significa "terminou mesmo". Os reruns da
# tela chegam com outros codigos e nao podem fechar a medicao.
FINISHED_SUCCESSFULLY = 0

# element_type do st.caption dentro do proto de markdown. Vem do enum, nao de um
# numero escrito a mao: LATEX e que e 4, e com o valor errado a legenda sumia em
# silencio -- o `elif` simplesmente nunca casava.
MARKDOWN_CAPTION = Markdown.Type.CAPTION


def _esquema(host):
    """ws:// para a instalacao local, wss:// para a demo publica.

    A mesma ferramenta serve aos dois: medir a demo no Space e medir o container
    na maquina, que e o numero que interessa a quem vai instalar isto. O
    container publica em http simples no loopback, sem TLS.
    """
    nome = host.split(':')[0].lower()
    return 'ws' if nome in ('localhost', '127.0.0.1', '::1') else 'wss'


def _endereco_http(host):
    return "{0}://{1}".format('http' if _esquema(host) == 'ws' else 'https', host)


class Tela:
    """Junta o que os ForwardMsg contam sobre a tela do outro lado."""

    def __init__(self):
        self.sessao = None
        self.uploader = None
        self.max_upload_mb = None
        self.botoes = {}
        self.selectbox = {}
        self.legendas = []
        self.textos = []
        self.metricas = {}
        self.alertas = []
        self.resultado_em = None
        self.texto = None

    def absorver(self, msg, tipo):
        if tipo == 'new_session':
            self.sessao = msg.new_session.initialize.session_id
            return
        if tipo != 'delta' or msg.delta.WhichOneof('type') != 'new_element':
            return

        elemento = msg.delta.new_element
        qual = elemento.WhichOneof('type')
        if qual == 'file_uploader':
            self.uploader = elemento.file_uploader.id
            self.max_upload_mb = elemento.file_uploader.max_upload_size_mb
        elif qual == 'button':
            self.botoes[elemento.button.label] = elemento.button.id
        elif qual == 'selectbox':
            self.selectbox[elemento.selectbox.label] = list(elemento.selectbox.options)
        elif qual == 'markdown':
            if elemento.markdown.element_type == MARKDOWN_CAPTION:
                self.legendas.append(elemento.markdown.body)
            else:
                self.textos.append(elemento.markdown.body)
        elif qual == 'metric':
            self.metricas[elemento.metric.label] = elemento.metric.body
        elif qual == 'alert':
            self.alertas.append(elemento.alert.body)
        elif qual == 'exception':
            self.alertas.append('EXCECAO: ' + elemento.exception.message)
        elif qual == 'text_area' and elemento.text_area.label == ROTULO_RESULTADO:
            if self.resultado_em is None:
                self.resultado_em = time.monotonic()
                self.texto = elemento.text_area.default or elemento.text_area.value


async def _ler_ate_o_fim(ws, tela, timeout):
    """Le ForwardMsg ate o script terminar de verdade; devolve o instante."""
    while True:
        bruto = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = ForwardMsg()
        msg.ParseFromString(bruto)
        tipo = msg.WhichOneof('type')
        tela.absorver(msg, tipo)
        if tipo == 'script_finished' and msg.script_finished == FINISHED_SUCCESSFULLY:
            return time.monotonic()


async def _pedir_urls(ws, sessao, nome):
    """Pede ao servidor onde depositar o arquivo, como o navegador faz."""
    pedido = BackMsg()
    pedido.file_urls_request.request_id = str(uuid.uuid4())
    pedido.file_urls_request.file_names.append(nome)
    pedido.file_urls_request.session_id = sessao
    await ws.send(pedido.SerializeToString())

    while True:
        bruto = await asyncio.wait_for(ws.recv(), timeout=60)
        msg = ForwardMsg()
        msg.ParseFromString(bruto)
        if msg.WhichOneof('type') == 'file_urls_response':
            if msg.file_urls_response.error_msg:
                raise SystemExit("o servidor recusou o upload: {0}".format(
                    msg.file_urls_response.error_msg))
            return msg.file_urls_response.file_urls[0]


def _sessao_com_xsrf(host):
    """Sessao HTTP ja com o cookie de XSRF, quando o servidor exige um.

    A protecao XSRF do Streamlit fica LIGADA na instalacao local e desligada na
    demo publica -- o cookie nao sobrevive ao iframe do Spaces. Sem o token, o
    upload local volta 403 "XSRF token missing or invalid".

    Quem entrega o cookie e /_stcore/health, nao a raiz. O token vai depois no
    cabecalho X-Xsrftoken, e o cookie acompanha pela propria sessao: o servidor
    compara os dois.
    """
    sessao = requests.Session()
    try:
        sessao.get(_endereco_http(host) + '/_stcore/health', timeout=15)
    except requests.RequestException:
        pass  # sem cookie o upload so falha se a protecao estiver mesmo ligada
    return sessao


async def _enviar_arquivo(host, sessao, urls, nome, dados):
    """Sobe o arquivo em multipart, fora do laco de eventos."""
    alvo = urls.upload_url
    if alvo.startswith('/'):
        alvo = _endereco_http(host) + alvo

    token = sessao.cookies.get('_streamlit_xsrf')
    cabecalhos = {'X-Xsrftoken': token} if token else {}

    def enviar():
        # multipart porque o handler do Streamlit le request.form(); em thread
        # separada porque bloquear o laco de eventos mata o ping do websocket, e
        # sem ping o servidor descarta a sessao antes de o upload chegar.
        return sessao.put(alvo, files={'file': (nome, dados, 'application/octet-stream')},
                          headers=cabecalhos, timeout=600)

    resposta = await asyncio.to_thread(enviar)
    if resposta.status_code >= 400:
        raise SystemExit("upload falhou: HTTP {0} -- {1}".format(
            resposta.status_code, resposta.text[:300]))
    return resposta.status_code


def _preencher_uploader(back, uploader_id, urls, nome, tamanho):
    """Poe o arquivo no estado do file_uploader, que e o que o clique enxerga."""
    estado = back.rerun_script.widget_states.widgets.add()
    estado.id = uploader_id
    info = estado.file_uploader_state_value.uploaded_file_info.add()
    info.name = nome
    info.size = tamanho
    info.file_id = urls.file_id
    info.file_urls.file_id = urls.file_id
    info.file_urls.upload_url = urls.upload_url
    info.file_urls.delete_url = urls.delete_url


async def medir(host, caminho, mostrar_tela=True):
    """Roda uma transcricao na demo e devolve os segundos do clique ao resultado."""
    nome = os.path.basename(caminho)
    with open(caminho, 'rb') as arquivo:
        dados = arquivo.read()

    tela = Tela()
    sessao = _sessao_com_xsrf(host)
    url = "{0}://{1}/_stcore/stream".format(_esquema(host), host)
    async with websockets.connect(url, subprotocols=['streamlit'], max_size=None,
                                  open_timeout=60, ping_interval=20) as ws:
        # Um rerun vazio e o que faz o servidor executar a tela pela primeira
        # vez: conectar sozinho nao dispara nada.
        await ws.send(BackMsg(rerun_script=BackMsg().rerun_script).SerializeToString())
        await _ler_ate_o_fim(ws, tela, timeout=300)

        if tela.uploader is None or 'Transcrever' not in tela.botoes:
            raise SystemExit("a tela nao trouxe uploader e botao Transcrever; "
                             "o Space esta no ar?")
        if mostrar_tela:
            print("  teto de upload : {0} MB".format(tela.max_upload_mb))
            print("  modelos        : {0}".format(tela.selectbox.get('Modelo')))
            for legenda in tela.legendas:
                if 'Upload' in legenda:
                    print("  legenda        : {0}".format(legenda))

        urls = await _pedir_urls(ws, tela.sessao, nome)
        inicio_upload = time.monotonic()
        await _enviar_arquivo(host, sessao, urls, nome, dados)
        if mostrar_tela:
            print("  upload         : {0:.1f} MB em {1:.1f} s".format(
                len(dados) / 1e6, time.monotonic() - inicio_upload))

        # Um rerun so com o arquivo: habilita o botao sem clicar nele.
        back = BackMsg()
        _preencher_uploader(back, tela.uploader, urls, nome, len(dados))
        await ws.send(back.SerializeToString())
        await _ler_ate_o_fim(ws, tela, timeout=300)

        # O CLIQUE. O arquivo vai junto porque cada rerun manda o estado inteiro
        # dos widgets: sem ele, o uploader voltaria vazio e nao haveria o que
        # transcrever.
        back = BackMsg()
        _preencher_uploader(back, tela.uploader, urls, nome, len(dados))
        gatilho = back.rerun_script.widget_states.widgets.add()
        gatilho.id = tela.botoes['Transcrever']
        gatilho.trigger_value = True

        tela.resultado_em = None
        clique = time.monotonic()
        await ws.send(back.SerializeToString())
        fim = await _ler_ate_o_fim(ws, tela, timeout=3600)

    if tela.alertas:
        raise SystemExit("a demo respondeu com erro: {0}".format(' | '.join(tela.alertas)))
    if tela.resultado_em is None:
        raise SystemExit("o script terminou sem desenhar o resultado")

    return tela.resultado_em - clique, fim - clique, tela


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Cronometra uma transcricao na demo publica, do clique ao resultado.")
    parser.add_argument('arquivo', help="audio ou video a enviar para a demo")
    parser.add_argument('--host', default=HOST_PADRAO,
                        help="host da demo (padrao: {0})".format(HOST_PADRAO))
    parser.add_argument('--repeticoes', type=int, default=1, metavar='N',
                        help="mede N vezes; descarte a primeira num container frio")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.arquivo):
        print("Arquivo nao encontrado: {0}".format(args.arquivo), file=sys.stderr)
        return 1

    print("demo    : {0}".format(args.host))
    print("arquivo : {0}".format(os.path.basename(args.arquivo)))

    tempos = []
    for rodada in range(1, args.repeticoes + 1):
        if args.repeticoes > 1:
            print("\nmedicao {0} de {1}".format(rodada, args.repeticoes))
        try:
            ate_resultado, ate_desenhar, tela = asyncio.run(
                medir(args.host, args.arquivo, mostrar_tela=(rodada == 1)))
        except SystemExit as erro:
            print("Erro: {0}".format(erro), file=sys.stderr)
            return 1

        tempos.append(ate_resultado)
        duracao = tela.metricas.get('Duração') or tela.metricas.get('Duracao')
        print("  DO CLIQUE AO RESULTADO: {0:.1f} s".format(ate_resultado))
        print("  tela completa em      : {0:.1f} s".format(ate_desenhar))
        print("  audio transcrito      : {0} | {1} segmentos | {2} palavras".format(
            duracao, tela.metricas.get('Segmentos'), tela.metricas.get('Palavras')))

    if len(tempos) > 1:
        print("\nresumo: {0} | mediana {1:.1f} s".format(
            ', '.join("{0:.1f} s".format(t) for t in tempos),
            sorted(tempos)[len(tempos) // 2]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
