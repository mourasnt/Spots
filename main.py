import os.path
import datetime
import random
import time
import base64
import sqlite3
import json
import requests
import threading
import traceback
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import timedelta, timezone
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo
import gspread

# --- Configurações ---
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly'] # SÓ PRECISAMOS DE .readonly AGORA
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.json'
DATABASE_FILE = 'viagens.db'
CONFIG_FILE = 'origens_config.json'

# Variável global thread-safe para origens incluídas
origens_incluidas = []
config_lock = threading.Lock()

# --- Filtros ---
remetente_procurado = "operacao@3zx.com.br"
assunto_procurado = "ATENÇÃO: a sua transportadora tem uma viagem de leilão com a Shopee"
minutos_para_filtrar = 240
filtro_de_tempo_api = "3d" # Busca e-mails dos últimos 2 dias (API)
agora_utc = datetime.datetime.now(timezone.utc)
# Filtro local: E-mails devem ser mais novos que 60 min atrás
limite_de_tempo = agora_utc - timedelta(minutes=minutos_para_filtrar)

# --- File Watcher para reload instantâneo do config ---
class ConfigFileHandler(FileSystemEventHandler):
    """Handler para detectar mudanças no arquivo de configuração"""
    def on_modified(self, event):
        if event.src_path.endswith('origens_config.json'):
            load_config()

def load_config():
    """Carrega configuração do arquivo JSON com thread-safety"""
    global origens_incluidas
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            with config_lock:
                origens_incluidas = data.get('origens_incluidas', [])
            print(f"✓ Configuração recarregada: {len(origens_incluidas)} origens ativas")
    except Exception as e:
        print(f"Erro ao ler {CONFIG_FILE}: {e}")
        with config_lock:
            origens_incluidas = []

