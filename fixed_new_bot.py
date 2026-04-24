#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Fixed Telegram VLESS Bot - Alireza0 / 3x-ui / X-UI Panel

Fixes:
- Do NOT delete config.json on every run
- Fixed dependency import check
- Better first-time config validation
- Better Telegram bot startup error handling
- Fixed /start not responding caused by broken config/token flow
- Added graceful old process cleanup
- Added safer X-UI login detection
"""

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

# ==================== Dependency Install ====================

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
            print(f"Installing missing package: {package_name}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])


install_dependencies()

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
except Exception:
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

import qrcode

# ==================== Logging ====================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("v2ray_bot")

# ==================== Config ====================

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


def load_config() -> bool:
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
        logger.error(f"Failed to load config.json: {e}")
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
            logger.error(f"Missing config value: {key}")
            return False

    token = str(CONFIG.get("BOT_TOKEN", ""))
    if ":" not in token or len(token) < 30:
        logger.error("BOT_TOKEN format looks wrong. Use token from BotFather.")
        return False

    if not str(CONFIG["PANEL_URL"]).startswith(("http://", "https://")):
        logger.error("PANEL_URL must start with http:// or https://")
        return False

    return True


def get_config():
    print("\n🔧 First-time configuration\n")

    CONFIG["BOT_TOKEN"] = input("Enter Bot Token: ").strip()
    CONFIG["ADMIN_ID"] = int(input("Enter Admin Telegram ID: ").strip())

    CONFIG["PANEL_URL"] = input("Enter X-UI Panel URL, example http://1.2.3.4:54321 or http://domain.com/panelpath: ").strip().rstrip("/")
    CONFIG["PANEL_USER"] = input("Enter Panel Username: ").strip()
    CONFIG["PANEL_PASS"] = input("Enter Panel Password: ").strip()

    CONFIG["INBOUND_ID"] = int(input("Enter Inbound ID: ").strip())
    CONFIG["PORT"] = int(input("Enter VLESS Port: ").strip())

    ws_path = input("Enter WS Path [default: /]: ").strip()
    CONFIG["WS_PATH"] = ws_path if ws_path else "/"

    CONFIG["SERVER_ADDRESS"] = input("Enter Server Address / Domain for VLESS link: ").strip()
    CONFIG["WS_HOST"] = input("Enter WebSocket Host / SNI Host: ").strip()

    contact = input("Enter Contact Username [default: @Juevpn]: ").strip()
    if contact:
        CONFIG["CONTACT_USERNAME"] = contact

    save_config()
    print(f"\n✅ Configuration saved to {CONFIG_FILE}\n")


def ensure_config():
    loaded = load_config()

    if loaded and config_is_valid():
        logger.info(f"Loaded configuration from {CONFIG_FILE}")
        return

    print(f"\n⚠️ {CONFIG_FILE} not found or incomplete.\n")

    if sys.stdin.isatty():
        get_config()
        if not config_is_valid():
            print("❌ Config is still invalid. Please delete config.json and run again.")
            sys.exit(1)
        return

    logger.error(f"{CONFIG_FILE} not found or incomplete. Run manually first: python3 bot.py")
    sys.exit(1)


# ==================== States ====================

TO_SLIP = 1
BANK_NAME, BANK_NUMBER, BANK_HOLDER, BANK_QR = range(10, 14)
ADMIN_NOTE = 20
BANK_EDIT_NAME, BANK_EDIT_NUMBER, BANK_EDIT_HOLDER, BANK_EDIT_QR = range(30, 34)
BROADCAST_TEXT = 40
BUY_USERNAME = 50

# ==================== Text ====================

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
            "❌ Invalid username.\n\n"
            "Only letters, numbers, underscore (_), dot (.), dash (-)\n"
            "Length: 3 to 32 characters."
        ),
        "username_exists_db": "❌ This username is already used in bot database.",
        "username_exists_panel": "❌ This username already exists in X-UI panel.",

        "insufficient_balance": (
            "❌ *Insufficient balance*\n\n"
            "💰 Your balance: *{balance} THB*\n"
            "📦 Plan price: *{price} THB*\n"
            "➕ Need more: *{need} THB*\n\n"
            "Please top up first."
        ),
        "creating_client": "⏳ Creating VLESS client...",
        "purchase_success": (
            "✅ *Plan Purchased Successfully!*\n\n"
            "📦 Plan: *{plan}*\n"
            "📅 Expires: {expiry}\n"
            "👤 Username: `{email}`\n"
            "🏷 Remark: `{email}`\n"
            "📱 Scan QR code to import"
        ),
        "vless_config": "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        "copy_fallback": "\n\n📋 Long press config to copy.",
        "copy_btn": "📋 Copy VLESS",
        "copy_not_supported_alert": "Long press config text to copy.",

        "account_info": "👤 *Account Information*\n\n📦 Total Configs: *{count}*",
        "no_active_plan": "👤 *Account Information*\n\n📡 Status: ⚪ No active plan",
        "config_header": "━━━━━━ Config {idx} ━━━━━━",
        "config_status": (
            "📦 Plan: *{plan}*\n"
            "👤 Username: `{email}`\n"
            "📅 Expiry: {expiry}\n"
            "{status_emoji} Status: *{status}*\n\n"
            "📊 *Traffic*\n"
            "📥 Download: `{down}`\n"
            "📤 Upload: `{up}`\n"
            "💾 Total Used: `{used} / {limit} GB` ({percent:.1f}%)\n\n"
            "🔑 UUID: `{uuid}`"
        ),

        "balance_text": "💰 *Your balance:* `{balance} THB`",
        "topup_prompt": (
            "💰 *Top-up Amount:* `{amount} THB`\n\n"
            "🏦 Please transfer to one of the bank accounts below and then send your payment slip."
        ),
        "bank_caption": (
            "🏦 *{name}*\n"
            "💳 `{number}`\n"
            "👤 {holder}\n\n"
            "💵 Amount: *{amount} THB*"
        ),
        "send_slip": "📸 *Now send the payment slip photo.*\nUse /cancel to go back.",
        "topup_sent": "✅ Top-up request for {amount} THB has been sent to admin.",
        "topup_approved": "✅ Your top-up of {amount} THB has been approved.",
        "topup_cancelled": "❌ Your top-up request of {amount} THB was cancelled.",

        "contact_text": "📞 Contact Support\n\nTelegram: {username}",
        "contact_btn": "📩 Open Contact",

        "admin_add_bank": "➕ Add Bank",
        "admin_pending_topups": "📋 Pending TopUps",
        "admin_manage_banks": "🏦 Manage Banks",
        "admin_broadcast": "📢 Broadcast Message",

        "bank_name_prompt": "🏦 Enter bank name:",
        "bank_number_prompt": "💳 Enter account number:",
        "bank_holder_prompt": "👤 Enter account holder name:",
        "bank_qr_prompt": "📷 Send QR photo, image URL, or /skip.",
        "bank_added": "✅ Bank added successfully.",
        "bank_updated": "✅ Bank updated successfully.",
        "no_banks": "ℹ️ No bank accounts available.",
        "no_pending_topups": "📭 No pending requests.",
        "pending_header": "📋 Found *{count}* pending request(s).",

        "admin_note": "📝 Enter note for user, or send /skip.",
        "cancel": "↩️ Cancelled.",
        "back_to_menu": "↩️ Back to main menu.",

        "confirm_delete": "🗑 Delete Config?",
        "delete_confirm_btn": "✅ Confirm Delete",
        "delete_cancel_btn": "❌ Cancel",
        "config_deleted": "✅ *Config deleted successfully*\n\n👤 Username: `{email}`\n🔑 UUID: `{uuid}`",
        "delete_failed": "❌ Failed to delete config.\n\nError: `{error}`",

        "select_lang": "🌐 Please select your language:",
        "lang_my": "🇲🇲 Myanmar",
        "lang_th": "🇹🇭 Thai",
        "lang_en": "🇬🇧 English",
        "lang_changed": "✅ Language changed to {lang}.",

        "broadcast_prompt": "📢 Send message to broadcast to all users.\nUse /cancel to stop.",
        "broadcast_sending": "⏳ Broadcasting message...",
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
            "❌ Username မမှန်ကန်ပါ။\n\n"
            "စာလုံး၊ နံပါတ်၊ underscore (_), dot (.), dash (-) သာခွင့်ပြုသည်။\n"
            "အလျား ၃ မှ ၃၂ လုံးအထိ။"
        ),
        "username_exists_db": "❌ ဤ username ကို bot database ထဲတွင် အသုံးပြုထားပြီးဖြစ်သည်။",
        "username_exists_panel": "❌ ဤ username သည် X-UI panel တွင် ရှိပြီးဖြစ်သည်။",

        "insufficient_balance": (
            "❌ *လက်ကျန်ငွေ မလုံလောက်ပါ*\n\n"
            "💰 သင့်လက်ကျန်: *{balance} THB*\n"
            "📦 Plan စျေးနှုန်း: *{price} THB*\n"
            "➕ ထပ်လိုအပ်ငွေ: *{need} THB*\n\n"
            "ကျေးဇူးပြု၍ ငွေဖြည့်ပါ။"
        ),
        "creating_client": "⏳ VLESS client ဖန်တီးနေသည်...",
        "purchase_success": (
            "✅ *Plan အောင်မြင်စွာ ဝယ်ယူပြီးပါပြီ!*\n\n"
            "📦 Plan: *{plan}*\n"
            "📅 သက်တမ်းကုန်ဆုံး: {expiry}\n"
            "👤 Username: `{email}`\n"
            "🏷 Remark: `{email}`\n"
            "📱 QR code ကို scan ဖတ်ပါ"
        ),
        "vless_config": "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        "copy_fallback": "\n\n📋 Config ကိုဖိထားပြီး copy ကူးပါ။",
        "copy_btn": "📋 VLESS ကူးယူရန်",
        "copy_not_supported_alert": "Config စာသားကို ဖိထား၍ copy ကူးပါ။",

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
            "💾 စုစုပေါင်းသုံးစွဲ: `{used} / {limit} GB` ({percent:.1f}%)\n\n"
            "🔑 UUID: `{uuid}`"
        ),

        "balance_text": "💰 *သင့်လက်ကျန်ငွေ:* `{balance} THB`",
        "topup_prompt": (
            "💰 *ငွေဖြည့်မည့်ပမာဏ:* `{amount} THB`\n\n"
            "🏦 အောက်ပါဘဏ်အကောင့်ထဲမှ တစ်ခုသို့လွှဲပြီး slip ပို့ပါ။"
        ),
        "bank_caption": (
            "🏦 *{name}*\n"
            "💳 `{number}`\n"
            "👤 {holder}\n\n"
            "💵 ပမာဏ: *{amount} THB*"
        ),
        "send_slip": "📸 *ငွေလွှဲ slip ဓာတ်ပုံ ပေးပို့ပါ။*\n/cancel ဖြင့်ပယ်ဖျက်နိုင်သည်။",
        "topup_sent": "✅ {amount} THB အတွက် ငွေဖြည့်တောင်းဆိုမှုကို admin ထံပို့ပြီးပါပြီ။",
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
        "no_pending_topups": "📭 ဆိုင်းငံ့တောင်းဆိုမှု မရှိပါ။",
        "pending_header": "📋 ဆိုင်းငံ့တောင်းဆိုမှု *{count}* ခုရှိသည်။",

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

        "broadcast_prompt": "📢 User အားလုံးသို့ပို့မည့် message ရိုက်ပါ။\n/cancel ဖြင့်ရပ်နိုင်သည်။",
        "broadcast_sending": "⏳ သတင်းပို့နေသည်...",
        "broadcast_result": "✅ သတင်းပို့ပြီးပါပြီ။\n\n📤 ပို့ပြီး: {sent}\n❌ မပို့ရသေး: {failed}",
    },

    "th": {
        "buy_plan": "🛒 ซื้อแผน",
        "topup": "💰 เติมเงิน",
        "account": "👤 บัญชี",
        "balance": "💰 ยอดเงิน",
        "contact": "📞 ติดต่อ",
        "admin_panel": "⚙️ แผงแอดมิน",
        "language": "🌐 ภาษา",
        "back": "🔙 กลับ",
        "main_menu": "🏠 เมนูหลัก",

        "select_plan": "📦 *เลือกแผน*",
        "select_amount": "💰 *เลือกจำนวนเงิน*",
        "enter_username": "👤 ส่ง username สำหรับ config นี้\n\nอนุญาต: `A-Z a-z 0-9 _ . -`\nใช้ /cancel เพื่อยกเลิก",
        "invalid_username": "❌ Username ไม่ถูกต้อง",
        "username_exists_db": "❌ Username นี้ถูกใช้แล้ว",
        "username_exists_panel": "❌ Username นี้มีอยู่ใน X-UI แล้ว",
        "insufficient_balance": "❌ *ยอดเงินไม่พอ*\n\nยอดเงิน: *{balance} THB*\nราคา: *{price} THB*\nต้องเพิ่ม: *{need} THB*",
        "creating_client": "⏳ กำลังสร้าง VLESS client...",
        "purchase_success": "✅ *ซื้อสำเร็จ!*\n\n📦 Plan: *{plan}*\n📅 หมดอายุ: {expiry}\n👤 Username: `{email}`",
        "vless_config": "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        "copy_fallback": "\n\n📋 กดค้างเพื่อคัดลอก",
        "copy_btn": "📋 Copy VLESS",
        "copy_not_supported_alert": "กดค้างที่ config เพื่อคัดลอก",

        "account_info": "👤 *บัญชี*\n\n📦 Config ทั้งหมด: *{count}*",
        "no_active_plan": "👤 ไม่มี active plan",
        "config_header": "━━━━━━ Config {idx} ━━━━━━",
        "config_status": (
            "📦 Plan: *{plan}*\n"
            "👤 Username: `{email}`\n"
            "📅 Expiry: {expiry}\n"
            "{status_emoji} Status: *{status}*\n\n"
            "📥 Download: `{down}`\n"
            "📤 Upload: `{up}`\n"
            "💾 Used: `{used} / {limit} GB` ({percent:.1f}%)\n"
            "🔑 UUID: `{uuid}`"
        ),

        "balance_text": "💰 *ยอดเงิน:* `{balance} THB`",
        "topup_prompt": "💰 *จำนวนเงิน:* `{amount} THB`\n\nโอนเข้าบัญชีด้านล่างแล้วส่งสลิป",
        "bank_caption": "🏦 *{name}*\n💳 `{number}`\n👤 {holder}\n\n💵 Amount: *{amount} THB*",
        "send_slip": "📸 ส่งรูปสลิป",
        "topup_sent": "✅ ส่งคำขอเติมเงิน {amount} THB แล้ว",
        "topup_approved": "✅ อนุมัติเติมเงิน {amount} THB แล้ว",
        "topup_cancelled": "❌ ยกเลิกคำขอเติมเงิน {amount} THB",

        "contact_text": "📞 Support\n\nTelegram: {username}",
        "contact_btn": "📩 Open Contact",

        "admin_add_bank": "➕ Add Bank",
        "admin_pending_topups": "📋 Pending TopUps",
        "admin_manage_banks": "🏦 Manage Banks",
        "admin_broadcast": "📢 Broadcast",

        "bank_name_prompt": "🏦 Bank name:",
        "bank_number_prompt": "💳 Account number:",
        "bank_holder_prompt": "👤 Account holder:",
        "bank_qr_prompt": "📷 Send QR photo, URL, or /skip.",
        "bank_added": "✅ Bank added.",
        "bank_updated": "✅ Bank updated.",
        "no_banks": "ℹ️ No banks.",
        "no_pending_topups": "📭 No pending requests.",
        "pending_header": "📋 Pending: *{count}*",

        "admin_note": "📝 Enter note or /skip.",
        "cancel": "↩️ Cancelled.",
        "back_to_menu": "↩️ Back to menu.",

        "confirm_delete": "🗑 Delete Config?",
        "delete_confirm_btn": "✅ Confirm",
        "delete_cancel_btn": "❌ Cancel",
        "config_deleted": "✅ Deleted\n\n👤 `{email}`\n🔑 `{uuid}`",
        "delete_failed": "❌ Delete failed: `{error}`",

        "select_lang": "🌐 Select language:",
        "lang_my": "🇲🇲 Myanmar",
        "lang_th": "🇹🇭 Thai",
        "lang_en": "🇬🇧 English",
        "lang_changed": "✅ Changed to {lang}.",

        "broadcast_prompt": "📢 Send broadcast message.",
        "broadcast_sending": "⏳ Broadcasting...",
        "broadcast_result": "✅ Done.\n\nSent: {sent}\nFailed: {failed}",
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
                    name TEXT UNIQUE,
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
                conn.execute(
                    """
                    INSERT INTO plans (name, days, data_gb, price)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        days=excluded.days,
                        data_gb=excluded.data_gb,
                        price=excluded.price
                    """,
                    (name, days, gb, price)
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
            (user_id, username, "my")
        )

    async def get_user(self, user_id):
        rows = await self.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return rows[0] if rows else None

    async def get_user_lang(self, user_id):
        user = await self.get_user(user_id)
        return user["lang"] if user and user.get("lang") else "my"

    async def set_user_lang(self, user_id, lang):
        await self.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id))

    async def set_admin(self, user_id):
        await self.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (user_id,))

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
        rows = await self.execute("SELECT * FROM plans WHERE id = ?", (plan_id,))
        return rows[0] if rows else None

    async def add_bank(self, name, number, holder, qr_file_id=None, qr_url=None):
        return await self.execute(
            "INSERT INTO banks (name, number, holder, qr_file_id, qr_url) VALUES (?, ?, ?, ?, ?)",
            (name, number, holder, qr_file_id, qr_url)
        )

    async def update_bank(self, bank_id, name, number, holder, qr_file_id=None, qr_url=None):
        await self.execute(
            "UPDATE banks SET name=?, number=?, holder=?, qr_file_id=?, qr_url=? WHERE id=?",
            (name, number, holder, qr_file_id, qr_url, bank_id)
        )

    async def get_bank(self, bank_id):
        rows = await self.execute("SELECT * FROM banks WHERE id = ?", (bank_id,))
        return rows[0] if rows else None

    async def get_banks(self):
        return await self.execute("SELECT * FROM banks ORDER BY id")

    async def delete_bank(self, bank_id):
        await self.execute("DELETE FROM banks WHERE id = ?", (bank_id,))

    async def create_topup(self, user_id, amount, slip_file_id):
        return await self.execute(
            "INSERT INTO topup_requests (user_id, amount, slip_file_id) VALUES (?, ?, ?)",
            (user_id, amount, slip_file_id)
        )

    async def get_topup(self, topup_id):
        rows = await self.execute("SELECT * FROM topup_requests WHERE id = ?", (topup_id,))
        return rows[0] if rows else None

    async def update_topup_status(self, topup_id, status):
        await self.execute("UPDATE topup_requests SET status=? WHERE id=?", (status, topup_id))

    async def get_pending_topups(self):
        return await self.execute(
            "SELECT * FROM topup_requests WHERE status='pending' ORDER BY created_at"
        )

    async def add_client(self, user_id, uuid_str, email, plan_id, total_gb, expiry_at):
        await self.execute(
            """
            INSERT INTO user_clients (user_id, uuid, email, plan_id, expiry_at, total_gb)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, uuid_str, email, plan_id, expiry_at.isoformat(), total_gb)
        )

    async def get_clients(self, user_id):
        return await self.execute(
            """
            SELECT uc.rowid AS row_id, uc.*, p.name AS plan_name, p.days, p.data_gb, p.price
            FROM user_clients uc
            LEFT JOIN plans p ON uc.plan_id = p.id
            WHERE uc.user_id = ?
            ORDER BY uc.created_at DESC
            """,
            (user_id,)
        )

    async def get_client_by_row_id(self, row_id):
        rows = await self.execute(
            """
            SELECT uc.rowid AS row_id, uc.*, p.name AS plan_name, p.days, p.data_gb, p.price
            FROM user_clients uc
            LEFT JOIN plans p ON uc.plan_id = p.id
            WHERE uc.rowid = ?
            LIMIT 1
            """,
            (row_id,)
        )
        return rows[0] if rows else None

    async def delete_client_by_row_id(self, row_id):
        await self.execute("DELETE FROM user_clients WHERE rowid = ?", (row_id,))

    async def email_exists(self, email):
        rows = await self.execute(
            "SELECT email FROM user_clients WHERE LOWER(email)=LOWER(?) LIMIT 1",
            (email,)
        )
        return bool(rows)

    async def update_client_usage_by_email(self, email, download, upload):
        await self.execute(
            "UPDATE user_clients SET download_used=?, upload_used=? WHERE email=?",
            (download, upload, email)
        )


