import json
import time
import uuid
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import requests
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

CONFIG_FILE = "config.json"
DB_FILE = "bot.sqlite3"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# =========================================================
# CONFIG FIRST RUN
# =========================================================

def load_or_create_config() -> dict:
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    print("\n=== First Run Setup ===")
    bot_token = input("Enter BOT TOKEN: ").strip()
    admin_ids_raw = input("Enter ADMIN Telegram ID(s), comma separated: ").strip()
    support_text = input("Support username or text [@support]: ").strip() or "@support"
    bot_name = input("Bot name [V2RAY X-UI PANEL]: ").strip() or "V2RAY X-UI PANEL"
    currency = input("Currency [THB]: ").strip() or "THB"
    tz_offset = input("Timezone offset [7]: ").strip() or "7"

    admin_ids = [int(x.strip()) for x in admin_ids_raw.split(",") if x.strip().isdigit()]

    cfg = {
        "BOT_TOKEN": bot_token,
        "ADMIN_IDS": admin_ids,
        "SUPPORT_TEXT": support_text,
        "BOT_NAME": bot_name,
        "DEFAULT_CURRENCY": currency,
        "TIMEZONE_OFFSET": int(tz_offset),
    }

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    print("Saved config.json")
    return cfg


CFG = load_or_create_config()
BOT_TOKEN = CFG["BOT_TOKEN"]
ADMIN_IDS = set(CFG["ADMIN_IDS"])
SUPPORT_TEXT = CFG["SUPPORT_TEXT"]
BOT_NAME = CFG["BOT_NAME"]
DEFAULT_CURRENCY = CFG["DEFAULT_CURRENCY"]
TIMEZONE_OFFSET = CFG["TIMEZONE_OFFSET"]


# =========================================================
# HELPERS
# =========================================================

def now_ts() -> int:
    return int(time.time())

def format_dt(ts: Optional[int]) -> str:
    if not ts:
        return "-"
    tz = timezone(timedelta(hours=TIMEZONE_OFFSET))
    return datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d %H:%M:%S")

def gb_to_bytes(gb: int) -> int:
    return gb * 1024 * 1024 * 1024

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def uname(user) -> str:
    if user.username:
        return f"@{user.username}"
    return " ".join(x for x in [user.first_name, user.last_name] if x).strip() or str(user.id)

def kb(rows):
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# =========================================================
# DB
# =========================================================

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        balance REAL DEFAULT 0,
        panel_id INTEGER,
        client_uuid TEXT,
        client_email TEXT,
        inbound_id INTEGER,
        expiry_ts INTEGER,
        traffic_bytes INTEGER DEFAULT 0,
        created_at INTEGER,
        updated_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        days INTEGER NOT NULL,
        price REAL NOT NULL,
        traffic_gb INTEGER NOT NULL,
        is_active INTEGER DEFAULT 1,
        created_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS topup_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount REAL NOT NULL,
        is_active INTEGER DEFAULT 1,
        created_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS banks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bank_name TEXT NOT NULL,
        account_name TEXT NOT NULL,
        account_number TEXT NOT NULL,
        note TEXT,
        qr_file_id TEXT,
        is_active INTEGER DEFAULT 1,
        created_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS panels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        panel_url TEXT NOT NULL,
        username TEXT NOT NULL,
        password TEXT NOT NULL,
        inbound_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        priority INTEGER DEFAULT 100,
        created_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS topups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        bank_id INTEGER NOT NULL,
        slip_file_id TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        admin_id INTEGER,
        created_at INTEGER,
        updated_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER NOT NULL,
        plan_id INTEGER NOT NULL,
        plan_name_snapshot TEXT NOT NULL,
        price_snapshot REAL NOT NULL,
        traffic_gb_snapshot INTEGER NOT NULL,
        days_snapshot INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'paid',
        panel_id INTEGER,
        created_at INTEGER,
        updated_at INTEGER
    )
    """)

    conn.commit()

    cur.execute("SELECT COUNT(*) c FROM plans")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO plans (name, days, price, traffic_gb, is_active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            ("15 DAYS", 15, 20, 100, now_ts()),
        )
        cur.execute(
            "INSERT INTO plans (name, days, price, traffic_gb, is_active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            ("30 DAYS", 30, 40, 200, now_ts()),
        )

    cur.execute("SELECT COUNT(*) c FROM topup_options")
    if cur.fetchone()["c"] == 0:
        for amount in [20, 40, 100, 200]:
            cur.execute(
                "INSERT INTO topup_options (amount, is_active, created_at) VALUES (?, 1, ?)",
                (amount, now_ts()),
            )

    conn.commit()
    conn.close()


def ensure_user(tg_user) -> sqlite3.Row:
    conn = get_conn()
    cur = conn.cursor()
    ts = now_ts()
    full_name = " ".join(x for x in [tg_user.first_name, tg_user.last_name] if x).strip()
    cur.execute("SELECT * FROM users WHERE telegram_id=?", (tg_user.id,))
    row = cur.fetchone()
    if row:
        cur.execute("""
            UPDATE users
            SET username=?, full_name=?, updated_at=?
            WHERE telegram_id=?
        """, (tg_user.username, full_name, ts, tg_user.id))
    else:
        cur.execute("""
            INSERT INTO users (telegram_id, username, full_name, balance, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?)
        """, (tg_user.id, tg_user.username, full_name, ts, ts))
    conn.commit()
    cur.execute("SELECT * FROM users WHERE telegram_id=?", (tg_user.id,))
    out = cur.fetchone()
    conn.close()
    return out

def get_user(telegram_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
    row = cur.fetchone()
    conn.close()
    return row

def update_balance(telegram_id: int, amount: float):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance=balance+?, updated_at=? WHERE telegram_id=?",
                (amount, now_ts(), telegram_id))
    conn.commit()
    conn.close()

def deduct_balance(telegram_id: int, amount: float) -> bool:
    user = get_user(telegram_id)
    if not user:
        return False
    if float(user["balance"]) < amount:
        return False
    update_balance(telegram_id, -amount)
    return True

def active_plans():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM plans WHERE is_active=1 ORDER BY days ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def all_plans():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM plans ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_plan(plan_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM plans WHERE id=?", (plan_id,))
    row = cur.fetchone()
    conn.close()
    return row

def create_plan(name: str, days: int, price: float, traffic_gb: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO plans (name, days, price, traffic_gb, is_active, created_at)
        VALUES (?, ?, ?, ?, 1, ?)
    """, (name, days, price, traffic_gb, now_ts()))
    conn.commit()
    conn.close()

