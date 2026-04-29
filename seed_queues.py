from app import create_app
from app.extensions import db
from app.models import Queue

app = create_app()

def seed():
    with app.app_context():
        queues = ["Comercial", "Financeiro", "Suporte", "Geral"]
        
        for q_name in queues:
            exists = Queue.query.filter_by(name=q_name).first()
            if not exists:
                new_q = Queue(name=q_name)
                db.session.add(new_q)
                print(f"Fila criada: {q_name}")
            else:
                print(f"Fila já existe: {q_name}")
        
        db.session.commit()

if __name__ == "__main__":
    seed()
