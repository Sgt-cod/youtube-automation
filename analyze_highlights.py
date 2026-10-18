"""
Analisa a transcricao e retorna os melhores trechos para cortar.

Por que os cortes saiam sem contexto (e o que mudou):
  1. O Gemini devolvia segundos "soltos"; agora ele escolhe INDICES de
     segmentos da transcricao, entao o corte sempre comeca/termina em
     fronteira real de fala.
  2. O codigo antigo cortava na marra em start+MAX (no meio da frase) e
     estendia a duracao minima em segmentos arbitrarios. Agora o inicio e o
     fim sao "encaixados" em fronteiras de frase (ponto final / ? / !).
  3. O prompt nao exigia que o trecho FECHASSE a ideia (ex: "sao 3 fatores"
     e o corte acabava no 1o). Prompt reescrito com essas regras.
  4. Nova etapa de VERIFICACAO: uma segunda chamada ao Gemini le o trecho
     final (com contexto antes/depois) e aprova, ajusta ou reprova. Corte
     reprovado e descartado: melhor menos cortes do que um corte quebrado.

Tambem serve para o corte longo (5-6 min): ver find_long_highlight().
"""
import argparse
import json
import os
import re
import time
from dataclasses import dataclass

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

HIGHLIGHTS_DIR = "highlights"
MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

START_PAD = 0.15  # folga (s) antes da primeira palavra
END_PAD = 0.40    # folga (s) depois da ultima palavra (sem invadir o proximo segmento)

SENTENCE_END_RE = re.compile(r"[.?!\u2026][\"')\]\u201d]*$")


@dataclass
class ClipConfig:
    name: str
    min_s: int        # duracao minima
    max_s: int        # duracao ideal maxima
    hard_max_s: int   # limite absoluto (so usado para conseguir fechar a ideia)
    num_clips: int    # quantos cortes queremos no final
    candidates: int   # quantos candidatos pedir ao Gemini (sobra p/ reprovados)
    ctx_before: int   # segmentos de contexto antes (na verificacao)
    ctx_after: int    # segmentos de contexto depois (na verificacao)


# Shorts: ideal 40-120s; pode ir ate 170s se for preciso para fechar a ideia
# (Short aceita ate 3 min). Ajuste por variavel de ambiente se quiser.
SHORT_CONFIG = ClipConfig(
    name="short",
    min_s=int(os.environ.get("SHORT_MIN_SECONDS", 40)),
    max_s=int(os.environ.get("SHORT_MAX_SECONDS", 120)),
    hard_max_s=int(os.environ.get("SHORT_HARD_MAX_SECONDS", 170)),
    num_clips=3,
    candidates=5,
    ctx_before=6,
    ctx_after=10,
)

# Corte longo: 5-6 min (pode passar um pouco para terminar a frase/ideia)
LONG_CONFIG = ClipConfig(
    name="long",
    min_s=int(os.environ.get("LONG_MIN_SECONDS", 300)),
    max_s=int(os.environ.get("LONG_MAX_SECONDS", 360)),
    hard_max_s=int(os.environ.get("LONG_HARD_MAX_SECONDS", 420)),
    num_clips=1,
    candidates=3,
    ctx_before=10,
    ctx_after=20,
)

# Mantidos por compatibilidade com outros scripts
MIN_CLIP_SECONDS = SHORT_CONFIG.min_s
MAX_CLIP_SECONDS = SHORT_CONFIG.max_s
NUM_CLIPS = SHORT_CONFIG.num_clips

RULES = """REGRAS DE OURO (um corte quebrado e pior que nenhum corte):
1. COMECO: o primeiro segmento deve iniciar uma frase e fazer sentido para quem
   nao viu o video. Se o trecho e uma resposta, COMECE NA PERGUNTA que a motivou.
   Nunca comece em "isso", "ele", "entao", "mas", "e ai" sem que o referente
   esteja dentro do corte.
2. FIM: o ultimo segmento deve encerrar uma frase E fechar a ideia. Se a pessoa
   anuncia uma lista ("sao 3 fatores", "tem duas razoes"), o corte so termina
   DEPOIS do ultimo item. Nunca termine em frase que introduz algo ("o primeiro
   e...", "deixa eu te explicar") nem no meio de um raciocinio.
3. Prefira terminar numa conclusao, climax, piada ou frase de impacto, e
   pode incluir a reacao curta de quem ouviu logo depois.
4. DURACAO: entre {min_s}s e {max_s}s e o ideal. Se for necessario para
   FECHAR a ideia, pode passar disso, ate o maximo absoluto de {hard_max_s}s.
   Trecho com menos de {min_s}s so e aceitavel se a ideia estiver completa.
5. Use SOMENTE os indices dos segmentos (numero entre colchetes). Os indices
   sao inclusivos: start_idx e o primeiro segmento, end_idx e o ultimo.
"""

