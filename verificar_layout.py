"""Carrega a tela do Streamlit nos tres estados e confere o que cada um mostra.

Usa o AppTest, que roda app.py sem navegador: nenhuma transcricao de verdade
acontece aqui -- o estado RESULTADO e montado direto no session_state, que e o
mesmo caminho que a transcricao real usa para sobreviver aos reruns.

Uso: python verificar_layout.py
"""

import sys

from streamlit.testing.v1 import AppTest

TEXTO = (
    "Bom dia a todos. Na aula de hoje vamos fechar o estudo dos principios da "
    "administracao publica, que caem em praticamente todas as bancas.\n\n"
    "Comecemos pela legalidade. Para o administrador publico, so se pode fazer "
    "aquilo que a lei autoriza."
)

falhas = []


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
    print("ESTADO VAZIO (nada enviado)")
    vazio = AppTest.from_file('app.py', default_timeout=60)
    vazio.run()
    conferir(not vazio.exception, "roda sem excecao")
    conferir([t.value for t in vazio.title] == ["Transcrição de áudio"],
             "titulo na tela")
    conferir(len(vazio.file_uploader) == 1, "uploader presente")
    conferir([e.label for e in vazio.expander] == ["Opções avançadas"],
             "opcoes avancadas recolhidas num expander")
    conferir(len(vazio.button) == 1 and vazio.button[0].disabled,
             "botao Transcrever desabilitado sem arquivo")
    conferir(len(vazio.metric) == 0 and len(vazio.download_button) == 0,
             "nada de resultado na tela")

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

    print("-" * 60)
    if falhas:
        print("{0} FALHA(S):".format(len(falhas)))
        for descricao in falhas:
            print("  - {0}".format(descricao))
        return 1
    print("tres estados conferidos, sem falha")
    return 0


if __name__ == '__main__':
    sys.exit(main())
