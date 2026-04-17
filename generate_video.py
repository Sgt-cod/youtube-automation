import os
import json
import random
import re
import time
import requests
import feedparser
from datetime import datetime
from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeVideoClip,
    concatenate_videoclips, ColorClip
)
from google import generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ─────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────
CONFIG_FILE = 'config.json'
ASSETS_DIR  = 'assets'
VIDEOS_DIR  = 'videos'

GEMINI_API_KEY      = os.environ.get('GEMINI_API_KEY')
PEXELS_API_KEY      = os.environ.get('PEXELS_API_KEY')
YOUTUBE_CREDENTIALS = os.environ.get('YOUTUBE_CREDENTIALS')

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

DURACAO_ALVO_MIN = config.get('duracao_alvo_minutos', 7)
PALAVRAS_POR_SEG = 2.5
PALAVRAS_ALVO    = int(DURACAO_ALVO_MIN * 60 * PALAVRAS_POR_SEG)  # ~1050 para 7min


# ─────────────────────────────────────────────
# 1. ESCOLHA DO TEMA
# ─────────────────────────────────────────────

def buscar_tema_via_rss():
    """Tenta extrair inspiração de tema a partir dos feeds RSS configurados."""
    feeds = config.get('rss_feeds_inspiracao', [])
    titulos = []

    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                titulos.append(entry.title.strip())
        except Exception as e:
            print(f"  ⚠️ Feed ignorado ({url[:40]}): {e}")

    if not titulos:
        return None

    # Pede ao Gemini para transformar os títulos em um tema original em PT-BR
    prompt = f"""Você recebeu estes títulos de podcasts e artigos filosóficos em inglês:

{chr(10).join(f'- {t}' for t in titulos[:10])}

Com base neles, escolha ou crie UM tema original em português brasileiro para um vídeo reflexivo no YouTube.
O tema deve ser profundo, acessível e instigante.

Retorne APENAS o tema, sem explicações, sem aspas, sem pontuação final."""

    try:
        response = model.generate_content(prompt)
        tema = response.text.strip().strip('"').strip("'")
        print(f"  💡 Tema via RSS: {tema}")
        return tema
    except Exception as e:
        print(f"  ⚠️ Gemini falhou ao processar RSS: {e}")
        return None


def escolher_tema():
    """Escolhe o tema do vídeo: tenta RSS primeiro, depois lista de temas ou Gemini."""
    print("🎯 Escolhendo tema...")

    # Tentativa 1: RSS
    if config.get('rss_feeds_inspiracao'):
        tema_rss = buscar_tema_via_rss()
        if tema_rss:
            return tema_rss

    # Tentativa 2: Gemini escolhe livremente baseado nos temas da lista
    temas_lista = config.get('temas', [])
    temas_amostra = random.sample(temas_lista, min(5, len(temas_lista)))

    prompt = f"""Você é um criador de conteúdo filosófico e reflexivo para YouTube.

Estes são alguns temas de referência:
{chr(10).join(f'- {t}' for t in temas_amostra)}

Escolha UM tema para o próximo vídeo. Pode ser um destes ou uma variação original.
O tema deve ser profundo, atual e ressoar com pessoas em busca de autoconhecimento.

Retorne APENAS o tema escolhido, sem explicações."""

    try:
        response = model.generate_content(prompt)
        tema = response.text.strip().strip('"').strip("'")
        print(f"  💡 Tema via Gemini: {tema}")
        return tema
    except Exception:
        # Fallback final: lista local
        tema = random.choice(temas_lista)
        print(f"  💡 Tema via lista local: {tema}")
        return tema


# ─────────────────────────────────────────────
# 2. GERAÇÃO DO ROTEIRO
# ─────────────────────────────────────────────

