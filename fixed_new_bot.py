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
        ("telegram", "python-telegram-bot==13.15"),
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

# Old CopyTextButton not available in 13.x, ignore
HAS_COPY_TEXT_BUTTON = False
CopyTextButton = None

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
logger = logging.getLogger("multi_inbound_bot")

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
    "SERVICES": [
        {
            "name": "AIS 64/128 KBPS",
            "inbound_id": 1,
            "port": 443,
            "ws_path": "/ais",
            "server_address": "ais.example.com",
            "ws_host": "ais.example.com"
        },
        {
            "name": "TRUE VDO V2RAY",
            "inbound_id": 2,
            "port": 443,
            "ws_path": "/true",
            "server_address": "true.example.com",
            "ws_host": "true.example.com"
        }
    ],
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
    if not CONFIG.get("BOT_TOKEN") or not CONFIG.get("ADMIN_ID"):
        return False
    if not CONFIG.get("PANEL_URL") or not CONFIG.get("PANEL_USER") or not CONFIG.get("PANEL_PASS"):
        return False
    if not isinstance(CONFIG.get("SERVICES"), list) or len(CONFIG["SERVICES"]) == 0:
        return False
    return True

def get_config():
    print("\n🔧 First-time configuration\n")
    CONFIG["BOT_TOKEN"] = input("Enter Bot Token: ").strip()
    CONFIG["ADMIN_ID"] = int(input("Enter Admin Telegram ID: ").strip())
    CONFIG["PANEL_URL"] = input("Enter X-UI Panel URL: ").strip().rstrip("/")
    CONFIG["PANEL_USER"] = input("Enter Panel Username: ").strip()
    CONFIG["PANEL_PASS"] = input("Enter Panel Password: ").strip()
    
    print("\nNow configure services (AIS and TRUE):")
    services = []
    for i, svc_name in enumerate(["AIS 64/128 KBPS", "TRUE VDO V2RAY"], start=1):
        print(f"\n--- Service {i}: {svc_name} ---")
        inbound_id = int(input(f"  Inbound ID for {svc_name}: ").strip())
        port = int(input(f"  Port: ").strip())
        ws_path = input(f"  WS Path (default /): ").strip() or "/"
        server_address = input(f"  Server Address / Domain: ").strip()
        ws_host = input(f"  WS Host: ").strip()
        services.append({
            "name": svc_name,
            "inbound_id": inbound_id,
            "port": port,
            "ws_path": ws_path,
            "server_address": server_address,
            "ws_host": ws_host
        })
    CONFIG["SERVICES"] = services

    contact = input("\nContact Username [default: @Juevpn]: ").strip()
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
        "select_service": "📡 *Select service*",
        "select_plan": "📦 *Plan*\n30 Days 150GB - 30 THB",
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
            "📦 Price: *30 THB*\n"
            "➕ Need: *{need} THB*"
        ),
        "creating_client": "⏳ Creating VLESS client...",
        "purchase_success": (
            "✅ *Plan Purchased Successfully!*\n\n"
            "📦 Plan: 30 Days 150GB\n"
            "📅 Expires: {expiry}\n"
            "👤 Username: `{email}`\n"
            "🔧 Service: {service}"
        ),
        "vless_config": "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        "copy_fallback": "\n\n📋 Long press config to copy.",
        "copy_btn": "📋 Copy VLESS",
        "copy_not_supported_alert": "Long press config text to copy.",
        "account_info": "👤 *Account Information*\n\n📦 Total Configs: *{count}*",
        "no_active_plan": "👤 *Account Information*\n\n📡 No active plan.",
        "config_header": "━━━━━━ Config {idx} ━━━━━━",
        "config_status": (
            "📦 Plan: 30 Days 150GB\n"
            "👤 Username: `{email}`\n"
            "📅 Expiry: {expiry}\n"
            "{status_emoji} Status: *{status}*\n"
            "🛜 Service: {service}\n\n"
            "📊 *Traffic*\n"
            "📥 Download: `{down}`\n"
            "📤 Upload: `{up}`\n"
            "💾 Used: `{used} / 150 GB` ({percent:.1f}%)\n\n"
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
        "select_service": "📡 *ဝန်ဆောင်မှုရွေးပါ*",
        "select_plan": "📦 *အစီအစဉ်*\nရက် 30 (150GB) - 30 ဘတ်",
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
            "📦 စျေးနှုန်း: *30 THB*\n"
            "➕ လိုအပ်ငွေ: *{need} THB*"
        ),
        "creating_client": "⏳ VLESS client ဖန်တီးနေသည်...",
        "purchase_success": (
            "✅ *အောင်မြင်စွာ ဝယ်ယူပြီးပါပြီ!*\n\n"
            "📦 အစီအစဉ်: ရက် 30 (150GB)\n"
            "📅 သက်တမ်းကုန်: {expiry}\n"
            "👤 Username: `{email}`\n"
            "🔧 ဝန်ဆောင်မှု: {service}"
        ),
        "vless_config": "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        "copy_fallback": "\n\n📋 Config ကိုဖိထားပြီး copy ကူးပါ။",
        "copy_btn": "📋 VLESS ကူးယူရန်",
        "copy_not_supported_alert": "Config စာသားကို ဖိထားပြီး copy ကူးပါ။",
        "account_info": "👤 *အကောင့်အချက်အလက်*\n\n📦 Config အရေအတွက်: *{count}*",
        "no_active_plan": "👤 *အကောင့်အချက်အလက်*\n\n📡 Active plan မရှိသေးပါ။",
        "config_header": "━━━━━━ Config {idx} ━━━━━━",
        "config_status": (
            "📦 အစီအစဉ်: ရက် 30 (150GB)\n"
            "👤 Username: `{email}`\n"
            "📅 သက်တမ်းကုန်: {expiry}\n"
            "{status_emoji} အခြေအနေ: *{status}*\n"
            "🛜 ဝန်ဆောင်မှု: {service}\n\n"
            "📊 *Traffic*\n"
            "📥 Download: `{down}`\n"
            "📤 Upload: `{up}`\n"
            "💾 သုံးပြီး: `{used} / 150 GB` ({percent:.1f}%)\n\n"
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
        "select_service": "📡 *เลือกบริการ*",
        "select_plan": "📦 *แผน*\n30 วัน 150GB - 30 บาท",
        "enter_username": "👤 ส่ง username\n/cancel เพื่อยกเลิก",
        "invalid_username": "❌ Username ไม่ถูกต้อง",
        "username_exists_db": "❌ Username นี้ถูกใช้แล้ว",
        "username_exists_panel": "❌ Username นี้มีใน X-UI แล้ว",
        "insufficient_balance": "❌ ยอดเงินไม่พอ\nBalance: {balance} THB\nPrice: 30 THB\nNeed: {need} THB",
        "creating_client": "⏳ กำลังสร้าง VLESS client...",
        "purchase_success": "✅ ซื้อสำเร็จ\nแผน: 30 วัน 150GB\nหมดอายุ: {expiry}\nUsername: `{email}`\nบริการ: {service}",
        "vless_config": "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        "copy_fallback": "\n\n📋 กดค้างเพื่อ copy",
        "copy_btn": "📋 Copy VLESS",
        "copy_not_supported_alert": "กดค้างเพื่อ copy",
        "account_info": "👤 บัญชี\nจำนวน Config: {count}",
        "no_active_plan": "ไม่มีแผนที่ใช้งานอยู่",
        "config_header": "━━━━━━ Config {idx} ━━━━━━",
        "config_status": "แผน: 30 วัน 150GB\nUsername: `{email}`\nหมดอายุ: {expiry}\nสถานะ: {status}\nบริการ: {service}\nใช้: `{used} / 150 GB`\nUUID: `{uuid}`",
        "balance_text": "💰 ยอดเงิน: `{balance} THB`",
        "topup_prompt": "เติมเงิน {amount} THB\nโอนแล้วส่ง slip",
        "bank_caption": "🏦 {name}\n💳 `{number}`\n👤 {holder}\nจำนวน: {amount} THB",
        "send_slip": "ส่งรูป slip",
        "topup_sent": "ส่งคำขอเติมเงินแล้ว",
        "topup_approved": "เติมเงินสำเร็จ",
        "topup_cancelled": "ยกเลิกการเติมเงิน",
        "contact_text": "ติดต่อ: {username}",
        "contact_btn": "เปิดติดต่อ",
        "admin_add_bank": "เพิ่มธนาคาร",
        "admin_pending_topups": "คำขอที่รออนุมัติ",
        "admin_manage_banks": "จัดการธนาคาร",
        "admin_broadcast": "ส่งข้อความถึงผู้ใช้ทั้งหมด",
        "bank_name_prompt": "ชื่อธนาคาร:",
        "bank_number_prompt": "เลขบัญชี:",
        "bank_holder_prompt": "ชื่อบัญชี:",
        "bank_qr_prompt": "ส่ง QR หรือ URL หรือ /skip",
        "bank_added": "เพิ่มธนาคารสำเร็จ",
        "bank_updated": "อัปเดตธนาคารสำเร็จ",
        "no_banks": "ไม่มีธนาคาร",
        "no_pending_topups": "ไม่มีคำขอเติมเงิน",
        "admin_note": "บันทึกหรือ /skip",
        "cancel": "ยกเลิก",
        "back_to_menu": "กลับเมนูหลัก",
        "confirm_delete": "ลบ Config?",
        "delete_confirm_btn": "ยืนยัน",
        "delete_cancel_btn": "ยกเลิก",
        "config_deleted": "ลบ `{email}` สำเร็จ",
        "delete_failed": "ลบไม่สำเร็จ: `{error}`",
        "select_lang": "เลือกภาษา:",
        "lang_my": "พม่า",
        "lang_th": "ไทย",
        "lang_en": "อังกฤษ",
        "lang_changed": "เปลี่ยนภาษาเป็น {lang}",
        "broadcast_prompt": "ส่งข้อความประชาสัมพันธ์",
        "broadcast_sending": "กำลังส่ง...",
        "broadcast_result": "ส่งเสร็จ\nส่งสำเร็จ: {sent}\nล้มเหลว: {failed}",
    }
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
            """)

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

    async def add_client(self, user_id, uuid_str, email, service_name, inbound_id, total_gb, expiry_at):
        await self.execute(
            """
            INSERT INTO user_clients (user_id, uuid, email, service_name, inbound_id, expiry_at, total_gb)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, uuid_str, email, service_name, inbound_id, expiry_at.isoformat(), total_gb),
        )

    async def get_clients(self, user_id):
        return await self.execute(
            """
            SELECT rowid, * FROM user_clients
            WHERE user_id=?
            ORDER BY created_at DESC
            """,
            (user_id,),
        )

    async def get_client_by_row_id(self, row_id):
        rows = await self.execute(
            """
            SELECT rowid, * FROM user_clients
            WHERE rowid=?
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
    def __init__(self, panel_url, panel_user, panel_pass):
        self.session = requests.Session()
        self.base_url = self._detect_api_base(panel_url, panel_user, panel_pass)

    def _try_login(self, base_url, username, password):
        url = f"{base_url.rstrip('/')}/login"
        data = {"username": username, "password": password}
        try:
            resp = self.session.post(url, data=data, timeout=12)
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
        candidates = [panel_url]
        if root_url != panel_url:
            candidates.append(root_url)
        for base in candidates:
            if self._try_login(base, username, password):
                logger.info(f"API base detected: {base}")
                return base.rstrip("/")
        raise Exception("Could not login to X-UI panel.")

    def add_client(self, inbound_id, email, uuid_str, total_gb=0, expiry_time=0):
        url = f"{self.base_url}/xui/API/inbounds/addClient/"
        settings = {
            "clients": [{
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
            }]
        }
        data = {"id": inbound_id, "settings": json.dumps(settings)}
        resp = self.session.post(url, data=data, timeout=20)
        if resp.status_code != 200:
            raise Exception(f"Add client HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            result = resp.json()
        except Exception:
            raise Exception(f"Add client invalid JSON: {resp.text[:300]}")
        if not result.get("success"):
            raise Exception(f"Add client error: {result.get('msg', 'Unknown')}")
        return result

    def get_client_traffic(self, email):
        encoded = quote(email, safe="")
        urls = [
            f"{self.base_url}/xui/API/inbounds/getClientTraffics/{encoded}",
            f"{self.base_url}/xui/API/inbounds/getClientTraffics/{email}",
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
        # fallback: list inbounds and search
        try:
            resp = self.session.get(f"{self.base_url}/xui/API/inbounds/list", timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    for inbound in data.get("obj") or []:
                        settings_raw = inbound.get("settings")
                        if settings_raw:
                            try:
                                settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
                                for client in settings.get("clients", []):
                                    if str(client.get("email", "")).lower() == email.lower():
                                        return self._normalize_traffic(client)
                            except Exception:
                                pass
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
        # try getClientTraffics first
        traffic = self.get_client_traffic(email)
        if traffic and str(traffic.get("email", "")).lower() == email.lower():
            return True
        # fallback to list inbounds
        try:
            resp = self.session.get(f"{self.base_url}/xui/API/inbounds/list", timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    for inbound in data.get("obj") or []:
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
        # try multiple methods
        candidates = [
            ("POST", f"{self.base_url}/xui/API/inbounds/delClient/{uuid_str}", {}),
            ("GET", f"{self.base_url}/xui/API/inbounds/delClient/{uuid_str}", {}),
            ("POST", f"{self.base_url}/xui/API/inbounds/delClient/{inbound_id}/{uuid_str}", {}),
            ("GET", f"{self.base_url}/xui/API/inbounds/delClient/{inbound_id}/{uuid_str}", {}),
            ("POST", f"{self.base_url}/xui/API/inbounds/delClient/", {"data": {"id": inbound_id, "clientId": uuid_str}}),
        ]
        for method, url, kwargs in candidates:
            try:
                if method == "POST":
                    resp = self.session.post(url, timeout=20, **kwargs)
                else:
                    resp = self.session.get(url, timeout=20, **kwargs)
                if resp.status_code == 200:
                    try:
                        if resp.json().get("success"):
                            return True
                    except Exception:
                        if "success" in resp.text.lower() and "true" in resp.text.lower():
                            return True
            except Exception:
                pass
        raise Exception("Failed to delete client from X-UI panel")

xui_client = None  # single panel instance

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

def generate_vless_link(uuid_str, remark, service_config):
    address = service_config["server_address"]
    port = service_config["port"]
    path = service_config.get("ws_path", "/")
    ws_host = service_config["ws_host"]
    link = (
        f"vless://{uuid_str}@{address}:{port}"
        f"?path={quote(path, safe='/')}"
        f"&security=none&encryption=none&type=ws&host={quote(ws_host, safe='')}"
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
    # No copy button in v13, just simple keyboard with callback
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

def get_service_config(service_name):
    for svc in CONFIG["SERVICES"]:
        if svc["name"] == service_name:
            return svc
    return None

def build_client_status_text(client, traffic, lang):
    service_name = client["service_name"]
    download = int(traffic.get("downlink", client.get("download_used", 0)) or 0)
    upload = int(traffic.get("uplink", client.get("upload_used", 0)) or 0)
    total_used = download + upload
    total_limit_bytes = int(client.get("total_gb", 0) or 0)
    if total_limit_bytes == 0:
        total_limit_bytes = 150 * 1024**3  # 150 GB default
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
    limit_gb = total_limit_bytes / (1024**3)
    usage_percent = (total_used / total_limit_bytes * 100) if total_limit_bytes > 0 else 0
    traffic_exhausted = total_limit_bytes > 0 and total_used >= total_limit_bytes
    is_active = enabled and not is_expired and not traffic_exhausted
    status_emoji = "🟢" if is_active else "🔴"
    status_text = "Active" if is_active else "Expired"
    return get_text(
        "config_status",
        lang,
        email=client["email"],
        expiry=expiry_str,
        status_emoji=status_emoji,
        status=status_text,
        service=service_name,
        down=format_bytes(download),
        up=format_bytes(upload),
        used=format_bytes(total_used),
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
    svc = get_service_config(client["service_name"])
    if not svc:
        raise Exception("Service config missing")
    link = generate_vless_link(client["uuid"], client["email"], svc)
    config_text = get_text("vless_config", lang, config=html.escape(link))
    keyboard = get_vless_copy_keyboard(link, lang)
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

    if state == "buy_service":
        await handle_buy_service(update, context)
        return
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
        await show_service_selection(update, lang)
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

async def show_service_selection(update, lang):
    services = CONFIG.get("SERVICES", [])
    keyboard = []
    for svc in services:
        keyboard.append([InlineKeyboardButton(svc["name"], callback_data=f"service_{svc['name']}")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])
    await update.message.reply_text(
        get_text("select_service", lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def start_buy_plan_from_service(query, context, service_name):
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)
    context.user_data.clear()
    context.user_data["state"] = "buy_username"
    context.user_data["selected_service"] = service_name
    try:
        await query.message.delete()
    except Exception:
        pass
    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=get_text("enter_username", lang),
        parse_mode="Markdown",
    )

async def handle_buy_service(update, context):
    # not used directly, handled by callback
    pass

async def handle_buy_username(update, context):
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)

    username = sanitize_username(text)
    service_name = context.user_data.get("selected_service")
    if not service_name:
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

    # check panel existence for this service
    svc = get_service_config(service_name)
    if not svc:
        await update.message.reply_text("❌ Service configuration missing.")
        return

    if xui_client and xui_client.email_exists(username):
        await update.message.reply_text(get_text("username_exists_panel", lang))
        return

    await process_buy_plan(update, context, username, service_name, lang)
    context.user_data.clear()

async def process_buy_plan(update, context, desired_username, service_name, lang):
    user_id = update.effective_user.id
    svc = get_service_config(service_name)
    if not svc:
        await update.message.reply_text("❌ Service not found.")
        await send_main_menu_by_message(update.message, user_id, lang)
        return

    price = 30  # fixed price
    is_admin = await db.is_admin(user_id)

    if not is_admin:
        balance = await db.get_balance(user_id)
        if balance < price:
            need = price - balance
            await update.message.reply_text(
                get_text("insufficient_balance", lang, balance=balance, need=need),
                parse_mode="Markdown",
            )
            await send_main_menu_by_message(update.message, user_id, lang)
            return
        await db.update_balance(user_id, -price)

    await update.message.reply_text(get_text("creating_client", lang))

    try:
        email = desired_username
        uuid_str = str(uuid.uuid4())
        expiry_dt = datetime.utcnow() + timedelta(days=30)
        expiry_ms = int(expiry_dt.timestamp() * 1000)
        total_bytes = 150 * 1024 ** 3

        if xui_client.email_exists(email):
            raise Exception("Username already exists in panel.")

        xui_client.add_client(
            svc["inbound_id"],
            email,
            uuid_str,
            total_gb=total_bytes,
            expiry_time=expiry_ms,
        )

        await db.add_client(
            user_id=user_id,
            uuid_str=uuid_str,
            email=email,
            service_name=service_name,
            inbound_id=svc["inbound_id"],
            total_gb=total_bytes,
            expiry_at=expiry_dt,
        )

        link = generate_vless_link(uuid_str, email, svc)
        qr_bytes = generate_qr_bytes(link)

        caption = get_text(
            "purchase_success",
            lang,
            expiry=expiry_dt.strftime("%d %b %Y"),
            email=email,
            service=service_name,
        )

        await update.message.reply_photo(
            photo=qr_bytes,
            caption=caption,
            parse_mode="Markdown",
        )

        config_text = get_text("vless_config", lang, config=html.escape(link))
        keyboard = get_vless_copy_keyboard(link, lang)
        await update.message.reply_text(
            config_text + get_text("copy_fallback", lang),
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        await send_main_menu_by_message(update.message, user_id, lang)

    except Exception as e:
        logger.error(f"Buy failed: {e}")
        if not is_admin:
            await db.update_balance(user_id, price)
        await update.message.reply_text(f"❌ Failed: {str(e)[:600]}")
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

async def start_topup(update, lang):
    amounts = [30, 60, 90]
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
        traffic = xui_client.get_client_traffic(client["email"]) if xui_client else {}
        down = int(traffic.get("downlink", client.get("download_used", 0)) or 0)
        up = int(traffic.get("uplink", client.get("upload_used", 0)) or 0)
        await db.update_client_usage_by_email(client["email"], down, up)

        status_text = build_client_status_text(client, traffic, lang)

        await update.message.reply_text(
            f"{get_text('config_header', lang, idx=idx)}\n{status_text}",
            parse_mode="Markdown",
            reply_markup=get_config_action_keyboard(client["rowid"], lang),
        )

        try:
            svc = get_service_config(client["service_name"])
            if svc:
                link = generate_vless_link(client["uuid"], client["email"], svc)
                qr_bytes = generate_qr_bytes(link)
                await update.message.reply_photo(
                    photo=qr_bytes,
                    caption=f"📱 *QR:* `{client['email']}`",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.warning(f"QR failed: {e}")

        await send_client_config_block(update.message, client, lang)

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

    if data.startswith("service_"):
        service_name = data[8:]
        await start_buy_plan_from_service(query, context, service_name)
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
            if xui_client:
                xui_client.delete_client(client["uuid"], inbound_id=client["inbound_id"], email=client["email"])
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
    global xui_client

    kill_old_bot()
    ensure_config()

    try:
        xui_client = XUIClient(CONFIG["PANEL_URL"], CONFIG["PANEL_USER"], CONFIG["PANEL_PASS"])
        logger.info(f"Connected to X-UI panel. API base: {xui_client.base_url}")
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

    # Fixed run_polling for python-telegram-bot 13.x
    app.run_polling()

if __name__ == "__main__":
    main()
