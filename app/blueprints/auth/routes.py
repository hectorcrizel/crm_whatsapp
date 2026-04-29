from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app.extensions import db  # <--- IMPORTANTE: Adicionado para salvar no banco
from . import bp_auth


@bp_auth.route('/login', methods=['GET', 'POST'])
def login():
    # 1. Se o usuário já estiver logado, manda pro chat
    if current_user.is_authenticated:
        return redirect(url_for('chat.index'))

    # 2. Se for Abertura de Página (GET), só mostra o HTML
    if request.method == 'GET':
        return render_template('login.html')

    # 3. Se for envio de dados (POST)
    data = None

    # Verifica se veio JSON (API/Fetch) ou Formulário Clássico
    if request.is_json:
        data = request.get_json()
    else:
        # Fallback para formulário normal, caso mude o front no futuro
        data = request.form

    email = data.get('email')
    password = data.get('password')

    user = User.query.filter_by(email=email).first()

    if user and user.check_password(password):
        login_user(user)
        # Resposta JSON para o seu Javascript do Frontend
        return jsonify({'status': 'success', 'redirect': url_for('chat.index')})

    # Se errou a senha
    return jsonify({'error': 'Credenciais inválidas'}), 401


@bp_auth.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    # Opcional: Definir como offline ao sair
    current_user.status = 'offline'
    db.session.commit()

    logout_user()
    flash('Você saiu do sistema.', 'info')

    # Redireciona para o login
    return redirect(url_for('auth.login'))


@bp_auth.route('/me', methods=['GET'])
@login_required
def get_current_user():
    return jsonify({
        'id': current_user.id,
        'name': current_user.name,
        'email': current_user.email,
        'is_admin': current_user.is_admin,
        'status': current_user.status
    })


# --- NOVA ROTA: ALTERAR STATUS ---
@bp_auth.route('/status', methods=['POST'])
@login_required
def set_status():
    """
    Recebe {status: 'online'|'busy'|'offline'} do Javascript
    e atualiza no banco de dados.
    """
    data = request.get_json()
    new_status = data.get('status')

    # Validação simples para evitar valores estranhos
    if new_status in ['online', 'offline', 'busy']:
        current_user.status = new_status
        db.session.commit()
        return jsonify({'success': True, 'new_status': new_status})

    return jsonify({'error': 'Status inválido'}), 400