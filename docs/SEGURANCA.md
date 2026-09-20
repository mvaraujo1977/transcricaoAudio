# Segurança

Auditoria desta aplicação: o que foi corrigido, o que foi verificado e estava
correto, e o teto de memória. O resumo está no [README](../README.md#segurança).

## Modelo de ameaça

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
uma limitação real (documentada nas **Limitações conhecidas** do
[README](../README.md#limitações-conhecidas)) e não um controle a burlar.
O que sobrou, e onde o esforço foi gasto: esgotamento de recursos a partir da
mídia enviada, tratamento do arquivo recebido, exposição da porta e a cadeia de
dependências.

## O que foi corrigido

### Bomba de descompressão

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

### Porta publicada só no loopback

O `docker-compose.yml` publica `127.0.0.1:8501:8501`. Sem o prefixo, o Docker
escuta em todas as interfaces do host e, como não há autenticação, qualquer um no
mesmo segmento de rede abriria a interface, enviaria arquivos e consumiria a CPU
da máquina.

O `--server.address=0.0.0.0` do `Dockerfile` **permanece como está**, e não é
contradição: são duas coisas diferentes. Ele é o bind do Streamlit *dentro* do
container, onde `0.0.0.0` é obrigatório — com `localhost`, o processo escutaria só
na interface interna do container e o mapeamento de porta do Docker não chegaria
até ele. Quem controla a exposição no host é exclusivamente a linha `ports`. A
subseção **Acesso pela rede**, abaixo, descreve o túnel SSH para o caso de acesso remoto
legítimo.

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

### Lockfile regenerado dentro da imagem de destino

A imagem instala `requirements.lock.txt`, com as 51 versões exatas já testadas, e
não `requirements.txt`, que declara apenas pisos (`>=`). Com pisos, cada
`docker build` resolve para o que estiver no PyPI naquele dia, e uma versão
comprometida de qualquer dependência transitiva entraria sem aviso.

O lock precisa ser gerado **dentro da imagem alvo** (`python:3.12-slim`), não no
venv de desenvolvimento, que aqui roda Python 3.14. Um `pip freeze` feito nele
inclui pacotes que não existem para o 3.12 — `audioop-lts`, por exemplo, só existe
a partir do 3.13 — e o `pip install` dentro da imagem falha, quebrando o build. O
comando de regeneração está em **Regenerando o lockfile**, abaixo.

### Regenerando o lockfile

Para atualizar as dependências:

```bash
docker run --rm -i python:3.12-slim   sh -c 'cat > /tmp/r.txt; pip install -q --no-cache-dir -r /tmp/r.txt >&2 && pip freeze'   < requirements.txt > requirements.lock.txt
```

Depois reconstrua e teste antes de commitar: `docker compose build && docker compose up -d`.

### Tratamento do arquivo enviado

- **Lista branca de extensão.** A extensão do arquivo temporário passou a vir de
  `FORMATOS_ACEITOS`, e não do nome enviado. O nome nunca virou caminho, mas o
  sufixo era repassado cru ao `tempfile`: uma extensão contendo byte nulo
  levantava `ValueError`, e como `_salvar_upload` ficava *fora* do `try`, o erro
  virava um traceback do Streamlit na tela, com caminhos do sistema. A chamada
  passou para dentro do `try` e o erro vira `st.error`.
- **Varredura de temporários órfãos.** O `finally` cobre erro, rerun e o
  cancelamento (que é um rerun, veja **Cancelar no meio**), mas não o
  SIGKILL — que já aconteceu nesta aplicação, com o processo morto pelo sistema
  por falta de memória. Cada morte dessas deixava para trás um arquivo do tamanho
  de um vídeo de reunião. Na inicialização, uma vez por processo, os arquivos com
  o prefixo `transcricaoAudio_` e mais de 24 h são removidos; o prefixo delimita a
  varredura aos arquivos desta aplicação.
- **pillow atualizado** para 12.3.0 no lock, fechando os avisos do `pip-audit`. É
  dependência transitiva do Streamlit e inalcançável neste fluxo — a mídia enviada
  vai para o PyAV, não para ele —, então a atualização é higiene, não correção de
  risco explorável. O `pip-audit` passa limpo no venv e no lock.

## Teto de duração: `TRANSCRICAO_MAX_HORAS`

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

## O que foi verificado e estava correto

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
