# Publicação da demo (Hugging Face Spaces)

Como a demo em
[huggingface.co/spaces/mvaraujo1977/transcricao-audio](https://huggingface.co/spaces/mvaraujo1977/transcricao-audio)
é publicada, e as restrições de plataforma que explicam decisões que, de fora,
parecem arbitrárias.

## O arranjo: dois repositórios, um código

O Space é um repositório git separado do GitHub e precisa de um `README.md` com
frontmatter YAML, que o repositório do projeto não tem. Em vez de manter duas
cópias, o que é do Space mora em `deploy/space/` e é publicado com outro nome:

| No repositório | No Space |
|---|---|
| `deploy/space/README.md` | `README.md` (com o frontmatter que o Spaces exige) |
| `Dockerfile`, `entrypoint.sh`, `requirements.lock.txt` | mesmos caminhos |
| `app.py`, `.streamlit/config.toml`, `audioTranscricao.py`, `gerar_pdf.py` | mesmos caminhos |
| `exemplos/`, `LICENSE` | mesmos caminhos |

Publicar:

```bash
hf auth login                               # uma vez, token de escrita
python deploy/publicar_space.py --ensaio    # mostra o que subiria
python deploy/publicar_space.py             # publica
```

Não sobem: `docs/`, `dados/` e os verificadores.

**A demo roda a mesma imagem da instalação local.** O SDK do Space é `docker`, e
o `app_port: 8501` do frontmatter aponta para a porta que o `entrypoint.sh` usa.
Os limites de demo não são outro código: o entrypoint aplica modelo `base`,
seletor restrito a `base` e `small`, teto de 20 minutos e upload de 100 MB
quando a variável `SPACE_ID` existe — é o Hugging Face que a define —, marca a
execução como demo (`TRANSCRICAO_DEMO`, que troca a mensagem do teto de duração
por uma que o visitante possa agir sobre) e desliga a proteção XSRF do Streamlit,
que é por cookie e não sobrevive ao iframe do Spaces (com ela ligada, o
`st.file_uploader` não funciona lá). Fora do Space nada disso roda, e a instalação
local mantém `small`, os cinco modelos, 4 horas, 256 MB e o XSRF ligado.

**Quanto tempo leva, medido no Space.** Não extrapolado de uma máquina local --
a extrapolação errou por cerca de 5x, para pior. Medições de ponta a ponta, do
clique em **Transcrever** até o texto na tela, com o modelo `base` no hardware
`cpu-basic`:

| Áudio | Relógio | Fator |
|---|---|---|
| 5 min | 25 a 32 s | 0,08–0,11x |
| 19 min 30 | 2 min 00 | 0,10x |
| **20 min (o teto)** | **2 min 38** | **0,13x** |

Ou seja: o teto da demo custa cerca de **2,5 minutos** de espera, com a posição no
áudio e a estimativa do que falta na tela o tempo todo. A CPU do Space chegou a
sair mais rápida que uma máquina local de 12 núcleos no mesmo arquivo -- o
`ctranslate2` em int8 não ganha muito com mais núcleos, e o servidor tem núcleos
melhores. Isso também é o que sustenta o `disconnectedSessionTTL` de 10 minutos
do `.streamlit/config.toml`: a janela de guarda é quatro vezes maior que a
transcrição mais longa que a demo aceita.

As medições saem do [`medir_demo.py`](../medir_demo.py), na raiz do repositório:
sem navegador, ele fala o protocolo websocket do Streamlit direto -- pede a URL
de upload, envia o arquivo, dispara o widget do botão e lê os `ForwardMsg` até o
`text_area` do resultado aparecer. É ferramenta de medição e **não sobe para o
Space**: a lista de `deploy/publicar_space.py` não o inclui.

```bash
python medir_demo.py dados/aula.mp3 --repeticoes 3   # descarte a primeira
```

A primeira medição de um container frio sai mais lenta, porque o modelo ainda não
está no `lru_cache` de `carregar_modelo()`.

**Por que o seletor é restrito.** `medium` e `large-v3` não estão na imagem — o
Dockerfile embute só `base` e `small`. Deixá-los no seletor de uma demo é um
download de 1,5 GB ou 3 GB para disco efêmero, disparado no meio da transcrição,
e depois dezenas de minutos de espera em 2 vCPU compartilhadas.

O modelo vem embutido na imagem porque **o disco do Space é efêmero**: o que for
baixado em execução some no próximo reinício.

## Histórico: a fase Gradio e o shim do ZeroGPU

Esta seção descreve o que valeu entre **20 e 21 de setembro de 2026**, no plano
gratuito. Não se aplica mais — a conta é PRO e a demo é Docker —, mas fica
registrada porque explica commits e porque as mesmas restrições voltam a valer
para quem for reproduzir o projeto numa conta gratuita.

**No plano gratuito, o SDK Docker não era oferecido.** O Space foi criado com SDK
Gradio, e a demo precisou de uma segunda tela (`app_gradio.py`, hoje removida e
preservada no histórico do git), que chamava a mesma `transcrever()` do motor.

**O hardware oferecido foi ZeroGPU**, e o primeiro deploy caiu na hora com:

```
No @spaces.GPU function detected during startup
```

O ZeroGPU **exige** enxergar uma função decorada na inicialização; não é só o
mecanismo para pedir GPU. Sem ela o runtime derruba a aplicação — o log mostrava
o Gradio subindo em `0.0.0.0:7860` e o processo parando em seguida. Como o motor
é CTranslate2, que o ZeroGPU não acelera (ele é para PyTorch), GPU não
interessava: a saída foi declarar uma função decorada que nunca era chamada, só
para passar na checagem, com `spaces` no `requirements.txt` do Space.

Sair do ZeroGPU teria resolvido, e foi tentado duas vezes:

1. **Pela API**, com `HfApi().request_space_hardware(..., 'cpu-basic')`: **401**
   no endpoint `/hardware`. O token do `hf auth login` (fluxo de dispositivo) dá
   escrita no repositório, não mudança de hardware — e isso continua valendo
   mesmo com PRO, então a troca é feita em Settings → Hardware, no site.
2. **Pelo site**: a Hugging Face **recusava o downgrade de ZeroGPU para
   `cpu-basic` sem assinatura PRO**.

Com o PRO, os dois bloqueios saíram do caminho: o SDK Docker liberou, o hardware
foi para CPU básica e a demo passou a ser a imagem do projeto. O shim
`@spaces.GPU`, a dependência `spaces` e a tela Gradio saíram juntos.

## Particularidades da plataforma que continuam valendo

- **Disco efêmero**: o modelo tem de estar na imagem, não ser baixado em
  execução. Na fase Gradio isso era feito com `preload_from_hub` no frontmatter;
  com Docker, é o `RUN` do Dockerfile que baixa `small` e `base` no build.
- **Hibernação: 48 horas, e isso vem do hardware, não do plano.** A
  documentação da Hugging Face é explícita: *"If your Space runs on the default
  `cpu-basic` hardware, it will go to sleep if inactive for more than a set time
  (currently, 48 hours). Anyone visiting your Space will restart it
  automatically. If you want your Space never to deactivate or if you want to
  set a custom sleep time, you need to upgrade to paid hardware."* Ou seja: a
  conta PRO **não** muda esse prazo — quem quiser Space sempre acordado, ou um
  tempo de hibernação customizado, precisa de hardware pago (CPU Upgrade ou GPU),
  que é cobrado por hora. No `cpu-basic` as 48 horas são fixas.
  Acordar custa **segundos**, não minutos: com SDK Docker, acordar é reiniciar o
  container de uma imagem já construída, e o modelo vem embutido nela — não há
  build nem download no caminho.
- **UID 1000**: o Spaces roda o container com esse usuário. O `Dockerfile` já
  criava um usuário não-root por outro motivo (segurança), e ele nasce com UID
  1000 — não foi preciso mudar nada.
- **Permissão do token**: escrita no repositório sim, settings não. Hardware,
  variáveis e segredos são alterados no site.
