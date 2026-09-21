---
title: Transcrição de Áudio
emoji: 🎙️
colorFrom: green
colorTo: gray
sdk: docker
app_port: 8501
pinned: false
license: mit
short_description: Transcreve áudio e vídeo em texto, com Whisper, sem nuvem
---

# Transcrição de áudio

Demo de uma ferramenta que transcreve áudio e vídeo em texto editável com o
modelo Whisper (via `faster-whisper`), exportando em `.txt` e `.pdf`.

- **Sem arquivo à mão?** Use **Testar com exemplo**: 24 s de *O Alienista*, de
  Machado de Assis, em domínio público.
- **Transcreve, não traduz** — o texto sai no idioma falado no áudio.
- **Limites desta demo**: 5 minutos de áudio, 50 MB por arquivo e modelo `base`,
  porque a CPU aqui é compartilhada. Rodando local, o padrão é `small` com teto
  de 4 horas.
- A demo **hiberna** depois de um tempo sem uso: a primeira visita pode levar
  cerca de um minuto para acordar.

O reconhecimento roda na CPU deste Space — nenhum arquivo é enviado para outro
serviço. A imagem é a mesma que o projeto usa localmente, com o modelo embutido.

Código, decisões técnicas e auditoria de segurança:
[github.com/mvaraujo1977/transcricaoAudio](https://github.com/mvaraujo1977/transcricaoAudio)
