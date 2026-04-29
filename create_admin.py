from app import create_app
from app.extensions import db
from app.models import User

app = create_app()

def create():
    with app.app_context():
        email = "admin@crm.com"
        if User.query.filter_by(email=email).first():
            print("Admin já existe.")
            return

        u = User(name="Super Admin", email=email, is_admin=True, status="online")
        u.set_password("admin123") # <--- A sua senha aqui

        db.session.add(u)
        db.session.commit()
        print(f"Admin criado: {email} / admin123")

if __name__ == "__main__":
    create()
