#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram VLESS Bot - Complete Final Version
All features working, including /start, admin note, bank edit/delete, traffic limit, expiry.
"""

import asyncio
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
from urllib.parse import urlparse

# Auto-install required packages
def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

try:
    import requests
except ImportError:
    install("requests")
    import requests

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler
except ImportError:
    install("python-telegram-bot==20.7")
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler

try:
    import qrcode
except ImportError:
    install("qrcode[pil]")
    import qrcode

# ==================== Configuration ====================
CONFIG_FILE = "config.json"
CONFIG = {
    "BOT_TOKEN": "",
    "ADMIN_ID": 0,
    "PANEL_URL": "",
    "PANEL_USER": "",
    "PANEL_PASS": "",
    "INBOUND_ID": 0,
    "PORT": 0,
    "WS_PATH": "/",
    "SERVER_ADDRESS": "",
    "WS_HOST": ""
}

def load_config():
    global CONFIG
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            CONFIG.update(json.load(f))
        return
    print("\n🔧 First-time configuration\n")
    CONFIG["BOT_TOKEN"] = input("Bot Token: ").strip()
    CONFIG["ADMIN_ID"] = int(input("Admin Telegram ID: ").strip())
    CONFIG["PANEL_URL"] = input("Panel URL (with custom path): ").strip()
    CONFIG["PANEL_USER"] = input("Panel Username: ").strip()
    CONFIG["PANEL_PASS"] = input("Panel Password: ").strip()
    CONFIG["INBOUND_ID"] = int(input("Inbound ID: ").strip())
    CONFIG["PORT"] = int(input("Port: ").strip())
    ws = input("WS Path [/]: ").strip()
    CONFIG["WS_PATH"] = ws if ws else "/"
    CONFIG["SERVER_ADDRESS"] = input("Server IP: ").strip()
    CONFIG["WS_HOST"] = input("WS Host (domain): ").strip()
    with open(CONFIG_FILE, 'w') as f:
        json.dump(CONFIG, f, indent=2)
    print("✅ Config saved.\n")

load_config()

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DB_FILE = "bot_data.db"

# ==================== Database ====================
class Database:
    def __init__(self):
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(DB_FILE) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    balance INTEGER DEFAULT 0,
                    is_admin INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS topup_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    slip_file_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS banks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    number TEXT,
                    holder TEXT,
                    qr_file_id TEXT,
                    logo_file_id TEXT
                );
                CREATE TABLE IF NOT EXISTS plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    days INTEGER,
                    data_gb INTEGER,
                    price INTEGER
                );
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
                );
                DELETE FROM plans;
                INSERT INTO plans (name, days, data_gb, price) VALUES 
                    ('30 DAYS 120GB', 30, 120, 40),
                    ('60 DAYS 250GB', 60, 250, 70);
            """)

    async def execute(self, query: str, params: tuple = ()):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self._exec, query, params))

    def _exec(self, q, p):
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(q, p)
            conn.commit()
            if q.strip().upper().startswith("SELECT"):
                return [dict(r) for r in cur.fetchall()]
            return cur.lastrowid

    async def get_user(self, uid): r = await self.execute("SELECT * FROM users WHERE user_id = ?", (uid,)); return r[0] if r else None
    async def create_user(self, uid, uname): await self.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (uid, uname))
    async def update_balance(self, uid, delta): await self.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, uid))
    async def get_balance(self, uid): u = await self.get_user(uid); return u["balance"] if u else 0
    async def set_admin(self, uid): await self.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (uid,))
    async def is_admin(self, uid): u = await self.get_user(uid); return bool(u and u["is_admin"])
    async def create_topup(self, uid, amt, slip=None): return await self.execute("INSERT INTO topup_requests (user_id, amount, slip_file_id) VALUES (?,?,?)", (uid, amt, slip))
    async def get_topup(self, tid): r = await self.execute("SELECT * FROM topup_requests WHERE id = ?", (tid,)); return r[0] if r else None
    async def update_topup_status(self, tid, status): await self.execute("UPDATE topup_requests SET status = ? WHERE id = ?", (status, tid))
    async def get_pending_topups(self): return await self.execute("SELECT * FROM topup_requests WHERE status = 'pending' ORDER BY created_at")
    async def add_bank(self, name, num, holder, qr=None, logo=None): return await self.execute("INSERT INTO banks (name, number, holder, qr_file_id, logo_file_id) VALUES (?,?,?,?,?)", (name, num, holder, qr, logo))
    async def get_banks(self): return await self.execute("SELECT * FROM banks ORDER BY id")
    async def get_bank(self, bid): r = await self.execute("SELECT * FROM banks WHERE id = ?", (bid,)); return r[0] if r else None
    async def update_bank(self, bid, name, num, holder, qr=None, logo=None): await self.execute("UPDATE banks SET name=?, number=?, holder=?, qr_file_id=?, logo_file_id=? WHERE id=?", (name, num, holder, qr, logo, bid))
    async def delete_bank(self, bid): await self.execute("DELETE FROM banks WHERE id = ?", (bid,))
    async def get_plans(self): return await self.execute("SELECT * FROM plans ORDER BY price")
    async def add_client(self, uid, u, e, pid, total, exp): await self.execute("INSERT INTO user_clients (user_id, uuid, email, plan_id, expiry_at, total_gb) VALUES (?,?,?,?,?,?)", (uid, u, e, pid, exp, total))
    async def get_client(self, uid): r = await self.execute("SELECT uc.*, p.name as plan_name FROM user_clients uc LEFT JOIN plans p ON uc.plan_id = p.id WHERE uc.user_id = ? ORDER BY uc.created_at DESC LIMIT 1", (uid,)); return r[0] if r else None
    async def update_client_usage(self, uid, down, up): await self.execute("UPDATE user_clients SET download_used=?, upload_used=? WHERE user_id=?", (down, up, uid))

