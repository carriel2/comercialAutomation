import requests
import os
import datetime
from dotenv import load_dotenv
import gspread
import re
import schedule
import time

load_dotenv()

SESSION_TOKEN = os.getenv("SESSION_TOKEN")
APPID = os.getenv("APPID", "cluster")
URL_BILLING = "https://jca.paas.saveincloud.net.br/JBilling/billing/account/rest/getaccountbillinghistorybyperiodinner"
URL_FUNDING = "https://jca.paas.saveincloud.net.br/JBilling/billing/account/rest/getfundaccounthistory"

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")


def get_initial_funding_and_bonus(uid):
    """Busca a 1ª recarga, o bônus inicial e identifica se houve expiração/remoção."""
    start_time = "2026-01-01 00:00:00"
    end_time = datetime.datetime.now().strftime("%Y-%m-%d 23:59:59")

    params = {
        "appid": APPID,
        "session": SESSION_TOKEN,
        "uid": uid,
        "starttime": start_time,
        "endtime": end_time,
        "startRow": 0,
        "resultCount": 1000,
        "charset": "UTF-8",
    }

    response = requests.get(URL_FUNDING, params=params, timeout=30)
    data = response.json()

    first_funding_date = None
    first_funding_ms = None
    real_amount = 0.0
    bonus_amount = 0.0

    data_expiracao_nota = None
    valor_removido_expiracao = 0.0
    data_remocao_efetiva = None

    if data.get("result") == 0 and "responses" in data:
        transactions = sorted(data["responses"], key=lambda x: x["operationDate"])

        for t in transactions:
            if t.get("chargeType") == "FUND":
                first_funding_ms = t["operationDate"]
                first_funding_date = datetime.datetime.fromtimestamp(
                    first_funding_ms / 1000.0
                )
                real_amount = t.get("amount", 0.0)
                break

        if first_funding_ms is not None:
            for t in transactions:
                charge_type = t.get("chargeType", "")
                note = t.get("note", "")
                amount = t.get("amount", 0.0)
                op_date = datetime.datetime.fromtimestamp(t["operationDate"] / 1000.0)

                # Captura o bônus inicial
                if charge_type == "FUND_BONUS" and amount > 0:
                    diff_ms = t["operationDate"] - first_funding_ms
                    if (
                        -(7 * 24 * 60 * 60 * 1000)
                        <= diff_ms
                        <= (15 * 24 * 60 * 60 * 1000)
                    ):
                        bonus_amount += amount

                        matches = re.findall(r"\d{2}/\d{2}/\d{4}", note)
                        if matches:
                            ultima_data_str = matches[-1]
                            data_expiracao_nota = datetime.datetime.strptime(
                                ultima_data_str, "%d/%m/%Y"
                            ).date()

                # Captura a remoção do bônus
                if charge_type == "REFUND_BONUS":
                    valor_removido_expiracao += amount
                    data_remocao_efetiva = op_date.date()
                elif (
                    (charge_type == "FUND_BONUS" and amount < 0)
                    or ("REVOKE" in charge_type)
                    or ("EXPIR" in note and amount < 0)
                ):
                    valor_removido_expiracao += abs(amount)
                    data_remocao_efetiva = op_date.date()

    return (
        first_funding_date,
        real_amount,
        bonus_amount,
        data_expiracao_nota,
        valor_removido_expiracao,
        data_remocao_efetiva,
    )


