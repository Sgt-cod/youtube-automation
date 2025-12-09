import os
import json
import random
from datetime import datetime
import requests
from gtts import gTTS
from moviepy.editor import *
from google import generativeai as genai
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ========== CONFIGURAÇÕES ==========
CONFIG_FILE = 'config.json'
VIDEOS_DIR = 'videos'
ASSETS_DIR = 'assets'

# Carregar configurações
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

# APIs
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')
YOUTUBE_CREDENTIALS = os.environ.get('YOUTUBE_CREDENTIALS')

# Configurar Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# ========== FUNÇÕES ==========

def gerar_roteiro(tema, duracao_minutos):
    """Gera roteiro de vídeo usando Gemini"""
    prompt = f"""
    Crie um roteiro completo para um vídeo de YouTube sobre: {tema}
    
    Requisitos:
    - Duração: {duracao_minutos} minutos (aproximadamente {duracao_minutos * 150} palavras)
    - Tom: envolvente, informativo e curioso
    - Estrutura: Introdução impactante, 10-15 fatos curiosos numerados, conclusão memorável
    - Linguagem: português brasileiro, natural para narração
    - Inclua transições suaves entre os fatos
    
    Formato: escreva apenas o texto para narração, sem indicações técnicas.
    """
    
    response = model.generate_content(prompt)
    return response.text

def gerar_titulo_descricao(roteiro):
    """Gera título e descrição otimizados para o vídeo"""
    prompt = f"""
    Com base neste roteiro de vídeo, crie:
    
    1. Um título chamativo (máximo 60 caracteres) otimizado para SEO
    2. Uma descrição completa (3-4 parágrafos) incluindo:
       - Resumo do conteúdo
       - Principais curiosidades abordadas
       - Call-to-action (inscrever-se, comentar)
       - Hashtags relevantes
    
    Roteiro: {roteiro[:500]}...
    
    Retorne no formato JSON:
    {{
        "titulo": "...",
        "descricao": "...",
        "tags": ["tag1", "tag2", ...]
    }}
    """
    
    response = model.generate_content(prompt)
    # Extrair JSON da resposta
    texto = response.text
    inicio = texto.find('{')
    fim = texto.rfind('}') + 1
    return json.loads(texto[inicio:fim])

def criar_audio(texto, output_file):
    """Converte texto em áudio usando Google TTS"""
    tts = gTTS(text=texto, lang='pt-br', slow=False)
    tts.save(output_file)
    return output_file

def buscar_imagens_pexels(palavras_chave, quantidade=15):
    """Busca imagens no Pexels"""
    headers = {'Authorization': PEXELS_API_KEY}
    imagens = []
    
    for palavra in palavras_chave:
        url = f'https://api.pexels.com/v1/search?query={palavra}&per_page={quantidade//len(palavras_chave)}'
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            for photo in data['photos']:
                imagens.append(photo['src']['large'])
    
    return imagens

def baixar_imagem(url, filename):
    """Baixa uma imagem"""
    response = requests.get(url)
    with open(filename, 'wb') as f:
        f.write(response.content)
    return filename

def criar_video(audio_path, imagens, output_file, duracao_audio):
    """Cria vídeo com imagens e áudio"""
    clips = []
    duracao_por_imagem = duracao_audio / len(imagens)
    
    for i, img_url in enumerate(imagens):
        img_path = f'{ASSETS_DIR}/img_{i}.jpg'
        baixar_imagem(img_url, img_path)
        
        # Criar clip da imagem com zoom suave
        img_clip = (ImageClip(img_path)
                   .set_duration(duracao_por_imagem)
                   .resize(height=1080)
                   .set_position('center'))
        
        # Efeito de zoom
        img_clip = img_clip.resize(lambda t: 1 + 0.02*t)
        clips.append(img_clip)
    
    # Concatenar clips
    video = concatenate_videoclips(clips, method="compose")
    
    # Adicionar áudio
    audio = AudioFileClip(audio_path)
    video = video.set_audio(audio)
    
    # Renderizar
    video.write_videofile(
        output_file,
        fps=24,
        codec='libx264',
        audio_codec='aac',
        threads=4,
        preset='medium'
    )
    
    return output_file

def fazer_upload_youtube(video_path, titulo, descricao, tags):
    """Faz upload do vídeo no YouTube"""
    # Carregar credenciais
    creds_dict = json.loads(YOUTUBE_CREDENTIALS)
    credentials = Credentials.from_authorized_user_info(creds_dict)
    
    youtube = build('youtube', 'v3', credentials=credentials)
    
    body = {
        'snippet': {
            'title': titulo,
            'description': descricao,
            'tags': tags,
            'categoryId': '27'  # Educação
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False
        }
    }
    
    media = MediaFileUpload(video_path, resumable=True)
    
    request = youtube.videos().insert(
        part='snippet,status',
        body=body,
        media_body=media
    )
    
    response = request.execute()
    return response['id']

def salvar_log(info):
    """Salva log do vídeo gerado"""
    log_file = 'videos_gerados.json'
    
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            logs = json.load(f)
    else:
        logs = []
    
    logs.append(info)
    
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)

# ========== EXECUÇÃO PRINCIPAL ==========

def main():
    print("🎬 Iniciando geração de vídeo...")
    
    # Criar diretórios
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    
    # Escolher tema aleatório
    tema = random.choice(config['temas'])
    print(f"📝 Tema escolhido: {tema}")
    
    # Gerar roteiro
    print("✍️ Gerando roteiro...")
    duracao = random.randint(config['duracao_min'], config['duracao_max'])
    roteiro = gerar_roteiro(tema, duracao)
    
    # Gerar título e descrição
    print("🏷️ Gerando metadados...")
    metadados = gerar_titulo_descricao(roteiro)
    
    # Criar áudio
    print("🎙️ Criando narração...")
    audio_path = f'{ASSETS_DIR}/naracao.mp3'
    criar_audio(roteiro, audio_path)
    
    # Obter duração do áudio
    audio_clip = AudioFileClip(audio_path)
    duracao_audio = audio_clip.duration
    audio_clip.close()
    
    # Buscar imagens
    print("🖼️ Buscando imagens...")
    palavras_chave = config.get('palavras_chave_imagens', [tema])
    imagens = buscar_imagens_pexels(palavras_chave, quantidade=15)
    
    # Criar vídeo
    print("🎥 Montando vídeo...")
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    video_path = f'{VIDEOS_DIR}/video_{timestamp}.mp4'
    criar_video(audio_path, imagens, video_path, duracao_audio)
    
    # Upload no YouTube
    print("📤 Fazendo upload no YouTube...")
    video_id = fazer_upload_youtube(
        video_path,
        metadados['titulo'],
        metadados['descricao'],
        metadados['tags']
    )
    
    # Salvar log
    info = {
        'data': datetime.now().isoformat(),
        'tema': tema,
        'titulo': metadados['titulo'],
        'duracao': duracao_audio,
        'video_id': video_id,
        'url': f'https://youtube.com/watch?v={video_id}'
    }
    salvar_log(info)
    
    print(f"✅ Vídeo publicado com sucesso!")
    print(f"🔗 URL: {info['url']}")
    
    # Limpar arquivos temporários
    for file in os.listdir(ASSETS_DIR):
        os.remove(os.path.join(ASSETS_DIR, file))

if __name__ == '__main__':
    main()
