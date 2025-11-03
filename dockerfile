# Use Python 3.12 so audioop exists
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy all files
COPY . .

# Install dependencies
RUN pip install -r requirements.txt

# Start both the Flask web server and the Discord bot
CMD ["bash", "-c", "python3 web_server.py & python3 main.py"]
