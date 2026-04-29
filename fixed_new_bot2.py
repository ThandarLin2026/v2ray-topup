#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import html
import io
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from functools import partial
from urllib.parse import quote

# ================= Dependency =================

def install_dependencies():
    packages = [
        ("requests", "requests"),
        ("telegram", "python-telegram-bot"),
        ("qrcode", "qrcode[pil]"),
        ("PIL", "pillow"),
    ]
    for module_name, package_name in packages:
        try:
            __import__(module_name)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])

install_dependencies()

import requests
import qrcode

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
except Exception:
    CopyTextButton = None
    HAS_COPY_TEXT_BUTTON = False

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================= Logging =================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("fixed_v2ray_bot")

# ================= Config =================

CONFIG_FILE = "config.json"
DB_FILE = "bot_data.db"
PID_FILE = "bot.pid"

DEFAULT_CONFIG = {
    "BOT_TOKEN": "",
    "ADMIN_ID": 0,
    "PANEL_URL": "",
    "PANEL_USER": "",
    "PANEL_PASS": "",
    "INBOUND_ID": 0,
    "PORT": 0,
    "WS_PATH": "/",
    "SERVER_ADDRESS": "",
    "WS_HOST": "",
    "CONTACT_USERNAME": "@Juevpn",
    "START_MESSAGE_MY": (
        "V2RAY X-UI PANEL မှာကြိုဆိုပါတယ်\n"
        "AIS 10 စမတ်\n"
        "*777*7067# 29 ဘတ်စမတ်\n"
        "*777*7068# 34 ဘတ်စမတ်\n"
        "V2BOX IOS ANDROID စတာတွေနဲ့သုံးနိုင်ပါတယ်"
    ),
    "START_MESSAGE_EN": "Welcome to V2RAY X-UI PANEL",
    "START_MESSAGE_TH": "ยินดีต้อนรับสู่ V2RAY X-UI PANEL",
}

CONFIG = DEFAULT_CONFIG.copy()

def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2, ensure_ascii=False)

def load_config():
    global CONFIG
    if not os.path.exists(CONFIG_FILE):
        return False
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update(loaded)
        CONFIG = merged
        return True
    except Exception as e:
        logger.error(f"Cannot load config.json: {e}")
        return False

def config_is_valid():
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
        if CONFIG.get(key) in ("", 0, None):
            logger.error(f"Missing config: {key}")
            return False

    if ":" not in str(CONFIG["BOT_TOKEN"]):
        logger.error("BOT_TOKEN format is wrong.")
        return False

    if not str(CONFIG["PANEL_URL"]).startswith(("http://", "https://")):
        logger.error("PANEL_URL must start with http:// or https://")
        return False

    return True

def get_config():
    print("\n🔧 First-time configuration\n")
    CONFIG["BOT_TOKEN"] = input("Enter Bot Token: ").strip()
    CONFIG["ADMIN_ID"] = int(input("Enter Admin Telegram ID: ").strip())
    CONFIG["PANEL_URL"] = input("Enter X-UI Panel URL: ").strip().rstrip("/")
    CONFIG["PANEL_USER"] = input("Enter Panel Username: ").strip()
    CONFIG["PANEL_PASS"] = input("Enter Panel Password: ").strip()
    CONFIG["INBOUND_ID"] = int(input("Enter Inbound ID: ").strip())
    CONFIG["PORT"] = int(input("Enter VLESS Port: ").strip())

    ws_path = input("Enter WS Path [default: /]: ").strip()
    CONFIG["WS_PATH"] = ws_path if ws_path else "/"

    CONFIG["SERVER_ADDRESS"] = input("Enter Server Address / Domain for config link: ").strip()
    CONFIG["WS_HOST"] = input("Enter WS Host / Domain: ").strip()

    contact = input("Enter Contact Username [default: @Juevpn]: ").strip()
    if contact:
        CONFIG["CONTACT_USERNAME"] = contact

    save_config()
    print(f"\n✅ Saved to {CONFIG_FILE}\n")

def ensure_config():
    loaded = load_config()
    if loaded and config_is_valid():
        logger.info("config.json loaded.")
        return

    print("\n⚠️ config.json not found or incomplete.\n")

    if sys.stdin.isatty():
        get_config()
        if not config_is_valid():
            print("❌ Config invalid. Please check config.json.")
            sys.exit(1)
        return

    print("❌ Run manually first: python3 bot.py")
    sys.exit(1)

def kill_old_bot():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            if old_pid != os.getpid():
                try:
                    os.kill(old_pid, 0)
                    os.kill(old_pid, 9)
                    logger.info(f"Killed old process: {old_pid}")
                except Exception:
                    pass
        except Exception:
            pass

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

# ================= Text =================

