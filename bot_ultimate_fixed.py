#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram VLESS Bot - Perfect Fixed Version
- Fixed Approve/Cancel
- Bank edit/delete, QR/Logo via photo or URL
- Plans: 30D/120GB/40THB, 60D/250GB/70THB
- Background service ready
"""

import asyncio
import io
import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from functools import partial
from urllib.parse import urlparse

import requests
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
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
    import subprocess
    subprocess.check_call(['pip3', 'install', 'qrcode[pil]'])
    import qrcode

# ==================== Config ====================
CONFIG = {
    "BOT_TOKEN": "",
    "ADMIN_ID": 0,
    "PANEL_URL": "",
    "API_BASE_URL": "",
    "PANEL_USER": "",
    "PANEL_PASS": "",
    "INBOUND_ID": 0,
    "PORT": 0,
    "WS_PATH": "",
    "SERVER_ADDRESS": "",
    "WS_HOST": "",
}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DB_FILE = "bot_data.db"

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
                    logo_file_id TEXT
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
            # Delete old plans and insert new ones
            conn.execute("DELETE FROM plans")
            plans = [
                ("30 DAYS 120GB", 30, 120, 40),
                ("60 DAYS 250GB", 60, 250, 70),
            ]
            for name, days, gb, price in plans:
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

    async def create_user(self, user_id: int, username: str):
        await self.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)",
            (user_id, username)
        )

    async def update_balance(self, user_id: int, delta: int):
        await self.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id))

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
        return await self.execute("SELECT * FROM topup_requests WHERE status = 'pending' ORDER BY created_at")

    async def add_bank(self, name: str, number: str, holder: str, qr_file_id: str = None, logo_file_id: str = None):
        return await self.execute(
            "INSERT INTO banks (name, number, holder, qr_file_id, logo_file_id) VALUES (?,?,?,?,?)",
            (name, number, holder, qr_file_id, logo_file_id)
        )

    async def get_banks(self):
        return await self.execute("SELECT * FROM banks ORDER BY id")

    async def get_bank(self, bank_id: int):
        rows = await self.execute("SELECT * FROM banks WHERE id = ?", (bank_id,))
        return rows[0] if rows else None

    async def update_bank(self, bank_id: int, name: str, number: str, holder: str, qr_file_id: str = None, logo_file_id: str = None):
        await self.execute(
            """UPDATE banks SET name = ?, number = ?, holder = ?, qr_file_id = ?, logo_file_id = ? WHERE id = ?""",
            (name, number, holder, qr_file_id, logo_file_id, bank_id)
        )

    async def delete_bank(self, bank_id: int):
        await self.execute("DELETE FROM banks WHERE id = ?", (bank_id,))

    async def get_plans(self):
        return await self.execute("SELECT * FROM plans ORDER BY price")

    async def add_client(self, user_id: int, uuid_str: str, email: str, plan_id: int, total_gb: int, expiry_at: datetime):
        await self.execute(
            """INSERT INTO user_clients 
               (user_id, uuid, email, plan_id, expiry_at, total_gb) 
               VALUES (?,?,?,?,?,?)""",
            (user_id, uuid_str, email, plan_id, expiry_at, total_gb)
        )

    async def get_client(self, user_id: int):
        rows = await self.execute(
            """SELECT uc.*, p.name as plan_name, p.days, p.data_gb 
               FROM user_clients uc 
               LEFT JOIN plans p ON uc.plan_id = p.id 
               WHERE uc.user_id = ? 
               ORDER BY uc.created_at DESC LIMIT 1""",
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
            if resp.status_code == 200 and resp.json().get("success"):
                self.base_url = base_url
                return True
        except:
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
        resp = self.session.post(url, data=data)
        if resp.status_code != 200:
            raise Exception(f"Add client HTTP {resp.status_code}: {resp.text[:100]}")
        result = resp.json()
        if not result.get("success"):
            raise Exception(f"Add client error: {result.get('msg', 'Unknown error')}")
        return result

    def get_client_traffic(self, email: str) -> dict:
        url = f"{self.base_url}{self.api_inbounds_path}/getClientTraffics/{email}"
        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return data.get("obj", {})
        except Exception as e:
            logger.error(f"Failed to get traffic for {email}: {e}")
        return {}

xui = None

# ==================== Helpers ====================
def generate_vless_link(uuid_str: str, remark: str = "") -> str:
    address = CONFIG["SERVER_ADDRESS"]
    port = CONFIG["PORT"]
    path = CONFIG["WS_PATH"] or "/"
    ws_host = CONFIG["WS_HOST"]
    link = f"vless://{uuid_str}@{address}:{port}?path={path}&security=none&encryption=none&type=ws&host={ws_host}"
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
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def is_url(string: str) -> bool:
    try:
        result = urlparse(string)
        return all([result.scheme, result.netloc])
    except:
        return False

async def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton("🛒 Buy Plan")],
        [KeyboardButton("💰 TopUp")],
        [KeyboardButton("👤 Account")],
        [KeyboardButton("🏦 Banks")],
    ]
    if is_admin:
        buttons.append([KeyboardButton("⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# ==================== States ====================
TO_AMOUNT, TO_SLIP = range(2)
BANK_NAME, BANK_NUMBER, BANK_HOLDER, BANK_QR, BANK_LOGO = range(5)
EDIT_BANK_SELECT, EDIT_BANK_FIELD, EDIT_BANK_VALUE = range(3)
ADMIN_NOTE = 10

# ==================== Handlers ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    await db.create_user(user_id, user.username or user.full_name)
    if user_id == CONFIG["ADMIN_ID"]:
        await db.set_admin(user_id)
    await send_main_menu(update)

async def send_main_menu(update: Update):
    user_id = update.effective_user.id
    is_admin = await db.is_admin(user_id)
    keyboard = await get_main_keyboard(is_admin)
    await update.message.reply_text("📋 Main Menu:", reply_markup=keyboard)

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
        btn_text = f"{plan['name']} - {plan['price']} THB"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"buy_{plan['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
    await update.message.reply_text("📦 Select a plan:", reply_markup=InlineKeyboardMarkup(keyboard))

async def start_topup(update: Update):
    amounts = [40, 70, 100]
    keyboard = [[InlineKeyboardButton(f"{amt} THB", callback_data=f"topup_amt_{amt}")] for amt in amounts]
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
    await update.message.reply_text("💰 Select top-up amount:", reply_markup=InlineKeyboardMarkup(keyboard))

async def topup_amount_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "menu_back":
        await query.message.delete()
        await send_main_menu(query)
        return ConversationHandler.END
    amount = int(data.split("_")[2])
    context.user_data["topup_amount"] = amount

    banks = await db.get_banks()
    if not banks:
        await query.edit_message_text("⚠️ No bank accounts available. Please contact admin.")
        return ConversationHandler.END

    # Send bank list with QR/Logo
    await query.edit_message_text("🏦 Please select a bank to transfer:")
    for bank in banks:
        text = f"*{bank['name']}*\n{bank['number']}\n{bank['holder']}"
        # Send logo if exists
        if bank.get('logo_file_id'):
            await query.message.reply_photo(photo=bank['logo_file_id'], caption=text, parse_mode="Markdown")
        elif bank.get('qr_file_id'):
            await query.message.reply_photo(photo=bank['qr_file_id'], caption=text, parse_mode="Markdown")
        else:
            await query.message.reply_text(text, parse_mode="Markdown")

    await query.message.reply_text(f"💵 Amount: *{amount} THB*\n\n📸 Then send the payment slip photo.", parse_mode="Markdown")
    return TO_SLIP

async def receive_slip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    file_id = photo.file_id
    amount = context.user_data["topup_amount"]

    topup_id = await db.create_topup(user_id, amount, file_id)
    await update.message.reply_text(f"✅ Top-up request for {amount} THB sent to admin.")
    await send_main_menu(update)

    admin_id = CONFIG["ADMIN_ID"]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{topup_id}"),
         InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{topup_id}")]
    ])
    user_mention = f"[{update.effective_user.full_name}](tg://user?id={user_id})"
    await context.bot.send_photo(
        admin_id,
        photo=file_id,
        caption=f"🔔 New top-up from {user_mention}\nAmount: {amount} THB",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel_topup_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    traffic = xui.get_client_traffic(client["email"])
    download = traffic.get("downlink", 0) if traffic else 0
    upload = traffic.get("uplink", 0) if traffic else 0
    total_used = download + upload
    await db.update_client_usage(user_id, download, upload)

    now = datetime.utcnow()
    expiry = datetime.fromisoformat(client["expiry_at"]) if client["expiry_at"] else None
    if expiry:
        days_left = (expiry - now).days
        is_expired = days_left < 0
        status_emoji = "🔴" if is_expired else "🟢"
        expiry_str = expiry.strftime("%d %b %Y") + f" ({days_left} days left)" if not is_expired else "Expired"
    else:
        status_emoji = "🟢"
        expiry_str = "Unlimited"

    total_gb = client["total_gb"]
    used_gb = total_used / (1024**3)
    limit_gb = total_gb / (1024**3)
    usage_percent = (used_gb / limit_gb * 100) if limit_gb > 0 else 0

    info = (
        f"👤 *Account Information*\n\n"
        f"💰 Balance: *{balance} THB*\n"
        f"📦 Plan: *{client['plan_name']}*\n"
        f"📅 Expiry: {expiry_str}\n"
        f"{status_emoji} Status: *{'Active' if not is_expired else 'Expired'}*\n\n"
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
    for bank in banks:
        text = f"🏦 *{bank['name']}*\n💳 {bank['number']}\n👤 {bank['holder']}"
        if bank.get('logo_file_id'):
            await update.message.reply_photo(photo=bank['logo_file_id'], caption=text, parse_mode="Markdown")
        elif bank.get('qr_file_id'):
            await update.message.reply_photo(photo=bank['qr_file_id'], caption=text, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, parse_mode="Markdown")

async def show_admin_panel(update: Update):
    keyboard = [
        [InlineKeyboardButton("➕ Add Bank", callback_data="admin_addbank")],
        [InlineKeyboardButton("📋 Pending TopUps", callback_data="admin_pending")],
        [InlineKeyboardButton("🏦 Manage Banks", callback_data="admin_listbanks")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_back")],
    ]
    await update.message.reply_text("⚙️ *Admin Panel*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "menu_back":
        await query.message.delete()
        await send_main_menu(query)

    elif data.startswith("buy_"):
        plan_id = int(data.split("_")[1])
        await process_buy_plan(query, plan_id)

    elif data == "admin_addbank":
        context.user_data["bank_edit_id"] = None
        await query.edit_message_text("🏦 Enter bank name (e.g., KBank):")
        return BANK_NAME

    elif data == "admin_pending":
        await show_pending_topups(query)

    elif data == "admin_listbanks":
        await manage_banks(query)

    elif data.startswith("delbank_"):
        bank_id = int(data.split("_")[1])
        await db.delete_bank(bank_id)
        await query.answer("Bank deleted.")
        await manage_banks(query)

    elif data.startswith("editbank_"):
        bank_id = int(data.split("_")[1])
        context.user_data["bank_edit_id"] = bank_id
        await query.edit_message_text(
            "Select field to edit:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Name", callback_data="editfield_name")],
                [InlineKeyboardButton("Number", callback_data="editfield_number")],
                [InlineKeyboardButton("Holder", callback_data="editfield_holder")],
                [InlineKeyboardButton("QR", callback_data="editfield_qr")],
                [InlineKeyboardButton("Logo", callback_data="editfield_logo")],
                [InlineKeyboardButton("🔙 Cancel", callback_data="admin_listbanks")],
            ])
        )
        return EDIT_BANK_FIELD

    elif data.startswith("editfield_"):
        field = data.split("_")[1]
        context.user_data["edit_field"] = field
        prompt = {
            "name": "Enter new bank name:",
            "number": "Enter new account number:",
            "holder": "Enter new account holder:",
            "qr": "Send new QR photo or enter URL:",
            "logo": "Send new Logo photo or enter URL:",
        }
        await query.edit_message_text(prompt[field])
        return EDIT_BANK_VALUE

async def process_buy_plan(query, plan_id: int):
    user_id = query.from_user.id
    plans = await db.get_plans()
    plan = next((p for p in plans if p["id"] == plan_id), None)
    if not plan:
        await query.edit_message_text("❌ Plan not found.")
        return

    is_admin = await db.is_admin(user_id)
    if not is_admin:
        balance = await db.get_balance(user_id)
        if balance < plan["price"]:
            await query.edit_message_text("❌ Insufficient balance.")
            return

    if not is_admin:
        await db.update_balance(user_id, -plan["price"])

    await query.edit_message_text("⏳ Creating VLESS client...")
    try:
        uuid_str = str(uuid.uuid4())
        email = f"user_{user_id}_{uuid_str[:8]}"
        expiry_time = int((datetime.utcnow() + timedelta(days=plan["days"])).timestamp() * 1000)
        total_bytes = plan["data_gb"] * 1024**3
        xui.add_client(
            CONFIG["INBOUND_ID"], email, uuid_str,
            total_gb=total_bytes, expiry_time=expiry_time
        )
        await db.add_client(
            user_id, uuid_str, email, plan_id,
            total_gb=total_bytes,
            expiry_at=datetime.utcnow() + timedelta(days=plan["days"])
        )

        link = generate_vless_link(uuid_str, plan["name"])
        qr_bytes = generate_qr_bytes(link)

        caption = (
            f"✅ *Plan Purchased Successfully!*\n\n"
            f"📦 Plan: *{plan['name']}*\n"
            f"📅 Expires: {(datetime.utcnow() + timedelta(days=plan['days'])).strftime('%d %b %Y')}\n"
            f"🔗 VLESS Link: `{link}`\n"
            f"📱 Scan QR code to import"
        )
        await query.message.delete()
        await query.message.reply_photo(photo=qr_bytes, caption=caption, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Add client error: {e}")
        if not is_admin:
            await db.update_balance(user_id, plan["price"])
        await query.edit_message_text(f"❌ Failed: {str(e)[:200]}")

async def admin_note_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    action_data = context.user_data.get("admin_action")
    if not action_data:
        await update.message.reply_text("Session expired.")
        return ConversationHandler.END

    note = text if text != "/skip" else None
    topup_id = action_data["topup_id"]
    action = action_data["action"]

    if action == "approve":
        await approve_topup_with_note(update, context, topup_id, note)
    else:
        await cancel_topup_with_note(update, context, topup_id, note)

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
    await update.message.reply_text(f"✅ Top-up {topup['amount']} THB approved with note sent.")

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
    await update.message.reply_text(f"❌ Top-up {topup['amount']} THB cancelled with note sent.")

async def show_pending_topups(query):
    pending = await db.get_pending_topups()
    if not pending:
        await query.edit_message_text("📭 No pending requests.")
        return
    text = "📋 *Pending TopUps:*\n"
    for req in pending:
        text += f"ID: {req['id']} | User: {req['user_id']} | {req['amount']} THB\n"
    await query.edit_message_text(text, parse_mode="Markdown")

async def manage_banks(query):
    banks = await db.get_banks()
    keyboard = []
    for bank in banks:
        keyboard.append([
            InlineKeyboardButton(f"✏️ Edit {bank['name']}", callback_data=f"editbank_{bank['id']}"),
            InlineKeyboardButton(f"❌ Delete", callback_data=f"delbank_{bank['id']}")
        ])
    keyboard.append([InlineKeyboardButton("➕ Add Bank", callback_data="admin_addbank")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
    await query.edit_message_text("🏦 *Manage Banks*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ==================== Bank Addition / Edit Conversations ====================
async def bank_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_name"] = update.message.text
    await update.message.reply_text("💳 Enter account number:")
    return BANK_NUMBER

async def bank_number_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_number"] = update.message.text
    await update.message.reply_text("👤 Enter account holder name:")
    return BANK_HOLDER

async def bank_holder_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_holder"] = update.message.text
    await update.message.reply_text("📷 Send QR code photo or enter URL (or /skip):")
    return BANK_QR

async def bank_qr_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data["bank_qr"] = update.message.photo[-1].file_id
    elif update.message.text and update.message.text != "/skip":
        url = update.message.text.strip()
        if is_url(url):
            context.user_data["bank_qr"] = url
        else:
            await update.message.reply_text("Invalid URL. Please send a valid photo or URL.")
            return BANK_QR
    else:
        context.user_data["bank_qr"] = None

    await update.message.reply_text("🖼️ Send bank logo photo or enter URL (or /skip):")
    return BANK_LOGO

async def bank_logo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data["bank_logo"] = update.message.photo[-1].file_id
    elif update.message.text and update.message.text != "/skip":
        url = update.message.text.strip()
        if is_url(url):
            context.user_data["bank_logo"] = url
        else:
            await update.message.reply_text("Invalid URL. Please send a valid photo or URL.")
            return BANK_LOGO
    else:
        context.user_data["bank_logo"] = None

    # Save to DB
    edit_id = context.user_data.get("bank_edit_id")
    if edit_id:
        await db.update_bank(
            edit_id,
            context.user_data["bank_name"],
            context.user_data["bank_number"],
            context.user_data["bank_holder"],
            context.user_data.get("bank_qr"),
            context.user_data.get("bank_logo")
        )
        await update.message.reply_text("✅ Bank updated successfully.")
    else:
        await db.add_bank(
            context.user_data["bank_name"],
            context.user_data["bank_number"],
            context.user_data["bank_holder"],
            context.user_data.get("bank_qr"),
            context.user_data.get("bank_logo")
        )
        await update.message.reply_text("✅ Bank added successfully.")

    await send_main_menu(update)
    return ConversationHandler.END

async def edit_field_value_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bank_id = context.user_data.get("bank_edit_id")
    field = context.user_data.get("edit_field")
    if not bank_id or not field:
        await update.message.reply_text("Session error.")
        return ConversationHandler.END

    bank = await db.get_bank(bank_id)
    if not bank:
        await update.message.reply_text("Bank not found.")
        return ConversationHandler.END

    value = update.message.text
    if field in ["qr", "logo"]:
        if update.message.photo:
            value = update.message.photo[-1].file_id
        elif value and value != "/skip":
            if not is_url(value):
                await update.message.reply_text("Invalid URL.")
                return EDIT_BANK_VALUE
        else:
            value = None
    elif value == "/skip":
        await update.message.reply_text("Edit cancelled.")
        return ConversationHandler.END

    # Update field
    updates = {
        "name": bank["name"],
        "number": bank["number"],
        "holder": bank["holder"],
        "qr_file_id": bank["qr_file_id"],
        "logo_file_id": bank["logo_file_id"],
    }
    if field == "name":
        updates["name"] = value
    elif field == "number":
        updates["number"] = value
    elif field == "holder":
        updates["holder"] = value
    elif field == "qr":
        updates["qr_file_id"] = value
    elif field == "logo":
        updates["logo_file_id"] = value

    await db.update_bank(bank_id, updates["name"], updates["number"], updates["holder"], updates["qr_file_id"], updates["logo_file_id"])
    await update.message.reply_text("✅ Bank updated.")
    await send_main_menu(update)
    return ConversationHandler.END

async def cancel_bank_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    print("\n✅ Configuration saved.\n")

def main():
    get_config()
    global xui
    try:
        xui = XUIClient()
        logger.info(f"Successfully connected to Alireza0 X-UI panel. API base: {xui.base_url}")
    except Exception as e:
        logger.error(f"Cannot login to X-UI: {e}")
        print("\n❌ X-UI Login failed. Please check your Panel URL, Username, Password.")
        return

    app = Application.builder().token(CONFIG["BOT_TOKEN"]).build()

    # Admin note conversation (MUST be first to catch approve/cancel callbacks)
    admin_note_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_note_start, pattern="^(approve_|cancel_)")],
        states={
            ADMIN_NOTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_note_input),
                CommandHandler("skip", admin_note_input)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_topup_conv)],
        per_message=False,
    )

    async def admin_note_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        parts = data.split("_")
        action = parts[0]
        topup_id = int(parts[1])
        context.user_data["admin_action"] = {"action": action, "topup_id": topup_id}
        await query.edit_message_text(
            f"📝 Enter a note for the user (optional).\n"
            f"Send /skip to proceed without a note."
        )
        return ADMIN_NOTE

    topup_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(topup_amount_selected, pattern="^topup_amt_")],
        states={TO_SLIP: [MessageHandler(filters.PHOTO, receive_slip)]},
        fallbacks=[CommandHandler("cancel", cancel_topup_conv)],
        per_message=False,
    )

    # Bank addition conversation
    bank_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u,c: BANK_NAME, pattern="^admin_addbank$")],
        states={
            BANK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_name_input)],
            BANK_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_number_input)],
            BANK_HOLDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_holder_input)],
            BANK_QR: [
                MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), bank_qr_input),
                CommandHandler("skip", bank_qr_input)
            ],
            BANK_LOGO: [
                MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), bank_logo_input),
                CommandHandler("skip", bank_logo_input)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_bank_conv)],
        per_message=False,
    )

    # Bank edit conversation
    bank_edit_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(lambda u,c: EDIT_BANK_FIELD, pattern="^editbank_"),
            CallbackQueryHandler(lambda u,c: EDIT_BANK_FIELD, pattern="^editfield_")
        ],
        states={
            EDIT_BANK_FIELD: [CallbackQueryHandler(edit_field_selected, pattern="^editfield_")],
            EDIT_BANK_VALUE: [
                MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), edit_field_value_input),
                CommandHandler("skip", edit_field_value_input)
            ],
        },
        fallbacks=[CallbackQueryHandler(manage_banks, pattern="^admin_listbanks$")],
        per_message=False,
    )

    async def edit_field_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        field = data.split("_")[1]
        context.user_data["edit_field"] = field
        prompt = {
            "name": "Enter new bank name:",
            "number": "Enter new account number:",
            "holder": "Enter new account holder:",
            "qr": "Send new QR photo or enter URL (/skip to keep):",
            "logo": "Send new Logo photo or enter URL (/skip to keep):",
        }
        await query.edit_message_text(prompt[field])
        return EDIT_BANK_VALUE

    # Important: Add admin_note_conv first so it catches approve/cancel before callback_handler
    app.add_handler(admin_note_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(topup_conv)
    app.add_handler(bank_add_conv)
    app.add_handler(bank_edit_conv)
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
