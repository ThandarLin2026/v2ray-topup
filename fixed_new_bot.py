#!/usr/bin/env python3

-- coding: utf-8 --

import asyncio import html import importlib import io import json import logging import os import re import sqlite3 import subprocess import sys import uuid from datetime import datetime, timedelta from functools import partial from urllib.parse import quote

================= Dependency =================

REQUIRED_PTB_VERSION = "python-telegram-bot>=21.7,<22"

def install_dependencies(): packages = [ ("requests", "requests"), ("telegram", REQUIRED_PTB_VERSION), ("qrcode", "qrcode[pil]"), ("PIL", "pillow"), ]

for module_name, package_name in packages:
    try:
        importlib.import_module(module_name)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])

try:
    import telegram  # noqa: F401
    from telegram.ext import Application  # noqa: F401
    from telegram import CopyTextButton  # noqa: F401
except Exception:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--upgrade", REQUIRED_PTB_VERSION]
    )

install_dependencies()

import requests import qrcode

from telegram import ( Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, CopyTextButton, )

from telegram.ext import ( Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, )

================= Logging =================

logging.basicConfig( format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO, ) logger = logging.getLogger("multi_inbound_bot")

================= Config =================

CONFIG_FILE = "config.json" DB_FILE = "bot_data.db" PID_FILE = "bot.pid" CURRENCY_SYMBOL = "฿"

DEFAULT_CONFIG = { "BOT_TOKEN": "", "ADMIN_ID": 0, "PANEL_URL": "", "PANEL_USER": "", "PANEL_PASS": "", "TOPUP_AMOUNTS": [30, 60, 90, 300, 500], "SERVICES": [ { "name": "🇹🇭 AIS 64/128 KBPS { V2RAY }", "inbound_id": 1, "port": 443, "ws_path": "/ais", "server_address": "ais.example.com", "ws_host": "ais.example.com", "plans": [ {"name": "🇹🇭 AIS 64/128 KBPS { 1 MONTH }", "days": 30, "price": 30, "total_gb": 150}, {"name": "🇹🇭 AIS 64/128 KBPS { 2 MONTHS }", "days": 60, "price": 60, "total_gb": 300}, ], }, { "name": "🇹🇭 TRUE VDO ZOOM { V2RAY }", "inbound_id": 2, "port": 443, "ws_path": "/true", "server_address": "true.example.com", "ws_host": "true.example.com", "plans": [ {"name": "🇹🇭 TRUE VDO ZOOM { 1 MONTH }", "days": 30, "price": 30, "total_gb": 150}, {"name": "🇹🇭 TRUE VDO ZOOM { 2 MONTHS }", "days": 60, "price": 60, "total_gb": 300}, ], }, { "name": "🇲🇲 Myanmar All Sim Wifi { V2RAY }", "inbound_id": 3, "port": 443, "ws_path": "/mm", "server_address": "mm.example.com", "ws_host": "mm.example.com", "plans": [ {"name": "🇲🇲 Myanmar All Sim Wifi { 1 MONTH }", "days": 30, "price": 30, "total_gb": 150}, {"name": "🇲🇲 Myanmar All Sim Wifi { 2 MONTHS }", "days": 60, "price": 60, "total_gb": 300}, ], }, ], "CONTACT_USERNAME": "@Juevpn", "START_MESSAGE_MY": "V2RAY X-UI PANEL မှာ ကြိုဆိုပါတယ်\nAIS / TRUE / Myanmar All Sim Wifi Service များ အသုံးပြုနိုင်ပါတယ်။", "START_MESSAGE_EN": "Welcome to V2RAY X-UI PANEL", "START_MESSAGE_TH": "ยินดีต้อนรับสู่ V2RAY X-UI PANEL", }

CONFIG = DEFAULT_CONFIG.copy()

def money(value): return f"{int(value)} {CURRENCY_SYMBOL}"

def save_config(): with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(CONFIG, f, indent=2, ensure_ascii=False)

def normalize_services(): if "TOPUP_AMOUNTS" not in CONFIG or not isinstance(CONFIG["TOPUP_AMOUNTS"], list) or not CONFIG["TOPUP_AMOUNTS"]: CONFIG["TOPUP_AMOUNTS"] = [30, 60, 90, 300, 500]

for svc in CONFIG.get("SERVICES", []):
    if "plans" not in svc or not isinstance(svc["plans"], list) or not svc["plans"]:
        svc["plans"] = [
            {"name": f"{svc.get('name', 'Service')} {{ 1 MONTH }}", "days": 30, "price": 30, "total_gb": 150},
            {"name": f"{svc.get('name', 'Service')} {{ 2 MONTHS }}", "days": 60, "price": 60, "total_gb": 300},
        ]

def load_config(): global CONFIG if not os.path.exists(CONFIG_FILE): return False try: with open(CONFIG_FILE, "r", encoding="utf-8") as f: loaded = json.load(f) merged = DEFAULT_CONFIG.copy() merged.update(loaded) CONFIG = merged normalize_services() return True except Exception as e: logger.error(f"Cannot load config.json: {e}") return False

def config_is_valid(): if not CONFIG.get("BOT_TOKEN") or not CONFIG.get("ADMIN_ID"): return False if not CONFIG.get("PANEL_URL") or not CONFIG.get("PANEL_USER") or not CONFIG.get("PANEL_PASS"): return False if not isinstance(CONFIG.get("SERVICES"), list) or len(CONFIG["SERVICES"]) == 0: return False return True

def get_config(): print("\n🔧 First-time configuration\n") CONFIG["BOT_TOKEN"] = input("Enter Bot Token: ").strip() CONFIG["ADMIN_ID"] = int(input("Enter Admin Telegram ID: ").strip()) CONFIG["PANEL_URL"] = input("Enter X-UI Panel URL: ").strip().rstrip("/") CONFIG["PANEL_USER"] = input("Enter Panel Username: ").strip() CONFIG["PANEL_PASS"] = input("Enter Panel Password: ").strip()

print("\nNow configure 3 services:")
service_names = [
    "🇹🇭 AIS 64/128 KBPS { V2RAY }",
    "🇹🇭 TRUE VDO ZOOM { V2RAY }",
    "🇲🇲 Myanmar All Sim Wifi { V2RAY }",
]
services = []
for i, svc_name in enumerate(service_names, start=1):
    print(f"\n--- Service {i}: {svc_name} ---")
    inbound_id = int(input(f"  Inbound ID for {svc_name}: ").strip())
    port = int(input("  Port: ").strip())
    ws_path = input("  WS Path default /: ").strip() or "/"
    server_address = input("  Server Address / Domain: ").strip()
    ws_host = input("  WS Host: ").strip()
    services.append(
        {
            "name": svc_name,
            "inbound_id": inbound_id,
            "port": port,
            "ws_path": ws_path,
            "server_address": server_address,
            "ws_host": ws_host,
            "plans": [
                {"name": svc_name.replace("{ V2RAY }", "{ 1 MONTH }"), "days": 30, "price": 30, "total_gb": 150},
                {"name": svc_name.replace("{ V2RAY }", "{ 2 MONTHS }"), "days": 60, "price": 60, "total_gb": 300},
            ],
        }
    )
CONFIG["SERVICES"] = services

contact = input("\nContact Username [default: @Juevpn]: ").strip()
if contact:
    CONFIG["CONTACT_USERNAME"] = contact

save_config()
print(f"\n✅ Saved to {CONFIG_FILE}\n")

def ensure_config(): loaded = load_config() if loaded and config_is_valid(): logger.info("config.json loaded.") return print("\n⚠️ config.json not found or incomplete.\n") if sys.stdin.isatty(): get_config() if not config_is_valid(): print("❌ Config invalid. Please check config.json.") sys.exit(1) return print("❌ Run manually first: python3 bot_full_updated.py") sys.exit(1)

def kill_old_bot(): if os.path.exists(PID_FILE): try: with open(PID_FILE, "r", encoding="utf-8") as f: old_pid = int(f.read().strip()) if old_pid != os.getpid(): try: os.kill(old_pid, 0) os.kill(old_pid, 9) logger.info(f"Killed old process: {old_pid}") except Exception: pass except Exception: pass with open(PID_FILE, "w", encoding="utf-8") as f: f.write(str(os.getpid()))

================= Text =================

