import uuid
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app.extensions import db

# --- TABELA DE ASSOCIAÇÃO: Usuários <-> Filas ---
user_queues = db.Table('user_queues',
                       db.Column('user_id', UUID(as_uuid=True), db.ForeignKey('users.id'), primary_key=True),
                       db.Column('queue_id', UUID(as_uuid=True), db.ForeignKey('queues.id'), primary_key=True)
                       )


# --- 1. Usuários ---
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = db.Column(db.String(150), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='offline')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    queues = db.relationship('Queue', secondary=user_queues, backref=db.backref('operators', lazy='dynamic'))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# --- 2. Filas ---
class Queue(db.Model):
    __tablename__ = 'queues'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(7), default='#CCCCCC')

    # Failover
    failover_queue_id = db.Column(UUID(as_uuid=True), db.ForeignKey('queues.id'), nullable=True)
    failover_target = db.relationship('Queue', remote_side=[id], backref='backup_source')
    failover_numbers = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# --- 3. Contatos ---
class Contact(db.Model):
    __tablename__ = 'contacts'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    remote_jid = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(150))
    profile_pic_url = db.Column(db.Text)
    email = db.Column(db.String(150))
    custom_vars = db.Column(JSONB)

    # Rastreia em qual menu o cliente está (Navegação)
    current_menu_id = db.Column(db.Integer, db.ForeignKey('bot_menu_options.id'), nullable=True)
    
    # Rastreia o estado da conversa e dados do Desk Manager
    conversation_state = db.Column(db.String(50), nullable=True)
    desk_context = db.Column(JSONB, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# --- 4. Tickets ---
class Ticket(db.Model):
    __tablename__ = 'tickets'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id = db.Column(UUID(as_uuid=True), db.ForeignKey('contacts.id'), nullable=False)
    contact = db.relationship('Contact', backref='tickets', foreign_keys=[contact_id])

    queue_id = db.Column(UUID(as_uuid=True), db.ForeignKey('queues.id'), nullable=True)
    queue = db.relationship('Queue', backref='tickets')

    operator_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=True)
    operator = db.relationship('User', backref='tickets')

    status = db.Column(db.String(20), default='open')
    external_protocol = db.Column(db.String(50), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = db.Column(db.DateTime)


# --- 5. Mensagens ---
class Message(db.Model):
    __tablename__ = 'messages'

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = db.Column(UUID(as_uuid=True), db.ForeignKey('tickets.id'), nullable=False)
    ticket = db.relationship('Ticket', backref='messages')
    sender_type = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text)
    message_type = db.Column(db.String(20), default='text')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# --- 6. Configurações ---
class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(200))

    @staticmethod
    def get(key, default=None):
        try:
            return SystemSetting.query.get(key).value
        except:
            return default

    @staticmethod
    def set(key, value):
        s = SystemSetting.query.get(key)
        if not s: s = SystemSetting(key=key)
        s.value = value
        db.session.add(s);
        db.session.commit()


# --- 7. Respostas Rápidas ---
class QuickAnswer(db.Model):
    __tablename__ = 'quick_answers'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    shortcut = db.Column(db.String(50))
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# --- 8. BOT: Menu Avançado ---
class BotMenuOption(db.Model):
    __tablename__ = 'bot_menu_options'

    id = db.Column(db.Integer, primary_key=True)

    # Hierarquia
    parent_id = db.Column(db.Integer, db.ForeignKey('bot_menu_options.id'), nullable=True)
    children = db.relationship('BotMenuOption',
                               backref=db.backref('parent', remote_side=[id]),
                               cascade="all, delete-orphan"
                               )

    digit = db.Column(db.String(10), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Ação Final
    queue_id = db.Column(UUID(as_uuid=True), db.ForeignKey('queues.id'), nullable=True)
    queue = db.relationship('Queue')

    # Configurações
    open_desk_ticket = db.Column(db.Boolean, default=True)
    generate_protocol = db.Column(db.Boolean, default=True)
    response_message = db.Column(db.Text, nullable=True)

    # NOVO: Flag para menu oculto/exclusivo VIP
    is_vip_only = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<Menu {self.digit} - {self.title}>"


# --- 9. BOT: Regras VIP ---
class BotSpecialRule(db.Model):
    __tablename__ = 'bot_special_rules'

    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(50), nullable=False)

    # Destino 1: Fila
    queue_id = db.Column(UUID(as_uuid=True), db.ForeignKey('queues.id'), nullable=True)
    queue = db.relationship('Queue')

    # Destino 2: Menu Específico (Submenu VIP)
    special_menu_id = db.Column(db.Integer, db.ForeignKey('bot_menu_options.id'), nullable=True)
    special_menu = db.relationship('BotMenuOption')

    def __repr__(self):
        return f"<VIP Rule: {self.keyword}>"