db = Database()

# ==================== X-UI Client ====================

class XUIClient:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = self._detect_api_base()
        self.api_inbounds_path = "/xui/API/inbounds"

    def _try_login(self, base_url):
        url = f"{base_url.rstrip('/')}/login"
        data = {
            "username": CONFIG["PANEL_USER"],
            "password": CONFIG["PANEL_PASS"],
        }

        try:
            resp = self.session.post(url, data=data, timeout=12)
            logger.info(f"Trying X-UI login: {url} HTTP {resp.status_code}")

            if resp.status_code != 200:
                return False

            try:
                payload = resp.json()
                if payload.get("success") is True:
                    return True
            except Exception:
                pass

            if "success" in resp.text.lower() and "true" in resp.text.lower():
                return True

            return False
        except Exception as e:
            logger.warning(f"Login failed at {url}: {e}")
            return False

    def _detect_api_base(self):
        panel_url = CONFIG["PANEL_URL"].rstrip("/")
        root_url = "/".join(panel_url.split("/")[:3])

        candidates = []
        candidates.append(panel_url)
        if root_url != panel_url:
            candidates.append(root_url)

        for base in candidates:
            if self._try_login(base):
                logger.info(f"API base detected: {base}")
                return base.rstrip("/")

        raise Exception("Could not login to X-UI panel. Check PANEL_URL, username, password, and panel path.")

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

        download = self._safe_int(obj.get("downlink", obj.get("down", obj.get("download", 0))))
        upload = self._safe_int(obj.get("uplink", obj.get("up", obj.get("upload", 0))))
        total = self._safe_int(obj.get("total", obj.get("totalGB", obj.get("total_gb", 0))))
        expiry_time = self._safe_int(obj.get("expiryTime", obj.get("expiry_time", 0)))
        enable = obj.get("enable", True)

        return {
            "downlink": download,
            "uplink": upload,
            "total": total,
            "expiryTime": expiry_time,
            "enable": enable,
            "email": obj.get("email", ""),
        }

    def get_client_traffic(self, email):
        encoded_email = quote(email, safe="")

        urls = [
            f"{self.base_url}{self.api_inbounds_path}/getClientTraffics/{encoded_email}",
            f"{self.base_url}{self.api_inbounds_path}/getClientTraffics/{email}",
        ]

        for url in urls:
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success") and data.get("obj"):
                        return self._normalize_traffic_obj(data.get("obj"))
            except Exception as e:
                logger.warning(f"Traffic endpoint failed: {e}")

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

    def _extract_traffic_from_list(self, email, payload):
        inbounds = payload.get("obj") or []

        for inbound in inbounds:
            client_stats = inbound.get("clientStats") or inbound.get("clientTraffic") or []

            if isinstance(client_stats, list):
                for stat in client_stats:
                    if str(stat.get("email", "")).lower() == email.lower():
                        return self._normalize_traffic_obj(stat)

            settings_raw = inbound.get("settings")
            if not settings_raw:
                continue

            try:
                settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
                clients = settings.get("clients", [])

                for client in clients:
                    if str(client.get("email", "")).lower() == email.lower():
                        normalized = self._normalize_traffic_obj(client)

                        if isinstance(client_stats, list):
                            for stat in client_stats:
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

            inbounds = data.get("obj") or []

            for inbound in inbounds:
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

        except Exception as e:
            logger.warning(f"email_exists failed: {e}")

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
            except Exception as e:
                logger.warning(f"Delete try failed: {method} {url}: {e}")

        raise Exception("Failed to delete client from X-UI panel.")


