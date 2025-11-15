FROM python:3.11-slim

WORKDIR /app

RUN pip install --upgrade pip

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py .

# Cloud Run will set $PORT; default to 8080
ENV PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