def toggle_plan(plan_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE plans SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?",
                (plan_id,))
    conn.commit()
    conn.close()

def delete_plan(plan_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM plans WHERE id=?", (plan_id,))
    conn.commit()
    conn.close()

def active_topup_options():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM topup_options WHERE is_active=1 ORDER BY amount ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def all_topup_options():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM topup_options ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def create_topup_option(amount: float):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO topup_options (amount, is_active, created_at) VALUES (?, 1, ?)",
                (amount, now_ts()))
    conn.commit()
    conn.close()

def toggle_topup_option(option_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE topup_options SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?",
                (option_id,))
    conn.commit()
    conn.close()

def delete_topup_option(option_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM topup_options WHERE id=?", (option_id,))
    conn.commit()
    conn.close()

def active_banks():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM banks WHERE is_active=1 ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def all_banks():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM banks ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_bank(bank_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM banks WHERE id=?", (bank_id,))
    row = cur.fetchone()
    conn.close()
    return row

def create_bank(bank_name: str, account_name: str, account_number: str, note: str, qr_file_id: Optional[str]):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO banks (bank_name, account_name, account_number, note, qr_file_id, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
    """, (bank_name, account_name, account_number, note, qr_file_id, now_ts()))
    conn.commit()
    conn.close()

def toggle_bank(bank_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE banks SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?",
                (bank_id,))
    conn.commit()
    conn.close()

def delete_bank(bank_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM banks WHERE id=?", (bank_id,))
    conn.commit()
    conn.close()

def all_panels():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM panels ORDER BY priority ASC, id ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_panel(panel_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM panels WHERE id=?", (panel_id,))
    row = cur.fetchone()
    conn.close()
    return row

def choose_active_panel():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM panels WHERE status='active' ORDER BY priority ASC, id ASC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row

def create_panel(name: str, panel_url: str, username: str, password: str, inbound_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO panels (name, panel_url, username, password, inbound_id, status, priority, created_at)
        VALUES (?, ?, ?, ?, ?, 'active', 100, ?)
    """, (name, panel_url, username, password, inbound_id, now_ts()))
    conn.commit()
    conn.close()

def set_panel_status(panel_id: int, status: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE panels SET status=? WHERE id=?", (status, panel_id))
    conn.commit()
    conn.close()

def delete_panel(panel_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM panels WHERE id=?", (panel_id,))
    conn.commit()
    conn.close()

def create_topup(telegram_id: int, amount: float, bank_id: int, slip_file_id: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO topups (telegram_id, amount, bank_id, slip_file_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'pending', ?, ?)
    """, (telegram_id, amount, bank_id, slip_file_id, now_ts(), now_ts()))
    topup_id = cur.lastrowid
    conn.commit()
    conn.close()
    return topup_id

def pending_topups():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM topups WHERE status='pending' ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return rows

def approve_topup(topup_id: int, admin_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM topups WHERE id=?", (topup_id,))
    row = cur.fetchone()
    if not row or row["status"] != "pending":
        conn.close()
        return None
    cur.execute("UPDATE users SET balance=balance+?, updated_at=? WHERE telegram_id=?",
                (row["amount"], now_ts(), row["telegram_id"]))
    cur.execute("UPDATE topups SET status='approved', admin_id=?, updated_at=? WHERE id=?",
                (admin_id, now_ts(), topup_id))
    conn.commit()
    cur.execute("SELECT * FROM topups WHERE id=?", (topup_id,))
    out = cur.fetchone()
    conn.close()
    return out

def cancel_topup(topup_id: int, admin_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM topups WHERE id=?", (topup_id,))
    row = cur.fetchone()
    if not row or row["status"] != "pending":
        conn.close()
        return None
    cur.execute("UPDATE topups SET status='cancelled', admin_id=?, updated_at=? WHERE id=?",
                (admin_id, now_ts(), topup_id))
    conn.commit()
    cur.execute("SELECT * FROM topups WHERE id=?", (topup_id,))
    out = cur.fetchone()
    conn.close()
    return out

def create_order(telegram_id: int, plan, panel_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders (
            telegram_id, plan_id, plan_name_snapshot, price_snapshot,
            traffic_gb_snapshot, days_snapshot, status, panel_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'paid', ?, ?, ?)
    """, (
        telegram_id, plan["id"], plan["name"], plan["price"],
        plan["traffic_gb"], plan["days"], panel_id, now_ts(), now_ts()
    ))
    order_id = cur.lastrowid
    conn.commit()
    conn.close()
    return order_id

def save_user_client(telegram_id: int, panel_id: int, inbound_id: int, client_uuid: str,
                     client_email: str, expiry_ts: int, traffic_bytes: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE users
        SET panel_id=?, inbound_id=?, client_uuid=?, client_email=?, expiry_ts=?, traffic_bytes=?, updated_at=?
        WHERE telegram_id=?
    """, (panel_id, inbound_id, client_uuid, client_email, expiry_ts, traffic_bytes, now_ts(), telegram_id))
    conn.commit()
    conn.close()


# =========================================================
# XUI CLIENT
# =========================================================

class XUIClient:
    def __init__(self, panel_url: str, username: str, password: str):
        self.panel_url = panel_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.verify = False

    def login(self) -> bool:
        endpoints = ["/login", "/panel/login", "/xui/login"]
        payload = {"username": self.username, "password": self.password}
        for ep in endpoints:
            try:
                r = self.session.post(self.panel_url + ep, data=payload, timeout=15)
                if r.status_code in (200, 302):
                    return True
            except Exception as e:
                logger.warning("login failed %s: %s", ep, e)
        return False

    def create_client(self, inbound_id: int, email: str, days: int, traffic_gb: int) -> Dict[str, Any]:
        client_uuid = str(uuid.uuid4())
        expiry_ts = now_ts() + days * 86400
        total_bytes = gb_to_bytes(traffic_gb)

        settings = {
            "clients": [{
                "id": client_uuid,
                "email": email,
                "enable": True,
                "expiryTime": expiry_ts * 1000,
                "totalGB": total_bytes,
                "limitIp": 0,
                "subId": uuid.uuid4().hex[:16],
                "reset": 0,
            }]
        }

        endpoints = ["/panel/inbound/addClient", "/xui/inbound/addClient"]
        for ep in endpoints:
            try:
                r = self.session.post(
                    self.panel_url + ep,
                    data={"id": inbound_id, "settings": json.dumps(settings)},
                    timeout=15,
                )
                if r.status_code == 200:
                    return {
                        "ok": True,
                        "uuid": client_uuid,
                        "expiry_ts": expiry_ts,
                        "traffic_bytes": total_bytes,
                        "sub_url": f"{self.panel_url}/sub/{client_uuid}",
                    }
            except Exception as e:
                logger.warning("create_client failed %s: %s", ep, e)
        return {"ok": False, "message": "create_client failed"}

    def renew_client(self, inbound_id: int, client_uuid: str, email: str,
                     new_expiry_ts: int, new_total_bytes: int) -> Dict[str, Any]:
        settings = {
            "clients": [{
                "id": client_uuid,
                "email": email,
                "enable": True,
                "expiryTime": new_expiry_ts * 1000,
                "totalGB": new_total_bytes,
                "limitIp": 0,
            }]
        }
        endpoints = [
            f"/panel/inbound/updateClient/{client_uuid}",
            f"/xui/inbound/updateClient/{client_uuid}",
        ]
        for ep in endpoints:
            try:
                r = self.session.post(
                    self.panel_url + ep,
                    data={"id": inbound_id, "settings": json.dumps(settings)},
                    timeout=15,
                )
                if r.status_code == 200:
                    return {
                        "ok": True,
                        "uuid": client_uuid,
                        "expiry_ts": new_expiry_ts,
                        "traffic_bytes": new_total_bytes,
                        "sub_url": f"{self.panel_url}/sub/{client_uuid}",
                    }
            except Exception as e:
                logger.warning("renew_client failed %s: %s", ep, e)
        return {"ok": False, "message": "renew_client failed"}


# =========================================================
# KEYBOARDS
# =========================================================

def user_menu():
    return kb([
        [KeyboardButton("🛒 Buy Plan"), KeyboardButton("💰 TopUp")],
        [KeyboardButton("👤 My Account"), KeyboardButton("📦 My Plan")],
        [KeyboardButton("☎️ Support")]
    ])

def admin_menu():
    return kb([
        [KeyboardButton("📥 TopUp Requests"), KeyboardButton("🏦 Manage Banks")],
        [KeyboardButton("📦 Manage Plans"), KeyboardButton("🖥 Manage Panels")],
        [KeyboardButton("💵 TopUp Amounts"), KeyboardButton("📊 Statistics")],
        [KeyboardButton("↩️ User Menu")]
    ])

def banks_menu():
    return kb([
        [KeyboardButton("➕ Add Bank"), KeyboardButton("📋 List Banks")],
        [KeyboardButton("🔙 Back")]
    ])

def plans_menu():
    return kb([
        [KeyboardButton("➕ Add Plan"), KeyboardButton("📋 List Plans")],
        [KeyboardButton("🔙 Back")]
    ])

def panels_menu():
    return kb([
        [KeyboardButton("➕ Add Panel"), KeyboardButton("📋 List Panels")],
        [KeyboardButton("🔙 Back")]
    ])

def topup_amount_menu():
    return kb([
        [KeyboardButton("➕ Add TopUp Amount"), KeyboardButton("📋 List TopUp Amounts")],
        [KeyboardButton("🔙 Back")]
    ])

def back_menu():
    return kb([[KeyboardButton("🔙 Back")]])

def skip_menu():
    return kb([[KeyboardButton("Skip")], [KeyboardButton("🔙 Back")]])


# =========================================================
# STATE
# =========================================================

def clear_state(context):
    keys = list(context.user_data.keys())
    for k in keys:
        if k.startswith("flow_") or k in {
            "awaiting_slip", "pending_topup_amount", "pending_topup_bank_id",
            "bank_name", "account_name", "account_number", "bank_note",
            "plan_name", "plan_days", "plan_price",
            "panel_name", "panel_url", "panel_username", "panel_password"
        }:
            context.user_data.pop(k, None)


# =========================================================
# NOTIFY
# =========================================================

async def notify_admins(app: Application, text: str, reply_markup=None, photo_file_id=None):
    for admin_id in ADMIN_IDS:
        try:
            if photo_file_id:
                await app.bot.send_photo(admin_id, photo=photo_file_id, caption=text, reply_markup=reply_markup)
            else:
                await app.bot.send_message(admin_id, text=text, reply_markup=reply_markup)
        except Exception as e:
            logger.warning("notify admin failed %s: %s", admin_id, e)


# =========================================================
# SCREENS
# =========================================================

async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        await update.effective_message.reply_text(f"မင်္ဂလာပါ\n{BOT_NAME}", reply_markup=admin_menu())
    else:
        await update.effective_message.reply_text(f"မင်္ဂလာပါ\n{BOT_NAME}", reply_markup=user_menu())

async def show_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update.effective_user)
    balance_text = "Unlimited" if is_admin(user["telegram_id"]) else f"{float(user['balance']):.2f} {DEFAULT_CURRENCY}"
    text = (
        f"👤 Account\n"
        f"ID: {user['telegram_id']}\n"
        f"Username: @{user['username'] if user['username'] else '-'}\n"
        f"Balance: {balance_text}\n"
        f"Panel ID: {user['panel_id'] or '-'}\n"
        f"Expiry: {format_dt(user['expiry_ts'])}"
    )
    await update.effective_message.reply_text(text, reply_markup=user_menu())

async def show_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update.effective_user)
    if not user["client_uuid"]:
        await update.effective_message.reply_text("Plan မရှိသေးပါ။", reply_markup=user_menu())
        return
    text = (
        f"📦 My Plan\n"
        f"UUID: {user['client_uuid']}\n"
        f"Expiry: {format_dt(user['expiry_ts'])}\n"
        f"Traffic: {round((user['traffic_bytes'] or 0)/(1024**3), 2)} GB\n"
        f"Panel ID: {user['panel_id']}"
    )
    await update.effective_message.reply_text(text, reply_markup=user_menu())

async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(f"Support: {SUPPORT_TEXT}", reply_markup=user_menu())

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) c FROM users")
    users_count = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM topups WHERE status='pending'")
    pending_topups_count = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM orders")
    orders_count = cur.fetchone()["c"]
    conn.close()

    await update.effective_message.reply_text(
        f"📊 Statistics\nUsers: {users_count}\nPending TopUps: {pending_topups_count}\nOrders: {orders_count}",
        reply_markup=admin_menu()
    )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    clear_state(context)
    await show_home(update, context)


# =========================================================
# BUY PLAN
# =========================================================

async def buy_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plans = active_plans()
    if not plans:
        await update.effective_message.reply_text("Active plan မရှိသေးပါ။", reply_markup=user_menu())
        return

    buttons = []
    for p in plans:
        buttons.append([InlineKeyboardButton(
            f"{p['name']} - {p['price']} {DEFAULT_CURRENCY} - {p['traffic_gb']} GB",
            callback_data=f"buy:{p['id']}"
        )])
    await update.effective_message.reply_text("Plan ရွေးပါ", reply_markup=InlineKeyboardMarkup(buttons))

async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user = ensure_user(q.from_user)
    plan_id = int(q.data.split(":")[1])
    plan = get_plan(plan_id)
    if not plan:
        await q.edit_message_text("Plan not found")
        return

    admin_free = is_admin(user["telegram_id"])

    existing_panel_id = user["panel_id"]
    if existing_panel_id:
        panel = get_panel(existing_panel_id)
        if not panel:
            await q.edit_message_text("Panel info not found")
            return
        if panel["status"] == "disabled":
            await q.edit_message_text("သင့် panel disabled ဖြစ်နေပါတယ်")
            return
    else:
        panel = choose_active_panel()
        if not panel:
            await q.edit_message_text("Active panel မရှိသေးပါ")
            return

    if not admin_free:
        if not deduct_balance(user["telegram_id"], float(plan["price"])):
            await q.edit_message_text("Balance မလုံလောက်ပါ")
            return

    xui = XUIClient(panel["panel_url"], panel["username"], panel["password"])
    if not xui.login():
        if not admin_free:
            update_balance(user["telegram_id"], float(plan["price"]))
        await q.edit_message_text("Panel login failed")
        return

    email = user["client_email"] or f"tg_{user['telegram_id']}"

    if user["client_uuid"]:
        current_expiry = int(user["expiry_ts"] or now_ts())
        base_expiry = current_expiry if current_expiry > now_ts() else now_ts()
        new_expiry = base_expiry + int(plan["days"]) * 86400
        new_bytes = int(user["traffic_bytes"] or 0) + gb_to_bytes(int(plan["traffic_gb"]))
        result = xui.renew_client(
            inbound_id=panel["inbound_id"],
            client_uuid=user["client_uuid"],
            email=email,
            new_expiry_ts=new_expiry,
            new_total_bytes=new_bytes
        )
        if not result["ok"]:
            if not admin_free:
                update_balance(user["telegram_id"], float(plan["price"]))
            await q.edit_message_text(f"Renew failed\n{result['message']}")
            return

        save_user_client(user["telegram_id"], panel["id"], panel["inbound_id"], user["client_uuid"], email, new_expiry, new_bytes)
        order_id = create_order(user["telegram_id"], plan, panel["id"])
        await q.edit_message_text(
            f"✅ Renew Success\n"
            f"Order ID: {order_id}\n"
            f"Plan: {plan['name']}\n"
            f"Expiry: {format_dt(new_expiry)}\n"
            f"Traffic: {round(new_bytes/(1024**3), 2)} GB\n"
            f"UUID: {user['client_uuid']}\n"
            f"Sub URL: {result.get('sub_url', '-')}"
        )
    else:
        result = xui.create_client(panel["inbound_id"], email, int(plan["days"]), int(plan["traffic_gb"]))
        if not result["ok"]:
            if not admin_free:
                update_balance(user["telegram_id"], float(plan["price"]))
            await q.edit_message_text(f"Create client failed\n{result['message']}")
            return

        save_user_client(user["telegram_id"], panel["id"], panel["inbound_id"], result["uuid"], email, result["expiry_ts"], result["traffic_bytes"])
        order_id = create_order(user["telegram_id"], plan, panel["id"])
        await q.edit_message_text(
            f"✅ Client Created\n"
            f"Order ID: {order_id}\n"
            f"Plan: {plan['name']}\n"
            f"Panel: {panel['name']}\n"
            f"Expiry: {format_dt(result['expiry_ts'])}\n"
            f"Traffic: {plan['traffic_gb']} GB\n"
            f"UUID: {result['uuid']}\n"
            f"Sub URL: {result.get('sub_url', '-')}"
        )


# =========================================================
# TOPUP
# =========================================================

async def topup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = active_topup_options()
    if not rows:
        await update.effective_message.reply_text("TopUp amount မရှိသေးပါ", reply_markup=user_menu())
        return

    buttons = []
    for r in rows:
        buttons.append([InlineKeyboardButton(
            f"TopUp {r['amount']} {DEFAULT_CURRENCY}",
            callback_data=f"topup_amount:{r['id']}"
        )])
    await update.effective_message.reply_text("TopUp amount ရွေးပါ", reply_markup=InlineKeyboardMarkup(buttons))

async def topup_amount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    option_id = int(q.data.split(":")[1])
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM topup_options WHERE id=? AND is_active=1", (option_id,))
    option = cur.fetchone()
    conn.close()

    if not option:
        await q.edit_message_text("Amount not found")
        return

    context.user_data["pending_topup_amount"] = float(option["amount"])

    banks = active_banks()
    if not banks:
        await q.edit_message_text("Active bank မရှိသေးပါ")
        return

    buttons = []
    for b in banks:
        buttons.append([InlineKeyboardButton(
            f"{b['bank_name']} - {b['account_number']}",
            callback_data=f"topup_bank:{b['id']}"
        )])
    await q.edit_message_text("Bank ရွေးပါ", reply_markup=InlineKeyboardMarkup(buttons))

async def topup_bank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    bank_id = int(q.data.split(":")[1])
    bank = get_bank(bank_id)
    amount = context.user_data.get("pending_topup_amount")

    if not bank:
        await q.edit_message_text("Bank not found")
        return

    context.user_data["pending_topup_bank_id"] = bank_id
    context.user_data["awaiting_slip"] = True

    text = (
        f"💰 TopUp Request\n"
        f"Amount: {amount} {DEFAULT_CURRENCY}\n"
        f"Bank: {bank['bank_name']}\n"
        f"Account Name: {bank['account_name']}\n"
        f"Account Number: {bank['account_number']}\n"
        f"Note: {bank['note'] or '-'}\n\n"
        f"ငွေလွှဲပြီး slip / screenshot ကို ပို့ပါ"
    )

    if bank["qr_file_id"]:
        await q.message.reply_photo(bank["qr_file_id"], caption=text, reply_markup=back_menu())
    else:
        await q.message.reply_text(text, reply_markup=back_menu())

async def user_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_slip"):
        return

    user = ensure_user(update.effective_user)
    amount = context.user_data.get("pending_topup_amount")
    bank_id = context.user_data.get("pending_topup_bank_id")
    if not amount or not bank_id:
        clear_state(context)
        await update.effective_message.reply_text("TopUp session expired", reply_markup=user_menu())
        return

    file_id = update.message.photo[-1].file_id
    topup_id = create_topup(user["telegram_id"], amount, bank_id, file_id)
    bank = get_bank(bank_id)

    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_topup:{topup_id}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_topup:{topup_id}")
    ]])

    admin_text = (
        f"📥 New TopUp Request\n\n"
        f"TopUp ID: {topup_id}\n"
        f"User: {uname(update.effective_user)}\n"
        f"Telegram ID: {user['telegram_id']}\n"
        f"Amount: {amount} {DEFAULT_CURRENCY}\n"
        f"Bank: {bank['bank_name'] if bank else '-'}\n"
        f"Status: pending"
    )
    await notify_admins(context.application, admin_text, reply_markup=buttons, photo_file_id=file_id)

    clear_state(context)
    await update.effective_message.reply_text("TopUp request ပို့ပြီးပါပြီ။ Admin approval စောင့်ပါ။", reply_markup=user_menu())

async def topup_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        return

    action, topup_id = q.data.split(":")
    topup_id = int(topup_id)

    if action == "approve_topup":
        row = approve_topup(topup_id, q.from_user.id)
        if not row:
            txt = "Already processed / invalid"
        else:
            user = get_user(row["telegram_id"])
            txt = (
                f"✅ TopUp Approved\n"
                f"TopUp ID: {row['id']}\n"
                f"Amount: {row['amount']} {DEFAULT_CURRENCY}\n"
                f"New Balance: {float(user['balance']):.2f} {DEFAULT_CURRENCY}"
            )
            try:
                await context.bot.send_message(row["telegram_id"], txt, reply_markup=user_menu())
            except Exception as e:
                logger.warning("notify user failed: %s", e)
    else:
        row = cancel_topup(topup_id, q.from_user.id)
        txt = "Already processed / invalid" if not row else f"❌ TopUp Cancelled\nTopUp ID: {row['id']}\nAmount: {row['amount']} {DEFAULT_CURRENCY}"
        if row:
            try:
                await context.bot.send_message(row["telegram_id"], txt, reply_markup=user_menu())
            except Exception as e:
                logger.warning("notify user failed: %s", e)

    if q.message.photo:
        await q.edit_message_caption(txt)
    else:
        await q.edit_message_text(txt)


# =========================================================
# ADMIN MENUS
# =========================================================

async def show_banks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_state(context)
    await update.effective_message.reply_text("🏦 Manage Banks", reply_markup=banks_menu())

async def show_plans_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_state(context)
    await update.effective_message.reply_text("📦 Manage Plans", reply_markup=plans_menu())

async def show_panels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_state(context)
    await update.effective_message.reply_text("🖥 Manage Panels", reply_markup=panels_menu())

async def show_topup_amount_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_state(context)
    await update.effective_message.reply_text("💵 TopUp Amounts", reply_markup=topup_amount_menu())


# =========================================================
# ADD FLOWS
# =========================================================

async def start_add_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_state(context)
    context.user_data["flow_add_bank"] = "bank_name"
    await update.effective_message.reply_text("Bank name ထည့်ပါ", reply_markup=back_menu())

async def start_add_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_state(context)
    context.user_data["flow_add_plan"] = "plan_name"
    await update.effective_message.reply_text("Plan name ထည့်ပါ", reply_markup=back_menu())

async def start_add_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_state(context)
    context.user_data["flow_add_panel"] = "panel_name"
    await update.effective_message.reply_text("Panel name ထည့်ပါ", reply_markup=back_menu())

async def start_add_topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_state(context)
    context.user_data["flow_add_topup_amount"] = True
    await update.effective_message.reply_text("TopUp amount ထည့်ပါ", reply_markup=back_menu())


# =========================================================
# LIST SCREENS
# =========================================================

async def list_banks_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = all_banks()
    if not rows:
        await update.effective_message.reply_text("Bank မရှိသေးပါ", reply_markup=banks_menu())
        return
    for b in rows:
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Toggle", callback_data=f"bank_toggle:{b['id']}"),
                InlineKeyboardButton("Delete", callback_data=f"bank_delete:{b['id']}")
            ]
        ])
        text = f"ID={b['id']} | {b['bank_name']}\n{b['account_name']}\n{b['account_number']}\nActive={b['is_active']}"
        if b["qr_file_id"]:
            await update.effective_message.reply_photo(b["qr_file_id"], caption=text, reply_markup=buttons)
        else:
            await update.effective_message.reply_text(text, reply_markup=buttons)

async def list_plans_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = all_plans()
    if not rows:
        await update.effective_message.reply_text("Plan မရှိသေးပါ", reply_markup=plans_menu())
        return
    for p in rows:
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Toggle", callback_data=f"plan_toggle:{p['id']}"),
                InlineKeyboardButton("Delete", callback_data=f"plan_delete:{p['id']}")
            ]
        ])
        text = f"ID={p['id']} | {p['name']}\nDays={p['days']} | Price={p['price']} | Traffic={p['traffic_gb']} GB | Active={p['is_active']}"
        await update.effective_message.reply_text(text, reply_markup=buttons)

async def list_panels_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = all_panels()
    if not rows:
        await update.effective_message.reply_text("Panel မရှိသေးပါ", reply_markup=panels_menu())
        return
    for p in rows:
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Active", callback_data=f"panel_status:{p['id']}:active"),
                InlineKeyboardButton("Full", callback_data=f"panel_status:{p['id']}:full")
            ],
            [
                InlineKeyboardButton("Disabled", callback_data=f"panel_status:{p['id']}:disabled"),
                InlineKeyboardButton("Delete", callback_data=f"panel_delete:{p['id']}")
            ]
        ])
        text = (
            f"ID={p['id']} | {p['name']}\n"
            f"URL={p['panel_url']}\n"
            f"User={p['username']}\n"
            f"Inbound ID={p['inbound_id']}\n"
            f"Status={p['status']}"
        )
        await update.effective_message.reply_text(text, reply_markup=buttons)

async def list_topup_amount_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = all_topup_options()
    if not rows:
        await update.effective_message.reply_text("TopUp amount မရှိသေးပါ", reply_markup=topup_amount_menu())
        return
    for r in rows:
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Toggle", callback_data=f"topupopt_toggle:{r['id']}"),
                InlineKeyboardButton("Delete", callback_data=f"topupopt_delete:{r['id']}")
            ]
        ])
        text = f"ID={r['id']} | {r['amount']} {DEFAULT_CURRENCY} | Active={r['is_active']}"
        await update.effective_message.reply_text(text, reply_markup=buttons)

async def pending_topups_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = pending_topups()
    if not rows:
        await update.effective_message.reply_text("Pending TopUp မရှိပါ", reply_markup=admin_menu())
        return
    for row in rows:
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_topup:{row['id']}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_topup:{row['id']}")
        ]])
        text = f"TopUp ID: {row['id']}\nUser ID: {row['telegram_id']}\nAmount: {row['amount']} {DEFAULT_CURRENCY}"
        if row["slip_file_id"]:
            await update.effective_message.reply_photo(row["slip_file_id"], caption=text, reply_markup=buttons)
        else:
            await update.effective_message.reply_text(text, reply_markup=buttons)


# =========================================================
# ADMIN CALLBACKS
# =========================================================

async def admin_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return

    data = q.data.split(":")
    head = data[0]

    if head == "bank_toggle":
        toggle_bank(int(data[1]))
        if q.message.photo:
            await q.edit_message_caption("Bank toggled")
        else:
            await q.edit_message_text("Bank toggled")
    elif head == "bank_delete":
        delete_bank(int(data[1]))
        if q.message.photo:
            await q.edit_message_caption("Bank deleted")
        else:
            await q.edit_message_text("Bank deleted")
    elif head == "plan_toggle":
        toggle_plan(int(data[1]))
        await q.edit_message_text("Plan toggled")
    elif head == "plan_delete":
        delete_plan(int(data[1]))
        await q.edit_message_text("Plan deleted")
    elif head == "panel_delete":
        delete_panel(int(data[1]))
        await q.edit_message_text("Panel deleted")
    elif head == "panel_status":
        set_panel_status(int(data[1]), data[2])
        await q.edit_message_text(f"Panel status = {data[2]}")
    elif head == "topupopt_toggle":
        toggle_topup_option(int(data[1]))
        await q.edit_message_text("TopUp amount toggled")
    elif head == "topupopt_delete":
        delete_topup_option(int(data[1]))
        await q.edit_message_text("TopUp amount deleted")


# =========================================================
# PHOTO ROUTER
# =========================================================

async def photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id) and context.user_data.get("flow_add_bank") == "qr":
        file_id = update.message.photo[-1].file_id
        create_bank(
            context.user_data["bank_name"],
            context.user_data["account_name"],
            context.user_data["account_number"],
            context.user_data.get("bank_note", ""),
            file_id
        )
        clear_state(context)
        await update.effective_message.reply_text("Bank added", reply_markup=banks_menu())
        return

    await user_photo_handler(update, context)


# =========================================================
# SKIP ROUTER
# =========================================================

async def skip_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "Skip":
        return

    if context.user_data.get("flow_add_bank") == "note":
        context.user_data["bank_note"] = ""
        context.user_data["flow_add_bank"] = "qr"
        await update.message.reply_text("QR photo ပို့ပါ (မထည့်ချင်ရင် Skip)", reply_markup=skip_menu())
        return

    if context.user_data.get("flow_add_bank") == "qr":
        create_bank(
            context.user_data["bank_name"],
            context.user_data["account_name"],
            context.user_data["account_number"],
            context.user_data.get("bank_note", ""),
            None
        )
        clear_state(context)
        await update.message.reply_text("Bank added", reply_markup=banks_menu())
        return


# =========================================================
# TEXT ROUTER
# =========================================================

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    uid = update.effective_user.id
    ensure_user(update.effective_user)

    if text in {"🔙 Back", "↩️ User Menu"}:
        clear_state(context)
        if text == "↩️ User Menu":
            await update.message.reply_text("User Menu", reply_markup=user_menu())
        else:
            await show_home(update, context)
        return

    # add bank flow
    if context.user_data.get("flow_add_bank") == "bank_name":
        context.user_data["bank_name"] = text
        context.user_data["flow_add_bank"] = "account_name"
        await update.message.reply_text("Account Name ထည့်ပါ", reply_markup=back_menu())
        return

    if context.user_data.get("flow_add_bank") == "account_name":
        context.user_data["account_name"] = text
        context.user_data["flow_add_bank"] = "account_number"
        await update.message.reply_text("Account Number ထည့်ပါ", reply_markup=back_menu())
        return

    if context.user_data.get("flow_add_bank") == "account_number":
        context.user_data["account_number"] = text
        context.user_data["flow_add_bank"] = "note"
        await update.message.reply_text("Note ထည့်ပါ (မလိုရင် Skip)", reply_markup=skip_menu())
        return

    if context.user_data.get("flow_add_bank") == "note":
        context.user_data["bank_note"] = text
        context.user_data["flow_add_bank"] = "qr"
        await update.message.reply_text("QR photo ပို့ပါ (မလိုရင် Skip)", reply_markup=skip_menu())
        return

    # add plan flow
    if context.user_data.get("flow_add_plan") == "plan_name":
        context.user_data["plan_name"] = text
        context.user_data["flow_add_plan"] = "days"
        await update.message.reply_text("Days ထည့်ပါ", reply_markup=back_menu())
        return

    if context.user_data.get("flow_add_plan") == "days":
        if not text.isdigit():
            await update.message.reply_text("Days number ထည့်ပါ")
            return
        context.user_data["plan_days"] = int(text)
        context.user_data["flow_add_plan"] = "price"
        await update.message.reply_text(f"Price ({DEFAULT_CURRENCY}) ထည့်ပါ", reply_markup=back_menu())
        return

    if context.user_data.get("flow_add_plan") == "price":
        try:
            context.user_data["plan_price"] = float(text)
        except Exception:
            await update.message.reply_text("Price number ထည့်ပါ")
            return
        context.user_data["flow_add_plan"] = "traffic"
        await update.message.reply_text("Traffic GB ထည့်ပါ", reply_markup=back_menu())
        return

    if context.user_data.get("flow_add_plan") == "traffic":
        if not text.isdigit():
            await update.message.reply_text("Traffic number ထည့်ပါ")
            return
        create_plan(
            context.user_data["plan_name"],
            context.user_data["plan_days"],
            context.user_data["plan_price"],
            int(text)
        )
        clear_state(context)
        await update.message.reply_text("Plan added", reply_markup=plans_menu())
        return

    # add panel flow
    if context.user_data.get("flow_add_panel") == "panel_name":
        context.user_data["panel_name"] = text
        context.user_data["flow_add_panel"] = "panel_url"
        await update.message.reply_text("Panel base URL ထည့်ပါ", reply_markup=back_menu())
        return

    if context.user_data.get("flow_add_panel") == "panel_url":
        context.user_data["panel_url"] = text
        context.user_data["flow_add_panel"] = "panel_username"
        await update.message.reply_text("Panel username ထည့်ပါ", reply_markup=back_menu())
        return

    if context.user_data.get("flow_add_panel") == "panel_username":
        context.user_data["panel_username"] = text
        context.user_data["flow_add_panel"] = "panel_password"
        await update.message.reply_text("Panel password ထည့်ပါ", reply_markup=back_menu())
        return

    if context.user_data.get("flow_add_panel") == "panel_password":
        context.user_data["panel_password"] = text
        context.user_data["flow_add_panel"] = "inbound_id"
        await update.message.reply_text("Inbound ID ထည့်ပါ", reply_markup=back_menu())
        return

    if context.user_data.get("flow_add_panel") == "inbound_id":
        if not text.isdigit():
            await update.message.reply_text("Inbound ID number ထည့်ပါ")
            return
        create_panel(
            context.user_data["panel_name"],
            context.user_data["panel_url"],
            context.user_data["panel_username"],
            context.user_data["panel_password"],
            int(text)
        )
        clear_state(context)
        await update.message.reply_text("Panel added", reply_markup=panels_menu())
        return

    # add topup amount flow
    if context.user_data.get("flow_add_topup_amount"):
        try:
            amount = float(text)
            create_topup_option(amount)
            clear_state(context)
            await update.message.reply_text("TopUp amount added", reply_markup=topup_amount_menu())
        except Exception:
            await update.message.reply_text("Amount number ထည့်ပါ")
        return

    # normal user
    if text == "🛒 Buy Plan":
        await buy_plan(update, context)
        return

    if text == "💰 TopUp":
        await topup_menu(update, context)
        return

    if text == "👤 My Account":
        await show_account(update, context)
        return

    if text == "📦 My Plan":
        await show_plan(update, context)
        return

    if text == "☎️ Support":
        await show_support(update, context)
        return

    if not is_admin(uid):
        await update.message.reply_text("Menu ကိုပဲသုံးပါ", reply_markup=user_menu())
        return

    # admin menus
    if text == "🏦 Manage Banks":
        await show_banks_menu(update, context)
        return

    if text == "📦 Manage Plans":
        await show_plans_menu(update, context)
        return

    if text == "🖥 Manage Panels":
        await show_panels_menu(update, context)
        return

    if text == "💵 TopUp Amounts":
        await show_topup_amount_menu(update, context)
        return

    if text == "📥 TopUp Requests":
        await pending_topups_screen(update, context)
        return

    if text == "📊 Statistics":
        await show_stats(update, context)
        return

    if text == "➕ Add Bank":
        await start_add_bank(update, context)
        return

    if text == "📋 List Banks":
        await list_banks_screen(update, context)
        return

    if text == "➕ Add Plan":
        await start_add_plan(update, context)
        return

    if text == "📋 List Plans":
        await list_plans_screen(update, context)
        return

    if text == "➕ Add Panel":
        await start_add_panel(update, context)
        return

    if text == "📋 List Panels":
        await list_panels_screen(update, context)
        return

    if text == "➕ Add TopUp Amount":
        await start_add_topup_amount(update, context)
        return

    if text == "📋 List TopUp Amounts":
        await list_topup_amount_screen(update, context)
        return

    await update.message.reply_text("Menu ကိုပဲသုံးပါ", reply_markup=admin_menu())


# =========================================================
# MAIN
# =========================================================

def main():
    requests.packages.urllib3.disable_warnings()
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buy_callback, pattern=r"^buy:\d+$"))
    app.add_handler(CallbackQueryHandler(topup_amount_callback, pattern=r"^topup_amount:\d+$"))
    app.add_handler(CallbackQueryHandler(topup_bank_callback, pattern=r"^topup_bank:\d+$"))
    app.add_handler(CallbackQueryHandler(topup_admin_callback, pattern=r"^(approve_topup|cancel_topup):\d+$"))
    app.add_handler(CallbackQueryHandler(admin_manage_callback, pattern=r"^(bank_toggle|bank_delete|plan_toggle|plan_delete|panel_delete|panel_status|topupopt_toggle|topupopt_delete):"))

    app.add_handler(MessageHandler(filters.PHOTO, photo_router))
    app.add_handler(MessageHandler(filters.Regex(r"^Skip$"), skip_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    logger.info("Bot started...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