xui = None

# ==================== Helpers ====================

def kill_old_bot():
    if not os.path.exists(PID_FILE):
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
        return

    try:
        with open(PID_FILE, "r") as f:
            old_pid = int(f.read().strip())

        if old_pid != os.getpid():
            try:
                os.kill(old_pid, 0)
                os.kill(old_pid, 9)
                logger.info(f"Killed old bot process PID {old_pid}")
            except ProcessLookupError:
                pass
            except PermissionError:
                logger.warning(f"No permission to kill old PID {old_pid}")
            except Exception as e:
                logger.warning(f"Failed to kill old PID {old_pid}: {e}")
    except Exception:
        pass

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def get_effective_message(target):
    if isinstance(target, Update):
        return target.effective_message
    return getattr(target, "message", None)


def get_welcome_text(lang):
    if lang == "my":
        return CONFIG.get("START_MESSAGE_MY", DEFAULT_CONFIG["START_MESSAGE_MY"])
    if lang == "th":
        return CONFIG.get("START_MESSAGE_TH", DEFAULT_CONFIG["START_MESSAGE_TH"])
    return CONFIG.get("START_MESSAGE_EN", DEFAULT_CONFIG["START_MESSAGE_EN"])


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


def sanitize_username(username):
    return username.strip()


def is_valid_xui_email_value(username):
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username))


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


