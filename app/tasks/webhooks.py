from celery import shared_task
from flask import current_app
from app.extensions import db, socketio
from app.models import Message, Contact, Ticket, SystemSetting
from app.services.bot import BotEngine
from app import create_app
import logging
import os
import time
import requests
import mimetypes
import base64
import traceback
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# --- UTILITÁRIOS DE MÍDIA ---

def get_extension_smart(mime_type, original_filename=None):
    if original_filename:
        _, ext = os.path.splitext(original_filename)
        if ext: return ext.lower()
    if not mime_type: return '.bin'
    mime = mime_type.lower()
    if 'image/jpeg' in mime: return '.jpg'
    if 'image/png' in mime: return '.png'
    if 'audio/ogg' in mime or 'audio/opus' in mime: return '.ogg'
    if 'audio/mpeg' in mime: return '.mp3'
    if 'pdf' in mime: return '.pdf'
    guess = mimetypes.guess_extension(mime)
    return guess if guess else '.bin'


def fetch_decrypted_media(message_object, force_mimetype=None, original_filename=None):
    try:
        base_url = SystemSetting.get('EVOLUTION_API_URL')
        api_key = SystemSetting.get('EVOLUTION_API_KEY')
        instance = SystemSetting.get('INSTANCE_NAME')
        if not base_url or not api_key or not instance: return None

        url = f"{base_url.rstrip('/')}/chat/getBase64FromMediaMessage/{instance}"
        payload = {"message": message_object, "convertToMp4": False}
        headers = {"apikey": api_key, "Content-Type": "application/json"}

        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code in [200, 201]:
            base64_str = response.json().get('base64', '')
            if ',' in base64_str: base64_str = base64_str.split(',')[1]
            file_data = base64.b64decode(base64_str)
            return save_file_to_disk(file_data, force_mimetype, original_filename)
    except Exception as e:
        logger.error(f"Erro Fetch Decrypted: {e}")
    return None


def save_file_to_disk(content_bytes, mimetype, filename_orig):
    try:
        save_path = os.path.join(os.getcwd(), 'app/static/uploads')
        os.makedirs(save_path, exist_ok=True)
        ext = get_extension_smart(mimetype, filename_orig)
        new_filename = f"{int(time.time())}_{os.urandom(2).hex()}{ext}"
        with open(os.path.join(save_path, new_filename), 'wb') as f:
            f.write(content_bytes)
        return f"/static/uploads/{new_filename}"
    except Exception as e:
        logger.error(f"Erro save_file_to_disk: {e}")
        return None


def download_media_smart(media_data, full_msg_object):
    url = media_data.get('url', '')
    mimetype = media_data.get('mimetype')
    filename = media_data.get('fileName')
    if '.enc' in url or 'mmg.whatsapp.net' in url or not url:
        return fetch_decrypted_media(full_msg_object, mimetype, filename)
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200: return save_file_to_disk(r.content, mimetype, filename)
    except:
        pass
    return None


# --- PROCESSAMENTO DO WEBHOOK ---

@shared_task(ignore_result=True)
def process_webhook_data(payload):
    try:
        app = create_app()
        with app.app_context():
            data = payload.get('data')
            if isinstance(data, list):
                for item in data: _handle_message(item)
            elif isinstance(data, dict):
                _handle_message(data)
    except Exception as e:
        logger.error(f"FATAL Webhook: {e}")


