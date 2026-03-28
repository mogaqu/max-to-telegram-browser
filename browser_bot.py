import os
import sys
import asyncio
import logging
import re
from dotenv import load_dotenv
from playwright.async_api import async_playwright

# Импорты для работы с Telegram через Cloudflare Worker
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

from server import run_in_background
run_in_background()

# Загружаем переменные из .env
load_dotenv()

# ================= НАСТРОЙКИ ИЗ .ENV =================
MAX_CHAT_URL = os.getenv("MAX_CHAT_URL")
AUTH_LOCAL_STORAGE = os.getenv("AUTH_LOCAL_STORAGE")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
TG_TOPIC_ID = os.getenv("TG_TOPIC_ID")
TG_API_URL = os.getenv("TG_API_URL")

# Проверка, всё ли заполнено
if not all([MAX_CHAT_URL, AUTH_LOCAL_STORAGE, TG_BOT_TOKEN, TG_CHAT_ID]):
    logger.error("❌ ОШИБКА: Не заполнены обязательные поля в .env файле!")
    sys.exit(1)

# Преобразуем Topic ID в число, если он указан
if TG_TOPIC_ID and TG_TOPIC_ID.isdigit():
    TG_TOPIC_ID = int(TG_TOPIC_ID)
else:
    TG_TOPIC_ID = None
# =====================================================

# Подключаем бота через твой прокси-воркер
session = AiohttpSession(api=TelegramAPIServer.from_base(TG_API_URL)) if TG_API_URL else None
bot = Bot(token=TG_BOT_TOKEN, session=session)

seen_ids = set()

async def send_to_telegram(sender: str, text: str):
    msg = f"📨 *{sender}*:\n{text}"
    try:
        await bot.send_message(
            chat_id=TG_CHAT_ID,
            message_thread_id=TG_TOPIC_ID,
            text=msg,
            parse_mode="Markdown"
        )
        logger.info(f"✅ Переслано в TG: {sender}: {text[:30]}...")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки в TG: {e}")

async def check_messages(page):
    blocks = await page.locator("div.block[role='listitem']").all()

    for block in blocks:
        try:
            item = block.locator("xpath=ancestor::div[contains(@class,'item')][@data-index]").first
            msg_id = await item.get_attribute("data-index")
            if not msg_id or msg_id in seen_ids:
                continue

            full_text = await block.inner_text()
            if not full_text.strip():
                seen_ids.add(msg_id)
                continue

            # Игнор системных
            if "присоединился(-ась)" in full_text or "Вчера" == full_text.strip() or "Сегодня" == full_text.strip():
                seen_ids.add(msg_id)
                continue

            # Автор
            sender_loc = block.locator("button.contact")
            sender = (await sender_loc.first.inner_text()) if await sender_loc.count() > 0 else "Кто-то"

            # Текст
            text_loc = block.locator("[class*='text']")
            texts = await text_loc.all_inner_texts() if await text_loc.count() > 0 else []
            valid = []
            for t in texts:
                t = t.strip()
                if not t: continue
                if re.fullmatch(r"\d{1,2}:\d{2}", t): continue
                if t == sender: continue
                # Убираем системный мусор
                if t in ("Избранное", "Сохраните что-нибудь"): continue
                valid.append(t)

            text = "\n".join(valid).strip()

            # Отправка в ТГ
            if text:
                await send_to_telegram(sender, text)

            seen_ids.add(msg_id)

        except Exception as e:
            logger.error(f"Ошибка парсинга: {e}")

async def main():
    logger.info("🚀 Запуск Playwright → Telegram Bridge (через CF Worker)")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        logger.info("Установка токена MAX...")
        await page.goto("https://web.max.ru/", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        
        await page.evaluate(
            "([key, value]) => window.localStorage.setItem(key, value)", 
            ["__oneme_auth", AUTH_LOCAL_STORAGE]
        )
        
        logger.info(f"Открываем MAX чат...")
        await page.goto(MAX_CHAT_URL, wait_until="domcontentloaded")
        
        logger.info("Ожидание загрузки чата (8 сек)...")
        await asyncio.sleep(8)
        
        # --- ПРОПУСКАЕМ СТАРЫЕ СООБЩЕНИЯ ---
        initial_blocks = await page.locator("div.block[role='listitem']").all()
        for block in initial_blocks:
            try:
                item = block.locator("xpath=ancestor::div[contains(@class,'item')][@data-index]").first
                idx = await item.get_attribute("data-index")
                if idx: seen_ids.add(idx)
            except:
                pass
        
        logger.info(f"✅ Чат открыт! Пропущено {len(seen_ids)} старых сообщений. Жду новые...")
        
        # Основной цикл
        while True:
            try:
                await check_messages(page)
                await asyncio.sleep(3) # проверять каждые 3 сек
            except Exception as e:
                logger.error(f"Сбой в цикле: {e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())