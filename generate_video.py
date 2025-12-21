import os
import json
import random
import re
import asyncio
import shutil
from datetime import datetime
import requests
import feedparser
import edge_tts
from moviepy.editor import *
from google import generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image

# Importar sistema de curadoria se existir
try:
    from telegram_curator import TelegramCurator
    CURACAO_DISPONIVEL = True
except ImportError:
    print("⚠️ telegram_curator.py não encontrado - modo curadoria desativado")
    CURACAO_DISPONIVEL = False

CONFIG_FILE = 'config.json'
VIDEOS_DIR = 'videos'
ASSETS_DIR = 'assets'
VIDEO_TYPE = os.environ.get('VIDEO_TYPE', 'short')

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')
YOUTUBE_CREDENTIALS = os.environ.get('YOUTUBE_CREDENTIALS')

# Configuração de curadoria
USAR_CURACAO = os.environ.get('USAR_CURACAO', 'false').lower() == 'true' and CURACAO_DISPONIVEL
CURACAO_TIMEOUT = int(os.environ.get('CURACAO_TIMEOUT', '3600'))

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

def buscar_noticias():
    """Busca notícias em feeds RSS"""
    if config.get('tipo') != 'noticias':
        return None
    
    feeds = config.get('rss_feeds', [])
    todas_noticias = []
    
    for feed_url in feeds[:3]:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:3]:
                todas_noticias.append({
                    'titulo': entry.title,
                    'resumo': entry.get('summary', entry.title),
                    'link': entry.link
                })
        except:
            continue
    
    return random.choice(todas_noticias) if todas_noticias else None

def gerar_titulo_especifico(tema):
    """Gera título específico e keywords baseado no tema"""
    prompt = f"""Baseado no tema "{tema}", crie um título ESPECÍFICO e palavras-chave.

Retorne APENAS JSON: {{"titulo": "título aqui", "keywords": ["palavra1", "palavra2", "palavra3", "palavra4", "palavra5"]}}"""
    
    response = model.generate_content(prompt)
    texto = response.text.strip().replace('```json', '').replace('```', '').strip()
    
    inicio = texto.find('{')
    fim = texto.rfind('}') + 1
    
    if inicio == -1 or fim == 0:
        return {"titulo": tema, "keywords": ["technology", "innovation", "future", "modern", "digital"]}
    
    try:
        return json.loads(texto[inicio:fim])
    except:
        return {"titulo": tema, "keywords": ["technology", "innovation", "future", "modern", "digital"]}

def gerar_roteiro(duracao_alvo, titulo, noticia=None):
    """Gera roteiro baseado na duração e tema"""
    if duracao_alvo == 'short':
        palavras_alvo = 120
        tempo = '30-60 segundos'
    else:
        palavras_alvo = config.get('duracao_minutos', 10) * 150
        tempo = f"{config.get('duracao_minutos', 10)} minutos"
    
    if noticia:
        prompt = f"""Script sobre: {titulo}
Resumo: {noticia['resumo']}
{tempo}, {palavras_alvo} palavras, noticioso, texto puro."""
    else:
        if duracao_alvo == 'short':
            prompt = f"""Crie um script para SHORT sobre: {titulo}

REGRAS IMPORTANTES:
- {palavras_alvo} palavras aproximadamente
- Comece SEMPRE com "Você sabia que..." ou variações como "Sabia que...", "Já parou pra pensar que..."
- Tom casual e envolvente
- NÃO mencione apresentador, slides, ou elementos visuais
- NÃO use frases como "vamos ver", "próximo slide", "na tela"
- Fale diretamente com o espectador
- Texto corrido para narração
- SEM formatação, asteriscos ou marcadores
- SEM emojis

Escreva APENAS o roteiro de narração."""
        else:
            prompt = f"""Crie um script sobre: {titulo}

REGRAS IMPORTANTES:
- {tempo} de duração, aproximadamente {palavras_alvo} palavras
- Comece com "Olá!" ou "E aí, tudo bem?"
- Tom amigável e conversacional
- NÃO mencione apresentador, slides, gráficos ou elementos visuais
- NÃO use frases como "vamos ver agora", "na próxima parte", "como vocês podem ver"
- Fale naturalmente como se estivesse contando uma história interessante
- Divida o conteúdo em pequenos parágrafos naturais
- Texto corrido para narração
- SEM formatação, asteriscos ou marcadores
- SEM emojis
- Finalize com chamada para inscrição no canal

Escreva APENAS o roteiro de narração."""
    
    response = model.generate_content(prompt)
    texto = response.text
    
    # Limpeza do texto
    texto = re.sub(r'\*+', '', texto)
    texto = re.sub(r'#+\s', '', texto)
    texto = re.sub(r'^-\s', '', texto, flags=re.MULTILINE)
    texto = texto.replace('*', '').replace('#', '').replace('_', '').strip()
    
    return texto

