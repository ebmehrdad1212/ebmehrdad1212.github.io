import os
import json
import time
import asyncio
import logging
from datetime import datetime
import pendulum
from PIL import Image, ImageDraw, ImageFont
import aiohttp
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.errors import FloodWaitError
import hashlib
import uuid
import re
from difflib import SequenceMatcher
import nest_asyncio

log_messages = []
nest_asyncio.apply()

class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

def pretty_print(message, type="info", details=None):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    prefix = f"{Colors.CYAN}[{timestamp}]{Colors.RESET}"
    if type == "success":
        output = f"{prefix} {Colors.GREEN}✓ {message}{Colors.RESET}"
        logging.info(f"✓ {message}")
    elif type == "warning":
        output = f"{prefix} {Colors.YELLOW}⚠ {message}{Colors.RESET}"
        logging.warning(f"⚠ {message}")
    elif type == "error":
        output = f"{prefix} {Colors.RED}✗ {message}{Colors.RESET}"
        logging.error(f"✗ {message}")
    else:
        output = f"{prefix} {Colors.BOLD}➜ {message}{Colors.RESET}"
        logging.info(f"➜ {message}")
    print(output)
    log_messages.append(output)
    if details:
        detail_output = f"{prefix} {Colors.BOLD}جزئیات: {details}{Colors.RESET}"
        print(detail_output)
        log_messages.append(detail_output)
        logging.info(f"جزئیات: {details}")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_config():
    pretty_print("بارگذاری تنظیمات...", "info")
    config_file = os.path.join(BASE_DIR, "config.json")
    if not os.path.exists(config_file):
        pretty_print("فایل کانفیگ یافت نشد.", "error")
        raise FileNotFoundError("فایل config.json یافت نشد.")
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
        config['api_id'] = int(os.getenv('API_ID', '0'))
        config['api_hash'] = os.getenv('API_HASH', '')
        config['gemini_api_key'] = os.getenv('GEMINI_API_KEY', '')
        pretty_print("تنظیمات بارگذاری شد.", "success")
        return config
    except Exception as e:
        pretty_print("خطا در بارگذاری تنظیمات.", "error", str(e))
        raise

def setup_logging(log_file):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(BASE_DIR, log_file), encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    pretty_print("تنظیمات لاگ فعال شد.", "success")

