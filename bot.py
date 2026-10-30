"""
╔══════════════════════════════════╗
║   🛒 OGGY SITE CHKR - MAIN BOT  ║
╚══════════════════════════════════╝
Full Shopify site checker + scraper bot for Telegram.
"""

import asyncio
import html
import logging
import re
import random
import time
import io
import os

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText, SendDocument, SendMessage
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# ─────────────────── CONFIGURATION ───────────────────
BOT_TOKEN   = os.getenv("BOT_TOKEN", "8558886316:AAG3qGKnqX_o2nBb0NVRlM4E8B4oxRpCzKo")
OWNER_ID    = int(os.getenv("OWNER_ID", "0"))  # set via env or hardcode
BOT_NAME    = "OGGY SITE CHKR"
WATERMARK   = "🛒 OGGY SITE CHKR"

# Price ranges for categorization
PRICE_RANGES = [
    (0,    5,   "0$-5$"),
    (5,    10,  "5$-10$"),
    (10,   20,  "10$-20$"),
    (20,   50,  "20$-50$"),
    (50,   100, "50$-100$"),
    (100,  999, "100$+"),
]

# ─────────────────── LOGGING ───────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s]: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("OggySiteChkr")

# ─────────────────── EMOJI / UI ───────────────────
DEAD_EMOJI    = ["❌", "🔴", "🛑"]
WORKING_EMOJI = ["✅", "🟢"]
ANY_EMOJI     = ["⚡", "🔒", "🏷", "👤", "🤖", "💎", "📜", "📂", "📢", "👥",
                 "👑", "⚙️", "🌐", "⏱", "📊", "📦", "⏳", "🗑", "🔄", "🔙",
                 "📥", "🛒", "💰", "🔍", "📋", "🧹"]

CYBER_QUOTES = [
    "Speed is the essence of war. — Sun Tzu",
    "Excellence is not an act, but a habit. — Aristotle",
    "The quieter you become, the more you are able to hear. — Anonymous",
    "Do or do not. There is no try. — Yoda",
    "Patience, persistence and perspiration make an unbeatable combination. — Napoleon Hill",
]

def create_progress_bar(percentage: float, length: int = 12) -> str:
    filled = int(round(length * percentage / 100))
    return "█" * filled + "▒" * (length - filled)

def box(title: str, lines: list) -> str:
    top = "╔══════════════════════════╗"
    mid = f"║  {title.center(24)}  ║"
    bot = "╚══════════════════════════╝"
    return "\n".join([top, mid, bot, ""] + lines)

# ─────────────────── BOT & MIDDLEWARE ───────────────────
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
router = Router()

# ─────────────────── GLOBAL STATE ───────────────────
bot_active     = True
known_users    = set()
start_uptime   = time.time()
active_sessions: dict[int, dict] = {}   # user_id → session info for stop-support

# ─────────────────── FSM STATES ───────────────────
class CheckState(StatesGroup):
    waiting_for_price = State()
    waiting_for_export_price = State()

class ScrapeState(StatesGroup):
    waiting_for_keyword = State()
    waiting_for_count   = State()

# ═══════════════════════════════════════════════════════
#  SHOPIFY CHECKER CORE
# ═══════════════════════════════════════════════════════

async def get_lowest_price(site: str, session: aiohttp.ClientSession) -> float | None:
    """Fetch the lowest product price from a Shopify store."""
    site = site.strip().rstrip("/")
    if not site.startswith("http"):
        site = "https://" + site
    try:
        url = f"{site}/products.json?limit=250&sort_by=price-ascending"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15), ssl=False) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            products = data.get("products", [])
            prices = []
            for p in products:
                for v in p.get("variants", []):
                    try:
                        prices.append(float(v["price"]))
                    except Exception:
                        pass
            if prices:
                return min(prices)
    except Exception:
        pass
    return None

async def check_has_captcha(site: str, session: aiohttp.ClientSession) -> bool:
    """Check if checkout page has captcha."""
    site = site.strip().rstrip("/")
    if not site.startswith("http"):
        site = "https://" + site
    captcha_patterns = [
        r"recaptcha", r"hcaptcha", r"turnstile", r"captcha",
        r"cf-turnstile", r"g-recaptcha"
    ]
    try:
        urls_to_check = [
            f"{site}/checkout",
            f"{site}/cart",
        ]
        for url in urls_to_check:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12),
                                   ssl=False, allow_redirects=True) as resp:
                text = (await resp.text()).lower()
                for pat in captcha_patterns:
                    if re.search(pat, text):
                        return True
    except Exception:
        pass
    return False

def is_shopify_site(domain: str) -> bool:
    """Basic heuristic – full confirmation done via products.json 200 check."""
    return True  # We validate via products.json fetch