TEXTS = { "en": { "buy_plan": "🛒 Buy Plan", "topup": "💰 TopUp", "account": "👤 Account", "balance": "💰 Balance", "contact": "📞 Contact", "admin_panel": "⚙️ Admin Panel", "language": "🌐 Language", "back": "🔙 Back", "main_menu": "🏠 Main Menu", "select_service": "📡 Select service", "select_plan": "📦 Select package", "select_amount": "💰 Select top-up amount", "enter_username": "👤 Please send username for this config.\n\nAllowed: A-Z a-z 0-9 _ . -\nExample: mgmg123\n\nUse /cancel to stop.", "invalid_username": "❌ Invalid username.\nOnly A-Z a-z 0-9 _ . - allowed.\nLength 3 to 32 characters.", "username_exists_db": "❌ This username is already used in bot database.", "username_exists_panel": "❌ This username already exists in X-UI panel.", "insufficient_balance": "❌ Insufficient balance\n\n💰 Balance: {balance}\n📦 Price: {price}\n➕ Need: {need}", "creating_client": "⏳ Creating VLESS client...", "purchase_success": "✅ Plan Purchased Successfully!\n\n📦 Package: {plan}\n💵 Price: {price}\n📊 Limit: {total_gb} GB\n📅 Expires: {expiry}\n👤 Username: {email}\n🔧 Service: {service}", "vless_config": "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>", "copy_fallback": "\n\n📋 Press the Copy VLESS button, or long press config text to copy.", "copy_btn": "📋 Copy VLESS", "copy_not_supported_alert": "Your Telegram app does not support direct copy. Long press config text to copy.", "account_info": "👤 Account Information\n\n📦 Total Configs: {count}", "no_active_plan": "👤 Account Information\n\n📡 No active plan.", "config_header": "━━━━━━ Config {idx} ━━━━━━", "config_status": "📦 Package: {plan}\n👤 Username: {email}\n🆔 User ID: {user_id}\n📅 Expiry: {expiry}\n{status_emoji} Status: {status}\n🛜 Service: {service}\n\n📊 Traffic\n📥 Download: {down}\n📤 Upload: {up}\n💾 Used: {used} / {limit} ({percent:.1f}%)\n\n🔑 UUID: {uuid}", "balance_text": "💰 Your balance: {balance}", "admin_balance_text": "💰 Admin balance: Unlimited", "topup_prompt": "💰 Top-up Amount: {amount}\n\n🏦 Transfer to one bank account below, then send slip photo.", "bank_caption": "🏦 {name}\n💳 {number}\n👤 {holder}\n\n💵 Amount: {amount}", "send_slip": "📸 Send payment slip photo.\nUse /cancel to stop.", "topup_sent": "✅ Top-up request for {amount} sent to admin.", "topup_approved": "✅ Your top-up of {amount} has been approved.", "topup_cancelled": "❌ Your top-up request of {amount} was cancelled.", "contact_text": "📞 Contact Support\n\nTelegram: {username}", "contact_btn": "📩 Open Contact", "admin_add_bank": "➕ Add Bank", "admin_pending_topups": "📋 Pending TopUps", "admin_manage_banks": "🏦 Manage Banks", "admin_broadcast": "📢 Broadcast", "admin_edit_prices": "💵 Edit Plan Prices", "admin_edit_topup": "💰 Edit TopUp Prices", "admin_dashboard": "📊 Users Dashboard", "bank_name_prompt": "🏦 Enter bank name:", "bank_number_prompt": "💳 Enter account number:", "bank_holder_prompt": "👤 Enter account holder:", "bank_qr_prompt": "📷 Send QR photo, image URL, or /skip.", "bank_added": "✅ Bank added.", "bank_updated": "✅ Bank updated.", "no_banks": "ℹ️ No bank accounts. Admin must add a bank first.", "no_pending_topups": "📭 No pending topups.", "admin_note": "📝 Enter note for user, or /skip.", "cancel": "↩️ Cancelled.", "confirm_delete": "🗑 Delete Config?", "delete_confirm_btn": "✅ Confirm Delete", "delete_cancel_btn": "❌ Cancel", "config_deleted": "✅ Config deleted successfully\n\n👤 Username: {email}\n🔑 UUID: {uuid}", "delete_failed": "❌ Failed to delete config.\n\nError: {error}", "select_lang": "🌐 Please select language:", "lang_my": "🇲🇲 Myanmar", "lang_th": "🇹🇭 Thai", "lang_en": "🇬🇧 English", "broadcast_prompt": "📢 Send message to broadcast.\nUse /cancel to stop.", "broadcast_sending": "⏳ Broadcasting...", "broadcast_result": "✅ Broadcast finished.\n\n📤 Sent: {sent}\n❌ Failed: {failed}", "admin_stats": "📊 Users Dashboard\n\n👥 Total Users: {total_users}\n🟢 Total Online: {online}\n⚪ Total Offline: {offline}\n📦 Total Configs: {total_configs}", "edit_topup_prompt": "💰 Send new top-up amounts separated by comma.\nExample: 30,60,90,300,500", "edit_plan_prompt": "Send new plan values as: price,days,total_gb\nExample: 30,30,150", }, "my": { "buy_plan": "🛒 Package ဝယ်ရန်", "topup": "💰 ငွေဖြည့်ရန်", "account": "👤 အကောင့်", "balance": "💰 လက်ကျန်ငွေ", "contact": "📞 ဆက်သွယ်ရန်", "admin_panel": "⚙️ Admin Panel", "language": "🌐 ဘာသာစကား", "back": "🔙 နောက်သို့", "main_menu": "🏠 Main Menu", "select_service": "📡 Service ရွေးပါ", "select_plan": "📦 Package ရွေးပါ", "select_amount": "💰 ငွေဖြည့်မည့် ပမာဏ ရွေးပါ", "enter_username": "👤 ဒီ config အတွက် username ပို့ပါ။\n\nခွင့်ပြုထားတာ: A-Z a-z 0-9 _ . -\nဥပမာ: mgmg123\n\n/cancel ဖြင့် ရပ်နိုင်သည်။", "invalid_username": "❌ Username မမှန်ပါ။\nA-Z a-z 0-9 _ . - သာ ခွင့်ပြုသည်။\nစာလုံးရေ 3 မှ 32 အတွင်း ဖြစ်ရမည်။", "username_exists_db": "❌ ဒီ username ကို bot database ထဲမှာ သုံးထားပြီးပါပြီ။", "username_exists_panel": "❌ ဒီ username က X-UI panel ထဲမှာ ရှိပြီးသားပါ။", "insufficient_balance": "❌ လက်ကျန်ငွေ မလုံလောက်ပါ\n\n💰 လက်ကျန်: {balance}\n📦 စျေးနှုန်း: {price}\n➕ လိုအပ်ငွေ: {need}", "creating_client": "⏳ VLESS client ဖန်တီးနေသည်...", "purchase_success": "✅ Package ဝယ်ယူမှု အောင်မြင်ပါပြီ!\n\n📦 Package: {plan}\n💵 စျေးနှုန်း: {price}\n📊 Data Limit: {total_gb} GB\n📅 သက်တမ်းကုန်: {expiry}\n👤 Username: {email}\n🔧 Service: {service}", "vless_config": "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>", "copy_fallback": "\n\n📋 Copy VLESS ခလုတ်နှိပ်ပါ။ မရပါက config စာသားကို ဖိထားပြီး copy ကူးပါ။", "copy_btn": "📋 Copy VLESS", "copy_not_supported_alert": "သင့် Telegram app မှာ direct copy မရပါ။ Config စာသားကို ဖိထားပြီး copy ကူးပါ။", "account_info": "👤 အကောင့်အချက်အလက်\n\n📦 Config အရေအတွက်: {count}", "no_active_plan": "👤 အကောင့်အချက်အလက်\n\n📡 Active plan မရှိသေးပါ။", "config_header": "━━━━━━ Config {idx} ━━━━━━", "config_status": "📦 Package: {plan}\n👤 Username: {email}\n🆔 User ID: {user_id}\n📅 Expiry: {expiry}\n{status_emoji} Status: {status}\n🛜 Service: {service}\n\n📊 Traffic\n📥 Download: {down}\n📤 Upload: {up}\n💾 Used: {used} / {limit} ({percent:.1f}%)\n\n🔑 UUID: {uuid}", "balance_text": "💰 သင့်လက်ကျန်ငွေ: {balance}", "admin_balance_text": "💰 Admin လက်ကျန်ငွေ: Unlimited", "topup_prompt": "💰 ငွေဖြည့်မည့်ပမာဏ: {amount}\n\n🏦 အောက်ပါ bank account တစ်ခုသို့ လွှဲပြီး slip ပို့ပါ။", "bank_caption": "🏦 {name}\n💳 {number}\n👤 {holder}\n\n💵 ပမာဏ: {amount}", "send_slip": "📸 ငွေလွှဲ slip ဓာတ်ပုံ ပို့ပါ။\n/cancel ဖြင့် ရပ်နိုင်သည်။", "topup_sent": "✅ {amount} ငွေဖြည့်တောင်းဆိုမှုကို admin ထံ ပို့ပြီးပါပြီ။", "topup_approved": "✅ သင့် {amount} ငွေဖြည့်မှုကို အတည်ပြုပြီးပါပြီ။", "topup_cancelled": "❌ သင့် {amount} ငွေဖြည့်တောင်းဆိုမှုကို ပယ်ဖျက်လိုက်ပါသည်။", "contact_text": "📞 ဆက်သွယ်ရန်\n\nTelegram: {username}", "contact_btn": "📩 Contact ဖွင့်ရန်", "admin_add_bank": "➕ Bank ထည့်ရန်", "admin_pending_topups": "📋 Pending TopUps", "admin_manage_banks": "🏦 Bank များစီမံရန်", "admin_broadcast": "📢 Broadcast", "admin_edit_prices": "💵 Package Price ပြင်ရန်", "admin_edit_topup": "💰 TopUp Price ပြင်ရန်", "admin_dashboard": "📊 Users Dashboard", "bank_name_prompt": "🏦 Bank name ရိုက်ထည့်ပါ:", "bank_number_prompt": "💳 Account number ရိုက်ထည့်ပါ:", "bank_holder_prompt": "👤 Account holder ရိုက်ထည့်ပါ:", "bank_qr_prompt": "📷 QR photo, image URL, သို့မဟုတ် /skip ပို့ပါ။", "bank_added": "✅ Bank ထည့်ပြီးပါပြီ။", "bank_updated": "✅ Bank ပြင်ပြီးပါပြီ။", "no_banks": "ℹ️ Bank account မရှိသေးပါ။ Admin က Bank အရင်ထည့်ပါ။", "no_pending_topups": "📭 Pending TopUp မရှိပါ။", "admin_note": "📝 User အတွက် note ရိုက်ပါ။ မလိုပါက /skip ပို့ပါ။", "cancel": "↩️ ပယ်ဖျက်လိုက်ပါပြီ။", "confirm_delete": "🗑 Config ဖျက်မည်?", "delete_confirm_btn": "✅ ဖျက်ရန် အတည်ပြု", "delete_cancel_btn": "❌ မဖျက်တော့ပါ", "config_deleted": "✅ Config ကို ဖျက်ပြီးပါပြီ\n\n👤 Username: {email}\n🔑 UUID: {uuid}", "delete_failed": "❌ Config ဖျက်မအောင်မြင်ပါ။\n\nError: {error}", "select_lang": "🌐 ဘာသာစကား ရွေးပါ:", "lang_my": "🇲🇲 မြန်မာ", "lang_th": "🇹🇭 ထိုင်း", "lang_en": "🇬🇧 English", "broadcast_prompt": "📢 User အားလုံးသို့ ပို့မည့် message ရိုက်ပါ။\n/cancel ဖြင့် ရပ်နိုင်သည်။", "broadcast_sending": "⏳ Broadcasting...", "broadcast_result": "✅ Broadcast ပြီးပါပြီ။\n\n📤 Sent: {sent}\n❌ Failed: {failed}", "admin_stats": "📊 Users Dashboard\n\n👥 Total Users: {total_users}\n🟢 Total Online: {online}\n⚪ Total Offline: {offline}\n📦 Total Configs: {total_configs}", "edit_topup_prompt": "💰 TopUp amount အသစ်တွေကို comma နဲ့ခွဲပြီးပို့ပါ။\nဥပမာ: 30,60,90,300,500", "edit_plan_prompt": "Plan တန်ဖိုးအသစ်ကို ဒီပုံစံနဲ့ပို့ပါ: price,days,total_gb\nဥပမာ: 30,30,150", }, "th": {} } TEXTS["th"] = TEXTS["en"].copy() TEXTS["th"].update({ "buy_plan": "🛒 ซื้อแพ็กเกจ", "topup": "💰 เติมเงิน", "account": "👤 บัญชี", "balance": "💰 ยอดเงิน", "contact": "📞 ติดต่อ", "admin_panel": "⚙️ แอดมิน", "language": "🌐 ภาษา", "main_menu": "🏠 เมนูหลัก", })

