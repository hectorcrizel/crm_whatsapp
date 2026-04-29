import logging
import uuid
import requests
import json
from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified
from app.extensions import db, socketio
from app.models import User, Contact, Ticket, Queue, Message, SystemSetting, BotMenuOption, BotSpecialRule, user_queues
from app.services.evolution import EvolutionClient

logger = logging.getLogger(__name__)


class BotEngine:
    def __init__(self):
        self.evo = EvolutionClient()

    def process_message(self, remote_jid, push_name, text_content, msg_type='text'):
        """Processamento padrão para chats privados (Direct Message)"""
        # 1. Identifica/Cria Contato
        contact = Contact.query.filter_by(remote_jid=remote_jid).first()
        if not contact:
            contact = Contact(remote_jid=remote_jid, name=push_name)
            db.session.add(contact)
            db.session.commit()

        # 2. Verifica Ticket Aberto (Bot não interfere em tickets em andamento)
        open_ticket = Ticket.query.filter_by(contact_id=contact.id, status='open').first()
        if open_ticket:
            self._save_message(open_ticket.id, text_content, 'contact', msg_type)
            return

        # 3. Bot Ativo Globalmente?
        if SystemSetting.get('BOT_ENABLED') != 'on':
            self._create_direct_ticket(contact, None, text_content, msg_type)
            return

        # 4. Regras VIP (Gatilhos por palavra-chave no nome)
        if contact.current_menu_id is None and msg_type == 'text':
            if self._check_contact_name_vip(contact, text_content, msg_type):
                return

        # 5. Estado de Conversa (Fluxos Especiais como Desk Manager)
        if contact.conversation_state and msg_type == 'text':
            self._handle_state_logic(contact, text_content.strip())
            return

        # 6. Navegação de Menus
        if msg_type == 'text':
            self._handle_menu_logic(contact, text_content.strip(), msg_type)
        else:
            self._send_menu_options(contact)

    # --- NOVO: FLUXO PARA CITAÇÃO EM GRUPOS ---
    def handle_group_mention(self, remote_jid, push_name, text_content):
        """Fluxo disparado quando o bot é citado com @ no grupo"""

        # 1. Identifica ou cria o contato do Grupo (JID termina em @g.us)
        contact = Contact.query.filter_by(remote_jid=remote_jid).first()
        if not contact:
            contact = Contact(remote_jid=remote_jid, name=push_name)
            db.session.add(contact)
            db.session.commit()

        # 2. Verifica se já há um ticket aberto para este grupo
        ticket = Ticket.query.filter_by(contact_id=contact.id, status='open').first()

        if not ticket:
            # 3. Cria novo ticket na fila específica definida no Admin
            queue_id = SystemSetting.get('GROUP_MENTION_QUEUE_ID')

            # Validação de segurança: se não houver fila, não trava o sistema, mas loga o erro
            if not queue_id or queue_id == "None":
                logger.error("❌ GROUP_MENTION_QUEUE_ID não configurado no painel Admin.")
                return

            prot = str(uuid.uuid4())[:8].upper()
            ticket = Ticket(
                contact_id=contact.id,
                queue_id=queue_id,
                status='open',
                external_protocol=prot
            )
            db.session.add(ticket)
            db.session.commit()

        # 4. Salva a mensagem que continha a menção
        self._save_message(ticket.id, text_content, 'contact')

        # 5. Tenta atribuir a um operador disponível
        operator = self._try_assign_operator(ticket)

        # 6. Busca Template do Admin (SEM HARDCODE)
        # Chave definida no seu admin/routes.py
        tpl = SystemSetting.get('MSG_GROUP_MENTION_REPLY', 'Olá! Recebi sua citação. Aguarde um momento.')

        # 7. Substituição Blindada de Variáveis
        final_msg = tpl.replace('{nome}', push_name)  # Nome do Grupo
        final_msg = final_msg.replace('{protocolo}', ticket.external_protocol or '')
        final_msg = final_msg.replace('{atendente}', operator.name if operator else 'equipe de suporte')
        final_msg = final_msg.replace('{fila}', ticket.queue.name if ticket.queue else 'Geral')

        # 8. Envia Resposta no Grupo e registra no banco
        if final_msg.strip():
            try:
                self.evo.send_text(remote_jid, final_msg)
                self._save_message(ticket.id, final_msg, 'bot')
            except Exception as e:
                logger.error(f"Erro ao responder no grupo: {e}")

    # --- DISTRIBUIÇÃO E ROTEAMENTO (RECURSIVO) ---
    def _try_assign_operator(self, ticket):
        queue = ticket.queue
        # Busca operador respeitando a hierarquia de transbordo (Fila A -> Fila B...)
        operator, final_queue = self._find_operator_recursive(queue, visited_ids=set())

        if operator:
            ticket.operator_id = operator.id
            db.session.commit()
            return operator
        else:
            # Ninguém online: Dispara alerta externo para o gerente
            ticket.operator_id = None
            db.session.commit()
            self._handle_failover_alert(ticket, final_queue or queue)
            return None

    def _find_operator_recursive(self, queue, visited_ids):
        if not queue: return None, None
        if str(queue.id) in visited_ids: return None, queue
        visited_ids.add(str(queue.id))

        operator = self._get_least_occupied_online(queue)
        if operator: return operator, queue

        # Se a fila atual falhar, tenta a fila de backup (Failover)
        if queue.failover_queue_id:
            return self._find_operator_recursive(queue.failover_target, visited_ids)
        return None, queue

    def _get_least_occupied_online(self, queue):
        """Busca o operador Online com menos chamados na fila específica"""
        db.session.commit()  # Limpa cache do Celery

        ops_in_queue = db.session.query(User).join(user_queues).filter(
            user_queues.c.queue_id == queue.id
        ).all()

        if not ops_in_queue: return None

        online_ops = []
        for op in ops_in_queue:
            db.session.refresh(op)  # Puxa status 'online' em tempo real
            status_atual = str(op.status).strip().lower() if op.status else ''
            if status_atual == 'online':
                online_ops.append(op)

        if not online_ops: return None

        # Algoritmo Round-robin/Least-load
        selected_op = None
        min_tickets = float('inf')
        for op in online_ops:
            count = Ticket.query.filter_by(operator_id=op.id, status='open').count()
            if count < min_tickets:
                min_tickets = count
                selected_op = op
        return selected_op

    def _handle_failover_alert(self, ticket, queue):
        """Dispara Alerta de Transbordo para Gerentes via WhatsApp Externo"""
        if queue and queue.failover_numbers:
            # Chave alinhada com ALLOWED_KEYS do seu admin/routes.py
            tpl_transbordo = SystemSetting.get('MSG_FAILOVER_ALERT', "🚨 Fila {fila} offline. Cliente: {nome}")

            msg = tpl_transbordo.replace('{nome}', ticket.contact.name or 'Cliente')
            msg = msg.replace('{fila}', queue.name if queue else 'Geral')
            msg = msg.replace('{protocolo}', ticket.external_protocol or '')

            for num in [n.strip() for n in queue.failover_numbers.split(',') if n.strip()]:
                jid = num if '@s.whatsapp.net' in num else f"{num}@s.whatsapp.net"
                try:
                    self.evo.send_text(jid, msg)
                except Exception as e:
                    logger.error(f"Erro ao notificar gerente: {e}")

    # --- DESK MANAGER INTEGRATION ---
    def _get_desk_auth_token(self):
        url = SystemSetting.get('DESK_API_URL')
        api_key = SystemSetting.get('DESK_API_KEY')
        public_key = SystemSetting.get('DESK_PUBLIC_KEY')
        if not url or not api_key or not public_key: return None

        try:
            auth_url = f"{url.rstrip('/')}/Login/autenticar"
            headers = {"Authorization": api_key, "Content-Type": "application/json"}
            payload = {"PublicKey": public_key}
            resp = requests.post(auth_url, json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.text.strip().replace('"', '')
        except Exception as e:
            logger.error(f"Erro Auth Desk: {e}")
        return None

    def _find_desk_user_id(self, email, token):
        url = SystemSetting.get('DESK_API_URL')
        if not url: return None
        try:
            search_url = f"{url.rstrip('/')}/Usuarios/lista"
            headers = {"Authorization": token, "Content-Type": "application/json"}
            payload = {
                "Pesquisa": email, "Ativo": "S", "Pagina": 1, "Quantidade": 1,
                "Colunas": {"Chave": "on", "Email": "on"}
            }
            resp = requests.post(search_url, json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('root') and len(data['root']) > 0:
                    return data['root'][0].get('Chave')
        except Exception as e:
            logger.error(f"Erro Busca Usuário Desk: {e}")
        return None

    def _create_desk_ticket(self, context, token):
        url = SystemSetting.get('DESK_API_URL')
        if not url: return None
        try:
            create_url = f"{url.rstrip('/')}/Chamados"
            headers = {"Authorization": token, "Content-Type": "application/json"}
            payload = {
                "TChamado": {
                    "Solicitante": context['solicitante_id'],
                    "Assunto": context['assunto'],
                    "Descricao": context['descricao'],
                    "Categoria": "000060"
                }
            }
            logger.info(f"DESK PUT /Chamados - URL: {create_url}")
            logger.info(f"DESK PUT /Chamados - Payload: {json.dumps(payload)}")
            resp = requests.put(create_url, json=payload, headers=headers, timeout=15)
            logger.info(f"DESK PUT /Chamados - Status: {resp.status_code} - Body: {resp.text[:500]}")
            if resp.status_code in [200, 201]:
                try:
                    data = resp.json()
                    # Extrai apenas o número de referência do chamado
                    return data.get('TChamado', {}).get('Referencia', str(data))
                except:
                    return resp.text.strip().replace('"', '')
        except Exception as e:
            logger.error(f"Erro Criar Chamado Desk: {e}")
        return None

    def _handle_state_logic(self, contact, user_input):
        state = contact.conversation_state
        context = contact.desk_context or {}

        if state == 'AWAITING_DESK_EMAIL':
            token = self._get_desk_auth_token()
            user_id = self._find_desk_user_id(user_input, token) if token else None
            
            if user_id:
                context['solicitante_id'] = user_id
                contact.desk_context = dict(context)
                flag_modified(contact, 'desk_context')
                contact.conversation_state = 'AWAITING_DESK_SUBJECT'
                db.session.commit()
                logger.info(f"Desk user found: {user_id}, context saved: {contact.desk_context}")
                self.evo.send_text(contact.remote_jid, SystemSetting.get('DESK_MSG_ASK_SUBJECT', "Qual o assunto do chamado?"))
            else:
                # Transbordo
                msg = SystemSetting.get('DESK_MSG_NOT_FOUND', "E-mail não encontrado. Transferindo...")
                self.evo.send_text(contact.remote_jid, msg)
                contact.conversation_state = None
                contact.desk_context = None
                db.session.commit()
                
                # Transfere para a fila de transbordo configurada
                queue_id = SystemSetting.get('DESK_FAILOVER_QUEUE_ID')
                q = Queue.query.get(queue_id) if queue_id else None
                # Se não houver fila configurada, usa a do menu original (se houver) ou Geral
                target_queue_id = q.id if q else context.get('original_queue_id')
                
                # Cria ticket local para atendimento humano
                fake_opt = BotMenuOption(queue_id=target_queue_id)
                self._execute_final_action(contact, fake_opt, f"E-mail Desk não encontrado: {user_input}", 'text')

        elif state == 'AWAITING_DESK_SUBJECT':
            context['assunto'] = user_input
            contact.desk_context = dict(context)
            flag_modified(contact, 'desk_context')
            contact.conversation_state = 'AWAITING_DESK_DESC'
            db.session.commit()
            logger.info(f"Subject saved, context now: {contact.desk_context}")
            self.evo.send_text(contact.remote_jid, SystemSetting.get('DESK_MSG_ASK_DESC', "Descreva o seu problema:"))

        elif state == 'AWAITING_DESK_DESC':
            context['descricao'] = user_input
            logger.info(f"Description received, full context: {context}")
            token = self._get_desk_auth_token()
            ticket_res = self._create_desk_ticket(context, token) if token else None
            
            if ticket_res:
                ticket_num = str(ticket_res) # Assume que o retorno é o número ou contém ele
                msg_tpl = SystemSetting.get('DESK_MSG_SUCCESS', "Chamado aberto com sucesso! Número: {ticket}")
                self.evo.send_text(contact.remote_jid, msg_tpl.replace('{ticket}', ticket_num))
                
                contact.conversation_state = 'AWAITING_DESK_CHOICE'
                db.session.commit()
                self.evo.send_text(contact.remote_jid, SystemSetting.get('DESK_MSG_POST_CHOICE', "1. Falar com atendente\n2. Aguardar retorno"))
            else:
                self.evo.send_text(contact.remote_jid, "Erro ao abrir chamado no Desk Manager. Transferindo para suporte humano...")
                contact.conversation_state = None
                db.session.commit()
                fake_opt = BotMenuOption(queue_id=context.get('original_queue_id'))
                self._execute_final_action(contact, fake_opt, "Falha na abertura automática do Desk", 'text')

        elif state == 'AWAITING_DESK_CHOICE':
            contact.conversation_state = None
            contact.desk_context = None
            db.session.commit()
            
            if user_input == '1':
                q_id = context.get('original_queue_id')
                fake_opt = BotMenuOption(queue_id=q_id)
                self._execute_final_action(contact, fake_opt, "Cliente solicitou atendimento após abertura Desk", 'text')
            else:
                self.evo.send_text(contact.remote_jid, "Entendido. Acompanhe seu chamado pelo e-mail ou portal.")

    # --- LÓGICA DE MENUS E NAVEGAÇÃO ---
    def _check_contact_name_vip(self, contact, original_msg, msg_type):
        if not contact.name: return False
        name_lower = contact.name.lower()
        rules = BotSpecialRule.query.all()
        for rule in rules:
            if rule.keyword.lower() in name_lower:
                if rule.special_menu_id:
                    t = BotMenuOption.query.get(rule.special_menu_id)
                    if t:
                        contact.current_menu_id = t.id
                        db.session.commit()
                        self._send_menu_options(contact, t)
                        return True
                elif rule.queue_id:
                    fake = BotMenuOption(queue_id=rule.queue_id, open_desk_ticket=True, response_message=None)
                    self._execute_final_action(contact, fake, original_msg, msg_type)
                    return True
        return False

    def _handle_menu_logic(self, contact, user_input, msg_type):
        input_lower = user_input.lower()
        current = BotMenuOption.query.get(contact.current_menu_id) if contact.current_menu_id else None

        if input_lower in ['0', 'voltar', 'sair', 'inicio']:
            self._navigate_back(contact, current)
            return

        opt = None
        if current:
            opt = BotMenuOption.query.filter_by(parent_id=current.id, digit=input_lower).first()
        else:
            opt = BotMenuOption.query.filter_by(parent_id=None, digit=input_lower, is_vip_only=False).first()

        if opt:
            has_child = BotMenuOption.query.filter_by(parent_id=opt.id).first()
            if has_child:
                contact.current_menu_id = opt.id
                db.session.commit()
                self._send_menu_options(contact, opt)
            else:
                self._execute_final_action(contact, opt, user_input, msg_type)
        else:
            if current:
                self.evo.send_text(contact.remote_jid, "Opção inválida.")
                self._send_menu_options(contact, current)
            else:
                self._send_menu_options(contact, None)

    def _send_menu_options(self, contact, parent_menu=None):
        if parent_menu:
            header = f"📂 *{parent_menu.title}*\n{parent_menu.description or 'Selecione:'}\n"
            options = parent_menu.children
        else:
            tpl = SystemSetting.get('MSG_WELCOME', "Olá {nome}, bem-vindo!")
            header = tpl.replace('{nome}', contact.name or 'Cliente') + "\n\n"
            options = BotMenuOption.query.filter_by(parent_id=None, is_vip_only=False).order_by(
                BotMenuOption.digit).all()

        if not options and not parent_menu:
            self._create_direct_ticket(contact, None, "Início automático", 'text')
            return

        txt = [header]
        for o in options: txt.append(f"*{o.digit}* - {o.title}")
        if parent_menu: txt.append("\n*0* - Voltar")
        self.evo.send_text(contact.remote_jid, "\n".join(txt))

    def _navigate_back(self, contact, current):
        if not current or not current.parent_id:
            contact.current_menu_id = None
            self._send_menu_options(contact, None)
        else:
            contact.current_menu_id = current.parent_id
            p = BotMenuOption.query.get(current.parent_id)
            self._send_menu_options(contact, p)
        db.session.commit()

    def _execute_final_action(self, contact, option, original_text, msg_type):
        """Finaliza a triagem e joga para o atendimento humano ou inicia fluxo Desk"""
        # Se for para abrir ticket no Desk Manager, inicia o fluxo de perguntas
        is_desk = bool(getattr(option, 'open_desk_ticket', False))
        logger.info(f"Final Action: Option={option.title}, is_desk={is_desk}")
        
        if is_desk:
            contact.conversation_state = 'AWAITING_DESK_EMAIL'
            contact.desk_context = {'original_queue_id': str(option.queue_id) if option.queue_id else None}
            db.session.commit()
            self.evo.send_text(contact.remote_jid, SystemSetting.get('DESK_MSG_ASK_EMAIL', "Informe seu e-mail para abrir o chamado:"))
            return

        contact.current_menu_id = None
        db.session.commit()

        prot = str(uuid.uuid4())[:8].upper()
        ticket = Ticket(
            contact_id=contact.id, queue_id=option.queue_id, status='open',
            external_protocol=prot, operator_id=None
        )
        db.session.add(ticket)
        db.session.commit()

        self._save_message(ticket.id, original_text, 'contact', msg_type)
        operator = self._try_assign_operator(ticket)

        if operator:
            tpl = option.response_message or SystemSetting.get('MSG_PROTOCOL_OPEN', 'Ticket {protocolo}.')
        else:
            tpl = SystemSetting.get('MSG_QUEUE_WAIT', 'Olá {nome}, você está na fila. Protocolo: {protocolo}')

        final = tpl.replace('{protocolo}', prot)
        final = final.replace('{nome}', contact.name or 'Cliente')
        final_queue_name = option.queue.name if option.queue else 'Geral'
        final = final.replace('{fila}', final_queue_name)
        final = final.replace('{atendente}', operator.name if operator else 'nossa equipe')

        if final.strip():
            self.evo.send_text(contact.remote_jid, final)
            self._save_message(ticket.id, final, 'bot')

    def _create_direct_ticket(self, contact, queue_id, content, msg_type):
        """Atendimento direto quando o bot de triagem está desligado"""
        prot = str(uuid.uuid4())[:8].upper()
        ticket = Ticket(contact_id=contact.id, queue_id=queue_id, status='open', external_protocol=prot)
        db.session.add(ticket)
        db.session.commit()

        self._save_message(ticket.id, content, 'contact', msg_type)
        operator = self._try_assign_operator(ticket)

        if operator:
            tpl = SystemSetting.get('MSG_PROTOCOL_OPEN', 'Seu atendimento foi iniciado. Protocolo: {protocolo}')
        else:
            tpl = SystemSetting.get('MSG_QUEUE_WAIT', 'Você está na fila de espera. Protocolo: {protocolo}')

        final_txt = tpl.replace('{protocolo}', prot)
        final_txt = final_txt.replace('{nome}', contact.name or 'Cliente')
        final_txt = final_txt.replace('{fila}', ticket.queue.name if ticket.queue else 'Geral')
        final_txt = final_txt.replace('{atendente}', operator.name if operator else 'nossa equipe')

        if final_txt.strip():
            self.evo.send_text(contact.remote_jid, final_txt)
            self._save_message(ticket.id, final_txt, 'bot')

    def _save_message(self, ticket_id, content, sender, msg_type='text'):
        """Grava no banco e notifica o painel via SocketIO"""
        msg = Message(ticket_id=ticket_id, content=content, sender_type=sender, message_type=msg_type)
        db.session.add(msg)
        db.session.commit()
        socketio.emit('new_message', {
            'ticket_id': str(ticket_id), 'content': content, 'sender': sender, 'type': msg_type,
            'timestamp': msg.created_at.isoformat()
        }, namespace='/')