async def get_main_keyboard(is_admin, lang):
    buttons = [
        [KeyboardButton(get_text("buy_plan", lang)), KeyboardButton(get_text("topup", lang))],
        [KeyboardButton(get_text("account", lang)), KeyboardButton(get_text("balance", lang))],
        [KeyboardButton(get_text("contact", lang)), KeyboardButton(get_text("language", lang))],
    ]

    if is_admin:
        buttons.append([KeyboardButton(get_text("admin_panel", lang))])

    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


async def send_main_menu(target, lang=None):
    if isinstance(target, Update):
        user_id = target.effective_user.id
    else:
        user_id = target.from_user.id

    if lang is None:
        lang = await db.get_user_lang(user_id)

    is_admin = await db.is_admin(user_id)
    keyboard = await get_main_keyboard(is_admin, lang)

    msg = get_effective_message(target)
    if msg:
        await msg.reply_text(get_text("main_menu", lang), reply_markup=keyboard)


# ==================== Main User Handlers ====================

async def start(update, context):
    user = update.effective_user
    user_id = user.id

    await db.create_user(user_id, user.username or user.full_name or str(user_id))

    if int(user_id) == int(CONFIG["ADMIN_ID"]):
        await db.set_admin(user_id)

    lang = await db.get_user_lang(user_id)

    await update.message.reply_text(get_welcome_text(lang))
    await send_main_menu(update, lang)