def get_text(key, lang="en", **kwargs): lang_dict = TEXTS.get(lang, TEXTS["en"]) text = lang_dict.get(key, TEXTS["en"].get(key, key)) if kwargs: try: return text.format(**kwargs) except Exception: return text return text

================= Database =================

class Database: def init(self): self._init_db()

def _column_exists(self, conn, table, column):
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())

def _add_column_if_missing(self, conn, table, column, definition):
    if not self._column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def _init_db(self):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0,
                lang TEXT DEFAULT 'my'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS topup_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                slip_file_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS banks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                number TEXT,
                holder TEXT,
                qr_file_id TEXT,
                qr_url TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_clients (
                user_id INTEGER,
                uuid TEXT,
                email TEXT,
                service_name TEXT,
                inbound_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expiry_at TIMESTAMP,
                total_gb INTEGER,
                download_used INTEGER DEFAULT 0,
                upload_used INTEGER DEFAULT 0
            )
            """
        )
        self._add_column_if_missing(conn, "user_clients", "plan_name", "TEXT DEFAULT ''")
        self._add_column_if_missing(conn, "user_clients", "plan_days", "INTEGER DEFAULT 30")
        self._add_column_if_missing(conn, "user_clients", "price", "INTEGER DEFAULT 30")
        conn.commit()

async def execute(self, query, params=()):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(self._execute_sync, query, params))

def _execute_sync(self, query, params):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(query, params)
        conn.commit()
        if query.strip().upper().startswith("SELECT"):
            return [dict(row) for row in cur.fetchall()]
        return cur.lastrowid

async def create_user(self, user_id, username):
    await self.execute("INSERT OR IGNORE INTO users (user_id, username, lang) VALUES (?, ?, ?)", (user_id, username, "my"))

async def get_user(self, user_id):
    rows = await self.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return rows[0] if rows else None

async def get_user_lang(self, user_id):
    user = await self.get_user(user_id)
    return user["lang"] if user and user.get("lang") else "my"

async def set_user_lang(self, user_id, lang):
    await self.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, user_id))

async def set_admin(self, user_id):
    await self.execute("UPDATE users SET is_admin=1 WHERE user_id=?", (user_id,))

async def is_admin(self, user_id):
    user = await self.get_user(user_id)
    return bool(user and user["is_admin"])

async def get_all_users(self):
    return await self.execute("SELECT * FROM users ORDER BY user_id")

async def get_balance(self, user_id):
    user = await self.get_user(user_id)
    return int(user["balance"]) if user else 0

async def update_balance(self, user_id, delta):
    await self.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id))

async def add_bank(self, name, number, holder, qr_file_id=None, qr_url=None):
    await self.execute("INSERT INTO banks (name, number, holder, qr_file_id, qr_url) VALUES (?, ?, ?, ?, ?)", (name, number, holder, qr_file_id, qr_url))

async def update_bank(self, bank_id, name, number, holder, qr_file_id=None, qr_url=None):
    await self.execute("UPDATE banks SET name=?, number=?, holder=?, qr_file_id=?, qr_url=? WHERE id=?", (name, number, holder, qr_file_id, qr_url, bank_id))

async def get_bank(self, bank_id):
    rows = await self.execute("SELECT * FROM banks WHERE id=?", (bank_id,))
    return rows[0] if rows else None

async def get_banks(self):
    return await self.execute("SELECT * FROM banks ORDER BY id")

async def delete_bank(self, bank_id):
    await self.execute("DELETE FROM banks WHERE id=?", (bank_id,))

async def create_topup(self, user_id, amount, slip_file_id):
    return await self.execute("INSERT INTO topup_requests (user_id, amount, slip_file_id) VALUES (?, ?, ?)", (user_id, amount, slip_file_id))

async def get_topup(self, topup_id):
    rows = await self.execute("SELECT * FROM topup_requests WHERE id=?", (topup_id,))
    return rows[0] if rows else None

async def update_topup_status(self, topup_id, status):
    await self.execute("UPDATE topup_requests SET status=? WHERE id=?", (status, topup_id))

async def get_pending_topups(self):
    return await self.execute("SELECT * FROM topup_requests WHERE status='pending' ORDER BY created_at")

async def add_client(self, user_id, uuid_str, email, service_name, inbound_id, total_gb, expiry_at, plan_name, plan_days, price):
    await self.execute(
        """
        INSERT INTO user_clients
        (user_id, uuid, email, service_name, inbound_id, expiry_at, total_gb, plan_name, plan_days, price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, uuid_str, email, service_name, inbound_id, expiry_at.isoformat(), total_gb, plan_name, plan_days, price),
    )

async def get_clients(self, user_id):
    return await self.execute("SELECT rowid, * FROM user_clients WHERE user_id=? ORDER BY created_at DESC", (user_id,))

async def get_clients_by_service(self, user_id, service_name):
    return await self.execute("SELECT rowid, * FROM user_clients WHERE user_id=? AND service_name=? ORDER BY created_at DESC", (user_id, service_name))

async def get_all_clients(self):
    return await self.execute("SELECT rowid, * FROM user_clients ORDER BY created_at DESC")

async def get_client_by_row_id(self, row_id):
    rows = await self.execute("SELECT rowid, * FROM user_clients WHERE rowid=? LIMIT 1", (row_id,))
    return rows[0] if rows else None

async def delete_client_by_row_id(self, row_id):
    await self.execute("DELETE FROM user_clients WHERE rowid=?", (row_id,))

async def email_exists(self, email):
    rows = await self.execute("SELECT email FROM user_clients WHERE LOWER(email)=LOWER(?) LIMIT 1", (email,))
    return bool(rows)

async def update_client_usage_by_email(self, email, down, up):
    await self.execute("UPDATE user_clients SET download_used=?, upload_used=? WHERE email=?", (down, up, email))

db = Database()

================= X-UI Client =================

class XUIClient: def init(self, panel_url, panel_user, panel_pass): self.session = requests.Session() self.base_url = self._detect_api_base(panel_url, panel_user, panel_pass)

def _try_login(self, base_url, username, password):
    try:
        resp = self.session.post(f"{base_url.rstrip('/')}/login", data={"username": username, "password": password}, timeout=12)
        if resp.status_code != 200:
            return False
        try:
            return resp.json().get("success") is True
        except Exception:
            return "success" in resp.text.lower() and "true" in resp.text.lower()
    except Exception:
        return False

