# Arquivo: run_celery.py
from app import create_app

# Instancia a aplicação Flask
application = create_app()

# Pega a instância do Celery configurada dentro do create_app
celery_app = application.extensions["celery"]