db = Database()

# ==================== Alireza0 X-UI Client ====================
class XUIClient:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = self._detect_api_base()
        self.api_path = "/xui/API/inbounds"

    def _detect_api_base(self):
        panel = CONFIG["PANEL_URL"].rstrip("/")
        root = "/".join(panel.split("/")[:3])
        if self._try_login(root): return root
        if self._try_login(panel): return panel
        raise Exception("X-UI login failed")

    def _try_login(self, base):
        try:
            resp = self.session.post(f"{base}/login", data={"username": CONFIG["PANEL_USER"], "password": CONFIG["PANEL_PASS"]}, timeout=10)
            if resp.status_code == 200 and resp.json().get("success"):
                self.base_url = base
                return True
        except: pass
        return False

    def add_client(self, inbound_id, email, uuid_str, total_gb=0, expiry_time=0):
        url = f"{self.base_url}{self.api_path}/addClient/"
        settings = {"clients": [{"email": email, "id": uuid_str, "enable": True, "flow": "", "totalGB": total_gb, "expiryTime": expiry_time, "limitIp": 0}]}
        resp = self.session.post(url, data={"id": inbound_id, "settings": json.dumps(settings)})
        if resp.status_code != 200: raise Exception(f"HTTP {resp.status_code}")
        data = resp.json()
        if not data.get("success"): raise Exception(data.get("msg", "Unknown error"))
        return data

    def get_client_traffic(self, email):
        try:
            resp = self.session.get(f"{self.base_url}{self.api_path}/getClientTraffics/{email}", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"): return data.get("obj", {})
        except: pass
        return {}

xui = None

# ==================== Helpers ====================
def generate_vless_link(uuid_str, remark=""):
    return f"vless://{uuid_str}@{CONFIG['SERVER_ADDRESS']}:{CONFIG['PORT']}?path={CONFIG['WS_PATH']}&security=none&encryption=none&type=ws&host={CONFIG['WS_HOST']}#{remark.replace(' ', '_')}"

def generate_qr_bytes(data):
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

def format_bytes(size):
    for u in ['B','KB','MB','GB','TB']:
        if size < 1024: return f"{size:.2f} {u}"
        size /= 1024
    return f"{size:.2f} TB"

def is_url(s):
    try:
        r = urlparse(s)
        return all([r.scheme, r.netloc])
    except: return False

async def get_main_keyboard(is_admin=False):
    btns = [[KeyboardButton("🛒 Buy Plan")], [KeyboardButton("💰 TopUp")], [KeyboardButton("👤 Account")], [KeyboardButton("🏦 Banks")]]
    if is_admin: btns.append([KeyboardButton("⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(btns, resize_keyboard=True)

# ==================== Conversation States ====================
TO_AMOUNT, TO_SLIP = range(2)
BANK_NAME, BANK_NUMBER, BANK_HOLDER, BANK_QR, BANK_LOGO = range(5)
EDIT_BANK_FIELD, EDIT_BANK_VALUE = range(2)
ADMIN_NOTE = 10

# ==================== Handlers ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.create_user(user.id, user.username or user.full_name)
    if user.id == CONFIG["ADMIN_ID"]: await db.set_admin(user.id)
    await send_main_menu(update)

async def send_main_menu(update: Update):
    is_adm = await db.is_admin(update.effective_user.id)
    kb = await get_main_keyboard(is_adm)
    await update.message.reply_text("📋 Main Menu:", reply_markup=kb)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.create_user(user.id, user.username or user.full_name)
    if user.id == CONFIG["ADMIN_ID"]: await db.set_admin(user.id)
    text = update.message.text
    if text == "🛒 Buy Plan": await show_plans(update)
    elif text == "💰 TopUp": await start_topup(update)
    elif text == "👤 Account": await show_account(update, context)
    elif text == "🏦 Banks": await show_banks(update)
    elif text == "⚙️ Admin Panel" and await db.is_admin(user.id): await show_admin_panel(update)
    else: await send_main_menu(update)

async def show_plans(update: Update):
    plans = await db.get_plans()
    kb = [[InlineKeyboardButton(f"{p['name']} - {p['price']} THB", callback_data=f"buy_{p['id']}")] for p in plans]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
    await update.message.reply_text("📦 Select plan:", reply_markup=InlineKeyboardMarkup(kb))

async def start_topup(update: Update):
    kb = [[InlineKeyboardButton(f"{a} THB", callback_data=f"topup_amt_{a}")] for a in [40,70,100]]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
    await update.message.reply_text("💰 Select amount:", reply_markup=InlineKeyboardMarkup(kb))

async def topup_amount_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "menu_back": await q.message.delete(); await send_main_menu(q); return ConversationHandler.END
    amt = int(q.data.split("_")[2])
    context.user_data["topup_amount"] = amt
    banks = await db.get_banks()
    if not banks: await q.edit_message_text("No bank accounts."); return ConversationHandler.END
    await q.edit_message_text("🏦 Select bank:")
    for b in banks:
        txt = f"*{b['name']}*\n{b['number']}\n{b['holder']}"
        if b.get('logo_file_id'): await q.message.reply_photo(b['logo_file_id'], caption=txt, parse_mode="Markdown")
        elif b.get('qr_file_id'): await q.message.reply_photo(b['qr_file_id'], caption=txt, parse_mode="Markdown")
        else: await q.message.reply_text(txt, parse_mode="Markdown")
    await q.message.reply_text(f"💵 Amount: *{amt} THB*\n📸 Send slip.", parse_mode="Markdown")
    return TO_SLIP

async def receive_slip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    fid = update.message.photo[-1].file_id
    amt = context.user_data["topup_amount"]
    tid = await db.create_topup(uid, amt, fid)
    await update.message.reply_text("✅ Request sent.")
    await send_main_menu(update)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{tid}"), InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{tid}")]])
    await context.bot.send_photo(CONFIG["ADMIN_ID"], fid, caption=f"🔔 New top-up from [{update.effective_user.full_name}](tg://user?id={uid})\nAmount: {amt} THB", reply_markup=kb, parse_mode="Markdown")
    return ConversationHandler.END

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_main_menu(update)
    return ConversationHandler.END