def _detect_api_base(self, panel_url, username, password):
    panel_url = panel_url.rstrip("/")
    root_url = "/".join(panel_url.split("/")[:3])
    candidates = []
    for base in [panel_url, root_url]:
        if base and base not in candidates:
            candidates.append(base)
    for base in candidates:
        if self._try_login(base, username, password):
            logger.info(f"API base detected: {base}")
            return base.rstrip("/")
    raise Exception("Could not login to X-UI panel.")

def add_client(self, inbound_id, email, uuid_str, total_gb=0, expiry_time=0):
    url = f"{self.base_url}/xui/API/inbounds/addClient/"
    settings = {"clients": [{"email": email, "id": uuid_str, "enable": True, "flow": "", "totalGB": total_gb, "expiryTime": expiry_time, "limitIp": 0, "subId": "", "tgId": "", "reset": 0}]}
    resp = self.session.post(url, data={"id": inbound_id, "settings": json.dumps(settings)}, timeout=20)
    if resp.status_code != 200:
        raise Exception(f"Add client HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        result = resp.json()
    except Exception:
        raise Exception(f"Add client invalid JSON: {resp.text[:300]}")
    if not result.get("success"):
        raise Exception(f"Add client error: {result.get('msg', 'Unknown')}")
    return result

def get_inbounds(self):
    for url in [f"{self.base_url}/xui/API/inbounds/list", f"{self.base_url}/panel/api/inbounds/list"]:
        try:
            resp = self.session.get(url, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return data.get("obj") or []
        except Exception:
            pass
    return []

def get_online_emails(self):
    for url in [f"{self.base_url}/xui/API/inbounds/onlines", f"{self.base_url}/panel/api/inbounds/onlines"]:
        try:
            resp = self.session.post(url, timeout=15)
            if resp.status_code != 200:
                resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if not data.get("success"):
                continue
            obj = data.get("obj")
            result = set()
            if obj is None:
                return result
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, str):
                        result.add(item.lower())
                    elif isinstance(item, dict):
                        email = item.get("email") or item.get("user") or item.get("remark")
                        if email:
                            result.add(str(email).lower())
                return result
            if isinstance(obj, dict):
                for value in obj.values():
                    if isinstance(value, str):
                        result.add(value.lower())
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, str):
                                result.add(item.lower())
                            elif isinstance(item, dict):
                                email = item.get("email") or item.get("user") or item.get("remark")
                                if email:
                                    result.add(str(email).lower())
                return result
        except Exception:
            pass
    return None

def get_client_traffic(self, email):
    encoded = quote(email, safe="")
    urls = [
        f"{self.base_url}/xui/API/inbounds/getClientTraffics/{encoded}",
        f"{self.base_url}/panel/api/inbounds/getClientTraffics/{encoded}",
        f"{self.base_url}/xui/API/inbounds/getClientTraffics/{email}",
        f"{self.base_url}/panel/api/inbounds/getClientTraffics/{email}",
    ]
    for url in urls:
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and data.get("obj"):
                    return self._normalize_traffic(data.get("obj"))
        except Exception:
            pass
    for inbound in self.get_inbounds():
        try:
            settings_raw = inbound.get("settings")
            if not settings_raw:
                continue
            settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
            for client in settings.get("clients", []):
                if str(client.get("email", "")).lower() == email.lower():
                    traffic = self._normalize_traffic(client)
                    for stat in inbound.get("clientStats", []) or []:
                        if str(stat.get("email", "")).lower() == email.lower():
                            traffic.update(self._normalize_traffic(stat))
                            traffic["enable"] = client.get("enable", traffic.get("enable", True))
                            traffic["expiryTime"] = client.get("expiryTime", traffic.get("expiryTime", 0))
                            traffic["total"] = client.get("totalGB", traffic.get("total", 0))
                            traffic["email"] = client.get("email", email)
                            break
                    return traffic
        except Exception:
            pass
    return {}

def _normalize_traffic(self, obj):
    return {
        "downlink": self._safe_int(obj.get("downlink", obj.get("down", obj.get("download", 0)))),
        "uplink": self._safe_int(obj.get("uplink", obj.get("up", obj.get("upload", 0)))),
        "total": self._safe_int(obj.get("total", obj.get("totalGB", obj.get("total_gb", 0)))),
        "expiryTime": self._safe_int(obj.get("expiryTime", obj.get("expiry_time", 0))),
        "enable": obj.get("enable", True),
        "email": obj.get("email", ""),
    }

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

def email_exists(self, email):
    traffic = self.get_client_traffic(email)
    if traffic and str(traffic.get("email", "")).lower() == email.lower():
        return True
    for inbound in self.get_inbounds():
        try:
            settings_raw = inbound.get("settings")
            if settings_raw:
                settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
                for client in settings.get("clients", []):
                    if str(client.get("email", "")).lower() == email.lower():
                        return True
        except Exception:
            pass
    return False

def delete_client(self, uuid_str, inbound_id=None, email=None):
    if not uuid_str:
        raise Exception("Missing client UUID")
    if not inbound_id:
        inbound_id = self.find_inbound_id_by_uuid_or_email(uuid_str, email)
    candidates = []
    if inbound_id:
        candidates.extend([
            ("POST", f"{self.base_url}/xui/API/inbounds/{inbound_id}/delClient/{uuid_str}", None),
            ("GET", f"{self.base_url}/xui/API/inbounds/{inbound_id}/delClient/{uuid_str}", None),
            ("POST", f"{self.base_url}/panel/api/inbounds/{inbound_id}/delClient/{uuid_str}", None),
            ("GET", f"{self.base_url}/panel/api/inbounds/{inbound_id}/delClient/{uuid_str}", None),
        ])
    candidates.extend([
        ("POST", f"{self.base_url}/xui/API/inbounds/delClient/{uuid_str}", None),
        ("GET", f"{self.base_url}/xui/API/inbounds/delClient/{uuid_str}", None),
        ("POST", f"{self.base_url}/panel/api/inbounds/delClient/{uuid_str}", None),
        ("GET", f"{self.base_url}/panel/api/inbounds/delClient/{uuid_str}", None),
        ("POST", f"{self.base_url}/xui/API/inbounds/delClient/", {"id": inbound_id, "clientId": uuid_str}),
        ("POST", f"{self.base_url}/panel/api/inbounds/delClient/", {"id": inbound_id, "clientId": uuid_str}),
    ])
    errors = []
    for method, url, form_data in candidates:
        try:
            resp = self.session.post(url, data=form_data, timeout=20) if method == "POST" else self.session.get(url, timeout=20)
            text = resp.text[:300]
            if resp.status_code != 200:
                errors.append(f"{resp.status_code} {url}")
                continue
            try:
                js = resp.json()
                if js.get("success") is True:
                    return True
                errors.append(f"{url}: {js.get('msg', js)}")
            except Exception:
                if "success" in text.lower() and "true" in text.lower():
                    return True
                errors.append(f"{url}: {text}")
        except Exception as e:
            errors.append(f"{url}: {e}")
    if email and not self.email_exists(email):
        return True
    raise Exception("Failed to delete client from X-UI panel. Tried endpoints: " + " | ".join(errors[-5:]))

def find_inbound_id_by_uuid_or_email(self, uuid_str, email=None):
    for inbound in self.get_inbounds():
        try:
            settings_raw = inbound.get("settings")
            if not settings_raw:
                continue
            settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
            for client in settings.get("clients", []):
                cid = str(client.get("id", ""))
                cmail = str(client.get("email", ""))
                if cid == uuid_str or (email and cmail.lower() == email.lower()):
                    return inbound.get("id")
        except Exception:
            pass
    return None

xui_client = None

================= Helpers =================

def get_welcome_text(lang): if lang == "my": return CONFIG["START_MESSAGE_MY"] if lang == "th": return CONFIG["START_MESSAGE_TH"] return CONFIG["START_MESSAGE_EN"]

def sanitize_username(username): return username.strip()

def is_valid_xui_email_value(username): return bool(re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username))

def get_service_by_index(index): services = CONFIG.get("SERVICES", []) if isinstance(index, int) and 0 <= index < len(services): return services[index] return None

def get_plan_by_index(service, index): plans = service.get("plans", []) if service else [] if isinstance(index, int) and 0 <= index < len(plans): return plans[index] return None

def get_service_config(service_name): for svc in CONFIG["SERVICES"]: if svc["name"] == service_name: return svc return None

def generate_vless_link(uuid_str, remark, service_config): address = service_config["server_address"] port = service_config["port"] path = service_config.get("ws_path", "/") ws_host = service_config["ws_host"] link = f"vless://{uuid_str}@{address}:{port}?path={quote(path, safe='/')}&security=none&encryption=none&type=ws&host={quote(ws_host, safe='')}" if remark: link += f"#{quote(remark.replace(' ', '_'), safe='')}" return link

def generate_qr_bytes(data): qr = qrcode.QRCode(box_size=10, border=4) qr.add_data(data) qr.make(fit=True) img = qr.make_image(fill_color="black", back_color="white") bio = io.BytesIO() img.save(bio, format="PNG") bio.seek(0) return bio

def format_bytes(size): size = int(size or 0) for unit in ["B", "KB", "MB", "GB", "TB"]: if size < 1024.0: return f"{size:.2f} {unit}" size /= 1024.0 return f"{size:.2f} PB"

