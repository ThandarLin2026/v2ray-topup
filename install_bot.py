import os
import json
import time
import uuid
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

import requests
from telegram import (
    Update,
    ReplyKeyboardMarkup,
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

# =========================================================
# DIRECT CONFIG
# =========================================================
# ဒီနေရာမှာ မင်း data တန်းထည့်
BOT_TOKEN = "PUT_YOUR_BOT_TOKEN_HERE"
ADMIN_IDS = {123456789}   # မင်း Telegram ID ထည့်
SUPPORT_TEXT = "@juevpn42"
BOT_NAME = "JueVPN Bot"
DB_PATH = "bot.sqlite3"
TIMEZONE_OFFSET = 7
DEFAULT_CURRENCY = "THB"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =========================================================
# DB
# =========================================================

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def now_ts() -> int:
    return int(time.time())

def format_dt(ts: Optional[int]) -> str:
    if not ts:
        return "-"
    tz = timezone(timedelta(hours=TIMEZONE_OFFSET))
    return datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d %H:%M:%S")

def gb_to_bytes(gb: int) -> int:
    return gb * 1024 * 1024 * 1024

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

# =========================================================
# DB HELPERS
# =========================================================

def ensure_user(tg_user) -> sqlite3.Row:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE telegram_id=?", (tg_user.id,))
    row = cur.fetchone()
    ts = now_ts()
    full_name = " ".join(x for x in [tg_user.first_name, tg_user.last_name] if x).strip()

    if row:
        cur.execute("""
            UPDATE users
            SET username=?, full_name=?, updated_at=?
            WHERE telegram_id=?
        """, (tg_user.username, full_name, ts, tg_user.id))
    else:
        cur.execute("""
            INSERT INTO users
            (telegram_id, username, full_name, balance, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?)
        """, (tg_user.id, tg_user.username, full_name, ts, ts))

    conn.commit()
    cur.execute("SELECT * FROM users WHERE telegram_id=?", (tg_user.id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_user(telegram_id: int) -> Optional[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_active_plans() -> List[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM plans WHERE is_active=1 ORDER BY days ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_plan(plan_id: int) -> Optional[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM plans WHERE id=?", (plan_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_active_topup_options() -> List[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM topup_options WHERE is_active=1 ORDER BY amount ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_active_banks() -> List[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM banks WHERE is_active=1 ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_bank(bank_id: int) -> Optional[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM banks WHERE id=?", (bank_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_panel(panel_id: int) -> Optional[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM panels WHERE id=?", (panel_id,))
    row = cur.fetchone()
    conn.close()
    return row

def choose_active_panel_for_new_user() -> Optional[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM panels
        WHERE status='active'
        ORDER BY priority ASC, id ASC
        LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()
    return row

def create_topup(telegram_id: int, amount: float, bank_id: int, slip_file_id: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    ts = now_ts()
    cur.execute("""
        INSERT INTO topups (telegram_id, amount, bank_id, slip_file_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'pending', ?, ?)
    """, (telegram_id, amount, bank_id, slip_file_id, ts, ts))
    topup_id = cur.lastrowid
    conn.commit()
    conn.close()
    return topup_id

def approve_topup_db(topup_id: int, admin_id: int) -> Optional[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM topups WHERE id=?", (topup_id,))
    topup = cur.fetchone()
    if not topup or topup["status"] != "pending":
        conn.close()
        return None

    cur.execute("SELECT * FROM users WHERE telegram_id=?", (topup["telegram_id"],))
    user = cur.fetchone()
    if not user:
        conn.close()
        return None

    new_balance = float(user["balance"]) + float(topup["amount"])
    ts = now_ts()

    cur.execute("UPDATE users SET balance=?, updated_at=? WHERE telegram_id=?",
                (new_balance, ts, topup["telegram_id"]))
    cur.execute("UPDATE topups SET status='approved', admin_id=?, updated_at=? WHERE id=?",
                (admin_id, ts, topup_id))

    conn.commit()
    cur.execute("SELECT * FROM topups WHERE id=?", (topup_id,))
    updated = cur.fetchone()
    conn.close()
    return updated

def cancel_topup_db(topup_id: int, admin_id: int) -> Optional[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM topups WHERE id=?", (topup_id,))
    topup = cur.fetchone()
    if not topup or topup["status"] != "pending":
        conn.close()
        return None

    cur.execute("UPDATE topups SET status='cancelled', admin_id=?, updated_at=? WHERE id=?",
                (admin_id, now_ts(), topup_id))
    conn.commit()
    cur.execute("SELECT * FROM topups WHERE id=?", (topup_id,))
    updated = cur.fetchone()
    conn.close()
    return updated

def deduct_user_balance(telegram_id: int, amount: float) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
    user = cur.fetchone()
    if not user:
        conn.close()
        return False
    balance = float(user["balance"])
    if balance < amount:
        conn.close()
        return False
    cur.execute("UPDATE users SET balance=?, updated_at=? WHERE telegram_id=?",
                (balance - amount, now_ts(), telegram_id))
    conn.commit()
    conn.close()
    return True

def refund_user_balance(telegram_id: int, amount: float):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ?, updated_at=? WHERE telegram_id=?",
                (amount, now_ts(), telegram_id))
    conn.commit()
    conn.close()

def create_order(telegram_id: int, plan: sqlite3.Row, panel_id: int) -> int:
    conn = get_conn()
    cur = conn.cursor()
    ts = now_ts()
    cur.execute("""
        INSERT INTO orders (
            telegram_id, plan_id,
            plan_name_snapshot, price_snapshot,
            traffic_gb_snapshot, days_snapshot,
            status, panel_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'paid', ?, ?, ?)
    """, (
        telegram_id,
        plan["id"],
        plan["name"],
        plan["price"],
        plan["traffic_gb"],
        plan["days"],
        panel_id,
        ts,
        ts,
    ))
    order_id = cur.lastrowid
    conn.commit()
    conn.close()
    return order_id

def save_user_client(
    telegram_id: int,
    panel_id: int,
    inbound_id: int,
    client_uuid: str,
    client_email: str,
    expiry_ts: int,
    traffic_bytes: int,
):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE users
        SET panel_id=?, inbound_id=?, client_uuid=?, client_email=?, expiry_ts=?, traffic_bytes=?, updated_at=?
        WHERE telegram_id=?
    """, (
        panel_id, inbound_id, client_uuid, client_email,
        expiry_ts, traffic_bytes, now_ts(), telegram_id
    ))
    conn.commit()
    conn.close()

def list_pending_topups(limit: int = 10) -> List[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM topups
        WHERE status='pending'
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows

# =========================================================
# X-UI CLIENT
# =========================================================

class XUIClient:
    """
    မင်း panel fork ပေါ်မူတည်ပြီး endpoint မတူနိုင်တယ်။
    မအလုပ်လုပ်ရင် login_endpoints / create / renew endpoint ကိုပြင်။
    """

    def __init__(self, panel_url: str, username: str, password: str):
        self.panel_url = panel_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.verify = False

    def login(self) -> bool:
        login_endpoints = [
            "/login",
            "/panel/login",
        ]
        payload = {"username": self.username, "password": self.password}

        for ep in login_endpoints:
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
                "tgId": "",
                "subId": uuid.uuid4().hex[:16],
                "reset": 0,
            }]
        }

        endpoints = [
            "/panel/inbound/addClient",
            "/xui/inbound/addClient",
        ]

        for ep in endpoints:
            try:
                r = self.session.post(
                    self.panel_url + ep,
                    data={
                        "id": inbound_id,
                        "settings": json.dumps(settings),
                    },
                    timeout=15,
                )
                if r.status_code == 200:
                    return {
                        "ok": True,
                        "uuid": client_uuid,
                        "sub_url": f"{self.panel_url}/sub/{client_uuid}",
                        "expiry_ts": expiry_ts,
                        "traffic_bytes": total_bytes,
                        "message": f"created via {ep}",
                    }
            except Exception as e:
                logger.warning("create_client failed %s: %s", ep, e)

        return {
            "ok": False,
            "message": "create_client failed, endpoint check လုပ်ပါ",
        }

    def renew_client(
        self,
        inbound_id: int,
        client_uuid: str,
        email: str,
        new_expiry_ts: int,
        new_total_bytes: int,
    ) -> Dict[str, Any]:
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
                    data={
                        "id": inbound_id,
                        "settings": json.dumps(settings),
                    },
                    timeout=15,
                )
                if r.status_code == 200:
                    return {
                        "ok": True,
                        "uuid": client_uuid,
                        "sub_url": f"{self.panel_url}/sub/{client_uuid}",
                        "expiry_ts": new_expiry_ts,
                        "traffic_bytes": new_total_bytes,
                        "message": f"renewed via {ep}",
                    }
            except Exception as e:
                logger.warning("renew_client failed %s: %s", ep, e)

        return {
            "ok": False,
            "message": "renew_client failed, endpoint check လုပ်ပါ",
        }

# =========================================================
# UI
# =========================================================

def user_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🛒 Buy Plan", "💰 TopUp"],
            ["👤 My Account", "📦 My Plan"],
            ["☎️ Support"],
        ],
        resize_keyboard=True,
    )

def admin_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📥 TopUp Requests", "📦 Manage Plans"],
            ["🏦 Manage Banks", "🖼 Manage QR"],
            ["💸 TopUp Amounts", "🖥 Manage Panels"],
            ["📊 Statistics", "🔙 User Menu"],
        ],
        resize_keyboard=True,
    )

def back_keyboard():
    return ReplyKeyboardMarkup([["🔙 Back"]], resize_keyboard=True)

# =========================================================
# HELPERS
# =========================================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def display_name(user) -> str:
    if user.username:
        return f"@{user.username}"
    full = " ".join(x for x in [user.first_name, user.last_name] if x).strip()
    return full or str(user.id)

async def send_admins(app: Application, text: str, reply_markup=None, photo_file_id: Optional[str] = None):
    for admin_id in ADMIN_IDS:
        try:
            if photo_file_id:
                await app.bot.send_photo(
                    chat_id=admin_id,
                    photo=photo_file_id,
                    caption=text,
                    reply_markup=reply_markup,
                )
            else:
                await app.bot.send_message(
                    chat_id=admin_id,
                    text=text,
                    reply_markup=reply_markup,
                )
        except Exception as e:
            logger.warning("admin send failed %s: %s", admin_id, e)

# =========================================================
# USER
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    keyboard = admin_main_keyboard() if is_admin(update.effective_user.id) else user_main_keyboard()
    await update.message.reply_text(
        f"မင်္ဂလာပါ\n{BOT_NAME} မှ ကြိုဆိုပါတယ်။",
        reply_markup=keyboard,
    )

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Support: {SUPPORT_TEXT}", reply_markup=user_main_keyboard())

async def my_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update.effective_user)
    text = (
        f"👤 Account\n"
        f"Telegram ID: {user['telegram_id']}\n"
        f"Username: @{user['username'] if user['username'] else '-'}\n"
        f"Balance: {float(user['balance']):.2f} {DEFAULT_CURRENCY}\n"
        f"Panel ID: {user['panel_id'] or '-'}\n"
        f"Expiry: {format_dt(user['expiry_ts'])}\n"
    )
    await update.message.reply_text(text, reply_markup=user_main_keyboard())

async def my_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update.effective_user)
    if not user["client_uuid"]:
        await update.message.reply_text("Plan မရှိသေးပါ။", reply_markup=user_main_keyboard())
        return

    text = (
        f"📦 My Plan\n"
        f"UUID: {user['client_uuid']}\n"
        f"Expiry: {format_dt(user['expiry_ts'])}\n"
        f"Traffic: {round((user['traffic_bytes'] or 0) / (1024**3), 2)} GB\n"
        f"Panel ID: {user['panel_id']}\n"
    )
    await update.message.reply_text(text, reply_markup=user_main_keyboard())

async def buy_plan_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plans = get_active_plans()
    if not plans:
        await update.message.reply_text("Active plan မရှိသေးပါ။", reply_markup=user_main_keyboard())
        return

    buttons = []
    for p in plans:
        buttons.append([
            InlineKeyboardButton(
                f"{p['name']} - {p['price']} {DEFAULT_CURRENCY} - {p['traffic_gb']} GB",
                callback_data=f"buyplan:{p['id']}"
            )
        ])

    await update.message.reply_text(
        "ဝယ်မယ့် Plan ကိုရွေးပါ",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def buy_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = ensure_user(query.from_user)
    plan_id = int(query.data.split(":")[1])
    plan = get_plan(plan_id)

    if not plan or not plan["is_active"]:
        await query.edit_message_text("Plan မရနိုင်တော့ပါ။")
        return

    balance = float(user["balance"])
    price = float(plan["price"])
    if balance < price:
        await query.edit_message_text(
            f"Balance မလုံလောက်ပါ။\nလိုအပ်သည်: {price} {DEFAULT_CURRENCY}\nလက်ရှိ: {balance:.2f} {DEFAULT_CURRENCY}"
        )
        return

    existing_panel_id = user["panel_id"]
    if existing_panel_id:
        panel = get_panel(existing_panel_id)
        if not panel:
            await query.edit_message_text("Panel info မတွေ့ပါ။ Admin ကိုဆက်သွယ်ပါ။")
            return
        if panel["status"] == "disabled":
            await query.edit_message_text("သင့် Panel disabled ဖြစ်နေပါတယ်။")
            return
    else:
        panel = choose_active_panel_for_new_user()
        if not panel:
            await query.edit_message_text("အသစ် user အတွက် active panel မရှိသေးပါ။")
            return

    if not deduct_user_balance(user["telegram_id"], price):
        await query.edit_message_text("Balance ဖြတ်မရပါ။")
        return

    xui = XUIClient(panel["panel_url"], panel["username"], panel["password"])
    if not xui.login():
        refund_user_balance(user["telegram_id"], price)
        await query.edit_message_text("Panel login failed")
        return

    email = user["client_email"] or f"tg_{user['telegram_id']}"

    if user["client_uuid"]:
        current_expiry = int(user["expiry_ts"] or now_ts())
        base_expiry = current_expiry if current_expiry > now_ts() else now_ts()
        new_expiry = base_expiry + plan["days"] * 86400
        current_bytes = int(user["traffic_bytes"] or 0)
        new_bytes = current_bytes + gb_to_bytes(plan["traffic_gb"])

        result = xui.renew_client(
            inbound_id=panel["inbound_id"],
            client_uuid=user["client_uuid"],
            email=email,
            new_expiry_ts=new_expiry,
            new_total_bytes=new_bytes,
        )

        if not result["ok"]:
            refund_user_balance(user["telegram_id"], price)
            await query.edit_message_text(f"Renew failed\n{result['message']}")
            return

        save_user_client(
            telegram_id=user["telegram_id"],
            panel_id=panel["id"],
            inbound_id=panel["inbound_id"],
            client_uuid=user["client_uuid"],
            client_email=email,
            expiry_ts=new_expiry,
            traffic_bytes=new_bytes,
        )

        order_id = create_order(user["telegram_id"], plan, panel["id"])
        await query.edit_message_text(
            f"✅ Renew Success\n"
            f"Order ID: {order_id}\n"
            f"Plan: {plan['name']}\n"
            f"Expiry: {format_dt(new_expiry)}\n"
            f"Traffic: {round(new_bytes/(1024**3), 2)} GB\n"
            f"UUID: {user['client_uuid']}\n"
            f"Sub URL: {result.get('sub_url', '-')}"
        )

    else:
        result = xui.create_client(
            inbound_id=panel["inbound_id"],
            email=email,
            days=plan["days"],
            traffic_gb=plan["traffic_gb"],
        )

        if not result["ok"]:
            refund_user_balance(user["telegram_id"], price)
            await query.edit_message_text(f"Create client failed\n{result['message']}")
            return

        save_user_client(
            telegram_id=user["telegram_id"],
            panel_id=panel["id"],
            inbound_id=panel["inbound_id"],
            client_uuid=result["uuid"],
            client_email=email,
            expiry_ts=result["expiry_ts"],
            traffic_bytes=result["traffic_bytes"],
        )

        order_id = create_order(user["telegram_id"], plan, panel["id"])
        await query.edit_message_text(
            f"✅ Client Created\n"
            f"Order ID: {order_id}\n"
            f"Plan: {plan['name']}\n"
            f"Panel: {panel['name']}\n"
            f"Expiry: {format_dt(result['expiry_ts'])}\n"
            f"Traffic: {plan['traffic_gb']} GB\n"
            f"UUID: {result['uuid']}\n"
            f"Sub URL: {result.get('sub_url', '-')}"
        )

async def topup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    options = get_active_topup_options()
    if not options:
        await update.message.reply_text("TopUp option မရှိသေးပါ။", reply_markup=user_main_keyboard())
        return

    buttons = []
    for row in options:
        buttons.append([
            InlineKeyboardButton(
                f"TopUp {row['amount']} {DEFAULT_CURRENCY}",
                callback_data=f"topupamt:{row['id']}"
            )
        ])

    await update.message.reply_text(
        "TopUp amount ကိုရွေးပါ",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def topup_amount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    option_id = int(query.data.split(":")[1])
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM topup_options WHERE id=? AND is_active=1", (option_id,))
    option = cur.fetchone()
    conn.close()

    if not option:
        await query.edit_message_text("TopUp option မရနိုင်တော့ပါ။")
        return

    context.user_data["pending_topup_amount"] = float(option["amount"])

    banks = get_active_banks()
    if not banks:
        await query.edit_message_text("Active bank မရှိသေးပါ။")
        return

    buttons = []
    for bank in banks:
        buttons.append([
            InlineKeyboardButton(
                f"{bank['bank_name']} - {bank['account_number']}",
                callback_data=f"topupbank:{bank['id']}"
            )
        ])

    await query.edit_message_text(
        f"Amount: {option['amount']} {DEFAULT_CURRENCY}\nBank ကိုရွေးပါ",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def topup_bank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    bank_id = int(query.data.split(":")[1])
    bank = get_bank(bank_id)
    amount = context.user_data.get("pending_topup_amount")

    if not bank or not bank["is_active"]:
        await query.edit_message_text("Bank မရနိုင်တော့ပါ။")
        return

    if not amount:
        await query.edit_message_text("TopUp session expired.")
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
        f"ငွေလွှဲပြီး slip / screenshot ကို ပို့ပါ။"
    )

    if bank["qr_file_id"]:
        await query.message.reply_photo(bank["qr_file_id"], caption=text, reply_markup=back_keyboard())
    else:
        await query.message.reply_text(text, reply_markup=back_keyboard())

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_slip"):
        return

    user = ensure_user(update.effective_user)
    amount = context.user_data.get("pending_topup_amount")
    bank_id = context.user_data.get("pending_topup_bank_id")

    if not amount or not bank_id:
        context.user_data.clear()
        await update.message.reply_text("TopUp session expired.", reply_markup=user_main_keyboard())
        return

    photo = update.message.photo[-1]
    file_id = photo.file_id
    topup_id = create_topup(user["telegram_id"], amount, bank_id, file_id)
    bank = get_bank(bank_id)

    admin_text = (
        f"📥 New TopUp Request\n\n"
        f"TopUp ID: {topup_id}\n"
        f"User: {display_name(update.effective_user)}\n"
        f"Telegram ID: {user['telegram_id']}\n"
        f"Amount: {amount} {DEFAULT_CURRENCY}\n"
        f"Bank: {bank['bank_name'] if bank else '-'}\n"
        f"Status: pending"
    )

    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approvetopup:{topup_id}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"canceltopup:{topup_id}"),
    ]])

    await send_admins(context.application, admin_text, reply_markup=markup, photo_file_id=file_id)

    context.user_data.pop("awaiting_slip", None)
    context.user_data.pop("pending_topup_amount", None)
    context.user_data.pop("pending_topup_bank_id", None)

    await update.message.reply_text(
        f"TopUp request ပို့ပြီးပါပြီ\nTopUp ID: {topup_id}\nAdmin approval စောင့်ပါ။",
        reply_markup=user_main_keyboard(),
    )

# =========================================================
# ADMIN CALLBACK
# =========================================================

async def approve_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        try:
            if query.message.photo:
                await query.edit_message_caption("Unauthorized")
            else:
                await query.edit_message_text("Unauthorized")
        except Exception:
            pass
        return

    action, topup_id = query.data.split(":")
    topup_id = int(topup_id)

    if action == "approvetopup":
        updated = approve_topup_db(topup_id, query.from_user.id)
        if not updated:
            if query.message.photo:
                await query.edit_message_caption("Already processed / invalid")
            else:
                await query.edit_message_text("Already processed / invalid")
            return

        user = get_user(updated["telegram_id"])
        new_balance = float(user["balance"]) if user else 0

        text = (
            f"✅ TopUp Approved\n"
            f"TopUp ID: {topup_id}\n"
            f"User ID: {updated['telegram_id']}\n"
            f"Amount: {updated['amount']} {DEFAULT_CURRENCY}\n"
            f"New Balance: {new_balance:.2f} {DEFAULT_CURRENCY}"
        )

        if query.message.photo:
            await query.edit_message_caption(text)
        else:
            await query.edit_message_text(text)

        try:
            await context.bot.send_message(
                chat_id=updated["telegram_id"],
                text=f"✅ TopUp approved\nAmount: {updated['amount']} {DEFAULT_CURRENCY}\nNew Balance: {new_balance:.2f} {DEFAULT_CURRENCY}",
                reply_markup=user_main_keyboard(),
            )
        except Exception:
            pass

    elif action == "canceltopup":
        updated = cancel_topup_db(topup_id, query.from_user.id)
        if not updated:
            if query.message.photo:
                await query.edit_message_caption("Already processed / invalid")
            else:
                await query.edit_message_text("Already processed / invalid")
            return

        text = (
            f"❌ TopUp Cancelled\n"
            f"TopUp ID: {topup_id}\n"
            f"User ID: {updated['telegram_id']}\n"
            f"Amount: {updated['amount']} {DEFAULT_CURRENCY}"
        )

        if query.message.photo:
            await query.edit_message_caption(text)
        else:
            await query.edit_message_text(text)

        try:
            await context.bot.send_message(
                chat_id=updated["telegram_id"],
                text=f"❌ TopUp cancelled\nAmount: {updated['amount']} {DEFAULT_CURRENCY}",
                reply_markup=user_main_keyboard(),
            )
        except Exception:
            pass

# =========================================================
# ADMIN COMMANDS
# =========================================================

ADMIN_HELP = """
Admin Commands

Plans
/addplan NAME|DAYS|PRICE|TRAFFIC_GB
/delplan PLAN_ID
/toggleplan PLAN_ID
/listplans

Banks
/addbank BANK_NAME|ACCOUNT_NAME|ACCOUNT_NUMBER|NOTE
/delbank BANK_ID
/togglebank BANK_ID
/listbanks
/setbankqr BANK_ID

TopUp Amounts
/addtopup AMOUNT
/deltopup TOPUP_OPTION_ID
/toggletopup TOPUP_OPTION_ID
/listtopups

Panels
/addpanel NAME|URL|USERNAME|PASSWORD|INBOUND_ID
/delpanel PANEL_ID
/setpanelstatus PANEL_ID|active|full|disabled|maintenance
/listpanels

/adminhelp
"""

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(ADMIN_HELP, reply_markup=admin_main_keyboard())

async def add_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = update.message.text.replace("/addplan", "", 1).strip()
    try:
        name, days, price, traffic_gb = [x.strip() for x in args.split("|")]
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO plans (name, days, price, traffic_gb, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (name, int(days), float(price), int(traffic_gb), now_ts()))
        conn.commit()
        plan_id = cur.lastrowid
        conn.close()
        await update.message.reply_text(f"Plan added. ID={plan_id}", reply_markup=admin_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Usage:\n/addplan NAME|DAYS|PRICE|TRAFFIC_GB\nError: {e}")

async def del_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        plan_id = int(context.args[0])
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM plans WHERE id=?", (plan_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Plan deleted. ID={plan_id}", reply_markup=admin_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Usage:\n/delplan PLAN_ID\nError: {e}")

async def toggle_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        plan_id = int(context.args[0])
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT is_active FROM plans WHERE id=?", (plan_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            await update.message.reply_text("Plan not found")
            return
        new_val = 0 if row["is_active"] else 1
        cur.execute("UPDATE plans SET is_active=? WHERE id=?", (new_val, plan_id))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Plan {plan_id} active={new_val}", reply_markup=admin_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Usage:\n/toggleplan PLAN_ID\nError: {e}")

async def list_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM plans ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No plans")
        return
    text = "Plans\n\n"
    for r in rows:
        text += f"ID={r['id']} | {r['name']} | {r['days']} days | {r['price']} {DEFAULT_CURRENCY} | {r['traffic_gb']} GB | active={r['is_active']}\n"
    await update.message.reply_text(text, reply_markup=admin_main_keyboard())

async def add_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = update.message.text.replace("/addbank", "", 1).strip()
    try:
        bank_name, account_name, account_number, note = [x.strip() for x in args.split("|")]
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO banks (bank_name, account_name, account_number, note, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (bank_name, account_name, account_number, note, now_ts()))
        conn.commit()
        bank_id = cur.lastrowid
        conn.close()
        await update.message.reply_text(f"Bank added. ID={bank_id}", reply_markup=admin_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Usage:\n/addbank BANK_NAME|ACCOUNT_NAME|ACCOUNT_NUMBER|NOTE\nError: {e}")

async def del_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        bank_id = int(context.args[0])
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM banks WHERE id=?", (bank_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Bank deleted. ID={bank_id}", reply_markup=admin_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Usage:\n/delbank BANK_ID\nError: {e}")

async def toggle_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        bank_id = int(context.args[0])
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT is_active FROM banks WHERE id=?", (bank_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            await update.message.reply_text("Bank not found")
            return
        new_val = 0 if row["is_active"] else 1
        cur.execute("UPDATE banks SET is_active=? WHERE id=?", (new_val, bank_id))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Bank {bank_id} active={new_val}", reply_markup=admin_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Usage:\n/togglebank BANK_ID\nError: {e}")

async def list_banks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM banks ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No banks")
        return
    text = "Banks\n\n"
    for r in rows:
        text += f"ID={r['id']} | {r['bank_name']} | {r['account_name']} | {r['account_number']} | active={r['is_active']} | qr={'yes' if r['qr_file_id'] else 'no'}\n"
    await update.message.reply_text(text, reply_markup=admin_main_keyboard())

async def set_bank_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        bank_id = int(context.args[0])
        context.user_data["set_bank_qr_for"] = bank_id
        await update.message.reply_text(f"Bank ID {bank_id} အတွက် QR photo ကို အခု ပို့ပါ။", reply_markup=admin_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Usage:\n/setbankqr BANK_ID\nError: {e}")

async def admin_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    bank_id = context.user_data.get("set_bank_qr_for")
    if bank_id:
        photo = update.message.photo[-1]
        file_id = photo.file_id

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE banks SET qr_file_id=? WHERE id=?", (file_id, bank_id))
        conn.commit()
        conn.close()

        context.user_data.pop("set_bank_qr_for", None)
        await update.message.reply_text(f"Bank {bank_id} QR updated.", reply_markup=admin_main_keyboard())

async def add_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        amount = float(context.args[0])
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO topup_options (amount, is_active, created_at) VALUES (?, 1, ?)",
                    (amount, now_ts()))
        conn.commit()
        topup_id = cur.lastrowid
        conn.close()
        await update.message.reply_text(f"TopUp option added. ID={topup_id}", reply_markup=admin_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Usage:\n/addtopup AMOUNT\nError: {e}")

async def del_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        topup_id = int(context.args[0])
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM topup_options WHERE id=?", (topup_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"TopUp option deleted. ID={topup_id}", reply_markup=admin_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Usage:\n/deltopup TOPUP_OPTION_ID\nError: {e}")

async def toggle_topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        topup_id = int(context.args[0])
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT is_active FROM topup_options WHERE id=?", (topup_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            await update.message.reply_text("TopUp option not found")
            return
        new_val = 0 if row["is_active"] else 1
        cur.execute("UPDATE topup_options SET is_active=? WHERE id=?", (new_val, topup_id))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"TopUp option {topup_id} active={new_val}", reply_markup=admin_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Usage:\n/toggletopup TOPUP_OPTION_ID\nError: {e}")

async def list_topup_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM topup_options ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No topup options")
        return
    text = "TopUp Options\n\n"
    for r in rows:
        text += f"ID={r['id']} | {r['amount']} {DEFAULT_CURRENCY} | active={r['is_active']}\n"
    await update.message.reply_text(text, reply_markup=admin_main_keyboard())

async def add_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = update.message.text.replace("/addpanel", "", 1).strip()
    try:
        name, url, username, password, inbound_id = [x.strip() for x in args.split("|")]
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO panels (name, panel_url, username, password, inbound_id, status, priority, created_at)
            VALUES (?, ?, ?, ?, ?, 'active', 100, ?)
        """, (name, url, username, password, int(inbound_id), now_ts()))
        conn.commit()
        panel_id = cur.lastrowid
        conn.close()
        await update.message.reply_text(f"Panel added. ID={panel_id}", reply_markup=admin_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Usage:\n/addpanel NAME|URL|USERNAME|PASSWORD|INBOUND_ID\nError: {e}")

async def del_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        panel_id = int(context.args[0])
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM panels WHERE id=?", (panel_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Panel deleted. ID={panel_id}", reply_markup=admin_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Usage:\n/delpanel PANEL_ID\nError: {e}")

async def set_panel_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = update.message.text.replace("/setpanelstatus", "", 1).strip()
    try:
        panel_id, status = [x.strip() for x in args.split("|")]
        if status not in ("active", "full", "disabled", "maintenance"):
            raise ValueError("status must be active/full/disabled/maintenance")
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE panels SET status=? WHERE id=?", (status, int(panel_id)))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Panel {panel_id} status={status}", reply_markup=admin_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"Usage:\n/setpanelstatus PANEL_ID|active|full|disabled|maintenance\nError: {e}")

async def list_panels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM panels ORDER BY priority ASC, id ASC")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No panels")
        return
    text = "Panels\n\n"
    for r in rows:
        text += f"ID={r['id']} | {r['name']} | inbound={r['inbound_id']} | status={r['status']} | priority={r['priority']}\nURL={r['panel_url']}\n\n"
    await update.message.reply_text(text, reply_markup=admin_main_keyboard())

async def statistics_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) c FROM users")
    users_count = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM topups WHERE status='pending'")
    pending_topups = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) c FROM orders")
    orders_count = cur.fetchone()["c"]
    cur.execute("SELECT COALESCE(SUM(balance),0) s FROM users")
    total_balance = cur.fetchone()["s"]
    conn.close()

    text = (
        f"📊 Statistics\n"
        f"Users: {users_count}\n"
        f"Pending TopUps: {pending_topups}\n"
        f"Orders: {orders_count}\n"
        f"Total User Balance: {float(total_balance):.2f} {DEFAULT_CURRENCY}"
    )
    await update.message.reply_text(text, reply_markup=admin_main_keyboard())

async def pending_topups_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    rows = list_pending_topups()
    if not rows:
        await update.message.reply_text("Pending TopUp မရှိပါ။", reply_markup=admin_main_keyboard())
        return

    for row in rows:
        user = get_user(row["telegram_id"])
        text = (
            f"📥 Pending TopUp\n"
            f"ID: {row['id']}\n"
            f"User: {user['full_name'] if user else '-'}\n"
            f"Telegram ID: {row['telegram_id']}\n"
            f"Amount: {row['amount']} {DEFAULT_CURRENCY}\n"
            f"Created: {format_dt(row['created_at'])}"
        )
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"approvetopup:{row['id']}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"canceltopup:{row['id']}"),
        ]])
        if row["slip_file_id"]:
            await update.message.reply_photo(row["slip_file_id"], caption=text, reply_markup=markup)
        else:
            await update.message.reply_text(text, reply_markup=markup)

# =========================================================
# TEXT ROUTER
# =========================================================

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user_id = update.effective_user.id

    if text == "🔙 Back":
        if is_admin(user_id):
            await update.message.reply_text("Admin Menu", reply_markup=admin_main_keyboard())
        else:
            await update.message.reply_text("User Menu", reply_markup=user_main_keyboard())
        return

    if text == "🔙 User Menu":
        await update.message.reply_text("User Menu", reply_markup=user_main_keyboard())
        return

    if text == "🛒 Buy Plan":
        await buy_plan_menu(update, context)
        return

    if text == "💰 TopUp":
        await topup_menu(update, context)
        return

    if text == "👤 My Account":
        await my_account(update, context)
        return

    if text == "📦 My Plan":
        await my_plan(update, context)
        return

    if text == "☎️ Support":
        await support(update, context)
        return

    if is_admin(user_id):
        if text == "📥 TopUp Requests":
            await pending_topups_handler(update, context)
            return
        if text == "📦 Manage Plans":
            await update.message.reply_text(
                "Use:\n/listplans\n/addplan NAME|DAYS|PRICE|TRAFFIC_GB\n/delplan ID\n/toggleplan ID",
                reply_markup=admin_main_keyboard(),
            )
            return
        if text == "🏦 Manage Banks":
            await update.message.reply_text(
                "Use:\n/listbanks\n/addbank BANK_NAME|ACCOUNT_NAME|ACCOUNT_NUMBER|NOTE\n/delbank ID\n/togglebank ID",
                reply_markup=admin_main_keyboard(),
            )
            return
        if text == "🖼 Manage QR":
            await update.message.reply_text(
                "Use:\n/setbankqr BANK_ID\nပြီးရင် QR photo ပို့ပါ။",
                reply_markup=admin_main_keyboard(),
            )
            return
        if text == "💸 TopUp Amounts":
            await update.message.reply_text(
                "Use:\n/listtopups\n/addtopup AMOUNT\n/deltopup ID\n/toggletopup ID",
                reply_markup=admin_main_keyboard(),
            )
            return
        if text == "🖥 Manage Panels":
            await update.message.reply_text(
                "Use:\n/listpanels\n/addpanel NAME|URL|USERNAME|PASSWORD|INBOUND_ID\n/delpanel ID\n/setpanelstatus PANEL_ID|active|full|disabled|maintenance",
                reply_markup=admin_main_keyboard(),
            )
            return
        if text == "📊 Statistics":
            await statistics_handler(update, context)
            return

# =========================================================
# MAIN
# =========================================================

def main():
    requests.packages.urllib3.disable_warnings()
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("adminhelp", admin_help))

    app.add_handler(CommandHandler("addplan", add_plan))
    app.add_handler(CommandHandler("delplan", del_plan))
    app.add_handler(CommandHandler("toggleplan", toggle_plan))
    app.add_handler(CommandHandler("listplans", list_plans))

    app.add_handler(CommandHandler("addbank", add_bank))
    app.add_handler(CommandHandler("delbank", del_bank))
    app.add_handler(CommandHandler("togglebank", toggle_bank))
    app.add_handler(CommandHandler("listbanks", list_banks))
    app.add_handler(CommandHandler("setbankqr", set_bank_qr))

    app.add_handler(CommandHandler("addtopup", add_topup))
    app.add_handler(CommandHandler("deltopup", del_topup))
    app.add_handler(CommandHandler("toggletopup", toggle_topup))
    app.add_handler(CommandHandler("listtopups", list_topup_options))

    app.add_handler(CommandHandler("addpanel", add_panel))
    app.add_handler(CommandHandler("delpanel", del_panel))
    app.add_handler(CommandHandler("setpanelstatus", set_panel_status))
    app.add_handler(CommandHandler("listpanels", list_panels))

    app.add_handler(CallbackQueryHandler(buy_plan_callback, pattern=r"^buyplan:\d+$"))
    app.add_handler(CallbackQueryHandler(topup_amount_callback, pattern=r"^topupamt:\d+$"))
    app.add_handler(CallbackQueryHandler(topup_bank_callback, pattern=r"^topupbank:\d+$"))
    app.add_handler(CallbackQueryHandler(approve_cancel_callback, pattern=r"^(approvetopup|canceltopup):\d+$"))

    app.add_handler(MessageHandler(filters.PHOTO & filters.User(list(ADMIN_IDS)), admin_photo_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    logger.info("Bot started...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