def gerar_roteiro(tema):
    """Gera roteiro completo e segmentado para o vídeo."""
    print(f"\n✍️ Gerando roteiro para: '{tema}'")

    estilo = random.choice(config.get('estilos_narrativa', ['reflexivo e contemplativo']))

    prompt = f"""Você é um roteirista especializado em vídeos filosóficos e reflexivos para YouTube.

TEMA: {tema}
ESTILO: {estilo}
DURAÇÃO ALVO: {DURACAO_ALVO_MIN} minutos (~{PALAVRAS_ALVO} palavras)

Crie um roteiro de narração em português brasileiro seguindo EXATAMENTE esta estrutura:

[INTRO]
Abertura impactante de 2-3 frases que prende o espectador imediatamente. Uma pergunta ou afirmação provocadora.

[DESENVOLVIMENTO_1]
Primeiro bloco de desenvolvimento do tema. Contexto histórico, filosófico ou científico. Apresente o problema ou a questão central.

[DESENVOLVIMENTO_2]
Aprofundamento. Traga um filósofo, pensador ou exemplo real. Explore a ideia central com profundidade.

[DESENVOLVIMENTO_3]
Virada ou perspectiva diferente. Como isso se aplica à vida cotidiana moderna. Exemplos práticos e palpáveis.

[REFLEXAO]
Momento contemplativo. Perguntas para o espectador refletir. Tom mais lento e introspectivo.

[CONCLUSAO]
Síntese poderosa. Uma ideia que o espectador vai levar para a vida. Encerramento que convida à ação interna.

REGRAS OBRIGATÓRIAS:
- Escreva APENAS o texto de narração, sem didascálias, sem indicações de câmera
- NÃO use asteriscos, hashtags, bullets, emojis ou qualquer formatação
- Texto corrido, natural para ser falado em voz alta
- Cada bloco deve ter entre {PALAVRAS_ALVO // 6} e {PALAVRAS_ALVO // 4} palavras
- Total aproximado: {PALAVRAS_ALVO} palavras
- Mantenha as marcações [INTRO], [DESENVOLVIMENTO_1] etc. para segmentação

Escreva o roteiro agora:"""

    response = model.generate_content(prompt)
    roteiro_bruto = response.text

    # Limpar formatação indesejada mas preservar marcadores de segmento
    roteiro = re.sub(r'\*+', '', roteiro_bruto)
    roteiro = re.sub(r'^#+\s.*$', '', roteiro, flags=re.MULTILINE)
    roteiro = roteiro.replace('_', '').strip()

    palavras = len(roteiro.split())
    print(f"  ✅ Roteiro gerado: {palavras} palavras (~{palavras / PALAVRAS_POR_SEG / 60:.1f}min)")

    return roteiro


def segmentar_roteiro(roteiro):
    """Divide o roteiro nas seções marcadas e retorna lista de segmentos."""
    marcadores = ['[INTRO]', '[DESENVOLVIMENTO_1]', '[DESENVOLVIMENTO_2]',
                  '[DESENVOLVIMENTO_3]', '[REFLEXAO]', '[CONCLUSAO]']

    segmentos = []
    roteiro_sem_marcadores = roteiro

    for i, marcador in enumerate(marcadores):
        if marcador not in roteiro:
            continue

        inicio = roteiro.index(marcador) + len(marcador)

        # Encontrar onde começa o próximo marcador
        fim = len(roteiro)
        for proximo in marcadores[i + 1:]:
            if proximo in roteiro:
                fim = roteiro.index(proximo)
                break

        texto_segmento = roteiro[inicio:fim].strip()
        # Limpar texto do segmento
        texto_segmento = re.sub(r'\[.*?\]', '', texto_segmento).strip()

        if texto_segmento:
            segmentos.append({
                'tipo': marcador.strip('[]'),
                'texto': texto_segmento
            })

    # Fallback: se não encontrou marcadores, usar o roteiro inteiro como um segmento
    if not segmentos:
        print("  ⚠️ Marcadores não encontrados, usando roteiro como segmento único")
        texto_limpo = re.sub(r'\[.*?\]', '', roteiro).strip()
        segmentos.append({'tipo': 'COMPLETO', 'texto': texto_limpo})

    # Texto limpo completo (sem marcadores) para o áudio
    texto_completo = '\n\n'.join(s['texto'] for s in segmentos)

    print(f"  📋 {len(segmentos)} segmentos identificados")
    return segmentos, texto_completo


# ─────────────────────────────────────────────
# 3. GERAÇÃO DE ÁUDIO
# ─────────────────────────────────────────────