def get_vless_copy_keyboard(vless_link, lang): try: return InlineKeyboardMarkup([[InlineKeyboardButton(get_text("copy_btn", lang), copy_text=CopyTextButton(text=vless_link))]]) except Exception: return InlineKeyboardMarkup([[InlineKeyboardButton(get_text("copy_btn", lang), callback_data="copy_not_supported")]])

def get_config_action_keyboard(row_id, lang): return InlineKeyboardMarkup([[InlineKeyboardButton(get_text("confirm_delete", lang), callback_data=f"delcfg_{row_id}")]])

def get_delete_confirm_keyboard(row_id, lang): return InlineKeyboardMarkup([[InlineKeyboardButton(get_text("delete_confirm_btn", lang), callback_data=f"confirmdelcfg_{row_id}"), InlineKeyboardButton(get_text("delete_cancel_btn", lang), callback_data=f"canceldelcfg_{row_id}")]])

def get_contact_keyboard(lang): username = CONFIG.get("CONTACT_USERNAME", "@Juevpn").strip() clean = username[1:] if username.startswith("@") else username return InlineKeyboardMarkup([[InlineKeyboardButton(get_text("contact_btn", lang), url=f"https://t.me/{clean}")]])

def get_contact_text(lang): username = CONFIG.get("CONTACT_USERNAME", "@Juevpn").strip() if not username.startswith("@"): username = "@" + username return get_text("contact_text", lang, username=username)

def build_client_status_text(client, traffic, lang, online_emails=None): download = int(traffic.get("downlink", client.get("download_used", 0)) or 0) upload = int(traffic.get("uplink", client.get("upload_used", 0)) or 0) total_used = download + upload total_limit_bytes = int(client.get("total_gb", 0) or 0) or 150 * 1024**3

panel_expiry_ms = int(traffic.get("expiryTime", 0) or 0)
if panel_expiry_ms > 0:
    expiry = datetime.utcfromtimestamp(panel_expiry_ms / 1000)
elif client.get("expiry_at"):
    expiry = datetime.fromisoformat(client["expiry_at"])
else:
    expiry = None

enabled = bool(traffic.get("enable", True))
now = datetime.utcnow()
if expiry:
    seconds_left = (expiry - now).total_seconds()
    days_left = int(seconds_left // 86400)
    is_expired = seconds_left < 0
    expiry_str = expiry.strftime("%d %b %Y") + (" (Expired)" if is_expired else f" ({days_left} days left)")
else:
    is_expired = False
    expiry_str = "Unlimited"

usage_percent = (total_used / total_limit_bytes * 100) if total_limit_bytes > 0 else 0
traffic_exhausted = total_limit_bytes > 0 and total_used >= total_limit_bytes
email_lower = str(client["email"]).lower()

if not enabled:
    status_text, status_emoji = "Disabled", "🔴"
elif is_expired:
    status_text, status_emoji = "Expired", "🔴"
elif traffic_exhausted:
    status_text, status_emoji = "Traffic Finished", "🔴"
else:
    if online_emails is not None:
        status_text, status_emoji = ("Online", "🟢") if email_lower in online_emails else ("Offline", "⚪")
    else:
        status_text, status_emoji = "Online", "🟢"

return get_text(
    "config_status",
    lang,
    plan=client.get("plan_name") or "Package",
    email=client["email"],
    user_id=client.get("user_id", "-"),
    expiry=expiry_str,
    status_emoji=status_emoji,
    status=status_text,
    service=client["service_name"],
    down=format_bytes(download),
    up=format_bytes(upload),
    used=format_bytes(total_used),
    limit=format_bytes(total_limit_bytes),
    percent=usage_percent,
    uuid=client["uuid"],
)

def is_client_online(client, online_emails): if online_emails is None: return False return str(client.get("email", "")).lower() in online_emails

async def get_main_keyboard(is_admin, lang): buttons = [ [KeyboardButton(get_text("buy_plan", lang)), KeyboardButton(get_text("topup", lang))], [KeyboardButton(get_text("account", lang)), KeyboardButton(get_text("balance", lang))], [KeyboardButton(get_text("contact", lang)), KeyboardButton(get_text("language", lang))], ] if is_admin: buttons.append([KeyboardButton(get_text("admin_panel", lang))]) return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def send_main_menu_by_message(message, user_id, lang=None): if lang is None: lang = await db.get_user_lang(user_id) keyboard = await get_main_keyboard(await db.is_admin(user_id), lang) await message.reply_text(get_text("main_menu", lang), reply_markup=keyboard)

async def send_main_menu_to_chat(context, chat_id, user_id, lang=None): if lang is None: lang = await db.get_user_lang(user_id) keyboard = await get_main_keyboard(await db.is_admin(user_id), lang) await context.bot.send_message(chat_id, get_text("main_menu", lang), reply_markup=keyboard)

async def send_client_config_block(message_obj, client, lang): svc = get_service_config(client["service_name"]) if not svc: raise Exception("Service config missing") link = generate_vless_link(client["uuid"], client["email"], svc) await message_obj.reply_text(get_text("vless_config", lang, config=html.escape(link)) + get_text("copy_fallback", lang), parse_mode="HTML", reply_markup=get_vless_copy_keyboard(link, lang))

================= Bot Handlers =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): user = update.effective_user user_id = user.id context.user_data.clear() await db.create_user(user_id, user.username or user.full_name or str(user_id)) if int(user_id) == int(CONFIG["ADMIN_ID"]): await db.set_admin(user_id) lang = await db.get_user_lang(user_id) await update.message.reply_text(get_welcome_text(lang)) await send_main_menu_by_message(update.message, user_id, lang)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE): context.user_data.clear() user_id = update.effective_user.id lang = await db.get_user_lang(user_id) await update.message.reply_text(get_text("cancel", lang)) await send_main_menu_by_message(update.message, user_id, lang)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE): user = update.effective_user user_id = user.id text = (update.message.text or "").strip() if update.message.text else "" await db.create_user(user_id, user.username or user.full_name or str(user_id)) if int(user_id) == int(CONFIG["ADMIN_ID"]): await db.set_admin(user_id) lang = await db.get_user_lang(user_id) state = context.user_data.get("state")

if state == "buy_username":
    await handle_buy_username(update, context)
elif state == "admin_note":
    await handle_admin_note(update, context)
elif state == "bank_name":
    context.user_data["bank_name"] = text
    context.user_data["state"] = "bank_number"
    await update.message.reply_text(get_text("bank_number_prompt", lang))
elif state == "bank_number":
    context.user_data["bank_number"] = text
    context.user_data["state"] = "bank_holder"
    await update.message.reply_text(get_text("bank_holder_prompt", lang))
elif state == "bank_holder":
    context.user_data["bank_holder"] = text
    context.user_data["state"] = "bank_qr"
    await update.message.reply_text(get_text("bank_qr_prompt", lang))
elif state == "bank_qr":
    await handle_bank_qr(update, context)
elif state == "edit_bank_name":
    bank = context.user_data["edit_bank"]
    context.user_data["edit_bank_name"] = bank["name"] if text == "/skip" else text
    context.user_data["state"] = "edit_bank_number"
    await update.message.reply_text("💳 Enter new account number, or /skip:")
elif state == "edit_bank_number":
    bank = context.user_data["edit_bank"]
    context.user_data["edit_bank_number"] = bank["number"] if text == "/skip" else text
    context.user_data["state"] = "edit_bank_holder"
    await update.message.reply_text("👤 Enter new account holder, or /skip:")
elif state == "edit_bank_holder":
    bank = context.user_data["edit_bank"]
    context.user_data["edit_bank_holder"] = bank["holder"] if text == "/skip" else text
    context.user_data["state"] = "edit_bank_qr"
    await update.message.reply_text("📷 Send new QR photo, URL, or /skip:")
elif state == "edit_bank_qr":
    await handle_edit_bank_qr(update, context)
elif state == "broadcast":
    await handle_broadcast(update, context)
elif state == "edit_topup_amounts":
    await handle_edit_topup_amounts(update, context)
elif state == "edit_plan_values":
    await handle_edit_plan_values(update, context)
else:
    await route_main_menu_text(update, context, text)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE): state = context.user_data.get("state") if state == "topup_slip": await receive_slip(update, context) elif state == "bank_qr": await handle_bank_qr(update, context) elif state == "edit_bank_qr": await handle_edit_bank_qr(update, context) else: user_id = update.effective_user.id lang = await db.get_user_lang(user_id) await update.message.reply_text(get_text("main_menu", lang)) await send_main_menu_by_message(update.message, user_id, lang)

async def route_main_menu_text(update, context, text): user_id = update.effective_user.id lang = await db.get_user_lang(user_id) if text == get_text("buy_plan", lang): await show_service_selection(update, lang) elif text == get_text("topup", lang): await start_topup(update, lang) elif text == get_text("account", lang): if await db.is_admin(user_id): await show_admin_dashboard(update.message, context, lang) else: await show_account_service_menu(update, lang) elif text == get_text("balance", lang): await show_balance(update, lang) elif text == get_text("contact", lang): await show_contact(update, lang) elif text == get_text("language", lang): await show_language_selector(update, lang) elif text == get_text("admin_panel", lang): if await db.is_admin(user_id): await show_admin_panel(update, lang) else: await send_main_menu_by_message(update.message, user_id, lang) else: await send_main_menu_by_message(update.message, user_id, lang)