SHORT_PROMPT = """Voce e um editor de video especialista em cortes virais para Shorts/Reels.
Abaixo esta a transcricao de um video, um segmento por linha, no formato
[indice|tempo_em_segundos] texto.
Escolha {candidates} trechos candidatos, do melhor para o pior, que funcionem como
cortes INDEPENDENTES e tenham potencial de engajamento (polemica, virada de
argumento, revelacao, piada, confronto, historia completa). Os trechos nao
podem se sobrepor.

{rules}
Responda SOMENTE com JSON valido, no formato:
[
  {{"start_idx": 120, "end_idx": 141, "titulo": "titulo curto e chamativo", "motivo": "por que funciona", "arco": "pergunta -> resposta -> conclusao"}}
]

Transcricao:
{transcript}
"""

LONG_PROMPT = """Voce e um editor de video de podcasts/entrevistas para o YouTube.
Abaixo esta a transcricao de um video, um segmento por linha, no formato
[indice|tempo_em_segundos] texto.
Escolha {candidates} trechos candidatos, do melhor para o pior, de CERCA DE 5 A 6 MINUTOS
cada, que funcionem como um "mini-episodio": um assunto coerente, com
abertura clara (apresenta o tema ou a pergunta), desenvolvimento e um fim natural
(conclusao, virada ou fechamento do assunto). Priorize assuntos que prendem
a atencao do inicio ao fim. Os trechos nao podem se sobrepor.

{rules}
Responda SOMENTE com JSON valido, no formato:
[
  {{"start_idx": 120, "end_idx": 410, "titulo": "titulo chamativo (max 90 caracteres)", "motivo": "descricao de 2-3 frases do que acontece no trecho, para a descricao do video", "arco": "abertura -> desenvolvimento -> conclusao"}}
]

Transcricao:
{transcript}
"""

VERIFY_PROMPT = """Voce e um revisor de cortes de video. Abaixo esta um trecho CANDIDATO
(linhas marcadas com >>) cercado por contexto (linhas sem marca). Formato:
[indice|tempo] texto.

Avalie se o trecho marcado funciona sozinho para quem nao viu o video:
- COMECO: a primeira frase e compreensivel sem o que veio antes? Se depende de
  uma pergunta ou referencia anterior, volte o start_idx para incluir.
- FIM: o ultimo segmento fecha a ideia? Respondeu tudo que prometeu (ex: "sao 3
  fatores" com os 3 explicados)? Ou ficou no meio / na introducao de algo? Se
  faltou, avance o end_idx.
- Voce SO pode escolher indices que aparecem na lista abaixo.
- Se mesmo ajustando dentro do contexto o corte nao fica bom, aprovado=false.
Responda SOMENTE com JSON:
{{"aprovado": true, "start_idx": N, "end_idx": N, "problema": "o que foi ajustado ou por que reprovou (vazio se estava ok)"}}
start_idx/end_idx sao as fronteiras FINAIS que voce recomenda.

Trecho:
{block}
"""


# ---------------------------------------------------------------- Gemini

def _call_gemini_json(prompt: str):
    """Chama o Gemini e devolve o JSON parseado, com retry para JSON invalido,
    limite de cota (429) e sobrecarga (500/503)."""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    attempts = 4
    for attempt in range(attempts):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    max_output_tokens=8192,
                ),
            )
            text = response.text.strip()
            text = text.removeprefix("```json").removesuffix("```").strip()
            return json.loads(text)
        except json.JSONDecodeError as e:
            print(f"[AVISO] Gemini retornou JSON invalido (tentativa {attempt+1}/{attempts}): {e}")
            if attempt < attempts - 1:
                time.sleep(5)
                continue
            raise
        except Exception as e:
            msg = str(e)
            transient = any(code in msg for code in ("429", "500", "503"))
            if transient and attempt < attempts - 1:
                time.sleep(20)
                continue
            raise


