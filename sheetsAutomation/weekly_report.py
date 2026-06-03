import os
import datetime
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import gspread

# Importa a função de busca de bônus que já criamos no main.py para não repetir código!
from main import (
    get_initial_funding_and_bonus,
    SPREADSHEET_ID,
    SESSION_TOKEN,
    APPID,
    URL_BILLING,
)

load_dotenv()

# Configurações de E-mail
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECEIVER_EMAILS_WEEKLY = os.getenv("RECEIVER_EMAILS_WEEKLY")


def get_last_week_dates():
    """Calcula a data da última segunda-feira e do último domingo."""
    hoje = datetime.date.today()
    dia_semana_hoje = hoje.weekday()

    dias_para_segunda_passada = dia_semana_hoje + 7
    segunda_passada = hoje - datetime.timedelta(days=dias_para_segunda_passada)
    domingo_passado = segunda_passada + datetime.timedelta(days=6)

    return segunda_passada, domingo_passado


def calculate_real_weekly_consumption(
    uid,
    first_funding_date,
    initial_bonus,
    data_exp,
    data_remocao_efetiva,
    start_week_date,
    end_week_date,
):
    """Refaz a queima do bônus, mas retorna apenas o custo REAL gerado na semana alvo, além de dados para log."""
    data_corte = datetime.datetime(2026, 1, 1)
    if first_funding_date > data_corte:
        start_time_api = first_funding_date.strftime("%Y-%m-%d 00:00:00")
    else:
        start_time_api = data_corte.strftime("%Y-%m-%d 00:00:00")

    end_time_api = datetime.datetime.now().strftime("%Y-%m-%d 23:59:59")

    params = {
        "appid": APPID,
        "session": SESSION_TOKEN,
        "period": "day",
        "groupNodes": "false",
        "uid": uid,
        "node": "root",
        "starttime": start_time_api,
        "endtime": end_time_api,
        "charset": "UTF-8",
    }

    response = requests.get(URL_BILLING, params=params, timeout=30)
    history = response.json()

    bonus_balance = initial_bonus
    custo_real_da_semana = 0.0
    consumo_bruto_da_semana = 0.0

    if history.get("result") == 0 and "array" in history:
        daily_costs = sorted(history["array"], key=lambda x: x.get("dateTime", ""))

        for day in daily_costs:
            cost = day.get("cost", 0.0)
            date_str = day.get("dateTime", "")
            if not date_str:
                continue

            only_date_str = date_str.split(" ")[0]
            current_day_obj = datetime.datetime.strptime(
                only_date_str, "%Y-%m-%d"
            ).date()

            # Lógica de Expiração/Remoção
            if bonus_balance > 0:
                if data_remocao_efetiva and current_day_obj >= data_remocao_efetiva:
                    bonus_balance = 0
                elif (
                    data_exp and not data_remocao_efetiva and current_day_obj > data_exp
                ):
                    bonus_balance = 0

            # Queima diária
            real_cost_today = 0.0
            if bonus_balance > 0:
                if cost <= bonus_balance:
                    bonus_balance -= cost
                else:
                    real_cost_today = cost - bonus_balance
                    bonus_balance = 0
            else:
                real_cost_today = cost

            # O PULO DO GATO: Só soma se o dia cair dentro da semana passada
            if start_week_date <= current_day_obj <= end_week_date:
                custo_real_da_semana += real_cost_today
                consumo_bruto_da_semana += cost

    return custo_real_da_semana, consumo_bruto_da_semana, bonus_balance


def rank_display(idx):
    """Retorna medalhas para o top 3 no relatório de e-mail."""
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    return medals.get(idx, str(idx))


