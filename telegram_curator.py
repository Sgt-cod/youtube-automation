import os
import json
import requests
import time
import sys
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
CURACAO_FILE = 'curacao_pendente.json'

class TelegramCurator:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.update_id_offset = self._obter_ultimo_update_id()
        
    def _obter_ultimo_update_id(self):
        """Obtém o último update_id para não processar mensagens antigas"""
        try:
            url = f"{self.base_url}/getUpdates"
            response = requests.get(url, params={'offset': -1}, timeout=5)
            result = response.json()
            
            if result.get('ok') and result.get('result'):
                return result['result'][0]['update_id'] + 1
            return 0
        except:
            return 0
        
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
            result = response.json()
            if result.get('ok'):
                return result
            else:
                print(f"⚠️ Erro ao enviar mensagem: {result}")
                return None
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
            result = response.json()
            if result.get('ok'):
                return result
            else:
                print(f"⚠️ Erro ao enviar foto: {result}")
                return None
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
            result = response.json()
            if result.get('ok'):
                return result
            else:
                print(f"⚠️ Erro ao enviar vídeo: {result}")
                return None
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
            'aguardando_url': False,
            'ultimo_envio': None
        }
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(curacao_data, f, indent=2, ensure_ascii=False)
        
        # Enviar cabeçalho
        self.enviar_mensagem(
            f"🎬 <b>NOVA CURADORIA DE VÍDEO</b>\n\n"
            f"📝 {len(segmentos_com_midias)} segmentos encontrados\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"Vou enviar segmento por segmento para aprovação.\n\n"
            f"<b>Comandos disponíveis:</b>\n"
            f"• <b>/cancelar</b> - Cancela TUDO (workflow para)\n"
            f"• <b>/status</b> - Ver progresso\n"
            f"• <b>/pular</b> - Aprovar todos restantes\n"
            f"• <b>/retomar</b> - Se bot travou, força próximo segmento"
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
            f"🎯 Tipo: {midia_tipo}\n\n"
            f"<i>Se não aparecer o próximo, use /retomar</i>"
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
        print(f"📤 Enviando segmento {num}/{total}...")
        
        resultado = None
        if midia_tipo == 'video':
            resultado = self.enviar_video(midia_info, caption, keyboard)
        else:
            resultado = self.enviar_foto(midia_info, caption, keyboard)
        
        if resultado:
            # Registrar timestamp do envio
            data['ultimo_envio'] = datetime.now().isoformat()
            with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print(f"✅ Segmento {num} enviado com sucesso")
            return True
        else:
            print(f"❌ Falha ao enviar segmento {num}")
            return False
    
    def _finalizar_curacao(self):
        """Finaliza a curadoria"""
        if not os.path.exists(CURACAO_FILE):
            return
            
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
        
        print("✅ Curadoria finalizada - criando vídeo...")
    
    def aguardar_aprovacao(self, timeout=3600):
        """Aguarda aprovação interativa do usuário"""
        print(f"⏳ Aguardando aprovação interativa...")
        print(f"⏰ Timeout: {timeout}s ({timeout/60:.0f} minutos)")
        print(f"🔄 Verificando Telegram a cada 3 segundos...")
        
        inicio = time.time()
        ultima_verificacao = 0
        ultimo_aviso_travamento = 0
        
        while True:
            tempo_decorrido = time.time() - inicio
            
            # Verificar timeout
            if tempo_decorrido >= timeout:
                print(f"⏰ Timeout atingido após {tempo_decorrido/60:.1f} minutos")
                print("⚠️ Cancelando curadoria automaticamente...")
                
                if os.path.exists(CURACAO_FILE):
                    with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    data['status'] = 'timeout'
                    with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                
                self.enviar_mensagem(
                    f"⏰ <b>TIMEOUT ATINGIDO</b>\n\n"
                    f"Aguardei {timeout/60:.0f} minutos mas não recebi resposta.\n"
                    f"Curadoria cancelada automaticamente.\n\n"
                    f"Para criar o vídeo, execute novamente o workflow."
                )
                
                return None
            
            # Mostrar progresso a cada minuto
            if int(tempo_decorrido) % 60 == 0 and tempo_decorrido != ultima_verificacao:
                minutos_passados = int(tempo_decorrido / 60)
                minutos_restantes = int((timeout - tempo_decorrido) / 60)
                print(f"⏱️ {minutos_passados}min decorridos | {minutos_restantes}min restantes")
                ultima_verificacao = tempo_decorrido
            
            # Verificar se bot travou (mais de 2 minutos sem resposta)
            if os.path.exists(CURACAO_FILE):
                with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if data.get('ultimo_envio'):
                    ultimo_envio = datetime.fromisoformat(data['ultimo_envio'])
                    tempo_sem_resposta = (datetime.now() - ultimo_envio).total_seconds()
                    
                    # Avisar a cada 2 minutos
                    if tempo_sem_resposta > 120 and tempo_sem_resposta - ultimo_aviso_travamento > 120:
                        minutos_travado = int(tempo_sem_resposta / 60)
                        seg_atual = data['segmento_atual'] + 1
                        total = len(data['segmentos'])
                        
                        self.enviar_mensagem(
                            f"⚠️ <b>BOT PODE ESTAR TRAVADO</b>\n\n"
                            f"Aguardando resposta há {minutos_travado} minutos...\n"
                            f"Último segmento: {seg_atual}/{total}\n\n"
                            f"Se não recebeu o próximo segmento:\n"
                            f"• Use <b>/retomar</b> para forçar envio\n"
                            f"• Ou use <b>/status</b> para ver situação"
                        )
                        
                        ultimo_aviso_travamento = tempo_sem_resposta
                        print(f"⚠️ Possível travamento detectado - {minutos_travado}min sem resposta")
            
            # Verificar status
            if os.path.exists(CURACAO_FILE):
                with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if data['status'] == 'aprovado':
                    print("✅ Curadoria aprovada pelo usuário!")
                    return data['segmentos']
                
                elif data['status'] == 'cancelado':
                    print("❌ Curadoria cancelada pelo usuário")
                    print("🛑 Encerrando workflow...")
                    
                    # CANCELAR WORKFLOW COMPLETAMENTE
                    self.enviar_mensagem(
                        "🛑 <b>WORKFLOW CANCELADO</b>\n\n"
                        "Encerrando processo...\n"
                        "Nenhum vídeo será criado."
                    )
                    
                    # Encerrar o processo Python
                    sys.exit(1)  # Exit code 1 = erro, cancela o workflow
            
            # Processar atualizações do Telegram
            self._processar_atualizacoes()
            
            # Aguardar antes da próxima verificação
            time.sleep(3)
    
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
            pass
    
    def _processar_mensagem(self, message):
        """Processa mensagens de texto"""
        text = message.get('text', '')
        
        if not os.path.exists(CURACAO_FILE):
            if text == '/start':
                self.enviar_mensagem(
                    "👋 <b>Olá! Sou o Curador de Vídeos</b>\n\n"
                    "Quando um novo vídeo for gerado, enviarei os segmentos "
                    "para você aprovar um por um.\n\n"
                    "Aguarde a próxima execução automática!"
                )
            return
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"📩 Comando recebido: {text}")
        
        # Comandos
        if text == '/cancelar':
            print("🛑 COMANDO /CANCELAR RECEBIDO - CANCELANDO TUDO")
            
            data['status'] = 'cancelado'
            with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.enviar_mensagem(
                "🛑 <b>CANCELAMENTO TOTAL ATIVADO</b>\n\n"
                "❌ Curadoria cancelada\n"
                "❌ Criação do vídeo cancelada\n"
                "❌ Workflow será encerrado\n\n"
                "Nenhum vídeo será publicado."
            )
            
            print("❌ Usuário cancelou TUDO - encerrando workflow")
        
        elif text == '/status':
            atual = data['segmento_atual']
            total = len(data['segmentos'])
            aprovados = len(data.get('aprovacoes', {}))
            
            ultimo_envio_str = "Nunca"
            if data.get('ultimo_envio'):
                ultimo_envio = datetime.fromisoformat(data['ultimo_envio'])
                tempo_decorrido = (datetime.now() - ultimo_envio).total_seconds()
                ultimo_envio_str = f"{int(tempo_decorrido / 60)} minutos atrás"
            
            self.enviar_mensagem(
                f"📊 <b>STATUS DA CURADORIA</b>\n\n"
                f"✅ Segmentos aprovados: {aprovados}\n"
                f"📍 Segmento atual: {atual + 1}/{total}\n"
                f"⏳ Status: {data['status']}\n"
                f"🕐 Último envio: {ultimo_envio_str}\n"
                f"📅 Iniciado: {data['timestamp'][:19]}\n\n"
                f"<i>Se travou, use /retomar</i>"
            )
        
        elif text == '/pular':
            print("⏭️ Usuário pulou - aprovando todos restantes")
            data['status'] = 'aprovado'
            with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.enviar_mensagem("⏭️ <b>Todos os segmentos restantes aprovados!</b>")
        
        elif text == '/retomar':
            print("🔄 Comando /retomar - forçando envio do próximo segmento")
            
            atual = data['segmento_atual']
            total = len(data['segmentos'])
            
            self.enviar_mensagem(
                f"🔄 <b>RETOMANDO CURADORIA</b>\n\n"
                f"Forçando envio do segmento {atual + 1}/{total}..."
            )
            
            time.sleep(1)
            
            if self._enviar_proximo_segmento():
                self.enviar_mensagem("✅ Segmento reenviado com sucesso!")
            else:
                self.enviar_mensagem("❌ Erro ao reenviar. Todos já foram enviados?")
        
        elif data.get('aguardando_url'):
            self._processar_url_customizada(text, data)
    
    def _processar_callback(self, callback):
        """Processa cliques nos botões"""
        callback_data = callback['data']
        callback_id = callback['id']
        
        if not os.path.exists(CURACAO_FILE):
            self._responder_callback(callback_id, "⚠️ Curadoria expirada")
            return
        
        with open(CURACAO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"🖱️ Botão clicado: {callback_data}")
        
        self._responder_callback(callback_id, "✅ Processando...")
        
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
        
        print(f"✅ Segmento {num} aprovado")
        
        data['aprovacoes'][str(idx)] = 'aprovado'
        data['segmento_atual'] = idx + 1
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(f"✅ <b>Segmento {num} aprovado!</b>")
        
        time.sleep(2)
        
        if not self._enviar_proximo_segmento():
            self._finalizar_curacao()
    
    def _buscar_nova_midia(self, data, num):
        """Busca nova mídia para o segmento"""
        idx = num - 1
        seg = data['segmentos'][idx]
        
        print(f"🔄 Buscando nova mídia para segmento {num}")
        
        self.enviar_mensagem(f"🔄 Buscando nova mídia...")
        
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from generate_video import buscar_midia_pexels
            
            novas_midias = buscar_midia_pexels(seg['keywords'], tipo='video', quantidade=3)
            
            if novas_midias:
                midia_atual = seg['midia'][0]
                nova_midia = None
                
                for midia in novas_midias:
                    if midia[0] != midia_atual:
                        nova_midia = midia
                        break
                
                if not nova_midia:
                    nova_midia = novas_midias[0]
                
                seg['midia'] = nova_midia
                data['segmentos'][idx] = seg
                data['segmento_atual'] = idx
                
                with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                print(f"✅ Nova mídia encontrada")
                time.sleep(2)
                self._enviar_proximo_segmento()
            else:
                self.enviar_mensagem("⚠️ Não encontrei outra. Tente 🔗 Enviar URL!")
        
        except Exception as e:
            print(f"❌ Erro: {e}")
            self.enviar_mensagem(f"❌ Erro. Tente 🔗 Enviar URL!")
    
    def _solicitar_url(self, data, num):
        """Solicita URL customizada"""
        idx = num - 1
        
        print(f"🔗 Solicitando URL para segmento {num}")
        
        data['aguardando_url'] = True
        data['url_segmento'] = idx
        
        with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.enviar_mensagem(
            f"🔗 <b>Envie a URL do Pexels</b>\n\n"
            f"Exemplo:\n"
            f"<code>https://www.pexels.com/video/ocean-123456/</code>\n\n"
            f"💡 Copie e cole a URL completa"
        )
    
    def _processar_url_customizada(self, url, data):
        """Processa URL customizada"""
        idx = data['url_segmento']
        
        print(f"🔍 Processando URL: {url}")
        
        self.enviar_mensagem(f"🔍 Extraindo mídia...")
        
        try:
            import re
            
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
                self.enviar_mensagem("❌ URL inválida!")
                return
            
            if midia_url:
                seg = data['segmentos'][idx]
                seg['midia'] = (midia_url, tipo)
                seg['customizado'] = True
                data['segmentos'][idx] = seg
                
                data['aprovacoes'][str(idx)] = 'aprovado'
                data['segmento_atual'] = idx + 1
                data['aguardando_url'] = False
                
                with open(CURACAO_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                print(f"✅ URL aplicada ao segmento {idx + 1}")
                
                self.enviar_mensagem(f"✅ <b>Mídia customizada aplicada!</b>")
                
                time.sleep(2)
                
                if not self._enviar_proximo_segmento():
                    self._finalizar_curacao()
            else:
                self.enviar_mensagem("❌ Não consegui extrair. Verifique a URL!")
        
        except Exception as e:
            print(f"❌ Erro: {e}")
            self.enviar_mensagem(f"❌ Erro: {e}")
    
    def _obter_video_pexels(self, video_id):
        """Obtém URL do vídeo"""
        try:
            PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')
            headers = {'Authorization': PEXELS_API_KEY}
            
            url = f'https://api.pexels.com/videos/videos/{video_id}'
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                video = response.json()
                VIDEO_TYPE = os.environ.get('VIDEO_TYPE', 'short')
                
                for file in video['video_files']:
                    if VIDEO_TYPE == 'short':
                        if file.get('height', 0) > file.get('width', 0):
                            return file['link']
                    else:
                        if file.get('width', 0) >= 1280:
                            return file['link']
                
                return video['video_files'][0]['link']
        except Exception as e:
            print(f"❌ Erro: {e}")
        
        return None
    
    def _obter_foto_pexels(self, foto_id):
        """Obtém URL da foto"""
        try:
            PEXELS_API_KEY = os.environ.get('PEXELS_API_KEY')
            headers = {'Authorization': PEXELS_API_KEY}
            
            url = f'https://api.pexels.com/v1/photos/{foto_id}'
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                foto = response.json()
                return foto['src']['large2x']
        except Exception as e:
            print(f"❌ Erro: {e}")
        
        return None
    
    def _responder_callback(self, callback_id, texto):
        """Responde ao callback do botão"""
        url = f"{self.base_url}/answerCallbackQuery"
        try:
            requests.post(url, json={
                'callback_query_id': callback_id,
                'text': texto,
                'show_alert': False
            }, timeout=5)
        except:
            pass
    
    def notificar_publicacao(self, video_info):
        """Notifica publicação"""
        mensagem = (
            f"🎉 <b>VÍDEO PUBLICADO!</b>\n\n"
            f"📺 Título: {video_info['titulo']}\n"
            f"⏱️ Duração: {video_info['duracao']:.1f}s\n"
            f"🔗 {video_info['url']}\n\n"
            f"✅ Disponível no YouTube!"
        )
        self.enviar_mensagem(mensagem)
        print("📤 Notificação enviada")
