"""Publica a demo no Hugging Face Spaces.

O Space é um repositório à parte, com README próprio: o de lá é uma página de
demo curta (e precisa do frontmatter YAML que o Spaces exige), enquanto o do
GitHub é a apresentação do projeto. Os dois vivem neste repositório --
`README.md` na raiz e `deploy/space/README.md` -- e este script monta a árvore
que o Space recebe, sem duplicar conteúdo.

O Space roda com SDK Docker: é a MESMA imagem da instalação local, com o modelo
embutido e os limites de demo aplicados pelo entrypoint quando SPACE_ID existe.
Sobe o necessário para o build acontecer lá -- Dockerfile, entrypoint, lockfile,
a tela Streamlit, o motor, o gerador de PDF, o tema, o áudio de exemplo e a
licença --, mais o README com o frontmatter que o Spaces exige. Fica de fora o
que é do repositório e não do Space: docs/, verificadores, dados/.

Uso:
    python deploy/publicar_space.py                  # publica
    python deploy/publicar_space.py --ensaio         # só mostra o que iria
    python deploy/publicar_space.py --space usuario/nome

Autenticação: `hf auth login` (o token fica no cache do huggingface_hub) ou a
variável de ambiente HF_TOKEN.
"""

import argparse
import os
import shutil
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPACE_PADRAO = 'mvaraujo1977/transcricao-audio'

# origem no repositório -> caminho no Space
ARQUIVOS = {
    'Dockerfile': 'Dockerfile',
    'entrypoint.sh': 'entrypoint.sh',
    'requirements.lock.txt': 'requirements.lock.txt',
    'app.py': 'app.py',
    '.streamlit/config.toml': '.streamlit/config.toml',
    'audioTranscricao.py': 'audioTranscricao.py',
    'gerar_pdf.py': 'gerar_pdf.py',
    'LICENSE': 'LICENSE',
    'exemplos/exemplo-o-alienista.mp3': 'exemplos/exemplo-o-alienista.mp3',
    'exemplos/CREDITOS.md': 'exemplos/CREDITOS.md',
    'deploy/space/README.md': 'README.md',
}

# Restos da fase Gradio, que o Space precisa perder na migração para Docker.
APAGAR_NO_SPACE = ['app_gradio.py', 'requirements.txt']


def montar(destino):
    """Copia a árvore que o Space recebe e devolve a lista de caminhos."""
    enviados = []
    for origem, alvo in sorted(ARQUIVOS.items()):
        caminho_origem = os.path.join(RAIZ, origem)
        if not os.path.isfile(caminho_origem):
            raise SystemExit("faltando no repositório: {0}".format(origem))
        caminho_alvo = os.path.join(destino, alvo)
        os.makedirs(os.path.dirname(caminho_alvo), exist_ok=True)
        shutil.copy2(caminho_origem, caminho_alvo)
        enviados.append((origem, alvo, os.path.getsize(caminho_origem)))
    return enviados


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--space', default=SPACE_PADRAO, help="usuario/nome do Space")
    parser.add_argument('--ensaio', action='store_true',
                        help="mostra o que seria enviado e não envia nada")
    parser.add_argument('--mensagem', default="Publica a demo a partir do repositório",
                        help="mensagem do commit no Space")
    args = parser.parse_args()

    pasta = tempfile.mkdtemp(prefix='space_')
    try:
        enviados = montar(pasta)
        print("Arvore que o Space recebe ({0}):".format(args.space))
        for origem, alvo, tamanho in enviados:
            seta = '=' if origem == alvo else '->'
            print("  {0:38s} {1} {2:32s} {3:>8.1f} KB".format(
                origem, seta, alvo, tamanho / 1024.0))

        if args.ensaio:
            print("\nensaio: nada foi enviado")
            return 0

        from huggingface_hub import HfApi
        api = HfApi()
        quem = api.whoami()
        print("\nautenticado como: {0}".format(quem.get('name')))
        url = api.upload_folder(
            folder_path=pasta,
            repo_id=args.space,
            repo_type='space',
            commit_message=args.mensagem,
            # Apaga do Space o que saiu daqui, para o repositório de lá não
            # acumular restos de publicações anteriores -- incluindo os arquivos
            # da fase Gradio, que o SDK Docker não usa.
            delete_patterns=['*.py', '*.txt', '*.md', 'exemplos/*'] + APAGAR_NO_SPACE,
        )
        print("publicado: {0}".format(url))
        print("acompanhe o build em: https://huggingface.co/spaces/{0}".format(args.space))
        return 0
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
