import os
import time
import base64
import mimetypes
import re
import traceback
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import render_template, jsonify, request, url_for, current_app, send_from_directory
from flask_login import login_required, current_user
from sqlalchemy import or_, and_, func

from app.models import Ticket, Message, Contact, SystemSetting
from app.services.evolution import EvolutionClient
from app.extensions import socketio, db
from . import bp_chat


@bp_chat.route('/')
@login_required
def index():
    return render_template('index.html')


# --- 1. MÉTRICAS (CORRIGIDAS PARA VISÃO TOTAL DO ADMIN) ---
@bp_chat.route('/tickets/counts', methods=['GET'])
@login_required
def ticket_counts():
    try:
        # 1. Meus Chats: Apenas o que o usuário logado está atendendo
        query_open = Ticket.query.filter(Ticket.status == 'open', Ticket.operator_id == current_user.id)

        # 2. Fila: O que não tem dono
        query_pending = Ticket.query.filter(Ticket.status == 'open', Ticket.operator_id == None)

        # Se não for admin, filtra a fila pelas permissões de departamento/fila
        if not getattr(current_user, 'is_admin', False):
            my_queues = [q.id for q in current_user.queues]
            if my_queues:
                query_pending = query_pending.filter(Ticket.queue_id.in_(my_queues))
            else:
                query_pending = query_pending.filter(Ticket.id == None)

        # 3. Monitoramento (Geral): Todos os tickets abertos do sistema (Com ou Sem dono)
        count_all = 0
        if getattr(current_user, 'is_admin', False):
            # Visão God Mode: Ignora operador, pega tudo que está status 'open'
            count_all = Ticket.query.filter(Ticket.status == 'open').count()

        return jsonify({
            'open': query_open.count(),
            'pending': query_pending.count(),
            'all': count_all
        })
    except:
        return jsonify({'open': 0, 'pending': 0, 'all': 0})


# --- 2. LISTAGEM (GOD MODE CORRIGIDO) ---
@bp_chat.route('/tickets', methods=['GET'])
@login_required
def list_tickets():
    try:
        scope = request.args.get('scope', 'me')
        query = Ticket.query.filter(Ticket.status == 'open')

        # === ABA: MONITORAMENTO GERAL (Visão Deus - Sem Restrições) ===
        if scope == 'all_active' and getattr(current_user, 'is_admin', False):
            # Não aplica filtro de operador: mostra atendidos E na fila.
            pass

        # === ABA: MEUS CHATS (Atendimentos do usuário atual) ===
        elif scope == 'me':
            query = query.filter(Ticket.operator_id == current_user.id)

        # === ABA: FILA (Tickets sem dono) ===
        elif scope == 'pending':
            query = query.filter(Ticket.operator_id == None)
            if not getattr(current_user, 'is_admin', False):
                my_queues = [q.id for q in current_user.queues]
                if my_queues:
                    query = query.filter(Ticket.queue_id.in_(my_queues))
                else:
                    return jsonify([])

        # Ordenação por última atualização para o monitoramento ser real-time
        tickets = query.order_by(Ticket.updated_at.desc()).all()
        results = []

        for t in tickets:
            last_msg = Message.query.filter_by(ticket_id=t.id).order_by(Message.created_at.desc()).first()
            preview = last_msg.content if last_msg else "Nova conversa"
            if last_msg and last_msg.message_type != 'text':
                preview = f"[{last_msg.message_type}]"

            results.append({
                'id': str(t.id),
                'contact_name': t.contact.name or 'Sem Nome',
                'profile_pic': t.contact.profile_pic_url,
                'queue_name': t.queue.name if t.queue else 'Geral',
                'queue_color': t.queue.color if t.queue else '#ccc',
                'operator_name': t.operator.name if t.operator else "Na Fila", # Indica quem atende no monitoramento
                'last_msg_content': preview,
                'status': t.status,
                'operator_id': str(t.operator_id) if t.operator_id else None,
                'created_at': t.created_at.isoformat(),
                'updated_at': t.updated_at.isoformat() if t.updated_at else ""
            })
        return jsonify(results)
    except Exception as e:
        print(f"Erro List: {e}")
        return jsonify([])


