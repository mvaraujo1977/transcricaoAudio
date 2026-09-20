# Transcrição de Áudio

Transcreve arquivos de áudio e vídeo para texto usando o [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
que roda **localmente** — nada é enviado para serviços externos. Tem interface web
(Streamlit) e linha de comando, e o texto pode ser revisado na tela antes de ser
exportado em `.txt` ou `.pdf`.

A saída vem com pontuação, capitalização e parágrafos, além de timestamps por
segmento, que permitem marcar cada parágrafo do PDF com `[MM:SS]` para voltar ao
ponto exato do áudio.

## A tela

A interface tem três estados e mostra um de cada vez:

- **Vazio**: título, uma linha dizendo o que a ferramenta faz, o uploader e as
  opções avançadas recolhidas.
- **Processando**: os controles ficam desabilitados e um painel único reúne a
  barra de progresso, o tempo decorrido, a posição no áudio (`08:17 de 37:27`) e
  a estimativa do que falta. A estimativa vem do ritmo observado na própria
  execução — segundos de relógio por segundo de áudio —, e não de um número fixo
  por modelo, que erraria em máquina mais lenta.
- **Resultado**: uma linha com duração, idioma, segmentos e palavras; o texto
  transcrito editável; e os dois downloads lado a lado.

Cor, fonte e raio das bordas ficam em `.streamlit/config.toml`, com uma variante
da cor de destaque para o modo claro e outra para o escuro — sem `base` definido,
a tela segue a preferência do navegador. O menu e o botão Deploy saem pelo
`toolbarMode = "minimal"`, e o empilhamento das colunas em tela estreita é o
comportamento padrão do `st.columns`, abaixo de 640 px. Sobrou um único bloco de
CSS em `app.py`, para o espaçamento do bloco principal, e ele usa seletor
`[data-testid=...]`: as classes que o Streamlit gera mudam de nome a cada
atualização e não servem de apoio.

`verificar_layout.py` carrega a tela nos três estados com o AppTest, sem
navegador e sem transcrever nada:

```bash
python verificar_layout.py
```

## Com Docker (recomendado)

Sobe a interface em http://localhost:8501:

```bash
docker compose up -d
```

Para acompanhar os logs e derrubar:

```bash
docker compose logs -f
docker compose down
```

### Acesso pela rede

A porta é publicada em `127.0.0.1:8501:8501`, ou seja, **a tela só abre na própria
máquina**. Isso é deliberado: a aplicação não tem autenticação nenhuma, e sem o
prefixo `127.0.0.1` o Docker escuta em todas as interfaces — em wifi de café ou de
hotel, qualquer um no mesmo segmento abriria a interface, enviaria arquivos e
consumiria a CPU da máquina.

Para alcançar a tela de outro aparelho da LAN, troque em `docker-compose.yml`:

```yaml
    ports:
      - "8501:8501"      # escuta em todas as interfaces
```

Faça isso apenas em rede confiável e sabendo que **não há login**: quem alcança a
porta tem acesso completo. Para uso legítimo fora da máquina, o caminho seguro é um
túnel SSH, que dispensa expor a porta:

```bash
ssh -L 8501:127.0.0.1:8501 usuario@maquina
```

O `--server.address=0.0.0.0` do `Dockerfile` é outra coisa e deve continuar como
está: ele é o bind *dentro* do container, sem o qual o mapeamento de porta não
funciona. Quem controla a exposição no host é só a linha `ports`.

O modelo `small` já vem embutido na imagem, então a primeira transcrição não
espera download nenhum e o container funciona sem rede. O limite de upload é de
256 MB — com folga para uma reunião longa, já que uma aula de 37 min ocupa 35 MB.

### CLI dentro do container

A pasta `./dados` do projeto é montada em `/app/dados`. Coloque os arquivos ali:

```bash
docker compose run --rm transcricao \
  python audioTranscricao.py dados/aula.mp3 -o dados/aula.txt
```

Apontar a saída para `dados/` faz o `.txt` aparecer no host.

## Sem Docker

Requer Python 3.12+. Não é necessário ter ffmpeg instalado: o faster-whisper
decodifica mp3, mp4, mkv e afins via PyAV, que traz os próprios codecs.

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Interface web:

```bash
streamlit run app.py
```

Linha de comando:

```bash
python audioTranscricao.py aula.mp3
python audioTranscricao.py reuniao.mp4 -o ata.txt -l en-US -m medium
```

| Argumento | Descrição | Padrão |
|---|---|---|
| `entrada` | arquivo de áudio ou vídeo | `audio1.wav` ao lado do script |
| `-o`, `--saida` | arquivo `.txt` de saída | `transcricao_audio.txt` |
| `-l`, `--idioma` | idioma do áudio (`en-US`, `es-ES`, ...) | `pt-BR` |
| `-m`, `--modelo` | `tiny`, `base`, `small`, `medium`, `large-v3` | `small` |
| `-v`, `--vocabulario` | termos e siglas do domínio, para o modelo acertar o jargão | nenhum |
| `--max-horas` | teto de duração do áudio, em horas | `4` |
| `--sem-limite` | desliga o teto (só para arquivo de origem confiável) | desligado |

Sai com código 1 em caso de erro.

Na primeira execução fora do Docker, o modelo escolhido é baixado para o cache do
Hugging Face (`~/.cache/huggingface`) — são centenas de MB.

## Dependências

`requirements.txt` declara as dependências diretas com pisos de versão, para
instalar à mão fora do Docker. A **imagem instala `requirements.lock.txt`**, que
fixa as 51 versões exatas já testadas — sem isso, cada `docker build` resolveria
para o que estivesse no PyPI naquele dia, e uma dependência transitiva
comprometida entraria sem aviso.

O lock precisa ser gerado **dentro da imagem alvo**, não no venv de
desenvolvimento: um lock feito no Python 3.14 do Windows inclui pacotes que nem
existem para o Python 3.12 da imagem (`audioop-lts`, por exemplo, só existe a
partir do 3.13) e quebra o build.

Para atualizar as dependências:

```bash
docker run --rm -i python:3.12-slim   sh -c 'cat > /tmp/r.txt; pip install -q --no-cache-dir -r /tmp/r.txt >&2 && pip freeze'   < requirements.txt > requirements.lock.txt
```

Depois reconstrua e teste antes de commitar: `docker compose build && docker compose up -d`.

## Escolha do modelo

| Modelo | Download | Precisão | Velocidade |
|---|---|---|---|
| `tiny` | ~75 MB | baixa | muito rápida |
| `base` | ~145 MB | razoável | rápida |
| `small` | ~480 MB | boa | ~1,6x o tempo real em CPU |
| `medium` | ~1,5 GB | alta | várias vezes mais lenta |
| `large-v3` | ~3 GB | melhor | mais lenta ainda |

Modelos maiores acertam mais jargão, siglas e nomes próprios. Se termos do seu
domínio saírem errados, subir de `small` para `medium` costuma resolver.

## Segurança

### Modelo de ameaça

Esta é uma aplicação pessoal: roda em um container na própria máquina, sem
autenticação, sem banco de dados e sem nenhuma requisição de saída. O único dado
de origem não confiável que ela recebe é um arquivo de mídia, que vai direto para
um decodificador binário; o que ela devolve é texto e um PDF. A auditoria descrita
abaixo foi feita contra esse cenário, não contra um checklist genérico de
aplicação web.

Categorias inaplicáveis foram descartadas explicitamente, em vez de preenchidas
com "N/A" ou com controles de enfeite: **SQL injection** não existe porque não há
banco nem consulta; **SSRF** não existe porque a aplicação não faz nenhuma
requisição de saída — o modelo vem embutido na imagem e o reconhecimento roda
local; **bypass de autenticação** não existe porque não há autenticação, o que é
uma limitação real (documentada no fim desta seção) e não um controle a burlar.
O que sobrou, e onde o esforço foi gasto: esgotamento de recursos a partir da
mídia enviada, tratamento do arquivo recebido, exposição da porta e a cadeia de
dependências.

### O que foi corrigido

#### Bomba de descompressão

O tamanho do arquivo não diz quanta memória ele vai custar. O arquivo de teste é
um Opus de **2.714.564 bytes (2,7 MB)** com **2 h** de áudio, que decodifica para
**115.200.000 amostras** a 16 kHz, ou seja **460,8 MB** de float32 — amplificação
de **170x**. Ele passaria folgado no limite de upload de 256 MB do Streamlit, e
nada impedia que o mesmo truque chegasse com 8 h ou 20 h.

Antes da correção, o caminho era `faster_whisper.audio.decode_audio`, que
decodifica o arquivo inteiro de uma vez. Medido: **pico de 1.209 MB** de memória
do processo (**+1.168 MB** sobre a linha de base de ~41 MB), em 6 a 18 s.

**A solução aparentemente óbvia não funciona.** O `faster-whisper` expõe a duração
do áudio em `info.duration`, mas esse valor só existe *depois* da decodificação
completa — que é justamente o passo que estoura a memória. Perguntar a duração
pelo caminho normal da biblioteca significa já ter pago o custo que se queria
evitar.

Por isso a defesa tem dois portões, em `audioTranscricao.py`, e eles atendem a
dois cenários diferentes.

**Cenário 1 — cabeçalho honesto.** O arquivo declara no container a duração que
de fato tem. `sondar_duracao` abre o arquivo com PyAV, lê `container.duration` e
recusa antes de decodificar qualquer coisa. Medido com o Opus de 2 h e o teto em
1 h: recusa em **~3 ms** (2,7 a 7,6 ms), com pico de **43 MB** — **+1,9 MB** sobre
a linha de base. Nenhum quadro de áudio chegou a ser decodificado.

**Cenário 2 — cabeçalho não confiável.** A duração declarada não corresponde ao
conteúdo. O arquivo de teste é o mesmo Opus de 2 h com a *granule position* da
última página Ogg reescrita para 300 s (e o CRC da página recalculado, para o
arquivo continuar válido): o PyAV passa a reportar 300 s, e o conteúdo continua
sendo 2 h inteiras. Com o teto em 1 h, a sonda deixa passar — 300 s está dentro do
limite — e quem barra é o segundo portão: `decodificar_audio` soma as amostras
quadro a quadro e levanta `DuracaoExcedida` no instante em que o total passa de
1 h. Medido: pico de **216 MB** contra os 1.209 MB do decode completo, porque a
decodificação é interrompida na marca do teto e o array float32 nunca chega a ser
alocado. A contagem compara com o teto configurado, não com a duração declarada
nem com o conteúdo: os 216 MB são do teto de 1 h usado na medição — 57,6 M
amostras, ou 115 MB de s16 nos blocos acumulados, sobre a linha de base de ~41 MB
—, e não dos 4 h do padrão, cujos 922 MB da tabela abaixo são o float32 que aqui
nunca é alocado. Com o teto no padrão de 4 h, este mesmo arquivo de 2 h não seria
barrado: seria transcrito.

**O cenário 2 é a razão de o segundo portão existir.** O cabeçalho é um dado sob
controle de quem envia o arquivo: falsificá-lo custa os poucos bytes editados
acima. Uma defesa que confie nele pode ser desligada por quem ataca, então a sonda
não serve como única barreira — ela existe para que o caso honesto custe
milissegundos em vez de uma decodificação inteira. O que fecha de verdade é a
contagem, que não lê metadado nenhum.

O que o segundo portão limita é **memória, não tempo**. Decodificar contando
amostras, em Python, é cerca de duas vezes mais lento por hora de áudio que o
`decode_audio` do faster-whisper (2 h completas: 20 a 33 s contra 9 a 17 s), e o
custo de um arquivo hostil passa a ser proporcional ao teto, não ao conteúdo do
arquivo. Com o teto em 1 h e um arquivo de 2 h, aborta-se na metade; com um
arquivo de 20 h, na mesma marca de 1 h.

O formato produzido por `decodificar_audio` (float32 mono 16 kHz, normalizado a
partir de s16) é idêntico ao que `decode_audio` gerava, e o array já decodificado
é passado ao `transcribe`, então a transcrição em si não mudou.

> Condições das medições: Windows 11, Python 3.14, teto de 1 h, um processo novo
> por medição, chamando `sondar_duracao` e `decodificar_audio` diretamente, com o
> modelo Whisper não carregado. "Pico" é o `PeakWorkingSetSize` do processo, e a linha de base de
> ~41 MB é o interpretador com `av`, `numpy` e o módulo importados. Os tempos
> variam com a carga da máquina — daí as faixas; os picos de memória repetiram
> dentro de 1%.

#### Porta publicada só no loopback

O `docker-compose.yml` publica `127.0.0.1:8501:8501`. Sem o prefixo, o Docker
escuta em todas as interfaces do host e, como não há autenticação, qualquer um no
mesmo segmento de rede abriria a interface, enviaria arquivos e consumiria a CPU
da máquina.

O `--server.address=0.0.0.0` do `Dockerfile` **permanece como está**, e não é
contradição: são duas coisas diferentes. Ele é o bind do Streamlit *dentro* do
container, onde `0.0.0.0` é obrigatório — com `localhost`, o processo escutaria só
na interface interna do container e o mapeamento de porta do Docker não chegaria
até ele. Quem controla a exposição no host é exclusivamente a linha `ports`. A
seção **Acesso pela rede** descreve o túnel SSH para o caso de acesso remoto
legítimo.

#### Lockfile regenerado dentro da imagem de destino

A imagem instala `requirements.lock.txt`, com as 51 versões exatas já testadas, e
não `requirements.txt`, que declara apenas pisos (`>=`). Com pisos, cada
`docker build` resolve para o que estiver no PyPI naquele dia, e uma versão
comprometida de qualquer dependência transitiva entraria sem aviso.

O lock precisa ser gerado **dentro da imagem alvo** (`python:3.12-slim`), não no
venv de desenvolvimento, que aqui roda Python 3.14. Um `pip freeze` feito nele
inclui pacotes que não existem para o 3.12 — `audioop-lts`, por exemplo, só existe
a partir do 3.13 — e o `pip install` dentro da imagem falha, quebrando o build. O
comando de regeneração está na seção **Dependências**.

#### Tratamento do arquivo enviado

- **Lista branca de extensão.** A extensão do arquivo temporário passou a vir de
  `FORMATOS_ACEITOS`, e não do nome enviado. O nome nunca virou caminho, mas o
  sufixo era repassado cru ao `tempfile`: uma extensão contendo byte nulo
  levantava `ValueError`, e como `_salvar_upload` ficava *fora* do `try`, o erro
  virava um traceback do Streamlit na tela, com caminhos do sistema. A chamada
  passou para dentro do `try` e o erro vira `st.error`.
- **Varredura de temporários órfãos.** O `finally` cobre erro e rerun, mas não
  SIGKILL — que já aconteceu nesta aplicação, com o processo morto pelo sistema
  por falta de memória. Cada morte dessas deixava para trás um arquivo do tamanho
  de um vídeo de reunião. Na inicialização, uma vez por processo, os arquivos com
  o prefixo `transcricaoAudio_` e mais de 24 h são removidos; o prefixo delimita a
  varredura aos arquivos desta aplicação.
- **pillow atualizado** para 12.3.0 no lock, fechando os avisos do `pip-audit`. É
  dependência transitiva do Streamlit e inalcançável neste fluxo — a mídia enviada
  vai para o PyAV, não para ele —, então a atualização é higiene, não correção de
  risco explorável. O `pip-audit` passa limpo no venv e no lock.

### Teto de duração: `TRANSCRICAO_MAX_HORAS`

Valor atual: **4 horas**. É o parâmetro que decide quanta memória um upload pode
custar, então quem for alterá-lo precisa da aritmética:

```
amostras = horas × 3600 × 16000        (o Whisper trabalha a 16 kHz mono)
s16      = amostras × 2 bytes          (saída do decode)
float32  = amostras × 4 bytes          (formato que o modelo consome)
pico     ≈ amostras × 6 bytes          (s16 e float32 vivos ao mesmo tempo, na conversão)
```

| Teto | Amostras | s16 | float32 | Pico na conversão |
|---|---|---|---|---|
| 1 h | 57,6 M | 115 MB | 230 MB | ~346 MB |
| 2 h | 115,2 M | 230 MB | 461 MB | ~691 MB |
| **4 h (padrão)** | **230,4 M** | **461 MB** | **922 MB** | **~1,4 GB** |
| 8 h | 460,8 M | 922 MB | 1,8 GB | ~2,8 GB |

Esses números são só dos arrays de áudio. O processo carrega ainda o
interpretador, o numpy, o PyAV e (na transcrição) o modelo, então o pico real é
maior que a coluna da direita: no arquivo de teste de 2 h, a tabela prevê ~691 MB
e o pico medido do decode completo foi de **1.209 MB**. Em máquina apertada,
abaixe o teto.

Para mudar o valor:

```bash
TRANSCRICAO_MAX_HORAS=8 python audioTranscricao.py aula.mp3   # variável de ambiente
python audioTranscricao.py aula.mp3 --max-horas 8             # só nesta execução
python audioTranscricao.py aula.mp3 --sem-limite              # desliga os dois portões
```

No container, passe a variável em `docker-compose.yml`:

```yaml
    environment:
      - TRANSCRICAO_MAX_HORAS=8
```

O `--sem-limite` existe para arquivo de origem confiável na linha de comando; a
interface web não o oferece.

### O que foi verificado e estava correto

Faz parte do resultado da auditoria, e está aqui porque um leitor não tem como
distinguir "verificado e correto" de "não olhado":

- **Path traversal no nome do upload.** Testado com 10 nomes de arquivo hostis.
  `upload.name` nunca é usado como caminho: o conteúdo vai para um
  `NamedTemporaryFile` com nome gerado pelo sistema, e do nome enviado se
  aproveita apenas a extensão — que hoje ainda passa pela lista branca. O nome dos
  downloads passa por `os.path.basename` antes de qualquer uso.
- **Injeção no `Content-Disposition`.** O nome dos arquivos baixados vem de
  `_nome_base`, que aplica `os.path.basename` e `os.path.splitext` sobre o nome
  enviado, e o cabeçalho é montado pelo próprio Streamlit. Não foi encontrado
  caminho para injetar CR/LF ou parâmetros extras no cabeçalho.
- **Escape do markup do reportlab, inclusive no cabeçalho.** O `Paragraph` do
  reportlab interpreta o conteúdo como markup, então um `&` ou `<` solto quebra a
  geração. Todo parágrafo do corpo passa por `xml.sax.saxutils.escape` — e também
  as linhas de metadados do cabeçalho, que é o ponto fácil de esquecer:
  `_linhas_cabecalho` escapa `nome_origem`, o nome do arquivo enviado, que é a
  única string do PDF vinda de fora sem ter passado pela transcrição.
- **XSRF.** A proteção XSRF do Streamlit (`server.enableXsrfProtection`) vem
  ligada por padrão e o `Dockerfile` não a desliga. Cada flag do `CMD` foi
  revisada; nenhuma afrouxa a configuração padrão.
- **Usuário não-root.** O container roda como `transcricao`. O usuário é criado no
  início do `Dockerfile`, antes do download do modelo, para o cache já nascer com
  o dono certo, e o `USER` é ativado antes do `COPY` do código.
- **Histórico do git.** Varrido em busca de credenciais, tokens e mídia pessoal
  que tivesse entrado em algum commit antigo. Limpo.

### Limitações conhecidas

- **Não há autenticação.** Quem alcança a porta tem acesso completo: envia
  arquivos, consome a CPU e lê as transcrições da sessão. A proteção é o binding
  em loopback, e nada além disso. Trocar `127.0.0.1:8501:8501` por `8501:8501`
  remove a única barreira que existe.
- **O `pip-audit` não enxerga as CVEs do FFmpeg embutido no PyAV.** O pacote `av`
  traz os próprios codecs como binários compilados, e é exatamente ele que recebe
  a mídia não confiável — a maior superfície de parsing binário do projeto. O
  `pip-audit` verifica a versão do pacote Python, não o FFmpeg que está dentro
  dele, então uma CVE de decodificador não aparece em varredura de dependências.
  Acompanhar isso exige seguir os avisos de segurança do próprio FFmpeg e subir a
  versão do `av` quando saírem.
- **O lock fixa versões, mas não grava hashes.** `requirements.lock.txt` é um
  `pip freeze`: torna o build reproduzível em termos de *versão*, não de
  *artefato*. Um pacote substituído no índice mantendo o mesmo número de versão
  ainda passaria. Fechar isso exigiria um lock com hashes
  (`pip-compile --generate-hashes`) instalado com `pip install --require-hashes`.

## Formatos aceitos

`mp3`, `wav`, `m4a`, `ogg`, `flac`, `aiff`, `mp4`, `mkv`, `avi`, `mov`.

## Medindo a qualidade de uma transcrição

`verificar_transcricao.py` transcreve um arquivo e relata contagem de palavras,
pontuação, parágrafos, presença de termos do domínio e repetições em loop:

```bash
python verificar_transcricao.py dados/aula.mp3 small
```

## Arquivos

| Arquivo | Papel |
|---|---|
| `app.py` | interface Streamlit |
| `.streamlit/config.toml` | tema da interface (cor, fonte, bordas) e toolbar |
| `audioTranscricao.py` | motor de transcrição e CLI |
| `gerar_pdf.py` | exportação do texto revisado em PDF |
| `verificar_transcricao.py` | métricas de qualidade da transcrição |
| `verificar_layout.py` | confere os três estados da tela com o AppTest |