async def handle_message(update, context):
    user = update.effective_user
    user_id = user.id
    text = update.message.text or ""

    await db.create_user(user_id, user.username or user.full_name or str(user_id))

    if int(user_id) == int(CONFIG["ADMIN_ID"]):
        await db.set_admin(user_id)

    await route_main_menu_text(update, context, text)


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
            await send_main_menu(update, lang)
    else:
        await send_main_menu(update, lang)


async def show_balance(update, lang):
    balance = await db.get_balance(update.effective_user.id)
    await update.message.reply_text(
        get_text("balance_text", lang, balance=balance),
        parse_mode="Markdown",
    )


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


async def set_language(query, lang_code):
    user_id = query.from_user.id
    await db.set_user_lang(user_id, lang_code)

    new_lang = await db.get_user_lang(user_id)

    try:
        await query.answer(get_text("lang_changed", new_lang, lang=new_lang.upper()))
    except Exception:
        pass

    try:
        await query.message.delete()
    except Exception:
        pass

    await send_main_menu(query, new_lang)


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

    keyboard = [
        [InlineKeyboardButton(f"💵 {amount} THB", callback_data=f"topup_amt_{amount}")]
        for amount in amounts
    ]
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

        download = int(traffic.get("downlink", client.get("download_used", 0)) or 0)
        upload = int(traffic.get("uplink", client.get("upload_used", 0)) or 0)

        await db.update_client_usage_by_email(client["email"], download, upload)

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


# ==================== Buy Plan ====================

async def buy_plan_entry(update, context):
    query = update.callback_query
    await query.answer()

    plan_id = int(query.data.split("_")[1])
    plan = await db.get_plan(plan_id)

    if not plan:
        await query.edit_message_text("❌ Plan not found.")
        return ConversationHandler.END

    context.user_data["pending_buy_plan_id"] = plan_id

    lang = await db.get_user_lang(query.from_user.id)

    await query.edit_message_text(
        get_text("enter_username", lang),
        parse_mode="Markdown",
    )

    return BUY_USERNAME


