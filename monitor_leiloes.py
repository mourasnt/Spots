import os
import time
import json
import base64
import random
import datetime
import traceback
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

import requests
import gspread
import redis
from bs4 import BeautifulSoup

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- Configurações Gerais ---
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.json'

# --- Configurações Redis ---
REDIS_URL = os.getenv('REDIS_URL', 'redis://spots_redis:6379/0')
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# --- Configurações Google Sheets ---
SHEETS_CREDS_PATH = "credentials_sheets.json"
SPREADSHEET_ID = "18a1S-ITSS6VATOCoJRZDx02pivQB6DZeNfi7SW-BKH8"
WORKSHEET_NAME = "DIMENSIONAMENTO"
SHEETS_SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# --- Configurações Evolution API (WhatsApp) ---
# Aqui você pode usar uma variável de ambiente para apontar para a máquina onde a Evolution está rodando
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://COLOQUE_O_IP_DA_EVOLUTION_AQUI:8080")
EVOLUTION_INSTANCE = "Spots"
EVOLUTION_API_KEY = "Senh@Segura123"
DESTINATION_NUMBER = "120363421560093254@g.us"

# --- Filtros de E-mail ---
REMETENTE_PROCURADO = "operacao@3zx.com.br"
ASSUNTO_PROCURADO = "ATENÇÃO: a sua transportadora tem uma viagem de leilão com a Shopee"
MINUTOS_PARA_FILTRAR = 600
FILTRO_DE_TEMPO_API = "3d"


def obter_origens_do_redis():
    """Busca as origens atualizadas direto do Redis"""
    try:
        origens = redis_client.lrange('spots:origens', 0, -1)
        return origens if origens else []
    except redis.RedisError as e:
        print(f"Erro ao ler origens do Redis: {e}")
        return []

def email_ja_processado(msg_id):
    """Verifica de forma extremamente rápida se o ID do e-mail está no Redis (O(1))"""
    try:
        return redis_client.sismember('spots:processed_emails', msg_id)
    except redis.RedisError:
        return False

def salvar_email_no_redis(msg_id, msg_date, subject, viagem, numero, origem, destino, eta, veiculo):
    """Salva os dados extraídos do e-mail no Redis"""
    try:
        pipeline = redis_client.pipeline()
        pipeline.sadd('spots:processed_emails', msg_id)
        chave_email = f"spots:email:{msg_id}"
        pipeline.hset(chave_email, mapping={
            'hora_recebida': msg_date.isoformat(),
            'assunto': subject,
            'nome_viagem': viagem,
            'numero_viagem': numero,
            'estacao_partida': origem,
            'estacao_chegada': destino,
            'eta_origem': eta,
            'veiculo': veiculo
        })
        pipeline.execute()
        return True
    except redis.RedisError as e:
        print(f"❌ ERRO REDIS ao inserir {msg_id}: {e}")
        return False

def get_full_email_body(payload):
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

    body_to_decode = body_data_html if body_data_html else body_data_plain

    if body_to_decode:
        dados_descodificados = base64.urlsafe_b64decode(body_to_decode.encode('ASCII'))
        return dados_descodificados.decode('utf-8')
    return None

def obter_dimensionamento():
    header_row_num = 1
    try:
        print("Autenticando no Google Sheets...")
        creds_sheets = ServiceAccountCredentials.from_service_account_file(
            SHEETS_CREDS_PATH, scopes=SHEETS_SCOPES)
        client = gspread.authorize(creds_sheets)

        print(f"Abrindo planilha: {SPREADSHEET_ID} | Aba: {WORKSHEET_NAME}")
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
        headers = worksheet.row_values(header_row_num)

        try:
            rota_col_index = headers.index('ROTA') + 1
            regular_col_index = headers.index('Rota') + 1
        except ValueError as e:
            print(f"Erro: Coluna obrigatória não encontrada. Verifique o cabeçalho.")
            return None

        rota_data = worksheet.col_values(rota_col_index)[header_row_num:]
        regular_data = worksheet.col_values(regular_col_index)[header_row_num:]

        rotas_com_status = []
        for i in range(len(rota_data)):
            rota_item = rota_data[i] if i < len(rota_data) else ""
            regular_item = regular_data[i] if i < len(regular_data) else ""
            
            rotas_com_status.append({
                'rota': rota_item.strip(),
                'status': regular_item.strip()
            })
        return rotas_com_status

    except Exception as e:
        print(f"Erro inesperado ao obter dados do Sheets: {e}")
        return None

def envia_mensagem(mensagem):
    url_endpoint = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    payload = {
        "number": DESTINATION_NUMBER,
        "options": {"delay": 1200, "presence": "composing"},
        "text": mensagem
    }
    headers = {"Content-Type": "application/json", "apikey": EVOLUTION_API_KEY}

    print(f"Enviando mensagem para: {DESTINATION_NUMBER} via {EVOLUTION_API_URL}...")
    try:
        response = requests.post(url_endpoint, headers=headers, data=json.dumps(payload), timeout=10)
        response.raise_for_status() 
        print("✅ Mensagem enviada com sucesso!")
        return True
    except Exception as e:
        print(f"❌ Erro ao enviar mensagem Evolution API: {e}")
        return False

