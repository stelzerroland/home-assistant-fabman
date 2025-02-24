# Verwende ein leichtgewichtiges Python-Image
FROM python:3.9-slim

# Setze das Arbeitsverzeichnis im Container
WORKDIR /app

# Kopiere die requirements.txt und installiere die Abhängigkeiten
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Kopiere den restlichen Code in das Arbeitsverzeichnis
COPY . .

# Exponiere Port 8000
EXPOSE 8000

# Starte den FastAPI-Server über Uvicorn
CMD ["uvicorn", "webhook_server:app", "--host", "0.0.0.0", "--port", "8000"]