async def show_service_selection(update, lang): keyboard = [[InlineKeyboardButton(svc["name"], callback_data=f"service_{idx}")] for idx, svc in enumerate(CONFIG.get("SERVICES", []))] keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")]) await update.message.reply_text(get_text("select_service", lang), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_plan_selection_from_service(query, context, service_index): user_id = query.from_user.id lang = await db.get_user_lang(user_id) service = get_service_by_index(service_index) if not service: await query.answer("Service not found.", show_alert=True) return keyboard = [] for plan_index, plan in enumerate(service.get("plans", [])): keyboard.append([InlineKeyboardButton(f"{plan['name']} - {money(plan['price'])}", callback_data=f"buyplan_{service_index}_{plan_index}")]) keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")]) try: await query.message.delete() except Exception: pass await context.bot.send_message(chat_id=query.message.chat.id, text=get_text("select_plan", lang), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def start_buy_plan_from_plan(query, context, service_index, plan_index): user_id = query.from_user.id lang = await db.get_user_lang(user_id) service = get_service_by_index(service_index) plan = get_plan_by_index(service, plan_index) if not service or not plan: await query.answer("Plan not found.", show_alert=True) return context.user_data.clear() context.user_data["state"] = "buy_username" context.user_data["selected_service_index"] = service_index context.user_data["selected_plan_index"] = plan_index try: await query.message.delete() except Exception: pass await context.bot.send_message(chat_id=query.message.chat.id, text=f"{plan['name']} - {money(plan['price'])}\n\n" + get_text("enter_username", lang), parse_mode="Markdown")

async def handle_buy_username(update, context): username = sanitize_username((update.message.text or "").strip()) user_id = update.effective_user.id lang = await db.get_user_lang(user_id) service = get_service_by_index(context.user_data.get("selected_service_index")) plan = get_plan_by_index(service, context.user_data.get("selected_plan_index")) if service else None if not service or not plan: context.user_data.clear() await update.message.reply_text("❌ Buy session expired.") await send_main_menu_by_message(update.message, user_id, lang) return if not is_valid_xui_email_value(username): await update.message.reply_text(get_text("invalid_username", lang)) return if await db.email_exists(username): await update.message.reply_text(get_text("username_exists_db", lang)) return if xui_client and xui_client.email_exists(username): await update.message.reply_text(get_text("username_exists_panel", lang)) return await process_buy_plan(update, context, username, service, plan, lang) context.user_data.clear()

async def process_buy_plan(update, context, desired_username, service, plan, lang): user_id = update.effective_user.id price = int(plan.get("price", 30)) days = int(plan.get("days", 30)) total_gb_value = int(plan.get("total_gb", 150)) total_bytes = total_gb_value * 1024**3 is_admin = await db.is_admin(user_id) if not is_admin: balance = await db.get_balance(user_id) if balance < price: await update.message.reply_text(get_text("insufficient_balance", lang, balance=money(balance), price=money(price), need=money(price - balance)), parse_mode="Markdown") await send_main_menu_by_message(update.message, user_id, lang) return await db.update_balance(user_id, -price) await update.message.reply_text(get_text("creating_client", lang)) try: email = desired_username uuid_str = str(uuid.uuid4()) expiry_dt = datetime.utcnow() + timedelta(days=days) expiry_ms = int(expiry_dt.timestamp() * 1000) if xui_client.email_exists(email): raise Exception("Username already exists in panel.") xui_client.add_client(service["inbound_id"], email, uuid_str, total_gb=total_bytes, expiry_time=expiry_ms) await db.add_client(user_id, uuid_str, email, service["name"], service["inbound_id"], total_bytes, expiry_dt, plan["name"], days, price) link = generate_vless_link(uuid_str, email, service) await update.message.reply_photo(photo=generate_qr_bytes(link), caption=get_text("purchase_success", lang, plan=plan["name"], price=money(price), total_gb=total_gb_value, expiry=expiry_dt.strftime("%d %b %Y"), email=email, service=service["name"]), parse_mode="Markdown") await update.message.reply_text(get_text("vless_config", lang, config=html.escape(link)) + get_text("copy_fallback", lang), parse_mode="HTML", reply_markup=get_vless_copy_keyboard(link, lang)) await send_main_menu_by_message(update.message, user_id, lang) except Exception as e: logger.error(f"Buy failed: {e}") if not is_admin: await db.update_balance(user_id, price) await update.message.reply_text(f"❌ Failed: {str(e)[:600]}") await send_main_menu_by_message(update.message, user_id, lang)

async def show_balance(update, lang): if await db.is_admin(update.effective_user.id): await update.message.reply_text(get_text("admin_balance_text", lang), parse_mode="Markdown") return balance = await db.get_balance(update.effective_user.id) await update.message.reply_text(get_text("balance_text", lang, balance=money(balance)), parse_mode="Markdown")

async def show_contact(update, lang): await update.message.reply_text(get_contact_text(lang), parse_mode="Markdown", reply_markup=get_contact_keyboard(lang))

async def show_language_selector(update, current_lang): keyboard = InlineKeyboardMarkup([ [InlineKeyboardButton(get_text("lang_my", current_lang), callback_data="lang_my")], [InlineKeyboardButton(get_text("lang_th", current_lang), callback_data="lang_th")], [InlineKeyboardButton(get_text("lang_en", current_lang), callback_data="lang_en")], [InlineKeyboardButton(get_text("back", current_lang), callback_data="menu_back")], ]) await update.message.reply_text(get_text("select_lang", current_lang), reply_markup=keyboard)

async def start_topup(update, lang): keyboard = [[InlineKeyboardButton(f"💵 {money(a)}", callback_data=f"topup_amt_{a}")] for a in CONFIG.get("TOPUP_AMOUNTS", [30, 60, 90, 300, 500])] keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")]) await update.message.reply_text(get_text("select_amount", lang), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_account_service_menu(update, lang): user_id = update.effective_user.id clients = await db.get_clients(user_id) if not clients: await update.message.reply_text(get_text("no_active_plan", lang), parse_mode="Markdown") return keyboard = [] for idx, svc in enumerate(CONFIG.get("SERVICES", [])): count = len([c for c in clients if c["service_name"] == svc["name"]]) keyboard.append([InlineKeyboardButton(f"{svc['name']} ({count})", callback_data=f"accsvc_{idx}")]) keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")]) await update.message.reply_text(get_text("account_info", lang, count=len(clients)), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_account_service_configs(query, context, service_index): user_id = query.from_user.id lang = await db.get_user_lang(user_id) service = get_service_by_index(service_index) if not service: await query.answer("Service not found.", show_alert=True) return clients = await db.get_clients_by_service(user_id, service["name"]) if not clients: await query.message.reply_text(get_text("no_active_plan", lang), parse_mode="Markdown") return online_emails = xui_client.get_online_emails() if xui_client else None await query.message.reply_text(f"📡 {service['name']}\n📦 Configs: {len(clients)}", parse_mode="Markdown") for idx, client in enumerate(clients, start=1): await send_one_client(query.message, client, lang, idx, online_emails, with_qr=True, with_config=True)

async def send_one_client(message, client, lang, idx=1, online_emails=None, with_qr=False, with_config=False): traffic = xui_client.get_client_traffic(client["email"]) if xui_client else {} down = int(traffic.get("downlink", client.get("download_used", 0)) or 0) up = int(traffic.get("uplink", client.get("upload_used", 0)) or 0) await db.update_client_usage_by_email(client["email"], down, up) await message.reply_text(f"{get_text('config_header', lang, idx=idx)}\n{build_client_status_text(client, traffic, lang, online_emails)}", parse_mode="Markdown", reply_markup=get_config_action_keyboard(client["rowid"], lang)) if with_qr: try: svc = get_service_config(client["service_name"]) if svc: link = generate_vless_link(client["uuid"], client["email"], svc) await message.reply_photo(photo=generate_qr_bytes(link), caption=f"📱 QR: {client['email']}", parse_mode="Markdown") except Exception as e: logger.warning(f"QR failed: {e}") if with_config: await send_client_config_block(message, client, lang)

async def start_topup_from_callback(query, context, amount): user_id = query.from_user.id lang = await db.get_user_lang(user_id) banks = await db.get_banks() if not banks: try: await query.message.delete() except Exception: pass await context.bot.send_message(query.message.chat.id, get_text("no_banks", lang)) await send_main_menu_to_chat(context, query.message.chat.id, user_id, lang) return context.user_data.clear() context.user_data["state"] = "topup_slip" context.user_data["topup_amount"] = amount try: await query.message.delete() except Exception: pass await context.bot.send_message(chat_id=query.message.chat.id, text=get_text("topup_prompt", lang, amount=money(amount)), parse_mode="Markdown") for bank in banks: caption = get_text("bank_caption", lang, name=bank["name"], number=bank["number"], holder=bank["holder"], amount=money(amount)) if bank.get("qr_file_id"): await context.bot.send_photo(chat_id=query.message.chat.id, photo=bank["qr_file_id"], caption=caption, parse_mode="Markdown") elif bank.get("qr_url"): await context.bot.send_photo(chat_id=query.message.chat.id, photo=bank["qr_url"], caption=caption, parse_mode="Markdown") else: await context.bot.send_message(chat_id=query.message.chat.id, text=caption, parse_mode="Markdown") await context.bot.send_message(chat_id=query.message.chat.id, text=get_text("send_slip", lang), parse_mode="Markdown")

async def receive_slip(update, context): user_id = update.effective_user.id lang = await db.get_user_lang(user_id) if not update.message.photo: await update.message.reply_text("❌ Please send slip photo.") return amount = context.user_data.get("topup_amount") if not amount: context.user_data.clear() await update.message.reply_text(get_text("cancel", lang)) await send_main_menu_by_message(update.message, user_id, lang) return file_id = update.message.photo[-1].file_id topup_id = await db.create_topup(user_id, amount, file_id) await update.message.reply_text(get_text("topup_sent", lang, amount=money(amount))) await send_main_menu_by_message(update.message, user_id, lang) keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{topup_id}"), InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{topup_id}")]]) mention = f"{update.effective_user.full_name}" try: await context.bot.send_photo(chat_id=CONFIG["ADMIN_ID"], photo=file_id, caption=f"🔔 New Top-up Request\n\n👤 User: {mention}\n🆔 User ID: {user_id}\n💵 Amount: {money(amount)}\n🆔 Request ID: {topup_id}", reply_markup=keyboard, parse_mode="Markdown") except Exception as e: logger.warning(f"Cannot notify admin: {e}") context.user_data.clear()

