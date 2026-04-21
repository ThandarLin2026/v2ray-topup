#!/usr/bin/env python3
"""
Telegram VLESS Bot with X-UI integration.
Run: python3 bot.py
First run will ask for configuration interactively.
"""

import asyncio
import io
import json
import logging
import sqlite3
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List

import qrcode
import requests
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
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

# ==================== Configuration (set at runtime) ====================
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

# ==================== Logging ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== Database ====================
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
            # Insert default plans if not exist
            plans = [
                ("30 DAYS 200GB", 30, 200, 40),
                ("60 DAYS 300GB", 60, 300, 60),
            ]
            for name, days, gb, price in plans:
                conn.execute(
                    "INSERT OR IGNORE INTO plans (name, days, data_gb, price) VALUES (?,?,?,?)",
                    (name, days, gb, price)
                )

    async def execute(self, query: str, params: tuple = ()) -> Any:
        """Run a DB query in a thread to avoid blocking."""
        def _run():
            with sqlite3.connect(DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(query, params)
                conn.commit()
                return cur.fetchall() if query.strip().upper().startswith("SELECT") else cur.lastrowid
        return await asyncio.to_thread(_run)

    async def get_user(self, user_id: int) -> Optional[Dict]:
        rows = await self.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return dict(rows[0]) if rows else None

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

    async def create_topup(self, user_id: int, amount: int) -> int:
        return await self.execute(
            "INSERT INTO topup_requests (user_id, amount) VALUES (?,?)",
            (user_id, amount)
        )

    async def get_topup(self, topup_id: int) -> Optional[Dict]:
        rows = await self.execute("SELECT * FROM topup_requests WHERE id = ?", (topup_id,))
        return dict(rows[0]) if rows else None

    async def update_topup_status(self, topup_id: int, status: str):
        await self.execute(
            "UPDATE topup_requests SET status = ? WHERE id = ?",
            (status, topup_id)
        )

    async def get_pending_topups(self) -> List[Dict]:
        rows = await self.execute(
            "SELECT * FROM topup_requests WHERE status = 'pending' ORDER BY created_at"
        )
        return [dict(r) for r in rows]

    async def add_bank(self, name: str, number: str, holder: str, qr_file_id: str):
        await self.execute(
            "INSERT INTO banks (name, number, holder, qr_file_id) VALUES (?,?,?,?)",
            (name, number, holder, qr_file_id)
        )

    async def get_banks(self) -> List[Dict]:
        rows = await self.execute("SELECT * FROM banks ORDER BY id")
        return [dict(r) for r in rows]

    async def delete_bank(self, bank_id: int):
        await self.execute("DELETE FROM banks WHERE id = ?", (bank_id,))

    async def get_plans(self) -> List[Dict]:
        rows = await self.execute("SELECT * FROM plans ORDER BY price")
        return [dict(r) for r in rows]

    async def add_client(self, user_id: int, uuid_str: str, email: str):
        await self.execute(
            "INSERT INTO user_clients (user_id, uuid, email) VALUES (?,?,?)",
            (user_id, uuid_str, email)
        )

    async def get_client(self, user_id: int) -> Optional[Dict]:
        rows = await self.execute(
            "SELECT * FROM user_clients WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        )
        return dict(rows[0]) if rows else None

db = Database()

# ==================== X-UI Panel API ====================
class XUIClient:
    def __init__(self):
        self.base_url = CONFIG["PANEL_URL"].rstrip("/")
        self.session = requests.Session()
        self._login()

    def _login(self):
        url = f"{self.base_url}/login"
        data = {"username": CONFIG["PANEL_USER"], "password": CONFIG["PANEL_PASS"]}
        resp = self.session.post(url, data=data)
        resp.raise_for_status()
        if resp.json().get("success") is not True:
            raise Exception("X-UI login failed")

    def add_client(self, inbound_id: int, email: str, uuid_str: str) -> dict:
        url = f"{self.base_url}/panel/api/inbounds/addClient"
        data = {
            "id": inbound_id,
            "settings": json.dumps({
                "clients": [{
                    "email": email,
                    "id": uuid_str,
                    "flow": "",
                    "enable": True,
                }]
            })
        }
        resp = self.session.post(url, data=data)
        resp.raise_for_status()
        return resp.json()

xui = None  # will be initialized after config

# ==================== Helper Functions ====================
def generate_vless_link(uuid_str: str, remark: str = "") -> str:
    host = CONFIG["HOST"]
    port = CONFIG["PORT"]
    path = CONFIG["WS_PATH"]
    if not path:
        path = "/"  # default if empty
    # VLESS link format: vless://uuid@host:port?path=ws_path&security=none&encryption=none&type=ws&host=host#remark
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

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = await db.is_admin(user_id)
    keyboard = await get_main_keyboard(is_admin)
    await update.message.reply_text("📋 Main Menu:", reply_markup=keyboard)

# ==================== Conversation States ====================
# For admin bank addition flow
BANK_NAME, BANK_NUMBER, BANK_HOLDER, BANK_QR = range(4)

# ==================== Handlers ====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command"""
    await send_main_menu(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main message handler for keyboard menu."""
    user = update.effective_user
    user_id = user.id
    text = update.message.text

    # Ensure user exists in DB
    await db.create_user(user_id, user.username or user.full_name)
    # Set admin if matches configured ID
    if user_id == CONFIG["ADMIN_ID"]:
        await db.set_admin(user_id)

    # Route based on text
    if text == "🛒 Buy Plan":
        await show_plans(update, context)
    elif text == "💰 TopUp":
        await show_topup_options(update, context)
    elif text == "👤 Account":
        await show_account(update, context)
    elif text == "🏦 Banks":
        await show_banks(update, context)
    elif text == "⚙️ Admin Panel" and await db.is_admin(user_id):
        await show_admin_panel(update, context)
    elif text == "🔙 Back":
        await send_main_menu(update, context)
    else:
        # If user sends something else, show menu anyway
        await send_main_menu(update, context)

async def show_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plans = await db.get_plans()
    keyboard = []
    for plan in plans:
        btn_text = f"{plan['name']} - {plan['price']} THB"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"buy_{plan['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
    await update.message.reply_text(
        "Select a plan:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_topup_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amounts = [40, 60, 100]
    keyboard = []
    for amt in amounts:
        keyboard.append([InlineKeyboardButton(f"{amt} THB", callback_data=f"topup_{amt}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
    await update.message.reply_text(
        "Select top-up amount:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = await db.get_balance(user_id)
    client = await db.get_client(user_id)
    info = f"👤 Account\n💰 Balance: {balance} THB\n"
    if client:
        info += f"🔑 VLESS UUID: `{client['uuid']}`\n📧 Email: {client['email']}"
    else:
        info += "No active VLESS client."
    await update.message.reply_text(info, parse_mode="Markdown")

async def show_banks(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Add Bank", callback_data="admin_addbank")],
        [InlineKeyboardButton("📋 Pending TopUps", callback_data="admin_pending")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_back")],
    ]
    await update.message.reply_text(
        "Admin Panel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==================== Callback Handlers ====================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "menu_back":
        await query.message.delete()
        is_admin = await db.is_admin(user_id)
        keyboard = await get_main_keyboard(is_admin)
        await query.message.reply_text("Main Menu:", reply_markup=keyboard)

    elif data.startswith("buy_"):
        plan_id = int(data.split("_")[1])
        await process_buy_plan(query, plan_id, context)

    elif data.startswith("topup_"):
        amount = int(data.split("_")[1])
        await create_topup_request(query, amount, context)

    elif data.startswith("approve_"):
        topup_id = int(data.split("_")[1])
        await approve_topup(query, topup_id, context)

    elif data.startswith("cancel_"):
        topup_id = int(data.split("_")[1])
        await cancel_topup(query, topup_id, context)

    elif data == "admin_addbank":
        await start_bank_addition(update, context)

    elif data == "admin_pending":
        await show_pending_topups(query, context)

    elif data.startswith("delbank_"):
        bank_id = int(data.split("_")[1])
        await db.delete_bank(bank_id)
        await query.edit_message_text("Bank deleted.")
        await show_admin_panel_menu(query)

async def process_buy_plan(query, plan_id: int, context):
    user_id = query.from_user.id
    plans = await db.get_plans()
    plan = next((p for p in plans if p["id"] == plan_id), None)
    if not plan:
        await query.edit_message_text("Plan not found.")
        return

    # Check balance (admin unlimited)
    is_admin = await db.is_admin(user_id)
    if not is_admin:
        balance = await db.get_balance(user_id)
        if balance < plan["price"]:
            await query.edit_message_text("❌ Insufficient balance.")
            return

    # Deduct balance
    if not is_admin:
        await db.update_balance(user_id, -plan["price"])
    else:
        # Admin gets for free, no deduction
        pass

    # Create VLESS client
    await query.edit_message_text("⏳ Creating your VLESS client...")
    try:
        uuid_str = str(uuid.uuid4())
        email = f"user_{user_id}_{uuid_str[:8]}"
        xui.add_client(CONFIG["INBOUND_ID"], email, uuid_str)
        await db.add_client(user_id, uuid_str, email)

        # Generate link and QR
        remark = f"{plan['name']}"
        link = generate_vless_link(uuid_str, remark)
        qr_bytes = generate_qr_bytes(link)

        # Send to user
        caption = (
            f"✅ Plan purchased: {plan['name']}\n"
            f"🔗 VLESS Link: `{link}`\n"
            f"📱 Scan QR to import"
        )
        await context.bot.send_photo(
            chat_id=user_id,
            photo=qr_bytes,
            caption=caption,
            parse_mode="Markdown"
        )
        await query.delete_message()
    except Exception as e:
        logger.error(f"Error creating client: {e}")
        # Refund if not admin
        if not is_admin:
            await db.update_balance(user_id, plan["price"])
        await query.edit_message_text("❌ Failed to create client. Please try later.")

async def create_topup_request(query, amount: int, context):
    user_id = query.from_user.id
    topup_id = await db.create_topup(user_id, amount)
    await query.edit_message_text(f"✅ Top-up request for {amount} THB sent to admin.")

    # Notify admin
    admin_id = CONFIG["ADMIN_ID"]
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{topup_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{topup_id}"),
        ]
    ])
    user_mention = f"[{query.from_user.full_name}](tg://user?id={user_id})"
    await context.bot.send_message(
        admin_id,
        f"🔔 New top-up request from {user_mention}\nAmount: {amount} THB",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def approve_topup(query, topup_id: int, context):
    topup = await db.get_topup(topup_id)
    if not topup or topup["status"] != "pending":
        await query.edit_message_text("Request already processed.")
        return
    await db.update_topup_status(topup_id, "approved")
    await db.update_balance(topup["user_id"], topup["amount"])
    await query.edit_message_text(f"✅ Top-up {topup['amount']} THB approved.")
    # Notify user
    await context.bot.send_message(
        topup["user_id"],
        f"✅ Your top-up of {topup['amount']} THB has been approved."
    )

async def cancel_topup(query, topup_id: int, context):
    topup = await db.get_topup(topup_id)
    if not topup or topup["status"] != "pending":
        await query.edit_message_text("Request already processed.")
        return
    await db.update_topup_status(topup_id, "cancelled")
    await query.edit_message_text(f"❌ Top-up {topup['amount']} THB cancelled.")
    await context.bot.send_message(
        topup["user_id"],
        f"❌ Your top-up request of {topup['amount']} THB was cancelled."
    )

async def show_pending_topups(query, context):
    pending = await db.get_pending_topups()
    if not pending:
        await query.edit_message_text("No pending top-up requests.")
        return
    text = "📋 Pending TopUps:\n"
    for req in pending:
        text += f"ID: {req['id']} | User: {req['user_id']} | Amount: {req['amount']} THB\n"
    await query.edit_message_text(text)

async def show_admin_panel_menu(query):
    keyboard = [
        [InlineKeyboardButton("➕ Add Bank", callback_data="admin_addbank")],
        [InlineKeyboardButton("📋 Pending TopUps", callback_data="admin_pending")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_back")],
    ]
    await query.edit_message_text("Admin Panel:", reply_markup=InlineKeyboardMarkup(keyboard))

# ==================== Bank Addition Conversation ====================
async def start_bank_addition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("Enter bank name (e.g., KBank):")
    return BANK_NAME

async def bank_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_name"] = update.message.text
    await update.message.reply_text("Enter bank account number:")
    return BANK_NUMBER

async def bank_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_number"] = update.message.text
    await update.message.reply_text("Enter account holder name:")
    return BANK_HOLDER

async def bank_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_holder"] = update.message.text
    await update.message.reply_text("Send the QR code image (as a photo).")
    return BANK_QR

async def bank_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file = await update.message.photo[-1].get_file()
    # Store file_id to reuse
    context.user_data["bank_qr"] = photo_file.file_id
    # Save to DB
    await db.add_bank(
        context.user_data["bank_name"],
        context.user_data["bank_number"],
        context.user_data["bank_holder"],
        context.user_data["bank_qr"]
    )
    await update.message.reply_text("✅ Bank added successfully.")
    # Return to main menu
    is_admin = await db.is_admin(update.effective_user.id)
    keyboard = await get_main_keyboard(is_admin)
    await update.message.reply_text("Main Menu:", reply_markup=keyboard)
    return ConversationHandler.END

async def cancel_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bank addition cancelled.")
    is_admin = await db.is_admin(update.effective_user.id)
    keyboard = await get_main_keyboard(is_admin)
    await update.message.reply_text("Main Menu:", reply_markup=keyboard)
    return ConversationHandler.END

# ==================== Configuration Prompt ====================
def get_config():
    print("\n🔧 First-time configuration\n")
    CONFIG["BOT_TOKEN"] = input("Enter Bot Token: ").strip()
    CONFIG["ADMIN_ID"] = int(input("Enter Admin Telegram ID: ").strip())
    CONFIG["PANEL_URL"] = input("Enter X-UI Panel URL (e.g., http://ip:port): ").strip()
    CONFIG["PANEL_USER"] = input("Enter Panel Username: ").strip()
    CONFIG["PANEL_PASS"] = input("Enter Panel Password: ").strip()
    CONFIG["INBOUND_ID"] = int(input("Enter Inbound ID: ").strip())
    CONFIG["PORT"] = int(input("Enter Port: ").strip())
    ws_path = input("Enter WS Path (e.g., /ws) [default: /]: ").strip()
    if not ws_path:
        ws_path = "/"
    CONFIG["WS_PATH"] = ws_path
    CONFIG["HOST"] = input("Enter Host (domain or IP): ").strip()
    print("✅ Configuration saved.\n")

# ==================== Main ====================
def main():
    get_config()
    global xui
    xui = XUIClient()

    # Build application
    app = Application.builder().token(CONFIG["BOT_TOKEN"]).build()

    # Conversation handler for bank addition (admin only)
    bank_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_bank_addition, pattern="^admin_addbank$")],
        states={
            BANK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_name)],
            BANK_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_number)],
            BANK_HOLDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_holder)],
            BANK_QR: [MessageHandler(filters.PHOTO, bank_qr)],
        },
        fallbacks=[CommandHandler("cancel", cancel_bank)],
        per_message=True  # avoid warning
    )

    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(bank_conv)

    # Start bot
    logger.info("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