async def check_single_site(site: str, session: aiohttp.ClientSession) -> dict:
    """Full check: is Shopify, has captcha, lowest price."""
    result = {
        "site": site,
        "shopify": False,
        "captcha": False,
        "price": None,
        "error": None,
    }
    try:
        price = await get_lowest_price(site, session)
        if price is not None:
            result["shopify"] = True
            result["price"]   = price
            result["captcha"] = await check_has_captcha(site, session)
        else:
            result["error"] = "Not Shopify or unreachable"
    except Exception as e:
        result["error"] = str(e)[:80]
    return result

def categorize_price(price: float) -> str:
    for lo, hi, label in PRICE_RANGES:
        if lo <= price < hi:
            return label
    return "100$+"

# ═══════════════════════════════════════════════════════
#  SHOPIFY SCRAPER CORE
# ═══════════════════════════════════════════════════════

GOOGLE_DORKS = [
    'site:myshopify.com "{kw}"',
    '"{kw}" shopify inurl:products',
    'inurl:".myshopify.com" "{kw}"',
    '"{kw}" site:shop.app',
    '"{kw}" powered by shopify',
]

async def scrape_shopify_sites(keyword: str, want: int, on_progress=None) -> list[dict]:
    """
    Scrape Google for Shopify sites matching keyword, then verify each.
    Returns list of {site, price, title} dicts.
    """
    from scraper import search_google_for_shopify
    return await search_google_for_shopify(keyword, want, on_progress)

# ═══════════════════════════════════════════════════════
#  URL / TEXT HELPERS
# ═══════════════════════════════════════════════════════

def extract_links(text: str) -> list[str]:
    """Extract URLs/domains from raw text."""
    url_pattern = re.compile(
        r'(?:https?://)?(?:www\.)?'
        r'([a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'
        r'(?:\.[a-zA-Z]{2,})+(?:/[^\s]*)?)',
        re.IGNORECASE
    )
    raw = url_pattern.findall(text)
    seen = set()
    out = []
    for match in raw:
        domain = match.strip().rstrip("/.,;:\"'")
        if "." not in domain:
            continue
        if domain not in seen:
            seen.add(domain)
            out.append(domain)
    return out

def clean_txt(text: str) -> list[str]:
    """Strip all non-link text, return only domains/URLs."""
    return extract_links(text)

def group_by_price(results: list[dict]) -> dict:
    groups: dict[str, list] = {}
    for r in results:
        if r.get("shopify") and r.get("price") is not None:
            label = categorize_price(r["price"])
            groups.setdefault(label, []).append(r)
    return groups

# ═══════════════════════════════════════════════════════
#  /start
# ═══════════════════════════════════════════════════════

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    known_users.add(uid)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Help & Commands", callback_data="help"),
            InlineKeyboardButton(text="📊 Stats",           callback_data="stats"),
        ],
        [
            InlineKeyboardButton(text="🔍 Scrape Sites",   callback_data="scrape_start"),
        ],
    ])
    if uid == OWNER_ID:
        kb.inline_keyboard.append(
            [InlineKeyboardButton(text="👑 Admin Panel", callback_data="open_admin")]
        )

    quote = random.choice(CYBER_QUOTES)
    text = (
        f"╔══════════════════════════╗\n"
        f"║   🛒 𝑶𝑮𝑮𝒀 𝑺𝑰𝑻𝑬 𝑪𝑯𝑲𝑹   ║\n"
        f"╚══════════════════════════╝\n\n"
        f"👤 Operator: <b>{html.escape(message.from_user.first_name)}</b>\n"
        f"💎 Status: Online & Operational\n\n"
        f"📜 {quote}\n\n"
        f"────────────────────────────\n"
        f"<b>How to use:</b>\n"
        f"• Send a <code>.txt</code> file OR paste links to check sites\n"
        f"• Reply to any text/file with /check to check links\n"
        f"• Reply with /cleantxt to extract only links\n"
        f"• Reply with /cat to categorize by price\n"
        f"• /scrape to scrape Shopify sites from Google\n"
        f"• /export to export a specific price tier\n"
        f"\n{WATERMARK}"
    )
    await message.answer(text, reply_markup=kb)

# ═══════════════════════════════════════════════════════
#  /help
# ═══════════════════════════════════════════════════════

