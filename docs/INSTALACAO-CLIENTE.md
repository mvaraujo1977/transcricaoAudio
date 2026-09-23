# Instalar na máquina de um cliente

Como esta aplicação chega a um computador que não é o seu, e o que responder
quando o cliente perguntar sobre licença. O guia que o **cliente** recebe é
outro: [GUIA-DO-CLIENTE.md](GUIA-DO-CLIENTE.md), sem jargão e sem comando.

## O pacote

A pasta `cliente/` tem o que vai para a máquina dele:

| Arquivo | Para quê |
|---|---|
| `instalar.bat` | duplo clique, uma vez; casca fina sobre o `.ps1` |
| `instalar.ps1` | carrega a imagem, sobe o serviço, cria o atalho |
| `transcricao.ico` | ícone do atalho principal |
| `transcricao-planoB.ico` | ícone do atalho secundário |
| `Se nao abrir - clique aqui.bat` | plano B, para quando o Docker ainda está acordando |

E mais dois que **ficam no repositório**: são ferramentas de quem monta o
pacote, não teriam função na máquina do cliente e exigiriam Python instalado
lá. O cliente recebe o que eles produzem, não a receita:

| Arquivo | Para quê |
|---|---|
| `gerar_icones.py` | gera os dois `.ico` |
| `gerar_guia_pdf.py` | gera o PDF do guia a partir de `docs/GUIA-DO-CLIENTE.md` |

O pacote montado, então, leva os cinco arquivos da primeira tabela mais o
`docker-compose.yml` (sem a linha `build:`), o `.tar` da imagem, o PDF do guia,
uma pasta `dados/` e um aviso em texto pedindo que a pasta não seja movida.

## De onde vem a imagem

**Entregue o `.tar`.** Na prática quem o gera é o `montar-pacote.ps1`, na raiz
do repositório — ele constrói a imagem a partir de um clone limpo, sobe um
container de validação, e só então salva. Os comandos por baixo são estes:

```bash
docker compose build
docker save transcricao-audio:1.0 -o cliente/transcricao-audio.tar
```

São **838 MB** — cabe em qualquer pen drive, e comprimir não adianta (as camadas
da imagem já estão comprimidas; `gzip` tirou 1 MB de 838). O `instalar.ps1`
carrega o `.tar` sozinho se ele estiver na pasta.

O `docker-compose.yml` fixa `image: transcricao-audio:1.0`. Isso não é detalhe:
sem a linha, o Compose deriva o nome da imagem do **nome da pasta** do projeto,
e na máquina do cliente — onde a pasta pode se chamar qualquer coisa — o nome
não bateria com o da imagem carregada do `.tar`. O Compose não a encontraria e
tentaria construir, que é exatamente o que o `.tar` existe para evitar, e que
falha numa máquina sem internet.

As alternativas perdem por motivos concretos:

**Construir na máquina do cliente** exige rede aberta para o PyPI *e* para o
Hugging Face — são ~625 MB de modelo baixados durante o build. O problema não é
o tempo: é que o público-alvo desta ferramenta é justamente quem tem rede
corporativa fechada. Escritório de advocacia e clínica são exatamente as
máquinas com proxy que bloqueia domínio desconhecido. E há o desconforto de
imagem: a ferramenta que se vende como "não manda nada para a nuvem" passaria a
instalação baixando coisas da nuvem.

**Docker Hub** funciona e é grátis em repositório público — e não há segredo na
imagem, já que o código é MIT. Mas continua dependendo de rede aberta para o
`docker.io` na hora da instalação. Repositório privado é pior: exige
`docker login` na máquina do cliente, ou seja, uma credencial sua morando lá,
para resolver um problema que não existe.

O `.tar` instala numa máquina sem internet nenhuma. Isso deixa de ser contorno e
vira argumento: *instala sem internet, e depois roda sem internet*.

## Armadilhas que o teste de instalação revelou

Quatro coisas quebraram numa instalação real. Ficam registradas porque nenhuma
aparece lendo o código.

**Fim de linha.** Com `core.autocrlf=true` — padrão em muita instalação do Git
no Windows — um `git checkout` reescreve a árvore com CRLF, o `COPY . .` leva
isso para dentro da imagem, e o `/bin/sh` aborta em `set -e\r`. O container
entra em loop de reinício. Resolvido pelo `.gitattributes`, que fixa LF na
origem. Sem ele, qualquer clone no Windows produz imagem quebrada.

**Nome da imagem.** O Compose deriva o nome do diretório do projeto. Na pasta
do cliente, com outro nome, ele não acha a imagem do `.tar` e tenta construir.
Resolvido fixando `image:` no compose.

