from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
import os
import redis
from datetime import datetime

# Carrega variáveis de ambiente
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['WTF_CSRF_ENABLED'] = True
csrf = CSRFProtect(app)

# Configuração do Redis (Apontando para o spots_redis)
REDIS_URL = os.getenv('REDIS_URL', 'redis://spots_redis:6379/0')
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# Chave no Redis para a lista de origens
REDIS_ORIGENS_KEY = 'spots:origens'

# Configuração do Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor, faça login para acessar esta página.'
login_manager.login_message_category = 'warning'

class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

def load_origens():
    """Carrega as origens do Redis (Lista)"""
    try:
        return redis_client.lrange(REDIS_ORIGENS_KEY, 0, -1)
    except redis.RedisError as e:
        print(f"Erro ao acessar Redis: {e}")
        return []

def save_origens(origens):
    """Salva a lista completa de origens no Redis"""
    try:
        # Remove duplicatas e strings vazias preservando a ordem
        origens_limpas = []
        seen = set()
        for o in origens:
            o_clean = o.strip()
            if o_clean and o_clean not in seen:
                origens_limpas.append(o_clean)
                seen.add(o_clean)
        
        # Pipeline para transação atômica
        pipeline = redis_client.pipeline()
        pipeline.delete(REDIS_ORIGENS_KEY)
        if origens_limpas:
            pipeline.rpush(REDIS_ORIGENS_KEY, *origens_limpas)
        pipeline.execute()
        
        return True, len(origens_limpas)
    except redis.RedisError as e:
        print(f"Erro ao salvar no Redis: {e}")
        return False, 0

# Rota de login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('config_origens'))
    
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        
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

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logout realizado com sucesso.', 'success')
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@login_required
def config_origens():
    origens = load_origens()
    if request.method == 'POST':
        novas_origens = request.form.get('origens', '')
        lista = [o.strip() for o in novas_origens.split('\n') if o.strip()]
        
        success, count = save_origens(lista)
        if success:
            flash(f'Lista de origens atualizada no Redis! {count} origem(ns) salva(s).', 'success')
        else:
            flash('Erro ao salvar a lista de origens.', 'error')
        
        return redirect(url_for('config_origens'))
    
    return render_template('config.html', origens=origens)

# API Endpoints
@app.route('/api/origens', methods=['GET'])
@login_required
def api_get_origens():
    origens = load_origens()
    return jsonify({'success': True, 'origens': origens, 'count': len(origens)})

@app.route('/api/origens', methods=['POST'])
@login_required
def api_add_origem():
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
        return jsonify({'success': True, 'message': 'Origem adicionada', 'origens': origens, 'count': count})
    else:
        return jsonify({'success': False, 'error': 'Erro ao salvar'}), 500

@app.route('/api/origens/<int:index>', methods=['DELETE'])
@login_required
def api_delete_origem(index):
    origens = load_origens()
    if index < 0 or index >= len(origens):
        return jsonify({'success': False, 'error': 'Índice inválido'}), 400
    
    origem_removida = origens.pop(index)
    success, count = save_origens(origens)
    
    if success:
        return jsonify({'success': True, 'message': f'Origem "{origem_removida}" removida', 'origens': origens, 'count': count})
    else:
        return jsonify({'success': False, 'error': 'Erro ao salvar'}), 500

@app.route('/api/status', methods=['GET'])
@login_required
def api_status():
    try:
        redis_status = redis_client.ping()
        origens = load_origens()
        processed_count = redis_client.scard('spots:processed_emails')
        
        return jsonify({
            'success': True,
            'database': 'Redis',
            'redis_connected': redis_status,
            'origens_count': len(origens),
            'emails_processed': processed_count,
            'user': current_user.id if current_user.is_authenticated else None
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', '5000'))
    
    print(f"🚀 Servidor Web Flask iniciando...")
    app.run(debug=debug_mode, host=host, port=port)