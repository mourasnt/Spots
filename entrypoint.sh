#!/bin/bash
set -e

echo "🚀 Iniciando aplicação Spots..."

# Função para lidar com sinais de término
cleanup() {
    echo "🛑 Encerrando processos..."
    kill -TERM "$flask_pid" "$main_pid" 2>/dev/null || true
    wait "$flask_pid" "$main_pid" 2>/dev/null || true
    exit 0
}

trap cleanup SIGTERM SIGINT

# Verifica se os arquivos de credenciais existem
if [ ! -f "credentials.json" ]; then
    echo "⚠️  AVISO: credentials.json não encontrado. O main.py pode não funcionar corretamente."
fi

if [ ! -f "credentials_sheets.json" ]; then
    echo "⚠️  AVISO: credentials_sheets.json não encontrado. O main.py pode não funcionar corretamente."
fi

if [ ! -f ".env" ]; then
    echo "⚠️  AVISO: .env não encontrado. Usando valores padrão."
fi

# Inicia o Flask (app.py) em background
echo "🌐 Iniciando servidor Flask na porta 5000..."
python app.py &
flask_pid=$!

# Aguarda alguns segundos para o Flask iniciar
sleep 3

# Inicia o monitor de emails (main.py) em background
echo "📧 Iniciando monitor de emails..."
python main.py &
main_pid=$!

# Exibe os PIDs dos processos
echo "✅ Aplicação iniciada!"
echo "   - Flask PID: $flask_pid"
echo "   - Monitor PID: $main_pid"
echo "   - Acesse: http://localhost:5000"

# Aguarda ambos os processos
wait "$flask_pid" "$main_pid"
