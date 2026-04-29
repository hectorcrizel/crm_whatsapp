# --- 1. GEVENT PATCH (Mantenha sempre no topo) ---
from gevent import monkey
monkey.patch_all()

from flask import request
from app import create_app, socketio

app = create_app()

# --- 2. BLOCO DE DEBUG "X-RAY" (O Espião) ---
# Isso vai imprimir qualquer coisa que chegar no servidor
@app.before_request
def log_request_info():
    # Ignora arquivos estáticos (js, css) para não poluir o log
    if '/static/' in request.path:
        return

    print("\n" + "!"*60)
    print(f"📡 RECEBENDO REQUEST EXTRENO")
    print(f"URL: {request.method} {request.url}")
    print(f"QUEM MANDOU (IP): {request.remote_addr}")
    
    print("\n--- HEADERS ---")
    # Mostra os cabeçalhos (ajuda a ver se é JSON mesmo)
    for header, value in request.headers.items():
        print(f"{header}: {value}")
    
    print("\n--- BODY (CONTEÚDO) ---")
    try:
        # Tenta mostrar o conteúdo que veio
        data = request.get_data(as_text=True)
        print(data if data else "(Vazio)")
    except Exception as e:
        print(f"(Erro ao ler body: {e})")
        
    print("!"*60 + "\n")
# ------------------------------------------------

if __name__ == '__main__':
    print("\n--- SERVIDOR RODANDO NO MODO ESCUTA TOTAL ---")
    print("Aguardando conexões em 0.0.0.0:5000...")
    
    # allow_unsafe_werkzeug=True permite rodar em ambientes de dev sem reclamar
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)
