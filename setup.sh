#!/bin/bash

# Script de setup inicial para servidor
# Execute este script na primeira instalação

set -e

echo "=========================================="
echo "🚀 Setup Inicial - Spots Application"
echo "=========================================="
echo ""

# Verifica se o Docker está instalado
if ! command -v docker &> /dev/null; then
    echo "❌ Docker não encontrado. Por favor, instale o Docker primeiro."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose não encontrado. Por favor, instale o Docker Compose primeiro."
    exit 1
fi

echo "✅ Docker e Docker Compose encontrados"
echo ""

# Verifica arquivos necessários
echo "📋 Verificando arquivos necessários..."
echo ""

MISSING_FILES=0

if [ ! -f "credentials.json" ]; then
    echo "❌ credentials.json não encontrado"
    MISSING_FILES=1
else
    echo "✅ credentials.json"
fi

if [ ! -f "credentials_sheets.json" ]; then
    echo "❌ credentials_sheets.json não encontrado"
    MISSING_FILES=1
else
    echo "✅ credentials_sheets.json"
fi

if [ ! -f "evolution.env" ]; then
    echo "❌ evolution.env não encontrado"
    MISSING_FILES=1
else
    echo "✅ evolution.env"
fi

# Verifica .env
if [ ! -f ".env" ]; then
    echo "⚠️  .env não encontrado, criando a partir do .env.example..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "✅ .env criado. EDITE ESTE ARQUIVO com suas credenciais!"
        echo ""
        echo "Execute: nano .env"
        echo ""
    else
        echo "❌ .env.example não encontrado"
        MISSING_FILES=1
    fi
else
    echo "✅ .env"
fi

# Verifica origens_config.json
if [ ! -f "origens_config.json" ]; then
    echo "⚠️  origens_config.json não encontrado, criando arquivo vazio..."
    echo '{"origens_incluidas": []}' > origens_config.json
    echo "✅ origens_config.json criado"
else
    echo "✅ origens_config.json"
fi

echo ""

if [ $MISSING_FILES -eq 1 ]; then
    echo "❌ Arquivos obrigatórios estão faltando!"
    echo ""
    echo "Por favor, adicione os arquivos faltantes e execute este script novamente."
    exit 1
fi

echo "=========================================="
echo "✅ Todos os arquivos necessários encontrados"
echo "=========================================="
echo ""

# Pergunta se deve iniciar os containers
read -p "Deseja iniciar os containers agora? (s/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Ss]$ ]]; then
    echo ""
    echo "🐳 Iniciando containers..."
    echo ""
    
    docker-compose up -d
    
    echo ""
    echo "=========================================="
    echo "✅ Setup concluído com sucesso!"
    echo "=========================================="
    echo ""
    echo "📊 Status dos containers:"
    docker-compose ps
    echo ""
    echo "🌐 Acesse a interface em: http://localhost:5000"
    echo "🔐 Credenciais padrão:"
    echo "   Usuário: admin"
    echo "   Senha: admin123"
    echo ""
    echo "📝 Para ver os logs:"
    echo "   docker-compose logs -f spots_app"
    echo ""
else
    echo ""
    echo "Setup preparado. Execute quando estiver pronto:"
    echo "   docker-compose up -d"
    echo ""
fi