# ---------------------------------------------------------------- helpers de segmento

def _is_sentence_end(seg: dict) -> bool:
    return bool(SENTENCE_END_RE.search(seg["text"].strip()))


def _span(segments: list[dict], s: int, e: int) -> float:
    return segments[e]["end"] - segments[s]["start"]


def _format_transcript(segments: list[dict]) -> str:
    return "\n".join(
        f"[{i}|{s['start']:.0f}] {s['text']}" for i, s in enumerate(segments)
    )


def _snap_to_sentences(
    s: int, e: int, segments: list[dict], cfg: ClipConfig, lock_start: bool = False,
) -> tuple[int, int]:
    """Ajusta indices para o corte comecar no inicio de uma frase e terminar
    no fim de uma frase, respeitando o limite absoluto de duracao.
    lock_start=True: o inicio foi escolhido pelo usuario e nao pode mudar."""
    last = len(segments) - 1
    s = max(0, min(s, last))
    e = max(s, min(e, last))

    # inicio: se o segmento anterior nao fechou frase, o atual e continuacao
    for _ in range(0 if lock_start else 4):
        if s > 0 and not _is_sentence_end(segments[s - 1]) \
                and _span(segments, s - 1, e) <= cfg.hard_max_s:
            s -= 1
        else:
            break

    # fim: avanca ate fechar a frase
    for _ in range(5):
        if e < last and not _is_sentence_end(segments[e]) \
                and _span(segments, s, e + 1) <= cfg.hard_max_s:
            e += 1
        else:
            break

    # duracao minima: estende em frases inteiras (primeiro pra frente)
    while _span(segments, s, e) < cfg.min_s and e < last:
        e += 1
        while e < last and not _is_sentence_end(segments[e]) \
                and _span(segments, s, e + 1) <= cfg.hard_max_s:
            e += 1
        if _span(segments, s, e) > cfg.hard_max_s:
            break
    while not lock_start and _span(segments, s, e) < cfg.min_s and s > 0:
        s -= 1
        while s > 0 and not _is_sentence_end(segments[s - 1]) \
                and _span(segments, s - 1, e) <= cfg.hard_max_s:
            s -= 1

    # acima do limite absoluto: recua o fim para a ultima frase completa
    if _span(segments, s, e) > cfg.hard_max_s:
        k = e
        while k > s and (_span(segments, s, k) > cfg.hard_max_s or not _is_sentence_end(segments[k])):
            k -= 1
        if k > s:
            e = k
    return s, e


def _to_times(s: int, e: int, segments: list[dict]) -> tuple[float, float]:
    start = max(segments[s]["start"] - START_PAD, 0.0)
    end = segments[e]["end"]
    if e + 1 < len(segments):
        nxt = segments[e + 1]["start"]
        end = min(end + END_PAD, max(nxt - 0.02, end))
    else:
        end += END_PAD
    return round(start, 2), round(end, 2)


def _build_clip(raw: dict, s: int, e: int, segments: list[dict]) -> dict:
    start, end = _to_times(s, e, segments)
    return {
        "start": start,
        "end": end,
        "start_idx": s,
        "end_idx": e,
        "titulo": raw.get("titulo", ""),
        "motivo": raw.get("motivo", ""),
        "arco": raw.get("arco", ""),
    }


def _overlaps(s: int, e: int, accepted: list[tuple[int, int]]) -> bool:
    for a, b in accepted:
        inter = max(0, min(e, b) - max(s, a) + 1)
        shorter = min(e - s + 1, b - a + 1)
        if shorter > 0 and inter / shorter > 0.3:
            return True
    return False