**Acento no PowerShell.** O Windows PowerShell 5.1 — o que vem no Windows — lê
`.ps1` como ANSI quando o arquivo não começa com BOM de UTF-8. Sem o BOM, o
atalho nasce na Área de Trabalho chamado `TranscriÃ§Ã£o de Ã¡udio.url`. O
`instalar.ps1` é gravado com BOM, e há um aviso no topo dele para não
removerem.

**Ícone em `.bat`.** Um `.bat` na Área de Trabalho carrega o ícone genérico de
engrenagem do Windows: o formato não guarda ícone próprio. Por isso o `.bat`
fica na pasta de instalação e o que vai para a mesa é um `.lnk` apontando para
ele — `.lnk` guarda `IconLocation`. Os dois atalhos usam ícones da mesma
família, para a Área de Trabalho mostrar um programa só.

Sobre o desenho dos ícones: o tamanho que importa é **16 px**, não o 256 do
preview. Uma onda com sete barras finas virava mancha cinza ali; três barras
grossas ficavam legíveis mas o ícone lia como um **rosto** (três elementos em
cima, barra horizontal embaixo). O que sobreviveu aos dois testes foi a onda
como traço contínuo. O `gerar_icones.py` registra esse caminho em comentário.

Vale notar que a Área de Trabalho pode estar redirecionada para o OneDrive
(`C:\Users\<user>\OneDrive\Área de Trabalho`). O instalador usa
`[Environment]::GetFolderPath('Desktop')`, que resolve os dois casos — não
monte o caminho à mão.

## Armadilhas de montar o pacote

A pasta de entrega é montada pelo `montar-pacote.ps1`, na raiz do repositório:
ele constrói a imagem a partir de um clone limpo, sobe um container de
validação, gera o `.tar` e copia para `pacote-cliente/` só o que vai para a
máquina do cliente. Escrever esse script revelou seis coisas — cinco sobre
PowerShell, e duas delas afetam também o que o cliente recebe.

**A política de execução barra `.ps1` que veio de fora.** Com `RemoteSigned`,
que é o padrão em boa parte das instalações, um `.ps1` marcado como baixado da
internet só roda se estiver assinado digitalmente; sem assinatura, o PowerShell
recusa com `UnauthorizedAccess`. A marca vem junto com o arquivo, então
`Unblock-File` resolve, ou `-ExecutionPolicy Bypass` na chamada. **Isso não é só
do script de montagem:** o pacote chega ao cliente por pen drive ou download, e
o `instalar.ps1` carrega a mesma marca. O `instalar.bat` precisa chamá-lo com
`-ExecutionPolicy Bypass`, senão a instalação morre no primeiro clique com um
texto em vermelho que o cliente não tem como interpretar.

**`.ps1` sem BOM lido como ANSI quebra o parser, não só os acentos.** Isto
estende o que está registrado acima sobre o nome do atalho. O terceiro byte de
um travessão em UTF-8 é `0x94`, que na tabela ANSI é a aspa tipográfica de
fechamento — e o PowerShell aceita aspa tipográfica como delimitador de string.
As strings passam a começar e terminar no lugar errado, as chaves são engolidas
para dentro delas, e o script falha com `Token '}' inesperado` numa linha que
não tem defeito nenhum. Ou seja: sem BOM, um comentário com travessão derruba o
arquivo inteiro. Ou se grava com BOM, ou se escreve o `.ps1` em ASCII puro. O
`montar-pacote.ps1` optou pelo ASCII e diz isso no próprio cabeçalho.

**Variável seguida de dois-pontos vira qualificador de unidade.** `"porta
$porta: a da validação"` não compila: o PowerShell lê `$porta:` como referência
a uma unidade, do mesmo jeito que em `$env:TEMP`. A forma correta é
`${porta}:`. Erro fácil de cometer e de diagnosticar mal, porque a mensagem
fala de "referência de variável inválida" e aponta o caractere, não a intenção.

**Programa externo que falha não lança exceção.** Um `try/catch` em volta de
`docker version` nunca é acionado: o comando escreve no stderr e devolve código
de saída, e o `catch` fica inerte. A primeira versão do script tinha exatamente
isso e imprimia `[ok] Docker respondendo` com o Docker fechado e o erro do named
pipe visível na tela logo acima. A verificação tem que ser no `$LASTEXITCODE`.

**Com `$ErrorActionPreference = 'Stop'`, stderr de programa externo vira erro
terminante — e o `2>$null` é o gatilho, não a proteção.** O caso concreto:
`docker rm -f` de um container que não existe escreve `No such container`, que
é justamente o resultado esperado de uma limpeza preventiva, e o script morria
ali. A saída é isolar as chamadas externas numa função que baixa a preferência
para `Continue` só dentro do bloco e a restaura depois, mantendo o
`$LASTEXITCODE` disponível para quem chamou.

