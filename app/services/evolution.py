import requests
import logging
import mimetypes
from app.models import SystemSetting  # <--- Essencial para ler do banco

logger = logging.getLogger(__name__)


class EvolutionClient:
    def __init__(self):
        """
        Inicializa lendo ESTRITAMENTE do banco de dados.
        Sem valores hardcoded. Se não estiver no banco, ficará None.
        """
        try:
            # Busca configurações direto do banco
            self.base_url = SystemSetting.get('EVOLUTION_API_URL')
            self.api_key = SystemSetting.get('EVOLUTION_API_KEY')
            self.instance_name = SystemSetting.get('INSTANCE_NAME')

            # --- DEBUG: Para você confirmar no terminal o que está sendo usado ---
            print(f"🔧 [CONFIG] URL: {self.base_url}")
            print(f"🔧 [CONFIG] Instance: {self.instance_name}")
            # -------------------------------------------------------------------

            if not self.base_url or not self.api_key or not self.instance_name:
                logger.warning("⚠️ Atenção: Configurações da Evolution incompletas no Painel Admin!")

        except Exception as e:
            logger.error(f"Erro ao ler SystemSettings: {e}")
            self.base_url = None
            self.api_key = None
            self.instance_name = None

        self.headers = {
            "Content-Type": "application/json",
            "apikey": self.api_key
        }

    def _clean_number(self, remote_jid):
        """Remove o sufixo @s.whatsapp.net se existir"""
        if not remote_jid: return ""
        return remote_jid.replace('@s.whatsapp.net', '').split('@')[0]

    def _validate_config(self):
        """Impede o envio se as configurações estiverem vazias"""
        if not self.base_url or not self.instance_name:
            logger.error("❌ Tentativa de envio sem configuração definida no Admin.")
            return False
        return True

    def send_text(self, remote_jid, text):
        """Envia mensagem de texto simples"""
        if not self._validate_config(): return None

        number = self._clean_number(remote_jid)
        url = f"{self.base_url}/message/sendText/{self.instance_name}"

        payload = {
            "number": number,
            "options": {
                "delay": 1200,
                "presence": "composing",
                "linkPreview": True
            },
            "text": text
        }

        try:
            print(f"📤 Enviando Texto para: {url}")
            response = requests.post(url, json=payload, headers=self.headers, timeout=15)

            if response.status_code not in [200, 201]:
                print(f"❌ ERRO API ({response.status_code}): {response.text}")

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Erro Conexão Evolution: {e}")
            return None

    def send_media(self, remote_jid, media_type, url, caption='', custom_filename=None):
        """Envia mídia (Imagem, Áudio, Doc)"""
        if not self._validate_config(): return None

        number = self._clean_number(remote_jid)
        endpoint = f"{self.base_url}/message/sendMedia/{self.instance_name}"

        if media_type not in ['image', 'video', 'audio', 'document']:
            media_type = 'document'

        # Default params
        mime_type = "application/octet-stream"
        file_name = custom_filename or f"file_{number}"
        final_media = url
        url_str = str(url)

        # Tratamento de Base64
        if url_str.startswith('data:'):
            try:
                parts = url_str.split(',')
                header = parts[0]
                if ':' in header and ';' in header:
                    mime_type = header.split(':')[1].split(';')[0]
                    if not custom_filename:
                        ext = mimetypes.guess_extension(mime_type) or '.bin'
                        file_name = f"upload{ext}"

                if len(parts) > 1:
                    final_media = parts[1]
            except Exception as e:
                logger.error(f"Erro base64: {e}")

        payload = {
            "number": number,
            "mediatype": media_type,
            "mimetype": mime_type,
            "fileName": file_name,
            "caption": caption,
            "media": final_media,
            "options": {
                "delay": 1200,
                "presence": "composing"
            }
        }

        try:
            print(f"📤 Enviando Mídia para: {endpoint}")
            response = requests.post(endpoint, json=payload, headers=self.headers, timeout=60)

            if response.status_code not in [200, 201]:
                print(f"❌ ERRO ENVIO MÍDIA: {response.text}")

            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Erro Evolution Media: {e}")
            return None