def criar_audio(texto, output_file):
    """Cria áudio usando Edge TTS com múltiplas vozes"""
    
    async def gerar():
        vozes_disponiveis = [
            'pt-BR-FranciscaNeural',
            'pt-BR-AntonioNeural',
            'pt-BR-BrendaNeural',
            'pt-BR-ThalitaNeural',
        ]
        
        tipo_canal = config.get('tipo', 'motivacional')
        
        if tipo_canal == 'noticias':
            voz = 'pt-BR-FranciscaNeural'
        elif tipo_canal == 'motivacional':
            voz = 'pt-BR-AntonioNeural'
        else:
            voz = random.choice(vozes_disponiveis)
        
        voz = config.get('voz_fallback', voz)
        
        print(f"🎤 Usando voz: {voz}")
        
        communicate = edge_tts.Communicate(texto, voz)
        await communicate.save(output_file)
        
        print("✅ Áudio gerado com Edge TTS!")
        return output_file
    
    return asyncio.run(gerar())

def extrair_keywords_do_texto(texto):
    """Extrai keywords do texto para buscar mídias"""
    prompt = f"""Extraia 3-5 palavras-chave em INGLÊS para buscar imagens/vídeos:
"{texto[:200]}"

Retorne APENAS palavras separadas por vírgula."""
    
    try:
        response = model.generate_content(prompt)
        keywords = [k.strip() for k in response.text.strip().split(',')]
        return keywords[:5]
    except:
        palavras = texto.lower().split()
        return [p for p in palavras if len(p) > 4][:3]

def buscar_midia_pexels(keywords, tipo='video', quantidade=1):
    """Busca mídias no Pexels"""
    headers = {'Authorization': PEXELS_API_KEY}
    
    if isinstance(keywords, str):
        keywords = [keywords]
    
    palavra_busca = ' '.join(keywords[:3])
    pagina = random.randint(1, 3)
    
    midias = []
    
    if tipo == 'video':
        orientacao = 'portrait' if VIDEO_TYPE == 'short' else 'landscape'
        url = f'https://api.pexels.com/videos/search?query={palavra_busca}&per_page=30&page={pagina}&orientation={orientacao}'
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                videos = response.json().get('videos', [])
                random.shuffle(videos)
                
                for video in videos:
                    for file in video['video_files']:
                        if VIDEO_TYPE == 'short':
                            if file.get('height', 0) > file.get('width', 0):
                                midias.append((file['link'], 'video'))
                                break
                        else:
                            if file.get('width', 0) >= 1280:
                                midias.append((file['link'], 'video'))
                                break
                    
                    if len(midias) >= quantidade:
                        break
        except Exception as e:
            print(f"⚠️ Pexels vídeos: {e}")
    
    # Se não encontrou vídeos suficientes, buscar fotos
    if len(midias) < quantidade:
        orientacao = 'portrait' if VIDEO_TYPE == 'short' else 'landscape'
        url = f'https://api.pexels.com/v1/search?query={palavra_busca}&per_page=50&page={pagina}&orientation={orientacao}'
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                fotos = response.json().get('photos', [])
                random.shuffle(fotos)
                
                for foto in fotos[:quantidade * 2]:
                    midias.append((foto['src']['large2x'], 'foto'))
        except Exception as e:
            print(f"⚠️ Pexels fotos: {e}")
    
    random.shuffle(midias)
    return midias[:quantidade]

def baixar_midia(url, filename):
    """Baixa mídia de uma URL"""
    try:
        response = requests.get(url, stream=True, timeout=30)
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return filename
    except:
        return None