================= Admin =================

async def show_admin_panel(update, lang): keyboard = [ [InlineKeyboardButton(get_text("admin_dashboard", lang), callback_data="admin_dashboard")], [InlineKeyboardButton(get_text("admin_edit_prices", lang), callback_data="admin_edit_prices")], [InlineKeyboardButton(get_text("admin_edit_topup", lang), callback_data="admin_edit_topup")], [InlineKeyboardButton(get_text("admin_add_bank", lang), callback_data="admin_addbank")], [InlineKeyboardButton(get_text("admin_pending_topups", lang), callback_data="admin_pending")], [InlineKeyboardButton(get_text("admin_manage_banks", lang), callback_data="admin_listbanks")], [InlineKeyboardButton(get_text("admin_broadcast", lang), callback_data="admin_broadcast")], [InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")], ] await update.message.reply_text("⚙️ Admin Panel", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_admin_dashboard(message, context, lang): users = await db.get_all_users() clients = await db.get_all_clients() online_emails = xui_client.get_online_emails() if xui_client else set() online_count = len([c for c in clients if is_client_online(c, online_emails)]) offline_count = max(0, len(clients) - online_count) keyboard = InlineKeyboardMarkup([ [InlineKeyboardButton(f"👥 Total Users ({len(users)})", callback_data="dash_total")], [InlineKeyboardButton(f"🟢 Total Online ({online_count})", callback_data="dash_online")], [InlineKeyboardButton(f"⚪ Total Offline ({offline_count})", callback_data="dash_offline")], [InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")], ]) await message.reply_text(get_text("admin_stats", lang, total_users=len(users), online=online_count, offline=offline_count, total_configs=len(clients)), reply_markup=keyboard, parse_mode="Markdown")

async def show_dashboard_clients(query, context, mode): user_id = query.from_user.id lang = await db.get_user_lang(user_id) if not await db.is_admin(user_id): await query.answer("Admin only.", show_alert=True) return clients = await db.get_all_clients() online_emails = xui_client.get_online_emails() if xui_client else set() if mode == "online": clients = [c for c in clients if is_client_online(c, online_emails)] title = "🟢 Online Configs" elif mode == "offline": clients = [c for c in clients if not is_client_online(c, online_emails)] title = "⚪ Offline Configs" else: title = "👥 All User Configs" if not clients: await query.message.reply_text("📭 No configs found.") return await query.message.reply_text(f"{title}: {len(clients)}", parse_mode="Markdown") for idx, client in enumerate(clients, start=1): await send_one_client(query.message, client, lang, idx, online_emails, with_qr=False, with_config=False)

async def show_pending_topups(query, context, lang): pending = await db.get_pending_topups() if not pending: await query.message.reply_text(get_text("no_pending_topups", lang)) return await query.message.reply_text(f"📋 Pending TopUps: {len(pending)}") for req in pending: keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{req['id']}"), InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{req['id']}")]]) caption = f"🔔 Pending Top-up\n\n🆔 ID: {req['id']}\n👤 User ID: {req['user_id']}\n💵 Amount: {money(req['amount'])}\n📅 Created: {req['created_at']}" if req.get("slip_file_id"): await context.bot.send_photo(chat_id=query.message.chat.id, photo=req["slip_file_id"], caption=caption, reply_markup=keyboard, parse_mode="Markdown") else: await context.bot.send_message(chat_id=query.message.chat.id, text=caption, reply_markup=keyboard, parse_mode="Markdown")

