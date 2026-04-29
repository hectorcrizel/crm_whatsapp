from flask import render_template, redirect, url_for
from flask_login import login_required, current_user
from . import bp_web

@bp_web.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('web.chat'))
    return render_template('login.html')

@bp_web.route('/chat')
@login_required 
def chat():
    return render_template('index.html')
