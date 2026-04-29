from flask import Flask
from celery import Celery, Task
from celery.schedules import crontab
from config import Config
from app.extensions import db, migrate, login_manager, socketio
from app.models import User

def create_app(config_class=Config):
    # --- MUDANÇA CRÍTICA AQUI ---
    # Mudamos o nome da variável de 'app' para 'flask_app'
    # para não conflitar com o 'import app' no final.
    flask_app = Flask(__name__)
    flask_app.config.from_object(config_class)

    # Inicializar Extensões (Use flask_app agora)
    db.init_app(flask_app)
    migrate.init_app(flask_app, db)
    login_manager.init_app(flask_app)

    # SocketIO
    socketio.init_app(flask_app, message_queue=flask_app.config.get('CELERY_BROKER_URL'), async_mode='gevent')

    # Configuração do Login
    login_manager.login_view = 'web.index'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(user_id)

    # Mapeia as variáveis do config
    flask_app.config.from_mapping(
        CELERY=dict(
            broker_url=flask_app.config['CELERY_BROKER_URL'],
            result_backend=flask_app.config['CELERY_RESULT_BACKEND'],
            task_ignore_result=True,
            timezone='America/Sao_Paulo',
        ),
    )

    # Inicializa o Celery
    celery = celery_init_app(flask_app)

    # --- AGENDAMENTO (BEAT) ---
    celery.conf.beat_schedule = {
        'sync-contacts-hourly': {
            'task': 'app.tasks.sync.sync_whatsapp_contacts',
            'schedule': crontab(minute=0),
        },
    }

    # Registrar Blueprints
    from app.blueprints.auth import bp_auth
    flask_app.register_blueprint(bp_auth, url_prefix='/auth')

    from app.blueprints.webhook import bp_webhook
    flask_app.register_blueprint(bp_webhook, url_prefix='/webhook')

    from app.blueprints.chat import bp_chat
    flask_app.register_blueprint(bp_chat, url_prefix='/chat')

    from app.blueprints.web import bp_web
    flask_app.register_blueprint(bp_web)

    from app.blueprints.admin import bp_admin
    flask_app.register_blueprint(bp_admin)

    # === AQUI ESTAVA O ERRO ===
    # Ao importar 'app.tasks...', a variável 'app' virava o módulo.
    # Como mudamos o nome da instância para 'flask_app', não há mais conflito.
    import app.tasks.sync

    # Retorna o OBJETO Flask correto
    return flask_app


def celery_init_app(app: Flask) -> Celery:
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config["CELERY"])
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app