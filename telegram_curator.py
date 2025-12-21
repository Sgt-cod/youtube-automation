import os
import json
import requests
import time
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
CURACAO_FILE = 'curacao_pendente.json'

class TelegramCurator:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        
    def enviar_mensagem(self, texto):
        """Envia mensagem de texto"""
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': self.chat_id,
            'text': texto,
            'parse_mode': 'HTML'
        }
        try:
            response = requests.post(url, data=data, timeout=10)
            return response.json()
        except Exception as e:
            print(f"❌ Erro ao enviar mensagem: {e}")
            return None
    
    def enviar_foto(self, foto_url, caption):
        """Envia foto com legenda"""
        url = f"{self.base_url}/sendPhoto"
        data = {
            'chat_id': self.chat_id,
            'photo': foto_url,
            'caption': caption,
            'parse_mode': 'HTML'
        }
        try:
            response = requests.post(url, data=data, timeout=15)
            return response.json()
        except Exception as e:
            print(f"❌ Erro ao enviar foto: {e}")
            return None
    
    def enviar_video(self, video_url, caption):
        """Envia vídeo com legenda"""
        url = f"{self.base_url}/sendVideo"
        data = {
            'chat_id': self.chat_id,
            'video': video_url,
            'caption': caption,
            'parse_mode': 'HTML'
        }
        try:
            response = requests.post(url, data=data, timeout=15)
            return response.json()
        except Exception as e:
            print(f"❌ Erro ao enviar vídeo: {e}")
            return None
    
    def enviar_teclado(self, texto, opcoes):
        """Envia mensagem com botões inline"""
        url = f"{self.base_url}/sendMessage"
        
        # Criar botões inline
        keyboard = []
        for opcao in opcoes:
            keyboard.append([{
                'text': opcao['texto'],
                'callback_data': opcao['callback']
            }])
        
        data = {
            'chat_id': self.chat_id,
            'text': texto,
            'parse_mode': 'HTML',
            'reply_markup': json.dumps({'inline_keyboard': keyboard})
        }
        
        try:
            response = requests.post(url, data=data, timeout=10)
            return response.json()
        except Exception as e:
            print(f"❌ Erro ao enviar teclado: {e}")
            return None
    
    def solicitar_curacao(self, segmentos_com_midias):
        """Envia segmentos para curadoria"""
        print("📱 Enviando para curadoria no Telegram...")
        
        # Salvar dados da curadoria
        curacao_data = {
            'timestamp': datetime.now().isoformat(),
            'segmentos': segmentos_com_midias,
            'status': 'pendente',
            'aprovacoes': []
        }
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(curacao_data, f, indent=2, ensure_ascii=False)
        
        # Enviar cabeçalho
        self.enviar_mensagem(
            f"🎬 <b>NOVA CURADORIA DE VÍDEO</b>\n\n"
            f"📝 {len(segmentos_com_midias)} segmentos encontrados\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"Analisando cada segmento..."
        )
        
        # Enviar cada segmento para aprovação
        for i, seg in enumerate(segmentos_com_midias, 1):
            self._enviar_segmento(i, seg, len(segmentos_com_midias))
            time.sleep(2)  # Evitar flood
        
        # Mensagem final
        self.enviar_mensagem(
            f"✅ Todos os {len(segmentos_com_midias)} segmentos enviados!\n\n"
            f"📋 Comandos disponíveis:\n"
            f"/aprovar_todos - Aprovar todas as mídias\n"
            f"/substituir [num] [url] - Substituir mídia\n"
            f"/cancelar - Cancelar este vídeo\n"
            f"/status - Ver status da curadoria"
        )
        
        print("✅ Curadoria enviada! Aguardando resposta...")
    
    def _enviar_segmento(self, num, segmento, total):
        """Envia um segmento específico"""
        midia_info, midia_tipo = segmento['midia']
        texto_seg = segmento['texto']
        keywords = segmento.get('keywords', [])
        
        # Montar mensagem
        caption = (
            f"📌 <b>Segmento {num}/{total}</b>\n\n"
            f"📝 Texto: \"{texto_seg}...\"\n\n"
            f"🔍 Keywords: {', '.join(keywords)}\n"
            f"🎯 Tipo: {midia_tipo}\n\n"
        )
        
        # Enviar mídia
        if midia_tipo == 'video':
            self.enviar_video(midia_info, caption)
        elif midia_tipo in ['foto', 'foto_local']:
            self.enviar_foto(midia_info, caption)
        
        # Botões de ação
        opcoes = [
            {'texto': '✅ Aprovar', 'callback': f'aprovar_{num}'},
            {'texto': '❌ Reprovar', 'callback': f'reprovar_{num}'},
            {'texto': '🔄 Buscar outra', 'callback': f'buscar_{num}'}
        ]
        
        self.enviar_teclado(
            f"<b>Segmento {num}</b> - O que deseja fazer?",
            opcoes
        )
    
    def aguardar_aprovacao(self, timeout=3600):
        """Aguarda aprovação do usuário (1 hora de timeout)"""
        print(f"⏳ Aguardando aprovação (timeout: {timeout}s)...")
        
        inicio = time.time()
        
        while time.time() - inicio < timeout:
            # Verificar se há resposta
            if os.path.exists(CURACAO_FILE):
                with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if data['status'] == 'aprovado':
                    print("✅ Curadoria aprovada!")
                    return data['segmentos']
                elif data['status'] == 'cancelado':
                    print("❌ Curadoria cancelada pelo usuário")
                    return None
            
            time.sleep(5)  # Verificar a cada 5 segundos
        
        print("⏰ Timeout atingido, prosseguindo automaticamente...")
        return None
    
    def notificar_publicacao(self, video_info):
        """Notifica quando o vídeo for publicado"""
        mensagem = (
            f"🎉 <b>VÍDEO PUBLICADO!</b>\n\n"
            f"📺 Título: {video_info['titulo']}\n"
            f"⏱️ Duração: {video_info['duracao']:.1f}s\n"
            f"🔗 URL: {video_info['url']}\n\n"
            f"✅ Publicado com sucesso!"
        )
        self.enviar_mensagem(mensagem)


