from flask import request, jsonify
from . import bp_webhook
from app.tasks.webhooks import process_webhook_data

@bp_webhook.route('/evolution', methods=['POST'])
def receive_event():
    # Recebe o JSON da Evolution
    data = request.get_json()

    if not data:
        return jsonify({'error': 'No payload'}), 400

    # Dispara a tarefa para o Celery (Fire and Forget)
    # O .delay() é o segredo: ele envia pro Redis e retorna imediatamente
    process_webhook_data.delay(data)

    # Responde rápido para a Evolution não reenviar
    return jsonify({'status': 'queued'}), 200
