# Transcrição para Atas

Aplicação em Python para transcrever áudios e vídeos, gerar ata em Markdown e criar um resumo com tópicos principais, decisões e encaminhamentos.

## Recursos

- Suporte a múltiplos arquivos em fila
- Suporte a `.ogg`, `.oga`, `.opus` e formatos comuns de áudio/vídeo
- Barra de progresso com porcentagem realista por etapas
- Logs em tempo real na interface para diagnosticar travamentos e erros
- Geração de:
  - transcrição completa (`*_transcricao.txt`)
  - ata resumida (`*_ata.md`)
- Identificação local de falantes por heurística
- Resumo em tópicos, decisões, tarefas e pendências

## Requisitos

- Python 3.10+
- `ffmpeg`
- `ffprobe`
- Whisper instalado via pip

Instalação sugerida:

```bash
pip install -r requirements.txt
```

## Como usar a interface

```bash
python interface.py
```

Na janela:

1. Selecione um ou mais arquivos.
2. Clique em **Iniciar transcrição**.
3. Aguarde a fila terminar.
4. Use **Abrir ata** para abrir o arquivo gerado.

Durante a execução, acompanhe o painel **Logs de execução** para ver cada etapa
(ffprobe, ffmpeg, carga do modelo e transcrição). Um arquivo `.log` também é
salvo em `transcricoes/logs/`.

## Como usar no terminal

```bash
python transcrever.py /caminho/para/audio.ogg
```

## Saída gerada

Os arquivos são salvos na pasta `transcricoes/`:

- `nome_do_arquivo_transcricao.txt`
- `nome_do_arquivo_ata.md`

## Observação sobre falantes

A identificação de falantes é local e heurística quando não há bibliotecas especializadas de diarização instaladas.
Para diarização real, você pode integrar `whisperx` ou `pyannote.audio` posteriormente.