def setup_database():
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS leiloes (
            gmail_message_id TEXT PRIMARY KEY,
            hora_recebida TIMESTAMP,
            assunto TEXT,
            nome_viagem TEXT,
            numero_viagem TEXT,
            estacao_partida TEXT,
            estacao_chegada TEXT,
            eta_origem TEXT,
            veiculo TEXT
        )
        ''')
        conn.commit()
        conn.close()
        print(f"Base de dados '{DATABASE_FILE}' pronta.")
    except Exception as e:
        print(f"Erro ao configurar a base de dados: {e}")

def get_existing_ids(conn):
    """Lê o banco de dados e retorna um SET com todos os IDs já processados."""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT gmail_message_id FROM leiloes")
        # Usamos um 'set comprehension' para performance máxima de lookup
        ids_existentes = {row[0] for row in cursor.fetchall()}
        print(f"Encontrados {len(ids_existentes)} e-mails já processados no banco de dados.")
        return ids_existentes
    except Exception as e:
        print(f"Erro ao ler IDs existentes: {e}")
        return set() # Retorna um set vazio em caso de erro

def get_full_email_body(payload):
    """Extrai o corpo do e-mail (HTML ou Texto)."""
    body_data_plain = None
    body_data_html = None
    if 'parts' in payload:
        for part in payload['parts']:
            mimeType = part.get('mimeType')
            if mimeType == 'text/plain' and 'data' in part['body']:
                body_data_plain = part['body']['data']
                break 
            elif mimeType == 'text/html' and 'data' in part['body']:
                body_data_html = part['body']['data'] 
    elif 'data' in payload['body']:
        if payload.get('mimeType') == 'text/plain':
            body_data_plain = payload['body']['data']
        elif payload.get('mimeType') == 'text/html':
            body_data_html = payload['body']['data']
        else:
            body_data_plain = payload['body']['data']

    body_to_decode = body_data_html if body_data_html else body_data_plain # Prefere HTML

    if body_to_decode:
        dados_descodificados = base64.urlsafe_b64decode(body_to_decode.encode('ASCII'))
        return dados_descodificados.decode('utf-8')
    return None

def obter_dimensionamento():
    creds_path = "credentials_sheets.json"
    spreadsheet_id = "18a1S-ITSS6VATOCoJRZDx02pivQB6DZeNfi7SW-BKH8"
    worksheet_name = "DIMENSIONAMENTO"
    header_row_num = 1

    try:
        print("Autenticando no Google Sheets...")
        SCOPES_SHEETS = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        creds_sheets = ServiceAccountCredentials.from_service_account_file(creds_path, scopes=SCOPES_SHEETS)
        client = gspread.authorize(creds_sheets)

        print(f"Abrindo planilha: {spreadsheet_id} | Aba: {worksheet_name}")
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(worksheet_name)

        print(f"Buscando cabeçalho na linha {header_row_num}...")
        headers = worksheet.row_values(header_row_num)

        # Encontrar os índices das colunas
        try:
            rota_col_index = headers.index('ROTA') + 1
            regular_col_index = headers.index('Rota') + 1
        except ValueError as e:
            print(f"Erro: Coluna obrigatória não encontrada. Verifique o cabeçalho. Detalhe: {e}")
            return None

        # Baixar dados das colunas
        print("Baixando dados do Sheets...")
        rota_data = worksheet.col_values(rota_col_index)[header_row_num:]
        regular_data = worksheet.col_values(regular_col_index)[header_row_num:]
        print(f"Processando {len(rota_data)} linhas de dados...")

        # Criar uma lista única com dicionários contendo rota e status
        rotas_com_status = []
        for i in range(len(rota_data)):
            rota_item = rota_data[i] if i < len(rota_data) else ""
            regular_item = regular_data[i] if i < len(regular_data) else ""
            
            rotas_com_status.append({
                'rota': rota_item.strip(),
                'status': regular_item.strip()
            })

        return rotas_com_status

    except gspread.exceptions.APIError as e:
        print(f"Erro de API do Google: {e}. Verifique cotas e permissões.")
        return None
    except Exception as e:
        print(f"Erro inesperado ao obter dados do Sheets: {e}")
        return None

def envia_mensagem(MESSAGE):
    API_URL = "http://127.0.0.1:8080" 
    INSTANCE_NAME = "Spots" 
    API_KEY = "Senh@Segura123"

    DESTINATION_NUMBER = "120363421560093254@g.us"
    # DESTINATION_NUMBER = "120363421560093254@g.us" 

    # Monta a URL completa do endpoint para enviar texto
    url_endpoint = f"{API_URL}/message/sendText/{INSTANCE_NAME}"

    # Monta o "payload" (corpo da requisição) em formato de dicionário Python
    payload = {
        "number": DESTINATION_NUMBER,
        "options": {
            "delay": 1200,          # Delay opcional em milissegundos
            "presence": "composing" # Simula "digitando..." (opcional)
        },
        "text": MESSAGE
    }

    # Monta os "headers" (cabeçalhos) com a autenticação
    headers = {
        "Content-Type": "application/json",
        "apikey": API_KEY
    }

    # --- Envia a requisição POST ---
    print(f"Enviando mensagem para: {DESTINATION_NUMBER}...")

    try:
        # Usamos json.dumps() para converter o dicionário Python em uma string JSON
        response = requests.post(url_endpoint, headers=headers, data=json.dumps(payload))

        # Lança um erro se a requisição falhar (status code 4xx ou 5xx)
        response.raise_for_status() 

        print("✅ Mensagem enviada com sucesso!")
        return True

    except requests.exceptions.HTTPError as errh:
        print(f"❌ Erro HTTP: {errh}")
        print(f"Detalhes: {errh.response.text}")
        return False
    except requests.exceptions.ConnectionError as errc:
        print(f"❌ Erro de Conexão: Não foi possível conectar à API em {API_URL}.")
        print(f"Verifique se o servidor Evolution está rodando e acessível.")
        return False
    except requests.exceptions.Timeout as errt:
        print(f"❌ Erro de Timeout: {errt}")
        return False
    except requests.exceptions.RequestException as err:
        print(f"❌ Erro na Requisição: {err}")
        return False

def main():
    setup_database()

    # Conectar ao DB uma vez no início
    conn = sqlite3.connect(DATABASE_FILE)
    ids_ja_processados = get_existing_ids(conn)
    conn.close() # Fechamos a conexão por enquanto

    while True:
        print(f"DEBUG: Início do loop principal. token existe={os.path.exists(TOKEN_FILE)}, credentials existe={os.path.exists(CREDENTIALS_FILE)}")
        # --- BLOCO DE AUTENTICAÇÃO CORRIGIDO ---
        creds = None
        # O arquivo token.json armazena os tokens de acesso e atualização do usuário.
        if os.path.exists(TOKEN_FILE):
            try:
                creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
            except Exception as e:
                print(f"Erro ao ler {TOKEN_FILE}: {e}. Removendo arquivo corrompido.")
                os.remove(TOKEN_FILE)
                creds = None

        # Se não houver credenciais (válidas), deixa o usuário fazer login.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    print("Token expirado, tentando atualizar...")
                    creds.refresh(Request())
                except Exception as e:
                    print(f"Não foi possível atualizar o token: {e}")
                    print("Por favor, autentique-se novamente.")
                    if os.path.exists(TOKEN_FILE):
                        os.remove(TOKEN_FILE) # Remove o token inválido
                    creds = None # Força nova autenticação
            else:
                # Se não existe token.json ou o refresh falhou,
                # inicia o fluxo de autenticação do zero.
                try:
                    if not os.path.exists(CREDENTIALS_FILE):
                        print(f"ERRO FATAL: Arquivo '{CREDENTIALS_FILE}' não encontrado.")
                        print("Faça o download do JSON de credenciais do Google Cloud Console.")
                        print("Continuando em loop para nova tentativa em 60s...")
                        time.sleep(60)
                        continue

                    print(f"Arquivo '{TOKEN_FILE}' não encontrado ou inválido. Iniciando nova autenticação...")

                    # Em containers, o fluxo interativo pode não funcionar.
                    if os.environ.get('GMAIL_NO_INTERACTIVE', 'false').lower() in ['1','true','yes']:
                        print('Modo NÃO interativo ativo: não será aberto browser. Verifique token.json manualmente.')
                        time.sleep(60)
                        continue

                    flow = InstalledAppFlow.from_client_secrets_file(
                        CREDENTIALS_FILE, SCOPES)
                    # port=0 faz a biblioteca encontrar uma porta livre
                    creds = flow.run_local_server(port=0) 
                    print("Autenticação realizada com sucesso!")
                except Exception as e:
                    print(f"Erro durante o fluxo de autenticação: {e}")
                    if os.environ.get('GMAIL_NO_INTERACTIVE', 'false').lower() in ['1','true','yes']:
                        print('Falha no fluxo OAuth interativo em modo não interativo, aguardando 60s e tentando novamente...')
                        time.sleep(60)
                        continue
                    else:
                        print('Saindo do processador principal por falha de autenticação.')
                        return

            # Salva as novas credenciais (token.json) para a próxima execução
            if creds:
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
            else:
                print('Não foi possível obter credenciais válidas, esperando 60s para retry...')
                time.sleep(60)
                continue
        # --- FIM DO BLOCO DE AUTENTICAÇÃO ---

        try:
            rotas_com_status = obter_dimensionamento()
            if rotas_com_status is None:
                print("Não foi possível obter os dados de dimensionamento. Tentando novamente no próximo ciclo.")
                time.sleep(60)
                continue

            service = build('gmail', 'v1', credentials=creds)
            print("Conectado à API do Gmail (Servidor) com sucesso!")

            # Atualiza o filtro de tempo a cada loop
            agora_utc = datetime.datetime.now(timezone.utc)
            limite_de_tempo = agora_utc - timedelta(minutes=minutos_para_filtrar)

            query = (
                f"from:({remetente_procurado}) "
                f"subject:({assunto_procurado}) "
                f"newer_than:{filtro_de_tempo_api}"
            )

            print(f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Procurando e-mails...")
            # print(f"Query: {query}")
            response = service.users().messages().list(userId='me', q=query).execute()
            messages = response.get('messages', [])

            if not messages:
                print("Nenhum e-mail candidato encontrado nesta busca.")
            else:
                print(f"{len(messages)} e-mails candidatos encontrados.")
                print(f"--- A aplicar filtro de duplicados e filtro de {minutos_para_filtrar} minutos ---")

                emails_novos_inseridos = 0

                for msg_summary in messages:
                    msg_id = msg_summary['id']

                    # --- CONTROLO PRINCIPAL (PELO BANCO DE DADOS) ---
                    if msg_id in ids_ja_processados:
                        continue # IGNORA: Já está no banco de dados

                    # Se chegou aqui, é um e-mail novo. Processamos.
                    try:
                        time.sleep(0.1) # Pequeno delay para não sobrecarregar a API

                        msg = service.users().messages().get(
                            userId='me', 
                            id=msg_id, 
                            format='full' 
                        ).execute()

                        internal_date_ms = int(msg['internalDate'])
                        msg_date = datetime.datetime.fromtimestamp(internal_date_ms / 1000.0, tz=timezone.utc)

                        # Aplicamos o filtro local de 15 minutos
                        if msg_date < limite_de_tempo:
                            continue

                        subject_header = next(h['value'] for h in msg['payload']['headers'] if h['name'] == 'Subject')
                        corpo_do_email_html = get_full_email_body(msg['payload'])

                        if not corpo_do_email_html:
                            print(f"E-mail {msg_id} sem corpo, a ignorar.")
                            continue

                        soup = BeautifulSoup(corpo_do_email_html, 'html.parser')
                        tabela = soup.find('table')

                        if tabela:
                            linhas = tabela.find_all('tr')
                            if len(linhas) > 1: # Pelo menos cabeçalho e uma linha de dados
                                celulas = linhas[1].find_all('td')
                                if len(celulas) == 6:
                                    # Extrai os dados
                                    nome_viagem = celulas[0].get_text(strip=True).strip()
                                    numero_viagem = celulas[1].get_text(strip=True).strip()
                                    origem = celulas[2].get_text(strip=True).split("]")[1].strip()
                                    destino = celulas[3].get_text(strip=True).split("]")[1].strip()
                                    eta_origem = celulas[4].get_text(strip=True).strip().replace("-", "/")
                                    veiculo = celulas[5].get_text(strip=True).strip()

                                    regular = 0
                                    print(origem + " | " + destino)
                                    # Usa a variável global (atualizada pelo file watcher)
                                    with config_lock:
                                        origens_atuais = origens_incluidas.copy()

                                    # Verifica contra a lista combinada de rotas com status
                                    rota_email = (origem.strip() + " | " + destino.strip())
                                    print(f"Verificando rota: {rota_email}")
                                    
                                    for item in rotas_com_status:
                                        if rota_email == item['rota']:
                                            if item['status'] == 'REGULAR':
                                                regular = 1
                                                print(f"✓ Rota encontrada como REGULAR: {item['rota']}")
                                            break
                                    
                                    # Verifica se a origem está na lista de incluídas
                                    if origem.strip() in origens_atuais:
                                        regular = 1
                                        print(f"✓ Origem incluída manualmente: {origem.strip()}")
                                    
                                    if regular == 0:
                                        print(f"✗ Rota não incluída, ignorando...")
                                        continue

                                    # --- INSERÇÃO NO SQLITE ---
                                    try:
                                        conn = sqlite3.connect(DATABASE_FILE)
                                        cursor = conn.cursor()
                                        dados_para_inserir = (
                                            msg_id, msg_date, subject_header,
                                            nome_viagem, numero_viagem, origem,
                                            destino, eta_origem, veiculo
                                        )
                                        # Usamos INSERT normal (pois já verificámos o ID)
                                        cursor.execute('''
                                        INSERT INTO leiloes (
                                            gmail_message_id, hora_recebida, assunto,
                                            nome_viagem, numero_viagem, estacao_partida,
                                            estacao_chegada, eta_origem, veiculo
                                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        ''', dados_para_inserir)
                                        conn.commit()
                                        conn.close()

                                        # Formata a mensagem para envio
                                        msg_date_sp = msg_date.astimezone(ZoneInfo("America/Sao_Paulo"))
                                        mensagem_formatada = (
                                            f"🚨 *Novo Spot recebido* 🚨\n"
                                            f"*Viagem Nº:* {numero_viagem}\n"
                                            f"*Origem:* {origem}\n"
                                            f"*Destino:* {destino}\n"
                                            f"*ETA Origem:* {eta_origem}\n"
                                            f"*Perfil:* {veiculo}\n"
                                            f"`Recebido: {msg_date_sp.strftime('%d/%m/%Y %H:%M')}`\n"
                                        )
                                        enviar = envia_mensagem(mensagem_formatada)
                                        if enviar:
                                            ids_ja_processados.add(msg_id) 
                                            print(f"\n--- E-MAIL {msg_id} GUARDADO NA BASE DE DADOS ---")
                                            print(f"Hora Recebida: {msg_date_sp.strftime('%Y-%m-%d %H:%M:%S')}")
                                            print(f"Número da Viagem: {numero_viagem}")
                                            emails_novos_inseridos += 1
                                        time.sleep(random.uniform(1, 3)) # Delay aleatório entre envios

                                    except sqlite3.Error as sql_e:
                                        print(f"ERRO SQLITE ao inserir {msg_id}: {sql_e}")
                                else:
                                    print(f"Ignorando {msg_id}: Tabela encontrada, mas formato inesperado (não tem 6 colunas).")
                            else:
                                print(f"Ignorando {msg_id}: Tabela encontrada, mas sem linhas de dados.")
                        else:
                            print(f"Ignorando {msg_id}: E-mail não contém uma tabela.")

                    except HttpError as error:
                        if error.resp.status == 429:
                            print(f"Atingido o limite de taxa (Rate Limit). A aguardar 5 segundos...")
                            time.sleep(5) 
                        else:
                            print(f"Ocorreu um erro HttpError no loop: {error}")
                    except Exception as e:
                        print(f"Erro inesperado ao processar msg {msg_id}: {e}")

                if emails_novos_inseridos == 0:
                    print(f"Nenhum e-mail *novo* (nos últimos {minutos_para_filtrar} min) foi encontrado.")
                else:
                    print(f"\nProcessamento concluído. {emails_novos_inseridos} e-mail(s) novos guardados na base de dados.")

        except HttpError as error:
            print(f'Ocorreu um erro na API: {error}')
            traceback.print_exc()
            if error.resp.status == 401 or error.resp.status == 403:
                print("Erro de autenticação. Removendo token.json para forçar novo login no próximo loop.")
                if os.path.exists(TOKEN_FILE):
                    os.remove(TOKEN_FILE)
        except Exception as e:
            print(f'Ocorreu um erro inesperado: {e}')
            traceback.print_exc()

        print(f"Aguardando 60 segundos antes da próxima verificação...")
        time.sleep(60)

if __name__ == '__main__':
    # Carrega config inicial
    load_config()
    
    # Inicia file watcher
    event_handler = ConfigFileHandler()
    observer = Observer()
    observer.schedule(event_handler, path='.', recursive=False)
    observer.start()
    print("✓ File watcher iniciado - config será recarregado automaticamente")
    
    try:
        main()
    finally:
        observer.stop()
        observer.join()
