FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for translators (esp. for headless browsers if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # For Selenium or browser-based translators
    wget curl unzip gnupg ca-certificates \
    firefox-esr \
    libglib2.0-0 libnss3 libgconf-2-4 libx11-xcb1 \
    libxcomposite1 libxcursor1 libxdamage1 libxi6 libxtst6 \
    libxrandr2 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxss1 \
    libasound2 libdbus-glib-1-2 fonts-liberation xdg-utils \
    # For proxy support or extra tools
    netbase iproute2 \
    && wget -q https://github.com/mozilla/geckodriver/releases/download/v0.34.0/geckodriver-v0.34.0-linux64.tar.gz \
    && tar -xzf geckodriver-v0.34.0-linux64.tar.gz -C /usr/local/bin \
    && chmod +x /usr/local/bin/geckodriver \
    && rm geckodriver-v0.34.0-linux64.tar.gz \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip first
RUN pip install --upgrade pip

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install project
COPY . /app