def _handle_message(msg_data):
    try:
        key = msg_data.get('key', {})
        raw_remote_jid = key.get('remoteJid', '')
        from_me = key.get('fromMe', False)

        # LOG INICIAL: Avisa que o Webhook chegou até aqui
        logger.info(f"📥 WB RECEBIDO | De: {raw_remote_jid} | Enviado_Por_Mim: {from_me}")

        if not raw_remote_jid or 'status@broadcast' in raw_remote_jid: return

        # 1. Identifica Grupo e Normaliza JID (Remove sub-ids como :1)
        is_group = raw_remote_jid.endswith('@g.us')
        remote_jid = raw_remote_jid.split(':')[0] + '@' + raw_remote_jid.split('@')[
            1] if ':' in raw_remote_jid else raw_remote_jid

        push_name = msg_data.get('pushName', 'Desconhecido')
        full_msg_object = msg_data
        message_content = msg_data.get('message', {})

        # Desembrulha mensagens temporárias
        if 'ephemeralMessage' in message_content:
            message_content = message_content['ephemeralMessage'].get('message', {})
        if 'viewOnceMessage' in message_content:
            message_content = message_content['viewOnceMessage'].get('message', {})

        msg_type = 'text'
        content = ""
        context_info = {}

        # Extração de conteúdo e do contextInfo (onde ficam as menções)
        if 'conversation' in message_content:
            content = message_content['conversation']
        elif 'extendedTextMessage' in message_content:
            content = message_content['extendedTextMessage'].get('text', '')
            context_info = message_content['extendedTextMessage'].get('contextInfo', {})
        elif 'imageMessage' in message_content:
            msg_type, content = 'image', download_media_smart(message_content['imageMessage'], full_msg_object)
            context_info = message_content['imageMessage'].get('contextInfo', {})
        elif 'audioMessage' in message_content:
            msg_type, content = 'audio', download_media_smart(message_content['audioMessage'], full_msg_object)
        elif 'videoMessage' in message_content:
            msg_type, content = 'video', download_media_smart(message_content['videoMessage'], full_msg_object)
            context_info = message_content['videoMessage'].get('contextInfo', {})
        elif 'documentMessage' in message_content:
            msg_type, content = 'document', download_media_smart(message_content['documentMessage'], full_msg_object)
            context_info = message_content['documentMessage'].get('contextInfo', {})

        if not content: return

        if from_me:
            # --- MENSAGENS ENVIADAS (POR NÓS) ---
            contact = Contact.query.filter_by(remote_jid=remote_jid).first()
            if not contact:
                contact = Contact(remote_jid=remote_jid, name=push_name)
                db.session.add(contact)
                db.session.commit()

            ticket = Ticket.query.filter(Ticket.contact_id == contact.id, Ticket.status != 'closed').order_by(
                Ticket.created_at.desc()).first()

            if ticket:
                time_limit = datetime.utcnow() - timedelta(seconds=15)
                duplicate = Message.query.filter(Message.ticket_id == ticket.id, Message.content == content,
                                                 Message.created_at >= time_limit).first()

                if not duplicate:
                    new_msg = Message(ticket_id=ticket.id, sender_type='operator', content=content,
                                      message_type=msg_type)
                    db.session.add(new_msg)
                    ticket.updated_at = db.func.now()
                    db.session.commit()
                    socketio.emit('new_message', {'ticket_id': str(ticket.id), 'content': content, 'sender': 'operator',
                                                  'type': msg_type, 'timestamp': new_msg.created_at.isoformat()},
                                  namespace='/')
        else:
            # --- MENSAGENS RECEBIDAS (DO CLIENTE) ---
            bot = BotEngine()

            if is_group:
                # 🛑 REGRA PARA GRUPOS: BLINDADA
                raw_bot_num = SystemSetting.get('BOT_NUMBER')
                if not raw_bot_num:
                    logger.warning("⚠️ BOT_NUMBER não configurado. Ignorando grupo.")
                    return

                # Pega apenas os últimos 8 dígitos (ignora +55, DDD e o 9º dígito problemático)
                clean_bot_num = "".join(filter(str.isdigit, str(raw_bot_num)))
                bot_suffix = clean_bot_num[-8:] if len(clean_bot_num) >= 8 else clean_bot_num

                mentions = context_info.get('mentionedJid', [])

                # LOG VITAL: Confirma se o webhook leu as menções
                logger.info(f"🔍 GRUPO DETECTADO | Suffix Esperado: {bot_suffix} | Menções Encontradas: {mentions}")

                # Verifica se o sufixo (ex: 81266668) está dentro de algum JID da lista de menções
                is_mentioned = any(bot_suffix in m for m in mentions)

                if is_mentioned:
                    logger.info(f"✅ GATILHO ACEITO: Bot citado no grupo! Redirecionando para fila...")
                    bot.handle_group_mention(remote_jid, push_name, content)
                    return
                else:
                    logger.info("❌ GATILHO RECUSADO: Nenhuma menção válida encontrada nesta mensagem.")
                    return
            else:
                # Chat Privado: Segue fluxo normal
                bot.process_message(remote_jid, push_name, content, msg_type)

    except Exception as e:
        logger.error(f"Erro no Webhook Handler: {e}")
        logger.error(traceback.format_exc())