**`container_name` fixo colide entre projetos — e a colisão passa despercebida.**
O `docker-compose.yml` fixa `container_name: transcricao`, o que é correto para
o cliente. Mas rodar o compose a partir do clone temporário, com a instância de
desenvolvimento no ar, esbarra em `Conflict. The container name "/transcricao"
is already in use`. O pior não é a falha: é que o `docker inspect transcricao`
seguinte **encontra o container antigo**, reporta `running`, e a validação passa
sem ter testado nada da imagem recém-construída. A etapa de validação por isso
não usa o compose — sobe a imagem com `docker run`, sob o nome
`transcricao-validacao` e na porta 8599, e remove o container ao final. Ela
valida a imagem (entrypoint, fim de linha), que é o que o `.tar` carrega; o
compose é validado na máquina do cliente.

**Uma ressalva sobre o build.** Com o cache quente, o `docker compose build`
termina em segundos e as camadas de `pip install` e de download do modelo saem
como `CACHED`. A imagem fica correta, mas essa execução não prova que o build
funciona numa máquina limpa. Antes de uma entrega que importe, vale uma rodada
com `--no-cache`: demora, e é o que confirma que o lockfile ainda resolve e que
o modelo ainda baixa.

---

## Se o cliente cair na faixa que exige Docker Desktop pago

O **Docker Desktop** exige assinatura para empresas com mais de 250 funcionários
**ou** mais de US$ 10 milhões de faturamento anual. Escritório pequeno e clínica
ficam fora; um cliente grande, não.

O que é pago é **só o Docker Desktop** — o aplicativo de janela, com a baleia na
bandeja. O motor que roda os containers é open source e gratuito em qualquer
tamanho de empresa. As saídas, da mais simples à mais trabalhosa:

### 1. Podman Desktop — a troca mais direta

Apache 2.0, sem cláusula de tamanho de empresa. Instala com instalador gráfico,
tem interface parecida e entende `docker-compose.yml`.

**O que muda para o cliente:** nada no uso diário. O atalho continua sendo o
mesmo `.url`, a tela é a mesma, o navegador é o mesmo.

**O que muda para você:** os comandos do `instalar.ps1` viram `podman` em vez de
`docker` (`podman load`, `podman compose up -d`), e o plano B usa
`podman start`. O reinício automático precisa ser configurado: no Podman o
`restart: unless-stopped` do compose não basta sozinho — é preciso gerar um
serviço de usuário para o container subir no login.

**Ressalva honesta:** o `podman compose` no Windows é menos rodado que o
`docker compose`. Testar antes de prometer numa reunião.

### 2. Docker Engine no WSL2 — o mesmo motor, sem a janela

O Docker Engine é Apache 2.0 e não tem restrição de empresa. Instala-se dentro
do WSL2 (o Linux que o Windows já traz), sem o Docker Desktop por cima.

**O que muda para o cliente:** nada, se você deixar configurado. O container
sobe com o WSL e o atalho funciona igual.

**O que muda para você:** a instalação deixa de ser "duplo clique" e passa a
exigir linha de comando dentro do WSL, mais um ajuste para o serviço subir no
login do Windows. É a opção que mais trabalho dá para configurar e a que menos
diferença faz depois de configurada.

### 3. Sem container, Python direto na máquina

Instalar Python e as dependências do `requirements.lock.txt`, e rodar o
Streamlit como serviço do Windows.

**O que muda para o cliente:** nada de licença nenhuma — some o Docker da
conversa. Em troca, a aplicação passa a dividir o Python com o resto da máquina.

**O que muda para você:** some a garantia que o container dá. O modelo (~480 MB
do `small`) precisa ser baixado ou copiado à mão, a versão do Python da máquina
do cliente passa a importar, e qualquer conflito de dependência vira chamado de
suporte seu. O `av` (PyAV) traz os codecs compilados, o que ajuda, mas não
elimina o risco.

Também é o caminho para um dia empacotar com PyInstaller num `.exe` — aí a
instalação vira mesmo um instalador comum e o Docker desaparece do vocabulário.
É projeto à parte, não ajuste de configuração.

### Resumo para a reunião

| Caminho | Licença | Instalação | Uso diário do cliente |
|---|---|---|---|
| Docker Desktop | paga acima de 250 func. / US$ 10 mi | duplo clique | idêntico |
| **Podman Desktop** | **livre (Apache 2.0)** | **duplo clique** | **idêntico** |
| Docker Engine no WSL2 | livre (Apache 2.0) | linha de comando | idêntico |
| Python direto | livre | média, e frágil | idêntico |

**A resposta curta, se a pergunta aparecer:** *"Se a licença do Docker Desktop
for um problema aí, a gente troca por Podman, que é livre e não tem essa
cláusula. Para quem usa não muda nada — mesmo atalho, mesma tela."*

Em todos os quatro caminhos a aplicação é a mesma e o áudio continua sem sair da
máquina. O que muda é só quem segura o container de pé.