async def buy_username_input(update, context):
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)

    menu_texts = [
        get_text("buy_plan", lang),
        get_text("topup", lang),
        get_text("account", lang),
        get_text("balance", lang),
        get_text("contact", lang),
        get_text("language", lang),
        get_text("admin_panel", lang),
    ]

    if text in menu_texts:
        context.user_data.pop("pending_buy_plan_id", None)
        await update.message.reply_text(get_text("back_to_menu", lang))
        await route_main_menu_text(update, context, text)
        return ConversationHandler.END

    username = sanitize_username(text)
    plan_id = context.user_data.get("pending_buy_plan_id")

    if not plan_id:
        await update.message.reply_text("❌ Buy session expired. Please select plan again.")
        await send_main_menu(update, lang)
        return ConversationHandler.END

    if not is_valid_xui_email_value(username):
        await update.message.reply_text(get_text("invalid_username", lang))
        return BUY_USERNAME

    if await db.email_exists(username):
        await update.message.reply_text(get_text("username_exists_db", lang))
        return BUY_USERNAME

    if xui and xui.email_exists(username):
        await update.message.reply_text(get_text("username_exists_panel", lang))
        return BUY_USERNAME

    await process_buy_plan_from_message(update, context, plan_id, username, lang)

    context.user_data.pop("pending_buy_plan_id", None)
    return ConversationHandler.END


async def process_buy_plan_from_message(update, context, plan_id, desired_username, lang):
    user_id = update.effective_user.id
    plan = await db.get_plan(plan_id)

    if not plan:
        await update.message.reply_text("❌ Plan not found.")
        await send_main_menu(update, lang)
        return

    is_admin = await db.is_admin(user_id)

    if not is_admin:
        balance = await db.get_balance(user_id)

        if balance < plan["price"]:
            need = plan["price"] - balance

            await update.message.reply_text(
                get_text(
                    "insufficient_balance",
                    lang,
                    balance=balance,
                    price=plan["price"],
                    need=need,
                ),
                parse_mode="Markdown",
            )
            return

        await db.update_balance(user_id, -plan["price"])

    await update.message.reply_text(get_text("creating_client", lang))

    try:
        uuid_str = str(uuid.uuid4())
        email = desired_username

        expiry_time_dt = datetime.utcnow() + timedelta(days=plan["days"])
        expiry_time_ms = int(expiry_time_dt.timestamp() * 1000)
        total_bytes = int(plan["data_gb"]) * 1024 ** 3

        if xui and xui.email_exists(email):
            raise Exception("This username already exists in X-UI panel.")

        if not xui:
            raise Exception("X-UI client is not connected.")

        xui.add_client(
            CONFIG["INBOUND_ID"],
            email,
            uuid_str,
            total_gb=total_bytes,
            expiry_time=expiry_time_ms,
        )

        await db.add_client(
            user_id=user_id,
            uuid_str=uuid_str,
            email=email,
            plan_id=plan_id,
            total_gb=total_bytes,
            expiry_at=expiry_time_dt,
        )

        link = generate_vless_link(uuid_str, email)
        qr_bytes = generate_qr_bytes(link)

        summary_caption = get_text(
            "purchase_success",
            lang,
            plan=plan["name"],
            expiry=expiry_time_dt.strftime("%d %b %Y"),
            email=email,
        )

        await update.message.reply_photo(
            photo=qr_bytes,
            caption=summary_caption,
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

        await send_main_menu(update, lang)

    except Exception as e:
        logger.error(f"Add client error: {e}")

        if not is_admin:
            await db.update_balance(user_id, plan["price"])

        await update.message.reply_text(f"❌ Failed: {str(e)[:500]}")
        await send_main_menu(update, lang)


# ==================== TopUp ====================

async def topup_amount_selected(update, context):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)

    data = query.data

    if data == "menu_back":
        try:
            await query.message.delete()
        except Exception:
            pass

        await send_main_menu(query, lang)
        return ConversationHandler.END

    amount = int(data.split("_")[2])
    context.user_data["topup_amount"] = amount

    banks = await db.get_banks()

    if not banks:
        await query.edit_message_text(get_text("no_banks", lang))
        return ConversationHandler.END

    try:
        await query.message.delete()
    except Exception:
        pass

    chat_id = query.message.chat.id

    await context.bot.send_message(
        chat_id=chat_id,
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
                chat_id=chat_id,
                photo=bank["qr_file_id"],
                caption=caption,
                parse_mode="Markdown",
            )
        elif bank.get("qr_url"):
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=bank["qr_url"],
                caption=caption,
                parse_mode="Markdown",
            )
        else:
            await context.bot.send_message(chat_id=chat_id, text=caption, parse_mode="Markdown")

    await context.bot.send_message(
        chat_id=chat_id,
        text=get_text("send_slip", lang),
        parse_mode="Markdown",
    )

    return TO_SLIP