async def show_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bal = await db.get_balance(uid)
    client = await db.get_client(uid)
    if not client:
        await update.message.reply_text(f"👤 Balance: {bal} THB\n📡 No active plan", parse_mode="Markdown")
        return
    traffic = xui.get_client_traffic(client["email"])
    down = traffic.get("downlink",0) or 0
    up = traffic.get("uplink",0) or 0
    await db.update_client_usage(uid, down, up)
    now = datetime.utcnow()
    exp = datetime.fromisoformat(client["expiry_at"]) if client["expiry_at"] else None
    if exp:
        left = (exp - now).days
        status = "🔴 Expired" if left < 0 else "🟢 Active"
        exp_str = exp.strftime("%d %b %Y") + (f" ({left} days left)" if left >=0 else "")
    else:
        status, exp_str = "🟢 Active", "Unlimited"
    used = down + up
    total = client["total_gb"]
    limit = total / (1024**3)
    used_gb = used / (1024**3)
    pct = (used_gb/limit*100) if limit>0 else 0
    info = (f"👤 *Account*\n💰 Balance: {bal} THB\n📦 Plan: {client['plan_name']}\n📅 Expiry: {exp_str}\n{status}\n\n"
            f"📊 Usage\n📥 {format_bytes(down)} 📤 {format_bytes(up)}\n💾 {format_bytes(used)} / {limit:.0f} GB ({pct:.1f}%)\n\n"
            f"🔑 UUID: `{client['uuid']}`\n📧 Email: `{client['email']}`")
    await update.message.reply_text(info, parse_mode="Markdown")

