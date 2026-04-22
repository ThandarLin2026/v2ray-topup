#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram VLESS Bot - Alireza0 X-UI Panel

Features:
- Separate Address (IP) and WS Host (Domain)
- Admin Note on Approve/Cancel
- Bank QR/Logo display (supports upload or URL)
- Bank Edit/Delete
- Updated Plans: 30D 120GB / 60D 250GB
- FIXED: service/background friendly config loading
- FIXED: top-up amount select flow
- FIXED: admin approve/cancel flow
- FIXED: insufficient balance -> ask user to top up first
- IMPROVED: cleaner keyboard / UI
- NEW: Direct X-UI traffic sync for accurate usage display
- NEW: Welcome message on /start
- NEW: Admin broadcast notification to all users
- NEW: Clean VLESS CONFIG section with copy button

How to use:
1) First run manually once:
   python3 bot.py
   -> it will create config.json

2) Then run with systemd:
   sudo nano /etc/systemd/system/vlessbot.service

   [Unit]
   Description=Telegram VLESS Bot
   After=network.target

   [Service]
   WorkingDirectory=/path/to/your/bot/folder
   ExecStart=/usr/bin/python3 /path/to/your/bot.py
   Restart=always
   RestartSec=3
   User=your_user

   [Install]
   WantedBy=multi-user.target

   sudo systemctl daemon-reload
   sudo systemctl enable --now vlessbot.service
   sudo systemctl status vlessbot.service
