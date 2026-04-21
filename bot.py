#!/usr/bin/env python3
"""
Telegram VLESS Bot with X-UI integration (FULLY FIXED)
- Admin panel auto-detection
- TopUp with slip photo
- Bank management
- VLESS client creation with detailed error handling
"""

import asyncio
import io
import json
import logging
import sqlite3
import uuid
from datetime import datetime
from typing import Optional, Dict, List

import qrcode
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

# ==================== Config ====================
CONFIG = {
    "BOT_TOKEN": "",
    "ADMIN_ID": 0,
    "PANEL_URL": "",
    "PANEL_USER": "",
    "PANEL_PASS": "",
    "INBOUND_ID": 0,
    "PORT": 0,
    "WS_PATH": "",
    "HOST": "",
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
                    qr_file_id TEXT
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            plans = [
                ("30 DAYS 200GB", 30, 200, 40),
                ("60 DAYS 300GB", 60, 300, 60),
            ]
            for name, days, gb, price in plans:
                conn.execute(
                    "INSERT OR IGNORE INTO plans (name, days, data_gb, price) VALUES (?,?,?,?)",
                    (name, days, gb, price)
                )

    async def execute(self, query: str, params: tuple = ()):
        def _run():
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(query, params)
                conn.commit()
                return cur.fetchall() if query.strip().upper().startswith("SELECT") else cur.lastrowid
        return await asyncio.to_thread(_run)

    async def get_user(self, user_id: int):
        rows = await self.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return dict(rows[0]) if rows else None

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
        return dict(rows[0]) if rows else None

    async def update_topup_status(self, topup_id: int, status: str):
        await self.execute("UPDATE topup_requests SET status = ? WHERE id = ?", (status, topup_id))

    async def get_pending_topups(self):
        rows = await self.execute("SELECT * FROM topup_requests WHERE status = 'pending' ORDER BY created_at")
        return [dict(r) for r in rows]

    async def add_bank(self, name: str, number: str, holder: str, qr_file_id: str):
        await self.execute(
            "INSERT INTO banks (name, number, holder, qr_file_id) VALUES (?,?,?,?)",
            (name, number, holder, qr_file_id)
        )

    async def get_banks(self):
        rows = await self.execute("SELECT * FROM banks ORDER BY id")
        return [dict(r) for r in rows]

    async def delete_bank(self, bank_id: int):
        await self.execute("DELETE FROM banks WHERE id = ?", (bank_id,))

    async def get_plans(self):
        rows = await self.execute("SELECT * FROM plans ORDER BY price")
        return [dict(r) for r in rows]

    async def add_client(self, user_id: int, uuid_str: str, email: str):
        await self.execute(
            "INSERT INTO user_clients (user_id, uuid, email) VALUES (?,?,?)",
            (user_id, uuid_str, email)
        )

    async def get_client(self, user_id: int):
        rows = await self.execute(
            "SELECT * FROM user_clients WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        )
        return dict(rows[0]) if rows else None

db = Database()

# ==================== X-UI Client ====================
class XUIClient:
    def __init__(self):
        self.base_url = CONFIG["PANEL_URL"].rstrip("/")
        self.session = requests.Session()
        self._login()

    def _login(self):
        url = f"{self.base_url}/login"
        data = {"username": CONFIG["PANEL_USER"], "password": CONFIG["PANEL_PASS"]}
        resp = self.session.post(url, data=data)
        if resp.status_code != 200:
            raise Exception(f"Login failed: {resp.status_code}")
        if not resp.json().get("success"):
            raise Exception(f"Login error: {resp.text}")

    def add_client(self, inbound_id: int, email: str, uuid_str: str) -> dict:
        url = f"{self.base_url}/panel/api/inbounds/addClient"
        settings = {"clients": [{"email": email, "id": uuid_str, "enable": True, "flow": ""}]}
        data = {"id": inbound_id, "settings": json.dumps(settings)}
        resp = self.session.post(url, data=data)
        if resp.status_code != 200:
            raise Exception(f"Add client HTTP {resp.status_code}: {resp.text}")
        result = resp.json()
        if not result.get("success"):
            raise Exception(f"Add client error: {result.get('msg')}")
        return result

xui = None

# ==================== Helpers ====================
def generate_vless_link(uuid_str: str, remark: str = "") -> str:
    host = CONFIG["HOST"]
    port = CONFIG["PORT"]
    path = CONFIG["WS_PATH"] or "/"
    link = f"vless://{uuid_str}@{host}:{port}?path={path}&security=none&encryption=none&type=ws&host={host}"
    if remark:
        link += f"#{remark}"
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
# Topup with slip
TO_AMOUNT, TO_SLIP = range(2)
# Bank addition
BANK_NAME, BANK_NUMBER, BANK_HOLDER, BANK_QR = range(4)

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
        await start_topup(update, context)
    elif text == "👤 Account":
        await show_account(update)
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
    await update.message.reply_text("Select a plan:", reply_markup=InlineKeyboardMarkup(keyboard))

# ---------- Topup with Slip ----------
async def start_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amounts = [40, 60, 100]
    keyboard = [[InlineKeyboardButton(f"{amt} THB", callback_data=f"topup_amt_{amt}")] for amt in amounts]
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
    await update.message.reply_text("Select amount:", reply_markup=InlineKeyboardMarkup(keyboard))

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
    await query.edit_message_text(f"Amount: {amount} THB\nPlease send the payment slip photo.")
    return TO_SLIP

async def receive_slip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    file_id = photo.file_id
    amount = context.user_data["topup_amount"]

    topup_id = await db.create_topup(user_id, amount, file_id)
    await update.message.reply_text(f"✅ Top-up request for {amount} THB with slip sent to admin.")

    # Notify admin
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
    await send_main_menu(update)
    return ConversationHandler.END

async def cancel_topup_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_main_menu(update)
    return ConversationHandler.END

# ---------- Account ----------
async def show_account(update: Update):
    user_id = update.effective_user.id
    balance = await db.get_balance(user_id)
    client = await db.get_client(user_id)
    info = f"👤 Account\n💰 Balance: {balance} THB\n"
    if client:
        info += f"🔑 VLESS UUID: `{client['uuid']}`\n📧 Email: {client['email']}"
    else:
        info += "No active VLESS client."
    await update.message.reply_text(info, parse_mode="Markdown")

# ---------- Banks ----------
async def show_banks(update: Update):
    banks = await db.get_banks()
    if not banks:
        await update.message.reply_text("No bank accounts available.")
        return
    for bank in banks:
        text = f"🏦 {bank['name']}\n💳 {bank['number']}\n👤 {bank['holder']}"
        if bank['qr_file_id']:
            await update.message.reply_photo(photo=bank['qr_file_id'], caption=text)
        else:
            await update.message.reply_text(text)

# ---------- Admin Panel ----------
async def show_admin_panel(update: Update):
    keyboard = [
        [InlineKeyboardButton("➕ Add Bank", callback_data="admin_addbank")],
        [InlineKeyboardButton("📋 Pending TopUps", callback_data="admin_pending")],
        [InlineKeyboardButton("🏦 Manage Banks", callback_data="admin_listbanks")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_back")],
    ]
    await update.message.reply_text("Admin Panel:", reply_markup=InlineKeyboardMarkup(keyboard))

# ---------- Callback Handlers ----------
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

    elif data.startswith("approve_"):
        topup_id = int(data.split("_")[1])
        await approve_topup(query, topup_id)

    elif data.startswith("cancel_"):
        topup_id = int(data.split("_")[1])
        await cancel_topup(query, topup_id)

    elif data == "admin_addbank":
        await query.edit_message_text("Enter bank name (e.g., KBank):")
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

async def process_buy_plan(query, plan_id: int):
    user_id = query.from_user.id
    plans = await db.get_plans()
    plan = next((p for p in plans if p["id"] == plan_id), None)
    if not plan:
        await query.edit_message_text("Plan not found.")
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
        xui.add_client(CONFIG["INBOUND_ID"], email, uuid_str)
        await db.add_client(user_id, uuid_str, email)

        link = generate_vless_link(uuid_str, plan["name"])
        qr_bytes = generate_qr_bytes(link)

        caption = f"✅ Plan: {plan['name']}\n🔗 `{link}`\n📱 Scan QR"
        await query.message.delete()
        await query.message.reply_photo(photo=qr_bytes, caption=caption, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Add client error: {e}")
        if not is_admin:
            await db.update_balance(user_id, plan["price"])
        await query.edit_message_text(f"❌ Failed: {str(e)[:200]}")

async def approve_topup(query, topup_id: int):
    topup = await db.get_topup(topup_id)
    if not topup or topup["status"] != "pending":
        await query.edit_message_text("Already processed.")
        return
    await db.update_topup_status(topup_id, "approved")
    await db.update_balance(topup["user_id"], topup["amount"])
    await query.edit_message_text(f"✅ Top-up {topup['amount']} THB approved.")
    await query.message.reply_text(f"✅ Your top-up of {topup['amount']} THB has been approved.",
                                   reply_to_message_id=topup["user_id"])

async def cancel_topup(query, topup_id: int):
    topup = await db.get_topup(topup_id)
    if not topup or topup["status"] != "pending":
        await query.edit_message_text("Already processed.")
        return
    await db.update_topup_status(topup_id, "cancelled")
    await query.edit_message_text(f"❌ Top-up {topup['amount']} THB cancelled.")
    await query.message.reply_text(f"❌ Your top-up request of {topup['amount']} THB was cancelled.",
                                   reply_to_message_id=topup["user_id"])

async def show_pending_topups(query):
    pending = await db.get_pending_topups()
    if not pending:
        await query.edit_message_text("No pending requests.")
        return
    text = "📋 Pending TopUps:\n"
    for req in pending:
        text += f"ID: {req['id']} | User: {req['user_id']} | {req['amount']} THB\n"
    await query.edit_message_text(text)

async def manage_banks(query):
    banks = await db.get_banks()
    keyboard = []
    for bank in banks:
        keyboard.append([InlineKeyboardButton(f"❌ Delete {bank['name']}", callback_data=f"delbank_{bank['id']}")])
    keyboard.append([InlineKeyboardButton("➕ Add Bank", callback_data="admin_addbank")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
    await query.edit_message_text("Manage Banks:", reply_markup=InlineKeyboardMarkup(keyboard))

# ---------- Bank Addition Conversation ----------
async def bank_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_name"] = update.message.text
    await update.message.reply_text("Enter account number:")
    return BANK_NUMBER

async def bank_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_number"] = update.message.text
    await update.message.reply_text("Enter account holder name:")
    return BANK_HOLDER

async def bank_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_holder"] = update.message.text
    await update.message.reply_text("Send QR code photo:")
    return BANK_QR

async def bank_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    context.user_data["bank_qr"] = photo.file_id
    await db.add_bank(
        context.user_data["bank_name"],
        context.user_data["bank_number"],
        context.user_data["bank_holder"],
        context.user_data["bank_qr"]
    )
    await update.message.reply_text("✅ Bank added.")
    await send_main_menu(update)
    return ConversationHandler.END

# ==================== Config Prompt ====================
def get_config():
    print("\n🔧 First-time configuration\n")
    CONFIG["BOT_TOKEN"] = input("Enter Bot Token: ").strip()
    CONFIG["ADMIN_ID"] = int(input("Enter Admin Telegram ID: ").strip())
    CONFIG["PANEL_URL"] = input("Enter X-UI Panel URL: ").strip()
    CONFIG["PANEL_USER"] = input("Enter Panel Username: ").strip()
    CONFIG["PANEL_PASS"] = input("Enter Panel Password: ").strip()
    CONFIG["INBOUND_ID"] = int(input("Enter Inbound ID: ").strip())
    CONFIG["PORT"] = int(input("Enter Port: ").strip())
    ws_path = input("Enter WS Path [default: /]: ").strip()
    CONFIG["WS_PATH"] = ws_path if ws_path else "/"
    CONFIG["HOST"] = input("Enter Host (domain/IP): ").strip()
    print("✅ Configuration saved.\n")

def main():
    get_config()
    global xui
    xui = XUIClient()

    app = Application.builder().token(CONFIG["BOT_TOKEN"]).build()

    # Topup conversation (with slip)
    topup_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(topup_amount_selected, pattern="^topup_amt_")],
        states={
            TO_SLIP: [MessageHandler(filters.PHOTO, receive_slip)],
        },
        fallbacks=[CommandHandler("cancel", cancel_topup_conv)],
    )

    # Bank addition conversation
    bank_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u,c: BANK_NAME, pattern="^admin_addbank$")],
        states={
            BANK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_name)],
            BANK_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_number)],
            BANK_HOLDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_holder)],
            BANK_QR: [MessageHandler(filters.PHOTO, bank_qr)],
        },
        fallbacks=[CommandHandler("cancel", cancel_topup_conv)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(topup_conv)
    app.add_handler(bank_conv)
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