async def show_banks(update: Update):
    banks = await db.get_banks()
    if not banks: await update.message.reply_text("No banks."); return
    for b in banks:
        txt = f"🏦 *{b['name']}*\n💳 {b['number']}\n👤 {b['holder']}"
        if b.get('logo_file_id'): await update.message.reply_photo(b['logo_file_id'], caption=txt, parse_mode="Markdown")
        elif b.get('qr_file_id'): await update.message.reply_photo(b['qr_file_id'], caption=txt, parse_mode="Markdown")
        else: await update.message.reply_text(txt, parse_mode="Markdown")

async def show_admin_panel(update: Update):
    kb = [[InlineKeyboardButton("➕ Add Bank", callback_data="admin_addbank")],
          [InlineKeyboardButton("📋 Pending", callback_data="admin_pending")],
          [InlineKeyboardButton("🏦 Manage Banks", callback_data="admin_listbanks")],
          [InlineKeyboardButton("🔙 Back", callback_data="menu_back")]]
    await update.message.reply_text("⚙️ Admin Panel", reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    if d == "menu_back": await q.message.delete(); await send_main_menu(q)
    elif d.startswith("buy_"): await process_buy_plan(q, int(d.split("_")[1]))
    elif d == "admin_addbank": context.user_data["bank_edit_id"] = None; await q.edit_message_text("Enter bank name:"); return BANK_NAME
    elif d == "admin_pending": await show_pending(q)
    elif d == "admin_listbanks": await manage_banks(q)
    elif d.startswith("delbank_"): await db.delete_bank(int(d.split("_")[1])); await q.answer("Deleted"); await manage_banks(q)
    elif d.startswith("editbank_"): context.user_data["bank_edit_id"] = int(d.split("_")[1]); await q.edit_message_text("Select field:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Name", callback_data="editfield_name")],[InlineKeyboardButton("Number", callback_data="editfield_number")],[InlineKeyboardButton("Holder", callback_data="editfield_holder")],[InlineKeyboardButton("QR", callback_data="editfield_qr")],[InlineKeyboardButton("Logo", callback_data="editfield_logo")],[InlineKeyboardButton("🔙 Cancel", callback_data="admin_listbanks")]])); return EDIT_BANK_FIELD
    elif d.startswith("editfield_"):
        f = d.split("_")[1]; context.user_data["edit_field"] = f
        prompts = {"name":"New name:","number":"New number:","holder":"New holder:","qr":"Send QR photo/URL:","logo":"Send Logo photo/URL:"}
        await q.edit_message_text(prompts[f]); return EDIT_BANK_VALUE