def analisar_roteiro_e_buscar_midias(roteiro, duracao_audio, usar_bing=False):
    """Analisa roteiro e busca mídias sincronizadas"""
    print("📋 Analisando roteiro para sincronização...")
    
    # Dividir em segmentos
    segmentos = re.split(r'[.!?]\s+', roteiro)
    segmentos = [s.strip() for s in segmentos if len(s.strip()) > 20]
    
    print(f"  {len(segmentos)} segmentos encontrados")
    
    palavras_total = len(roteiro.split())
    palavras_por_segundo = palavras_total / duracao_audio
    
    segmentos_com_tempo = []
    tempo_atual = 0
    
    for segmento in segmentos:
        palavras_segmento = len(segmento.split())
        duracao_segmento = palavras_segmento / palavras_por_segundo
        
        keywords = extrair_keywords_do_texto(segmento)
        
        segmentos_com_tempo.append({
            'texto': segmento[:100],
            'texto_completo': segmento,
            'inicio': tempo_atual,
            'duracao': duracao_segmento,
            'keywords': keywords
        })
        
        tempo_atual += duracao_segmento
    
    # Buscar mídias
    midias_sincronizadas = []
    
    for i, seg in enumerate(segmentos_com_tempo):
        print(f"🔍 Seg {i+1}: '{seg['texto'][:50]}...' → {seg['keywords']}")
        
        midia = buscar_midia_pexels(seg['keywords'], tipo='video', quantidade=1)
        
        if midia and len(midia) > 0:
            midias_sincronizadas.append({
                'midia': midia[0],
                'inicio': seg['inicio'],
                'duracao': seg['duracao'],
                'texto': seg['texto'],
                'keywords': seg['keywords']
            })
        else:
            print(f"  ⚠️ Sem mídia para seg {i+1}")
    
    print(f"✅ {len(midias_sincronizadas)} mídias encontradas")
    
    # CURADORIA (se ativado)
    if USAR_CURACAO:
        print("\n" + "="*60)
        print("🎬 MODO CURADORIA ATIVADO")
        print("="*60)
        
        try:
            curator = TelegramCurator()
            curator.solicitar_curacao(midias_sincronizadas)
            midias_aprovadas = curator.aguardar_aprovacao(timeout=CURACAO_TIMEOUT)
            
            if midias_aprovadas:
                print("✅ Mídias aprovadas!")
                midias_sincronizadas = midias_aprovadas
            else:
                print("⏰ Timeout - usando mídias originais")
        except Exception as e:
            print(f"⚠️ Erro na curadoria: {e}")
    
    return midias_sincronizadas

def criar_video_short_sincronizado(audio_path, midias_sincronizadas, output_file, duracao_total):
    """Cria vídeo short com mídias sincronizadas"""
    print(f"📹 Criando short com {len(midias_sincronizadas)} mídias")
    
    clips = []
    tempo_coberto = 0
    
    for i, item in enumerate(midias_sincronizadas):
        midia_info, midia_tipo = item['midia']
        inicio = item['inicio']
        duracao_clip = item['duracao']
        
        try:
            if midia_tipo == 'video':
                video_temp = f'{ASSETS_DIR}/v_{i}.mp4'
                if baixar_midia(midia_info, video_temp):
                    vclip = VideoFileClip(video_temp, audio=False)
                    
                    ratio = 9/16
                    if vclip.w / vclip.h > ratio:
                        new_w = int(vclip.h * ratio)
                        vclip = vclip.crop(x_center=vclip.w/2, width=new_w, height=vclip.h)
                    else:
                        new_h = int(vclip.w / ratio)
                        vclip = vclip.crop(y_center=vclip.h/2, width=vclip.w, height=new_h)
                    
                    vclip = vclip.resize((1080, 1920))
                    vclip = vclip.set_duration(min(duracao_clip, vclip.duration))
                    vclip = vclip.set_start(inicio)
                    clips.append(vclip)
                    tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
            
            else:  # foto
                foto_temp = f'{ASSETS_DIR}/f_{i}.jpg'
                if baixar_midia(midia_info, foto_temp):
                    clip = ImageClip(foto_temp).set_duration(duracao_clip)
                    clip = clip.resize(height=1920)
                    if clip.w > 1080:
                        clip = clip.crop(x_center=clip.w/2, width=1080, height=1920)
                    clip = clip.resize(lambda t: 1 + 0.1 * (t / duracao_clip))
                    clip = clip.set_start(inicio)
                    clips.append(clip)
                    tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
        
        except Exception as e:
            print(f"⚠️ Erro mídia {i}: {e}")
    
    # Preencher lacunas
    if tempo_coberto < duracao_total:
        print(f"⚠️ Preenchendo {duracao_total - tempo_coberto:.1f}s")
        extras = buscar_midia_pexels(['nature', 'landscape'], tipo='foto', quantidade=3)
        duracao_restante = duracao_total - tempo_coberto
        duracao_por_extra = duracao_restante / len(extras) if extras else duracao_restante
        
        for idx, (midia_info, midia_tipo) in enumerate(extras):
            try:
                foto_temp = f'{ASSETS_DIR}/extra_{idx}.jpg'
                if baixar_midia(midia_info, foto_temp):
                    clip = ImageClip(foto_temp).set_duration(duracao_por_extra)
                    clip = clip.resize(height=1920)
                    if clip.w > 1080:
                        clip = clip.crop(x_center=clip.w/2, width=1080, height=1920)
                    clip = clip.set_start(tempo_coberto)
                    clips.append(clip)
                    tempo_coberto += duracao_por_extra
            except:
                continue
    
    if not clips:
        return None
    
    video = CompositeVideoClip(clips, size=(1080, 1920))
    video = video.set_duration(duracao_total)
    
    audio = AudioFileClip(audio_path)
    video = video.set_audio(audio)
    
    video.write_videofile(output_file, fps=30, codec='libx264', audio_codec='aac', preset='medium', bitrate='8000k')
    
    return output_file