@router.message(Command("help"))
@router.callback_query(F.data == "help")
async def cmd_help(event):
    text = (
        "╔══════════════════════════╗\n"
        "║   📋 𝑪𝑶𝑴𝑴𝑨𝑵𝑫𝑺 𝑳𝑰𝑺𝑻    ║\n"
        "╚══════════════════════════╝\n\n"
        "<b>Core Commands:</b>\n"
        "/start — Launch bot & welcome screen\n"
        "/check — Reply to msg/file to check sites\n"
        "/cleantxt — Reply to msg/file to extract links only\n"
        "/cat — Reply to msg/file to categorize sites by price\n"
        "/scrape — Scrape Shopify sites from Google\n"
        "/export — Export sites of a specific price (e.g. /export 1)\n"
        "/stop — Stop current running check session\n"
        "/cancel — Cancel current operation\n\n"
        "<b>How it works:</b>\n"
        "🔹 Send .txt file → auto checks all sites\n"
        "🔹 /check reply → checks sites in that message\n"
        "🔹 /cleantxt reply → extracts clean domain list\n"
        "🔹 /cat reply → groups sites by price tier\n"
        "🔹 /scrape → enter keyword → get Shopify sites\n"
        "🔹 /export 5 → get all sites priced at $5 or under\n\n"
        "<b>Price Tiers:</b>\n"
        "0$-5$ · 5$-10$ · 10$-20$ · 20$-50$ · 50$-100$ · 100$+\n\n"
        f"{WATERMARK}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="back_start")]
    ])
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb)

@router.callback_query(F.data == "back_start")
async def back_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await cmd_start(cb.message, state)

# ═══════════════════════════════════════════════════════
#  /stats (public)
# ═══════════════════════════════════════════════════════

@router.callback_query(F.data == "stats")
async def cb_stats(cb: CallbackQuery):
    uptime_sec = int(time.time() - start_uptime)
    h, rem = divmod(uptime_sec, 3600)
    m, s   = divmod(rem, 60)
    text = (
        "╔══════════════════════════╗\n"
        "║     📊 𝑩𝑶𝑻 𝑺𝑻𝑨𝑻𝑺       ║\n"
        "╚══════════════════════════╝\n\n"
        f"👥 Total Users: <b>{len(known_users)}</b>\n"
        f"⏱ Uptime: <b>{h}h {m}m {s}s</b>\n"
        f"⚡ Engine: Async Rocket\n"
        f"🌐 Active Sessions: <b>{len(active_sessions)}</b>\n\n"
        f"{WATERMARK}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data="back_start")]
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

# ═══════════════════════════════════════════════════════
#  ADMIN PANEL
# ═══════════════════════════════════════════════════════

@router.message(Command("admin"))
@router.callback_query(F.data == "open_admin")
async def cmd_admin(event):
    uid = event.from_user.id
    if uid != OWNER_ID and OWNER_ID != 0:
        if isinstance(event, CallbackQuery):
            await event.answer("⚠️ Unauthorized.", show_alert=True)
        return

    status = "🟢 ACTIVE" if bot_active else "🔴 STOPPED"
    uptime_sec = int(time.time() - start_uptime)
    h, rem = divmod(uptime_sec, 3600)
    m, s   = divmod(rem, 60)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🛑 Stop Bot" if bot_active else "🟢 Start Bot",
                callback_data="toggle_bot"
            )
        ],
        [
            InlineKeyboardButton(text="📊 Stats", callback_data="admin_stats"),
            InlineKeyboardButton(text="🔄 Refresh", callback_data="open_admin"),
        ],
        [InlineKeyboardButton(text="🔙 Back", callback_data="back_start")],
    ])

    text = (
        "╔══════════════════════════╗\n"
        "║  👑 𝑶𝑾𝑵𝑬𝑹 𝑪𝑶𝑵𝑻𝑹𝑶𝑳 𝑪𝑬𝑵𝑻𝑬𝑹  ║\n"
        "╚══════════════════════════╝\n\n"
        f"⚙️ Status: <b>{status}</b>\n"
        f"👥 Users: <b>{len(known_users)}</b>\n"
        f"🌐 Active Sessions: <b>{len(active_sessions)}</b>\n"
        f"⏱ Uptime: <b>{h}h {m}m {s}s</b>\n\n"
        f"{WATERMARK}"
    )

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb)

@router.callback_query(F.data == "toggle_bot")
async def toggle_bot(cb: CallbackQuery):
    global bot_active
    if cb.from_user.id != OWNER_ID and OWNER_ID != 0:
        return
    bot_active = not bot_active
    await cmd_admin(cb)

