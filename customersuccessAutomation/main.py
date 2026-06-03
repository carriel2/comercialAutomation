import requests
import smtplib
import os
import time
import datetime
import schedule
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

load_dotenv()

# ==========================================
# CONFIGURAÇÕES JELASTIC
# ==========================================
SESSION_TOKEN = os.getenv("SESSION_TOKEN")
APPID = "cluster"
URL_BILLING = "https://jca.paas.saveincloud.net.br/JBilling/billing/account/rest/getaccountbillinghistorybyperiodinner"

# ==========================================
# CONFIGURAÇÕES DE E-MAIL
# ==========================================
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECEIVER_EMAILS = os.getenv("RECEIVER_EMAILS")

# ==========================================
# LISTA DE CLIENTES (E-MAIL : UID) VIA .ENV
# ==========================================
CLIENTES = {}
clientes_env = os.getenv(
    "CLIENTES",
)

if clientes_env:
    pares = clientes_env.split(",")
    for par in pares:
        if ":" in par:
            email, uid = par.split(":", 1)
            CLIENTES[email.strip()] = int(uid.strip())
else:
    print("⚠️ AVISO: Nenhuma lista de clientes encontrada no arquivo .env.")


def get_mes_passado_dates():
    """Calcula dinamicamente o primeiro e o último dia do mês passado."""
    hoje = datetime.date.today()

    # Primeiro dia do mês atual
    primeiro_dia_atual = hoje.replace(day=1)
    # Subtrai 1 dia para cair no último dia do mês passado
    ultimo_dia_passado = primeiro_dia_atual - datetime.timedelta(days=1)
    # Primeiro dia do mês passado
    primeiro_dia_passado = ultimo_dia_passado.replace(day=1)

    start_time = primeiro_dia_passado.strftime("%Y-%m-%d 00:00:00")
    end_time = ultimo_dia_passado.strftime("%Y-%m-%d 23:59:59")
    mes_str = primeiro_dia_passado.strftime("%m/%Y")

    return start_time, end_time, mes_str


def consultar_consumo_mes_passado(uid, start_time, end_time):
    """Consulta o consumo diário do período passado e ignora os bônus."""
    params = {
        "appid": APPID,
        "session": SESSION_TOKEN,
        "uid": uid,
        "period": "day",
        "starttime": start_time,
        "endtime": end_time,
        "charset": "UTF-8",
    }

    custo_total = 0.0

    try:
        response = requests.get(URL_BILLING, params=params, timeout=60)

        if response.status_code != 200:
            print(
                f"  ❌ Erro HTTP {response.status_code} para o UID {uid}. Resposta: {response.text[:100]}"
            )
            return custo_total

        try:
            data = response.json()
        except Exception:
            print(
                f"  ❌ Erro ao ler JSON para o UID {uid}. Resposta: {response.text[:100]}"
            )
            return custo_total

        if data.get("result") == 0 and "array" in data:
            for dia in data["array"]:
                custo = dia.get("cost", 0.0)
                is_bonus = dia.get("isBonus", False)

                if not is_bonus:
                    custo_total += custo

    except requests.exceptions.Timeout:
        print(f"  ❌ Timeout da requisição para o UID {uid}.")
    except Exception as e:
        print(f"  ❌ Erro de conexão ao consultar o UID {uid}: {e}")

    return custo_total


