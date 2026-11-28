"""
Thumbnail do corte longo: imagem gerada pela Agnes AI + texto curto por cima.

Fluxo:
  1. Gemini cria o "conceito": um texto de 2 a 4 palavras e um prompt de imagem
     (visual simbolico relacionado ao tema, sem texto e sem rostos reais).
  2. Agnes AI (agnes-image-2.1-flash) gera so a IMAGEM DE FUNDO.
  3. O texto e desenhado aqui com Pillow (fonte Bangers). Geradores de imagem
     erram letras e acentos com frequencia; escrevendo nos mesmo, o texto sai
     sempre correto e legivel.

Secret: AGNES_API_KEY. Opcionais: AGNES_IMAGE_MODEL, AGNES_BASE_URL.
"""
import base64
import io
import os
import re
import time

import requests
from PIL import Image, ImageDraw, ImageFont

AGNES_BASE_URL = os.environ.get("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1").rstrip("/")
AGNES_IMAGE_MODEL = os.environ.get("AGNES_IMAGE_MODEL", "agnes-image-2.1-flash")
# tenta 16:9 primeiro; se a API recusar o tamanho, cai para o do exemplo oficial
AGNES_SIZES = ["1280x720", "1024x768"]

FONT_PATH = os.path.join("assets", "fonts", "Bangers-Regular.ttf")
THUMB_W, THUMB_H = 1280, 720
MAX_BYTES = 2 * 1024 * 1024  # limite do YouTube para thumbnail

CONCEPT_PROMPT = """Voce cria thumbnails de alto CTR para YouTube (cortes de podcast/entrevista em portugues).
Com base no corte abaixo, devolva SOMENTE um JSON:
{{"texto": "...", "prompt_imagem": "..."}}

REGRAS:
- "texto": de 2 a 4 palavras em portugues do Brasil, em MAIUSCULAS, que despertem curiosidade ou
  tensao (ex: "O FIM DE UMA ERA", "NINGUEM FALA ISSO"). Nao repita o titulo inteiro. Sem emojis,
  sem pontuacao exagerada.
- "prompt_imagem": prompt em INGLES para um gerador de imagens, descrevendo UMA cena ou metafora visual
  relacionada ao tema do corte: cinematografica, alto contraste, cores fortes, um unico ponto focal,
  formato horizontal 16:9. A parte inferior esquerda deve ter area mais escura/limpa (o texto sera
  colocado ali).
- No prompt_imagem: NAO inclua texto, letras, numeros, logos nem marcas d'agua na imagem. NAO represente
  pessoas reais nem rostos reconhecíveis (use silhuetas, objetos, simbolos, cenarios ou ilustracao).

Titulo do corte: {titulo}
Resumo: {motivo}
Trecho falado: {trecho}
"""


# ---------------------------------------------------------------- conceito

def generate_concept(titulo: str, motivo: str, trecho: str) -> dict:
    """Retorna {'texto': 'AS 3 PALAVRAS', 'prompt': 'english image prompt'}.
    Se o Gemini falhar, usa um conceito simples derivado do titulo."""
    try:
        import analyze_highlights  # import tardio (carrega o SDK do Gemini)
        data = analyze_highlights._call_gemini_json(
            CONCEPT_PROMPT.format(titulo=titulo, motivo=motivo, trecho=trecho)
        )
        if isinstance(data, list):
            data = data[0]
        texto = _clean_text(str(data["texto"]))
        prompt = str(data["prompt_imagem"]).strip()
        if texto and prompt:
            return {"texto": texto, "prompt": prompt}
    except Exception as e:
        print(f"[AVISO] Gemini nao gerou o conceito da thumbnail ({e}); usando titulo.")
    return {
        "texto": _clean_text(titulo),
        "prompt": (
            f"Cinematic dramatic symbolic illustration about: {titulo}. High contrast, bold colors, "
            "single focal point, no text, no letters, no logos, no real people, 16:9, "
            "darker clean area in the lower left."
        ),
    }


def _clean_text(text: str, max_words: int = 4) -> str:
    words = re.sub(r"[^\w\s?!.,'’-]", "", text, flags=re.UNICODE).split()
    return " ".join(words[:max_words]).upper()


# ---------------------------------------------------------------- Agnes AI