@router.callback_query(F.data == "admin_stats")
async def admin_stats(cb: CallbackQuery):
    if cb.from_user.id != OWNER_ID and OWNER_ID != 0:
        return
    uptime_sec = int(time.time() - start_uptime)
    h, rem = divmod(uptime_sec, 3600)
    m, s   = divmod(rem, 60)
    text = (
        "╔══════════════════════════╗\n"
        "║  📊 𝑺𝒀𝑺𝑻𝑬𝑴 𝑨𝑵𝑨𝑳𝒀𝑻𝑰𝑪𝑺  ║\n"
        "╚══════════════════════════╝\n\n"
        f"👥 Users: <b>{len(known_users)}</b>\n"
        f"🌐 Active Sessions: <b>{len(active_sessions)}</b>\n"
        f"⏱ Uptime: <b>{h}h {m}m {s}s</b>\n\n"
        f"{WATERMARK}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Admin", callback_data="open_admin")]
    ])
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()

# ═══════════════════════════════════════════════════════
#  /stop — stop current session
# ═══════════════════════════════════════════════════════

@router.message(Command("stop"))
async def cmd_stop(message: Message):
    uid = message.from_user.id
    if uid in active_sessions:
        active_sessions[uid]["stop"] = True
        await message.answer("🛑 Stop signal sent. Finishing current item and halting…")
    else:
        await message.answer("⚠️ No active session found.")

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Operation cancelled.")

# ═══════════════════════════════════════════════════════
#  AUTO FILE HANDLER (.txt → auto check)
# ═══════════════════════════════════════════════════════

@router.message(F.document)
async def handle_document(message: Message, state: FSMContext):
    if not bot_active:
        await message.answer("⚠️ Bot engine is offline.")
        return
    if not message.document.file_name.endswith(".txt"):
        await message.answer("⚠️ Please send a .txt file.")
        return
    raw = await _read_file(message)
    if not raw:
        return
    sites = extract_links(raw)
    if not sites:
        await message.answer("⚠️ No valid links found in file.")
        return
    await _run_check(message, sites)

# ═══════════════════════════════════════════════════════
#  /check — reply to message or file
# ═══════════════════════════════════════════════════════

@router.message(Command("check"))
async def cmd_check(message: Message, state: FSMContext):
    if not bot_active:
        await message.answer("⚠️ Bot engine is offline.")
        return

    text_to_parse = None

    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.document and replied.document.file_name.endswith(".txt"):
            raw = await _read_file(replied)
            text_to_parse = raw
        elif replied.text:
            text_to_parse = replied.text
        elif replied.caption:
            text_to_parse = replied.caption
    else:
        # Check if command has inline text: /check site1.com site2.com
        parts = message.text.split(None, 1)
        if len(parts) > 1:
            text_to_parse = parts[1]

    if not text_to_parse:
        await message.answer("⚠️ Reply to a message or file containing sites, or send: /check site1.com site2.com")
        return

    sites = extract_links(text_to_parse)
    if not sites:
        await message.answer("⚠️ No valid links found.")
        return

    await _run_check(message, sites)

# ═══════════════════════════════════════════════════════
#  /cleantxt — reply to extract only links
# ═══════════════════════════════════════════════════════

@router.message(Command("cleantxt"))
async def cmd_cleantxt(message: Message):
    text_to_parse = None
    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.document and replied.document.file_name.endswith(".txt"):
            raw = await _read_file(replied)
            text_to_parse = raw
        elif replied.text:
            text_to_parse = replied.text
        elif replied.caption:
            text_to_parse = replied.caption
    else:
        parts = message.text.split(None, 1)
        if len(parts) > 1:
            text_to_parse = parts[1]

    if not text_to_parse:
        await message.answer("⚠️ Reply to a message or file to clean it.")
        return

    links = clean_txt(text_to_parse)
    if not links:
        await message.answer("⚠️ No links found in the text.")
        return

    cleaned = "\n".join(links)
    file_bytes = cleaned.encode("utf-8")
    doc = BufferedInputFile(file_bytes, filename="cleaned_links.txt")
    caption = (
        f"🧹 <b>Clean Links</b>\n"
        f"📦 Found: <b>{len(links)}</b> links\n\n"
        f"{WATERMARK}"
    )
    await message.answer_document(doc, caption=caption)

# ═══════════════════════════════════════════════════════
#  /cat — categorize sites by price
# ═══════════════════════════════════════════════════════