def calculate_real_monthly_consumption(
    uid,
    first_funding_date,
    initial_bonus,
    data_expiracao_nota,
    valor_removido_expiracao,
    data_remocao_efetiva,
):
    """Abate o consumo diário considerando remoções por expiração de bônus e gera logs detalhados."""
    data_corte = datetime.datetime(2026, 1, 1)
    if first_funding_date > data_corte:
        start_time = first_funding_date.strftime("%Y-%m-%d 00:00:00")
    else:
        start_time = data_corte.strftime("%Y-%m-%d 00:00:00")

    end_time = datetime.datetime.now().strftime("%Y-%m-%d 23:59:59")

    params = {
        "appid": APPID,
        "session": SESSION_TOKEN,
        "period": "day",
        "groupNodes": "false",
        "uid": uid,
        "node": "root",
        "starttime": start_time,
        "endtime": end_time,
        "charset": "UTF-8",
    }

    response = requests.get(URL_BILLING, params=params, timeout=30)
    history = response.json()

    bonus_balance = initial_bonus
    real_consumption_by_month = {}

    total_bruto_consumido = 0.0
    total_pago_com_bonus = 0.0
    total_pago_real = 0.0
    motivo_fim_bonus = "Ainda Ativo / Saldo Disponível"
    data_fim_bonus = "—"
    sobra_bonus_na_expiracao = 0.0

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

            parts = only_date_str.split("-")
            month_key = f"{parts[1]}/{parts[0]}" if len(parts) >= 2 else "Desconhecido"

            if month_key not in real_consumption_by_month:
                real_consumption_by_month[month_key] = 0.0

            total_bruto_consumido += cost

            # INTERCEPÇÃO DE EXPIRAÇÃO / REMOÇÃO MANUAL
            if bonus_balance > 0:
                if data_remocao_efetiva and current_day_obj >= data_remocao_efetiva:
                    motivo_fim_bonus = f"Removido/Expirou via API Jelastic (Estorno de R$ {valor_removido_expiracao:.2f})"
                    data_fim_bonus = data_remocao_efetiva.strftime("%d/%m/%Y")
                    sobra_bonus_na_expiracao = bonus_balance
                    bonus_balance = 0
                elif (
                    data_expiracao_nota
                    and not data_remocao_efetiva
                    and current_day_obj > data_expiracao_nota
                ):
                    motivo_fim_bonus = f"Expirou por Data Limite da Nota ({data_expiracao_nota.strftime('%d/%m/%Y')})"
                    data_fim_bonus = data_expiracao_nota.strftime("%d/%m/%Y")
                    sobra_bonus_na_expiracao = bonus_balance
                    bonus_balance = 0

            # LÓGICA DE QUEIMA DE BÔNUS DIÁRIO
            if bonus_balance > 0:
                if cost <= bonus_balance:
                    bonus_balance -= cost
                    total_pago_com_bonus += cost
                else:
                    real_cost = cost - bonus_balance
                    total_pago_com_bonus += bonus_balance
                    total_pago_real += real_cost
                    real_consumption_by_month[month_key] += real_cost

                    motivo_fim_bonus = "Esgotado por Consumo do Cliente"
                    data_fim_bonus = current_day_obj.strftime("%d/%m/%Y")
                    bonus_balance = 0
            else:
                total_pago_real += cost
                real_consumption_by_month[month_key] += cost

    if initial_bonus > 0:
        eficiencia = (
            (total_pago_com_bonus / initial_bonus) * 100 if initial_bonus > 0 else 0.0
        )
        print(f"\n    📋 [LOG DE AUDITORIA DE BÔNUS - UID {uid}]")
        print(f"    ├── Bônus Concedido Inicial: R$ {initial_bonus:.2f}")
        print(f"    ├── Consumo Bruto no Período: R$ {total_bruto_consumido:.2f}")
        print(
            f"    ├── 🛡️ Total Pago c/ Bônus: R$ {total_pago_com_bonus:.2f} ({eficiencia:.1f}% de aproveitamento)"
        )
        print(f"    ├── 📊 Total Pago em Dinheiro Real: R$ {total_pago_real:.2f}")
        print(f"    └── 🛑 Fim do Bônus: {motivo_fim_bonus} | Data: {data_fim_bonus}")
        if sobra_bonus_na_expiracao > 0:
            print(
                f"        ⚠️ Desperdício: O cliente deixou vencer R$ {sobra_bonus_na_expiracao:.2f} de bônus."
            )
    else:
        print(
            f"    ℹ️ [LOG] Cliente sem bônus inicial. Todo o consumo bruto (R$ {total_bruto_consumido:.2f}) foi direto para Custo Real."
        )

    return real_consumption_by_month


def gerar_lista_meses():
    """Gera lista de meses no formato cronológico MM/YYYY desde 01/2026 até o mês atual."""
    meses = []
    hoje = datetime.date.today()
    ano, mes = 2026, 1

    while (ano < hoje.year) or (ano == hoje.year and mes <= hoje.month):
        meses.append(f"{mes:02d}/{ano}")
        mes += 1
        if mes > 12:
            mes = 1
            ano += 1
    return meses


