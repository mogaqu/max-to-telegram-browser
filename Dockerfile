FROM python:3.12-slim

WORKDIR /app

# Системные зависимости для Playwright
RUN apt-get update && apt-get install -y \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем Chromium для Playwright
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

EXPOSE 10000

CMD ["python", "browser_bot.py"]