"""

import asyncio
import html
import io
import json
import logging
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from functools import partial
from urllib.parse import quote

import requests
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

try:
    from telegram import CopyTextButton
    HAS_COPY_TEXT_BUTTON = True
except ImportError:
    CopyTextButton = None
    HAS_COPY_TEXT_BUTTON = False

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

try:
    import qrcode
except ImportError:
    subprocess.check_call(['pip3', 'install', 'qrcode[pil]'])
    import qrcode

# ==================== Config ====================
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "BOT_TOKEN": "",
    "ADMIN_ID": 0,
    "PANEL_URL": "",
    "API_BASE_URL": "",
    "PANEL_USER": "",
    "PANEL_PASS": "",
    "INBOUND_ID": 0,
    "PORT": 0,
    "WS_PATH": "/",
    "SERVER_ADDRESS": "",  # IP address for VLESS link
    "WS_HOST": "",         # WebSocket host (domain)
    "START_MESSAGE": (
        "V2RAY X-UI PANEL မှာကြိုဆိုပါတယ်\n"
        "AIS 10 စမတ်\n"
        "*777*7067# 29 ဘတ်စမတ်\n"
        "*777*7068# 34 ဘတ်စမတ်\n"
        "V2BOX IOS ANDROID စတာတွေနဲ့သုံးနိုင်ပါတယ်"
    ),
}

CONFIG = DEFAULT_CONFIG.copy()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_FILE = "bot_data.db"


def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2, ensure_ascii=False)


def load_config() -> bool:
    global CONFIG
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update(loaded)
        CONFIG = merged
        return True
    return False


def config_is_valid() -> bool:
    required = [
        "BOT_TOKEN",
        "ADMIN_ID",
        "PANEL_URL",
        "PANEL_USER",
        "PANEL_PASS",
        "INBOUND_ID",
        "PORT",
        "SERVER_ADDRESS",
        "WS_HOST",
    ]
    for key in required:
        value = CONFIG.get(key)
        if value in ("", 0, None):
            return False
    return True


# ==================== Database ====================
class Database:
    def __init__(self):
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    balance INTEGER DEFAULT 0,
                    is_admin INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS topup_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    slip_file_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS banks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    number TEXT,
                    holder TEXT,
                    qr_file_id TEXT,
                    qr_url TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    days INTEGER,
                    data_gb INTEGER,
                    price INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_clients (
                    user_id INTEGER,
                    uuid TEXT,
                    email TEXT,
                    plan_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expiry_at TIMESTAMP,
                    total_gb INTEGER,
                    download_used INTEGER DEFAULT 0,
                    upload_used INTEGER DEFAULT 0
                )
            """)

            # Prevent duplicate plans on every restart
            plans = [
                ("30 DAYS 120GB", 30, 120, 40),
                ("60 DAYS 250GB", 60, 250, 70),
            ]
            for name, days, gb, price in plans:
                cur = conn.execute("SELECT id FROM plans WHERE name = ?", (name,))
                exists = cur.fetchone()
                if exists:
                    conn.execute(
                        "UPDATE plans SET days=?, data_gb=?, price=? WHERE name=?",
                        (days, gb, price, name)
                    )
                else:
                    conn.execute(
                        "INSERT INTO plans (name, days, data_gb, price) VALUES (?,?,?,?)",
                        (name, days, gb, price)
                    )

    async def execute(self, query: str, params: tuple = ()):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self._execute_sync, query, params))

    def _execute_sync(self, query: str, params: tuple):
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(query, params)
            conn.commit()
            if query.strip().upper().startswith("SELECT"):
                return [dict(row) for row in cur.fetchall()]
            return cur.lastrowid

    async def get_user(self, user_id: int):
        rows = await self.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return rows[0] if rows else None

    async def get_all_users(self):
        return await self.execute("SELECT * FROM users ORDER BY user_id")

    async def create_user(self, user_id: int, username: str):
        await self.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)",
            (user_id, username)
        )

    async def update_balance(self, user_id: int, delta: int):
        await self.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (delta, user_id)
        )

    async def get_balance(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        return user["balance"] if user else 0

    async def set_admin(self, user_id: int):
        await self.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (user_id,))

    async def is_admin(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return bool(user and user["is_admin"])

    async def create_topup(self, user_id: int, amount: int, slip_file_id: str = None):
        return await self.execute(
            "INSERT INTO topup_requests (user_id, amount, slip_file_id) VALUES (?,?,?)",
            (user_id, amount, slip_file_id)
        )

    async def get_topup(self, topup_id: int):
        rows = await self.execute("SELECT * FROM topup_requests WHERE id = ?", (topup_id,))
        return rows[0] if rows else None

    async def update_topup_status(self, topup_id: int, status: str):
        await self.execute("UPDATE topup_requests SET status = ? WHERE id = ?", (status, topup_id))

    async def get_pending_topups(self):
        return await self.execute(
            "SELECT * FROM topup_requests WHERE status = 'pending' ORDER BY created_at"
        )

    async def add_bank(self, name: str, number: str, holder: str, qr_file_id: str = None, qr_url: str = None):
        await self.execute(
            "INSERT INTO banks (name, number, holder, qr_file_id, qr_url) VALUES (?,?,?,?,?)",
            (name, number, holder, qr_file_id, qr_url)
        )

    async def update_bank(self, bank_id: int, name: str, number: str, holder: str,
                          qr_file_id: str = None, qr_url: str = None):
        await self.execute(
            """UPDATE banks SET name=?, number=?, holder=?, qr_file_id=?, qr_url=? WHERE id=?""",
            (name, number, holder, qr_file_id, qr_url, bank_id)
        )

    async def get_bank(self, bank_id: int):
        rows = await self.execute("SELECT * FROM banks WHERE id = ?", (bank_id,))
        return rows[0] if rows else None

    async def get_banks(self):
        return await self.execute("SELECT * FROM banks ORDER BY id")

    async def delete_bank(self, bank_id: int):
        await self.execute("DELETE FROM banks WHERE id = ?", (bank_id,))

    async def get_plans(self):
        return await self.execute("SELECT * FROM plans ORDER BY price")

    async def get_plan(self, plan_id: int):
        rows = await self.execute("SELECT * FROM plans WHERE id = ?", (plan_id,))
        return rows[0] if rows else None

    async def add_client(self, user_id: int, uuid_str: str, email: str, plan_id: int, total_gb: int, expiry_at: datetime):
        await self.execute(
            """INSERT INTO user_clients (user_id, uuid, email, plan_id, expiry_at, total_gb)
               VALUES (?,?,?,?,?,?)""",
            (user_id, uuid_str, email, plan_id, expiry_at.isoformat(), total_gb)
        )

    async def get_client(self, user_id: int):
        rows = await self.execute(
            """SELECT uc.*, p.name as plan_name, p.days, p.data_gb
               FROM user_clients uc
               LEFT JOIN plans p ON uc.plan_id = p.id
               WHERE uc.user_id = ? ORDER BY uc.created_at DESC LIMIT 1""",
            (user_id,)
        )
        return rows[0] if rows else None

    async def update_client_usage(self, user_id: int, download: int, upload: int):
        await self.execute(
            "UPDATE user_clients SET download_used = ?, upload_used = ? WHERE user_id = ?",
            (download, upload, user_id)
        )


db = Database()


# ==================== Alireza0 X-UI Client ====================
class XUIClient:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = self._detect_api_base()
        self.api_inbounds_path = "/xui/API/inbounds"

    def _detect_api_base(self):
        panel_url = CONFIG["PANEL_URL"].rstrip("/")
        root_url = "/".join(panel_url.split("/")[:3])

        if self._try_login(root_url):
            logger.info(f"API base detected as root: {root_url}")
            return root_url

        if self._try_login(panel_url):
            logger.info(f"API base detected as custom: {panel_url}")
            return panel_url

        raise Exception("Could not login with any API base URL")

    def _try_login(self, base_url: str) -> bool:
        url = f"{base_url}/login"
        data = {"username": CONFIG["PANEL_USER"], "password": CONFIG["PANEL_PASS"]}
        try:
            resp = self.session.post(url, data=data, timeout=10)
            if resp.status_code == 200:
                try:
                    payload = resp.json()
                    if payload.get("success"):
                        self.base_url = base_url
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    def add_client(self, inbound_id: int, email: str, uuid_str: str, total_gb: int = 0, expiry_time: int = 0) -> dict:
        url = f"{self.base_url}{self.api_inbounds_path}/addClient/"
        settings = {
            "clients": [{
                "email": email,
                "id": uuid_str,
                "enable": True,
                "flow": "",
                "totalGB": total_gb,
                "expiryTime": expiry_time,
                "limitIp": 0,
            }]
        }
        data = {"id": inbound_id, "settings": json.dumps(settings)}
        resp = self.session.post(url, data=data, timeout=20)
        if resp.status_code != 200:
            raise Exception(f"Add client HTTP {resp.status_code}: {resp.text[:200]}")
        result = resp.json()
        if not result.get("success"):
            raise Exception(f"Add client error: {result.get('msg', 'Unknown error')}")
        return result

    def _safe_int(self, value, default=0):
        try:
            if value is None or value == "":
                return default
            return int(value)
        except Exception:
            try:
                return int(float(value))
            except Exception:
                return default

    def _normalize_traffic_obj(self, obj: dict) -> dict:
        if not isinstance(obj, dict):
            return {}

        download = self._safe_int(
            obj.get("downlink", obj.get("down", obj.get("download", 0)))
        )
        upload = self._safe_int(
            obj.get("uplink", obj.get("up", obj.get("upload", 0)))
        )
        total = self._safe_int(
            obj.get("total", obj.get("totalGB", obj.get("total_gb", 0)))
        )
        expiry_time = self._safe_int(
            obj.get("expiryTime", obj.get("expiry_time", 0))
        )
        enable = obj.get("enable", True)

        return {
            "downlink": download,
            "uplink": upload,
            "total": total,
            "expiryTime": expiry_time,
            "enable": enable,
            "email": obj.get("email", ""),
        }

    def _extract_traffic_from_inbounds_list(self, email: str, payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {}

        inbounds = payload.get("obj") or []
        for inbound in inbounds:
            # Most common in Alireza/X-UI panel
            client_stats = inbound.get("clientStats") or inbound.get("clientTraffic") or []
            if isinstance(client_stats, list):
                for stat in client_stats:
                    if stat.get("email") == email:
                        return self._normalize_traffic_obj(stat)

            # Fallback: sometimes client config exists in settings JSON
            settings_raw = inbound.get("settings")
            if settings_raw:
                try:
                    settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
                    clients = settings.get("clients", [])
                    for client in clients:
                        if client.get("email") == email:
                            normalized = self._normalize_traffic_obj(client)

                            if isinstance(client_stats, list):
                                for stat in client_stats:
                                    if stat.get("email") == email:
                                        stat_n = self._normalize_traffic_obj(stat)
                                        normalized["downlink"] = stat_n.get("downlink", 0)
                                        normalized["uplink"] = stat_n.get("uplink", 0)
                                        if stat_n.get("total"):
                                            normalized["total"] = stat_n["total"]
                                        if stat_n.get("expiryTime"):
                                            normalized["expiryTime"] = stat_n["expiryTime"]
                                        normalized["enable"] = stat_n.get("enable", normalized["enable"])
                                        return normalized

                            return normalized
                except Exception:
                    pass

        return {}

    def get_client_traffic(self, email: str) -> dict:
        # 1) Direct endpoint first
        try:
            encoded_email = quote(email, safe="")
            url = f"{self.base_url}{self.api_inbounds_path}/getClientTraffics/{encoded_email}"
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    obj = data.get("obj", {})
                    normalized = self._normalize_traffic_obj(obj)
                    if normalized:
                        return normalized
        except Exception as e:
            logger.warning(f"Direct traffic endpoint failed for {email}: {e}")

        # 2) Fallback: read all inbounds and find exact panel data there
        try:
            url = f"{self.base_url}{self.api_inbounds_path}/list"
            resp = self.session.get(url, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    found = self._extract_traffic_from_inbounds_list(email, data)
                    if found:
                        return found
        except Exception as e:
            logger.error(f"Failed to fallback traffic search for {email}: {e}")

        return {}


xui = None


# ==================== Helpers ====================
def generate_vless_link(uuid_str: str, remark: str = "") -> str:
    address = CONFIG["SERVER_ADDRESS"]
    port = CONFIG["PORT"]
    path = CONFIG["WS_PATH"] or "/"
    ws_host = CONFIG["WS_HOST"]
    link = (
        f"vless://{uuid_str}@{address}:{port}"
        f"?path={path}&security=none&encryption=none&type=ws&host={ws_host}"
    )
    if remark:
        link += f"#{remark.replace(' ', '_')}"
    return link


def generate_qr_bytes(data: str) -> io.BytesIO:
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio


def format_bytes(size: int) -> str:
    size = int(size or 0)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def get_effective_message(target):
    if isinstance(target, Update):
        return target.effective_message
    return getattr(target, "message", None)


def get_vless_copy_keyboard(vless_link: str):
    if HAS_COPY_TEXT_BUTTON and CopyTextButton is not None:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Copy VLESS", copy_text=CopyTextButton(vless_link))]
        ])
    return None


def get_welcome_text() -> str:
    return CONFIG.get("START_MESSAGE", DEFAULT_CONFIG["START_MESSAGE"])


async def send_main_menu(target):
    user_id = None
    if isinstance(target, Update):
        user_id = target.effective_user.id
    else:
        user_id = target.from_user.id

    is_admin = await db.is_admin(user_id)
    keyboard = await get_main_keyboard(is_admin)
    msg = get_effective_message(target)
    if msg:
        await msg.reply_text("🏠 Main Menu", reply_markup=keyboard)


async def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton("🛒 Buy Plan"), KeyboardButton("💰 TopUp")],
        [KeyboardButton("👤 Account"), KeyboardButton("🏦 Banks")],
    ]
    if is_admin:
        buttons.append([KeyboardButton("⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def main_inline_back():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_back")]
    ])


