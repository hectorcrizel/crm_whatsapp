from flask import render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
import requests
from app.models import SystemSetting, User, Queue, QuickAnswer, BotMenuOption, BotSpecialRule
from app.extensions import db
from . import bp_admin

# Tenta importar a task de sincronização (opcional)
try:
    from app.tasks.sync import sync_whatsapp_contacts
except ImportError:
    sync_whatsapp_contacts = None


# --- 1. CONFIGURAÇÕES GERAIS (DASHBOARD) ---
@bp_admin.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    # Segurança: Apenas Admin acessa
    if not getattr(current_user, 'is_admin', True):
        flash('Acesso restrito ao administrador.', 'danger')
        return redirect(url_for('chat.index'))

    # SE FOR POST: SALVAR CONFIGURAÇÕES
    if request.method == 'POST':
        try:
            ALLOWED_KEYS = [
                # Integrações
                'EVOLUTION_API_URL', 'EVOLUTION_API_KEY', 'INSTANCE_NAME',
                'COMPANY_NAME', 'DESK_API_URL', 'DESK_API_TOKEN', 'DESK_USER_KEY',
                'DESK_API_KEY', 'DESK_PUBLIC_KEY',
                'DESK_MSG_ASK_EMAIL', 'DESK_MSG_ASK_SUBJECT', 'DESK_MSG_ASK_DESC',
                'DESK_MSG_NOT_FOUND', 'DESK_FAILOVER_QUEUE_ID', 'DESK_MSG_SUCCESS',
                'DESK_MSG_POST_CHOICE',

                # Configurações do Bot
                'BOT_ENABLED', 'BOT_WELCOME_MSG', 'DISTRIBUTION_MODE',
                'BOT_NUMBER',  # Para identificar citações em grupos

                # Mensagens Parametrizáveis
                'MSG_WELCOME',  # Boas vindas
                'MSG_PROTOCOL_OPEN',  # Protocolo gerado
                'MSG_QUEUE_WAIT',  # Fila de espera (Cliente)
                'MSG_FAILOVER_ALERT',  # Alerta de transbordo (Gerente)
                'MSG_TICKET_CLOSED',  # Encerramento

                # Configurações de Grupos
                'GROUP_MENTION_QUEUE_ID',  # ID da Fila para citações
                'MSG_GROUP_MENTION_REPLY'  # Mensagem de resposta automática no grupo
            ]

            for key, value in request.form.items():
                if key in ALLOWED_KEYS:
                    SystemSetting.set(key, value.strip())

            flash('Configurações salvas com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao salvar: {str(e)}', 'danger')
        return redirect(url_for('admin.settings'))

    # SE FOR GET: CARREGAR DADOS PARA O TEMPLATE
    settings_list = SystemSetting.query.all()
    config = {s.key: s.value for s in settings_list}

    users = User.query.order_by(User.name).all()
    queues = Queue.query.order_by(Queue.name).all()
    quick_answers = QuickAnswer.query.order_by(QuickAnswer.title).all()
    bot_options = BotMenuOption.query.order_by(BotMenuOption.digit).all()
    bot_rules = BotSpecialRule.query.all()

    return render_template('admin/settings.html',
                           config=config,
                           users=users,
                           queues=queues,
                           quick_answers=quick_answers,
                           bot_options=bot_options,
                           bot_rules=bot_rules)


# --- 2. GESTÃO DE USUÁRIOS ---
@bp_admin.route('/users/save', methods=['POST'])
@login_required
def save_user():
    try:
        data = request.form
        user_id = data.get('user_id')
        queue_ids = request.form.getlist('queue_ids')

        if user_id:  # Editar existente
            user = User.query.get(user_id)
            if not user: raise Exception("Usuário não encontrado")
            if data.get('password'): user.set_password(data.get('password'))
        else:  # Criar novo
            if User.query.filter_by(email=data.get('email')).first():
                raise Exception("Email já cadastrado")
            user = User(email=data.get('email'))
            user.set_password(data.get('password'))
            db.session.add(user)
            db.session.flush()

        user.name = data.get('name')
        user.is_admin = (data.get('is_admin') == 'on')

        # Atualiza filas vinculadas
        user.queues = []
        for qid in queue_ids:
            q = Queue.query.get(qid)
            if q: user.queues.append(q)

        db.session.commit()
        flash('Usuário salvo com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro: {str(e)}', 'danger')
    return redirect(url_for('admin.settings'))


