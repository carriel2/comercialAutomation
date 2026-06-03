FROM python:3.11-slim

ENV TZ="America/Sao_Paulo"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY customersuccessAutomation/ .

CMD ["python", "-u", "main.py"]