# Modelo Coqui VITS nativo em português — leve (~50MB) e sem necessidade de
# áudio de referência. O diretório de cache é configurável via variável de
# ambiente TTS_HOME para facilitar o cache no GitHub Actions.
COQUI_MODEL    = 'tts_models/pt/cv/vits'
COQUI_CACHE    = os.environ.get('TTS_HOME', os.path.expanduser('~/.local/share/tts'))

# Limite de caracteres por chamada — textos longos são divididos em chunks para
# evitar degradação de qualidade no final da síntese.
CHUNK_MAX_CHARS = 800


def _dividir_em_chunks(texto, max_chars=CHUNK_MAX_CHARS):
    """
    Divide o texto em chunks respeitando pontuação para não cortar palavras.
    Garante síntese mais natural em textos longos.
    """
    # Separar por sentenças (. ! ?)
    sentencas = re.split(r'(?<=[.!?])\s+', texto.strip())
    chunks = []
    atual = ''

    for sentenca in sentencas:
        if len(atual) + len(sentenca) + 1 <= max_chars:
            atual = (atual + ' ' + sentenca).strip()
        else:
            if atual:
                chunks.append(atual)
            # Sentença maior que o limite: dividir por vírgulas
            if len(sentenca) > max_chars:
                partes = sentenca.split(', ')
                sub = ''
                for parte in partes:
                    if len(sub) + len(parte) + 2 <= max_chars:
                        sub = (sub + ', ' + parte).strip(', ')
                    else:
                        if sub:
                            chunks.append(sub)
                        sub = parte
                if sub:
                    chunks.append(sub)
                atual = ''
            else:
                atual = sentenca

    if atual:
        chunks.append(atual)

    return chunks


def criar_audio(texto, output_file):
    """
    Cria narração em português via Coqui TTS (modelo VITS pt/cv).
    Divide o texto em chunks para preservar qualidade em textos longos.
    Fallback automático para gTTS se o Coqui falhar.
    """
    print("\n🎙️ Gerando narração com Coqui TTS...")
    print(f"  📦 Modelo: {COQUI_MODEL}")
    print(f"  📁 Cache : {COQUI_CACHE}")

    try:
        from TTS.api import TTS
        import soundfile as sf
        import numpy as np

        # Inicializar modelo (usa cache se já baixado)
        tts = TTS(model_name=COQUI_MODEL, progress_bar=False)
        sample_rate = tts.synthesizer.output_sample_rate

        chunks = _dividir_em_chunks(texto)
        print(f"  📝 {len(chunks)} chunks para síntese")

        audios = []
        silencio_curto  = np.zeros(int(sample_rate * 0.3), dtype=np.float32)  # 300ms entre chunks
        silencio_paragrafo = np.zeros(int(sample_rate * 0.6), dtype=np.float32)  # 600ms entre parágrafos

        for i, chunk in enumerate(chunks):
            print(f"  🔊 Chunk {i + 1}/{len(chunks)}: {len(chunk)} chars")
            wav = tts.tts(text=chunk)
            wav_array = np.array(wav, dtype=np.float32)
            audios.append(wav_array)

            # Pausa maior após ponto final, menor após vírgula/continuação
            if chunk.rstrip().endswith(('.', '!', '?')):
                audios.append(silencio_paragrafo)
            else:
                audios.append(silencio_curto)

        audio_final = np.concatenate(audios)

        # Salvar como WAV primeiro, depois converter para MP3 via ffmpeg
        wav_temp = output_file.replace('.mp3', '_temp.wav')
        sf.write(wav_temp, audio_final, sample_rate)

        # Converter WAV → MP3 (ffmpeg instalado pelo workflow)
        ret = os.system(f'ffmpeg -y -i "{wav_temp}" -codec:a libmp3lame -qscale:a 2 "{output_file}" -loglevel error')
        if ret != 0:
            # ffmpeg falhou — usar o WAV diretamente (moviepy aceita)
            import shutil
            shutil.copy(wav_temp, output_file.replace('.mp3', '.wav'))
            output_file = output_file.replace('.mp3', '.wav')
            print("  ⚠️ ffmpeg falhou, usando WAV diretamente")

        # Limpar temporário
        if os.path.exists(wav_temp):
            os.remove(wav_temp)

        tamanho_kb = os.path.getsize(output_file) / 1024
        print(f"  ✅ Áudio criado: {tamanho_kb:.0f} KB → {output_file}")
        return output_file

    except Exception as e:
        print(f"  ❌ Coqui TTS falhou: {e}")
        print("  ⚠️ Usando fallback: gTTS")
        try:
            from gtts import gTTS
            tts_fb = gTTS(text=texto, lang='pt-br', slow=False)
            tts_fb.save(output_file)
            tamanho_kb = os.path.getsize(output_file) / 1024
            print(f"  ✅ Fallback gTTS: {tamanho_kb:.0f} KB")
            return output_file
        except Exception as e2:
            print(f"  ❌ gTTS também falhou: {e2}")
            raise


