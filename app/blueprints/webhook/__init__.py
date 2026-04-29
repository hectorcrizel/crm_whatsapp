from flask import Blueprint

bp_webhook = Blueprint('webhook', __name__)

from . import routes