# ==================== States ====================
TO_AMOUNT, TO_SLIP = range(2)
BANK_NAME, BANK_NUMBER, BANK_HOLDER, BANK_QR = range(4)
ADMIN_NOTE = 10
BANK_EDIT_NAME, BANK_EDIT_NUMBER, BANK_EDIT_HOLDER, BANK_EDIT_QR = range(20, 24)
BROADCAST_TEXT = 30


# ==================== Handlers ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    await db.create_user(user_id, user.username or user.full_name)
    if user_id == CONFIG["ADMIN_ID"]:
        await db.set_admin(user_id)

    await update.message.reply_text(get_welcome_text())
    await send_main_menu(update)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    text = update.message.text

    await db.create_user(user_id, user.username or user.full_name)
    if user_id == CONFIG["ADMIN_ID"]:
        await db.set_admin(user_id)

    if text == "🛒 Buy Plan":
        await show_plans(update)
    elif text == "💰 TopUp":
        await start_topup(update)
    elif text == "👤 Account":
        await show_account(update, context)
    elif text == "🏦 Banks":
        await show_banks(update)
    elif text == "⚙️ Admin Panel":
        if await db.is_admin(user_id):
            await show_admin_panel(update)
        else:
            await send_main_menu(update)
    else:
        await send_main_menu(update)


