# Publicação da demo (Hugging Face Spaces)

Como a demo em
[huggingface.co/spaces/mvaraujo1977/transcricao-audio](https://huggingface.co/spaces/mvaraujo1977/transcricao-audio)
é publicada, e as restrições da plataforma que explicam decisões que, de fora,
parecem arbitrárias.

## O arranjo: dois repositórios, um código

O Space é um repositório git separado do GitHub, e precisa de coisas que o
repositório do projeto não tem — um `README.md` com frontmatter YAML e um
`requirements.txt` sem Streamlit. Em vez de manter duas cópias do código, o que
é do Space mora em `deploy/space/` e é publicado com nome de destino diferente:

| No repositório | No Space |
|---|---|
| `deploy/space/README.md` | `README.md` (com o frontmatter que o Spaces exige) |
| `deploy/space/requirements.txt` | `requirements.txt` |
| `app_gradio.py`, `audioTranscricao.py`, `gerar_pdf.py`, `LICENSE`, `exemplos/` | mesmos caminhos |

Publicar:

```bash
hf auth login                        # uma vez, token de escrita
python deploy/publicar_space.py --ensaio    # mostra o que subiria
python deploy/publicar_space.py             # publica
```

Não sobem para o Space: `app.py` (Streamlit), `Dockerfile`, `docs/`, `dados/` e
os verificadores.

## Por que existe uma função `@spaces.GPU` que ninguém chama

**Esta é a restrição que mais parece erro quando se olha depois.**

A conta gratuita não libera o SDK Docker, então a demo não pode ser a imagem
deste repositório: ela roda com SDK Gradio. E, no momento da criação, o hardware
oferecido foi **ZeroGPU** — não CPU básica.

O primeiro deploy subiu e caiu na hora, com:

```
No @spaces.GPU function detected during startup
```

O ZeroGPU **exige** enxergar uma função decorada na inicialização; não é só o
mecanismo para pedir GPU. Sem ela o runtime derruba a aplicação — o log mostrava
o Gradio subindo em `0.0.0.0:7860` e o processo parando em seguida.

O motor deste projeto é o CTranslate2, que o ZeroGPU não acelera (ele é para
PyTorch), então **GPU não interessa aqui**. A saída foi declarar em
`app_gradio.py` uma função decorada que nunca é chamada, só para passar na
checagem, e acrescentar `spaces` ao `requirements.txt` do Space. A transcrição
continua inteira na CPU e nenhuma cota de GPU é consumida.

### Por que não trocar o hardware para CPU básica

Foi tentado, nesta ordem:

1. **Pela API**, com `HfApi().request_space_hardware(..., 'cpu-basic')`: falha
   com **401** no endpoint `/hardware` — o token do `hf auth login` (fluxo de
   dispositivo) dá escrita no repositório, não mudança de hardware.
2. **Pelo site**, em Settings → Hardware: a Hugging Face **recusa o downgrade de
   ZeroGPU para `cpu-basic` sem assinatura PRO**.

Ou seja: enquanto o Space estiver em ZeroGPU, **o shim e a dependência `spaces`
precisam ficar**. Não são escolha de projeto nem sobra de experimento.

Se um dia o Space passar para CPU básica (conta PRO, ou um Space novo criado já
nesse hardware), saem juntos e sem tocar em mais nada: o bloco marcado em
`app_gradio.py` e a linha `spaces` no `deploy/space/requirements.txt`. O
decorador é inócuo fora do ZeroGPU, então a ordem das operações não importa —
trocar o hardware primeiro não quebra a demo.

## Outras particularidades da plataforma

- **Disco efêmero**: o que for baixado em execução some quando o Space reinicia.
  Por isso o modelo é pré-carregado no build, pelo `preload_from_hub` no
  frontmatter, e não na primeira transcrição.
- **Hibernação**: o Space gratuito dorme depois de um tempo sem uso e a primeira
  visita seguinte espera o retorno (cerca de um minuto). O README avisa isso
  junto do link, para quem clica não achar que quebrou.
- **Limites da demo**: modelo `base`, 5 minutos de áudio e 50 MB por arquivo,
  aplicados quando a variável `SPACE_ID` existe — é o Hugging Face que a define.
  Todos cedem a variáveis de ambiente (veja o README), e fora do Space a
  aplicação mantém os padrões locais: `small`, 4 horas, 256 MB.
- **XSRF do Streamlit**: não afeta esta demo (que é Gradio), mas afeta quem
  rodar a imagem Docker num Space: a proteção por cookie não sobrevive ao iframe
  e o uploader para de funcionar. O `entrypoint.sh` desliga a proteção só quando
  `SPACE_ID` existe.