@router.message(Command("cat"))
async def cmd_cat(message: Message, state: FSMContext):
    text_to_parse = None
    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.document and replied.document.file_name.endswith(".txt"):
            raw = await _read_file(replied)
            text_to_parse = raw
        elif replied.text:
            text_to_parse = replied.text
    else:
        parts = message.text.split(None, 1)
        if len(parts) > 1:
            text_to_parse = parts[1]

    if not text_to_parse:
        await message.answer("⚠️ Reply to a message or file with sites to categorize.")
        return

    sites = extract_links(text_to_parse)
    if not sites:
        await message.answer("⚠️ No valid links found.")
        return

    status_msg = await message.answer(
        f"📊 Categorizing <b>{len(sites)}</b> sites by price…\n"
        f"This will take a moment ⏳"
    )
    results = await _do_check(message.from_user.id, sites, status_msg)

    groups = group_by_price(results)
    if not groups:
        await status_msg.edit_text("⚠️ No Shopify sites with prices found.")
        return

    summary = (
        "╔══════════════════════════╗\n"
        "║  📊 𝑷𝑹𝑰𝑪𝑬 𝑪𝑨𝑻𝑬𝑮𝑶𝑹𝑰𝑬𝑺   ║\n"
        "╚══════════════════════════╝\n\n"
    )
    for lo, hi, label in PRICE_RANGES:
        count = len(groups.get(label, []))
        if count:
            summary += f"💰 <b>{label}</b>: {count} sites\n"
    summary += f"\n{WATERMARK}"

    await status_msg.edit_text(summary)

    # Send a file per category
    for lo, hi, label in PRICE_RANGES:
        group = groups.get(label, [])
        if group:
            lines = [f"{r['site']} | ${r['price']:.2f}" for r in group]
            file_bytes = "\n".join(lines).encode("utf-8")
            fname = f"category_{label.replace('$', 'usd').replace('-','_')}.txt"
            doc = BufferedInputFile(file_bytes, filename=fname)
            await message.answer_document(doc, caption=f"💰 <b>{label}</b> — {len(group)} sites")

# ═══════════════════════════════════════════════════════
#  /export — export sites of a specific price
# ═══════════════════════════════════════════════════════

@router.message(Command("export"))
async def cmd_export(message: Message, state: FSMContext):
    parts = message.text.strip().split(None, 1)
    if len(parts) < 2:
        await message.answer(
            "💰 Enter the max price you want to export:\n"
            "Example: <code>/export 5</code> → all sites $5 and under\n"
            "Or: <code>/export 1</code> for $1 and under\n\n"
            "Reply to a .txt file of checked sites with this command."
        )
        await state.set_state(CheckState.waiting_for_export_price)
        return

    # /export 5 with reply to file
    try:
        max_price = float(parts[1].strip().replace("$", ""))
    except ValueError:
        await message.answer("⚠️ Invalid price. Example: /export 5")
        return

    text_to_parse = None
    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.document:
            raw = await _read_file(replied)
            text_to_parse = raw
        elif replied.text:
            text_to_parse = replied.text

    if not text_to_parse:
        await message.answer(
            f"⚠️ Reply to a .txt file of sites with /export {max_price}\n"
            "The bot will check and export sites ≤ ${max_price}"
        )
        return

    sites = extract_links(text_to_parse)
    if not sites:
        await message.answer("⚠️ No links found.")
        return

    status_msg = await message.answer(f"🔍 Checking {len(sites)} sites for price ≤ ${max_price}…")
    results = await _do_check(message.from_user.id, sites, status_msg)

    filtered = [r for r in results if r.get("shopify") and r.get("price") is not None and r["price"] <= max_price]

    if not filtered:
        await status_msg.edit_text(f"⚠️ No Shopify sites found with price ≤ ${max_price}")
        return

    lines = [f"{r['site']} | ${r['price']:.2f}" for r in filtered]
    file_bytes = "\n".join(lines).encode("utf-8")
    doc = BufferedInputFile(file_bytes, filename=f"sites_under_{max_price}usd.txt")
    caption = (
        f"💰 <b>Sites ≤ ${max_price}</b>\n"
        f"📦 Count: <b>{len(filtered)}</b>\n\n"
        f"{WATERMARK}"
    )
    await status_msg.delete()
    await message.answer_document(doc, caption=caption)

# ═══════════════════════════════════════════════════════
#  /scrape — scrape Google for Shopify sites
# ═══════════════════════════════════════════════════════

@router.message(Command("scrape"))
@router.callback_query(F.data == "scrape_start")
async def cmd_scrape(event, state: FSMContext = None):
    msg = event.message if isinstance(event, CallbackQuery) else event
    if state:
        await state.set_state(ScrapeState.waiting_for_keyword)
    text = (
        "🔍 <b>Shopify Site Scraper</b>\n\n"
        "Send me a <b>keyword</b> to scrape Shopify sites from Google.\n\n"
        "Examples:\n"
        "• <code>phone case</code>\n"
        "• <code>sticker</code>\n"
        "• <code>keychain</code>\n"
        "• <code>cheap clothing</code>\n\n"
        "I'll find Shopify stores and check their lowest prices! 🛒"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="back_start")]
    ])
    if isinstance(event, CallbackQuery):
        await msg.edit_text(text, reply_markup=kb)
        await event.answer()
    else:
        await msg.answer(text, reply_markup=kb)