async def show_plans(update: Update):
    plans = await db.get_plans()
    keyboard = []
    for plan in plans:
        btn_text = f"📦 {plan['name']} • {plan['price']} THB"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"buy_{plan['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])

    text = "📦 *Select a plan*"
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def start_topup(update: Update):
    amounts = [40, 70, 100]
    keyboard = [[InlineKeyboardButton(f"💵 {amt} THB", callback_data=f"topup_amt_{amt}")] for amt in amounts]
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])

    await update.message.reply_text(
        "💰 *Select top-up amount*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def show_topup_from_callback(query):
    amounts = [40, 70, 100]
    keyboard = [[InlineKeyboardButton(f"💵 {amt} THB", callback_data=f"topup_amt_{amt}")] for amt in amounts]
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])

    await query.edit_message_text(
        "💰 *Select top-up amount*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def topup_amount_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_back":
        try:
            await query.message.delete()
        except Exception:
            pass
        await send_main_menu(query)
        return ConversationHandler.END

    amount = int(data.split("_")[2])
    context.user_data["topup_amount"] = amount

    banks = await db.get_banks()
    if not banks:
        await query.edit_message_text("⚠️ No bank accounts available. Please contact admin.")
        return ConversationHandler.END

    try:
        await query.message.delete()
    except Exception:
        pass

    chat_id = query.message.chat.id

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"💰 *Top-up Amount:* `{amount} THB`\n\n🏦 Please transfer to one of the bank accounts below and then send your payment slip.",
        parse_mode="Markdown"
    )

    for bank in banks:
        caption = (
            f"🏦 *{bank['name']}*\n"
            f"💳 `{bank['number']}`\n"
            f"👤 {bank['holder']}\n\n"
            f"💵 Amount: *{amount} THB*"
        )
        if bank.get('qr_file_id'):
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=bank['qr_file_id'],
                caption=caption,
                parse_mode="Markdown"
            )
        elif bank.get('qr_url'):
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=bank['qr_url'],
                caption=caption,
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode="Markdown"
            )

    await context.bot.send_message(
        chat_id=chat_id,
        text="📸 *Now send the payment slip photo.*\nUse /cancel to go back.",
        parse_mode="Markdown"
    )
    return TO_SLIP


