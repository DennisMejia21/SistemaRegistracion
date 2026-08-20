FROM python:3.12-slim

WORKDIR /app

# Sin requirements: el ejemplo usa solo la biblioteca estandar, a proposito.
COPY consumidor.py .

EXPOSE 9000

CMD ["python", "consumidor.py"]
