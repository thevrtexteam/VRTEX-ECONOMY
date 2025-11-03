FROM python:3.12-slim

WORKDIR /app
COPY . .

RUN pip install -r requirements.txt

CMD ["bash", "-c", "python3 web_server.py & python3 main.py"]
