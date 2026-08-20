FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# main.py es el servicio; migrar_passwords.py se corre a mano una sola vez
# (`docker compose exec mock-service python migrar_passwords.py`), asi que tiene
# que estar adentro de la imagen.
COPY main.py migrar_passwords.py ./

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]