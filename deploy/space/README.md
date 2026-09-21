---
title: Transcrição de Áudio
emoji: 🎙️
colorFrom: green
colorTo: gray
sdk: docker
app_port: 8501
pinned: false
license: mit
short_description: Transcreve áudio e vídeo em texto, sem API de terceiros
---

# Transcrição de áudio

Demo de uma ferramenta que transcreve áudio e vídeo em texto editável com o
modelo Whisper (via `faster-whisper`), exportando em `.txt` e `.pdf`.

## Para quem serve

Feito para material que **não pode ir para a nuvem** — audiência, sessão clínica,
reunião interna, entrevista. O áudio é processado pelo modelo na própria máquina
que roda a aplicação, sem chamada a nenhuma API de terceiros.

> ⚠️ **Nesta demo, essa máquina é o servidor do Hugging Face — não o seu
> computador. Não envie material confidencial aqui.** A demo existe para você ver
> a ferramenta funcionando antes de instalar. Para ter a garantia de verdade,
> rode local com Docker:
> [github.com/mvaraujo1977/transcricaoAudio](https://github.com/mvaraujo1977/transcricaoAudio).

## Como usar

- **Sem arquivo à mão?** Use **Testar com exemplo**: 24 s de *O Alienista*, de
  Machado de Assis, em domínio público.
- **Transcreve, não traduz** — o texto sai no idioma falado no áudio.
- **Limites desta demo**: 20 minutos de áudio, 100 MB por arquivo, e a escolha
  de modelo vai só até o `small` (o padrão aqui é `base`), porque a CPU é
  compartilhada. Rodando local, o padrão é `small`, com teto de 4 horas e todos
  os modelos disponíveis.
- **Não feche nem deixe a aba em segundo plano** durante uma transcrição longa:
  se a conexão com esta página cair, a transcrição é interrompida. O que já tiver
  sido reconhecido até ali é recuperado quando você volta.
- A demo **hiberna** depois de um tempo sem uso: a primeira visita pode levar
  cerca de um minuto para acordar.

## Quanto tempo leva

Medido aqui mesmo, do clique em **Transcrever** até o texto na tela, com o
modelo `base`:

| Áudio | Relógio | Fator |
|---|---|---|
| 5 min | 25 a 32 s | 0,08–0,11x |
| **20 min (o teto)** | **2 min 38** | **0,13x** |

O maior arquivo que esta demo aceita sai em pouco mais de dois minutos e meio,
com a posição no áudio e a estimativa do que falta na tela o tempo todo.

Curiosidade dos números: esta CPU compartilhada chegou a ser **mais rápida que
uma máquina local de 12 núcleos** no arquivo de 5 minutos. O CTranslate2 em
`int8` não escala com quantidade de núcleos — a inferência quantizada fica presa
à largura de banda de memória e ao que cada núcleo entrega sozinho —, então
núcleos melhores valem mais que núcleos numerosos.

O reconhecimento roda na CPU deste Space: o arquivo não é repassado a nenhum
serviço de terceiro, e a imagem é a mesma que o projeto usa localmente, com o
modelo embutido. O que ele não é, e a ressalva acima diz por quê, é privado —
para isso, rode na sua máquina.

Código, decisões técnicas e auditoria de segurança:
[github.com/mvaraujo1977/transcricaoAudio](https://github.com/mvaraujo1977/transcricaoAudio)
