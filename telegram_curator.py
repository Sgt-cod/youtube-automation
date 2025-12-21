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
        self.update_id_offset = 0
        
    def enviar_mensagem(self, texto, reply_markup=None):
        """Envia mensagem de texto"""
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': self.chat_id,
            'text': texto,
            'parse_mode': 'HTML'
        }
        
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        
        try:
            response = requests.post(url, json=data, timeout=10)
            return response.json()
        except Exception as e:
            print(f"❌ Erro ao enviar mensagem: {e}")
            return None
    
    def enviar_foto(self, foto_url, caption, reply_markup=None):
        """Envia foto com legenda"""
        url = f"{self.base_url}/sendPhoto"
        data = {
            'chat_id': self.chat_id,
            'photo': foto_url,
            'caption': caption,
            'parse_mode': 'HTML'
        }
        
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        
        try:
            response = requests.post(url, json=data, timeout=15)
            return response.json()
        except Exception as e:
            print(f"❌ Erro ao enviar foto: {e}")
            return None
    
    def enviar_video(self, video_url, caption, reply_markup=None):
        """Envia vídeo com legenda"""
        url = f"{self.base_url}/sendVideo"
        data = {
            'chat_id': self.chat_id,
            'video': video_url,
            'caption': caption,
            'parse_mode': 'HTML'
        }
        
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        
        try:
            response = requests.post(url, json=data, timeout=15)
            return response.json()
        except Exception as e:
            print(f"❌ Erro ao enviar vídeo: {e}")
            return None
    
    def solicitar_curacao(self, segmentos_com_midias):
        """Inicia curadoria interativa segmento por segmento"""
        print("📱 Iniciando curadoria interativa no Telegram...")
        
        # Salvar dados da curadoria
        curacao_data = {
            'timestamp': datetime.now().isoformat(),
            'segmentos': segmentos_com_midias,
            'status': 'aguardando',
            'segmento_atual': 0,
            'aprovacoes': {},
            'aguardando_url': False
        }
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(curacao_data, f, indent=2, ensure_ascii=False)
        
        # Enviar cabeçalho
        self.enviar_mensagem(
            f"🎬 <b>NOVA CURADORIA DE VÍDEO</b>\n\n"
            f"📝 {len(segmentos_com_midias)} segmentos encontrados\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"Vou enviar segmento por segmento para aprovação.\n"
            f"Você pode aprovar, reprovar ou enviar URL customizada!\n\n"
            f"Comandos disponíveis:\n"
            f"• <b>/cancelar</b> - Cancelar este vídeo\n"
            f"• <b>/status</b> - Ver progresso\n"
            f"• <b>/pular</b> - Aprovar todos restantes"
        )
        
        time.sleep(2)
        
        # Enviar primeiro segmento
        self._enviar_proximo_segmento()
        
        print("✅ Primeiro segmento enviado! Aguardando resposta...")
    
    def _enviar_proximo_segmento(self):
        """Envia o próximo segmento para aprovação"""
        if not os.path.exists(CURACAO_FILE):
            return False
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        segmento_atual = data['segmento_atual']
        segmentos = data['segmentos']
        
        if segmento_atual >= len(segmentos):
            # Todos aprovados
            self._finalizar_curacao()
            return False
        
        seg = segmentos[segmento_atual]
        num = segmento_atual + 1
        total = len(segmentos)
        
        midia_info, midia_tipo = seg['midia']
        texto_seg = seg['texto']
        keywords = seg.get('keywords', [])
        
        # Montar caption
        caption = (
            f"📌 <b>Segmento {num}/{total}</b>\n\n"
            f"📝 <i>\"{texto_seg}...\"</i>\n\n"
            f"🔍 Keywords: {', '.join(keywords)}\n"
            f"🎯 Tipo: {midia_tipo}"
        )
        
        # Criar botões
        keyboard = {
            'inline_keyboard': [
                [
                    {'text': '✅ Aprovar', 'callback_data': f'aprovar_{num}'},
                    {'text': '❌ Buscar outra', 'callback_data': f'buscar_{num}'}
                ],
                [
                    {'text': '🔗 Enviar minha URL', 'callback_data': f'url_{num}'}
                ]
            ]
        }
        
        # Enviar mídia
        if midia_tipo == 'video':
            self.enviar_video(midia_info, caption, keyboard)
        else:
            self.enviar_foto(midia_info, caption, keyboard)
        
        return True
    
    def _finalizar_curacao(self):
        """Finaliza a curadoria"""
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data['status'] = 'aprovado'
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(
            f"🎉 <b>CURADORIA CONCLUÍDA!</b>\n\n"
            f"✅ Todos os {len(data['segmentos'])} segmentos aprovados!\n"
            f"🎥 Montando e publicando vídeo agora...\n\n"
            f"Você receberá o link assim que for publicado!"
        )
    
    def aguardar_aprovacao(self, timeout=3600):
        """Aguarda aprovação interativa do usuário"""
        print(f"⏳ Aguardando aprovação interativa (timeout: {timeout}s)...")
        
        inicio = time.time()
        
        while time.time() - inicio < timeout:
            # Verificar status
            if os.path.exists(CURACAO_FILE):
                with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if data['status'] == 'aprovado':
                    print("✅ Curadoria aprovada!")
                    return data['segmentos']
                elif data['status'] == 'cancelado':
                    print("❌ Curadoria cancelada")
                    return None
            
            # Processar atualizações do Telegram
            self._processar_atualizacoes()
            
            time.sleep(2)
        
        print("⏰ Timeout atingido")
        return None
    
    def _processar_atualizacoes(self):
        """Processa mensagens e callbacks do Telegram"""
        url = f"{self.base_url}/getUpdates"
        params = {
            'offset': self.update_id_offset,
            'timeout': 1
        }
        
        try:
            response = requests.get(url, params=params, timeout=5)
            result = response.json()
            
            if not result.get('ok'):
                return
            
            updates = result.get('result', [])
            
            for update in updates:
                self.update_id_offset = update['update_id'] + 1
                
                # Processar mensagem
                if 'message' in update:
                    self._processar_mensagem(update['message'])
                
                # Processar callback (botão)
                elif 'callback_query' in update:
                    self._processar_callback(update['callback_query'])
        
        except Exception as e:
            pass  # Silencioso para não poluir logs
    
    def _processar_mensagem(self, message):
        """Processa mensagens de texto"""
        text = message.get('text', '')
        
        if not os.path.exists(CURACAO_FILE):
            return
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Comandos
        if text == '/cancelar':
            data['status'] = 'cancelado'
            with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.enviar_mensagem("❌ Vídeo cancelado!")
        
        elif text == '/status':
            atual = data['segmento_atual']
            total = len(data['segmentos'])
            self.enviar_mensagem(
                f"📊 <b>STATUS</b>\n\n"
                f"✅ Aprovados: {atual}/{total}\n"
                f"⏳ Status: {data['status']}"
            )
        
        elif text == '/pular':
            # Aprovar todos restantes
            data['status'] = 'aprovado'
            with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.enviar_mensagem("⏭️ Todos os segmentos restantes aprovados!")
        
        # Se está aguardando URL
        elif data.get('aguardando_url'):
            self._processar_url_customizada(text, data)
    
    def _processar_callback(self, callback):
        """Processa cliques nos botões"""
        callback_data = callback['data']
        callback_id = callback['id']
        
        if not os.path.exists(CURACAO_FILE):
            return
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Responder callback
        self._responder_callback(callback_id, "✅ Processando...")
        
        # Processar ação
        if callback_data.startswith('aprovar_'):
            num = int(callback_data.split('_')[1])
            self._aprovar_segmento(data, num)
        
        elif callback_data.startswith('buscar_'):
            num = int(callback_data.split('_')[1])
            self._buscar_nova_midia(data, num)
        
        elif callback_data.startswith('url_'):
            num = int(callback_data.split('_')[1])
            self._solicitar_url(data, num)
    
    def _aprovar_segmento(self, data, num):
        """Aprova o segmento atual"""
        idx = num - 1
        data['aprovacoes'][str(idx)] = 'aprovado'
        data['segmento_atual'] = idx + 1
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(f"✅ Segmento {num} aprovado!")
        
        time.sleep(1)
        
        # Enviar próximo
        if not self._enviar_proximo_segmento():
            self._finalizar_curacao()
    
    def _buscar_nova_midia(self, data, num):
        """Busca nova mídia para o segmento"""
        idx = num - 1
        seg = data['segmentos'][idx]
        
        self.enviar_mensagem(f"🔄 Buscando nova mídia para segmento {num}...")
        
        # Importar função de busca
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from generate_video import buscar_midia_pexels
            
            # Buscar nova mídia
            novas_midias = buscar_midia_pexels(seg['keywords'], tipo='video', quantidade=3)
            
            if novas_midias:
                # Pegar uma diferente da atual
                midia_atual = seg['midia'][0]
                nova_midia = None
                
                for midia in novas_midias:
                    if midia[0] != midia_atual:
                        nova_midia = midia
                        break
                
                if not nova_midia:
                    nova_midia = novas_midias[0]
                
                # Atualizar
                seg['midia'] = nova_midia
                data['segmentos'][idx] = seg
                
                with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                # Reenviar segmento
                data['segmento_atual'] = idx
                with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                time.sleep(1)
                self._enviar_proximo_segmento()
            else:
                self.enviar_mensagem("⚠️ Não encontrei outra mídia. Tente enviar URL customizada!")
        
        except Exception as e:
            self.enviar_mensagem(f"❌ Erro ao buscar: {e}\nTente enviar URL customizada!")
    
    def _solicitar_url(self, data, num):
        """Solicita URL customizada"""
        idx = num - 1
        
        data['aguardando_url'] = True
        data['url_segmento'] = idx
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(
            f"🔗 <b>Envie a URL do Pexels</b>\n\n"
            f"Exemplo:\n"
            f"<code>https://www.pexels.com/video/ocean-waves-123456/</code>\n\n"
            f"Ou envie:\n"
            f"<code>https://www.pexels.com/photo/mountain-789012/</code>\n\n"
            f"💡 Copie e cole a URL completa do vídeo ou foto"
        )
    
    def _processar_url_customizada(self, url, data):
        """Processa URL customizada enviada pelo usuário"""
        idx = data['url_segmento']
        
        self.enviar_mensagem(f"🔍 Extraindo mídia de: {url}")
        
        try:
            # Extrair ID do Pexels
            import re
            
            # Padrão: https://www.pexels.com/video/TITULO-NUMEROS/
            match_video = re.search(r'pexels\.com/(?:pt-br/)?video/[^/]+-(\d+)', url)
            match_foto = re.search(r'pexels\.com/(?:pt-br/)?photo/[^/]+-(\d+)', url)
            
            if match_video:
                video_id = match_video.group(1)
                midia_url = self._obter_video_pexels(video_id)
                tipo = 'video'
            elif match_foto:
                foto_id = match_foto.group(1)
                midia_url = self._obter_foto_pexels(foto_id)
                tipo = 'foto'
            else:
                self.enviar_mensagem("❌ URL inválida! Use formato: https://www.pexels.com/video/titulo-123456/")
                return
            
            if midia_url:
                # Atualizar segmento
                seg = data['segmentos'][idx]
                seg['midia'] = (midia_url, tipo)
                seg['customizado'] = True
                data['segmentos'][idx] = seg
                
                # Aprovar automaticamente
                data['aprovacoes'][str(idx)] = 'aprovado'
                data['segmento_atual'] = idx + 1
                data['aguardando_url'] = False
                
                with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                self.enviar_mensagem(f"✅ Mídia customizada aplicada ao segmento {idx + 1}!")
                
                time.sleep(1)
                
                # Enviar próximo
                if not self._enviar_proximo_segmento():
                    self._finalizar_curacao()
            else:
                self.enviar_mensagem("❌ Não consegui extrair a mídia. Verifique a URL!")
        
        except Exception as e:
            self.enviar_mensagem(f"❌ Erro: {e}")
    
    def _obter_video_pexels(self, video_id):
        """Obtém URL de download do vídeo"""
        try:
            PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')
            headers = {'Authorization': PEXELS_API_KEY}
            
            url = f'https://api.pexels.com/videos/videos/{video_id}'
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                video = response.json()
                
                # Pegar melhor qualidade
                VIDEO_TYPE = os.environ.get('VIDEO_TYPE', 'short')
                
                for file in video['video_files']:
                    if VIDEO_TYPE == 'short':
                        if file.get('height', 0) > file.get('width', 0):
                            return file['link']
                    else:
                        if file.get('width', 0) >= 1280:
                            return file['link']
                
                # Fallback: primeiro arquivo
                return video['video_files'][0]['link']
        except Exception as e:
            print(f"Erro ao obter vídeo: {e}")
        
        return None
    
    def _obter_foto_pexels(self, foto_id):
        """Obtém URL de download da foto"""
        try:
            PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')
            headers = {'Authorization': PEXELS_API_KEY}
            
            url = f'https://api.pexels.com/v1/photos/{foto_id}'
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                foto = response.json()
                return foto['src']['large2x']
        except Exception as e:
            print(f"Erro ao obter foto: {e}")
        
        return None
    
    def _responder_callback(self, callback_id, texto):
        """Responde ao callback do botão"""
        url = f"{self.base_url}/answerCallbackQuery"
        requests.post(url, json={
            'callback_query_id': callback_id,
            'text': texto,
            'show_alert': False
        }, timeout=5)
    
    def notificar_publicacao(self, video_info):
        """Notifica quando o vídeo for publicado"""
        mensagem = (
            f"🎉 <b>VÍDEO PUBLICADO!</b>\n\n"
            f"📺 Título: {video_info['titulo']}\n"
            f"⏱️ Duração: {video_info['duracao']:.1f}s\n"
            f"🔗 {video_info['url']}\n\n"
            f"✅ Disponível no YouTube agora!"
        )
        self.enviar_mensagem(mensagem)