# --- 3. AUTO-ATRIBUIÇÃO (SOMENTE PARA OPERADORES) ---
@bp_chat.route('/tickets/<ticket_id>/messages', methods=['GET'])
@login_required
def get_messages(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)

    # CORREÇÃO: Admin pode clicar no ticket para monitorar sem "roubar" a posse dele.
    # A auto-atribuição só ocorre se o ticket estiver sem dono E quem abriu NÃO for admin.
    if ticket.status == 'open' and ticket.operator_id is None and not getattr(current_user, 'is_admin', False):

        ticket.operator_id = current_user.id
        db.session.commit()

        tpl = SystemSetting.get('MSG_PROTOCOL_OPEN', 'Olá, sou {atendente} e vou te atender. Protocolo: {protocolo}')

        msg_text = tpl.replace('{nome}', ticket.contact.name or '')
        msg_text = msg_text.replace('{protocolo}', ticket.external_protocol or '')
        msg_text = msg_text.replace('{fila}', ticket.queue.name if ticket.queue else '')
        msg_text = msg_text.replace('{atendente}', current_user.name)

        try:
            EvolutionClient().send_text(ticket.contact.remote_jid, msg_text)
        except Exception as e:
            print(f"Erro Greeting: {e}")

        msg = Message(ticket_id=ticket.id, sender_type='operator', content=msg_text, message_type='text')
        db.session.add(msg)
        db.session.commit()

        socketio.emit('ticket_assigned', {'ticket_id': str(ticket.id), 'operator_id': str(current_user.id)},
                      namespace='/')
        socketio.emit('new_message', {
            'ticket_id': str(ticket.id), 'content': msg_text, 'sender': 'operator',
            'type': 'text', 'timestamp': msg.created_at.isoformat()
        }, namespace='/')

    messages = Message.query.filter_by(ticket_id=ticket_id).order_by(Message.created_at.asc()).all()

    return jsonify([{
        'id': str(m.id),
        'sender': m.sender_type,
        'content': m.content,
        'type': m.message_type,
        'timestamp': m.created_at.isoformat()
    } for m in messages])


# --- 4. ENVIAR MENSAGEM (COM PREFIXO E PROTEÇÃO DE DONO) ---
@bp_chat.route('/tickets/<ticket_id>/messages', methods=['POST'])
@login_required
def send_message(ticket_id):
    data = request.get_json()
    raw_content = data.get('content')
    if not raw_content: return jsonify({'error': 'Vazio'}), 400

    ticket = Ticket.query.get_or_404(ticket_id)

    # Se o Admin enviar mensagem em um ticket sem dono, ele assume (intervenção)
    if not ticket.operator_id and not getattr(current_user, 'is_admin', False):
        ticket.operator_id = current_user.id

    if ticket.status == 'closed': ticket.status = 'open'

    # Identificação visual do remetente
    if getattr(current_user, 'is_admin', False):
        final_content = f"_*Supervisor {current_user.name}:*_\n{raw_content}"
    else:
        final_content = f"_{current_user.name}:_\n{raw_content}"

    msg = Message(ticket_id=ticket.id, sender_type='operator', content=final_content, message_type='text')
    db.session.add(msg)
    ticket.updated_at = db.func.now()
    db.session.commit()

    try:
        EvolutionClient().send_text(ticket.contact.remote_jid, final_content)
    except:
        pass

    socketio.emit('new_message',
                  {'ticket_id': str(ticket.id), 'content': final_content, 'sender': 'operator', 'type': 'text',
                   'timestamp': msg.created_at.isoformat()}, namespace='/')
    return jsonify({'status': 'sent'})