async def receive_slip(update, context):
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)

    if not update.message.photo:
        await update.message.reply_text("❌ Please send a photo.")
        return TO_SLIP

    photo = update.message.photo[-1]
    file_id = photo.file_id
    amount = context.user_data.get("topup_amount")

    if not amount:
        await update.message.reply_text(get_text("cancel", lang))
        await send_main_menu(update, lang)
        return ConversationHandler.END

    topup_id = await db.create_topup(user_id, amount, file_id)

    await update.message.reply_text(get_text("topup_sent", lang, amount=amount))
    await send_main_menu(update, lang)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{topup_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{topup_id}"),
        ]
    ])

    user_mention = f"[{update.effective_user.full_name}](tg://user?id={user_id})"

    try:
        await context.bot.send_photo(
            chat_id=CONFIG["ADMIN_ID"],
            photo=file_id,
            caption=(
                f"🔔 *New Top-up Request*\n\n"
                f"👤 User: {user_mention}\n"
                f"💵 Amount: *{amount} THB*\n"
                f"🆔 Request ID: `{topup_id}`"
            ),
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Failed to send topup to admin: {e}")

    context.user_data.pop("topup_amount", None)
    return ConversationHandler.END


# ==================== Admin ====================

async def show_admin_panel(update, lang):
    keyboard = [
        [InlineKeyboardButton(get_text("admin_add_bank", lang), callback_data="admin_addbank")],
        [InlineKeyboardButton(get_text("admin_pending_topups", lang), callback_data="admin_pending")],
        [InlineKeyboardButton(get_text("admin_manage_banks", lang), callback_data="admin_listbanks")],
        [InlineKeyboardButton(get_text("admin_broadcast", lang), callback_data="admin_broadcast")],
        [InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")],
    ]

    await update.message.reply_text(
        "⚙️ Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def show_pending_topups(query, context, lang):
    pending = await db.get_pending_topups()

    if not pending:
        await query.edit_message_text(get_text("no_pending_topups", lang))
        return

    await query.edit_message_text(
        get_text("pending_header", lang, count=len(pending)),
        parse_mode="Markdown",
    )

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

    await query.edit_message_text(
        "🏦 *Manage Banks*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def admin_note_input(update, context):
    action_data = context.user_data.get("admin_action")

    if not action_data:
        await update.message.reply_text("Session expired.")
        return ConversationHandler.END

    text = (update.message.text or "").strip()
    note = None if text == "/skip" else text

    topup_id = action_data["topup_id"]
    action = action_data["action"]

    admin_lang = await db.get_user_lang(update.effective_user.id)

    if action == "approve":
        await approve_topup_with_note(update, context, topup_id, note)
    else:
        await cancel_topup_with_note(update, context, topup_id, note)

    context.user_data.pop("admin_action", None)
    await send_main_menu(update, admin_lang)
    return ConversationHandler.END


async def approve_topup_with_note(update, context, topup_id, note=None):
    topup = await db.get_topup(topup_id)

    if not topup or topup["status"] != "pending":
        await update.message.reply_text("Already processed.")
        return

    await db.update_topup_status(topup_id, "approved")
    await db.update_balance(topup["user_id"], topup["amount"])

    user_lang = await db.get_user_lang(topup["user_id"])

    msg = get_text("topup_approved", user_lang, amount=topup["amount"])
    if note:
        msg += f"\n📝 Admin Note: {note}"

    try:
        await context.bot.send_message(topup["user_id"], msg)
    except Exception as e:
        logger.warning(f"Failed to notify user: {e}")

    await update.message.reply_text(f"✅ Top-up {topup['amount']} THB approved.")


async def cancel_topup_with_note(update, context, topup_id, note=None):
    topup = await db.get_topup(topup_id)

    if not topup or topup["status"] != "pending":
        await update.message.reply_text("Already processed.")
        return

    await db.update_topup_status(topup_id, "cancelled")

    user_lang = await db.get_user_lang(topup["user_id"])

    msg = get_text("topup_cancelled", user_lang, amount=topup["amount"])
    if note:
        msg += f"\n📝 Admin Note: {note}"

    try:
        await context.bot.send_message(topup["user_id"], msg)
    except Exception as e:
        logger.warning(f"Failed to notify user: {e}")

    await update.message.reply_text(f"❌ Top-up {topup['amount']} THB cancelled.")


# ==================== Bank Add ====================

async def start_bank_addition(update, context):
    query = update.callback_query
    await query.answer()

    if not await db.is_admin(query.from_user.id):
        await query.answer("Admin only.", show_alert=True)
        return ConversationHandler.END

    lang = await db.get_user_lang(query.from_user.id)
    await query.edit_message_text(get_text("bank_name_prompt", lang))
    return BANK_NAME


async def bank_name(update, context):
    lang = await db.get_user_lang(update.effective_user.id)
    context.user_data["bank_name"] = update.message.text
    await update.message.reply_text(get_text("bank_number_prompt", lang))
    return BANK_NUMBER


async def bank_number(update, context):
    lang = await db.get_user_lang(update.effective_user.id)
    context.user_data["bank_number"] = update.message.text
    await update.message.reply_text(get_text("bank_holder_prompt", lang))
    return BANK_HOLDER


async def bank_holder(update, context):
    lang = await db.get_user_lang(update.effective_user.id)
    context.user_data["bank_holder"] = update.message.text
    await update.message.reply_text(get_text("bank_qr_prompt", lang))
    return BANK_QR


async def bank_qr(update, context):
    lang = await db.get_user_lang(update.effective_user.id)

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
        await update.message.reply_text("❌ Please send photo, URL, or /skip.")
        return BANK_QR

    await db.add_bank(
        context.user_data["bank_name"],
        context.user_data["bank_number"],
        context.user_data["bank_holder"],
        qr_file_id,
        qr_url,
    )

    await update.message.reply_text(get_text("bank_added", lang))
    await send_main_menu(update, lang)
    return ConversationHandler.END


# ==================== Bank Edit ====================

async def edit_bank_name(update, context):
    bank = context.user_data["edit_bank"]

    if update.message.text != "/skip":
        context.user_data["edit_bank_name"] = update.message.text
    else:
        context.user_data["edit_bank_name"] = bank["name"]

    await update.message.reply_text("💳 Enter new account number, or /skip:")
    return BANK_EDIT_NUMBER


async def edit_bank_number(update, context):
    bank = context.user_data["edit_bank"]

    if update.message.text != "/skip":
        context.user_data["edit_bank_number"] = update.message.text
    else:
        context.user_data["edit_bank_number"] = bank["number"]

    await update.message.reply_text("👤 Enter new account holder, or /skip:")
    return BANK_EDIT_HOLDER


async def edit_bank_holder(update, context):
    bank = context.user_data["edit_bank"]

    if update.message.text != "/skip":
        context.user_data["edit_bank_holder"] = update.message.text
    else:
        context.user_data["edit_bank_holder"] = bank["holder"]

    await update.message.reply_text("📷 Send new QR photo, URL, or /skip to keep:")
    return BANK_EDIT_QR


async def edit_bank_qr(update, context):
    lang = await db.get_user_lang(update.effective_user.id)

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
        await update.message.reply_text("❌ Invalid input. Send photo, URL, or /skip.")
        return BANK_EDIT_QR

    await db.update_bank(
        bank_id,
        context.user_data["edit_bank_name"],
        context.user_data["edit_bank_number"],
        context.user_data["edit_bank_holder"],
        qr_file_id,
        qr_url,
    )

    await update.message.reply_text(get_text("bank_updated", lang))
    await send_main_menu(update, lang)
    return ConversationHandler.END


# ==================== Broadcast ====================

async def broadcast_input(update, context):
    sender_id = update.effective_user.id

    if not await db.is_admin(sender_id):
        await update.message.reply_text("❌ Admin only.")
        return ConversationHandler.END

    text = update.message.text

    users = await db.get_all_users()

    await update.message.reply_text(get_text("broadcast_sending", "en"))

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
        get_text("broadcast_result", "en", sent=sent, failed=failed)
    )

    await send_main_menu(update)
    return ConversationHandler.END


# ==================== Callback Handler ====================

async def callback_handler(update, context):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)

    if data == "copy_not_supported":
        await query.answer(get_text("copy_not_supported_alert", lang), show_alert=True)
        return

    if data == "menu_back":
        try:
            await query.message.delete()
        except Exception:
            pass
        await send_main_menu(query, lang)
        return

    if data.startswith("lang_"):
        code = data.split("_")[1]
        await set_language(query, code)
        return

    if data == "goto_topup":
        try:
            await query.message.delete()
        except Exception:
            pass

        amounts = [40, 70, 100]
        keyboard = [
            [InlineKeyboardButton(f"💵 {amount} THB", callback_data=f"topup_amt_{amount}")]
            for amount in amounts
        ]
        keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])

        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text=get_text("select_amount", lang),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    if data.startswith("delcfg_"):
        row_id = int(data.split("_")[1])
        client = await db.get_client_by_row_id(row_id)

        if not client:
            await query.answer(get_text("no_active_plan", lang), show_alert=True)
            return

        is_admin = await db.is_admin(user_id)

        if client["user_id"] != user_id and not is_admin:
            await query.answer("You are not allowed.", show_alert=True)
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
            await query.answer("You are not allowed.", show_alert=True)
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
            return ConversationHandler.END

        parts = data.split("_")
        action = parts[0]
        topup_id = int(parts[1])

        context.user_data["admin_action"] = {
            "action": action,
            "topup_id": topup_id,
        }

        try:
            await query.edit_message_caption(
                caption=get_text("admin_note", lang),
                parse_mode="Markdown",
            )
        except Exception:
            await query.message.reply_text(
                get_text("admin_note", lang),
                parse_mode="Markdown",
            )

        return ADMIN_NOTE

    if not await db.is_admin(user_id):
        await query.answer("Admin only.", show_alert=True)
        return

    if data == "admin_addbank":
        await query.edit_message_text(get_text("bank_name_prompt", lang))
        return BANK_NAME

    if data == "admin_pending":
        await show_pending_topups(query, context, lang)
        return

    if data == "admin_listbanks":
        await manage_banks(query, lang)
        return

    if data == "admin_broadcast":
        await query.edit_message_text(get_text("broadcast_prompt", lang))
        return BROADCAST_TEXT

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

        context.user_data["edit_bank_id"] = bank_id
        context.user_data["edit_bank"] = bank

        await query.edit_message_text(
            f"✏️ Editing bank: {bank['name']}\n\nEnter new name, or /skip:"
        )

        return BANK_EDIT_NAME