def send_weekly_report():
    print("Iniciando geração do Relatório Semanal...")
    segunda, domingo = get_last_week_dates()
    print(
        f"Período de Análise: {segunda.strftime('%d/%m/%Y')} até {domingo.strftime('%d/%m/%Y')}"
    )

    gc = gspread.service_account(filename="google_credentials.json")
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws_controle = sh.worksheet("CONTROLE GERAL CLIENTES")

    controle_data = ws_controle.get_all_values()

    dados_clientes = []
    total_geral_semana = 0.0
    total_clientes_analisados = 0

    for i in range(1, len(controle_data)):
        row_controle = controle_data[i]
        if len(row_controle) <= 3:
            continue

        email = row_controle[1].strip()
        uid_str = row_controle[3].strip()

        if not uid_str.isdigit() or not email:
            continue

        uid = int(uid_str)
        first_date, _, bonus_amount, data_exp, _, data_rem_efetiva = (
            get_initial_funding_and_bonus(uid)
        )

        if not first_date:
            continue

        total_clientes_analisados += 1

        custo_semana, consumo_bruto_semana, saldo_bonus_atual = (
            calculate_real_weekly_consumption(
                uid,
                first_date,
                bonus_amount,
                data_exp,
                data_rem_efetiva,
                segunda,
                domingo,
            )
        )

        # ---------------------------------------------------------
        # IMPRESSÃO DE LOGS NO TERMINAL (ESTILO DOCKER)
        # ---------------------------------------------------------
        custo_pago_por_bonus = consumo_bruto_semana - custo_semana
        print(f"\n    📋 [SEMANAL - UID {uid}] {email}")
        print(f"    ├── Consumo Bruto da Semana: R$ {consumo_bruto_semana:.2f}")
        print(f"    ├── 🛡️ Pago c/ Bônus na Semana: R$ {custo_pago_por_bonus:.2f}")
        print(f"    ├── 📊 Custo Real da Semana: R$ {custo_semana:.2f}")
        print(f"    └── 💰 Saldo de Bônus Restante (Atual): R$ {saldo_bonus_atual:.2f}")
        # ---------------------------------------------------------

        if custo_semana > 0:
            total_geral_semana += custo_semana
            dados_clientes.append(
                {
                    "email": email,
                    "consumo": custo_semana,
                    "saldo_bonus": saldo_bonus_atual,
                }
            )

    # Ordena do maior consumidor para o menor
    dados_clientes_ordenados = sorted(
        dados_clientes, key=lambda x: x["consumo"], reverse=True
    )

    qtd_clientes_com_custo = len(dados_clientes_ordenados)
    ticket_medio = (
        total_geral_semana / qtd_clientes_com_custo
        if qtd_clientes_com_custo > 0
        else 0.0
    )

    print("\n📧 Preparando envio de e-mail HTML premium...")

    # Monta a Tabela de Clientes
    tr_clientes = ""
    for idx, cli in enumerate(dados_clientes_ordenados, start=1):
        bg = "#ffffff" if idx % 2 == 1 else "#fafbfc"
        valor_br = (
            f"R$ {cli['consumo']:,.2f}".replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

        # Formatação chique para o saldo de bônus
        if cli["saldo_bonus"] > 0:
            bonus_badge = f'<span style="background:#e8f5e9;color:#1b5e20;padding:2px 6px;border-radius:8px;font-size:10px;">Saldo: R$ {cli["saldo_bonus"]:.2f}</span>'
        else:
            bonus_badge = '<span style="color:#b0bec5;font-size:10px;">Esgotado</span>'

        tr_clientes += f"""
            <tr style="background-color:{bg};">
                <td style="padding:12px 10px;text-align:center;font-weight:600;color:#455a64;border-bottom:1px solid #eceff1;">{rank_display(idx)}</td>
                <td style="padding:12px 10px;color:#263238;border-bottom:1px solid #eceff1;">
                    {cli['email']}<br>
                    {bonus_badge}
                </td>
                <td style="padding:12px 10px;text-align:right;color:#263238;font-variant-numeric:tabular-nums;border-bottom:1px solid #eceff1;font-weight:500;">{valor_br}</td>
            </tr>
        """

    total_br = (
        f"R$ {total_geral_semana:,.2f}".replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )
    ticket_br = (
        f"R$ {ticket_medio:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    )

    # Monta o E-mail HTML Premium
    html_content = f"""
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background-color:#f4f6f8;font-family:'Segoe UI',Helvetica,Arial,sans-serif;color:#2c3e50;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f6f8;padding:30px 0;">
            <tr><td align="center">
                <table width="720" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.06);">

                    <tr><td style="background:linear-gradient(135deg,#1a73e8 0%,#0d47a1 100%);padding:32px 40px;">
                        <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:600;letter-spacing:-0.3px;">Fechamento Semanal (Consumo Real)</h1>
                        <p style="margin:6px 0 0;color:#bbdefb;font-size:14px;">Período: {segunda.strftime('%d/%m/%Y')} a {domingo.strftime('%d/%m/%Y')}</p>
                    </td></tr>

                    <tr><td style="padding:28px 40px 8px;">
                        <table width="100%" cellpadding="0" cellspacing="0">
                            <tr>
                                <td width="33%" style="padding:16px;background:#f8fafc;border-radius:8px;border-left:4px solid #1a73e8;">
                                    <div style="font-size:11px;color:#78909c;text-transform:uppercase;letter-spacing:0.5px;font-weight:600;">Consumo Faturado</div>
                                    <div style="font-size:22px;color:#0d47a1;font-weight:700;margin-top:6px;">{total_br}</div>
                                </td>
                                <td width="4"></td>
                                <td width="33%" style="padding:16px;background:#f8fafc;border-radius:8px;border-left:4px solid #43a047;">
                                    <div style="font-size:11px;color:#78909c;text-transform:uppercase;letter-spacing:0.5px;font-weight:600;">Pagantes (Semana)</div>
                                    <div style="font-size:22px;color:#1b5e20;font-weight:700;margin-top:6px;">{qtd_clientes_com_custo} <span style="font-size:13px;color:#90a4ae;font-weight:400;">/ {total_clientes_analisados}</span></div>
                                </td>
                                <td width="4"></td>
                                <td width="33%" style="padding:16px;background:#f8fafc;border-radius:8px;border-left:4px solid #fb8c00;">
                                    <div style="font-size:11px;color:#78909c;text-transform:uppercase;letter-spacing:0.5px;font-weight:600;">Ticket Médio (Semanal)</div>
                                    <div style="font-size:22px;color:#e65100;font-weight:700;margin-top:6px;">{ticket_br}</div>
                                </td>
                            </tr>
                        </table>
                    </td></tr>

                    <tr><td style="padding:24px 40px 8px;">
                        <p style="margin:0;font-size:14px;color:#546e7a;line-height:1.6;">
                            Segue o ranking dos clientes que geraram Custo Real (já descontado o bônus) nos últimos 7 dias.
                        </p>
                    </td></tr>

                    <tr><td style="padding:16px 40px 32px;">
                        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px;">
                            <thead>
                                <tr style="background-color:#f1f4f8;">
                                    <th style="padding:12px 10px;text-align:center;color:#37474f;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #cfd8dc;width:50px;">#</th>
                                    <th style="padding:12px 10px;text-align:left;color:#37474f;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #cfd8dc;">Cliente</th>
                                    <th style="padding:12px 10px;text-align:right;color:#37474f;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #cfd8dc;">Consumo Real</th>
                                </tr>
                            </thead>
                            <tbody>
                                {tr_clientes}
                                <tr style="background-color:#0d47a1;">
                                    <td style="padding:14px 10px;text-align:center;color:#ffffff;font-weight:700;">Σ</td>
                                    <td style="padding:14px 10px;color:#ffffff;font-weight:700;letter-spacing:0.3px;">TOTAL GERAL DA SEMANA</td>
                                    <td style="padding:14px 10px;text-align:right;color:#ffffff;font-weight:700;font-size:15px;font-variant-numeric:tabular-nums;">{total_br}</td>
                                </tr>
                            </tbody>
                        </table>
                    </td></tr>

                    <tr><td style="background-color:#f8fafc;padding:24px 40px;border-top:1px solid #eceff1;">
                        <table width="100%" cellpadding="0" cellspacing="0">
                            <tr>
                                <td style="font-size:12px;color:#78909c;line-height:1.6;">
                                    <strong style="color:#37474f;">Automação de Faturamento</strong><br>
                                    <span style="color:#90a4ae;">SaveinCloud Team</span>
                                </td>
                                <td style="text-align:right;font-size:11px;color:#b0bec5;">
                                    Relatório gerado em:<br>
                                    {datetime.datetime.now().strftime('%d/%m/%Y às %H:%M')}
                                </td>
                            </tr>
                        </table>
                    </td></tr>

                </table>
                <p style="font-size:11px;color:#b0bec5;margin:16px 0 0;">Este é um e-mail automatizado. Em caso de divergência, consulte a planilha principal.</p>
            </td></tr>
        </table>
    </body>
    </html>
    """

    lista_destinatarios = [e.strip() for e in RECEIVER_EMAILS_WEEKLY.split(",")]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"Relatório Semanal ({segunda.strftime('%d/%m')} a {domingo.strftime('%d/%m')})"
    )
    msg["From"] = SENDER_EMAIL
    msg["To"] = ", ".join(lista_destinatarios)
    msg.attach(MIMEText(html_content, "html"))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, lista_destinatarios, msg.as_string())
        server.quit()
        print("✅ E-mail enviado com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao enviar e-mail: {e}")


if __name__ == "__main__":
    send_weekly_report()
