# Pipeline de Shorts Automáticos (100% gratuito, sem cartão de crédito)

Automatiza: buscar vídeo → baixar → transcrever → achar momentos fortes → cortar em
formato vertical com legenda → publicar como Short no YouTube.

⚠️ **Use apenas com canais seus ou com autorização expressa do titular do canal.**
O arquivo `channels_allowlist.json` funciona como um "freio de mão": o pipeline
recusa a rodar em qualquer canal que não esteja nessa lista.

## Componentes e por que são gratuitos

| Etapa | Ferramenta | Custo |
|---|---|---|
| Buscar vídeos / metadados | YouTube Data API v3 | Grátis (cota diária) |
| Download | yt-dlp | Grátis, open source |
| Transcrição | faster-whisper (local) | Grátis, roda na sua máquina |
| Detecção de momentos fortes | Google Gemini API (AI Studio) | Grátis, **não pede cartão** |
| Corte / vertical / legenda | ffmpeg | Grátis, open source |
| Upload do Short | YouTube Data API v3 | Grátis (cota diária) |
| Orquestração/agendamento | n8n (self-hosted) ou cron/GitHub Actions | Grátis |

Não uso OpenAI nem Anthropic API porque ambas pedem cartão de crédito cadastrado
mesmo para o nível "gratuito". O Gemini (via https://aistudio.google.com) libera
uma cota grátis apenas com login Google, sem cartão. Se no seu caso a política
mudar, dá pra trocar `analyze_highlights.py` para usar Ollama local (modelo
open-source, sem internet) — deixei a alternativa comentada no arquivo.

## Setup

```bash
pip install -r requirements.txt
# instale o ffmpeg do seu sistema (não é pip):
# Ubuntu: sudo apt install ffmpeg
# Mac: brew install ffmpeg
```

Crie um arquivo `.env` (copie de `.env.example`) com:

- `YOUTUBE_API_KEY` — YouTube Data API v3 (Google Cloud Console, plano grátis)
- `GEMINI_API_KEY` — Google AI Studio (grátis, sem cartão): https://aistudio.google.com/app/apikey
- `YOUTUBE_OAUTH_CLIENT_SECRETS` — caminho do client_secrets.json (necessário só
  para o **upload**, que exige OAuth de dono do canal — não dá pra fazer com
  API key simples)

Edite `channels_allowlist.json` com os canais autorizados (ID do canal + nome).

## Ordem de execução (por vídeo)

```bash
python pipeline.py --video-id VIDEO_ID
```

Isso roda em sequência: `download.py` → `transcribe.py` →
`analyze_highlights.py` → `cut_shorts.py` → `upload_short.py`.

Cada script também funciona isolado, útil pra depurar uma etapa sem repetir tudo.

## Agendamento

Para rodar sozinho todos os dias, duas opções grátis:
1. **Cron** na sua própria máquina/servidor (`crontab -e`), rodando `python watch_channels.py`.
2. **GitHub Actions** (grátis até um limite de minutos/mês) com um workflow
   agendado (`schedule: cron`) que faz checkout do repo e executa o pipeline.

## Limites a saber
- YouTube Data API v3 tem cota diária (10.000 unidades/dia no padrão); upload
  custa ~1600 unidades, então há um limite prático de uploads/dia no plano grátis.
- Gemini free tier tem limite de requisições por minuto/dia — o script já trata
  erro 429 com retry simples.
- faster-whisper local é mais lento sem GPU, mas funciona em CPU.
