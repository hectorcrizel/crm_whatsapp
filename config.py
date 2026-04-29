import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev_key_fallback')
    
    # Configuração do Banco de Dados
    SQLALCHEMY_DATABASE_URI = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASS')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Configuração do Celery
    CELERY_BROKER_URL = os.getenv('REDIS_URL')
    CELERY_RESULT_BACKEND = os.getenv('REDIS_URL')
    
   # Variavel env
    EVOLUTION_API_URL = os.getenv('EVOLUTION_API_URL')
    EVOLUTION_API_KEY = os.getenv('EVOLUTION_API_KEY')
    INSTANCE_NAME = os.getenv('INSTANCE_NAME')