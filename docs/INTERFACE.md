# A tela

Como a interface está organizada, como uma transcrição pode ser interrompida
(pela pessoa ou pela rede) e as cores com as razões de contraste medidas. O resumo está no
[README](../README.md#como-usar).

A interface tem três estados e mostra um de cada vez:

- **Vazio**: título, o que a ferramenta faz, os selos do que a diferencia
  (processamento local, sem envio para a nuvem, modelo Whisper, idiomas), o
  uploader, as opções avançadas recolhidas e a faixa **Como funciona**, com os
  três passos do fluxo em uma frase cada. É o que responde "o que isso faz" a
  quem abre o link sem conhecer o projeto; some assim que houver transcrição.
- **Processando**: os controles ficam desabilitados e um painel único reúne a
  barra de progresso, o tempo decorrido, a posição no áudio (`08:17 de 37:27`),
  a estimativa do que falta e o botão **Cancelar**. A estimativa vem do ritmo
  observado na própria execução — segundos de relógio por segundo de áudio —, e
  não de um número fixo por modelo, que erraria em máquina mais lenta.
- **Resultado**: uma linha com duração, idioma, segmentos e palavras; o texto
  transcrito editável; e os dois downloads lado a lado.

## Cancelar no meio

O script do Streamlit roda numa thread só e fica preso dentro da transcrição: o
clique em **Cancelar** só é processado quando o script passa por uma chamada do
Streamlit. É por isso que a decodificação — que vem antes de transcrever e não
mostrava nada — passou a chamar o mesmo callback de progresso a cada minuto de
áudio lido (`FASE_PREPARO`, em `audioTranscricao.py`): sem isso o botão ficaria
sem resposta durante toda essa fase, que num arquivo longo leva dezenas de
segundos.

**Sobra uma janela em que o botão não responde, e ela é inevitável.** O
`faster-whisper` roda a detecção de voz e monta o espectrograma *dentro* do
`transcribe()`, antes de devolver o gerador, sem passar por nenhuma chamada de
quem o chamou — não há onde inserir um ponto de rendição. Medido com `base`:
1,9 s para 5 min de áudio e 7,0 s para 20 min. Cresce com a duração, mas é uma
fração pequena da espera total (o teto de 20 min sai em ~2,5 min no Space). O que
dá para fazer é a tela
dizer o que está acontecendo, e é o que a `FASE_ANALISE` faz: o painel troca para
"Analisando o áudio (detecção de voz)" em vez de ficar parado no fim do preparo,
parecendo travado. A barra não é mexida nessa fase — zerá-la ou enchê-la seria
inventar um progresso que não existe.

Quando o clique chega, o Streamlit interrompe o script levantando uma exceção
que herda de `BaseException`, e não de `Exception`. Ela passa direto pelos
`except` da tela — de propósito — mas não pelo `finally` de
`_transcrever_upload`, que é onde o arquivo temporário é apagado. O
`verificar_layout.py` confere as duas coisas: a hierarquia da exceção e o
temporário removido depois do corte.

**O trabalho parcial é preservado.** Os segmentos são acumulados no
`session_state` conforme chegam, não numa lista local — que iria embora junto com
a pilha desmontada pela interrupção. Ao cancelar, o que já foi reconhecido vira
um resultado normal, editável e exportável, com um aviso dizendo até que ponto do
áudio o texto vai. Cancelando antes do primeiro segmento, a tela volta ao estado
de entrada com uma mensagem neutra. Nos dois casos o arquivo enviado continua no
uploader, para recomeçar sem reenviar.

## Quando a conexão cai

Perder o websocket **mata a transcrição em andamento**, não só a tela. O servidor
do Streamlit chama `request_script_stop()` na sessão que desconecta
(`runtime/websocket_session_manager.py`), e não há opção de configuração que mude
isso. Basta trocar de app no celular, uma oscilação de rede ou a tampa do
notebook. Com o teto da demo em 20 minutos de áudio, a janela em que isso pode
acontecer deixou de ser desprezível.

Por dentro é o mesmo evento do cancelamento — o script é interrompido no meio e a
pilha desmontada —, com uma diferença: ninguém marcou `cancelado`, porque ninguém
clicou em nada. **Era por aí que a perda passava silenciosa**: o script recomeçava
do topo na reconexão, não encontrava `texto_editado` e a tela voltava ao estado
vazio como se nada tivesse acontecido, com os minutos já transcritos presos no
`session_state` e ninguém para mostrá-los.

Hoje a tela trata os dois casos pelo mesmo `_salvar_parcial`, e o que os separa é
só a frase do aviso: a queda diz que a transcrição foi interrompida e aponta a
causa provável, em vez de chamar de "cancelada" o que ninguém cancelou. Quem
perdeu a conexão não sabe que perdeu — a aba dele continuou aberta —, e sem dizer
a causa o texto pela metade parece defeito da ferramenta.

Chegar a esse rerun depende de a sessão ainda existir quando o navegador
reconecta, e isso é o `server.disconnectedSessionTTL` que decide. O padrão do
Streamlit é 120 s, dimensionado para "pequenas quedas de rede" — curto demais
aqui, então o `.streamlit/config.toml` o leva a 10 minutos. Não mais que isso:
uma sessão guardada segura também o arquivo que ela enviou.

## Paleta

Tudo o que é cor fica em `.streamlit/config.toml`. Sem `base` definido, a tela
segue a preferência do navegador, e **cada modo é desenhado à mão**: o escuro não
é conversão do claro, porque pastel claro sobre fundo escuro ofusca. Lá o
equivalente de pastel é superfície um degrau acima do fundo, e o acento sobe em
vez de descer.

Um matiz só, o verde-azulado, em duas intensidades:

| Papel | Claro | Escuro |
|---|---|---|
| Fundo da página | `#FAF8F4` creme quente | `#101715` quase preto esverdeado |
| Superfície (campos, uploader, área de texto) | `#E7EFEA` sálvia pastel | `#1B2523` |
| Texto | `#1C2723` | `#E6EDEA` |
| Acento (botão primário, barra, foco) | `#0F766E` | `#178273` |
| Link | `#0F766E` | `#7FD8C6` |
| Selo: fundo / texto | `#DCE8E1` / `#2E443D` | `#26332F` / `#BFD6CD` |
| Borda de widget | `#77877F` | `#5B7871` |

**O pastel fica na superfície, nunca no texto.** O acento não pode ser pastel
porque o Streamlit escreve em **branco** sobre ele no botão primário, nos dois
modos — por isso o tom do modo escuro é mais aberto que o do claro (luminância
0,17 contra 0,15), mas não muito mais: acima disso o branco do botão reprova.

Pelo mesmo motivo os selos e os números dos passos usam `:gray-badge[...]` e
`:gray[...]`, com `grayColor` definido por modo, e não `primary`: como o texto do
selo é pintado com a própria cor de destaque, um acento profundo o bastante para
o botão cai para **3,16:1** dentro do selo no modo escuro.

### Contraste medido

Medido no Chromium, contra o container, lendo as cores que o navegador de fato
pinta (inclusive a composição alfa dos selos e a opacidade que o Streamlit aplica
na legenda):

| Par | Mínimo | Claro | Escuro |
|---|---|---|---|
| Texto do corpo sobre o fundo | 4,5:1 | 14,52:1 | 15,29:1 |
| Texto do corpo sobre a superfície | 4,5:1 | 13,15:1 | 13,23:1 |
| Legenda (`st.caption`) sobre o fundo | 4,5:1 | 5,92:1 | 8,32:1 |
| Texto do selo sobre o fundo do selo | 4,5:1 | 8,29:1 | 8,59:1 |
| Branco sobre o botão primário | 4,5:1 | 5,47:1 | 4,69:1 |
| Borda de widget contra o fundo | 3:1 | 3,56:1 | 3,78:1 |
| Borda de widget contra a superfície | 3:1 | 3,23:1 | 3,27:1 |

Dois pares reprovavam e foram corrigidos: a borda padrão do Streamlit ficava em
**1,45:1** contra o fundo (daí `borderColor` explícito), e a legenda, que o
Streamlit apaga com `opacity: 0.6`, ficava em **4,08:1** no modo claro — a
opacidade subiu para 0,72 por CSS, o que resolve nos dois modos sem fixar cor.

O menu e o botão Deploy saem pelo `toolbarMode = "minimal"`, e o empilhamento das
colunas em tela estreita é o comportamento padrão do `st.columns`, abaixo de
640 px.

Sobraram três blocos de CSS em `app.py`, todos com seletor `[data-testid=...]`,
porque as classes que o Streamlit gera mudam de nome a cada atualização: o
espaçamento do bloco principal, a opacidade da legenda e as instruções do
uploader, que o Streamlit escreve em inglês ("256MB per file • MP3, WAV, …") sem
oferecer tradução nem parâmetro para trocá-las — a linha em português logo abaixo
do uploader diz a mesma coisa, com o teto lido de `server.maxUploadSize`.

`verificar_layout.py` carrega a tela nos três estados com o AppTest, sem
navegador e sem transcrever nada:

```bash
python verificar_layout.py
```