def criar_video_long_sincronizado(audio_path, midias_sincronizadas, output_file, duracao_total):
    """Cria vídeo longo com mídias sincronizadas"""
    print(f"📹 Criando long com {len(midias_sincronizadas)} mídias")
    
    clips = []
    tempo_coberto = 0
    
    for i, item in enumerate(midias_sincronizadas):
        midia_info, midia_tipo = item['midia']
        inicio = item['inicio']
        duracao_clip = item['duracao']
        
        try:
            if midia_tipo == 'video':
                video_temp = f'{ASSETS_DIR}/v_{i}.mp4'
                if baixar_midia(midia_info, video_temp):
                    vclip = VideoFileClip(video_temp, audio=False)
                    vclip = vclip.resize(height=1080)
                    if vclip.w < 1920:
                        vclip = vclip.resize(width=1920)
                    vclip = vclip.crop(x_center=vclip.w/2, y_center=vclip.h/2, width=1920, height=1080)
                    vclip = vclip.set_duration(min(duracao_clip, vclip.duration))
                    vclip = vclip.set_start(inicio)
                    clips.append(vclip)
                    tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
            
            else:  # foto
                foto_temp = f'{ASSETS_DIR}/f_{i}.jpg'
                if baixar_midia(midia_info, foto_temp):
                    clip = ImageClip(foto_temp).set_duration(duracao_clip)
                    clip = clip.resize(height=1080)
                    if clip.w < 1920:
                        clip = clip.resize(width=1920)
                    clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=1920, height=1080)
                    clip = clip.resize(lambda t: 1 + 0.05 * (t / duracao_clip))
                    clip = clip.set_start(inicio)
                    clips.append(clip)
                    tempo_coberto = max(tempo_coberto, inicio + duracao_clip)
        
        except Exception as e:
            print(f"⚠️ Erro mídia {i}: {e}")
    
    # Preencher lacunas
    if tempo_coberto < duracao_total:
        print(f"⚠️ Preenchendo {duracao_total - tempo_coberto:.1f}s")
        extras = buscar_midia_pexels(['nature', 'landscape'], tipo='foto', quantidade=3)
        duracao_restante = duracao_total - tempo_coberto
        duracao_por_extra = duracao_restante / len(extras) if extras else duracao_restante
        
        for idx, (midia_info, midia_tipo) in enumerate(extras):
            try:
                foto_temp = f'{ASSETS_DIR}/extra_{idx}.jpg'
                if baixar_midia(midia_info, foto_temp):
                    clip = ImageClip(foto_temp).set_duration(duracao_por_extra)
                    clip = clip.resize(height=1080)
                    if clip.w < 1920:
                        clip = clip.resize(width=1920)
                    clip = clip.crop(x_center=clip.w/2, y_center=clip.h/2, width=1920, height=1080)
                    clip = clip.set_start(tempo_coberto)
                    clips.append(clip)
                    tempo_coberto += duracao_por_extra
            except:
                continue
    
    if not clips:
        return None
    
    video = CompositeVideoClip(clips, size=(1920, 1080))
    video = video.set_duration(duracao_total)
    
    audio = AudioFileClip(audio_path)
    video = video.set_audio(audio)
    
    video.write_videofile(output_file, fps=24, codec='libx264', audio_codec='aac', preset='medium', bitrate='5000k')
    
    return output_file

