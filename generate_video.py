import os
import json
import random
import re
import asyncio
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

# Importar sistema de curadoria
from telegram_curator import TelegramCurator

CONFIG_FILE = 'config.json'
VIDEOS_DIR = 'videos'
ASSETS_DIR = 'assets'
VIDEO_TYPE = os.environ.get('VIDEO_TYPE', 'short')

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')
YOUTUBE_CREDENTIALS = os.environ.get('YOUTUBE_CREDENTIALS')

# Configuração de curadoria
USAR_CURACAO = os.environ.get('USAR_CURACAO', 'true').lower() == 'true'
CURACAO_TIMEOUT = int(os.environ.get('CURACAO_TIMEOUT', '3600'))  # 1 hora

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash-exp')

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

# [... manter todas as funções existentes: buscar_noticias, gerar_titulo_especifico, 
# gerar_roteiro, extrair_keywords_do_texto, buscar_midia_pexels, buscar_imagens_bing, etc ...]

def criar_audio(texto, output_file):
    """Cria áudio usando Edge TTS com múltiplas vozes"""
    
    async def gerar():
        # Vozes brasileiras de alta qualidade
        vozes_disponiveis = [
            'pt-BR-FranciscaNeural',  # Feminina, jovem, energética
            'pt-BR-AntonioNeural',    # Masculina, profissional
            'pt-BR-BrendaNeural',     # Feminina, suave
            'pt-BR-ThalitaNeural',    # Feminina, clara
        ]
        
        # Selecionar voz baseada no tipo de conteúdo
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


def analisar_roteiro_e_buscar_midias_com_curacao(roteiro, duracao_audio, usar_bing=False):
    """Versão com curadoria humana via Telegram"""
    
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
            'texto': segmento[:100],  # Texto completo para contexto
            'texto_completo': segmento,
            'inicio': tempo_atual,
            'duracao': duracao_segmento,
            'keywords': keywords
        })
        
        tempo_atual += duracao_segmento
    
    # Buscar mídias iniciais
    midias_sincronizadas = []
    
    for i, seg in enumerate(segmentos_com_tempo):
        print(f"🔍 Seg {i+1}: '{seg['texto'][:50]}...' → {seg['keywords']}")
        
        if usar_bing:
            midia = buscar_imagens_bing(seg['keywords'], quantidade=1)
        else:
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
    
    # CURADORIA HUMANA
    if USAR_CURACAO:
        print("\n" + "="*60)
        print("🎬 MODO CURADORIA ATIVADO")
        print("="*60)
        
        curator = TelegramCurator()
        
        # Enviar para curadoria
        curator.solicitar_curacao(midias_sincronizadas)
        
        # Aguardar aprovação
        midias_aprovadas = curator.aguardar_aprovacao(timeout=CURACAO_TIMEOUT)
        
        if midias_aprovadas:
            print("✅ Mídias aprovadas pelo curador!")
            midias_sincronizadas = midias_aprovadas
        else:
            print("⏰ Timeout ou cancelamento - usando mídias originais")
    
    return midias_sincronizadas


def main():
    print(f"{'📱' if VIDEO_TYPE == 'short' else '🎬'} Iniciando...")
    
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    
    # Buscar notícia ou tema
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
    
    # Buscar mídias COM CURADORIA
    usar_bing = config.get('tipo') == 'noticias' and config.get('fonte_midias') == 'bing'
    
    if usar_bing:
        print("🌐 Modo: BING (notícias)")
    else:
        print("📸 Modo: PEXELS")
    
    if config.get('palavras_chave_fixas'):
        keywords_busca = config.get('palavras_chave_fixas')
        print(f"🎯 Keywords fixas: {', '.join(keywords_busca)}")
    else:
        keywords_busca = keywords
    
    # USAR FUNÇÃO COM CURADORIA
    midias_sincronizadas = analisar_roteiro_e_buscar_midias_com_curacao(
        roteiro, 
        duracao, 
        usar_bing
    )
    
    # Complementar se necessário
    if len(midias_sincronizadas) < 3:
        print("⚠️ Poucas mídias, complementando...")
        extras = buscar_midia_pexels(['nature landscape'], tipo='foto', quantidade=5)
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
    print("🎥 Montando vídeo sincronizado...")
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    video_path = f'{VIDEOS_DIR}/{VIDEO_TYPE}_{timestamp}.mp4'
    
    if VIDEO_TYPE == 'short':
        resultado = criar_video_short_sincronizado(audio_path, midias_sincronizadas, video_path, duracao)
    else:
        resultado = criar_video_long_sincronizado(audio_path, midias_sincronizadas, video_path, duracao)
    
    if not resultado:
        print("❌ Erro na criação do vídeo")
        return
    
    # Preparar informações para upload
    titulo = titulo_video[:60] if len(titulo_video) <= 60 else titulo_video[:57] + '...'
    
    if VIDEO_TYPE == 'short':
        titulo += ' #shorts'
    
    descricao = roteiro[:300] + '...\n\n🔔 Inscreva-se!\n#' + ('shorts' if VIDEO_TYPE == 'short' else 'curiosidades')
    
    tags = ['curiosidades', 'fatos'] if not noticia else ['noticias', 'informacao']
    
    if VIDEO_TYPE == 'short':
        tags.append('shorts')
    
    # Upload no YouTube
    print("📤 Fazendo upload...")
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
        'url': url,
        'curadoria_usada': USAR_CURACAO
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
    
    # Notificar no Telegram
    if USAR_CURACAO:
        curator = TelegramCurator()
        curator.notificar_publicacao({
            'titulo': titulo,
            'duracao': duracao,
            'url': url
        })
    
    # Limpar arquivos temporários
    for file in os.listdir(ASSETS_DIR):
        try:
            os.remove(os.path.join(ASSETS_DIR, file))
        except:
            pass

if __name__ == '__main__':
    main()
