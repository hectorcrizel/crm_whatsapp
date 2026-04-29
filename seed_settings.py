import sys
from app import create_app, db
from app.models import SystemSetting


def seed_system_settings():
    """
    Script para popular configurações iniciais do sistema no Banco de Dados.
    """
    # Inicializa o contexto da aplicação Flask para ter acesso ao Banco
    app = create_app()

    with app.app_context():
        print("🌱 Iniciando a população das configurações do sistema...")

        # Lista de Configurações Padrão
        # (Chave, Valor, Descrição)
        settings = [
            (
                'EVOLUTION_API_URL',
                'http://sua-url-da-api:8080',
                'URL base da API Evolution (ex: http://localhost:8080)'
            ),
            (
                'EVOLUTION_API_KEY',
                'SUA_API_KEY_AQUI',
                'API Key Global da Evolution'
            ),
            (
                'INSTANCE_NAME',
                'instancia_padrao',
                'Nome da Instância conectada ao WhatsApp'
            )
        ]

        try:
            # Garante que as tabelas existam (caso não tenha rodado migration)
            db.create_all()

            for key, value, description in settings:
                # Usa o método estático .set() que já trata Update ou Insert
                SystemSetting.set(key, value, description)
                print(f"   ✅ Configuração '{key}' definida.")

            print("\n🎉 Sucesso! Todas as credenciais foram salvas no banco.")
            print("   Acesse o painel admin para verificar: /admin/settings")

        except Exception as e:
            print(f"\n❌ Erro ao popular banco: {e}")
            sys.exit(1)


if __name__ == '__main__':
    seed_system_settings()