def _verify(s: int, e: int, segments: list[dict], cfg: ClipConfig):
    """Segunda opiniao do Gemini sobre o corte. Retorna (aprovado, s, e,
    problema). Se a chamada falhar, nao derruba o pipeline: devolve o corte
    como esta (aprovado) com um aviso."""
    lo = max(0, s - cfg.ctx_before)
    hi = min(len(segments) - 1, e + cfg.ctx_after)
    lines = []
    for i in range(lo, hi + 1):
        mark = ">> " if s <= i <= e else "   "
        lines.append(f"{mark}[{i}|{segments[i]['start']:.0f}] {segments[i]['text']}")
    try:
        data = _call_gemini_json(VERIFY_PROMPT.format(block="\n".join(lines)))
        if isinstance(data, list):
            data = data[0]
        ns = int(data.get("start_idx", s))
        ne = int(data.get("end_idx", e))
        ns = max(lo, min(ns, hi))
        ne = max(ns, min(ne, hi))
        return bool(data.get("aprovado", True)), ns, ne, data.get("problema", "")
    except Exception as exc:
        print(f"[AVISO] Verificacao falhou ({exc}); mantendo o corte sem revisao.")
        return True, s, e, ""


# ---------------------------------------------------------------- inicio escolhido pelo usuario

END_PROMPT = """Voce e um editor de video. O usuario escolheu manualmente ONDE O CORTE COMECA:
o segmento marcado com >> . O inicio e FIXO, nao mude. Sua tarefa e escolher onde
o corte TERMINA (end_idx) e dar um titulo.
Formato das linhas: [indice|tempo_em_segundos] texto.

{rules}
Responda SOMENTE com JSON:
{{"end_idx": N, "titulo": "titulo curto e chamativo", "motivo": "descricao de 1-3 frases do que acontece no trecho", "arco": "..."}}
end_idx deve ser >= {start_idx} e aparecer na lista abaixo.

Trecho:
{block}
"""


def parse_start_seconds(text: str) -> list[float]:
    """'60, 120 130; 1:56 1:02:03' -> [60.0, 120.0, 130.0, 116.0, 3723.0].
    Aceita virgula, ponto e virgula, espaco ou quebra de linha; mm:ss e hh:mm:ss."""
    values = []
    for tok in re.split(r"[,;\s]+", (text or "").strip()):
        if not tok:
            continue
        try:
            secs = 0.0
            for part in tok.split(":"):
                secs = secs * 60 + float(part.replace(",", "."))
        except ValueError:
            raise ValueError(f"Segundo invalido: '{tok}'. Use numeros, ex: 60, 120, 130 (ou 1:30).")
        values.append(secs)
    return values


def _locate_start(t: float, segments: list[dict]):
    """Acha (indice_do_segmento, tempo_exato_de_inicio) para o segundo t.
    O corte comeca na primeira palavra que inicia a partir de t (com 0.4s de
    tolerancia), que e o que o usuario esta vendo no player."""
    for i, seg in enumerate(segments):
        if seg["end"] <= t - 0.4:
            continue
        for w in seg.get("words", []):
            if w["start"] >= t - 0.4:
                return i, w["start"]
        if seg["start"] >= t - 0.4:
            return i, seg["start"]
    return None


def _fallback_end(s: int, segments: list[dict], cfg: ClipConfig) -> int:
    e = s
    while e < len(segments) - 1 and _span(segments, s, e) < cfg.min_s:
        e += 1
    return e


def find_clips_from_starts(segments: list[dict], starts: list[float], cfg: ClipConfig) -> list[dict]:
    """Um corte para cada segundo informado pelo usuario. O inicio e respeitado;
    o Gemini escolhe apenas onde terminar para fechar a ideia."""
    rules = RULES.format(min_s=cfg.min_s, max_s=cfg.max_s, hard_max_s=cfg.hard_max_s)
    clips = []
    for t in starts:
        found = _locate_start(t, segments)
        if not found:
            print(f"[AVISO] Segundo {t:g} nao tem fala (depois do fim do video ou sem transcricao); ignorado.")
            continue
        s_idx, start_time = found

        # janela: do inicio ate hard_max + folga, para o Gemini ver o fechamento
        hi = s_idx
        while hi < len(segments) - 1 and segments[hi]["end"] - start_time < cfg.hard_max_s + 40:
            hi += 1
        lines = [
            f"{'>> ' if i == s_idx else '   '}[{i}|{segments[i]['start']:.0f}] {segments[i]['text']}"
            for i in range(s_idx, hi + 1)
        ]
        raw = {}
        try:
            raw = _call_gemini_json(END_PROMPT.format(
                rules=rules, start_idx=s_idx, block="\n".join(lines)))
            if isinstance(raw, list):
                raw = raw[0]
            e = max(s_idx, min(int(raw["end_idx"]), hi))
        except Exception as exc:
            print(f"[AVISO] Gemini nao definiu o fim do corte em {t:g}s ({exc}); usando fim por frase.")
            raw = {"titulo": f"Corte aos {int(t)}s"}
            e = _fallback_end(s_idx, segments, cfg)

        _, e = _snap_to_sentences(s_idx, e, segments, cfg, lock_start=True)
        clip = _build_clip(raw, s_idx, e, segments)
        clip["start"] = round(max(start_time - START_PAD, 0.0), 2)
        clip["start_requested"] = t
        if not clip["titulo"]:
            clip["titulo"] = f"Corte aos {int(t)}s"
        dur = clip["end"] - clip["start"]
        print(f"[OK] Corte a partir de {t:g}s -> {clip['start']:.1f}s a {clip['end']:.1f}s ({dur:.0f}s): {clip['titulo']}")
        clips.append(clip)
        time.sleep(1)
    return clips