TEXTS = {
    "en": {
        "buy_plan": "🛒 Buy Plan",
        "topup": "💰 TopUp",
        "account": "👤 Account",
        "balance": "💰 Balance",
        "contact": "📞 Contact",
        "admin_panel": "⚙️ Admin Panel",
        "language": "🌐 Language",
        "back": "🔙 Back",
        "main_menu": "🏠 Main Menu",
        "select_plan": "📦 *Select a plan*",
        "select_amount": "💰 *Select top-up amount*",
        "enter_username": (
            "👤 Please send username for this config.\n\n"
            "Allowed: `A-Z a-z 0-9 _ . -`\n"
            "Example: `mgmg123`\n\n"
            "Use /cancel to stop."
        ),
        "invalid_username": (
            "❌ Invalid username.\n"
            "Only A-Z a-z 0-9 _ . - allowed.\n"
            "Length 3 to 32 characters."
        ),
        "username_exists_db": "❌ This username is already used in bot database.",
        "username_exists_panel": "❌ This username already exists in X-UI panel.",
        "insufficient_balance": (
            "❌ *Insufficient balance*\n\n"
            "💰 Balance: *{balance} THB*\n"
            "📦 Price: *{price} THB*\n"
            "➕ Need: *{need} THB*"
        ),
        "creating_client": "⏳ Creating VLESS client...",
        "purchase_success": (
            "✅ *Plan Purchased Successfully!*\n\n"
            "📦 Plan: *{plan}*\n"
            "📅 Expires: {expiry}\n"
            "👤 Username: `{email}`\n"
            "🏷 Remark: `{email}`"
        ),
        "vless_config": "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        "copy_fallback": "\n\n📋 Long press config to copy.",
        "copy_btn": "📋 Copy VLESS",
        "copy_not_supported_alert": "Long press config text to copy.",
        "account_info": "👤 *Account Information*\n\n📦 Total Configs: *{count}*",
        "no_active_plan": "👤 *Account Information*\n\n📡 No active plan.",
        "config_header": "━━━━━━ Config {idx} ━━━━━━",
        "config_status": (
            "📦 Plan: *{plan}*\n"
            "👤 Username: `{email}`\n"
            "📅 Expiry: {expiry}\n"
            "{status_emoji} Status: *{status}*\n\n"
            "📊 *Traffic*\n"
            "📥 Download: `{down}`\n"
            "📤 Upload: `{up}`\n"
            "💾 Used: `{used} / {limit} GB` ({percent:.1f}%)\n\n"
            "🔑 UUID: `{uuid}`"
        ),
        "balance_text": "💰 *Your balance:* `{balance} THB`",
        "topup_prompt": (
            "💰 *Top-up Amount:* `{amount} THB`\n\n"
            "🏦 Transfer to one bank account below, then send slip photo."
        ),
        "bank_caption": (
            "🏦 *{name}*\n"
            "💳 `{number}`\n"
            "👤 {holder}\n\n"
            "💵 Amount: *{amount} THB*"
        ),
        "send_slip": "📸 Send payment slip photo.\nUse /cancel to stop.",
        "topup_sent": "✅ Top-up request for {amount} THB sent to admin.",
        "topup_approved": "✅ Your top-up of {amount} THB has been approved.",
        "topup_cancelled": "❌ Your top-up request of {amount} THB was cancelled.",
        "contact_text": "📞 Contact Support\n\nTelegram: {username}",
        "contact_btn": "📩 Open Contact",
        "admin_add_bank": "➕ Add Bank",
        "admin_pending_topups": "📋 Pending TopUps",
        "admin_manage_banks": "🏦 Manage Banks",
        "admin_broadcast": "📢 Broadcast",
        "bank_name_prompt": "🏦 Enter bank name:",
        "bank_number_prompt": "💳 Enter account number:",
        "bank_holder_prompt": "👤 Enter account holder:",
        "bank_qr_prompt": "📷 Send QR photo, image URL, or /skip.",
        "bank_added": "✅ Bank added.",
        "bank_updated": "✅ Bank updated.",
        "no_banks": "ℹ️ No bank accounts.",
        "no_pending_topups": "📭 No pending topups.",
        "admin_note": "📝 Enter note for user, or /skip.",
        "cancel": "↩️ Cancelled.",
        "back_to_menu": "↩️ Back to main menu.",
        "confirm_delete": "🗑 Delete Config?",
        "delete_confirm_btn": "✅ Confirm Delete",
        "delete_cancel_btn": "❌ Cancel",
        "config_deleted": "✅ *Config deleted successfully*\n\n👤 Username: `{email}`\n🔑 UUID: `{uuid}`",
        "delete_failed": "❌ Failed to delete config.\n\nError: `{error}`",
        "select_lang": "🌐 Please select language:",
        "lang_my": "🇲🇲 Myanmar",
        "lang_th": "🇹🇭 Thai",
        "lang_en": "🇬🇧 English",
        "lang_changed": "✅ Language changed to {lang}.",
        "broadcast_prompt": "📢 Send message to broadcast.\nUse /cancel to stop.",
        "broadcast_sending": "⏳ Broadcasting...",
        "broadcast_result": "✅ Broadcast finished.\n\n📤 Sent: {sent}\n❌ Failed: {failed}",
    },
    "my": {
        "buy_plan": "🛒 အစီအစဉ်ဝယ်ရန်",
        "topup": "💰 ငွေဖြည့်ရန်",
        "account": "👤 အကောင့်",
        "balance": "💰 လက်ကျန်ငွေ",
        "contact": "📞 ဆက်သွယ်ရန်",
        "admin_panel": "⚙️ အက်ဒမင်ဘောင်",
        "language": "🌐 ဘာသာစကား",
        "back": "🔙 နောက်သို့",
        "main_menu": "🏠 ပင်မမီနူး",
        "select_plan": "📦 *အစီအစဉ်တစ်ခုရွေးပါ*",
        "select_amount": "💰 *ငွေပမာဏရွေးပါ*",
        "enter_username": (
            "👤 ဤ config အတွက် username ပေးပို့ပါ။\n\n"
            "ခွင့်ပြုသောစာလုံးများ: `A-Z a-z 0-9 _ . -`\n"
            "ဥပမာ: `mgmg123`\n\n"
            "/cancel ဖြင့်ပယ်ဖျက်နိုင်သည်။"
        ),
        "invalid_username": (
            "❌ Username မမှန်ကန်ပါ။\n"
            "A-Z a-z 0-9 _ . - သာခွင့်ပြုသည်။\n"
            "အလျား ၃ မှ ၃၂ လုံး။"
        ),
        "username_exists_db": "❌ ဤ username ကို bot database ထဲတွင် အသုံးပြုထားပြီးဖြစ်သည်။",
        "username_exists_panel": "❌ ဤ username သည် X-UI panel ထဲတွင် ရှိပြီးဖြစ်သည်။",
        "insufficient_balance": (
            "❌ *လက်ကျန်ငွေ မလုံလောက်ပါ*\n\n"
            "💰 လက်ကျန်: *{balance} THB*\n"
            "📦 စျေးနှုန်း: *{price} THB*\n"
            "➕ လိုအပ်ငွေ: *{need} THB*"
        ),
        "creating_client": "⏳ VLESS client ဖန်တီးနေသည်...",
        "purchase_success": (
            "✅ *Plan အောင်မြင်စွာ ဝယ်ယူပြီးပါပြီ!*\n\n"
            "📦 Plan: *{plan}*\n"
            "📅 သက်တမ်းကုန်: {expiry}\n"
            "👤 Username: `{email}`\n"
            "🏷 Remark: `{email}`"
        ),
        "vless_config": "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        "copy_fallback": "\n\n📋 Config ကိုဖိထားပြီး copy ကူးပါ။",
        "copy_btn": "📋 VLESS ကူးယူရန်",
        "copy_not_supported_alert": "Config စာသားကို ဖိထားပြီး copy ကူးပါ။",
        "account_info": "👤 *အကောင့်အချက်အလက်*\n\n📦 Config အရေအတွက်: *{count}*",
        "no_active_plan": "👤 *အကောင့်အချက်အလက်*\n\n📡 Active plan မရှိသေးပါ။",
        "config_header": "━━━━━━ Config {idx} ━━━━━━",
        "config_status": (
            "📦 Plan: *{plan}*\n"
            "👤 Username: `{email}`\n"
            "📅 သက်တမ်းကုန်: {expiry}\n"
            "{status_emoji} အခြေအနေ: *{status}*\n\n"
            "📊 *Traffic*\n"
            "📥 Download: `{down}`\n"
            "📤 Upload: `{up}`\n"
            "💾 သုံးပြီး: `{used} / {limit} GB` ({percent:.1f}%)\n\n"
            "🔑 UUID: `{uuid}`"
        ),
        "balance_text": "💰 *သင့်လက်ကျန်ငွေ:* `{balance} THB`",
        "topup_prompt": (
            "💰 *ငွေဖြည့်မည့်ပမာဏ:* `{amount} THB`\n\n"
            "🏦 အောက်ပါဘဏ်တစ်ခုသို့လွှဲပြီး slip ပို့ပါ။"
        ),
        "bank_caption": (
            "🏦 *{name}*\n"
            "💳 `{number}`\n"
            "👤 {holder}\n\n"
            "💵 ပမာဏ: *{amount} THB*"
        ),
        "send_slip": "📸 ငွေလွှဲ slip ဓာတ်ပုံ ပို့ပါ။\n/cancel ဖြင့်ရပ်နိုင်သည်။",
        "topup_sent": "✅ {amount} THB ငွေဖြည့်တောင်းဆိုမှုကို admin ထံ ပို့ပြီးပါပြီ။",
        "topup_approved": "✅ သင်၏ {amount} THB ငွေဖြည့်မှုကို အတည်ပြုပြီးပါပြီ။",
        "topup_cancelled": "❌ သင်၏ {amount} THB ငွေဖြည့်တောင်းဆိုမှုကို ပယ်ဖျက်လိုက်ပါသည်။",
        "contact_text": "📞 အကူအညီလိုပါက ဆက်သွယ်ရန်\n\nTelegram: {username}",
        "contact_btn": "📩 ဆက်သွယ်ရန် ဖွင့်မည်",
        "admin_add_bank": "➕ ဘဏ်အသစ်ထည့်",
        "admin_pending_topups": "📋 ဆိုင်းငံ့ TopUp များ",
        "admin_manage_banks": "🏦 ဘဏ်များစီမံ",
        "admin_broadcast": "📢 သတင်းပို့ရန်",
        "bank_name_prompt": "🏦 ဘဏ်အမည် ရိုက်ထည့်ပါ:",
        "bank_number_prompt": "💳 အကောင့်နံပါတ် ရိုက်ထည့်ပါ:",
        "bank_holder_prompt": "👤 အကောင့်အမည် ရိုက်ထည့်ပါ:",
        "bank_qr_prompt": "📷 QR ဓာတ်ပုံ၊ ပုံ URL ပို့ပါ။ မရှိပါက /skip ပို့ပါ။",
        "bank_added": "✅ ဘဏ်အသစ် ထည့်ပြီးပါပြီ။",
        "bank_updated": "✅ ဘဏ်အချက်အလက် ပြင်ပြီးပါပြီ။",
        "no_banks": "ℹ️ ဘဏ်အကောင့် မရှိသေးပါ။",
        "no_pending_topups": "📭 ဆိုင်းငံ့ TopUp မရှိပါ။",
        "admin_note": "📝 User အတွက် note ရိုက်ပါ။ မလိုပါက /skip ပို့ပါ။",
        "cancel": "↩️ ပယ်ဖျက်လိုက်ပါပြီ။",
        "back_to_menu": "↩️ ပင်မမီနူးသို့ ပြန်သွားသည်။",
        "confirm_delete": "🗑 Config ဖျက်မည်?",
        "delete_confirm_btn": "✅ ဖျက်ရန်အတည်ပြု",
        "delete_cancel_btn": "❌ မဖျက်တော့ပါ",
        "config_deleted": "✅ *Config ကိုဖျက်ပြီးပါပြီ*\n\n👤 Username: `{email}`\n🔑 UUID: `{uuid}`",
        "delete_failed": "❌ Config ဖျက်မအောင်မြင်ပါ။\n\nအမှား: `{error}`",
        "select_lang": "🌐 ဘာသာစကားရွေးပါ:",
        "lang_my": "🇲🇲 မြန်မာ",
        "lang_th": "🇹🇭 ထိုင်း",
        "lang_en": "🇬🇧 အင်္ဂလိပ်",
        "lang_changed": "✅ ဘာသာစကားကို {lang} သို့ပြောင်းပြီးပါပြီ။",
        "broadcast_prompt": "📢 User အားလုံးသို့ ပို့မည့် message ရိုက်ပါ။\n/cancel ဖြင့်ရပ်နိုင်သည်။",
        "broadcast_sending": "⏳ သတင်းပို့နေသည်...",
        "broadcast_result": "✅ သတင်းပို့ပြီးပါပြီ။\n\n📤 ပို့ပြီး: {sent}\n❌ မပို့ရသေး: {failed}",
    },
    "th": {
        "buy_plan": "🛒 ซื้อแผน",
        "topup": "💰 เติมเงิน",
        "account": "👤 บัญชี",
        "balance": "💰 ยอดเงิน",
        "contact": "📞 ติดต่อ",
        "admin_panel": "⚙️ แอดมิน",
        "language": "🌐 ภาษา",
        "back": "🔙 กลับ",
        "main_menu": "🏠 เมนูหลัก",
        "select_plan": "📦 *เลือกแผน*",
        "select_amount": "💰 *เลือกจำนวนเงิน*",
        "enter_username": "👤 ส่ง username สำหรับ config นี้\n\nใช้ /cancel เพื่อยกเลิก",
        "invalid_username": "❌ Username ไม่ถูกต้อง",
        "username_exists_db": "❌ Username นี้ถูกใช้แล้ว",
        "username_exists_panel": "❌ Username นี้มีใน X-UI แล้ว",
        "insufficient_balance": "❌ ยอดเงินไม่พอ\nBalance: {balance} THB\nPrice: {price} THB\nNeed: {need} THB",
        "creating_client": "⏳ กำลังสร้าง VLESS client...",
        "purchase_success": "✅ ซื้อสำเร็จ\nPlan: {plan}\nExpires: {expiry}\nUsername: `{email}`",
        "vless_config": "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        "copy_fallback": "\n\n📋 กดค้างเพื่อ copy",
        "copy_btn": "📋 Copy VLESS",
        "copy_not_supported_alert": "กดค้างเพื่อ copy",
        "account_info": "👤 Account\nConfigs: {count}",
        "no_active_plan": "No active plan.",
        "config_header": "━━━━━━ Config {idx} ━━━━━━",
        "config_status": "Plan: {plan}\nUsername: `{email}`\nExpiry: {expiry}\nStatus: {status}\nUsed: `{used} / {limit} GB`\nUUID: `{uuid}`",
        "balance_text": "💰 Balance: `{balance} THB`",
        "topup_prompt": "Top-up: {amount} THB\nSend slip after transfer.",
        "bank_caption": "🏦 {name}\n💳 `{number}`\n👤 {holder}\nAmount: {amount} THB",
        "send_slip": "Send slip photo.",
        "topup_sent": "Top-up request sent.",
        "topup_approved": "Top-up approved.",
        "topup_cancelled": "Top-up cancelled.",
        "contact_text": "Contact: {username}",
        "contact_btn": "Open Contact",
        "admin_add_bank": "Add Bank",
        "admin_pending_topups": "Pending TopUps",
        "admin_manage_banks": "Manage Banks",
        "admin_broadcast": "Broadcast",
        "bank_name_prompt": "Bank name:",
        "bank_number_prompt": "Account number:",
        "bank_holder_prompt": "Account holder:",
        "bank_qr_prompt": "Send QR photo, URL, or /skip.",
        "bank_added": "Bank added.",
        "bank_updated": "Bank updated.",
        "no_banks": "No banks.",
        "no_pending_topups": "No pending topups.",
        "admin_note": "Enter note or /skip.",
        "cancel": "Cancelled.",
        "back_to_menu": "Back to menu.",
        "confirm_delete": "Delete Config?",
        "delete_confirm_btn": "Confirm",
        "delete_cancel_btn": "Cancel",
        "config_deleted": "Deleted `{email}`",
        "delete_failed": "Delete failed: `{error}`",
        "select_lang": "Select language:",
        "lang_my": "Myanmar",
        "lang_th": "Thai",
        "lang_en": "English",
        "lang_changed": "Changed to {lang}.",
        "broadcast_prompt": "Send broadcast message.",
        "broadcast_sending": "Broadcasting...",
        "broadcast_result": "Done. Sent: {sent}, Failed: {failed}",
    },
}