def main():
    try:
        redis_client.ping()
        print("✓ Conexão com Redis estabelecida.")
    except redis.ConnectionError:
        print("❌ ERRO FATAL: Não foi possível conectar ao Redis.")
        return

    while True:
        print(f"DEBUG: Início do loop. token={os.path.exists(TOKEN_FILE)}, creds={os.path.exists(CREDENTIALS_FILE)}")
        
        # --- BLOCO AUTENTICAÇÃO GMAIL ---
        creds = None
        if os.path.exists(TOKEN_FILE):
            try:
                creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
            except Exception as e:
                print(f"Erro no {TOKEN_FILE}: {e}. Removendo.")
                os.remove(TOKEN_FILE)
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(f"Falha no refresh do token: {e}")
                    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE) 
                    creds = None 
            else:
                try:
                    if not os.path.exists(CREDENTIALS_FILE):
                        print(f"ERRO: '{CREDENTIALS_FILE}' não encontrado. Retry 60s...")
                        time.sleep(60)
                        continue

                    if os.environ.get('GMAIL_NO_INTERACTIVE', 'false').lower() in ['1','true','yes']:
                        print('Modo NÃO interativo ativo. Precisamos de um token.json válido.')
                        time.sleep(60)
                        continue

                    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                    creds = flow.run_local_server(port=0) 
                except Exception as e:
                    print(f"Erro OAuth: {e}. Retry 60s...")
                    time.sleep(60)
                    continue

            if creds:
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
            else:
                time.sleep(60)
                continue
        # --- FIM AUTENTICAÇÃO ---

        try:
            rotas_com_status = obter_dimensionamento()
            if rotas_com_status is None:
                time.sleep(60)
                continue

            origens_atuais = obter_origens_do_redis()
            
            service = build('gmail', 'v1', credentials=creds)
            agora_utc = datetime.datetime.now(timezone.utc)
            limite_de_tempo = agora_utc - timedelta(minutes=MINUTOS_PARA_FILTRAR)

            query = f"from:({REMETENTE_PROCURADO}) subject:({ASSUNTO_PROCURADO}) newer_than:{FILTRO_DE_TEMPO_API}"
            print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Procurando e-mails...")
            
            response = service.users().messages().list(userId='me', q=query).execute()
            messages = response.get('messages', [])

            if messages:
                emails_novos_inseridos = 0
                for msg_summary in messages:
                    msg_id = msg_summary['id']

                    if email_ja_processado(msg_id):
                        continue 

                    try:
                        time.sleep(0.1)
                        msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
                        msg_date = datetime.datetime.fromtimestamp(int(msg['internalDate']) / 1000.0, tz=timezone.utc)

                        if msg_date < limite_de_tempo: continue

                        subject_header = next(h['value'] for h in msg['payload']['headers'] if h['name'] == 'Subject')
                        corpo_do_email_html = get_full_email_body(msg['payload'])

                        if not corpo_do_email_html: continue

                        soup = BeautifulSoup(corpo_do_email_html, 'html.parser')
                        tabela = soup.find('table')

                        if tabela and len(tabela.find_all('tr')) > 1:
                            celulas = tabela.find_all('tr')[1].find_all('td')
                            if len(celulas) == 6:
                                nome_viagem = celulas[0].get_text(strip=True).strip()
                                numero_viagem = celulas[1].get_text(strip=True).strip()
                                origem = celulas[2].get_text(strip=True).split("]")[1].strip() if "]" in celulas[2].get_text() else celulas[2].get_text(strip=True)
                                destino = celulas[3].get_text(strip=True).split("]")[1].strip() if "]" in celulas[3].get_text() else celulas[3].get_text(strip=True)
                                eta_origem = celulas[4].get_text(strip=True).strip().replace("-", "/")
                                veiculo = celulas[5].get_text(strip=True).strip()

                                regular = False
                                rota_email = (origem.strip() + " | " + destino.strip())
                                
                                for item in rotas_com_status:
                                    if rota_email == item['rota'] and item['status'] == 'REGULAR':
                                        regular = True
                                        break
                                
                                if origem.strip() in origens_atuais:
                                    regular = True
                                
                                if not regular:
                                    continue

                                salvo_no_redis = salvar_email_no_redis(
                                    msg_id, msg_date, subject_header, nome_viagem, 
                                    numero_viagem, origem, destino, eta_origem, veiculo
                                )
                                
                                if salvo_no_redis:
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
                                    
                                    if envia_mensagem(mensagem_formatada):
                                        print(f"\n--- E-MAIL {msg_id} GUARDADO NO REDIS ---")
                                        emails_novos_inseridos += 1
                                        
                                    time.sleep(random.uniform(1, 3))

                    except HttpError as error:
                        if error.resp.status == 429: time.sleep(5)
                    except Exception as e:
                        print(f"Erro msg {msg_id}: {e}")

                if emails_novos_inseridos > 0:
                    print(f"Processamento concluído. {emails_novos_inseridos} novos spots.")

        except HttpError as error:
            print(f'Erro de API: {error}')
            if error.resp.status in [401, 403] and os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
        except Exception as e:
            traceback.print_exc()

        print("Aguardando 60 segundos antes da próxima verificação...")
        time.sleep(60)

if __name__ == '__main__':
    main()