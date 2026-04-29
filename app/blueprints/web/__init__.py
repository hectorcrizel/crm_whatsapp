from flask import Blueprint

# template_folder='../../templates' diz para o Flask buscar o HTML na raiz app/templates
bp_web = Blueprint('web', __name__)

from . import routes