@bp_admin.route('/users/delete/<user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if user_id == str(current_user.id):
        flash('Você não pode se excluir.', 'warning')
    else:
        User.query.filter_by(id=user_id).delete()
        db.session.commit()
        flash('Usuário removido.', 'success')
    return redirect(url_for('admin.settings'))


# --- 3. GESTÃO DE FILAS ---
@bp_admin.route('/queues/save', methods=['POST'])
@login_required
def save_queue():
    try:
        q_id = request.form.get('queue_id')
        name = request.form.get('name')
        color = request.form.get('color', '#CCCCCC')
        failover_type = request.form.get('failover_type')
        failover_queue_id = request.form.get('failover_queue_id')
        failover_numbers = request.form.get('failover_numbers')

        target_queue_id = failover_queue_id if failover_type == 'queue' and failover_queue_id else None
        target_numbers = failover_numbers if failover_type == 'number' and failover_numbers else None

        if q_id:
            q = Queue.query.get(q_id)
            q.name, q.color = name, color
            q.failover_queue_id, q.failover_numbers = target_queue_id, target_numbers
        else:
            q = Queue(name=name, color=color, failover_queue_id=target_queue_id, failover_numbers=target_numbers)
            db.session.add(q)

        db.session.commit()
        flash('Fila salva!', 'success')
    except Exception as e:
        flash(f'Erro ao salvar fila: {str(e)}', 'danger')
    return redirect(url_for('admin.settings'))


@bp_admin.route('/queues/delete/<queue_id>', methods=['POST'])
@login_required
def delete_queue(queue_id):
    Queue.query.filter_by(id=queue_id).delete()
    db.session.commit()
    flash('Fila removida.', 'success')
    return redirect(url_for('admin.settings'))


# --- 4. RESPOSTAS RÁPIDAS ---
@bp_admin.route('/quick_answers/save', methods=['POST'])
@login_required
def save_quick_answer():
    try:
        qa_id = request.form.get('qa_id')
        title, shortcut, text = request.form.get('title'), request.form.get('shortcut'), request.form.get('text')

        if qa_id:
            qa = QuickAnswer.query.get(qa_id)
            qa.title, qa.shortcut, qa.text = title, shortcut, text
        else:
            qa = QuickAnswer(title=title, shortcut=shortcut, text=text)
            db.session.add(qa)
        db.session.commit()
        flash('Resposta rápida salva!', 'success')
    except Exception as e:
        flash(f'Erro: {str(e)}', 'danger')
    return redirect(url_for('admin.settings'))


@bp_admin.route('/quick_answers/delete/<qa_id>', methods=['POST'])
@login_required
def delete_quick_answer(qa_id):
    QuickAnswer.query.filter_by(id=qa_id).delete()
    db.session.commit()
    flash('Resposta rápida removida.', 'success')
    return redirect(url_for('admin.settings'))


# --- 5. MENU DO BOT ---
@bp_admin.route('/bot/option/save', methods=['POST'])
@login_required
def save_bot_option():
    try:
        opt_id = request.form.get('option_id')
        digit, title, description = request.form.get('digit'), request.form.get('title'), request.form.get(
            'description')

        queue_id = request.form.get('queue_id') or None
        parent_id = request.form.get('parent_id') or None
        response_msg = request.form.get('response_message')
        open_desk = (request.form.get('open_desk_ticket') == 'on')
        is_vip = (request.form.get('is_vip_only') == 'on')

        if opt_id:
            opt = BotMenuOption.query.get(opt_id)
        else:
            opt = BotMenuOption()
            db.session.add(opt)

        opt.digit, opt.title, opt.description = digit, title, description
        opt.queue_id, opt.parent_id = queue_id, parent_id
        opt.open_desk_ticket, opt.response_message = open_desk, response_msg
        opt.is_vip_only, opt.generate_protocol = is_vip, True

        db.session.commit()
        flash('Opção de menu salva!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao salvar menu: {e}', 'danger')
    return redirect(url_for('admin.settings'))


@bp_admin.route('/bot/option/delete/<opt_id>', methods=['POST'])
@login_required
def delete_bot_option(opt_id):
    BotMenuOption.query.filter_by(id=opt_id).delete()
    db.session.commit()
    flash('Opção de menu removida.', 'success')
    return redirect(url_for('admin.settings'))


# --- 6. REGRAS VIP ---
@bp_admin.route('/bot/vip/save', methods=['POST'])
@login_required
def save_bot_rule():
    try:
        rule_id = request.form.get('rule_id')
        keyword = request.form.get('keyword')
        queue_id = request.form.get('queue_id') or None
        special_menu_id = request.form.get('special_menu_id') or None

        if not keyword: raise Exception("Palavra-chave obrigatória")

        if rule_id:
            rule = BotSpecialRule.query.get(rule_id)
        else:
            rule = BotSpecialRule()
            db.session.add(rule)

        rule.keyword, rule.queue_id, rule.special_menu_id = keyword, queue_id, special_menu_id
        db.session.commit()
        flash('Regra VIP salva!', 'success')
    except Exception as e:
        flash(f'Erro ao salvar regra VIP: {e}', 'danger')
    return redirect(url_for('admin.settings'))


@bp_admin.route('/bot/vip/delete/<rule_id>', methods=['POST'])
@login_required
def delete_bot_rule(rule_id):
    BotSpecialRule.query.filter_by(id=rule_id).delete()
    db.session.commit()
    flash('Regra VIP removida.', 'success')
    return redirect(url_for('admin.settings'))


# --- 7. UTILITÁRIOS ---
@bp_admin.route('/test_connection/<service>', methods=['GET'])
@login_required
def test_connection(service):
    if service == 'evolution':
        url = SystemSetting.get('EVOLUTION_API_URL')
        api_key = SystemSetting.get('EVOLUTION_API_KEY')
        instance_name = SystemSetting.get('INSTANCE_NAME')
        if not url or not instance_name: 
            return jsonify({'status': 'error', 'message': 'Configuração incompleta'})
        try:
            headers = {"apikey": api_key} if api_key else {}
            test_url = f"{url.rstrip('/')}/instance/connectionState/{instance_name}"
            resp = requests.get(test_url, headers=headers, timeout=5)
            if resp.status_code in [200, 201]:
                return jsonify({'status': 'ok', 'message': 'Conectado à Evolution API'})
            else:
                return jsonify({'status': 'error', 'message': f'Erro API: {resp.status_code}'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Erro: {str(e)}'})

    if service == 'desk':
        url = SystemSetting.get('DESK_API_URL')
        api_key = SystemSetting.get('DESK_API_KEY')
        public_key = SystemSetting.get('DESK_PUBLIC_KEY')
        
        if not url or not api_key or not public_key:
            return jsonify({'status': 'error', 'message': 'Configuração incompleta'})
        
        try:
            # Conforme solicitado: POST para /Login/autenticar
            auth_url = f"{url.rstrip('/')}/Login/autenticar"
            headers = {
                "Authorization": api_key,
                "Content-Type": "application/json"
            }
            payload = {
                "PublicKey": public_key
            }
            
            resp = requests.post(auth_url, json=payload, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                return jsonify({'status': 'ok', 'message': 'Conectado ao Desk Manager'})
            else:
                return jsonify({'status': 'error', 'message': f'Falha na autenticação ({resp.status_code})'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Erro: {str(e)}'})

    return jsonify({'status': 'error', 'message': 'Serviço desconhecido'}), 400