# ---------------------------------------------------------------- API principal

def find_highlights(segments: list[dict], cfg: ClipConfig) -> list[dict]:
    prompt_tpl = LONG_PROMPT if cfg.name == "long" else SHORT_PROMPT
    prompt = prompt_tpl.format(
        candidates=cfg.candidates,
        rules=RULES.format(min_s=cfg.min_s, max_s=cfg.max_s, hard_max_s=cfg.hard_max_s),
        transcript=_format_transcript(segments),
    )
    raw_list = _call_gemini_json(prompt)
    if isinstance(raw_list, dict):
        raw_list = [raw_list]

    accepted, accepted_ranges = [], []
    for raw in raw_list:
        if len(accepted) >= cfg.num_clips:
            break
        try:
            s, e = int(raw["start_idx"]), int(raw["end_idx"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= s <= e < len(segments)):
            continue

        s, e = _snap_to_sentences(s, e, segments, cfg)
        approved, vs, ve, problema = _verify(s, e, segments, cfg)
        if not approved:
            print(f"[REPROVADO] '{raw.get('titulo', '')}': {problema}")
            continue
        if (vs, ve) != (s, e):
            print(f"[AJUSTADO] '{raw.get('titulo', '')}': {problema}")
            s, e = _snap_to_sentences(vs, ve, segments, cfg)

        if _span(segments, s, e) > cfg.hard_max_s:
            print(f"[DESCARTADO] '{raw.get('titulo', '')}': passa de {cfg.hard_max_s}s para fechar a ideia.")
            continue
        if _span(segments, s, e) < cfg.min_s * 0.6:
            print(f"[DESCARTADO] '{raw.get('titulo', '')}': curto demais.")
            continue
        if _overlaps(s, e, accepted_ranges):
            continue

        accepted.append(_build_clip(raw, s, e, segments))
        accepted_ranges.append((s, e))
        time.sleep(1)  # respiro entre chamadas (cota gratuita)
    return accepted


def find_highlights_gemini(segments: list[dict]) -> list[dict]:
    """Shorts. Assinatura mantida para o pipeline.py."""
    return find_highlights(segments, SHORT_CONFIG)


def find_long_highlight(segments: list[dict]) -> list[dict]:
    """Corte longo (5-6 min). Retorna lista com 0 ou 1 clipe."""
    return find_highlights(segments, LONG_CONFIG)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--long", action="store_true", help="modo corte longo (5-6 min)")
    parser.add_argument("--starts", default=None, help="segundos de inicio escolhidos, ex: \"60,120,130\"")
    args = parser.parse_args()
    with open(f"transcripts/{args.video_id}.json", "r", encoding="utf-8") as f:
        segments = json.load(f)
    cfg = LONG_CONFIG if args.long else SHORT_CONFIG
    if args.starts:
        highlights = find_clips_from_starts(segments, parse_start_seconds(args.starts), cfg)
    else:
        highlights = find_highlights(segments, cfg)
    os.makedirs(HIGHLIGHTS_DIR, exist_ok=True)
    out_path = os.path.join(HIGHLIGHTS_DIR, f"{args.video_id}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(highlights, f, ensure_ascii=False, indent=2)
    print(f"[OK] {len(highlights)} highlights salvos em {out_path}")
    return out_path


if __name__ == "__main__":
    main()
