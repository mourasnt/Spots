# Dockerfile para aplicação Spots
FROM python:3.11-slim

# Define o diretório de trabalho
WORKDIR /app

# Instala dependências do sistema necessárias
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia o arquivo de requisitos
COPY requirements.txt .

# Instala as dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia todos os arquivos da aplicação
COPY . .

# Cria diretório para templates se não existir
RUN mkdir -p templates

# Expõe a porta do Flask
EXPOSE 5000

# Torna o script de entrada executável
RUN chmod +x /app/entrypoint.sh

# Define o script de entrada
ENTRYPOINT ["/app/entrypoint.sh"]
