from flask import Blueprint

bp_chat = Blueprint('chat', __name__)

from . import routes