async def process_buy_plan(q, pid):
    uid = q.from_user.id
    plan = next((p for p in await db.get_plans() if p["id"]==pid), None)
    if not plan: await q.edit_message_text("Plan not found"); return
    is_adm = await db.is_admin(uid)
    if not is_adm:
        if await db.get_balance(uid) < plan["price"]: await q.edit_message_text("❌ Insufficient balance"); return
        await db.update_balance(uid, -plan["price"])
    await q.edit_message_text("⏳ Creating...")
    try:
        u = str(uuid.uuid4())
        email = f"user_{uid}_{u[:8]}"
        exp = int((datetime.utcnow() + timedelta(days=plan["days"])).timestamp() * 1000)
        total = plan["data_gb"] * 1024**3
        xui.add_client(CONFIG["INBOUND_ID"], email, u, total, exp)
        await db.add_client(uid, u, email, pid, total, datetime.utcnow() + timedelta(days=plan["days"]))
        link = generate_vless_link(u, plan["name"])
        qr = generate_qr_bytes(link)
        cap = f"✅ *Purchased!*\n📦 {plan['name']}\n📅 Expires: {(datetime.utcnow() + timedelta(days=plan['days'])).strftime('%d %b %Y')}\n🔗 `{link}`"
        await q.message.delete()
        await q.message.reply_photo(qr, caption=cap, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Add client error: {e}")
        if not is_adm: await db.update_balance(uid, plan["price"])
        await q.edit_message_text(f"❌ Failed: {str(e)[:200]}")

async def admin_note_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    context.user_data["admin_action"] = {"action": d.split("_")[0], "topup_id": int(d.split("_")[1])}
    await q.edit_message_text("📝 Enter note (or /skip):")
    return ADMIN_NOTE

async def admin_note_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    act = context.user_data.get("admin_action")
    if not act: await update.message.reply_text("Expired"); return ConversationHandler.END
    note = update.message.text if update.message.text != "/skip" else None
    tid = act["topup_id"]
    topup = await db.get_topup(tid)
    if not topup or topup["status"] != "pending": await update.message.reply_text("Already processed"); return ConversationHandler.END
    if act["action"] == "approve":
        await db.update_topup_status(tid, "approved")
        await db.update_balance(topup["user_id"], topup["amount"])
        msg = f"✅ Top-up {topup['amount']} THB approved." + (f"\n📝 Note: {note}" if note else "")
    else:
        await db.update_topup_status(tid, "cancelled")
        msg = f"❌ Top-up {topup['amount']} THB cancelled." + (f"\n📝 Note: {note}" if note else "")
    await context.bot.send_message(topup["user_id"], msg)
    await update.message.reply_text("Done.")
    await send_main_menu(update)
    return ConversationHandler.END

async def show_pending(q):
    p = await db.get_pending_topups()
    if not p: await q.edit_message_text("No pending")
    else: await q.edit_message_text("📋 *Pending:*\n" + "\n".join([f"ID {r['id']} | User {r['user_id']} | {r['amount']} THB" for r in p]), parse_mode="Markdown")

async def manage_banks(q):
    banks = await db.get_banks()
    kb = []
    for b in banks:
        kb.append([InlineKeyboardButton(f"✏️ Edit {b['name']}", callback_data=f"editbank_{b['id']}"), InlineKeyboardButton("❌ Delete", callback_data=f"delbank_{b['id']}")])
    kb.append([InlineKeyboardButton("➕ Add Bank", callback_data="admin_addbank"), InlineKeyboardButton("🔙 Back", callback_data="menu_back")])
    await q.edit_message_text("🏦 Manage Banks", reply_markup=InlineKeyboardMarkup(kb))

# Bank addition
async def bank_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_name"] = update.message.text
    await update.message.reply_text("Account number:"); return BANK_NUMBER
async def bank_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_number"] = update.message.text
    await update.message.reply_text("Holder name:"); return BANK_HOLDER
async def bank_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_holder"] = update.message.text
    await update.message.reply_text("QR (photo/URL) or /skip:"); return BANK_QR
async def bank_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo: context.user_data["bank_qr"] = update.message.photo[-1].file_id
    elif update.message.text and update.message.text != "/skip": context.user_data["bank_qr"] = update.message.text if is_url(update.message.text) else None
    else: context.user_data["bank_qr"] = None
    await update.message.reply_text("Logo (photo/URL) or /skip:"); return BANK_LOGO
async def bank_logo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo: context.user_data["bank_logo"] = update.message.photo[-1].file_id
    elif update.message.text and update.message.text != "/skip": context.user_data["bank_logo"] = update.message.text if is_url(update.message.text) else None
    else: context.user_data["bank_logo"] = None
    eid = context.user_data.get("bank_edit_id")
    if eid:
        await db.update_bank(eid, context.user_data["bank_name"], context.user_data["bank_number"], context.user_data["bank_holder"], context.user_data.get("bank_qr"), context.user_data.get("bank_logo"))
        await update.message.reply_text("✅ Updated.")
    else:
        await db.add_bank(context.user_data["bank_name"], context.user_data["bank_number"], context.user_data["bank_holder"], context.user_data.get("bank_qr"), context.user_data.get("bank_logo"))
        await update.message.reply_text("✅ Added.")
    await send_main_menu(update)
    return ConversationHandler.END

async def edit_field_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bid = context.user_data.get("bank_edit_id")
    field = context.user_data.get("edit_field")
    if not bid or not field: await update.message.reply_text("Error"); return ConversationHandler.END
    bank = await db.get_bank(bid)
    val = update.message.text
    if field in ["qr","logo"]:
        if update.message.photo: val = update.message.photo[-1].file_id
        elif val != "/skip" and not is_url(val): await update.message.reply_text("Invalid URL"); return EDIT_BANK_VALUE
        elif val == "/skip": val = None
    elif val == "/skip": await update.message.reply_text("Cancelled"); return ConversationHandler.END
    updates = {"name":bank["name"], "number":bank["number"], "holder":bank["holder"], "qr_file_id":bank["qr_file_id"], "logo_file_id":bank["logo_file_id"]}
    if field == "name": updates["name"] = val
    elif field == "number": updates["number"] = val
    elif field == "holder": updates["holder"] = val
    elif field == "qr": updates["qr_file_id"] = val
    elif field == "logo": updates["logo_file_id"] = val
    await db.update_bank(bid, updates["name"], updates["number"], updates["holder"], updates["qr_file_id"], updates["logo_file_id"])
    await update.message.reply_text("✅ Updated.")
    await send_main_menu(update)
    return ConversationHandler.END

# ==================== Service Install ====================
def install_service():
    if os.geteuid() != 0: print("Need root"); return
    choice = input("\nInstall as systemd service? (y/n): ").strip().lower()
    if choice != 'y': return
    svc = f"""[Unit]
Description=Telegram VLESS Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={os.getcwd()}
ExecStart={sys.executable} {os.path.abspath(__file__)}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    with open("/etc/systemd/system/telegram-bot.service", "w") as f: f.write(svc)
    subprocess.run(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "enable", "telegram-bot.service"])
    subprocess.run(["systemctl", "start", "telegram-bot.service"])
    print("✅ Service installed. Bot running in background.")
    os._exit(0)

# ==================== Main ====================
def main():
    global xui
    try:
        xui = XUIClient()
        logger.info(f"Connected to X-UI. API: {xui.base_url}")
    except Exception as e:
        logger.error(f"Login failed: {e}")
        sys.exit(1)

    app = Application.builder().token(CONFIG["BOT_TOKEN"]).build()

    # Conversations
    admin_note_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_note_start, pattern="^(approve_|cancel_)")],
        states={ADMIN_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_note_input), CommandHandler("skip", admin_note_input)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)], per_message=False
    )
    topup_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(topup_amount_selected, pattern="^topup_amt_")],
        states={TO_SLIP: [MessageHandler(filters.PHOTO, receive_slip)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)], per_message=False
    )
    bank_add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u,c: BANK_NAME, pattern="^admin_addbank$")],
        states={
            BANK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_name)],
            BANK_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_number)],
            BANK_HOLDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_holder)],
            BANK_QR: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), bank_qr), CommandHandler("skip", bank_qr)],
            BANK_LOGO: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), bank_logo), CommandHandler("skip", bank_logo)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)], per_message=False
    )
    bank_edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u,c: EDIT_BANK_FIELD, pattern="^editbank_"), CallbackQueryHandler(lambda u,c: EDIT_BANK_FIELD, pattern="^editfield_")],
        states={
            EDIT_BANK_FIELD: [CallbackQueryHandler(lambda u,c: EDIT_BANK_VALUE, pattern="^editfield_")],
            EDIT_BANK_VALUE: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), edit_field_value), CommandHandler("skip", edit_field_value)],
        },
        fallbacks=[CallbackQueryHandler(manage_banks, pattern="^admin_listbanks$")], per_message=False
    )

    app.add_handler(admin_note_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(topup_conv)
    app.add_handler(bank_add_conv)
    app.add_handler(bank_edit_conv)
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is starting...")
    # Run polling and then offer service install
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(app.initialize())
        loop.run_until_complete(app.start())
        loop.create_task(app.updater.start_polling())
        install_service()
        loop.run_until_complete(app.updater.wait_until_stopped())
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(app.stop())
        loop.close()

if __name__ == "__main__":
    main()