def _extract_image(payload: dict) -> Image.Image:
    """Aceita as variacoes comuns de resposta: url, b64_json ou data URI."""
    items = payload.get("data") or payload.get("images") or [payload]
    item = items[0] if isinstance(items, list) and items else items
    if isinstance(item, str):
        item = {"url": item}
    raw = item.get("b64_json") or item.get("base64") or item.get("image")
    url = item.get("url") or item.get("image_url")

    if isinstance(raw, str) and raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    if isinstance(raw, str) and not raw.startswith("http"):
        return Image.open(io.BytesIO(base64.b64decode(raw)))
    url = url or (raw if isinstance(raw, str) and raw.startswith("http") else None)
    if url:
        if url.startswith("data:"):
            return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content))
    raise RuntimeError(f"Resposta da Agnes sem imagem reconhecivel: chaves {list(item.keys())}")


def generate_background(prompt: str) -> Image.Image:
    api_key = os.environ["AGNES_API_KEY"]
    last_error = None
    for size in AGNES_SIZES:
        for attempt in range(3):
            resp = requests.post(
                f"{AGNES_BASE_URL}/images/generations",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": AGNES_IMAGE_MODEL, "prompt": prompt, "size": size},
                timeout=180,
            )
            if resp.status_code in (429, 500, 502, 503, 520):
                last_error = f"HTTP {resp.status_code}"
                time.sleep(10 * (attempt + 1))
                continue
            if resp.status_code == 400:
                last_error = f"HTTP 400 ({size}): {resp.text[:200]}"
                break  # tamanho/parametro recusado: tenta o proximo tamanho
            if resp.status_code in (401, 403):
                raise RuntimeError(f"Agnes recusou a chave (HTTP {resp.status_code}). Confira o secret AGNES_API_KEY.")
            resp.raise_for_status()
            return _extract_image(resp.json())
    raise RuntimeError(f"Agnes nao gerou a imagem: {last_error}")


# ---------------------------------------------------------------- composicao

def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.convert("RGB")
    scale = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _split_lines(words: list[str]) -> list[str]:
    if len(words) <= 2:
        return [" ".join(words)]
    best, best_diff = None, 10 ** 9  # divide em 2 linhas mais equilibradas
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        diff = abs(len(a) - len(b))
        if diff < best_diff:
            best, best_diff = [a, b], diff
    return best


def compose(background: Image.Image, texto: str, out_path: str) -> str:
    img = _cover(background, THUMB_W, THUMB_H)

    # degrade escuro embaixo/esquerda para o texto ler bem em qualquer fundo
    shade = Image.new("L", (THUMB_W, THUMB_H), 0)
    px = shade.load()
    for y in range(THUMB_H):
        for x in range(0, THUMB_W, 1):
            v = max(0.0, (y / THUMB_H - 0.35) / 0.65) * 0.85
            v = max(v, max(0.0, (0.55 - x / THUMB_W)) * 0.5)
            px[x, y] = int(255 * min(v, 0.85))
    img = Image.composite(Image.new("RGB", img.size, (0, 0, 0)), img, shade)

    lines = _split_lines(texto.split())
    margin, max_w, max_h = 60, int(THUMB_W * 0.88), int(THUMB_H * 0.5)
    draw = ImageDraw.Draw(img)
    size = 190
    while size > 60:
        font = ImageFont.truetype(FONT_PATH, size)
        stroke = max(4, size // 11)
        widths = [draw.textlength(l, font=font) + 2 * stroke for l in lines]
        height = len(lines) * size * 1.0
        if max(widths) <= max_w and height <= max_h:
            break
        size -= 6

    y = THUMB_H - margin - len(lines) * size * 1.0 + size * 0.02
    colors = [(255, 255, 255), (255, 214, 0)]  # linha 1 branca, ultima amarela
    for i, line in enumerate(lines):
        color = colors[1] if (len(lines) > 1 and i == len(lines) - 1) else colors[0]
        draw.text((margin, y + i * size), line, font=font, fill=color,
                  stroke_width=stroke, stroke_fill=(0, 0, 0))

    for quality in (93, 88, 82, 75, 65):
        img.save(out_path, "JPEG", quality=quality, optimize=True)
        if os.path.getsize(out_path) <= MAX_BYTES:
            break
    return out_path


# ---------------------------------------------------------------- API do modulo

def build_ai_thumbnail(titulo: str, motivo: str, trecho: str, out_path: str) -> dict | None:
    """Gera a thumbnail. Retorna {'path', 'texto', 'prompt'} ou None se o
    secret AGNES_API_KEY nao estiver configurado. Erros da API sobem."""
    if not os.environ.get("AGNES_API_KEY"):
        return None
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    concept = generate_concept(titulo, motivo, trecho)
    print(f"Thumbnail IA: texto='{concept['texto']}' | prompt='{concept['prompt'][:120]}...'")
    background = generate_background(concept["prompt"])
    compose(background, concept["texto"], out_path)
    return {"path": out_path, **concept}
