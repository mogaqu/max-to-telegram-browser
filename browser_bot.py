import os
import sys
import asyncio
import logging
import gc
import re
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

from server import run_in_background
run_in_background()

load_dotenv()

# ================= НАСТРОЙКИ =================
MAX_CHAT_URL = os.getenv("MAX_CHAT_URL")
AUTH_LOCAL_STORAGE = os.getenv("AUTH_LOCAL_STORAGE")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
TG_TOPIC_ID = os.getenv("TG_TOPIC_ID")
TG_API_URL = os.getenv("TG_API_URL")

if not all([MAX_CHAT_URL, AUTH_LOCAL_STORAGE, TG_BOT_TOKEN, TG_CHAT_ID]):
    logger.error("❌ ОШИБКА: Не заполнены обязательные поля в .env файле!")
    sys.exit(1)

if TG_TOPIC_ID and TG_TOPIC_ID.isdigit():
    TG_TOPIC_ID = int(TG_TOPIC_ID)
else:
    TG_TOPIC_ID = None

session = AiohttpSession(api=TelegramAPIServer.from_base(TG_API_URL)) if TG_API_URL else None
bot = Bot(token=TG_BOT_TOKEN, session=session)

# ========== ХРАНИЛИЩЕ ID ==========
MAX_SEEN_IDS = 5000
seen_ids = set()
first_run = True  # Флаг первого запуска


def add_seen_id(msg_id: str):
    global seen_ids
    if len(seen_ids) >= MAX_SEEN_IDS:
        seen_ids = set(list(seen_ids)[MAX_SEEN_IDS // 2:])
        logger.info(f"🧹 Очистка seen_ids, осталось: {len(seen_ids)}")
    seen_ids.add(msg_id)


def get_memory_mb() -> float:
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except:
        pass
    return 0


async def send_to_telegram(sender: str, text: str):
    msg = f"📨 *{sender}*:\n{text}"
    if len(msg) > 4000:
        msg = msg[:4000] + "…"
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
                add_seen_id(msg_id)
                continue

            if "присоединился(-ась)" in full_text or full_text.strip() in ("Вчера", "Сегодня"):
                add_seen_id(msg_id)
                continue

            sender_loc = block.locator("button.contact")
            sender = (await sender_loc.first.inner_text()) if await sender_loc.count() > 0 else "Кто-то"

            text_loc = block.locator("[class*='text']")
            texts = await text_loc.all_inner_texts() if await text_loc.count() > 0 else []
            valid = []
            for t in texts:
                t = t.strip()
                if not t:
                    continue
                if re.fullmatch(r"\d{1,2}:\d{2}", t):
                    continue
                if t == sender:
                    continue
                if t in ("Избранное", "Сохраните что-нибудь"):
                    continue
                valid.append(t)

            text = "\n".join(valid).strip()

            if text:
                await send_to_telegram(sender, text)

            add_seen_id(msg_id)

        except Exception as e:
            logger.error(f"Ошибка парсинга: {e}")


async def skip_visible_messages(page):
    """Помечает все видимые сообщения как прочитанные (только при первом запуске!)."""
    blocks = await page.locator("div.block[role='listitem']").all()
    count = 0
    for block in blocks:
        try:
            item = block.locator("xpath=ancestor::div[contains(@class,'item')][@data-index]").first
            idx = await item.get_attribute("data-index")
            if idx and idx not in seen_ids:
                add_seen_id(idx)
                count += 1
        except:
            pass
    return count


async def setup_page(p):
    """Создаёт браузер, авторизуется и открывает чат."""
    global first_run

    browser = await p.chromium.launch(
        headless=True,
        args=[
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-extensions",
            "--disable-background-networking",
            "--single-process",
            "--disable-cache",
            "--js-flags=--max-old-space-size=128",
        ]
    )

    context = await browser.new_context()
    page = await context.new_page()

    logger.info("Установка токена MAX...")
    await page.goto("https://web.max.ru/", wait_until="domcontentloaded")
    await asyncio.sleep(2)

    await page.evaluate(
        "([key, value]) => window.localStorage.setItem(key, value)",
        ["__oneme_auth", AUTH_LOCAL_STORAGE]
    )

    logger.info("Открываем MAX чат...")
    await page.goto(MAX_CHAT_URL, wait_until="domcontentloaded")

    logger.info("Ожидание загрузки чата (8 сек)...")
    await asyncio.sleep(8)

    # Пропускаем сообщения ТОЛЬКО при первом запуске
    if first_run:
        skipped = await skip_visible_messages(page)
        logger.info(f"✅ Первый запуск! Пропущено {skipped} старых сообщений")
        first_run = False
    else:
        # После перезапуска браузера — просто ждём и проверяем
        logger.info(f"✅ Браузер перезапущен. В памяти {len(seen_ids)} ID. Новые сообщения будут отправлены.")

    return browser, page


async def main():
    logger.info("🚀 Запуск Playwright → Telegram Bridge")

    while True:
        browser = None
        try:
            async with async_playwright() as p:
                browser, page = await setup_page(p)

                iterations = 0
                RELOAD_PAGE_EVERY = 600       # 30 мин
                RESTART_BROWSER_EVERY = 1800  # 1.5 часа
                LOG_STATS_EVERY = 100         # 5 мин
                MEMORY_LIMIT_MB = 450

                while True:
                    try:
                        await check_messages(page)
                        iterations += 1

                        if iterations % LOG_STATS_EVERY == 0:
                            gc.collect()
                            mem = get_memory_mb()
                            logger.info(f"📊 Итерация {iterations} | RAM: {mem:.0f} МБ | IDs: {len(seen_ids)}")

                            if mem > MEMORY_LIMIT_MB:
                                logger.warning(f"⚠️ RAM {mem:.0f} > {MEMORY_LIMIT_MB} МБ, перезапуск...")
                                break

                        # Перезагрузка страницы — НЕ пропускаем сообщения!
                        if iterations % RELOAD_PAGE_EVERY == 0 and iterations > 0:
                            logger.info("🔄 Перезагрузка страницы...")
                            await page.goto(MAX_CHAT_URL, wait_until="domcontentloaded")
                            await asyncio.sleep(5)
                            gc.collect()
                            logger.info("✅ Страница перезагружена, продолжаю мониторинг")

                        if iterations >= RESTART_BROWSER_EVERY:
                            logger.info("🔄 Плановый перезапуск браузера...")
                            break

                        await asyncio.sleep(3)

                    except Exception as e:
                        logger.error(f"Сбой в цикле: {e}")
                        await asyncio.sleep(5)

                        try:
                            await page.title()
                        except:
                            logger.error("💀 Страница мертва, перезапуск...")
                            break

        except Exception as e:
            logger.error(f"💀 Критическая ошибка: {e}")

        finally:
            if browser:
                try:
                    await browser.close()
                except:
                    pass
            gc.collect()
            logger.info("🧹 Браузер закрыт")

        logger.info("⏳ Перезапуск через 5 сек...")
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())