def processar_comandos_telegram():
    """Processa comandos recebidos do Telegram (webhook ou polling)"""
    curator = TelegramCurator()
    
    # Obter atualizações
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    try:
        response = requests.get(url, timeout=10)
        updates = response.json().get('result', [])
        
        for update in updates:
            if 'message' in update:
                message = update['message']
                text = message.get('text', '')
                
                # Processar comandos
                if text.startswith('/aprovar_todos'):
                    processar_aprovacao_total()
                elif text.startswith('/substituir'):
                    processar_substituicao(text)
                elif text.startswith('/cancelar'):
                    processar_cancelamento()
                elif text.startswith('/status'):
                    enviar_status()
            
            elif 'callback_query' in update:
                callback = update['callback_query']
                data = callback['data']
                
                # Processar callbacks dos botões
                processar_callback(data)
    
    except Exception as e:
        print(f"❌ Erro ao processar comandos: {e}")


def processar_aprovacao_total():
    """Aprova todos os segmentos"""
    if os.path.exists(CURACAO_FILE):
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data['status'] = 'aprovado'
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print("✅ Todos os segmentos aprovados!")


def processar_substituicao(comando):
    """Substitui uma mídia específica"""
    # Formato: /substituir 3 https://example.com/video.mp4
    partes = comando.split()
    if len(partes) < 3:
        return
    
    num_segmento = int(partes[1]) - 1
    nova_url = partes[2]
    
    if os.path.exists(CURACAO_FILE):
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if 0 <= num_segmento < len(data['segmentos']):
            # Determinar tipo da mídia
            tipo = 'video' if any(ext in nova_url.lower() for ext in ['.mp4', '.mov']) else 'foto'
            
            data['segmentos'][num_segmento]['midia'] = (nova_url, tipo)
            data['segmentos'][num_segmento]['modificado'] = True
            
            with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Segmento {num_segmento + 1} substituído!")


def processar_cancelamento():
    """Cancela a criação do vídeo"""
    if os.path.exists(CURACAO_FILE):
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data['status'] = 'cancelado'
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print("❌ Vídeo cancelado pelo usuário!")


def processar_callback(callback_data):
    """Processa cliques nos botões"""
    if callback_data.startswith('aprovar_'):
        num = int(callback_data.split('_')[1]) - 1
        marcar_segmento_aprovado(num)
    
    elif callback_data.startswith('reprovar_'):
        num = int(callback_data.split('_')[1]) - 1
        marcar_segmento_reprovado(num)
    
    elif callback_data.startswith('buscar_'):
        num = int(callback_data.split('_')[1]) - 1
        buscar_nova_midia(num)


def marcar_segmento_aprovado(num):
    """Marca segmento como aprovado"""
    if os.path.exists(CURACAO_FILE):
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if 'aprovacoes' not in data:
            data['aprovacoes'] = []
        
        data['aprovacoes'].append(num)
        
        # Se todos aprovados, marcar como concluído
        if len(data['aprovacoes']) >= len(data['segmentos']):
            data['status'] = 'aprovado'
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def enviar_status():
    """Envia status atual da curadoria"""
    curator = TelegramCurator()
    
    if os.path.exists(CURACAO_FILE):
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        total = len(data['segmentos'])
        aprovados = len(data.get('aprovacoes', []))
        status = data['status']
        
        mensagem = (
            f"📊 <b>STATUS DA CURADORIA</b>\n\n"
            f"✅ Aprovados: {aprovados}/{total}\n"
            f"📌 Status: {status}\n"
            f"⏰ Iniciado: {data['timestamp']}\n"
        )
        
        curator.enviar_mensagem(mensagem)
    else:
        curator.enviar_mensagem("⚠️ Nenhuma curadoria pendente")