def fazer_upload_youtube(video_path, titulo, descricao, tags):
    """Faz upload do vídeo no YouTube"""
    try:
        creds_dict = json.loads(YOUTUBE_CREDENTIALS)
        credentials = Credentials.from_authorized_user_info(creds_dict)
        youtube = build('youtube', 'v3', credentials=credentials)
        
        body = {
            'snippet': {'title': titulo, 'description': descricao, 'tags': tags, 'categoryId': '27'},
            'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}
        }
        
        media = MediaFileUpload(video_path, resumable=True)
        request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
        response = request.execute()
        
        return response['id']
    except Exception as e:
        print(f"❌ Erro no upload: {e}")
        raise

def main():
    """Função principal"""
    print(f"{'📱' if VIDEO_TYPE == 'short' else '🎬'} Iniciando...")
    
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    
    # Buscar tema
    noticia = buscar_noticias()
    
    if noticia:
        titulo_video = noticia['titulo']
        keywords = titulo_video.split()[:5]
        print(f"📰 Notícia: {titulo_video}")
    else:
        tema = random.choice(config['temas'])
        print(f"📝 Tema: {tema}")
        
        info = gerar_titulo_especifico(tema)
        titulo_video = info['titulo']
        keywords = info['keywords']
        
        print(f"🎯 Título: {titulo_video}")
        print(f"🔍 Keywords: {', '.join(keywords)}")
    
    # Gerar roteiro
    print("✍️ Gerando roteiro...")
    roteiro = gerar_roteiro(VIDEO_TYPE, titulo_video, noticia)
    
    # Criar áudio
    audio_path = f'{ASSETS_DIR}/audio.mp3'
    criar_audio(roteiro, audio_path)
    
    audio_clip = AudioFileClip(audio_path)
    duracao = audio_clip.duration
    audio_clip.close()
    
    print(f"⏱️ {duracao:.1f}s")
    
    # Buscar mídias
    midias_sincronizadas = analisar_roteiro_e_buscar_midias(roteiro, duracao)
    
    # Complementar se necessário
    if len(midias_sincronizadas) < 3:
        print("⚠️ Complementando mídias...")
        extras = buscar_midia_pexels(['nature', 'landscape'], tipo='foto', quantidade=5)
        tempo_restante = duracao - sum([m['duracao'] for m in midias_sincronizadas])
        duracao_extra = tempo_restante / len(extras) if extras else 0
        
        for extra in extras:
            midias_sincronizadas.append({
                'midia': extra,
                'inicio': duracao - tempo_restante,
                'duracao': duracao_extra
            })
            tempo_restante -= duracao_extra
    
    # Montar vídeo
    print("🎥 Montando vídeo...")
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    video_path = f'{VIDEOS_DIR}/{VIDEO_TYPE}_{timestamp}.mp4'
    
    if VIDEO_TYPE == 'short':
        resultado = criar_video_short_sincronizado(audio_path, midias_sincronizadas, video_path, duracao)
    else:
        resultado = criar_video_long_sincronizado(audio_path, midias_sincronizadas, video_path, duracao)
    
    if not resultado:
        print("❌ Erro na criação")
        return
    
    # Upload
    titulo = titulo_video[:60] if len(titulo_video) <= 60 else titulo_video[:57] + '...'
    if VIDEO_TYPE == 'short':
        titulo += ' #shorts'
    
    descricao = roteiro[:300] + '...\n\n🔔 Inscreva-se!\n#' + ('shorts' if VIDEO_TYPE == 'short' else 'curiosidades')
    tags = ['curiosidades', 'fatos'] if not noticia else ['noticias', 'informacao']
    if VIDEO_TYPE == 'short':
        tags.append('shorts')
    
    print("📤 Upload...")
    video_id = fazer_upload_youtube(video_path, titulo, descricao, tags)
    
    url = f'https://youtube.com/{"shorts" if VIDEO_TYPE == "short" else "watch?v="}{video_id}'
    
    # Log
    log_entry = {
        'data': datetime.now().isoformat(),
        'tipo': VIDEO_TYPE,
        'tema': titulo_video,
        'titulo': titulo,
        'duracao': duracao,
        'video_id': video_id,
        'url': url
    }
    
    log_file = 'videos_gerados.json'
    logs = []
    
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            logs = json.load(f)
    
    logs.append(log_entry)
    
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Publicado!\n🔗 {url}")
    
    # Notificar Telegram
    if USAR_CURACAO:
        try:
            curator = TelegramCurator()
            curator.notificar_publicacao({
                'titulo': titulo,
                'duracao': duracao,
                'url': url
            })
        except:
            pass
    
    # Limpar
    for file in os.listdir(ASSETS_DIR):
        try:
            os.remove(os.path.join(ASSETS_DIR, file))
        except:
            pass

if __name__ == '__main__':
    main()