async def manage_banks(query, lang): banks = await db.get_banks() keyboard = [] for bank in banks: keyboard.append([InlineKeyboardButton(f"✏️ Edit {bank['name']}", callback_data=f"editbank_{bank['id']}"), InlineKeyboardButton("❌ Delete", callback_data=f"delbank_{bank['id']}")]) keyboard.append([InlineKeyboardButton(get_text("admin_add_bank", lang), callback_data="admin_addbank")]) keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")]) await query.message.reply_text("🏦 Manage Banks", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_admin_edit_prices(query, lang): keyboard = [] for sidx, svc in enumerate(CONFIG.get("SERVICES", [])): keyboard.append([InlineKeyboardButton(svc["name"], callback_data=f"editprice_svc_{sidx}")]) keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")]) await query.message.reply_text("💵 Select service to edit price:", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_admin_edit_plan_list(query, lang, service_index): svc = get_service_by_index(service_index) if not svc: await query.answer("Service not found.", show_alert=True) return keyboard = [] for pidx, plan in enumerate(svc.get("plans", [])): keyboard.append([InlineKeyboardButton(f"{plan['name']} | {money(plan['price'])} | {plan['days']} days | {plan['total_gb']} GB", callback_data=f"editplan_{service_index}_{pidx}")]) keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")]) await query.message.reply_text("📦 Select package to edit:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_edit_plan_values(update, context): user_id = update.effective_user.id lang = await db.get_user_lang(user_id) if not await db.is_admin(user_id): context.user_data.clear() await update.message.reply_text("❌ Admin only.") return text = (update.message.text or "").strip() try: parts = [int(x.strip()) for x in text.split(",")] if len(parts) != 3: raise ValueError price, days, total_gb = parts if price < 0 or days <= 0 or total_gb <= 0: raise ValueError except Exception: await update.message.reply_text(get_text("edit_plan_prompt", lang), parse_mode="Markdown") return sidx = context.user_data["edit_service_index"] pidx = context.user_data["edit_plan_index"] CONFIG["SERVICES"][sidx]["plans"][pidx]["price"] = price CONFIG["SERVICES"][sidx]["plans"][pidx]["days"] = days CONFIG["SERVICES"][sidx]["plans"][pidx]["total_gb"] = total_gb save_config() context.user_data.clear() await update.message.reply_text(f"✅ Updated plan.\n💵 Price: {money(price)}\n📅 Days: {days}\n📊 Limit: {total_gb} GB") await send_main_menu_by_message(update.message, user_id, lang)

async def handle_edit_topup_amounts(update, context): user_id = update.effective_user.id lang = await db.get_user_lang(user_id) if not await db.is_admin(user_id): context.user_data.clear() await update.message.reply_text("❌ Admin only.") return text = (update.message.text or "").strip() try: amounts = [int(x.strip()) for x in text.split(",") if x.strip()] if not amounts or any(a <= 0 for a in amounts): raise ValueError except Exception: await update.message.reply_text(get_text("edit_topup_prompt", lang), parse_mode="Markdown") return CONFIG["TOPUP_AMOUNTS"] = amounts save_config() context.user_data.clear() await update.message.reply_text("✅ TopUp prices updated:\n" + "\n".join([f"• {money(a)}" for a in amounts])) await send_main_menu_by_message(update.message, user_id, lang)

async def handle_admin_note(update, context): admin_id = update.effective_user.id lang = await db.get_user_lang(admin_id) data = context.user_data.get("admin_action") if not data: context.user_data.clear() await update.message.reply_text("Session expired.") return note = None if (update.message.text or "").strip() == "/skip" else (update.message.text or "").strip() topup_id = data["topup_id"] action = data["action"] topup = await db.get_topup(topup_id) if not topup or topup["status"] != "pending": context.user_data.clear() await update.message.reply_text("Already processed.") return user_lang = await db.get_user_lang(topup["user_id"]) if action == "approve": await db.update_topup_status(topup_id, "approved") await db.update_balance(topup["user_id"], topup["amount"]) msg = get_text("topup_approved", user_lang, amount=money(topup["amount"])) if note: msg += f"\n📝 Admin Note: {note}" try: await context.bot.send_message(topup["user_id"], msg) except Exception: pass await update.message.reply_text(f"✅ Top-up {money(topup['amount'])} approved.\n👤 User ID: {topup['user_id']}", parse_mode="Markdown") else: await db.update_topup_status(topup_id, "cancelled") msg = get_text("topup_cancelled", user_lang, amount=money(topup["amount"])) if note: msg += f"\n📝 Admin Note: {note}" try: await context.bot.send_message(topup["user_id"], msg) except Exception: pass await update.message.reply_text(f"❌ Top-up {money(topup['amount'])} cancelled.\n👤 User ID: {topup['user_id']}", parse_mode="Markdown") context.user_data.clear() await send_main_menu_by_message(update.message, admin_id, lang)

async def handle_bank_qr(update, context): user_id = update.effective_user.id lang = await db.get_user_lang(user_id) text = (update.message.text or "").strip() if update.message.text else "" qr_file_id = None qr_url = None if update.message.photo: qr_file_id = update.message.photo[-1].file_id elif text == "/skip": pass elif text.startswith(("http://", "https://")): qr_url = text else: await update.message.reply_text("❌ Send photo, URL, or /skip.") return await db.add_bank(context.user_data["bank_name"], context.user_data["bank_number"], context.user_data["bank_holder"], qr_file_id, qr_url) context.user_data.clear() await update.message.reply_text(get_text("bank_added", lang)) await send_main_menu_by_message(update.message, user_id, lang)

async def handle_edit_bank_qr(update, context): user_id = update.effective_user.id lang = await db.get_user_lang(user_id) bank_id = context.user_data["edit_bank_id"] bank = context.user_data["edit_bank"] qr_file_id = bank.get("qr_file_id") qr_url = bank.get("qr_url") text = (update.message.text or "").strip() if update.message.text else "" if update.message.photo: qr_file_id = update.message.photo[-1].file_id qr_url = None elif text.startswith(("http://", "https://")): qr_url = text qr_file_id = None elif text == "/skip": pass else: await update.message.reply_text("❌ Send photo, URL, or /skip.") return await db.update_bank(bank_id, context.user_data["edit_bank_name"], context.user_data["edit_bank_number"], context.user_data["edit_bank_holder"], qr_file_id, qr_url) context.user_data.clear() await update.message.reply_text(get_text("bank_updated", lang)) await send_main_menu_by_message(update.message, user_id, lang)

async def handle_broadcast(update, context): user_id = update.effective_user.id if not await db.is_admin(user_id): context.user_data.clear() await update.message.reply_text("❌ Admin only.") return text = update.message.text users = await db.get_all_users() await update.message.reply_text(get_text("broadcast_sending", "en")) sent = failed = 0 for user in users: try: await context.bot.send_message(user["user_id"], text) sent += 1 except Exception: failed += 1 context.user_data.clear() await update.message.reply_text(get_text("broadcast_result", "en", sent=sent, failed=failed)) await send_main_menu_by_message(update.message, user_id)

================= Callback =================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query data = query.data or "" user_id = query.from_user.id lang = await db.get_user_lang(user_id)

if data == "copy_not_supported":
    await query.answer(get_text("copy_not_supported_alert", lang), show_alert=True)
    return
await query.answer()

if data == "menu_back":
    context.user_data.clear()
    try:
        await query.message.delete()
    except Exception:
        pass
    await send_main_menu_to_chat(context, query.message.chat.id, user_id, lang)
    return

if data.startswith("lang_"):
    code = data.split("_")[1]
    await db.set_user_lang(user_id, code)
    context.user_data.clear()
    try:
        await query.message.delete()
    except Exception:
        pass
    await send_main_menu_to_chat(context, query.message.chat.id, user_id, code)
    return

if data.startswith("service_"):
    await show_plan_selection_from_service(query, context, int(data.split("_")[1]))
    return

if data.startswith("buyplan_"):
    _, service_index_s, plan_index_s = data.split("_")
    await start_buy_plan_from_plan(query, context, int(service_index_s), int(plan_index_s))
    return

if data.startswith("accsvc_"):
    await show_account_service_configs(query, context, int(data.split("_")[1]))
    return

if data.startswith("topup_amt_"):
    await start_topup_from_callback(query, context, int(data.split("_")[2]))
    return

if data.startswith("delcfg_"):
    row_id = int(data.split("_")[1])
    client = await db.get_client_by_row_id(row_id)
    if not client:
        await query.answer(get_text("no_active_plan", lang), show_alert=True)
        return
    if client["user_id"] != user_id and not await db.is_admin(user_id):
        await query.answer("Not allowed.", show_alert=True)
        return
    await query.edit_message_reply_markup(reply_markup=get_delete_confirm_keyboard(row_id, lang))
    return

if data.startswith("canceldelcfg_"):
    row_id = int(data.split("_")[1])
    await query.edit_message_reply_markup(reply_markup=get_config_action_keyboard(row_id, lang))
    return

if data.startswith("confirmdelcfg_"):
    row_id = int(data.split("_")[1])
    client = await db.get_client_by_row_id(row_id)
    if not client:
        await query.answer(get_text("no_active_plan", lang), show_alert=True)
        return
    if client["user_id"] != user_id and not await db.is_admin(user_id):
        await query.answer("Not allowed.", show_alert=True)
        return
    try:
        if xui_client:
            xui_client.delete_client(client["uuid"], inbound_id=client["inbound_id"], email=client["email"])
        await db.delete_client_by_row_id(row_id)
        await query.edit_message_text(get_text("config_deleted", lang, email=client["email"], uuid=client["uuid"]), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Delete config failed: {e}")
        await query.edit_message_text(get_text("delete_failed", lang, error=str(e)[:300]), parse_mode="Markdown")
    return

if data.startswith("approve_") or data.startswith("cancel_"):
    if not await db.is_admin(user_id):
        await query.answer("Admin only.", show_alert=True)
        return
    action, topup_id_s = data.split("_")
    context.user_data.clear()
    context.user_data["state"] = "admin_note"
    context.user_data["admin_action"] = {"action": action, "topup_id": int(topup_id_s)}
    await query.message.reply_text(get_text("admin_note", lang))
    return

if not await db.is_admin(user_id):
    await query.answer("Admin only.", show_alert=True)
    return

if data == "admin_dashboard":
    await show_admin_dashboard(query.message, context, lang)
elif data == "dash_total":
    await show_dashboard_clients(query, context, "total")
elif data == "dash_online":
    await show_dashboard_clients(query, context, "online")
elif data == "dash_offline":
    await show_dashboard_clients(query, context, "offline")
elif data == "admin_edit_prices":
    await show_admin_edit_prices(query, lang)
elif data.startswith("editprice_svc_"):
    await show_admin_edit_plan_list(query, lang, int(data.split("_")[2]))
elif data.startswith("editplan_"):
    _, sidx_s, pidx_s = data.split("_")
    context.user_data.clear()
    context.user_data["state"] = "edit_plan_values"
    context.user_data["edit_service_index"] = int(sidx_s)
    context.user_data["edit_plan_index"] = int(pidx_s)
    await query.message.reply_text(get_text("edit_plan_prompt", lang), parse_mode="Markdown")
elif data == "admin_edit_topup":
    context.user_data.clear()
    context.user_data["state"] = "edit_topup_amounts"
    await query.message.reply_text(get_text("edit_topup_prompt", lang), parse_mode="Markdown")
elif data == "admin_addbank":
    context.user_data.clear()
    context.user_data["state"] = "bank_name"
    await query.message.reply_text(get_text("bank_name_prompt", lang))
elif data == "admin_pending":
    await show_pending_topups(query, context, lang)
elif data == "admin_listbanks":
    await manage_banks(query, lang)
elif data == "admin_broadcast":
    context.user_data.clear()
    context.user_data["state"] = "broadcast"
    await query.message.reply_text(get_text("broadcast_prompt", lang))
elif data.startswith("delbank_"):
    await db.delete_bank(int(data.split("_")[1]))
    await query.answer("Bank deleted.")
    await manage_banks(query, lang)
elif data.startswith("editbank_"):
    bank_id = int(data.split("_")[1])
    bank = await db.get_bank(bank_id)
    if not bank:
        await query.answer("Bank not found.", show_alert=True)
        return
    context.user_data.clear()
    context.user_data["state"] = "edit_bank_name"
    context.user_data["edit_bank_id"] = bank_id
    context.user_data["edit_bank"] = bank
    await query.message.reply_text(f"✏️ Editing bank: {bank['name']}\n\nEnter new name, or /skip:")

================= Main =================

def main(): global xui_client kill_old_bot() ensure_config() try: xui_client = XUIClient(CONFIG["PANEL_URL"], CONFIG["PANEL_USER"], CONFIG["PANEL_PASS"]) logger.info(f"Connected to X-UI panel. API base: {xui_client.base_url}") except Exception as e: logger.error(f"X-UI login failed: {e}") print("\n❌ X-UI Login failed.") print("Check PANEL_URL, PANEL_USER, PANEL_PASS, panel path.") print(f"Error: {e}\n") sys.exit(1) try: app = Application.builder().token(CONFIG["BOT_TOKEN"]).build() except Exception as e: logger.error(f"Telegram app failed: {e}") print("\n❌ BOT_TOKEN invalid.") print(f"Error: {e}\n") sys.exit(1) app.add_handler(CommandHandler("start", start)) app.add_handler(CommandHandler("cancel", cancel)) app.add_handler(CallbackQueryHandler(callback_handler)) app.add_handler(MessageHandler(filters.PHOTO, handle_photo)) app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)) logger.info("Bot started.") print("\n✅ Bot started successfully.") print("Open Telegram and press /start.\n") app.run_polling(allowed_updates=Update.ALL_TYPES)

if name == "main": main()