async def receive_slip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    file_id = photo.file_id
    amount = context.user_data.get("topup_amount")

    if not amount:
        await update.message.reply_text("❌ Top-up session expired. Please try again.")
        await send_main_menu(update)
        return ConversationHandler.END

    topup_id = await db.create_topup(user_id, amount, file_id)
    await update.message.reply_text(f"✅ Top-up request for {amount} THB has been sent to admin.")
    await send_main_menu(update)

    admin_id = CONFIG["ADMIN_ID"]
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{topup_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{topup_id}")
        ]
    ])
    user_mention = f"[{update.effective_user.full_name}](tg://user?id={user_id})"

    await context.bot.send_photo(
        chat_id=admin_id,
        photo=file_id,
        caption=f"🔔 *New Top-up Request*\n\n👤 User: {user_mention}\n💵 Amount: *{amount} THB*\n🆔 Request ID: `{topup_id}`",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    context.user_data.pop("topup_amount", None)
    return ConversationHandler.END


async def cancel_topup_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("topup_amount", None)
    await update.message.reply_text("↩️ Cancelled.")
    await send_main_menu(update)
    return ConversationHandler.END


async def show_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = await db.get_balance(user_id)
    client = await db.get_client(user_id)

    if not client:
        info = (
            "👤 *Account Information*\n\n"
            f"💰 Balance: *{balance} THB*\n"
            "📡 Status: ⚪ No active plan\n\n"
            "Purchase a plan to get started!"
        )
        await update.message.reply_text(info, parse_mode="Markdown")
        return

    traffic = xui.get_client_traffic(client["email"]) if xui else {}

    download = int(traffic.get("downlink", 0) or 0)
    upload = int(traffic.get("uplink", 0) or 0)
    total_used = download + upload
    await db.update_client_usage(user_id, download, upload)

    panel_total = int(traffic.get("total", 0) or 0)
    total_limit_bytes = panel_total if panel_total > 0 else int(client["total_gb"] or 0)

    panel_expiry_ms = int(traffic.get("expiryTime", 0) or 0)
    if panel_expiry_ms > 0:
        expiry = datetime.utcfromtimestamp(panel_expiry_ms / 1000)
    else:
        expiry = datetime.fromisoformat(client["expiry_at"]) if client["expiry_at"] else None

    enabled = bool(traffic.get("enable", True))
    now = datetime.utcnow()

    if expiry:
        seconds_left = (expiry - now).total_seconds()
        days_left = int(seconds_left // 86400)
        is_expired = seconds_left < 0
        expiry_str = expiry.strftime("%d %b %Y")
        if is_expired:
            expiry_str += " (Expired)"
        else:
            expiry_str += f" ({days_left} days left)"
    else:
        is_expired = False
        expiry_str = "Unlimited"

    limit_gb = (total_limit_bytes / (1024**3)) if total_limit_bytes > 0 else 0
    usage_percent = (total_used / total_limit_bytes * 100) if total_limit_bytes > 0 else 0

    traffic_exhausted = total_limit_bytes > 0 and total_used >= total_limit_bytes
    is_active = enabled and (not is_expired) and (not traffic_exhausted)
    status_emoji = "🟢" if is_active else "🔴"
    status_text = "Active" if is_active else "Expired"

    info = (
        f"👤 *Account Information*\n\n"
        f"💰 Balance: *{balance} THB*\n"
        f"📦 Plan: *{client['plan_name']}*\n"
        f"📅 Expiry: {expiry_str}\n"
        f"{status_emoji} Status: *{status_text}*\n\n"
        f"📊 *Data Usage*\n"
        f"📥 Download: `{format_bytes(download)}`\n"
        f"📤 Upload: `{format_bytes(upload)}`\n"
        f"💾 Total Used: `{format_bytes(total_used)} / {limit_gb:.0f} GB` ({usage_percent:.1f}%)\n\n"
        f"🔑 VLESS UUID: `{client['uuid']}`\n"
        f"📧 Email: `{client['email']}`"
    )
    await update.message.reply_text(info, parse_mode="Markdown")


async def show_banks(update: Update):
    banks = await db.get_banks()
    if not banks:
        await update.message.reply_text("ℹ️ No bank accounts available.")
        return

    await update.message.reply_text("🏦 *Available Bank Accounts*", parse_mode="Markdown")
    for bank in banks:
        text = f"🏦 *{bank['name']}*\n💳 `{bank['number']}`\n👤 {bank['holder']}"
        if bank.get('qr_file_id'):
            await update.message.reply_photo(photo=bank['qr_file_id'], caption=text, parse_mode="Markdown")
        elif bank.get('qr_url'):
            await update.message.reply_photo(photo=bank['qr_url'], caption=text, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, parse_mode="Markdown")


async def show_admin_panel(update: Update):
    keyboard = [
        [InlineKeyboardButton("➕ Add Bank", callback_data="admin_addbank")],
        [InlineKeyboardButton("📋 Pending TopUps", callback_data="admin_pending")],
        [InlineKeyboardButton("🏦 Manage Banks", callback_data="admin_listbanks")],
        [InlineKeyboardButton("📢 Broadcast Message", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_back")],
    ]
    await update.message.reply_text(
        "⚙️ *Admin Panel*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "menu_back":
        try:
            await query.message.delete()
        except Exception:
            pass
        await send_main_menu(query)
        return

    if data == "goto_topup":
        await show_topup_from_callback(query)
        return

    if data.startswith("buy_"):
        plan_id = int(data.split("_")[1])
        await process_buy_plan(query, plan_id)
        return

    if data.startswith("approve_") or data.startswith("cancel_"):
        parts = data.split("_")
        action = parts[0]
        topup_id = int(parts[1])
        context.user_data["admin_action"] = {"action": action, "topup_id": topup_id}
        await query.edit_message_caption(
            caption=(
                f"📝 *Enter a note for the user (optional)*\n"
                f"Send /skip to proceed without a note."
            ),
            parse_mode="Markdown"
        )
        return ADMIN_NOTE

    if data == "admin_addbank":
        await query.edit_message_text("🏦 Enter bank name (e.g., KBank):")
        return BANK_NAME

    if data == "admin_pending":
        await show_pending_topups(query, context)
        return

    if data == "admin_listbanks":
        await manage_banks(query)
        return

    if data == "admin_broadcast":
        await query.edit_message_text(
            "📢 Send the message you want to broadcast to all users.\nUse /cancel to stop."
        )
        return BROADCAST_TEXT

    if data.startswith("delbank_"):
        bank_id = int(data.split("_")[1])
        await db.delete_bank(bank_id)
        await query.answer("Bank deleted.")
        await manage_banks(query)
        return

    if data.startswith("editbank_"):
        bank_id = int(data.split("_")[1])
        bank = await db.get_bank(bank_id)
        if not bank:
            await query.answer("Bank not found.")
            return
        context.user_data["edit_bank_id"] = bank_id
        context.user_data["edit_bank"] = bank
        await query.edit_message_text(
            f"✏️ Editing bank: {bank['name']}\n\nEnter new name (or /skip to keep):"
        )
        return BANK_EDIT_NAME

    if not await db.is_admin(user_id):
        await send_main_menu(query)


async def process_buy_plan(query, plan_id: int):
    user_id = query.from_user.id
    plan = await db.get_plan(plan_id)

    if not plan:
        await query.edit_message_text("❌ Plan not found.")
        return

    is_admin = await db.is_admin(user_id)

    if not is_admin:
        balance = await db.get_balance(user_id)
        if balance < plan["price"]:
            need = plan["price"] - balance
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 TopUp Now", callback_data="goto_topup")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu_back")]
            ])
            await query.edit_message_text(
                (
                    f"❌ *Insufficient balance*\n\n"
                    f"💰 Your balance: *{balance} THB*\n"
                    f"📦 Plan price: *{plan['price']} THB*\n"
                    f"➕ Need more: *{need} THB*\n\n"
                    f"Please top up first."
                ),
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            return

    if not is_admin:
        await db.update_balance(user_id, -plan["price"])

    await query.edit_message_text("⏳ Creating VLESS client...")

    try:
        uuid_str = str(uuid.uuid4())
        email = f"user_{user_id}_{uuid_str[:8]}"
        expiry_time_dt = datetime.utcnow() + timedelta(days=plan["days"])
        expiry_time_ms = int(expiry_time_dt.timestamp() * 1000)
        total_bytes = plan["data_gb"] * 1024**3

        xui.add_client(
            CONFIG["INBOUND_ID"],
            email,
            uuid_str,
            total_gb=total_bytes,
            expiry_time=expiry_time_ms
        )

        await db.add_client(
            user_id=user_id,
            uuid_str=uuid_str,
            email=email,
            plan_id=plan_id,
            total_gb=total_bytes,
            expiry_at=expiry_time_dt
        )

        link = generate_vless_link(uuid_str, plan["name"])
        qr_bytes = generate_qr_bytes(link)

        try:
            await query.message.delete()
        except Exception:
            pass

        summary_caption = (
            f"✅ *Plan Purchased Successfully!*\n\n"
            f"📦 Plan: *{plan['name']}*\n"
            f"📅 Expires: {expiry_time_dt.strftime('%d %b %Y')}\n"
            f"📧 Email: `{email}`\n"
            f"📱 Scan QR code to import"
        )

        await query.message.reply_photo(
            photo=qr_bytes,
            caption=summary_caption,
            parse_mode="Markdown"
        )

        config_text = (
            "🔐 <b>VLESS CONFIG</b>\n\n"
            f"<code>{html.escape(link)}</code>"
        )

        copy_keyboard = get_vless_copy_keyboard(link)
        if copy_keyboard:
            await query.message.reply_text(
                config_text,
                parse_mode="HTML",
                reply_markup=copy_keyboard
            )
        else:
            await query.message.reply_text(
                config_text + "\n\n📋 Copy button requires a newer python-telegram-bot version.",
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Add client error: {e}")
        if not is_admin:
            await db.update_balance(user_id, plan["price"])
        await query.message.reply_text(f"❌ Failed: {str(e)[:200]}")


async def admin_note_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    action_data = context.user_data.get("admin_action")

    if not action_data:
        await update.message.reply_text("Session expired.")
        return ConversationHandler.END

    note = None if text == "/skip" else text
    topup_id = action_data["topup_id"]
    action = action_data["action"]

    if action == "approve":
        await approve_topup_with_note(update, context, topup_id, note)
    else:
        await cancel_topup_with_note(update, context, topup_id, note)

    context.user_data.pop("admin_action", None)
    await send_main_menu(update)
    return ConversationHandler.END


async def approve_topup_with_note(update: Update, context: ContextTypes.DEFAULT_TYPE, topup_id: int, note: str = None):
    topup = await db.get_topup(topup_id)
    if not topup or topup["status"] != "pending":
        await update.message.reply_text("Already processed.")
        return

    await db.update_topup_status(topup_id, "approved")
    await db.update_balance(topup["user_id"], topup["amount"])

    msg = f"✅ Your top-up of {topup['amount']} THB has been approved."
    if note:
        msg += f"\n📝 Admin Note: {note}"

    await context.bot.send_message(topup["user_id"], msg)
    await update.message.reply_text(
        f"✅ Top-up {topup['amount']} THB approved and credit added successfully."
    )


async def cancel_topup_with_note(update: Update, context: ContextTypes.DEFAULT_TYPE, topup_id: int, note: str = None):
    topup = await db.get_topup(topup_id)
    if not topup or topup["status"] != "pending":
        await update.message.reply_text("Already processed.")
        return

    await db.update_topup_status(topup_id, "cancelled")

    msg = f"❌ Your top-up request of {topup['amount']} THB was cancelled."
    if note:
        msg += f"\n📝 Admin Note: {note}"

    await context.bot.send_message(topup["user_id"], msg)
    await update.message.reply_text(f"❌ Top-up {topup['amount']} THB cancelled.")


async def show_pending_topups(query, context: ContextTypes.DEFAULT_TYPE):
    pending = await db.get_pending_topups()
    if not pending:
        await query.edit_message_text("📭 No pending requests.")
        return

    await query.edit_message_text(
        f"📋 Found *{len(pending)}* pending request(s).\nRequests are being sent below.",
        parse_mode="Markdown"
    )

    for req in pending:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{req['id']}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{req['id']}")
            ]
        ])
        caption = (
            f"🔔 *Pending Top-up*\n\n"
            f"🆔 ID: `{req['id']}`\n"
            f"👤 User ID: `{req['user_id']}`\n"
            f"💵 Amount: *{req['amount']} THB*\n"
            f"📅 Created: `{req['created_at']}`"
        )

        if req.get("slip_file_id"):
            await context.bot.send_photo(
                chat_id=query.message.chat.id,
                photo=req["slip_file_id"],
                caption=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )


