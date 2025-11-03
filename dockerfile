# Use a stable Python version that includes audioop
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Copy only requirements first (for caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy your bot files
COPY . .

# Expose port for Flask web server
EXPOSE 8080

# Run both Flask web server and Discord bot
CMD ["sh", "-c", "python3 web_server.py & python3 main.py"]
