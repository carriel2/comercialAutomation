import os
import requests
from dotenv import load_dotenv
import json

load_dotenv()

SESSION_TOKEN = os.getenv("SESSION_TOKEN")
UID_ALVO = None  # INSIRA O UID DO CLIENTE AQUI (ex: 12345)

params = {
    "appid": "cluster",
    "session": SESSION_TOKEN,
    "uid": UID_ALVO,
    "period": "day",
    "starttime": None,  # INSIRA A DATA DE INÍCIO (ex: "2026-01-01 00:00:00"),
    "endtime": None,  # INSIRA A DATA DE FIM (ex: "2026-05-01 23:59:59").
    "charset": "UTF-8",
}

url = "https://jca.paas.saveincloud.net.br/JBilling/billing/account/rest/getaccountbillinghistorybyperiodinner"

print("Consultando a Jelastic...")
response = requests.get(url, params=params)

if response.status_code == 200:
    dados = response.json()
    if dados.get("result") == 0 and "array" in dados and len(dados["array"]) > 0:
        primeiro_dia = dados["array"][0]

        print("\n=== DADOS ENCONTRADOS NESSE DIA ===")
        print(json.dumps(primeiro_dia, indent=4, ensure_ascii=False))
    else:
        print("Nenhum dado encontrado nesse dia ou formato inesperado.")
else:
    print(f"Erro na requisição: {response.status_code}")
