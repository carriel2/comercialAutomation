
# ☁️ SaveinCloud Billing & CS Automations

Ecossistema automatizado de faturamento, análise de consumo e disparos de relatórios executivos para a operação da SaveinCloud. O projeto integra a API da SaveinCloudd  com o Google Sheets e serviços de SMTP para manter a equipe comercial e de Customer Success sempre atualizada.

---

## 🏗️ Arquitetura do Projeto

O ecossistema é dividido em dois microsserviços independentes, rodando em contêineres Docker isolados sob a mesma rede (host) e compartilhando as mesmas variáveis de ambiente.

    COMAUTOMATIONS/
    ├── docker-compose.yaml         # Orquestração dos contêineres
    ├── .env                        # Variáveis de ambiente compartilhadas (API, SMTP, etc)
    ├── requirements.txt            # Dependências Python
    │
    ├── customersuccessAutomation/  # Microsserviço de Customer Success
    │   ├── Dockerfile
    │   └── main.py                 
    │
    └── sheetsAutomation/           # Microsserviço de Planilhas e Relatórios Semanais
        ├── Dockerfile
        ├── main.py                 
        ├── weekly_report.py        
        └── google_credentials.json # Chave de serviço de API do Google Cloud

---

## 🤖 Microsserviços

### 1. Bot Planilhas & Reports (`sheetsAutomation`)
Responsável por espelhar o consumo faturado na nuvem para o Google Sheets e enviar alertas de performance. Possui inteligência para abater valores pagos via *Funding Bonus* e registrar apenas o Custo Real.

* **Sincronização Mensal (Dia 1 às 03:00):** Calcula o consumo retroativo desde o início das contas, abate os bônus (considerando expirações manuais ou sistêmicas) e preenche a aba de Consumo na planilha.
* **Relatório Semanal (Segundas às 05:00):** Isola a janela de consumo da semana anterior (Seg - Dom) e dispara um e-mail HTML com o ranking de maiores consumidores reais da semana, ticket médio e clientes ativos.

### 2. Bot Customer Success (`customersuccessAutomation`)
Focado na carteira exclusiva de CS definida nas variáveis de ambiente.
* **Fechamento Mensal (Dia 1 às 04:00):** Busca os clientes pré-definidos no `.env`, analisa o faturamento exato do mês que acabou de fechar (ignorando bônus consumidos) e dispara um relatório executivo para o time de Sucesso do Cliente.

---

## ⚙️ Pré-requisitos e Configuração

### 1. Variáveis de Ambiente (`.env`)
Crie um arquivo `.env` na raiz do projeto contendo as credenciais de acesso às APIs e os e-mails de destino. Utilize o template abaixo:

    # Configurações Jelastic API
    SESSION_TOKEN="seu_token_aqui"
    APPID="cluster"

    # Configurações Google Sheets
    SPREADSHEET_ID="id_da_sua_planilha_aqui"

    # Configurações Servidor SMTP (E-mail)
    SMTP_SERVER="smtp.email.com"
    SMTP_PORT=587
    SENDER_EMAIL="seu_email_de_envio@dominio.com"
    SENDER_PASSWORD="sua_senha_de_app"

    # Destinatários dos Relatórios (Separados por vírgula)
    RECEIVER_EMAILS="diretoria@dominio.com,comercial@dominio.com"
    RECEIVER_EMAILS_WEEKLY="email@dominio.com"

    # Carteira de Clientes CS (Formato: email:uid, email:uid)
    CLIENTES_LIST="cliente1@teste.com:12345, cliente2@teste.com:67890"

### 2. Autenticação Google
Certifique-se de que o arquivo de credenciais da Service Account do Google Cloud (`google_credentials.json`) esteja presente dentro da pasta `sheetsAutomation`. Sem ele, o script não terá permissão de leitura/escrita na planilha.

---

## 🚀 Como Fazer o Deploy (Docker)

O projeto foi desenhado para rodar em *background* 24/7. Para iniciar os robôs na nuvem com a rede em modo **host**:

1. Acesse o servidor e navegue até a raiz do projeto.
2. Construa as imagens e inicie os contêineres em segundo plano:
   
       docker-compose up -d --build

---

## 📊 Monitoramento e Logs

Os robôs contam com um sistema de logs detalhado (Auditoria de Bônus) e *check-ins* diários para garantir que o *scheduler* está ativo. Para visualizar o que os robôs estão fazendo em tempo real:

**Para ver os logs do Robô de Planilhas:**
    
    docker logs -f jca_sheets_bot

**Para ver os logs do Robô de CS:**
    
    docker logs -f jca_cs_bot