# ─────────────────────────────────────────────
# 4. BUSCA DE VÍDEOS NO PEXELS
# ─────────────────────────────────────────────

def gerar_queries_pexels(tema, segmentos):
    """Usa o Gemini para gerar queries de busca no Pexels adequadas ao tema."""
    print("\n🔍 Gerando queries para Pexels...")

    tipos_segmento = [s['tipo'] for s in segmentos]

    prompt = f"""Para um vídeo filosófico no YouTube sobre o tema "{tema}", preciso de vídeos de paisagens e cenas contemplativas do Pexels.

Segmentos do vídeo: {', '.join(tipos_segmento)}

Gere {len(segmentos)} queries de busca em INGLÊS para o Pexels, uma por segmento, que combinem visualmente com o conteúdo.
Use termos como: nature, forest, ocean, mountain, sunrise, fog, rain, candle, stars, city night, person walking, meditation, etc.
Prefira queries que retornem vídeos de alta qualidade e contemplativas.

Retorne APENAS as queries separadas por vírgula, sem numeração, sem explicações.
Exemplo: misty forest morning, ocean waves sunset, mountain fog, person silhouette walking"""

    try:
        response = model.generate_content(prompt)
        queries_raw = response.text.strip()
        queries = [q.strip() for q in queries_raw.split(',')]
        queries = [q for q in queries if q][:len(segmentos)]

        # Garantir que temos queries suficientes
        queries_base = config.get('pexels_queries', {})
        todas_queries = []
        for categoria in queries_base.values():
            todas_queries.extend(categoria)

        while len(queries) < len(segmentos):
            queries.append(random.choice(todas_queries))

        print(f"  ✅ {len(queries)} queries geradas")
        return queries
    except Exception as e:
        print(f"  ⚠️ Erro ao gerar queries: {e}")
        queries_base = config.get('pexels_queries', {})
        todas = []
        for cat in queries_base.values():
            todas.extend(cat)
        random.shuffle(todas)
        return todas[:len(segmentos)]


