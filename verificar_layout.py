"""Carrega a tela do Streamlit nos tres estados e confere o que cada um mostra.

Usa o AppTest, que roda app.py sem navegador: nenhuma transcricao de verdade
acontece aqui -- o estado RESULTADO e montado direto no session_state, que e o
mesmo caminho que a transcricao real usa para sobreviver aos reruns.

O cancelamento e testado com uma transcrever() falsa que levanta a mesma excecao
que o Streamlit usa para interromper o script quando um clique chega, a
RerunException. E o unico jeito de exercitar esse caminho sem navegador.

Uso: python verificar_layout.py
"""

import io
import os
import sys
import tempfile
import wave

import audioTranscricao
from streamlit.runtime.scriptrunner_utils.exceptions import RerunException
from streamlit.runtime.scriptrunner_utils.script_requests import RerunData
from streamlit.testing.v1 import AppTest

# O mesmo prefixo que app.PREFIXO_TEMPORARIO usa nos temporarios. Repetido aqui
# para nao importar app.py, que e um script do Streamlit: importa-lo executaria
# a tela inteira fora de um run e encheria a saida de avisos.
PREFIXO_TEMPORARIO = 'transcricaoAudio_'

TEXTO = (
    "Bom dia a todos. Na aula de hoje vamos fechar o estudo dos principios da "
    "administracao publica, que caem em praticamente todas as bancas.\n\n"
    "Comecemos pela legalidade. Para o administrador publico, so se pode fazer "
    "aquilo que a lei autoriza."
)

DURACAO_FALSA = 2247.0

falhas = []


def wav_de_teste():
    """Um wav minimo, so para o uploader ter um arquivo de verdade para gravar."""
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(16000)
        arquivo.writeframes(b'\x00\x00' * 1600)
    return buffer.getvalue()


def temporarios_nossos():
    """Temporarios desta aplicacao que existem agora."""
    try:
        return {nome for nome in os.listdir(tempfile.gettempdir())
                if nome.startswith(PREFIXO_TEMPORARIO)}
    except OSError:
        return set()


def segmentos_falsos(quantidade):
    return [audioTranscricao.Segmento(
        indice * 30.0, (indice + 1) * 30.0,
        "Trecho {0} da aula, com pontuacao no fim.".format(indice + 1))
        for indice in range(quantidade)]


def transcrever_falsa(segmentos, cancelar_em=None):
    """Imita transcrever(): canta progresso, entrega segmentos e pode ser cortada.

    `cancelar_em` diz depois de quantos segmentos o script e interrompido --
    0 corta ainda na fase de preparo. O corte reproduz o que o Streamlit faz
    quando o clique em Cancelar chega: o callback do botao marca o pedido e a
    RerunException interrompe o script na chamada seguinte.
    """
    import streamlit as st

    def falsa(caminho, text_output_path=None, idioma="pt-BR", modelo='small',
              progresso=None, vocabulario=None, max_horas=None, ao_segmento=None):
        def cortar():
            if st.session_state.get('execucao_ativa'):
                st.session_state['cancelado'] = True
            raise RerunException(RerunData())

        if progresso is not None:
            progresso(60.0, DURACAO_FALSA, audioTranscricao.FASE_PREPARO)
        if cancelar_em == 0:
            cortar()

        for indice, segmento in enumerate(segmentos):
            if ao_segmento is not None:
                ao_segmento(segmento)
            if progresso is not None:
                progresso(segmento.end, DURACAO_FALSA,
                          audioTranscricao.FASE_TRANSCRICAO)
            if cancelar_em is not None and indice + 1 >= cancelar_em:
                cortar()

        texto = '\n\n'.join(audioTranscricao.agrupar_em_paragrafos(segmentos))
        return audioTranscricao.Transcricao(texto, list(segmentos), DURACAO_FALSA, 'pt')

    return falsa


def app_com_arquivo():
    """AppTest com um arquivo ja escolhido no uploader, pronto para transcrever."""
    app = AppTest.from_file('app.py', default_timeout=120)
    app.run()
    app.file_uploader[0].set_value(('aula-principios.wav', wav_de_teste(), 'audio/wav'))
    app.run()
    return app


def conferir(condicao, descricao):
    """Registra o resultado de uma checagem e devolve o proprio booleano."""
    print("  [{0}] {1}".format('ok ' if condicao else 'FALHA', descricao))
    if not condicao:
        falhas.append(descricao)
    return condicao


def estado_com_resultado():
    """Roda app.py com o session_state de uma transcricao ja concluida."""
    app = AppTest.from_file('app.py', default_timeout=60)
    app.session_state['texto_editado'] = TEXTO
    app.session_state['segmentos'] = []
    app.session_state['duracao'] = 2247.0
    app.session_state['idioma_detectado'] = 'pt'
    app.session_state['nome_origem'] = 'aula-principios.mp3'
    app.session_state['idioma_escolhido'] = 'pt-BR'
    app.run()
    return app


