"""
Analisa a transcricao e retorna os melhores trechos para cortar em Shorts.
Padrao: Google Gemini API (aistudio.google.com) - tem camada gratuita que
NAO exige cartao de credito, apenas login Google.
Alternativa 100% local/offline: Ollama (ollama.com) rodando um modelo
open-source (ex: llama3.1) na sua propria maquina, sem depender de API
nenhuma. O bloco de codigo para isso esta comentado mais abaixo -
troque a chamada em `find_highlights()` se preferir esse caminho.
"""
import argparse
import json
import os
import time

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

HIGHLIGHTS_DIR = "highlights"
MIN_CLIP_SECONDS = 30
MAX_CLIP_SECONDS = 90
NUM_CLIPS = 3
# gemini-1.5-flash foi desativado pelo Google. gemini-2.5-flash-lite e o
# substituto recomendado, ainda coberto pelo free tier (sem cartao).
MODEL_NAME = "gemini-2.5-flash-lite"

PROMPT_TEMPLATE = """Voce e um editor de video especialista em cortes virais para Shorts/Reels.
Abaixo esta a transcricao de um video com timestamps (em segundos).
Escolha ate {num_clips} trechos que funcionem como cortes independentes e
que tenham potencial de engajamento (polemica, virada de argumento, frase
de impacto, revelacao, piada, confronto).
IMPORTANTE sobre duracao: nao escolha so a frase de impacto isolada.
Inclua o CONTEXTO ao redor dela (o que motivou aquela fala, a pergunta que
a provocou, a reacao ou conclusao logo depois) para o corte fazer sentido
sozinho para quem nao viu o video inteiro. Cada trecho deve ter DURACAO
MINIMA DE {min_s} SEGUNDOS (isso e obrigatorio, nao aceite trechos mais
curtos) e no maximo {max_s} segundos. Prefira trechos mais completos, com
comeco (contexto/pergunta), meio (desenvolvimento) e fim (conclusao/climax),
em vez de cortes secos de uma unica frase curta.
Responda SOMENTE com JSON valido, no formato:
[
  {{"start": 123.4, "end": 178.9, "titulo": "titulo curto e chamativo", "motivo": "por que esse trecho funciona"}}
]
Transcricao:
{transcript}
"""


def _format_transcript(segments: list[dict]) -> str:
    lines = [f"[{s['start']}-{s['end']}] {s['text']}" for s in segments]
    return "\n".join(lines)


def _enforce_duration(highlight: dict, segments: list[dict]) -> dict:
    """O Gemini as vezes ignora a duracao minima pedida no prompt. Aqui a
    gente garante isso na marra: se o trecho veio curto, estende o fim
    (ou puxa o inicio para tras) usando os limites reais dos segmentos da
    transcricao, para nao cortar no meio de uma frase. Tambem garante que
    nao passe do maximo."""
    start = highlight["start"]
    end = highlight["end"]
    ordered = sorted(segments, key=lambda s: s["start"])

    if end - start < MIN_CLIP_SECONDS:
        # 1) tenta estender para frente, pegando os proximos segmentos inteiros
        for seg in ordered:
            if end - start >= MIN_CLIP_SECONDS:
                break
            if seg["start"] >= end:
                end = seg["end"]

        # 2) se ainda faltar (ex: clipe perto do fim do video), tenta puxar
        #    o inicio para tras usando os segmentos anteriores
        if end - start < MIN_CLIP_SECONDS:
            for seg in reversed(ordered):
                if end - start >= MIN_CLIP_SECONDS:
                    break
                if seg["end"] <= start:
                    start = seg["start"]

    if end - start > MAX_CLIP_SECONDS:
        end = start + MAX_CLIP_SECONDS

    return {**highlight, "start": start, "end": end}


def _dedupe_highlights(highlights: list[dict], overlap_threshold: float = 0.6) -> list[dict]:
    """Remove trechos que sobrepoem demais um trecho ja aceito (ex: quando
    a extensao de duracao minima faz dois highlights curtos convergirem
    para praticamente o mesmo intervalo). Mantem a ordem de preferencia
    original do Gemini (primeira ocorrencia de cada intervalo e mantida)."""
    accepted = []
    for h in highlights:
        h_dur = h["end"] - h["start"]
        is_dupe = False
        for a in accepted:
            overlap = max(0, min(h["end"], a["end"]) - max(h["start"], a["start"]))
            a_dur = a["end"] - a["start"]
            shorter = min(h_dur, a_dur)
            if shorter > 0 and overlap / shorter > overlap_threshold:
                is_dupe = True
                break
        if not is_dupe:
            accepted.append(h)
    return accepted


def find_highlights_gemini(segments: list[dict]) -> list[dict]:
    api_key = os.environ["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
    prompt = PROMPT_TEMPLATE.format(
        num_clips=NUM_CLIPS,
        min_s=MIN_CLIP_SECONDS,
        max_s=MAX_CLIP_SECONDS,
        transcript=_format_transcript(segments),
    )
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    max_output_tokens=4096,
                ),
            )
            text = response.text.strip()
            text = text.removeprefix("```json").removesuffix("```").strip()
            highlights = json.loads(text)
            highlights = [_enforce_duration(h, segments) for h in highlights]
            return _dedupe_highlights(highlights)
        except json.JSONDecodeError as e:
            # O Gemini as vezes devolve JSON truncado/invalido (ex: resposta
            # cortada no limite de tokens). Tenta de novo antes de desistir.
            print(f"[AVISO] Gemini retornou JSON invalido (tentativa {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(5)
                continue
            raise
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                time.sleep(20)  # cota do free tier: espera e tenta de novo
                continue
            raise


# --- Alternativa 100% local, sem nenhuma API externa (opcional) ---
# import requests
# def find_highlights_ollama(segments: list[dict]) -> list[dict]:
#     prompt = PROMPT_TEMPLATE.format(
#         num_clips=NUM_CLIPS, min_s=MIN_CLIP_SECONDS, max_s=MAX_CLIP_SECONDS,
#         transcript=_format_transcript(segments),
#     )
#     resp = requests.post(
#         "http://localhost:11434/api/generate",
#         json={"model": "llama3.1", "prompt": prompt, "stream": False},
#     )
#     text = resp.json()["response"].strip()
#     text = text.removeprefix("```json").removesuffix("```").strip()
#     return json.loads(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    args = parser.parse_args()
    with open(f"transcripts/{args.video_id}.json", "r", encoding="utf-8") as f:
        segments = json.load(f)
    highlights = find_highlights_gemini(segments)
    os.makedirs(HIGHLIGHTS_DIR, exist_ok=True)
    out_path = os.path.join(HIGHLIGHTS_DIR, f"{args.video_id}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(highlights, f, ensure_ascii=False, indent=2)
    print(f"[OK] {len(highlights)} highlights salvos em {out_path}")
    return out_path


if __name__ == "__main__":
    main()