def get_text(key, lang="en", **kwargs):
    lang_dict = TEXTS.get(lang, TEXTS["en"])
    text = lang_dict.get(key, TEXTS["en"].get(key, key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text

# ================= Database =================

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
                    is_admin INTEGER DEFAULT 0,
                    lang TEXT DEFAULT 'my'
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

            plans = [
                ("30 DAYS 120GB", 30, 120, 40),
                ("60 DAYS 250GB", 60, 250, 70),
            ]

            for name, days, gb, price in plans:
                row = conn.execute("SELECT id FROM plans WHERE name = ?", (name,)).fetchone()
                if row:
                    conn.execute(
                        "UPDATE plans SET days=?, data_gb=?, price=? WHERE name=?",
                        (days, gb, price, name),
                    )
                else:
                    conn.execute(
                        "INSERT INTO plans (name, days, data_gb, price) VALUES (?, ?, ?, ?)",
                        (name, days, gb, price),
                    )

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
        await self.execute(
            "INSERT OR IGNORE INTO users (user_id, username, lang) VALUES (?, ?, ?)",
            (user_id, username, "my"),
        )

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

    async def get_plans(self):
        return await self.execute("SELECT * FROM plans ORDER BY price")

    async def get_plan(self, plan_id):
        rows = await self.execute("SELECT * FROM plans WHERE id=?", (plan_id,))
        return rows[0] if rows else None

    async def add_bank(self, name, number, holder, qr_file_id=None, qr_url=None):
        await self.execute(
            "INSERT INTO banks (name, number, holder, qr_file_id, qr_url) VALUES (?, ?, ?, ?, ?)",
            (name, number, holder, qr_file_id, qr_url),
        )

    async def update_bank(self, bank_id, name, number, holder, qr_file_id=None, qr_url=None):
        await self.execute(
            "UPDATE banks SET name=?, number=?, holder=?, qr_file_id=?, qr_url=? WHERE id=?",
            (name, number, holder, qr_file_id, qr_url, bank_id),
        )

    async def get_bank(self, bank_id):
        rows = await self.execute("SELECT * FROM banks WHERE id=?", (bank_id,))
        return rows[0] if rows else None

    async def get_banks(self):
        return await self.execute("SELECT * FROM banks ORDER BY id")

    async def delete_bank(self, bank_id):
        await self.execute("DELETE FROM banks WHERE id=?", (bank_id,))

    async def create_topup(self, user_id, amount, slip_file_id):
        return await self.execute(
            "INSERT INTO topup_requests (user_id, amount, slip_file_id) VALUES (?, ?, ?)",
            (user_id, amount, slip_file_id),
        )

    async def get_topup(self, topup_id):
        rows = await self.execute("SELECT * FROM topup_requests WHERE id=?", (topup_id,))
        return rows[0] if rows else None

    async def update_topup_status(self, topup_id, status):
        await self.execute("UPDATE topup_requests SET status=? WHERE id=?", (status, topup_id))

    async def get_pending_topups(self):
        return await self.execute("SELECT * FROM topup_requests WHERE status='pending' ORDER BY created_at")

    async def add_client(self, user_id, uuid_str, email, plan_id, total_gb, expiry_at):
        await self.execute(
            """
            INSERT INTO user_clients (user_id, uuid, email, plan_id, expiry_at, total_gb)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, uuid_str, email, plan_id, expiry_at.isoformat(), total_gb),
        )

    async def get_clients(self, user_id):
        return await self.execute(
            """
            SELECT uc.rowid AS row_id, uc.*, p.name AS plan_name, p.days, p.data_gb, p.price
            FROM user_clients uc
            LEFT JOIN plans p ON uc.plan_id = p.id
            WHERE uc.user_id=?
            ORDER BY uc.created_at DESC
            """,
            (user_id,),
        )

    async def get_client_by_row_id(self, row_id):
        rows = await self.execute(
            """
            SELECT uc.rowid AS row_id, uc.*, p.name AS plan_name, p.days, p.data_gb, p.price
            FROM user_clients uc
            LEFT JOIN plans p ON uc.plan_id = p.id
            WHERE uc.rowid=?
            LIMIT 1
            """,
            (row_id,),
        )
        return rows[0] if rows else None

    async def delete_client_by_row_id(self, row_id):
        await self.execute("DELETE FROM user_clients WHERE rowid=?", (row_id,))

    async def email_exists(self, email):
        rows = await self.execute(
            "SELECT email FROM user_clients WHERE LOWER(email)=LOWER(?) LIMIT 1",
            (email,),
        )
        return bool(rows)

    async def update_client_usage_by_email(self, email, down, up):
        await self.execute(
            "UPDATE user_clients SET download_used=?, upload_used=? WHERE email=?",
            (down, up, email),
        )

db = Database()

# ================= X-UI Client =================

class XUIClient:
    def __init__(self):
        self.session = requests.Session()
        self.api_inbounds_path = "/xui/API/inbounds"
        self.base_url = self._detect_api_base()

    def _try_login(self, base_url):
        url = f"{base_url.rstrip('/')}/login"
        data = {
            "username": CONFIG["PANEL_USER"],
            "password": CONFIG["PANEL_PASS"],
        }
        try:
            resp = self.session.post(url, data=data, timeout=12)
            logger.info(f"Trying panel login {url} HTTP {resp.status_code}")
            if resp.status_code != 200:
                return False

            try:
                payload = resp.json()
                if payload.get("success") is True:
                    return True
            except Exception:
                pass

            text = resp.text.lower()
            if "success" in text and "true" in text:
                return True

            return False
        except Exception as e:
            logger.warning(f"Login failed {url}: {e}")
            return False

    def _detect_api_base(self):
        panel_url = CONFIG["PANEL_URL"].rstrip("/")
        root_url = "/".join(panel_url.split("/")[:3])

        candidates = [panel_url]
        if root_url != panel_url:
            candidates.append(root_url)

        for base in candidates:
            if self._try_login(base):
                logger.info(f"API base detected: {base}")
                return base.rstrip("/")

        raise Exception("Could not login to X-UI panel.")

    def add_client(self, inbound_id, email, uuid_str, total_gb=0, expiry_time=0):
        url = f"{self.base_url}{self.api_inbounds_path}/addClient/"

        settings = {
            "clients": [
                {
                    "email": email,
                    "id": uuid_str,
                    "enable": True,
                    "flow": "",
                    "totalGB": total_gb,
                    "expiryTime": expiry_time,
                    "limitIp": 0,
                    "subId": "",
                    "tgId": "",
                    "reset": 0,
                }
            ]
        }

        data = {
            "id": inbound_id,
            "settings": json.dumps(settings),
        }

        resp = self.session.post(url, data=data, timeout=20)

        if resp.status_code != 200:
            raise Exception(f"Add client HTTP {resp.status_code}: {resp.text[:300]}")

        try:
            result = resp.json()
        except Exception:
            raise Exception(f"Add client invalid JSON: {resp.text[:300]}")

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

    def _normalize_traffic_obj(self, obj):
        if not isinstance(obj, dict):
            return {}
        return {
            "downlink": self._safe_int(obj.get("downlink", obj.get("down", obj.get("download", 0)))),
            "uplink": self._safe_int(obj.get("uplink", obj.get("up", obj.get("upload", 0)))),
            "total": self._safe_int(obj.get("total", obj.get("totalGB", obj.get("total_gb", 0)))),
            "expiryTime": self._safe_int(obj.get("expiryTime", obj.get("expiry_time", 0))),
            "enable": obj.get("enable", True),
            "email": obj.get("email", ""),
        }

    def _extract_traffic_from_list(self, email, payload):
        inbounds = payload.get("obj") or []

        for inbound in inbounds:
            stats = inbound.get("clientStats") or inbound.get("clientTraffic") or []
            if isinstance(stats, list):
                for stat in stats:
                    if str(stat.get("email", "")).lower() == email.lower():
                        return self._normalize_traffic_obj(stat)

            settings_raw = inbound.get("settings")
            if settings_raw:
                try:
                    settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
                    for client in settings.get("clients", []):
                        if str(client.get("email", "")).lower() == email.lower():
                            normalized = self._normalize_traffic_obj(client)

                            for stat in stats:
                                if str(stat.get("email", "")).lower() == email.lower():
                                    stat_n = self._normalize_traffic_obj(stat)
                                    normalized["downlink"] = stat_n["downlink"]
                                    normalized["uplink"] = stat_n["uplink"]
                                    if stat_n["total"]:
                                        normalized["total"] = stat_n["total"]
                                    if stat_n["expiryTime"]:
                                        normalized["expiryTime"] = stat_n["expiryTime"]
                                    normalized["enable"] = stat_n["enable"]

                            return normalized
                except Exception:
                    pass

        return {}

    def get_client_traffic(self, email):
        encoded = quote(email, safe="")
        urls = [
            f"{self.base_url}{self.api_inbounds_path}/getClientTraffics/{encoded}",
            f"{self.base_url}{self.api_inbounds_path}/getClientTraffics/{email}",
        ]

        for url in urls:
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success") and data.get("obj"):
                        return self._normalize_traffic_obj(data.get("obj"))
            except Exception:
                pass

        try:
            url = f"{self.base_url}{self.api_inbounds_path}/list"
            resp = self.session.get(url, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return self._extract_traffic_from_list(email, data)
        except Exception as e:
            logger.warning(f"Traffic fallback failed: {e}")

        return {}

    def email_exists(self, email):
        try:
            traffic = self.get_client_traffic(email)
            if traffic and str(traffic.get("email", "")).lower() == email.lower():
                return True
        except Exception:
            pass

        try:
            url = f"{self.base_url}{self.api_inbounds_path}/list"
            resp = self.session.get(url, timeout=20)
            if resp.status_code != 200:
                return False
            data = resp.json()
            if not data.get("success"):
                return False

            for inbound in data.get("obj") or []:
                settings_raw = inbound.get("settings")
                if settings_raw:
                    try:
                        settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
                        for client in settings.get("clients", []):
                            if str(client.get("email", "")).lower() == email.lower():
                                return True
                    except Exception:
                        pass

                stats = inbound.get("clientStats") or inbound.get("clientTraffic") or []
                for stat in stats:
                    if str(stat.get("email", "")).lower() == email.lower():
                        return True
        except Exception:
            pass

        return False

    def delete_client(self, uuid_str, inbound_id=None, email=None):
        inbound_id = inbound_id or CONFIG["INBOUND_ID"]

        candidates = [
            ("POST", f"{self.base_url}{self.api_inbounds_path}/delClient/{uuid_str}", {}),
            ("GET", f"{self.base_url}{self.api_inbounds_path}/delClient/{uuid_str}", {}),
            ("POST", f"{self.base_url}{self.api_inbounds_path}/delClient/{inbound_id}/{uuid_str}", {}),
            ("GET", f"{self.base_url}{self.api_inbounds_path}/delClient/{inbound_id}/{uuid_str}", {}),
            ("POST", f"{self.base_url}{self.api_inbounds_path}/delClient/", {"data": {"id": inbound_id, "clientId": uuid_str}}),
            ("POST", f"{self.base_url}{self.api_inbounds_path}/delClient/", {"data": {"clientId": uuid_str}}),
        ]

        if email:
            candidates.append(
                ("POST", f"{self.base_url}{self.api_inbounds_path}/delClient/", {"data": {"id": inbound_id, "email": email}})
            )

        for method, url, kwargs in candidates:
            try:
                if method == "POST":
                    resp = self.session.post(url, timeout=20, **kwargs)
                else:
                    resp = self.session.get(url, timeout=20, **kwargs)

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        if data.get("success") is True:
                            return True
                    except Exception:
                        if "success" in resp.text.lower() and "true" in resp.text.lower():
                            return True
            except Exception:
                pass

        raise Exception("Failed to delete client from X-UI panel.")

xui = None

# ================= Helpers =================

def get_welcome_text(lang):
    if lang == "my":
        return CONFIG["START_MESSAGE_MY"]
    if lang == "th":
        return CONFIG["START_MESSAGE_TH"]
    return CONFIG["START_MESSAGE_EN"]

def sanitize_username(username):
    return username.strip()

def is_valid_xui_email_value(username):
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username))

def generate_vless_link(uuid_str, remark=""):
    address = CONFIG["SERVER_ADDRESS"]
    port = CONFIG["PORT"]
    path = CONFIG.get("WS_PATH") or "/"
    ws_host = CONFIG["WS_HOST"]

    link = (
        f"vless://{uuid_str}@{address}:{port}"
        f"?path={quote(path, safe='/')}"
        f"&security=none"
        f"&encryption=none"
        f"&type=ws"
        f"&host={quote(ws_host, safe='')}"
    )

    if remark:
        link += f"#{quote(remark.replace(' ', '_'), safe='')}"

    return link

def generate_qr_bytes(data):
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio

def format_bytes(size):
    size = int(size or 0)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def get_vless_copy_keyboard(vless_link, lang):
    if HAS_COPY_TEXT_BUTTON and CopyTextButton is not None:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text("copy_btn", lang), copy_text=CopyTextButton(vless_link))]
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text("copy_btn", lang), callback_data="copy_not_supported")]
    ])

def get_config_action_keyboard(row_id, lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text("confirm_delete", lang), callback_data=f"delcfg_{row_id}")]
    ])

def get_delete_confirm_keyboard(row_id, lang):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(get_text("delete_confirm_btn", lang), callback_data=f"confirmdelcfg_{row_id}"),
            InlineKeyboardButton(get_text("delete_cancel_btn", lang), callback_data=f"canceldelcfg_{row_id}"),
        ]
    ])

def get_contact_keyboard(lang):
    username = CONFIG.get("CONTACT_USERNAME", "@Juevpn").strip()
    clean = username[1:] if username.startswith("@") else username
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text("contact_btn", lang), url=f"https://t.me/{clean}")]
    ])

def get_contact_text(lang):
    username = CONFIG.get("CONTACT_USERNAME", "@Juevpn").strip()
    if not username.startswith("@"):
        username = "@" + username
    return get_text("contact_text", lang, username=username)

def build_client_status_text(client, traffic, lang):
    download = int(traffic.get("downlink", client.get("download_used", 0)) or 0)
    upload = int(traffic.get("uplink", client.get("upload_used", 0)) or 0)
    total_used = download + upload

    panel_total = int(traffic.get("total", 0) or 0)
    total_limit_bytes = panel_total if panel_total > 0 else int(client.get("total_gb", 0) or 0)

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
        expiry_str = expiry.strftime("%d %b %Y")
        if is_expired:
            expiry_str += " (Expired)"
        else:
            expiry_str += f" ({days_left} days left)"
    else:
        is_expired = False
        expiry_str = "Unlimited"

    limit_gb = total_limit_bytes / (1024 ** 3) if total_limit_bytes > 0 else 0
    usage_percent = (total_used / total_limit_bytes * 100) if total_limit_bytes > 0 else 0
    traffic_exhausted = total_limit_bytes > 0 and total_used >= total_limit_bytes

    is_active = enabled and not is_expired and not traffic_exhausted
    status_emoji = "🟢" if is_active else "🔴"
    status_text = "Active" if is_active else "Expired"

    return get_text(
        "config_status",
        lang,
        plan=client.get("plan_name", "Unknown"),
        email=client["email"],
        expiry=expiry_str,
        status_emoji=status_emoji,
        status=status_text,
        down=format_bytes(download),
        up=format_bytes(upload),
        used=format_bytes(total_used),
        limit=f"{limit_gb:.0f}",
        percent=usage_percent,
        uuid=client["uuid"],
    )

async def get_main_keyboard(is_admin, lang):
    buttons = [
        [KeyboardButton(get_text("buy_plan", lang)), KeyboardButton(get_text("topup", lang))],
        [KeyboardButton(get_text("account", lang)), KeyboardButton(get_text("balance", lang))],
        [KeyboardButton(get_text("contact", lang)), KeyboardButton(get_text("language", lang))],
    ]
    if is_admin:
        buttons.append([KeyboardButton(get_text("admin_panel", lang))])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def send_main_menu_by_message(message, user_id, lang=None):
    if lang is None:
        lang = await db.get_user_lang(user_id)
    is_admin = await db.is_admin(user_id)
    keyboard = await get_main_keyboard(is_admin, lang)
    await message.reply_text(get_text("main_menu", lang), reply_markup=keyboard)

async def send_main_menu_to_chat(context, chat_id, user_id, lang=None):
    if lang is None:
        lang = await db.get_user_lang(user_id)
    is_admin = await db.is_admin(user_id)
    keyboard = await get_main_keyboard(is_admin, lang)
    await context.bot.send_message(chat_id, get_text("main_menu", lang), reply_markup=keyboard)

async def send_client_config_block(message_obj, client, lang):
    link = generate_vless_link(client["uuid"], client["email"])
    config_text = get_text("vless_config", lang, config=html.escape(link))
    keyboard = get_vless_copy_keyboard(link, lang)

    if HAS_COPY_TEXT_BUTTON and CopyTextButton is not None:
        await message_obj.reply_text(config_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message_obj.reply_text(
            config_text + get_text("copy_fallback", lang),
            parse_mode="HTML",
            reply_markup=keyboard,
        )

# ================= Bot Handlers =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    context.user_data.clear()

    await db.create_user(user_id, user.username or user.full_name or str(user_id))

    if int(user_id) == int(CONFIG["ADMIN_ID"]):
        await db.set_admin(user_id)

    lang = await db.get_user_lang(user_id)
    await update.message.reply_text(get_welcome_text(lang))
    await send_main_menu_by_message(update.message, user_id, lang)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)
    await update.message.reply_text(get_text("cancel", lang))
    await send_main_menu_by_message(update.message, user_id, lang)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    text = (update.message.text or "").strip() if update.message.text else ""

    await db.create_user(user_id, user.username or user.full_name or str(user_id))

    if int(user_id) == int(CONFIG["ADMIN_ID"]):
        await db.set_admin(user_id)

    lang = await db.get_user_lang(user_id)

    state = context.user_data.get("state")

    if state == "buy_username":
        await handle_buy_username(update, context)
        return

    if state == "admin_note":
        await handle_admin_note(update, context)
        return

    if state == "bank_name":
        context.user_data["bank_name"] = text
        context.user_data["state"] = "bank_number"
        await update.message.reply_text(get_text("bank_number_prompt", lang))
        return

    if state == "bank_number":
        context.user_data["bank_number"] = text
        context.user_data["state"] = "bank_holder"
        await update.message.reply_text(get_text("bank_holder_prompt", lang))
        return

    if state == "bank_holder":
        context.user_data["bank_holder"] = text
        context.user_data["state"] = "bank_qr"
        await update.message.reply_text(get_text("bank_qr_prompt", lang))
        return

    if state == "bank_qr":
        await handle_bank_qr(update, context)
        return

    if state == "edit_bank_name":
        bank = context.user_data["edit_bank"]
        context.user_data["edit_bank_name"] = bank["name"] if text == "/skip" else text
        context.user_data["state"] = "edit_bank_number"
        await update.message.reply_text("💳 Enter new account number, or /skip:")
        return

    if state == "edit_bank_number":
        bank = context.user_data["edit_bank"]
        context.user_data["edit_bank_number"] = bank["number"] if text == "/skip" else text
        context.user_data["state"] = "edit_bank_holder"
        await update.message.reply_text("👤 Enter new account holder, or /skip:")
        return

    if state == "edit_bank_holder":
        bank = context.user_data["edit_bank"]
        context.user_data["edit_bank_holder"] = bank["holder"] if text == "/skip" else text
        context.user_data["state"] = "edit_bank_qr"
        await update.message.reply_text("📷 Send new QR photo, URL, or /skip:")
        return

    if state == "edit_bank_qr":
        await handle_edit_bank_qr(update, context)
        return

    if state == "broadcast":
        await handle_broadcast(update, context)
        return

    await route_main_menu_text(update, context, text)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")

    if state == "topup_slip":
        await receive_slip(update, context)
        return

    if state == "bank_qr":
        await handle_bank_qr(update, context)
        return

    if state == "edit_bank_qr":
        await handle_edit_bank_qr(update, context)
        return

    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)
    await update.message.reply_text(get_text("main_menu", lang))
    await send_main_menu_by_message(update.message, user_id, lang)

async def route_main_menu_text(update, context, text):
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)

    if text == get_text("buy_plan", lang):
        await show_plans(update, lang)
    elif text == get_text("topup", lang):
        await start_topup(update, lang)
    elif text == get_text("account", lang):
        await show_account(update, context, lang)
    elif text == get_text("balance", lang):
        await show_balance(update, lang)
    elif text == get_text("contact", lang):
        await show_contact(update, lang)
    elif text == get_text("language", lang):
        await show_language_selector(update, lang)
    elif text == get_text("admin_panel", lang):
        if await db.is_admin(user_id):
            await show_admin_panel(update, lang)
        else:
            await send_main_menu_by_message(update.message, user_id, lang)
    else:
        await send_main_menu_by_message(update.message, user_id, lang)

async def show_balance(update, lang):
    balance = await db.get_balance(update.effective_user.id)
    await update.message.reply_text(get_text("balance_text", lang, balance=balance), parse_mode="Markdown")

async def show_contact(update, lang):
    await update.message.reply_text(
        get_contact_text(lang),
        parse_mode="Markdown",
        reply_markup=get_contact_keyboard(lang),
    )

async def show_language_selector(update, current_lang):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text("lang_my", current_lang), callback_data="lang_my")],
        [InlineKeyboardButton(get_text("lang_th", current_lang), callback_data="lang_th")],
        [InlineKeyboardButton(get_text("lang_en", current_lang), callback_data="lang_en")],
        [InlineKeyboardButton(get_text("back", current_lang), callback_data="menu_back")],
    ])
    await update.message.reply_text(get_text("select_lang", current_lang), reply_markup=keyboard)

async def show_plans(update, lang):
    plans = await db.get_plans()
    keyboard = []

    for plan in plans:
        keyboard.append([
            InlineKeyboardButton(
                f"📦 {plan['name']} • {plan['price']} THB",
                callback_data=f"buy_{plan['id']}",
            )
        ])

    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])

    await update.message.reply_text(
        get_text("select_plan", lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def start_topup(update, lang):
    amounts = [40, 70, 100]
    keyboard = [[InlineKeyboardButton(f"💵 {a} THB", callback_data=f"topup_amt_{a}")] for a in amounts]
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])

    await update.message.reply_text(
        get_text("select_amount", lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def show_account(update, context, lang):
    user_id = update.effective_user.id
    clients = await db.get_clients(user_id)

    if not clients:
        await update.message.reply_text(get_text("no_active_plan", lang), parse_mode="Markdown")
        return

    await update.message.reply_text(
        get_text("account_info", lang, count=len(clients)),
        parse_mode="Markdown",
    )

    for idx, client in enumerate(clients, start=1):
        traffic = xui.get_client_traffic(client["email"]) if xui else {}

        down = int(traffic.get("downlink", client.get("download_used", 0)) or 0)
        up = int(traffic.get("uplink", client.get("upload_used", 0)) or 0)
        await db.update_client_usage_by_email(client["email"], down, up)

        status_text = build_client_status_text(client, traffic, lang)

        await update.message.reply_text(
            f"{get_text('config_header', lang, idx=idx)}\n{status_text}",
            parse_mode="Markdown",
            reply_markup=get_config_action_keyboard(client["row_id"], lang),
        )

        try:
            link = generate_vless_link(client["uuid"], client["email"])
            qr_bytes = generate_qr_bytes(link)
            await update.message.reply_photo(
                photo=qr_bytes,
                caption=f"📱 *QR:* `{client['email']}`",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning(f"QR failed: {e}")

        await send_client_config_block(update.message, client, lang)

# ================= Buy Flow =================

async def start_buy_plan_from_callback(query, context, plan_id):
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)

    plan = await db.get_plan(plan_id)
    if not plan:
        await query.message.reply_text("❌ Plan not found.")
        return

    context.user_data.clear()
    context.user_data["state"] = "buy_username"
    context.user_data["pending_buy_plan_id"] = plan_id

    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=get_text("enter_username", lang),
        parse_mode="Markdown",
    )

async def handle_buy_username(update, context):
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)

    username = sanitize_username(text)
    plan_id = context.user_data.get("pending_buy_plan_id")

    if not plan_id:
        context.user_data.clear()
        await update.message.reply_text("❌ Buy session expired.")
        await send_main_menu_by_message(update.message, user_id, lang)
        return

    if not is_valid_xui_email_value(username):
        await update.message.reply_text(get_text("invalid_username", lang))
        return

    if await db.email_exists(username):
        await update.message.reply_text(get_text("username_exists_db", lang))
        return

    if xui and xui.email_exists(username):
        await update.message.reply_text(get_text("username_exists_panel", lang))
        return

    await process_buy_plan(update, context, plan_id, username, lang)
    context.user_data.clear()

async def process_buy_plan(update, context, plan_id, desired_username, lang):
    user_id = update.effective_user.id
    plan = await db.get_plan(plan_id)

    if not plan:
        await update.message.reply_text("❌ Plan not found.")
        await send_main_menu_by_message(update.message, user_id, lang)
        return

    is_admin = await db.is_admin(user_id)

    if not is_admin:
        balance = await db.get_balance(user_id)
        if balance < plan["price"]:
            need = plan["price"] - balance
            await update.message.reply_text(
                get_text("insufficient_balance", lang, balance=balance, price=plan["price"], need=need),
                parse_mode="Markdown",
            )
            await send_main_menu_by_message(update.message, user_id, lang)
            return
        await db.update_balance(user_id, -plan["price"])

    await update.message.reply_text(get_text("creating_client", lang))

    try:
        if not xui:
            raise Exception("X-UI is not connected.")

        email = desired_username
        uuid_str = str(uuid.uuid4())
        expiry_dt = datetime.utcnow() + timedelta(days=int(plan["days"]))
        expiry_ms = int(expiry_dt.timestamp() * 1000)
        total_bytes = int(plan["data_gb"]) * 1024 ** 3

        if xui.email_exists(email):
            raise Exception("Username already exists in panel.")

        xui.add_client(
            CONFIG["INBOUND_ID"],
            email,
            uuid_str,
            total_gb=total_bytes,
            expiry_time=expiry_ms,
        )

        await db.add_client(
            user_id=user_id,
            uuid_str=uuid_str,
            email=email,
            plan_id=plan_id,
            total_gb=total_bytes,
            expiry_at=expiry_dt,
        )

        link = generate_vless_link(uuid_str, email)
        qr_bytes = generate_qr_bytes(link)

        caption = get_text(
            "purchase_success",
            lang,
            plan=plan["name"],
            expiry=expiry_dt.strftime("%d %b %Y"),
            email=email,
        )

        await update.message.reply_photo(
            photo=qr_bytes,
            caption=caption,
            parse_mode="Markdown",
        )

        config_text = get_text("vless_config", lang, config=html.escape(link))
        keyboard = get_vless_copy_keyboard(link, lang)

        if HAS_COPY_TEXT_BUTTON and CopyTextButton is not None:
            await update.message.reply_text(config_text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await update.message.reply_text(
                config_text + get_text("copy_fallback", lang),
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        await send_main_menu_by_message(update.message, user_id, lang)

    except Exception as e:
        logger.error(f"Buy failed: {e}")

        if not is_admin:
            await db.update_balance(user_id, plan["price"])

        await update.message.reply_text(f"❌ Failed: {str(e)[:600]}")
        await send_main_menu_by_message(update.message, user_id, lang)

# ================= TopUp Flow =================

async def start_topup_from_callback(query, context, amount):
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)
    banks = await db.get_banks()

    if not banks:
        await query.message.reply_text(get_text("no_banks", lang))
        return

    context.user_data.clear()
    context.user_data["state"] = "topup_slip"
    context.user_data["topup_amount"] = amount

    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=get_text("topup_prompt", lang, amount=amount),
        parse_mode="Markdown",
    )

    for bank in banks:
        caption = get_text(
            "bank_caption",
            lang,
            name=bank["name"],
            number=bank["number"],
            holder=bank["holder"],
            amount=amount,
        )

        if bank.get("qr_file_id"):
            await context.bot.send_photo(
                chat_id=query.message.chat.id,
                photo=bank["qr_file_id"],
                caption=caption,
                parse_mode="Markdown",
            )
        elif bank.get("qr_url"):
            await context.bot.send_photo(
                chat_id=query.message.chat.id,
                photo=bank["qr_url"],
                caption=caption,
                parse_mode="Markdown",
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text=caption,
                parse_mode="Markdown",
            )

    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=get_text("send_slip", lang),
        parse_mode="Markdown",
    )

async def receive_slip(update, context):
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)

    if not update.message.photo:
        await update.message.reply_text("❌ Please send slip photo.")
        return

    amount = context.user_data.get("topup_amount")
    if not amount:
        context.user_data.clear()
        await update.message.reply_text(get_text("cancel", lang))
        await send_main_menu_by_message(update.message, user_id, lang)
        return

    file_id = update.message.photo[-1].file_id
    topup_id = await db.create_topup(user_id, amount, file_id)

    await update.message.reply_text(get_text("topup_sent", lang, amount=amount))
    await send_main_menu_by_message(update.message, user_id, lang)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{topup_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{topup_id}"),
        ]
    ])

    mention = f"[{update.effective_user.full_name}](tg://user?id={user_id})"

    try:
        await context.bot.send_photo(
            chat_id=CONFIG["ADMIN_ID"],
            photo=file_id,
            caption=(
                f"🔔 *New Top-up Request*\n\n"
                f"👤 User: {mention}\n"
                f"💵 Amount: *{amount} THB*\n"
                f"🆔 Request ID: `{topup_id}`"
            ),
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning(f"Cannot notify admin: {e}")

    context.user_data.clear()

# ================= Admin =================

async def show_admin_panel(update, lang):
    keyboard = [
        [InlineKeyboardButton(get_text("admin_add_bank", lang), callback_data="admin_addbank")],
        [InlineKeyboardButton(get_text("admin_pending_topups", lang), callback_data="admin_pending")],
        [InlineKeyboardButton(get_text("admin_manage_banks", lang), callback_data="admin_listbanks")],
        [InlineKeyboardButton(get_text("admin_broadcast", lang), callback_data="admin_broadcast")],
        [InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")],
    ]
    await update.message.reply_text("⚙️ Admin Panel", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_pending_topups(query, context, lang):
    pending = await db.get_pending_topups()

    if not pending:
        await query.message.reply_text(get_text("no_pending_topups", lang))
        return

    await query.message.reply_text(f"📋 Pending TopUps: {len(pending)}")

    for req in pending:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{req['id']}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{req['id']}"),
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
                parse_mode="Markdown",
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text=caption,
                reply_markup=keyboard,
                parse_mode="Markdown",
            )

async def manage_banks(query, lang):
    banks = await db.get_banks()
    keyboard = []

    for bank in banks:
        keyboard.append([
            InlineKeyboardButton(f"✏️ Edit {bank['name']}", callback_data=f"editbank_{bank['id']}"),
            InlineKeyboardButton("❌ Delete", callback_data=f"delbank_{bank['id']}"),
        ])

    keyboard.append([InlineKeyboardButton(get_text("admin_add_bank", lang), callback_data="admin_addbank")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])

    await query.message.reply_text(
        "🏦 *Manage Banks*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def handle_admin_note(update, context):
    admin_id = update.effective_user.id
    lang = await db.get_user_lang(admin_id)

    data = context.user_data.get("admin_action")
    if not data:
        context.user_data.clear()
        await update.message.reply_text("Session expired.")
        return

    text = (update.message.text or "").strip()
    note = None if text == "/skip" else text

    topup_id = data["topup_id"]
    action = data["action"]

    topup = await db.get_topup(topup_id)
    if not topup or topup["status"] != "pending":
        context.user_data.clear()
        await update.message.reply_text("Already processed.")
        return

    user_lang = await db.get_user_lang(topup["user_id"])

    if action == "approve":
        await db.update_topup_status(topup_id, "approved")
        await db.update_balance(topup["user_id"], topup["amount"])

        msg = get_text("topup_approved", user_lang, amount=topup["amount"])
        if note:
            msg += f"\n📝 Admin Note: {note}"

        try:
            await context.bot.send_message(topup["user_id"], msg)
        except Exception:
            pass

        await update.message.reply_text(f"✅ Top-up {topup['amount']} THB approved.")

    else:
        await db.update_topup_status(topup_id, "cancelled")

        msg = get_text("topup_cancelled", user_lang, amount=topup["amount"])
        if note:
            msg += f"\n📝 Admin Note: {note}"

        try:
            await context.bot.send_message(topup["user_id"], msg)
        except Exception:
            pass

        await update.message.reply_text(f"❌ Top-up {topup['amount']} THB cancelled.")

    context.user_data.clear()
    await send_main_menu_by_message(update.message, admin_id, lang)

async def handle_bank_qr(update, context):
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)

    text = (update.message.text or "").strip() if update.message.text else ""
    qr_file_id = None
    qr_url = None

    if update.message.photo:
        qr_file_id = update.message.photo[-1].file_id
    elif text == "/skip":
        pass
    elif text.startswith(("http://", "https://")):
        qr_url = text
    else:
        await update.message.reply_text("❌ Send photo, URL, or /skip.")
        return

    await db.add_bank(
        context.user_data["bank_name"],
        context.user_data["bank_number"],
        context.user_data["bank_holder"],
        qr_file_id,
        qr_url,
    )

    context.user_data.clear()
    await update.message.reply_text(get_text("bank_added", lang))
    await send_main_menu_by_message(update.message, user_id, lang)

async def handle_edit_bank_qr(update, context):
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)

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
        await update.message.reply_text("❌ Send photo, URL, or /skip.")
        return

    await db.update_bank(
        bank_id,
        context.user_data["edit_bank_name"],
        context.user_data["edit_bank_number"],
        context.user_data["edit_bank_holder"],
        qr_file_id,
        qr_url,
    )

    context.user_data.clear()
    await update.message.reply_text(get_text("bank_updated", lang))
    await send_main_menu_by_message(update.message, user_id, lang)

async def handle_broadcast(update, context):
    user_id = update.effective_user.id

    if not await db.is_admin(user_id):
        context.user_data.clear()
        await update.message.reply_text("❌ Admin only.")
        return

    text = update.message.text
    users = await db.get_all_users()

    await update.message.reply_text(get_text("broadcast_sending", "en"))

    sent = 0
    failed = 0

    for user in users:
        try:
            await context.bot.send_message(user["user_id"], text)
            sent += 1
        except Exception:
            failed += 1

    context.user_data.clear()

    await update.message.reply_text(get_text("broadcast_result", "en", sent=sent, failed=failed))
    await send_main_menu_by_message(update.message, user_id)

# ================= Callback =================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)

    if data == "copy_not_supported":
        await query.answer(get_text("copy_not_supported_alert", lang), show_alert=True)
        return

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

    if data.startswith("buy_"):
        plan_id = int(data.split("_")[1])
        await start_buy_plan_from_callback(query, context, plan_id)
        return

    if data.startswith("topup_amt_"):
        amount = int(data.split("_")[2])
        await start_topup_from_callback(query, context, amount)
        return

    if data.startswith("delcfg_"):
        row_id = int(data.split("_")[1])
        client = await db.get_client_by_row_id(row_id)
        if not client:
            await query.answer(get_text("no_active_plan", lang), show_alert=True)
            return

        is_admin = await db.is_admin(user_id)
        if client["user_id"] != user_id and not is_admin:
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

        is_admin = await db.is_admin(user_id)
        if client["user_id"] != user_id and not is_admin:
            await query.answer("Not allowed.", show_alert=True)
            return

        try:
            if xui:
                xui.delete_client(client["uuid"], inbound_id=CONFIG["INBOUND_ID"], email=client["email"])

            await db.delete_client_by_row_id(row_id)

            await query.edit_message_text(
                get_text("config_deleted", lang, email=client["email"], uuid=client["uuid"]),
                parse_mode="Markdown",
            )
        except Exception as e:
            await query.edit_message_text(
                get_text("delete_failed", lang, error=str(e)[:300]),
                parse_mode="Markdown",
            )
        return

    if data.startswith("approve_") or data.startswith("cancel_"):
        if not await db.is_admin(user_id):
            await query.answer("Admin only.", show_alert=True)
            return

        action, topup_id_s = data.split("_")
        context.user_data.clear()
        context.user_data["state"] = "admin_note"
        context.user_data["admin_action"] = {
            "action": action,
            "topup_id": int(topup_id_s),
        }

        try:
            await query.message.reply_text(get_text("admin_note", lang))
        except Exception:
            pass
        return

    if not await db.is_admin(user_id):
        await query.answer("Admin only.", show_alert=True)
        return

    if data == "admin_addbank":
        context.user_data.clear()
        context.user_data["state"] = "bank_name"
        await query.message.reply_text(get_text("bank_name_prompt", lang))
        return

    if data == "admin_pending":
        await show_pending_topups(query, context, lang)
        return

    if data == "admin_listbanks":
        await manage_banks(query, lang)
        return

    if data == "admin_broadcast":
        context.user_data.clear()
        context.user_data["state"] = "broadcast"
        await query.message.reply_text(get_text("broadcast_prompt", lang))
        return

    if data.startswith("delbank_"):
        bank_id = int(data.split("_")[1])
        await db.delete_bank(bank_id)
        await query.answer("Bank deleted.")
        await manage_banks(query, lang)
        return

    if data.startswith("editbank_"):
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
        return

# ================= Main =================

def main():
    global xui

    kill_old_bot()
    ensure_config()

    try:
        xui = XUIClient()
        logger.info(f"Connected to X-UI panel. API base: {xui.base_url}")
    except Exception as e:
        logger.error(f"X-UI login failed: {e}")
        print("\n❌ X-UI Login failed.")
        print("Check PANEL_URL, PANEL_USER, PANEL_PASS, panel path.")
        print(f"Error: {e}\n")
        sys.exit(1)

    try:
        app = Application.builder().token(CONFIG["BOT_TOKEN"]).build()
    except Exception as e:
        logger.error(f"Telegram app failed: {e}")
        print("\n❌ BOT_TOKEN invalid.")
        print(f"Error: {e}\n")
        sys.exit(1)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started.")
    print("\n✅ Bot started successfully.")
    print("Open Telegram and press /start.\n")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