def buscar_video_pexels(query, duracao_minima=5, tentativas_query=3):
    """Busca um vídeo no Pexels com a query fornecida."""
    if not PEXELS_API_KEY:
        print(f"  ❌ PEXELS_API_KEY não configurada")
        return None

    headers = {'Authorization': PEXELS_API_KEY}
    url = 'https://api.pexels.com/videos/search'

    params = {
        'query': query,
        'per_page': 15,
        'orientation': 'landscape',
        'size': 'medium'
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        data = response.json()

        videos = data.get('videos', [])
        if not videos:
            print(f"  ⚠️ Nenhum resultado para: '{query}'")
            return None

        # Filtrar por duração mínima e selecionar o melhor arquivo HD disponível
        candidatos = [v for v in videos if v.get('duration', 0) >= duracao_minima]
        if not candidatos:
            candidatos = videos  # relaxar filtro de duração

        random.shuffle(candidatos)

        for video in candidatos[:5]:
            arquivos = video.get('video_files', [])
            # Preferir HD (1920x1080) mas aceitar outros
            arquivos_hd = [a for a in arquivos if a.get('width', 0) >= 1280 and a.get('height', 0) >= 720]
            arquivo = arquivos_hd[0] if arquivos_hd else (arquivos[0] if arquivos else None)

            if arquivo and arquivo.get('link'):
                return {
                    'url': arquivo['link'],
                    'duracao': video['duration'],
                    'largura': arquivo.get('width', 1920),
                    'altura': arquivo.get('height', 1080),
                    'query': query,
                    'id': video['id']
                }

        return None

    except Exception as e:
        print(f"  ❌ Erro Pexels para '{query}': {e}")
        return None


def baixar_video(url, destino):
    """Faz download de um vídeo para o caminho destino."""
    try:
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()

        with open(destino, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        tamanho_mb = os.path.getsize(destino) / (1024 * 1024)
        print(f"    ⬇️ Baixado: {os.path.basename(destino)} ({tamanho_mb:.1f} MB)")
        return True
    except Exception as e:
        print(f"    ❌ Falha no download: {e}")
        return False


def obter_videos_para_segmentos(segmentos, tema):
    """Para cada segmento, busca e baixa um vídeo do Pexels."""
    print("\n🎬 Buscando vídeos no Pexels...")
    os.makedirs(ASSETS_DIR, exist_ok=True)

    queries = gerar_queries_pexels(tema, segmentos)
    ids_usados = set()  # evitar repetir o mesmo vídeo
    videos_segmentos = []

    for i, (segmento, query) in enumerate(zip(segmentos, queries)):
        print(f"\n  🔎 Segmento {i+1}/{len(segmentos)} [{segmento['tipo']}]: '{query}'")

        info_video = None
        queries_tentadas = [query]

        # Tentar a query principal e depois fallbacks
        queries_base = config.get('pexels_queries', {})
        fallbacks = []
        for cat in queries_base.values():
            fallbacks.extend(cat)
        random.shuffle(fallbacks)

        for q in [query] + fallbacks[:5]:
            resultado = buscar_video_pexels(q)
            if resultado and resultado['id'] not in ids_usados:
                info_video = resultado
                ids_usados.add(resultado['id'])
                break
            elif resultado and resultado['id'] in ids_usados:
                print(f"    ↩️ Vídeo já usado, tentando outra query...")

        if not info_video:
            print(f"  ⚠️ Nenhum vídeo encontrado para segmento {i+1}")
            videos_segmentos.append(None)
            continue

        # Download
        destino = os.path.join(ASSETS_DIR, f'video_seg_{i+1:02d}.mp4')
        sucesso = baixar_video(info_video['url'], destino)

        if sucesso:
            videos_segmentos.append({
                'path': destino,
                'duracao_original': info_video['duracao'],
                'query': info_video['query'],
                'segmento': segmento['tipo']
            })
        else:
            videos_segmentos.append(None)

        time.sleep(0.5)  # respeitar rate limit do Pexels

    baixados = sum(1 for v in videos_segmentos if v is not None)
    print(f"\n  ✅ {baixados}/{len(segmentos)} vídeos obtidos")
    return videos_segmentos


# ─────────────────────────────────────────────
# 5. MONTAGEM DO VÍDEO
# ─────────────────────────────────────────────

def preparar_clip_para_segmento(video_path, duracao_alvo):
    """
    Carrega, corta/loopa e redimensiona um clip de vídeo para a duração e
    resolução corretas (1920x1080).
    """
    try:
        clip = VideoFileClip(video_path)
        duracao_original = clip.duration

        # Se o vídeo for mais curto que o necessário, fazer loop
        if duracao_original < duracao_alvo:
            repeticoes = int(duracao_alvo / duracao_original) + 2
            clips_loop = [clip] * repeticoes
            clip = concatenate_videoclips(clips_loop)

        # Cortar para a duração exata necessária
        clip = clip.subclip(0, duracao_alvo)

        # Redimensionar para 1920x1080 mantendo proporção + crop central
        clip = clip.resize(height=1080)
        if clip.w < 1920:
            clip = clip.resize(width=1920)
        if clip.w > 1920 or clip.h > 1080:
            clip = clip.crop(x_center=clip.w / 2, y_center=clip.h / 2,
                             width=1920, height=1080)
        if clip.size != (1920, 1080):
            clip = clip.resize((1920, 1080))

        # Remover áudio original do vídeo (narração substitui)
        clip = clip.without_audio()

        return clip

    except Exception as e:
        print(f"  ❌ Erro ao preparar clip '{video_path}': {e}")
        return None


def criar_clip_fallback(duracao, cor=(10, 10, 20)):
    """Cria um clip preto/escuro como fallback quando não há vídeo disponível."""
    return ColorClip(size=(1920, 1080), color=cor, duration=duracao)


def montar_video(audio_path, videos_segmentos, segmentos, output_file):
    """Monta o vídeo final combinando todos os clips com o áudio da narração."""
    print("\n🎥 Montando vídeo final...")

    audio = AudioFileClip(audio_path)
    duracao_total = audio.duration
    print(f"  ⏱️ Duração total do áudio: {duracao_total:.1f}s ({duracao_total/60:.1f}min)")

    # Calcular duração de cada segmento proporcional ao número de palavras
    total_palavras = sum(len(s['texto'].split()) for s in segmentos)
    duracoes_segmentos = []

    for seg in segmentos:
        palavras_seg = len(seg['texto'].split())
        proporcao = palavras_seg / total_palavras
        duracao_seg = duracao_total * proporcao
        duracoes_segmentos.append(duracao_seg)
        print(f"  📐 [{seg['tipo']}]: {palavras_seg} palavras → {duracao_seg:.1f}s")

    # Preparar clips de vídeo
    clips_finais = []

    for i, (info_video, duracao_seg) in enumerate(zip(videos_segmentos, duracoes_segmentos)):
        tipo = segmentos[i]['tipo']
        print(f"\n  🎞️ Processando clip {i+1}/{len(segmentos)} [{tipo}]...")

        if info_video and os.path.exists(info_video['path']):
            clip = preparar_clip_para_segmento(info_video['path'], duracao_seg)
            if clip:
                clips_finais.append(clip)
                print(f"    ✅ Clip pronto: {duracao_seg:.1f}s")
            else:
                print(f"    ⚠️ Fallback (clip escuro)")
                clips_finais.append(criar_clip_fallback(duracao_seg))
        else:
            print(f"    ⚠️ Sem vídeo, usando fallback escuro")
            clips_finais.append(criar_clip_fallback(duracao_seg))

    # Ajuste fino: garantir que a soma dos clips bata com o áudio
    soma_clips = sum(c.duration for c in clips_finais)
    diferenca = duracao_total - soma_clips
    if abs(diferenca) > 0.1 and clips_finais:
        # Estender ou encurtar o último clip
        ultimo = clips_finais[-1]
        nova_duracao = max(0.5, ultimo.duration + diferenca)
        clips_finais[-1] = ultimo.subclip(0, min(nova_duracao, ultimo.duration)) if diferenca < 0 \
            else concatenate_videoclips([ultimo, criar_clip_fallback(diferenca)])

    print("\n  🔗 Concatenando clips...")
    video_final = concatenate_videoclips(clips_finais, method='compose')
    video_final = video_final.set_audio(audio)

    print("  💾 Renderizando arquivo final...")
    video_final.write_videofile(
        output_file,
        fps=24,
        codec='libx264',
        audio_codec='aac',
        preset='medium',
        bitrate='5000k',
        threads=4,
        logger=None
    )

    print("  🧹 Liberando memória...")
    video_final.close()
    audio.close()
    for c in clips_finais:
        c.close()

    tamanho_mb = os.path.getsize(output_file) / (1024 * 1024)
    print(f"\n  ✅ Vídeo final: {output_file} ({tamanho_mb:.1f} MB)")
    return output_file


# ─────────────────────────────────────────────
# 6. METADADOS E UPLOAD
# ─────────────────────────────────────────────

def gerar_metadados(tema, roteiro, segmentos):
    """Gera título, descrição e tags otimizados para YouTube."""
    print("\n📝 Gerando metadados para YouTube...")

    texto_resumo = ' '.join(s['texto'][:200] for s in segmentos[:2])

    prompt = f"""Crie metadados otimizados para YouTube para um vídeo filosófico sobre: "{tema}"

Trecho do roteiro:
{texto_resumo[:500]}

Retorne APENAS um JSON válido com esta estrutura exata:
{{
  "titulo": "título atraente com até 70 caracteres",
  "descricao": "descrição de 3 parágrafos, contemplativa e com palavras-chave",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"]
}}"""

    try:
        response = model.generate_content(prompt)
        texto = response.text.strip()
        texto = re.sub(r'```json\s*', '', texto)
        texto = re.sub(r'```\s*', '', texto)

        inicio = texto.find('{')
        fim = texto.rfind('}') + 1
        metadados = json.loads(texto[inicio:fim])

        # Garantir que o título não ultrapasse 100 chars (limite YouTube)
        titulo = metadados.get('titulo', tema)[:100]
        descricao = metadados.get('descricao', tema)
        tags = metadados.get('tags', [])

        # Mesclar com tags base do config
        tags_base = config.get('youtube', {}).get('tags_base', [])
        tags_finais = list(dict.fromkeys(tags + tags_base))[:30]

        print(f"  ✅ Título: {titulo}")
        return titulo, descricao, tags_finais

    except Exception as e:
        print(f"  ⚠️ Erro nos metadados, usando fallback: {e}")
        tags_base = config.get('youtube', {}).get('tags_base', [])
        return tema[:100], f"Uma reflexão sobre {tema}.", tags_base


def fazer_upload_youtube(video_path, titulo, descricao, tags):
    """Faz upload do vídeo para o YouTube."""
    print("\n📤 Fazendo upload para YouTube...")

    creds_dict = json.loads(YOUTUBE_CREDENTIALS)
    credentials = Credentials.from_authorized_user_info(creds_dict)
    youtube = build('youtube', 'v3', credentials=credentials)

    categoria_id = config.get('youtube', {}).get('categoria_id', '27')

    body = {
        'snippet': {
            'title': titulo,
            'description': descricao,
            'tags': tags,
            'categoryId': categoria_id
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False
        }
    }

    media = MediaFileUpload(video_path, resumable=True, chunksize=5 * 1024 * 1024)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            progresso = int(status.progress() * 100)
            print(f"  📊 Upload: {progresso}%")

    video_id = response['id']
    url = f'https://www.youtube.com/watch?v={video_id}'
    print(f"  ✅ Publicado: {url}")
    return video_id, url


def salvar_log(tema, titulo, duracao, video_id, url):
    """Salva registro do vídeo publicado."""
    log_file = 'videos_gerados.json'
    logs = []

    if os.path.exists(log_file):
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        except:
            pass

    logs.append({
        'data': datetime.now().isoformat(),
        'tema': tema,
        'titulo': titulo,
        'duracao_segundos': round(duracao, 1),
        'duracao_minutos': round(duracao / 60, 1),
        'video_id': video_id,
        'url': url
    })

    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)

    print(f"  📋 Log salvo ({len(logs)} vídeos no histórico)")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("🎬 GERADOR DE VÍDEOS FILOSÓFICOS")
    print("=" * 60)

    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(VIDEOS_DIR, exist_ok=True)

    # 1. Tema
    tema = escolher_tema()
    print(f"\n🎯 Tema escolhido: {tema}")

    # 2. Roteiro
    roteiro = gerar_roteiro(tema)
    segmentos, texto_narrado = segmentar_roteiro(roteiro)

    # 3. Áudio
    audio_path = os.path.join(ASSETS_DIR, 'naracao.mp3')
    criar_audio(texto_narrado, audio_path)

    audio_clip = AudioFileClip(audio_path)
    duracao_real = audio_clip.duration
    audio_clip.close()
    print(f"  ⏱️ Duração real: {duracao_real:.1f}s ({duracao_real/60:.1f}min)")

    # 4. Vídeos do Pexels
    videos_segmentos = obter_videos_para_segmentos(segmentos, tema)

    # 5. Montagem
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = os.path.join(VIDEOS_DIR, f'reflexao_{timestamp}.mp4')
    montar_video(audio_path, videos_segmentos, segmentos, output_path)

    # 6. Metadados e upload
    titulo, descricao, tags = gerar_metadados(tema, roteiro, segmentos)

    try:
        video_id, url = fazer_upload_youtube(output_path, titulo, descricao, tags)
        salvar_log(tema, titulo, duracao_real, video_id, url)
        print(f"\n{'=' * 60}")
        print(f"✅ CONCLUÍDO!")
        print(f"🔗 {url}")
        print(f"{'=' * 60}")
    except Exception as e:
        print(f"\n❌ Erro no upload: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
