import requests
from celery import shared_task
from flask import current_app
from sqlalchemy import text
from app.extensions import db
from app.models import Contact, Ticket


@shared_task(bind=True)
def sync_whatsapp_contacts(self):
    """
    Sincronização CORRIGIDA (Baseada no Log X-Ray):
    1. Lê 'remoteJid' em vez de 'id'.
    2. Lê 'profilePicUrl'.
    3. Filtra LIDs e Groups.
    4. Espelha o banco (Remove antigos, mantendo histórico).
    """
    base_url = current_app.config.get('EVOLUTION_API_URL')
    api_key = current_app.config.get('EVOLUTION_API_KEY')
    instance = current_app.config.get('INSTANCE_NAME')

    if not base_url or not api_key or not instance:
        return "Configurações incompletas."

    headers = {
        "apikey": api_key,
        "Content-Type": "application/json"
    }

    # 1. BUSCA LISTA
    url = f"{base_url}/chat/findContacts/{instance}"
    try:
        response = requests.post(url, json={}, headers=headers, timeout=60)

        if response.status_code not in [200, 201]:
            # Tenta fallback
            url_alt = f"{base_url}/contact/find/{instance}"
            response = requests.post(url_alt, json={}, headers=headers, timeout=60)

        if response.status_code not in [200, 201]:
            return f"Erro API Evolution: {response.status_code}"

        data = response.json()
        raw_contacts = []
        if isinstance(data, list):
            raw_contacts = data
        elif isinstance(data, dict):
            raw_contacts = data.get('contacts') or data.get('data') or []

        valid_remote_jids = []
        count_upsert = 0

        # 2. PROCESSAMENTO (Com as chaves corretas do seu Log)
        for c in raw_contacts:
            # CORREÇÃO PRINCIPAL: Pega remoteJid, se não tiver, tenta id
            remote_jid = c.get('remoteJid') or c.get('id')

            if not remote_jid: continue

            # Filtro 1: Ignora LIDs (Privacy IDs que terminam em @lid)
            if '@lid' in remote_jid:
                continue

            # Filtro 2: Tem que ser usuário real (@s.whatsapp.net)
            if not remote_jid.endswith('@s.whatsapp.net'):
                continue

            # Filtro 3: A parte do número deve ser dígitos (sem hash)
            user_part = remote_jid.split('@')[0]
            if not user_part.isdigit():
                continue

            # Filtro 4: Ignora status
            if 'status' in remote_jid:
                continue

            # Se passou, é válido
            valid_remote_jids.append(remote_jid)

            # Mapeamento de Campos (Baseado no seu Log)
            push_name = c.get('pushName') or c.get('name') or c.get('verifiedName') or user_part
            # O log mostrou que a chave é 'profilePicUrl' (camelCase)
            profile_pic = c.get('profilePicUrl') or c.get('profilePictureUrl') or ''

            # Upsert no Banco
            contact_db = Contact.query.filter_by(remote_jid=remote_jid).first()

            if contact_db:
                # Atualiza se mudou nome ou foto
                if (contact_db.name != push_name) or (contact_db.profile_pic_url != profile_pic):
                    contact_db.name = push_name
                    contact_db.profile_pic_url = profile_pic
            else:
                new_contact = Contact(
                    remote_jid=remote_jid,
                    name=push_name,
                    profile_pic_url=profile_pic
                )
                db.session.add(new_contact)

            count_upsert += 1

        db.session.commit()

        # 3. LIMPEZA (Remove quem não veio na lista, protegendo Tickets)
        if len(valid_remote_jids) > 0:

            # Protege contatos com conversas
            contacts_with_tickets = db.session.query(Ticket.contact_id).distinct().all()
            ids_protected = [row[0] for row in contacts_with_tickets]

            # Deleta quem não é válido E não tem ticket
            contacts_to_delete = Contact.query.filter(
                Contact.remote_jid.notin_(valid_remote_jids),
                Contact.id.notin_(ids_protected)
            ).all()

            deleted_count = 0
            for dying_contact in contacts_to_delete:
                db.session.delete(dying_contact)
                deleted_count += 1

            db.session.commit()

            return f"Sync Sucesso! Processados: {count_upsert}. Paulinho Mecanico e outros salvos. Lixo removido: {deleted_count}."

        return f"Sync Finalizado. Processados: {count_upsert}."

    except Exception as e:
        db.session.rollback()
        print(f"ERRO SYNC: {e}")
        return f"Erro Crítico: {str(e)}"