@router.message(ScrapeState.waiting_for_keyword)
async def scrape_got_keyword(message: Message, state: FSMContext):
    keyword = message.text.strip()
    if not keyword or len(keyword) < 2:
        await message.answer("⚠️ Keyword too short. Try again:")
        return
    await state.update_data(keyword=keyword)
    await state.set_state(ScrapeState.waiting_for_count)
    await message.answer(
        f"✅ Keyword: <b>{html.escape(keyword)}</b>\n\n"
        "How many sites do you want? (10-200)\n"
        "Recommended: <code>50</code>"
    )

@router.message(ScrapeState.waiting_for_count)
async def scrape_got_count(message: Message, state: FSMContext):
    try:
        count = int(message.text.strip())
        count = max(10, min(200, count))
    except ValueError:
        await message.answer("⚠️ Send a number (10-200):")
        return

    data = await state.get_data()
    keyword = data.get("keyword", "shopify")
    await state.clear()

    status_msg = await message.answer(
        f"╔══════════════════════════╗\n"
        f"║  🔍 𝑺𝑪𝑹𝑨𝑷𝑰𝑵𝑮 𝑮𝑶𝑶𝑮𝑳𝑬  ║\n"
        f"╚══════════════════════════╝\n\n"
        f"🔑 Keyword: <b>{html.escape(keyword)}</b>\n"
        f"📦 Target: <b>{count}</b> sites\n"
        f"⏳ Scraping in progress…\n\n"
        f"{WATERMARK}"
    )

    uid = message.from_user.id
    active_sessions[uid] = {"stop": False, "type": "scrape"}

    try:
        from scraper import search_google_for_shopify
        found = []
        done  = [0]

        async def on_progress(site_info: dict):
            found.append(site_info)
            done[0] += 1
            if done[0] % 5 == 0 or done[0] == count:
                pct = done[0] / count * 100
                bar = create_progress_bar(pct)
                try:
                    await status_msg.edit_text(
                        f"╔══════════════════════════╗\n"
                        f"║  🔍 𝑺𝑪𝑹𝑨𝑷𝑰𝑵𝑮 𝑮𝑶𝑶𝑮𝑳𝑬  ║\n"
                        f"╚══════════════════════════╝\n\n"
                        f"🔑 Keyword: <b>{html.escape(keyword)}</b>\n"
                        f"[{bar}] {pct:.0f}%\n"
                        f"✅ Found: <b>{len(found)}</b>\n\n"
                        f"{WATERMARK}"
                    )
                except Exception:
                    pass

        results = await search_google_for_shopify(keyword, count, on_progress,
                                                   stop_ref=active_sessions[uid])

    except Exception as e:
        logger.error(f"Scrape error: {e}")
        results = []

    finally:
        active_sessions.pop(uid, None)

    if not results:
        await status_msg.edit_text(
            "⚠️ No Shopify sites found. Try a different keyword."
        )
        return

    # Build output files
    all_lines   = [f"{r['site']} | ${r['price']:.2f} | {r.get('title','')}" for r in results]
    clean_lines = [r["site"] for r in results]

    groups = {}
    for r in results:
        label = categorize_price(r["price"])
        groups.setdefault(label, []).append(r)

    summary = (
        f"╔══════════════════════════╗\n"
        f"║  🔍 𝑺𝑪𝑹𝑨𝑷𝑬 𝑹𝑬𝑺𝑼𝑳𝑻𝑺  ║\n"
        f"╚══════════════════════════╝\n\n"
        f"🔑 Keyword: <b>{html.escape(keyword)}</b>\n"
        f"📦 Sites Found: <b>{len(results)}</b>\n\n"
        f"<b>Price Breakdown:</b>\n"
    )
    for lo, hi, label in PRICE_RANGES:
        cnt = len(groups.get(label, []))
        if cnt:
            summary += f"💰 {label}: {cnt}\n"
    summary += f"\n{WATERMARK}"

    await status_msg.edit_text(summary)

    # Send full results file
    doc = BufferedInputFile("\n".join(all_lines).encode(), filename=f"scraped_{keyword[:20]}.txt")
    await message.answer_document(doc, caption=f"📂 All scraped sites ({len(results)})")

    # Send clean domains file
    doc2 = BufferedInputFile("\n".join(clean_lines).encode(), filename=f"clean_{keyword[:20]}.txt")
    await message.answer_document(doc2, caption="🧹 Clean domains only")

    # Send per-category
    for lo, hi, label in PRICE_RANGES:
        group = groups.get(label, [])
        if group:
            lines = [f"{r['site']} | ${r['price']:.2f}" for r in group]
            fname = f"{label.replace('$','usd').replace('-','_')}_{keyword[:10]}.txt"
            doc3 = BufferedInputFile("\n".join(lines).encode(), filename=fname)
            await message.answer_document(doc3, caption=f"💰 {label} — {len(group)} sites")

