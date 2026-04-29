from run import app
from app.extensions import db
from app.models import Ticket, Message, Contact

def limpar_banco():
    with app.app_context():
        try:
            print("A iniciar a limpeza cirúrgica do banco de dados...")
            
            # A ordem é importante: primeiro as mensagens, depois os tickets, depois os contactos
            apagadas_msg = db.session.query(Message).delete()
            apagados_tck = db.session.query(Ticket).delete()
            apagados_cnt = db.session.query(Contact).delete()
            
            db.session.commit()
            
            print("\n✅ Limpeza concluída com sucesso!")
            print(f"  -> Mensagens eliminadas: {apagadas_msg}")
            print(f"  -> Tickets eliminados: {apagados_tck}")
            print(f"  -> Contactos eliminados: {apagados_cnt}")
            print("\nOs seus Utilizadores (Admin/Operadores), Filas e Configurações foram mantidos.")
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ Ocorreu um erro ao limpar o banco de dados: {e}")

if __name__ == "__main__":
    limpar_banco()