@bp_chat.route('/tickets/<ticket_id>/close', methods=['POST'])
@login_required
def close_ticket(ticket_id):
    t = Ticket.query.get_or_404(ticket_id)
    t.contact.current_menu_id = None
    db.session.add(t.contact)

    tpl = SystemSetting.get('MSG_TICKET_CLOSED', '')
    if tpl:
        txt = tpl.replace('{nome}', t.contact.name or '').replace('{protocolo}', t.external_protocol or '')
        EvolutionClient().send_text(t.contact.remote_jid, txt)
        sys = Message(ticket_id=t.id, sender_type='bot', content=txt, message_type='text')
        db.session.add(sys)
        socketio.emit('new_message', {'ticket_id': str(t.id), 'content': txt, 'sender': 'bot', 'type': 'text',
                                      'timestamp': datetime.utcnow().isoformat()}, namespace='/')

    t.status = 'closed'
    t.closed_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'status': 'closed'})


@bp_chat.route('/tickets/<ticket_id>/upload', methods=['POST'])
@login_required
def upload_file(ticket_id):
    if 'file' not in request.files: return jsonify({'error': 'Sem arquivo'}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({'error': 'Nome vazio'}), 400

    ticket = Ticket.query.get_or_404(ticket_id)

    filename = secure_filename(f"{int(time.time())}_{file.filename}")
    upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
    os.makedirs(upload_folder, exist_ok=True)

    filepath = os.path.join(upload_folder, filename)
    file.save(filepath)

    public_url = f"/static/uploads/{filename}"

    mime_type, _ = mimetypes.guess_type(file.filename)
    if not mime_type: mime_type = 'application/octet-stream'

    if mime_type.startswith('image/'):
        msg_type = 'image'
    elif mime_type.startswith('audio/'):
        msg_type = 'audio'
    elif mime_type.startswith('video/'):
        msg_type = 'video'
    else:
        msg_type = 'document'

    if not ticket.operator_id and not getattr(current_user, 'is_admin', False):
        ticket.operator_id = current_user.id

    if ticket.status == 'closed':
        ticket.status = 'open'

    message = Message(ticket_id=ticket.id, sender_type='operator', content=public_url, message_type=msg_type)
    db.session.add(message)

    if hasattr(ticket, 'updated_at'):
        ticket.updated_at = db.func.now()

    db.session.commit()

    try:
        with open(filepath, "rb") as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')
            base64_data = f"data:{mime_type};base64,{b64}"
        EvolutionClient().send_media(ticket.contact.remote_jid, msg_type, base64_data, custom_filename=file.filename)
    except Exception as e:
        print(f"Erro Upload Evo: {e}")

    socketio.emit('new_message', {
        'ticket_id': str(ticket.id), 'content': public_url, 'sender': 'operator',
        'type': msg_type, 'timestamp': message.created_at.isoformat()
    }, namespace='/')

    return jsonify({'status': 'sent', 'url': public_url})


@bp_chat.route('/media/<path:filename>')
def serve_media_file(filename):
    return send_from_directory(os.path.join(current_app.root_path, 'static', 'uploads'), filename)


@bp_chat.route('/contacts/search', methods=['GET'])
@login_required
def search_contacts():
    q = request.args.get('q', '').lower()
    res = Contact.query.filter(Contact.name.ilike(f'%{q}%')).limit(20).all()
    return jsonify([{'id': c.id, 'name': c.name} for c in res])


@bp_chat.route('/start', methods=['POST'])
@login_required
def start_conversation():
    try:
        data = request.json
        contact_id = data.get('contact_id')
        phone = data.get('phone')
        contact = None
        if contact_id:
            contact = Contact.query.get(contact_id)
        elif phone:
            clean = re.sub(r'\D', '', phone)
            contact = Contact.query.filter_by(remote_jid=f"{clean}@s.whatsapp.net").first()
            if not contact:
                contact = Contact(remote_jid=f"{clean}@s.whatsapp.net", name=phone)
                db.session.add(contact)
                db.session.commit()

        if not contact: return jsonify({'error': 'Inválido'}), 400

        exist = Ticket.query.filter_by(contact_id=contact.id, status='open').first()
        if exist: return jsonify({'ticket_id': str(exist.id), 'contact_name': contact.name})

        new_t = Ticket(contact_id=contact.id, status='open', operator_id=current_user.id)
        new_t.updated_at = db.func.now()
        db.session.add(new_t)
        db.session.commit()
        return jsonify({'ticket_id': str(new_t.id), 'contact_name': contact.name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500