async def manage_banks(query):
    banks = await db.get_banks()
    keyboard = []
    for bank in banks:
        keyboard.append([
            InlineKeyboardButton(f"✏️ Edit {bank['name']}", callback_data=f"editbank_{bank['id']}"),
            InlineKeyboardButton("❌ Delete", callback_data=f"delbank_{bank['id']}")
        ])
    keyboard.append([InlineKeyboardButton("➕ Add Bank", callback_data="admin_addbank")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])

    await query.edit_message_text(
        "🏦 *Manage Banks*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = update.effective_user.id
    if not await db.is_admin(sender_id):
        await update.message.reply_text("❌ Admin only.")
        return ConversationHandler.END

    text = update.message.text
    users = await db.get_all_users()

    if not users:
        await update.message.reply_text("ℹ️ No users found.")
        await send_main_menu(update)
        return ConversationHandler.END

    await update.message.reply_text("⏳ Broadcasting message...")

    sent = 0
    failed = 0
    for user in users:
        try:
            await context.bot.send_message(user["user_id"], text)
            sent += 1
        except Exception as e:
            logger.warning(f"Broadcast failed for {user['user_id']}: {e}")
            failed += 1

    await update.message.reply_text(
        f"✅ Broadcast finished.\n\n📤 Sent: {sent}\n❌ Failed: {failed}"
    )
    await send_main_menu(update)
    return ConversationHandler.END


# ==================== Bank Addition Conversation ====================
async def start_bank_addition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🏦 Enter bank name (e.g., KBank):")
    return BANK_NAME


async def bank_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_name"] = update.message.text
    await update.message.reply_text("💳 Enter account number:")
    return BANK_NUMBER


async def bank_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_number"] = update.message.text
    await update.message.reply_text("👤 Enter account holder name:")
    return BANK_HOLDER


async def bank_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_holder"] = update.message.text
    await update.message.reply_text(
        "📷 Send QR code photo (or logo), or send an image URL.\n"
        "Send /skip if no image."
    )
    return BANK_QR


async def bank_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip() if update.message.text else ""

    if update.message.photo:
        photo = update.message.photo[-1]
        context.user_data["bank_qr_file_id"] = photo.file_id
        context.user_data["bank_qr_url"] = None
    elif text == "/skip":
        context.user_data["bank_qr_file_id"] = None
        context.user_data["bank_qr_url"] = None
    elif text.startswith(("http://", "https://")):
        context.user_data["bank_qr_url"] = text
        context.user_data["bank_qr_file_id"] = None
    else:
        await update.message.reply_text("❌ Please send a photo, a valid URL, or /skip.")
        return BANK_QR

    await db.add_bank(
        context.user_data["bank_name"],
        context.user_data["bank_number"],
        context.user_data["bank_holder"],
        context.user_data.get("bank_qr_file_id"),
        context.user_data.get("bank_qr_url")
    )
    await update.message.reply_text("✅ Bank added successfully.")
    await send_main_menu(update)
    return ConversationHandler.END


# ==================== Bank Edit Conversation ====================
async def edit_bank_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "/skip":
        context.user_data["edit_bank_name"] = update.message.text
    else:
        context.user_data["edit_bank_name"] = context.user_data["edit_bank"]["name"]
    await update.message.reply_text("💳 Enter new account number (or /skip):")
    return BANK_EDIT_NUMBER


async def edit_bank_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "/skip":
        context.user_data["edit_bank_number"] = update.message.text
    else:
        context.user_data["edit_bank_number"] = context.user_data["edit_bank"]["number"]
    await update.message.reply_text("👤 Enter new account holder name (or /skip):")
    return BANK_EDIT_HOLDER


async def edit_bank_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "/skip":
        context.user_data["edit_bank_holder"] = update.message.text
    else:
        context.user_data["edit_bank_holder"] = context.user_data["edit_bank"]["holder"]
    await update.message.reply_text(
        "📷 Send new QR code photo or URL (or /skip to keep existing):"
    )
    return BANK_EDIT_QR


async def edit_bank_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bank_id = context.user_data["edit_bank_id"]
    bank = context.user_data["edit_bank"]
    qr_file_id = bank.get("qr_file_id")
    qr_url = bank.get("qr_url")
    text = (update.message.text or "").strip() if update.message.text else ""

    if update.message.photo:
        qr_file_id = update.message.photo[-1].file_id
        qr_url = None
    elif text.startswith(("http://", "https://")):
        qr_url = text
        qr_file_id = None
    elif text == "/skip":
        pass
    else:
        await update.message.reply_text("❌ Invalid input. Use /skip to keep existing.")
        return BANK_EDIT_QR

    await db.update_bank(
        bank_id,
        context.user_data["edit_bank_name"],
        context.user_data["edit_bank_number"],
        context.user_data["edit_bank_holder"],
        qr_file_id,
        qr_url
    )
    await update.message.reply_text("✅ Bank updated successfully.")
    await send_main_menu(update)
    return ConversationHandler.END


async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("↩️ Cancelled.")
    await send_main_menu(update)
    return ConversationHandler.END


# ==================== Config Prompt ====================
def get_config():
    print("\n🔧 First-time configuration (Alireza0 X-UI Panel)\n")
    CONFIG["BOT_TOKEN"] = input("Enter Bot Token: ").strip()
    CONFIG["ADMIN_ID"] = int(input("Enter Admin Telegram ID: ").strip())
    CONFIG["PANEL_URL"] = input("Enter X-UI Panel URL (with custom path if any): ").strip()
    CONFIG["PANEL_USER"] = input("Enter Panel Username: ").strip()
    CONFIG["PANEL_PASS"] = input("Enter Panel Password: ").strip()
    CONFIG["INBOUND_ID"] = int(input("Enter Inbound ID: ").strip())
    CONFIG["PORT"] = int(input("Enter Port: ").strip())
    ws_path = input("Enter WS Path [default: /]: ").strip()
    CONFIG["WS_PATH"] = ws_path if ws_path else "/"
    CONFIG["SERVER_ADDRESS"] = input("Enter Server Address (VPS IP): ").strip()
    CONFIG["WS_HOST"] = input("Enter WebSocket Host (domain): ").strip()

    save_config()
    print(f"\n✅ Configuration saved to {CONFIG_FILE}\n")


def ensure_config():
    loaded = load_config()
    if loaded and config_is_valid():
        logger.info(f"Loaded configuration from {CONFIG_FILE}")
        return

    if sys.stdin.isatty():
        get_config()
        return

    logger.error(f"{CONFIG_FILE} not found or incomplete. Run the bot manually once to generate it.")
    sys.exit(1)


def main():
    ensure_config()

    global xui
    try:
        xui = XUIClient()
        logger.info(f"Successfully connected to Alireza0 X-UI panel. API base: {xui.base_url}")
    except Exception as e:
        logger.error(f"Cannot login to X-UI: {e}")
        print("\n❌ X-UI Login failed. Please check your Panel URL, Username, Password.")
        return

    app = Application.builder().token(CONFIG["BOT_TOKEN"]).build()

    # Admin note conversation (Approve/Cancel)
    admin_note_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^(approve|cancel)_")],
        states={
            ADMIN_NOTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_note_input),
                CommandHandler("skip", admin_note_input)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_topup_conv)],
        per_message=False,
    )

    topup_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(topup_amount_selected, pattern="^topup_amt_")],
        states={
            TO_SLIP: [MessageHandler(filters.PHOTO, receive_slip)]
        },
        fallbacks=[CommandHandler("cancel", cancel_topup_conv)],
        per_message=False,
    )

    bank_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_bank_addition, pattern="^admin_addbank$")],
        states={
            BANK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_name)],
            BANK_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_number)],
            BANK_HOLDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_holder)],
            BANK_QR: [
                MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), bank_qr),
                CommandHandler("skip", bank_qr)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_topup_conv)],
        per_message=False,
    )

    bank_edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^editbank_")],
        states={
            BANK_EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bank_name),
                CommandHandler("skip", edit_bank_name)
            ],
            BANK_EDIT_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bank_number),
                CommandHandler("skip", edit_bank_number)
            ],
            BANK_EDIT_HOLDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bank_holder),
                CommandHandler("skip", edit_bank_holder)
            ],
            BANK_EDIT_QR: [
                MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), edit_bank_qr),
                CommandHandler("skip", edit_bank_qr)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_edit)],
        per_message=False,
    )

    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^admin_broadcast$")],
        states={
            BROADCAST_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_edit)],
        per_message=False,
    )

    # Order matters: specific conversations first
    app.add_handler(admin_note_conv)
    app.add_handler(bank_edit_conv)
    app.add_handler(bank_conv)
    app.add_handler(topup_conv)
    app.add_handler(broadcast_conv)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
