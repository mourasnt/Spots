from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
import json
import os
from datetime import datetime
from werkzeug.security import check_password_hash, generate_password_hash

# Carrega variáveis de ambiente
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['WTF_CSRF_ENABLED'] = True
csrf = CSRFProtect(app)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'origens_config.json')

# Configuração do Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor, faça login para acessar esta página.'
login_manager.login_message_category = 'warning'

# Classe de usuário simples
class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

def load_origens():
    if not os.path.exists(CONFIG_PATH):
        return []
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('origens_incluidas', [])
    except Exception as e:
        print(f"Erro ao carregar origens: {e}")
        return []

def save_origens(origens):
    try:
        # Remove duplicatas e strings vazias
        origens_limpas = []
        seen = set()
        for o in origens:
            o_clean = o.strip()
            if o_clean and o_clean not in seen:
                origens_limpas.append(o_clean)
                seen.add(o_clean)
        
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump({'origens_incluidas': origens_limpas}, f, ensure_ascii=False, indent=2)
        return True, len(origens_limpas)
    except Exception as e:
        print(f"Erro ao salvar origens: {e}")
        return False, 0

# Rota de login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('config_origens'))
    
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        
        # Credenciais do .env
        valid_username = os.getenv('ADMIN_USERNAME', 'admin')
        valid_password = os.getenv('ADMIN_PASSWORD', 'admin123')
        
        if username == valid_username and password == valid_password:
            user = User(username)
            login_user(user)
            flash('Login realizado com sucesso!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page if next_page else url_for('config_origens'))
        else:
            flash('Usuário ou senha incorretos.', 'error')
    
    return render_template('login.html')

# Rota de logout
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logout realizado com sucesso.', 'success')
    return redirect(url_for('login'))

# Rota principal - Config de origens
@app.route('/', methods=['GET', 'POST'])
@login_required
def config_origens():
    origens = load_origens()
    if request.method == 'POST':
        novas_origens = request.form.get('origens', '')
        lista = [o.strip() for o in novas_origens.split('\n') if o.strip()]
        
        success, count = save_origens(lista)
        if success:
            flash(f'Lista de origens atualizada com sucesso! {count} origem(ns) salva(s).', 'success')
        else:
            flash('Erro ao salvar a lista de origens.', 'error')
        
        return redirect(url_for('config_origens'))
    
    return render_template('config.html', origens=origens)

# API Endpoints
@app.route('/api/origens', methods=['GET'])
@login_required
def api_get_origens():
    """Retorna lista de origens em JSON"""
    origens = load_origens()
    return jsonify({
        'success': True,
        'origens': origens,
        'count': len(origens)
    })

@app.route('/api/origens', methods=['POST'])
@login_required
def api_add_origem():
    """Adiciona uma nova origem"""
    data = request.get_json()
    nova_origem = data.get('origem', '').strip()
    
    if not nova_origem:
        return jsonify({'success': False, 'error': 'Origem vazia'}), 400
    
    origens = load_origens()
    
    if nova_origem in origens:
        return jsonify({'success': False, 'error': 'Origem já existe'}), 400
    
    origens.append(nova_origem)
    success, count = save_origens(origens)
    
    if success:
        return jsonify({
            'success': True,
            'message': 'Origem adicionada com sucesso',
            'origens': origens,
            'count': count
        })
    else:
        return jsonify({'success': False, 'error': 'Erro ao salvar'}), 500

@app.route('/api/origens/<int:index>', methods=['DELETE'])
@login_required
def api_delete_origem(index):
    """Remove uma origem pelo índice"""
    origens = load_origens()
    
    if index < 0 or index >= len(origens):
        return jsonify({'success': False, 'error': 'Índice inválido'}), 400
    
    origem_removida = origens.pop(index)
    success, count = save_origens(origens)
    
    if success:
        return jsonify({
            'success': True,
            'message': f'Origem "{origem_removida}" removida',
            'origens': origens,
            'count': count
        })
    else:
        return jsonify({'success': False, 'error': 'Erro ao salvar'}), 500

@app.route('/api/status', methods=['GET'])
@login_required
def api_status():
    """Retorna status da aplicação"""
    try:
        origens = load_origens()
        config_mtime = os.path.getmtime(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else None
        
        return jsonify({
            'success': True,
            'config_file': CONFIG_PATH,
            'origens_count': len(origens),
            'last_modified': datetime.fromtimestamp(config_mtime).isoformat() if config_mtime else None,
            'user': current_user.id if current_user.is_authenticated else None
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    # Configurações de desenvolvimento/produção via variáveis de ambiente
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', '5000'))
    
    print(f"🚀 Servidor Flask iniciando em http://{host}:{port}")
    print(f"   Debug mode: {debug_mode}")
    print(f"   Admin user: {os.getenv('ADMIN_USERNAME', 'admin')}")
    
    app.run(debug=debug_mode, host=host, port=port)