# ═══════════════════════════════════════════════════════
#  CORE CHECK RUNNER
# ═══════════════════════════════════════════════════════

async def _run_check(message: Message, sites: list[str]):
    uid = message.from_user.id
    known_users.add(uid)

    status_msg = await message.answer(
        f"╔══════════════════════════╗\n"
        f"║  ⚡ 𝑳𝑨𝑼𝑵𝑪𝑯𝑰𝑵𝑮 𝑪𝑯𝑬𝑪𝑲𝑬𝑹  ║\n"
        f"╚══════════════════════════╝\n\n"
        f"📦 Sites to check: <b>{len(sites)}</b>\n"
        f"⏳ Initializing…\n\n"
        f"💡 Send /stop to halt early and get partial results.\n\n"
        f"{WATERMARK}"
    )

    results = await _do_check(uid, sites, status_msg)

    # Partial results if stopped early
    shopify_ok   = [r for r in results if r.get("shopify")]
    no_captcha   = [r for r in shopify_ok if not r.get("captcha")]
    has_captcha  = [r for r in shopify_ok if r.get("captcha")]
    not_shopify  = [r for r in results if not r.get("shopify")]
    remaining    = [s for s in sites if s not in [r["site"] for r in results]]

    groups = group_by_price(no_captcha)

    # Determine if stopped early
    stopped_early = (active_sessions.get(uid, {}).get("stop") or
                     len(results) < len(sites))
    active_sessions.pop(uid, None)

    summary = (
        f"╔══════════════════════════╗\n"
        f"║   📊 𝑪𝑯𝑬𝑪𝑲 𝑹𝑬𝑺𝑼𝑳𝑻𝑺   ║\n"
        f"╚══════════════════════════╝\n\n"
        f"📦 Total Sent: <b>{len(sites)}</b>\n"
        f"✅ Checked: <b>{len(results)}</b>\n"
        f"🛒 Shopify Sites: <b>{len(shopify_ok)}</b>\n"
        f"🔓 No Captcha: <b>{len(no_captcha)}</b>\n"
        f"🔒 Has Captcha: <b>{len(has_captcha)}</b>\n"
        f"❌ Not Shopify: <b>{len(not_shopify)}</b>\n"
    )
    if remaining:
        summary += f"⏭ Unchecked: <b>{len(remaining)}</b>\n"
    if stopped_early:
        summary += "\n⚠️ <b>Stopped early — partial results below.</b>\n"

    if no_captcha:
        summary += "\n<b>💰 Price Breakdown (clean sites):</b>\n"
        for lo, hi, label in PRICE_RANGES:
            cnt = len(groups.get(label, []))
            if cnt:
                summary += f"  • {label}: {cnt}\n"

    summary += f"\n{WATERMARK}"

    try:
        await status_msg.edit_text(summary)
    except Exception:
        await message.answer(summary)

    # Send result files
    if no_captcha:
        lines = [f"{r['site']} | ${r['price']:.2f}" for r in no_captcha]
        doc = BufferedInputFile("\n".join(lines).encode(), filename="clean_sites.txt")
        await message.answer_document(doc, caption=f"✅ Clean Shopify Sites ({len(no_captcha)})")

    if has_captcha:
        lines = [f"{r['site']} | ${r['price']:.2f}" for r in has_captcha]
        doc = BufferedInputFile("\n".join(lines).encode(), filename="captcha_sites.txt")
        await message.answer_document(doc, caption=f"🔒 Sites with Captcha ({len(has_captcha)})")

    if not_shopify:
        lines = [r["site"] for r in not_shopify]
        doc = BufferedInputFile("\n".join(lines).encode(), filename="not_shopify.txt")
        await message.answer_document(doc, caption=f"❌ Non-Shopify Sites ({len(not_shopify)})")

    if remaining:
        doc = BufferedInputFile("\n".join(remaining).encode(), filename="remaining_sites.txt")
        await message.answer_document(doc, caption=f"⏭ Unchecked Sites ({len(remaining)})")

    # Per-category files for clean sites
    for lo, hi, label in PRICE_RANGES:
        group = groups.get(label, [])
        if group:
            lines = [f"{r['site']} | ${r['price']:.2f}" for r in group]
            fname = f"category_{label.replace('$','usd').replace('-','_')}.txt"
            doc = BufferedInputFile("\n".join(lines).encode(), filename=fname)
            await message.answer_document(doc, caption=f"💰 {label} — {len(group)} clean sites")