def enviar_email(dados_clientes, total_geral, mes_str, nao_preenchidos):
    """Monta a tabela HTML simplificada (1 coluna de mês) e envia por e-mail."""
    print("\n📧 Preparando envio de e-mail do CS...")

    tr_clientes = ""
    for cliente in dados_clientes:
        valor_cli = f"R$ {cliente['consumo']:.2f}".replace(".", ",")
        tr_clientes += (
            f"<tr><td>{cliente['email']}</td><td><strong>{valor_cli}</strong></td></tr>"
        )

    td_total_absoluto = f"R$ {total_geral:.2f}".replace(".", ",")

    html_erros = ""
    if nao_preenchidos:
        lista_erros = "".join([f"<li>{email}</li>" for email in nao_preenchidos])
        html_erros = f"""
        <div style="color: #a94442; background-color: #f2dede; padding: 15px; margin-bottom: 20px; border: 1px solid #ebccd1; border-radius: 4px; font-family: Arial;">
            <strong>Aviso:</strong> Os seguintes clientes foram ignorados porque o UID não foi preenchido:
            <ul>{lista_erros}</ul>
        </div>
        """

    html = f"""
    <html>
      <head>
        <style>
          table {{ font-family: Arial, sans-serif; border-collapse: collapse; width: 100%; max-width: 600px; }}
          th, td {{ border: 1px solid #dddddd; text-align: right; padding: 8px; }}
          td:first-child, th:first-child {{ text-align: left; }}
          th {{ background-color: #f2f2f2; }}
          .total-row {{ background-color: #e6f2ff; font-weight: bold; }}
        </style>
      </head>
      <body>
        <h2>Fechamento Customer Success ({mes_str})</h2>
        <p>Consumo real faturado no mês passado para os clientes da carteira de CS.</p>
        {html_erros}
        <table>
          <tr>
            <th>Cliente</th>
            <th>Consumo {mes_str}</th>
          </tr>
          {tr_clientes}
          <tr class="total-row">
            <td>TOTAL GERAL</td>
            <td>{td_total_absoluto}</td>
          </tr>
        </table>
      </body>
    </html>
    """

    lista_destinatarios = [email.strip() for email in RECEIVER_EMAILS.split(",")]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Relatório CS: Consumo Fechado ({mes_str})"
    msg["From"] = SENDER_EMAIL
    msg["To"] = ", ".join(lista_destinatarios)
    msg.attach(MIMEText(html, "html"))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, lista_destinatarios, msg.as_string())
        server.quit()
        print("✅ E-mail de CS enviado com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao enviar e-mail de CS: {e}")


def main():
    if not CLIENTES:
        print("❌ Operação abortada. Nenhuma conta encontrada na variável do .env.")
        return

    dados_processados = []
    nao_preenchidos = []
    total_geral = 0.0

    start_time, end_time, mes_str = get_mes_passado_dates()
    print(
        f"\nIniciando consulta de consumo CS para o período: {start_time} até {end_time}"
    )

    for email, uid in CLIENTES.items():
        if uid == 0:
            print(f"⚠️ UID não preenchido para {email}. Pulando...")
            nao_preenchidos.append(email)
            continue

        print(f"⏳ Consultando {email} (UID: {uid})...")

        custo_mes = consultar_consumo_mes_passado(uid, start_time, end_time)
        total_geral += custo_mes

        dados_processados.append({"email": email, "consumo": custo_mes})

        time.sleep(1)

    dados_processados = sorted(
        dados_processados, key=lambda x: x["consumo"], reverse=True
    )

    if dados_processados or nao_preenchidos:
        enviar_email(dados_processados, total_geral, mes_str, nao_preenchidos)
    else:
        print("Nenhum cliente processado para enviar e-mail.")


if __name__ == "__main__":
    print("🚀 Robô de Customer Success iniciado na nuvem!")
    print("⏰ Relatório agendado para o DIA 1 de cada mês às 04:00 da manhã.")
    print("-" * 50)

    def agendamento_mensal_cs():
        hoje = datetime.date.today()
        if hoje.day == 1:
            print(
                f"\n📅 Dia 1 do mês detectado. Gerando relatório de CS do mês passado..."
            )
            main()
        else:
            print(
                f"💤 [{datetime.datetime.now().strftime('%d/%m %H:%M')}] Check diário CS: hoje é dia {hoje.day}. Nada a fazer."
            )

    # Agendado para as 04:00 (1 hora depois da planilha, para não esbarrar na API ao mesmo tempo)
    schedule.every().day.at("04:00").do(agendamento_mensal_cs)

    # LOOP INFINITO DO DOCKER
    while True:
        schedule.run_pending()
        time.sleep(60)