def metrica(app, rotulo):
    """Valor da metrica com este rotulo, ou None."""
    for medida in app.metric:
        if medida.label == rotulo:
            return medida.value
    return None


def main():
    antes_de_tudo = temporarios_nossos()

    print("ESTADO VAZIO (nada enviado)")
    vazio = AppTest.from_file('app.py', default_timeout=60)
    vazio.run()
    conferir(not vazio.exception, "roda sem excecao")
    conferir([t.value for t in vazio.title] == ["Transcrição de áudio"],
             "titulo na tela")
    conferir(len(vazio.file_uploader) == 1, "uploader presente")
    conferir([e.label for e in vazio.expander] == ["Opções avançadas"],
             "opcoes avancadas recolhidas num expander")
    rotulos = [b.label for b in vazio.button]
    conferir(rotulos == ['Transcrever', 'Testar com exemplo'],
             "os dois botoes do estado vazio, nesta ordem")
    conferir(vazio.button[0].disabled, "Transcrever desabilitado sem arquivo")
    conferir(not vazio.button[1].disabled,
             "Testar com exemplo habilitado: nao depende de upload")
    conferir(len(vazio.metric) == 0 and len(vazio.download_button) == 0,
             "nada de resultado na tela")

    marcacoes = " ".join(m.value for m in vazio.markdown)
    legendas = " ".join(c.value for c in vazio.caption)
    conferir("Processamento local" in marcacoes and "Sem envio para a nuvem" in marcacoes,
             "diferencial em selo, fora do texto apagado")
    conferir([s.value for s in vazio.subheader] == ["Como funciona"],
             "faixa Como funciona presente")
    conferir(all(passo in marcacoes for passo in
                 ["1.] Envie o arquivo", "2.] Roda nesta máquina", "3.] Revise e baixe"]),
             "os tres passos, numerados na cor de destaque")
    conferir("até 200 MB" in legendas and "mp3" in legendas,
             "instrucoes do uploader em portugues, com o teto de upload")
    conferir("github.com/mvaraujo1977/transcricaoAudio" in legendas,
             "rodape com link para o repositorio")

    print("ESTADO RESULTADO (pos-transcricao)")
    pronto = estado_com_resultado()
    conferir(not pronto.exception, "roda sem excecao")
    conferir([m.label for m in pronto.metric] ==
             ['Duração', 'Idioma', 'Segmentos', 'Palavras'],
             "as quatro metricas, em uma linha")
    conferir(metrica(pronto, 'Duração') == '37:27', "duracao formatada em mm:ss")
    conferir(metrica(pronto, 'Idioma') == 'pt', "idioma detectado")
    conferir(metrica(pronto, 'Palavras') == str(len(TEXTO.split())),
             "contagem de palavras do texto")
    conferir(any(t.label == 'Texto transcrito' and t.value == TEXTO
                 for t in pronto.text_area), "texto transcrito editavel")
    conferir([d.label for d in pronto.download_button] == ['Baixar .txt', 'Baixar .pdf'],
             "os dois downloads, lado a lado")
    conferir(not any(d.disabled for d in pronto.download_button),
             "downloads habilitados com texto na tela")
    conferir([s.value for s in pronto.subheader] == ["Transcrição"],
             "faixa Como funciona some quando ha resultado")
    conferir([b.label for b in pronto.button] == ['Transcrever'],
             "botao de exemplo some quando ja ha transcricao")
    conferir(any("github.com/mvaraujo1977/transcricaoAudio" in c.value
                 for c in pronto.caption), "rodape continua no estado resultado")

    print("ESTADO RESULTADO (apos editar o texto)")
    editado = TEXTO + "\n\nParagrafo acrescentado na revisao, com seis palavras."
    depois = estado_com_resultado()
    depois.text_area(key='texto_editado').set_value(editado).run()
    conferir(not depois.exception, "roda sem excecao depois da edicao")
    conferir(depois.text_area(key='texto_editado').value == editado,
             "a edicao sobrevive ao rerun")
    conferir(metrica(depois, 'Palavras') == str(len(editado.split())),
             "contagem de palavras acompanha a edicao")
    conferir(metrica(depois, 'Duração') == '37:27',
             "metricas do audio nao mudam com a edicao")
    conferir(not any(d.disabled for d in depois.download_button),
             "downloads seguem habilitados (o PDF e gerado do texto editado)")

    print("BOTAO TESTAR COM EXEMPLO")
    conferir(os.path.isfile(os.path.join('exemplos', 'exemplo-o-alienista.mp3')),
             "o audio de exemplo esta no repositorio")
    original_exemplo = audioTranscricao.transcrever
    try:
        segmentos = segmentos_falsos(2)
        recebidos = []

        def espiar(caminho, *args, **kwargs):
            recebidos.append(caminho)
            return transcrever_falsa(segmentos)(caminho, *args, **kwargs)

        audioTranscricao.transcrever = espiar
        com_exemplo = AppTest.from_file('app.py', default_timeout=120)
        com_exemplo.run()
        com_exemplo.button[1].click().run()
        conferir(not com_exemplo.exception, "o exemplo roda sem excecao")
        conferir(bool(recebidos) and recebidos[0].endswith('exemplo-o-alienista.mp3'),
                 "transcreve o arquivo do repositorio, sem upload")
        conferir(com_exemplo.session_state.get('nome_origem') == 'exemplo-o-alienista.mp3',
                 "o nome do exemplo vai para os downloads")
        conferir(temporarios_nossos() <= antes_de_tudo,
                 "o exemplo nao deixa temporario: nao passa por upload")
    finally:
        audioTranscricao.transcrever = original_exemplo

    print("CANCELAMENTO (mecanismo)")
    conferir(issubclass(RerunException, BaseException)
             and not issubclass(RerunException, Exception),
             "RerunException herda de BaseException, nao de Exception")
    fonte_app = open('app.py', encoding='utf-8').read()
    conferir("finally" in fonte_app.split('def _transcrever_upload')[1].split('def ')[0],
             "_transcrever_upload apaga o temporario num finally")
    # st.status.update() sem `expanded` recolhe o painel, e recolhido o Streamlit
    # tira o conteudo do DOM: a barra, os numeros e o botao Cancelar somem da
    # tela justamente enquanto a transcricao corre. Isso nao aparece no AppTest,
    # que nao renderiza -- so no navegador --, entao fica checado na fonte.
    conferir(all('expanded=' in trecho[:240]
                 for trecho in fonte_app.split('status.update(label')[1:]),
             "todo status.update diz se o painel continua aberto")

    print("CANCELAMENTO durante a transcricao")
    original = audioTranscricao.transcrever
    try:
        antes = temporarios_nossos()
        segmentos = segmentos_falsos(4)
        audioTranscricao.transcrever = transcrever_falsa(segmentos, cancelar_em=2)
        cortado = app_com_arquivo()
        cortado.button[0].click().run()

        conferir(not cortado.exception, "roda sem excecao ate a tela voltar")
        conferir(temporarios_nossos() <= antes,
                 "temporario removido pelo finally, apesar do corte")
        conferir(cortado.session_state.get('processando') is False
                 and cortado.session_state.get('execucao_ativa') is False,
                 "nenhum estado preso em processando")
        conferir(cortado.session_state.get('parcial_ate') == segmentos[1].end,
                 "marca ate onde o texto parcial vai")
        parcial = cortado.text_area(key='texto_editado').value
        conferir(all(s.text in parcial for s in segmentos[:2])
                 and not any(s.text in parcial for s in segmentos[2:]),
                 "texto parcial tem o que foi reconhecido, e so isso")
        conferir(any("cancelada" in a.value.lower() for a in cortado.warning),
                 "aviso de transcricao cancelada, com o ponto de corte")
        conferir(cortado.file_uploader[0].value is not None,
                 "arquivo enviado continua no uploader, para recomecar sem reenviar")

        print("NOVA TRANSCRICAO DEPOIS DO CANCELAMENTO")
        audioTranscricao.transcrever = transcrever_falsa(segmentos)
        cortado.button[0].click().run()
        conferir(not cortado.exception, "a transcricao seguinte roda sem excecao")
        conferir(cortado.session_state.get('parcial_ate') is None
                 and not cortado.warning,
                 "o aviso de parcial some quando a transcricao completa")
        completo = cortado.text_area(key='texto_editado').value
        conferir(all(s.text in completo for s in segmentos),
                 "texto completo substitui o parcial")
        conferir(temporarios_nossos() <= antes, "nenhum temporario sobrou no caminho")

        print("CANCELAMENTO durante o preparo (antes do primeiro segmento)")
        audioTranscricao.transcrever = transcrever_falsa(segmentos, cancelar_em=0)
        cedo = app_com_arquivo()
        cedo.button[0].click().run()
        conferir(not cedo.exception, "roda sem excecao")
        conferir(temporarios_nossos() <= antes, "temporario removido tambem no preparo")
        conferir(any("cancelada" in i.value.lower() for i in cedo.info),
                 "mensagem neutra de cancelamento")
        conferir(len(cedo.metric) == 0 and len(cedo.download_button) == 0,
                 "sem texto parcial, a tela volta ao estado de entrada")
        conferir([s.value for s in cedo.subheader] == ["Como funciona"],
                 "faixa Como funciona de volta")
        conferir(cedo.file_uploader[0].value is not None,
                 "arquivo enviado preservado")
    finally:
        audioTranscricao.transcrever = original

    print("-" * 60)
    if falhas:
        print("{0} FALHA(S):".format(len(falhas)))
        for descricao in falhas:
            print("  - {0}".format(descricao))
        return 1
    print("tres estados e os dois cancelamentos conferidos, sem falha")
    return 0


if __name__ == '__main__':
    sys.exit(main())
