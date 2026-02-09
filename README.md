# Spots - Sistema de Monitoramento e Configuração

Sistema para monitoramento de emails de leilão da Shopee com notificações via WhatsApp através da Evolution API.

## 🚀 Deploy no Servidor

### Pré-requisitos

- Docker e Docker Compose instalados
- Arquivos de credenciais do Google:
  - `credentials.json` (Gmail API)
  - `credentials_sheets.json` (Google Sheets API)
- Arquivo `evolution.env` configurado

### Passo a Passo

1. **Clone ou faça upload dos arquivos para o servidor**

2. **Configure as variáveis de ambiente**
   
   Copie o arquivo de exemplo e edite com suas credenciais:
   ```bash
   cp .env.example .env
   nano .env
   ```

3. **Certifique-se de que os arquivos de credenciais existem:**
   - `credentials.json`
   - `credentials_sheets.json`
   - `evolution.env`
   - `origens_config.json`

4. **Inicie os containers**
   ```bash
   docker-compose up -d
   ```

5. **Verifique os logs**
   ```bash
   docker-compose logs -f spots_app
   ```

6. **Acesse a interface web**
   ```
   http://seu-servidor:5000
   ```

### 🔐 Credenciais Padrão

- **Usuário:** admin
- **Senha:** admin123

⚠️ **IMPORTANTE:** Altere as credenciais no arquivo `.env` antes de usar em produção!

## 📦 Estrutura de Volumes

O docker-compose monta os seguintes volumes:

- `credentials.json` - Credenciais Gmail (somente leitura)
- `credentials_sheets.json` - Credenciais Sheets (somente leitura)
- `evolution.env` - Config Evolution API (somente leitura)
- `origens_config.json` - Config de origens (leitura/escrita)
- `token.json` - Token OAuth Gmail (persistido)
- `viagens.db` - Banco de dados SQLite (persistido)

## 🛠️ Comandos Úteis

### Ver logs em tempo real
```bash
docker-compose logs -f spots_app
```

### Reiniciar apenas a aplicação
```bash
docker-compose restart spots_app
```

### Rebuild completo (após alterações no código)
```bash
docker-compose build --no-cache spots_app
docker-compose up -d
```

### Parar todos os serviços
```bash
docker-compose down
```

### Parar e remover volumes (cuidado!)
```bash
docker-compose down -v
```

## 🔄 Atualização

Para atualizar a aplicação:

```bash
# Pull das alterações
git pull

# Rebuild da imagem
docker-compose build spots_app

# Restart do container
docker-compose up -d
```

## 📊 Monitoramento

A aplicação expõe:
- **Porta 5000:** Interface web de configuração
- **Health check:** Acessível via interface web

## 🔧 Troubleshooting

### OAuth do Gmail não funciona

O container precisa fazer o fluxo OAuth na primeira execução. Se necessário:

1. Execute localmente primeiro para gerar o `token.json`
2. Depois copie o arquivo para o servidor

### Mudanças no config não são aplicadas instantaneamente

O file watcher detecta mudanças em menos de 1 segundo. Se não funcionar:

```bash
docker-compose restart spots_app
```

### Verificar se o monitor está rodando

```bash
docker-compose exec spots_app ps aux
```

Deve mostrar dois processos Python: `app.py` e `main.py`

## 🌐 Portas Utilizadas

- **5000:** Spots App (Interface Web)
- **8080:** Evolution API
- **5432:** PostgreSQL (não exposto externamente)
- **6379:** Redis (não exposto externamente)

## 📝 Desenvolvimento Local

Para desenvolver localmente:

```bash
# Crie um virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# Instale dependências
pip install -r requirements.txt

# Inicie Flask
python app.py

# Em outro terminal, inicie o monitor
python main.py
```

## 🏗️ Build Manual da Imagem

Para fazer build e push da imagem:

```bash
docker build -t willianmoura3zx/spots:1.0 .
docker push willianmoura3zx/spots:1.0
```

## 📄 Licença

Uso interno 3ZX © 2026