async def cancel_edit(update, context):
    context.user_data.clear()

    lang = await db.get_user_lang(update.effective_user.id)

    await update.message.reply_text(get_text("cancel", lang))
    await send_main_menu(update, lang)

    return ConversationHandler.END


# ==================== Main ====================

def main():
    global xui

    kill_old_bot()
    ensure_config()

    try:
        xui = XUIClient()
        logger.info(f"Successfully connected to X-UI panel. API base: {xui.base_url}")
    except Exception as e:
        logger.error(f"Cannot login to X-UI: {e}")
        print("\n❌ X-UI Login failed.")
        print("Check PANEL_URL, PANEL_USER, PANEL_PASS, and custom panel path.")
        print(f"Error: {e}\n")
        sys.exit(1)

    try:
        app = Application.builder().token(CONFIG["BOT_TOKEN"]).build()
    except Exception as e:
        logger.error(f"Failed to create Telegram app: {e}")
        print("\n❌ Telegram BOT_TOKEN is invalid or python-telegram-bot has issue.")
        print(f"Error: {e}\n")
        sys.exit(1)

    admin_note_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^(approve|cancel)_")],
        states={
            ADMIN_NOTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_note_input),
                CommandHandler("skip", admin_note_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_edit)],
        per_message=False,
    )

    buy_plan_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(buy_plan_entry, pattern="^buy_")],
        states={
            BUY_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, buy_username_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_edit)],
        per_message=False,
    )

    topup_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(topup_amount_selected, pattern="^topup_amt_")],
        states={
            TO_SLIP: [
                MessageHandler(filters.PHOTO, receive_slip),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_edit)],
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
                CommandHandler("skip", bank_qr),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_edit)],
        per_message=False,
    )

    bank_edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^editbank_")],
        states={
            BANK_EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bank_name),
                CommandHandler("skip", edit_bank_name),
            ],
            BANK_EDIT_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bank_number),
                CommandHandler("skip", edit_bank_number),
            ],
            BANK_EDIT_HOLDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bank_holder),
                CommandHandler("skip", edit_bank_holder),
            ],
            BANK_EDIT_QR: [
                MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), edit_bank_qr),
                CommandHandler("skip", edit_bank_qr),
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

    app.add_handler(admin_note_conv)
    app.add_handler(buy_plan_conv)
    app.add_handler(bank_edit_conv)
    app.add_handler(bank_conv)
    app.add_handler(topup_conv)
    app.add_handler(broadcast_conv)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started. Waiting for Telegram updates...")
    print("\n✅ Bot started successfully.")
    print("Now open Telegram and press /start.\n")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