def process_and_sync_sheets():
    print("Conectando ao Google Sheets...")
    gc = gspread.service_account(filename="google_credentials.json")
    sh = gc.open_by_key(SPREADSHEET_ID)

    ws_controle = sh.worksheet("CONTROLE GERAL CLIENTES")
    ws_consumo = sh.worksheet("Consumo")

    meses_ordenados = gerar_lista_meses()

    # --- ADICIONADO AS DUAS COLUNAS NOVAS NO CABEÇALHO ---
    matriz_final = [
        ["ID", "E-MAIL", "DATA CONVERSÃO", "VALOR 1ª RECARGA"] + meses_ordenados
    ]

    # Dicionário para acumular o total geral de cada mês
    totais_por_mes = {mes: 0.0 for mes in meses_ordenados}

    controle_data = ws_controle.get_all_values()

    for i in range(1, len(controle_data)):
        row_controle = controle_data[i]

        if len(row_controle) <= 3:
            continue

        email = row_controle[1].strip()
        uid_str = row_controle[3].strip()

        if not uid_str.isdigit():
            continue

        uid = int(uid_str)
        print(f"\n--- Analisando {email if email else 'SEM EMAIL'} (UID: {uid}) ---")

        if not email:
            print(
                f"⚠️ ATENÇÃO: O e-mail do UID {uid} está em branco na aba de Controle. Verifique colunas ocultas!"
            )

        first_date, real_amount, bonus_amount, data_exp, val_rem, data_rem_efetiva = (
            get_initial_funding_and_bonus(uid)
        )

        if not first_date:
            print("❌ Nenhuma recarga encontrada em 2026. Pulando...")
            continue

        print(
            f"💰 1ª Recarga: {first_date.strftime('%d/%m/%Y')} | Real: R$ {real_amount:.2f} | Bônus: R$ {bonus_amount:.2f}"
        )

        monthly_real_costs = calculate_real_monthly_consumption(
            uid, first_date, bonus_amount, data_exp, val_rem, data_rem_efetiva
        )

        # --- ADICIONADO A DATA E O VALOR NA LINHA DO CLIENTE ---
        data_conversao_str = first_date.strftime("%d/%m/%Y")
        valor_recarga_str = f"{real_amount:.2f}".replace(".", ",")

        linha_cliente = [uid_str, email, data_conversao_str, valor_recarga_str]

        for m in meses_ordenados:
            valor_real = monthly_real_costs.get(m, 0.0)

            totais_por_mes[m] += valor_real

            if valor_real > 0:
                linha_cliente.append(f"{valor_real:.2f}".replace(".", ","))
            else:
                linha_cliente.append("0,00")

        matriz_final.append(linha_cliente)

    # --- CRIA A LINHA FINAL DE SOMA GERAL (COM ESPAÇOS PARA ALINHAR) ---
    # Os dois espaços vazios ("") servem para pular as colunas "DATA CONVERSÃO" e "VALOR 1ª RECARGA"
    linha_totais = ["", "TOTAL GERAL", "", ""]
    for m in meses_ordenados:
        linha_totais.append(f"{totais_por_mes[m]:.2f}".replace(".", ","))

    matriz_final.append(linha_totais)

    print("\n💾 Escrevendo dados ordenados no Google Sheets...")
    ws_consumo.clear()

    try:
        ws_consumo.update(values=matriz_final, range_name="A1")
    except TypeError:
        ws_consumo.update("A1", matriz_final)

    print(
        "🎉 Sincronização concluída com as novas colunas e a linha de TOTAL GERAL no rodapé!"
    )


if __name__ == "__main__":
    from weeklyreportAutomation.weekly_report import send_weekly_report

    print("🚀 Robô iniciado com sucesso na nuvem!")
    print(
        "⏰ Sincronização da Planilha agendada para o DIA 1 de cada mês às 03:00 da manhã."
    )
    print(
        "📧 Relatório Semanal por E-mail agendado para SEGUNDAS-FEIRAS às 05:00 da manhã."
    )
    print("-" * 50)

    # -------------------------------------------------------------------------
    # ROTINA DA PLANILHA: Roda apenas no dia 1 de cada mês às 03:00
    # -------------------------------------------------------------------------
    def agendamento_mensal():
        hoje = datetime.date.today()
        if hoje.day == 1:
            print(
                f"\n📅 Dia 1 do mês detectado ({hoje.strftime('%d/%m/%Y')}). Iniciando fechamento da planilha..."
            )
            process_and_sync_sheets()
        else:
            print(
                f"💤 [{datetime.datetime.now().strftime('%d/%m %H:%M')}] Check diário: hoje é dia {hoje.day}. Nada a fazer na planilha."
            )

    # O schedule acorda todos os dias às 03:00, mas a função acima barra se não for dia 1
    schedule.every().day.at("03:00").do(agendamento_mensal)

    # -------------------------------------------------------------------------
    # ROTINA SEMANAL: Dispara o E-mail de Consumo toda Segunda às 05:00
    # -------------------------------------------------------------------------
    schedule.every().monday.at("05:00").do(send_weekly_report)

    # process_and_sync_sheets()  # Para rodar de forma manual, basta descomentar esta linha e rodar o script.

    # -------------------------------------------------------------------------
    # LOOP INFINITO DO DOCKER
    # -------------------------------------------------------------------------
    while True:
        schedule.run_pending()
        time.sleep(60)