async def _do_check(uid: int, sites: list[str], status_msg: Message) -> list[dict]:
    """Run the actual check with progress updates. Respects stop signal."""
    active_sessions[uid] = {"stop": False, "type": "check"}
    results = []
    total   = len(sites)
    done    = 0
    semaphore = asyncio.Semaphore(20)

    async def check_one(site: str):
        nonlocal done
        if active_sessions.get(uid, {}).get("stop"):
            return
        async with semaphore:
            async with aiohttp.ClientSession() as sess:
                r = await check_single_site(site, sess)
            results.append(r)
            done += 1

    tasks = [check_one(s) for s in sites]

    async def update_progress():
        while done < total and not active_sessions.get(uid, {}).get("stop"):
            await asyncio.sleep(3)
            pct = done / total * 100 if total else 0
            bar = create_progress_bar(pct)
            shopify_cnt  = sum(1 for r in results if r.get("shopify"))
            no_cap_cnt   = sum(1 for r in results if r.get("shopify") and not r.get("captcha"))
            try:
                await status_msg.edit_text(
                    f"╔══════════════════════════╗\n"
                    f"║  ⚡ 𝑪𝑯𝑬𝑪𝑲𝑰𝑵𝑮 𝑷𝑹𝑶𝑮𝑹𝑬𝑺𝑺  ║\n"
                    f"╚══════════════════════════╝\n\n"
                    f"[{bar}] {pct:.1f}%\n\n"
                    f"✅ Done: <b>{done}/{total}</b>\n"
                    f"🛒 Shopify: <b>{shopify_cnt}</b>\n"
                    f"🔓 No Captcha: <b>{no_cap_cnt}</b>\n\n"
                    f"💡 /stop to halt early\n\n"
                    f"{WATERMARK}"
                )
            except Exception:
                pass

    prog_task = asyncio.create_task(update_progress())
    await asyncio.gather(*tasks)
    prog_task.cancel()
    return results

# ─── helper: read file from message ───
async def _read_file(message: Message) -> str | None:
    try:
        file_info = await bot.get_file(message.document.file_id)
        dl = await bot.download_file(file_info.file_path)
        return dl.read().decode("utf-8", errors="ignore")
    except Exception as e:
        logger.error(f"File read error: {e}")
        await message.answer("❌ Failed to read file.")
        return None

# ═══════════════════════════════════════════════════════
#  PLAIN MESSAGE — auto detect links
# ═══════════════════════════════════════════════════════

@router.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    # Skip if FSM is active (handled above)
    current = await state.get_state()
    if current:
        return

    text = message.text.strip()
    # If text looks like it has links, offer actions
    links = extract_links(text)
    if links and len(links) >= 1:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=f"✅ Check ({len(links)})", callback_data=f"quick_check"),
                InlineKeyboardButton(text="🧹 Clean",               callback_data="quick_clean"),
            ],
            [
                InlineKeyboardButton(text="📊 Categorize",          callback_data="quick_cat"),
            ],
        ])
        await message.answer(
            f"🔗 Found <b>{len(links)}</b> link(s). What do you want to do?",
            reply_markup=kb
        )
        # Store the links in FSM for next action
        await state.update_data(pending_links=links, pending_text=text)
    # else: ignore random chat

@router.callback_query(F.data == "quick_check")
async def cb_quick_check(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    links = data.get("pending_links", [])
    await state.clear()
    await cb.answer()
    if links:
        await _run_check(cb.message, links)

@router.callback_query(F.data == "quick_clean")
async def cb_quick_clean(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    links = data.get("pending_links", [])
    await state.clear()
    await cb.answer()
    if links:
        cleaned = "\n".join(links)
        doc = BufferedInputFile(cleaned.encode(), filename="cleaned.txt")
        await cb.message.answer_document(doc, caption=f"🧹 {len(links)} clean links\n\n{WATERMARK}")

@router.callback_query(F.data == "quick_cat")
async def cb_quick_cat(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    links = data.get("pending_links", [])
    await state.clear()
    await cb.answer()
    if links:
        status_msg = await cb.message.answer(f"📊 Categorizing {len(links)} sites…")
        results = await _do_check(cb.from_user.id, links, status_msg)
        groups = group_by_price(results)
        for lo, hi, label in PRICE_RANGES:
            group = groups.get(label, [])
            if group:
                lines = [f"{r['site']} | ${r['price']:.2f}" for r in group]
                doc = BufferedInputFile("\n".join(lines).encode(),
                                       filename=f"{label.replace('$','usd')}.txt")
                await cb.message.answer_document(doc, caption=f"💰 {label} — {len(group)} sites")

# ═══════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════

async def main():
    logger.info("Starting OGGY SITE CHKR...")
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot is live and polling!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