def ensure_files(config):
    pretty_print("بررسی فایل‌ها...", "info")
    os.makedirs(BASE_DIR, exist_ok=True)
    for file_key in ["session_file", "last_message_ids_file", "posted_content_file", "log_file"]:
        file_path = os.path.join(BASE_DIR, config[file_key])
        if not os.path.exists(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                if file_key.endswith('_file') and file_key != "session_file" and file_key != "log_file":
                    json.dump({}, f)
                else:
                    f.write("")
            pretty_print(f"فایل {file_path} ایجاد شد.", "success")

def is_advertisement(message_text, ad_keywords):
    if not message_text:
        return False
    return any(keyword in message_text.lower() for keyword in ad_keywords)

def truncate_to_last_sentence(text, max_length):
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_period = truncated.rfind('.')
    return truncated[:last_period + 1] if last_period != -1 else truncated + "..."

def append_signature(caption, signature):
    if not caption:
        return signature
    max_length = 1024 - len(signature) - 5
    if len(caption) > max_length:
        caption = truncate_to_last_sentence(caption, max_length)
    return f"{caption}\n{signature}"

async def get_client(api_id, api_hash, session_file):
    session_file_path = os.path.join(BASE_DIR, session_file)
    session_string = open(session_file_path, "r", encoding="utf-8").read().strip() if os.path.exists(session_file_path) else None
    client = TelegramClient(StringSession(session_string), api_id, api_hash, auto_reconnect=True)
    if not session_string:
        await client.start()
        with open(session_file_path, "w", encoding="utf-8") as f:
            f.write(client.session.save())
    pretty_print("کلاینت تلگرام آماده شد.", "success")
    return client

async def ensure_connected(client, max_retries=10, initial_delay=5):
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            if not client.is_connected():
                pretty_print(f"تلاش {attempt} برای اتصال...", "info")
                await client.connect()
                if client.is_connected():
                    pretty_print("اتصال برقرار شد.", "success")
                    return
            else:
                pretty_print("اتصال از قبل برقرار است.", "success")
                return
        except Exception as e:
            pretty_print(f"خطا در اتصال: {str(e)}", "error")
        await asyncio.sleep(delay)
        delay *= 2
    raise Exception("اتصال مجدد ناموفق بود.")

def load_last_message_ids(last_message_ids_file):
    file_path = os.path.join(BASE_DIR, last_message_ids_file)
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump({}, f)
    try:
        data = json.load(open(file_path, "r", encoding="utf-8"))
        pretty_print("شناسه‌های آخرین پیام‌ها بارگذاری شد.", "success")
        return data
    except Exception as e:
        pretty_print("خطا در بارگذاری شناسه‌ها.", "error", str(e))
        return {}

def save_last_message_ids(ids, last_message_ids_file):
    file_path = os.path.join(BASE_DIR, last_message_ids_file)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(ids, f)
        pretty_print("شناسه‌های آخرین پیام‌ها ذخیره شد.", "success")
    except Exception as e:
        pretty_print("خطا در ذخیره شناسه‌ها.", "error", str(e))

def load_posted_content(posted_content_file):
    file_path = os.path.join(BASE_DIR, posted_content_file)
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump([], f)
    try:
        data = set(tuple(item) for item in json.load(open(file_path, "r", encoding="utf-8")))
        pretty_print("محتوای ارسال‌شده بارگذاری شد.", "success")
        return data
    except Exception as e:
        pretty_print("خطا در بارگذاری محتوای ارسال‌شده.", "error", str(e))
        return set()

def save_posted_content(content, posted_content_file):
    file_path = os.path.join(BASE_DIR, posted_content_file)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(list(list(item) for item in content), f)
        pretty_print("محتوای ارسال‌شده ذخیره شد.", "success")
    except Exception as e:
        pretty_print("خطا در ذخیره محتوای ارسال‌شده.", "error", str(e))

def compute_file_hash(file_path):
    if not file_path:
        return None
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def is_similar_caption(new_caption, posted_captions, threshold=0.85):
    for old_caption in posted_captions:
        similarity = SequenceMatcher(None, new_caption, old_caption).ratio()
        if similarity >= threshold:
            return True
    return False

caption_cache = {}

async def rephrase_caption(original_caption, api_key, session, prompt_template):
    if original_caption in caption_cache:
        return caption_cache[original_caption]
    if not original_caption:
        return ""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": prompt_template.format(caption=original_caption)}]}]}
    try:
        async with session.post(url, headers=headers, json=data, timeout=30) as response:
            result = await response.json()
            rephrased = result['candidates'][0]['content']['parts'][0]['text'].strip()
            if len(rephrased) > 900:
                rephrased = truncate_to_last_sentence(rephrased, 900)
            caption_cache[original_caption] = rephrased
            pretty_print("کپشن بازنویسی شد.", "success")
            return rephrased
    except Exception as e:
        pretty_print("خطا در بازنویسی کپشن.", "error", str(e))
        return original_caption

CURRENCY_FLAGS = {
    'دلار آمریکا': '🇺🇸', 'یورو': '🇪🇺', 'پوند': '🇬🇧', 'دلار کانادا': '🇨🇦',
    'دلار استرالیا': '🇦🇺', 'ین ژاپن': '🇯🇵', 'درهم امارات': '🇦🇪', 'لیر ترکیه': '🇹🇷',
    'دینار عراق': '🇮🇶', 'منات آذربایجان': '🇦🇿', 'افغانی': '🇦🇫',
    'سکه امامی': '🌕', 'سکه طرح قدیم': '🌟', 'گرم طلا 18 عیار': '💫',
    'بیت‌کوین': '💰', 'اتریوم': '💎', 'تتر': '💲'
}

def process_currency_message(original_caption):
    if not original_caption.startswith("نرخ فروش #دلار، #ارز، #سکه و #طلا در بازار"):
        pretty_print("پیام نرخ ارز نیست.", "warning")
        return None
    currency_pattern = r"([💵💶💷🇨🇦🇦🇺💴🇦🇪🇹🇷🇮🇶🇦🇿🇦🇫])\s*([^:]+):\s*([\d,]+)\s*تومان\s*([\d,]+)?\s*(🔼|🔻|➖)\s*%([\d.+-]+)"
    coin_pattern = r"([🌕🌟💫])\s*([^:]+):\s*([\d,]+)\s*تومان\s*([\d,]+)?\s*(🔼|🔻|➖)\s*%([\d.+-]+)"
    crypto_pattern = r"([💲💸♦️✖️🔶⛓💎💥])\s*([^:]+):\s*([\d,.]+)\s*(تومان|🔻|🔼)?\s*([\d,]+)?\s*(🔼|🔻|➖)\s*%([\d.+-]+)"
    currencies = re.findall(currency_pattern, original_caption)
    coins = re.findall(coin_pattern, original_caption)
    cryptos = re.findall(crypto_pattern, original_caption)
    formatted_message = "\u200F<pre>\n📊 <b>نرخ لحظه‌ای بازار</b>\n\n"
    if currencies:
        formatted_message += "<b>💸 ارزها:</b>\n"
        for _, name, rate, change, direction, percent in currencies:
            flag = CURRENCY_FLAGS.get(name.strip(), '💵')
            formatted_message += f"{flag} {name}: {rate} تومان {change if change else '0'}{direction} ({percent}%)\n"
    if coins:
        formatted_message += "\n<b>🌟 سکه و طلا:</b>\n"
        for _, name, rate, change, direction, percent in coins:
            flag = CURRENCY_FLAGS.get(name.strip(), '🌕')
            formatted_message += f"{flag} {name}: {rate} تومان {change if change else '0'}{direction} ({percent}%)\n"
    if cryptos:
        formatted_message += "\n<b>💰 ارزهای دیجیتال:</b>\n"
        for _, name, rate, unit, change, direction, percent in cryptos:
            flag = CURRENCY_FLAGS.get(name.strip(), '💰')
            formatted_message += f"{flag} {name}: {rate} {unit if unit else 'تومان'} {change if change else '0'}{direction} ({percent}%)\n"
    update_time = re.search(r"⌚آخرین بروزرسانی:\s*(.*)", original_caption)
    if update_time:
        formatted_message += f"\n⌚ <b>به‌روزرسانی:</b> {update_time.group(1)}"
    formatted_message += "\n📈 نظرتون چیه؟\n</pre>"
    pretty_print("نرخ ارز پردازش شد.", "success")
    return formatted_message

def resize_image(file_path, max_width=1920, max_height=1080):
    try:
        with Image.open(file_path) as img:
            img = img.convert("RGBA")
            width, height = img.size
            if width > max_width or height > max_height:
                aspect_ratio = width / height
                if aspect_ratio > 1:
                    new_width = max_width
                    new_height = int(max_width / aspect_ratio)
                else:
                    new_height = max_height
                    new_width = int(max_height * aspect_ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            draw = ImageDraw.Draw(img)
            font_path = os.path.join(BASE_DIR, "fonts", "DejaVuSans-Bold.ttf")
            font = ImageFont.truetype(font_path, 20) if os.path.exists(font_path) else ImageFont.load_default()
            draw.text((10, 10), "@IranTechn", fill="white", font=font)
            if img.mode == "RGBA":
                img = img.convert("RGB")
            img.save(file_path, "JPEG", quality=85)
    except Exception as e:
        pretty_print("خطا در تغییر اندازه تصویر.", "error", str(e))

async def download_media(client, message, download_folder=os.path.join(BASE_DIR, "downloads")):
    if not message.media:
        return None
    os.makedirs(download_folder, exist_ok=True)
    file_name = f"media_{uuid.uuid4().hex[:8]}_{message.id}"
    file_path = os.path.join(download_folder, file_name)
    try:
        downloaded_file = await client.download_media(message, file_path)
        pretty_print(f"رسانه دانلود شد: {file_path}", "success")
        return downloaded_file
    except Exception as e:
        pretty_print("خطا در دانلود رسانه.", "error", str(e))
        return None

async def send_to_telegram(client, target_channel, caption, media_path=None):
    final_caption = append_signature(caption, config['signature'])
    if media_path and len(final_caption) > 1024:
        final_caption = final_caption[:1024].rstrip()
    try:
        await ensure_connected(client)
        if media_path:
            file_ext = os.path.splitext(media_path)[1].lower()
            if file_ext in [".jpg", ".jpeg", ".png"]:
                resize_image(media_path)
            await client.send_file(target_channel, media_path, caption=final_caption, parse_mode='html')
        else:
            await client.send_message(target_channel, final_caption, parse_mode='html')
        pretty_print("پیام با موفقیت ارسال شد.", "success")
        return True
    except FloodWaitError as e:
        pretty_print(f"منتظر {e.seconds} ثانیه...", "warning")
        await asyncio.sleep(e.seconds)
        return False
    except Exception as e:
        pretty_print("خطا در ارسال پیام.", "error", str(e))
        return False
    finally:
        if media_path and os.path.exists(media_path):
            os.remove(media_path)

class TelegramScraper:
    def __init__(self, client, source_channels, target_channel, session, config):
        self.client = client
        self.source_channels = source_channels
        self.target_channel = target_channel
        self.last_message_ids = load_last_message_ids(config['last_message_ids_file'])
        self.posted_content = load_posted_content(config['posted_content_file'])
        self.posted_captions = {item[0] for item in self.posted_content if item[0]}
        self.session = session
        self.config = config
        self.processed_message_ids = set()

    async def scrape_channel(self, channel_username):
        pretty_print(f"شروع اسکریپ {channel_username}", "info")
        last_id = int(self.last_message_ids.get(channel_username, 0))
        try:
            channel_entity = await self.client.get_entity(channel_username)
            messages = await self.client(GetHistoryRequest(
                peer=channel_entity, limit=10, offset_id=0, min_id=last_id, max_id=0, offset_date=None, add_offset=0, hash=0
            ))
            new_messages = [msg for msg in messages.messages if msg.id > last_id and (msg.message or msg.media) and msg.id not in self.processed_message_ids]
            pretty_print(f"تعداد پیام‌های جدید در {channel_username}: {len(new_messages)}", "info")
            for message in reversed(new_messages):
                if message.id in self.processed_message_ids:
                    pretty_print(f"پیام {message.id} قبلاً پردازش شده.", "warning")
                    continue
                original_caption = message.message if message.message else ""
                if len(original_caption) < self.config['min_message_length'] and not message.media:
                    pretty_print(f"پیام {message.id} کوتاه است.", "warning")
                    continue
                if is_advertisement(original_caption, self.config['ad_keywords']):
                    pretty_print(f"پیام {message.id} تبلیغاتی است.", "warning")
                    continue
                final_caption = None
                if channel_username == "@irancurrency":
                    final_caption = process_currency_message(original_caption)
                    if not final_caption:
                        pretty_print(f"پیام {message.id} نرخ ارز نیست.", "warning")
                        continue
                else:
                    final_caption = await rephrase_caption(original_caption, self.config['gemini_api_key'], self.session, self.config['prompt_template'])
                if is_similar_caption(final_caption, self.posted_captions, threshold=0.85):
                    pretty_print(f"پیام {message.id} مشابه پیام قبلی است (تشابه > 85%).", "warning")
                    continue
                media_path = await download_media(self.client, message)
                media_hash = compute_file_hash(media_path)
                key = (final_caption, media_hash)
                if key in self.posted_content:
                    pretty_print(f"محتوای {message.id} قبلاً ارسال شده.", "warning")
                    if media_path:
                        os.remove(media_path)
                    continue
                if await send_to_telegram(self.client, self.target_channel, final_caption, media_path):
                    self.posted_content.add(key)
                    self.posted_captions.add(final_caption)
                    self.processed_message_ids.add(message.id)
                    save_posted_content(self.posted_content, self.config['posted_content_file'])
                    self.last_message_ids[channel_username] = message.id
                    save_last_message_ids(self.last_message_ids, self.config['last_message_ids_file'])
                    pretty_print(f"پیام {message.id} ارسال شد.", "success")
                    await asyncio.sleep(self.config['post_delay_seconds'])
        except Exception as e:
            pretty_print(f"خطا در اسکریپ {channel_username}", "error", str(e))

    async def run_scraping(self):
        pretty_print("شروع فرآیند اسکریپینگ...", "info")
        await run_scraping_with_limit(self, max_concurrent_tasks=3)
        pretty_print("اسکریپینگ به پایان رسید.", "success")

async def run_scraping_with_limit(scraper, max_concurrent_tasks=3):
    sem = asyncio.Semaphore(max_concurrent_tasks)

    async def scrape_with_limit(channel):
        async with sem:
            await scraper.scrape_channel(channel)

    await asyncio.gather(*(scrape_with_limit(channel) for channel in scraper.source_channels))

async def run_bot():
    global config
    config = load_config()
    ensure_files(config)
    setup_logging(config['log_file'])

    client = await get_client(config['api_id'], config['api_hash'], config['session_file'])
    await ensure_connected(client)

    target_channel = await client.get_entity(config['telegram_channel_id'])
    async with aiohttp.ClientSession() as session:
        scraper = TelegramScraper(client, config['source_channel_usernames'], target_channel, session, config)
        await scraper.run_scraping()
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_bot())