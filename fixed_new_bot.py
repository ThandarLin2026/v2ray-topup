#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import html
import importlib
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

REQUIRED_PTB_VERSION = "python-telegram-bot>=21.7,<22"

def install_dependencies():
    packages = [
        ("requests", "requests"),
        ("telegram", REQUIRED_PTB_VERSION),
        ("qrcode", "qrcode[pil]"),
        ("PIL", "pillow"),
    ]
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

import requests
import qrcode

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    CopyTextButton,
)
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
            "name": "🇹🇭 AIS 64/128 KBPS { V2RAY }",
            "inbound_id": 1,
            "port": 443,
            "ws_path": "/ais",
            "server_address": "ais.example.com",
            "ws_host": "ais.example.com",
            "plans": [
                {"name": "🇹🇭 AIS 64/128 KBPS { 1 MONTH }", "days": 30, "price": 30, "total_gb": 150},
                {"name": "🇹🇭 AIS 64/128 KBPS { 2 MONTHS }", "days": 60, "price": 60, "total_gb": 300},
            ],
        },
        {
            "name": "🇹🇭 TRUE VDO ZOOM { V2RAY }",
            "inbound_id": 2,
            "port": 443,
            "ws_path": "/true",
            "server_address": "true.example.com",
            "ws_host": "true.example.com",
            "plans": [
                {"name": "🇹🇭 TRUE VDO ZOOM { 1 MONTH }", "days": 30, "price": 30, "total_gb": 150},
                {"name": "🇹🇭 TRUE VDO ZOOM { 2 MONTHS }", "days": 60, "price": 60, "total_gb": 300},
            ],
        },
        {
            "name": "🇲🇲 Myanmar All Sim Wifi { V2RAY }",
            "inbound_id": 3,
            "port": 443,
            "ws_path": "/mm",
            "server_address": "mm.example.com",
            "ws_host": "mm.example.com",
            "plans": [
                {"name": "🇲🇲 Myanmar All Sim Wifi { 1 MONTH }", "days": 30, "price": 30, "total_gb": 150},
                {"name": "🇲🇲 Myanmar All Sim Wifi { 2 MONTHS }", "days": 60, "price": 60, "total_gb": 300},
            ],
        },
    ],
    "CONTACT_USERNAME": "@Juevpn",
    "START_MESSAGE_MY": (
        "🌟 *V2RAY X-UI PANEL* 🌟\n\n"
        "✅ AIS 64/128 KBPS\n"
        "✅ TRUE VDO ZOOM\n"
        "✅ Myanmar All Sim Wifi\n\n"
        "အောက်ပါ Menu မှ ဝယ်ယူအသုံးပြုနိုင်ပါသည်။"
    ),
    "START_MESSAGE_EN": (
        "🌟 *V2RAY X-UI PANEL* 🌟\n\n"
        "✅ AIS 64/128 KBPS\n"
        "✅ TRUE VDO ZOOM\n"
        "✅ Myanmar All Sim Wifi\n\n"
        "Use the menu below to purchase."
    ),
    "START_MESSAGE_TH": (
        "🌟 *V2RAY X-UI PANEL* 🌟\n\n"
        "✅ AIS 64/128 KBPS\n"
        "✅ TRUE VDO ZOOM\n"
        "✅ Myanmar All Sim Wifi\n\n"
        "ใช้เมนูด้านล่างเพื่อซื้อแพ็กเกจ"
    ),
    "TOPUP_AMOUNTS": [30, 60, 90, 300, 500],
}

CONFIG = DEFAULT_CONFIG.copy()

def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2, ensure_ascii=False)

def normalize_services():
    for svc in CONFIG.get("SERVICES", []):
        if "plans" not in svc or not isinstance(svc["plans"], list) or not svc["plans"]:
            svc["plans"] = [
                {"name": f"{svc.get('name', 'Service')} {{ 1 MONTH }}", "days": 30, "price": 30, "total_gb": 150},
                {"name": f"{svc.get('name', 'Service')} {{ 2 MONTHS }}", "days": 60, "price": 60, "total_gb": 300},
            ]

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
        normalize_services()
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
    print("❌ Run manually first: python3 bot_updated.py")
    sys.exit(1)

def kill_old_bot():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r", encoding="utf-8") as f:
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
    with open(PID_FILE, "w", encoding="utf-8") as f:
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
        "select_service": "📡 Select service",
        "select_plan": "📦 Select package",
        "select_amount": "💰 Select top-up amount",
        "enter_username": "👤 *Please send username for this config.*\n\nAllowed: `A-Z a-z 0-9 _ . -`\nExample: `mgmg123`\n\nUse /cancel to stop.",
        "invalid_username": "❌ Invalid username.\nOnly A-Z a-z 0-9 _ . - allowed.\nLength 3 to 32 characters.",
        "username_exists_db": "❌ This username is already used in bot database.",
        "username_exists_panel": "❌ This username already exists in X-UI panel.",
        "insufficient_balance": "❌ Insufficient balance\n\n💰 Balance: {balance} ฿\n📦 Price: {price} ฿\n➕ Need: {need} ฿",
        "creating_client": "⏳ Creating VLESS client...",
        "purchase_success": "✅ Plan Purchased Successfully!\n\n📦 Package: {plan}\n💵 Price: {price} ฿\n📊 Limit: {total_gb} GB\n📅 Expires: {expiry}\n👤 Username: {email}\n🔧 Service: {service}",
        "vless_config": "🔐 VLESS CONFIG\n\n`{config}`",
        "copy_fallback": "\n\n📋 Press the Copy VLESS button, or long press config text to copy.",
        "copy_btn": "📋 Copy VLESS",
        "copy_not_supported_alert": "Your Telegram app does not support direct copy. Long press config text to copy.",
        "account_info": "👤 Account Information\n\n📦 Total Configs: {count}",
        "no_active_plan": "👤 Account Information\n\n📡 No active plan.",
        "config_header": "━━━━━━ Config {idx} ━━━━━━",
        "config_status": "📦 Package: {plan}\n👤 Username: {email}\n📅 Expiry: {expiry}\n{status_emoji} Status: {status}\n🛜 Service: {service}\n\n📊 Traffic\n📥 Download: {down}\n📤 Upload: {up}\n💾 Used: {used} / {limit} ({percent:.1f}%)\n\n🔑 UUID: `{uuid}`",
        "balance_text": "💰 Your balance: {balance} ฿",
        "balance_unlimited": "💰 Your balance: ♾️ Unlimited",
        "topup_prompt": "💰 Top-up Amount: {amount} ฿\n\n🏦 Transfer to one bank account below, then send slip photo.",
        "bank_caption": "🏦 {name}\n💳 {number}\n👤 {holder}\n\n💵 Amount: {amount} ฿",
        "send_slip": "📸 Send payment slip photo.\nUse /cancel to stop.",
        "topup_sent": "✅ Top-up request for {amount} ฿ sent to admin.",
        "topup_approved": "✅ Your top-up of {amount} ฿ has been approved.",
        "topup_cancelled": "❌ Your top-up request of {amount} ฿ was cancelled.",
        "contact_text": "📞 *Contact Support*\n\nTelegram: {username}\n\nClick the button below to chat.",
        "contact_btn": "📩 Chat Now",
        "admin_add_bank": "➕ Add Bank",
        "admin_pending_topups": "📋 Pending TopUps",
        "admin_manage_banks": "🏦 Manage Banks",
        "admin_broadcast": "📢 Broadcast",
        "admin_edit_plans": "✏️ Edit Prices",
        "admin_edit_topups": "💰 Edit TopUp Amounts",
        "admin_stats": "📊 Statistics",
        "admin_user_mgmt": "👥 User Mgmt",
        "bank_name_prompt": "🏦 Enter bank name:",
        "bank_number_prompt": "💳 Enter account number:",
        "bank_holder_prompt": "👤 Enter account holder:",
        "bank_qr_prompt": "📷 Send QR photo, image URL, or /skip.",
        "bank_added": "✅ Bank added.",
        "bank_updated": "✅ Bank updated.",
        "no_banks": "ℹ️ No bank accounts. Admin must add a bank first.",
        "no_pending_topups": "📭 No pending topups.",
        "admin_note": "📝 Enter note for user, or /skip.",
        "cancel": "↩️ Cancelled.",
        "back_to_menu": "↩️ Back to main menu.",
        "confirm_delete": "🗑 Delete Config?",
        "delete_confirm_btn": "✅ Confirm Delete",
        "delete_cancel_btn": "❌ Cancel",
        "config_deleted": "✅ Config deleted successfully\n\n👤 Username: {email}\n🔑 UUID: {uuid}",
        "delete_failed": "❌ Failed to delete config.\n\nError: {error}",
        "select_lang": "🌐 Please select language:",
        "lang_my": "🇲🇲 Myanmar",
        "lang_th": "🇹🇭 Thai",
        "lang_en": "🇬🇧 English",
        "lang_changed": "✅ Language changed to {lang}.",
        "broadcast_prompt": "📢 Send message to broadcast.\nUse /cancel to stop.",
        "broadcast_sending": "⏳ Broadcasting...",
        "broadcast_result": "✅ Broadcast finished.\n\n📤 Sent: {sent}\n❌ Failed: {failed}",
        "total_users": "👥 Total Users: {count}",
        "total_online": "🟢 Total Online: {count}",
        "total_offline": "🔴 Total Offline: {count}",
        "list_all_users": "📋 List All Users (with configs)",
        "list_online_cfgs": "🟢 List Online Configs",
        "list_offline_cfgs": "🔴 List Offline Configs",
        "add_credit": "➕ Add Credit",
        "enter_user_id": "🆔 Enter user ID to add credit:",
        "enter_credit_amount": "💰 Enter amount (฿) to add:",
        "credit_added": "✅ Added {amount} ฿ to user {user_id}.",
        "user_not_found": "❌ User not found.",
        "select_service_to_view": "📡 Select service to view your configs",
        "no_configs_for_service": "❌ No configs for this service.",
        "config_qr_caption": "📱 *QR Code for* `{email}`\n🛜 Service: {service}\n{status_emoji} Status: {status}",
        "user_configs_title": "👤 *User ID:* `{user_id}`\n💰 Balance: {balance} ฿\n📦 Total configs: {count}\n",
        "edit_topup_current": "💰 *Current Top‑up amounts*: {amounts}\n\nSend new comma‑separated list, e.g. `30,60,100,200`\nOr /cancel",
        "edit_topup_success": "✅ Top‑up amounts updated to: {amounts} ฿",
    },
    "my": {
        "buy_plan": "🛒 Package ဝယ်ရန်",
        "topup": "💰 ငွေဖြည့်ရန်",
        "account": "👤 အကောင့်",
        "balance": "💰 လက်ကျန်ငွေ",
        "contact": "📞 ဆက်သွယ်ရန်",
        "admin_panel": "⚙️ Admin Panel",
        "language": "🌐 ဘာသာစကား",
        "back": "🔙 နောက်သို့",
        "main_menu": "🏠 Main Menu",
        "select_service": "📡 Service ရွေးပါ",
        "select_plan": "📦 Package ရွေးပါ",
        "select_amount": "💰 ငွေဖြည့်မည့် ပမာဏ ရွေးပါ",
        "enter_username": "👤 *ဒီ config အတွက် username ပို့ပါ။*\n\nခွင့်ပြုထားတာ: `A-Z a-z 0-9 _ . -`\nဥပမာ: `mgmg123`\n\n/cancel ဖြင့် ရပ်နိုင်သည်။",
        "invalid_username": "❌ Username မမှန်ပါ။\nA-Z a-z 0-9 _ . - သာ ခွင့်ပြုသည်။\nစာလုံးရေ 3 မှ 32 အတွင်း ဖြစ်ရမည်။",
        "username_exists_db": "❌ ဒီ username ကို bot database ထဲမှာ သုံးထားပြီးပါပြီ။",
        "username_exists_panel": "❌ ဒီ username က X-UI panel ထဲမှာ ရှိပြီးသားပါ။",
        "insufficient_balance": "❌ လက်ကျန်ငွေ မလုံလောက်ပါ\n\n💰 လက်ကျန်: {balance} ฿\n📦 စျေးနှုန်း: {price} ฿\n➕ လိုအပ်ငွေ: {need} ฿",
        "creating_client": "⏳ VLESS client ဖန်တီးနေသည်...",
        "purchase_success": "✅ Package ဝယ်ယူမှု အောင်မြင်ပါပြီ!\n\n📦 Package: {plan}\n💵 စျေးနှုန်း: {price} ฿\n📊 Data Limit: {total_gb} GB\n📅 သက်တမ်းကုန်: {expiry}\n👤 Username: {email}\n🔧 Service: {service}",
        "vless_config": "🔐 VLESS CONFIG\n\n`{config}`",
        "copy_fallback": "\n\n📋 Copy VLESS ခလုတ်နှိပ်ပါ။ မရပါက config စာသားကို ဖိထားပြီး copy ကူးပါ။",
        "copy_btn": "📋 Copy VLESS",
        "copy_not_supported_alert": "သင့် Telegram app မှာ direct copy မရပါ။ Config စာသားကို ဖိထားပြီး copy ကူးပါ။",
        "account_info": "👤 အကောင့်အချက်အလက်\n\n📦 Config အရေအတွက်: {count}",
        "no_active_plan": "👤 အကောင့်အချက်အလက်\n\n📡 Active plan မရှိသေးပါ။",
        "config_header": "━━━━━━ Config {idx} ━━━━━━",
        "config_status": "📦 Package: {plan}\n👤 Username: {email}\n📅 Expiry: {expiry}\n{status_emoji} Status: {status}\n🛜 Service: {service}\n\n📊 Traffic\n📥 Download: {down}\n📤 Upload: {up}\n💾 Used: {used} / {limit} ({percent:.1f}%)\n\n🔑 UUID: `{uuid}`",
        "balance_text": "💰 သင့်လက်ကျန်ငွေ: {balance} ฿",
        "balance_unlimited": "💰 သင့်လက်ကျန်: ♾️ အကန့်အသတ်မရှိ",
        "topup_prompt": "💰 ငွေဖြည့်မည့်ပမာဏ: {amount} ฿\n\n🏦 အောက်ပါ bank account တစ်ခုသို့ လွှဲပြီး slip ပို့ပါ။",
        "bank_caption": "🏦 {name}\n💳 {number}\n👤 {holder}\n\n💵 ပမာဏ: {amount} ฿",
        "send_slip": "📸 ငွေလွှဲ slip ဓာတ်ပုံ ပို့ပါ။\n/cancel ဖြင့် ရပ်နိုင်သည်။",
        "topup_sent": "✅ {amount} ฿ ငွေဖြည့်တောင်းဆိုမှုကို admin ထံ ပို့ပြီးပါပြီ။",
        "topup_approved": "✅ သင့် {amount} ฿ ငွေဖြည့်မှုကို အတည်ပြုပြီးပါပြီ။",
        "topup_cancelled": "❌ သင့် {amount} ฿ ငွေဖြည့်တောင်းဆိုမှုကို ပယ်ဖျက်လိုက်ပါသည်။",
        "contact_text": "📞 *ဆက်သွယ်ရန်*\n\nTelegram: {username}\n\nအောက်ပါခလုတ်ကို နှိပ်၍ စကားပြောနိုင်ပါသည်။",
        "contact_btn": "📩 စကားပြောရန်",
        "admin_add_bank": "➕ Bank ထည့်ရန်",
        "admin_pending_topups": "📋 Pending TopUps",
        "admin_manage_banks": "🏦 Bank များစီမံရန်",
        "admin_broadcast": "📢 Broadcast",
        "admin_edit_plans": "✏️ စျေးနှုန်းပြင်ရန်",
        "admin_edit_topups": "💰 ငွေဖြည့်ပမာဏပြင်ရန်",
        "admin_stats": "📊 စာရင်းအင်း",
        "admin_user_mgmt": "👥 အသုံးပြုသူစီမံ",
        "bank_name_prompt": "🏦 Bank name ရိုက်ထည့်ပါ:",
        "bank_number_prompt": "💳 Account number ရိုက်ထည့်ပါ:",
        "bank_holder_prompt": "👤 Account holder ရိုက်ထည့်ပါ:",
        "bank_qr_prompt": "📷 QR photo, image URL, သို့မဟုတ် /skip ပို့ပါ။",
        "bank_added": "✅ Bank ထည့်ပြီးပါပြီ။",
        "bank_updated": "✅ Bank ပြင်ပြီးပါပြီ။",
        "no_banks": "ℹ️ Bank account မရှိသေးပါ။ Admin က Bank အရင်ထည့်ပါ။",
        "no_pending_topups": "📭 Pending TopUp မရှိပါ။",
        "admin_note": "📝 User အတွက် note ရိုက်ပါ။ မလိုပါက /skip ပို့ပါ။",
        "cancel": "↩️ ပယ်ဖျက်လိုက်ပါပြီ။",
        "back_to_menu": "↩️ Main Menu သို့ ပြန်သွားသည်။",
        "confirm_delete": "🗑 Config ဖျက်မည်?",
        "delete_confirm_btn": "✅ ဖျက်ရန် အတည်ပြု",
        "delete_cancel_btn": "❌ မဖျက်တော့ပါ",
        "config_deleted": "✅ Config ကို ဖျက်ပြီးပါပြီ\n\n👤 Username: {email}\n🔑 UUID: {uuid}",
        "delete_failed": "❌ Config ဖျက်မအောင်မြင်ပါ။\n\nError: {error}",
        "select_lang": "🌐 ဘာသာစကား ရွေးပါ:",
        "lang_my": "🇲🇲 မြန်မာ",
        "lang_th": "🇹🇭 ထိုင်း",
        "lang_en": "🇬🇧 English",
        "lang_changed": "✅ ဘာသာစကားကို {lang} သို့ ပြောင်းပြီးပါပြီ။",
        "broadcast_prompt": "📢 User အားလုံးသို့ ပို့မည့် message ရိုက်ပါ။\n/cancel ဖြင့် ရပ်နိုင်သည်။",
        "broadcast_sending": "⏳ Broadcasting...",
        "broadcast_result": "✅ Broadcast ပြီးပါပြီ။\n\n📤 Sent: {sent}\n❌ Failed: {failed}",
        "total_users": "👥 စုစုပေါင်းအသုံးပြုသူ: {count}",
        "total_online": "🟢 အွန်လိုင်း Config: {count}",
        "total_offline": "🔴 အော့ဖ်လိုင်း Config: {count}",
        "list_all_users": "📋 အသုံးပြုသူအားလုံး (Config များပါ)",
        "list_online_cfgs": "🟢 အွန်လိုင်း Config များ",
        "list_offline_cfgs": "🔴 အော့ဖ်လိုင်း Config များ",
        "add_credit": "➕ ခရက်ဒစ်ထည့်ရန်",
        "enter_user_id": "🆔 ခရက်ဒစ်ထည့်မည့် User ID ထည့်ပါ:",
        "enter_credit_amount": "💰 ထည့်မည့်ငွေ (ဘတ်) ထည့်ပါ:",
        "credit_added": "✅ User {user_id} သို့ {amount} ฿ ထည့်ပြီးပါပြီ။",
        "user_not_found": "❌ User မတွေ့ပါ။",
        "select_service_to_view": "📡 သင့် config များကြည့်ရန် Service ရွေးပါ",
        "no_configs_for_service": "❌ ဒီ Service အတွက် Config မရှိပါ။",
        "config_qr_caption": "📱 *QR Code for* `{email}`\n🛜 Service: {service}\n{status_emoji} Status: {status}",
        "user_configs_title": "👤 *User ID:* `{user_id}`\n💰 လက်ကျန်: {balance} ฿\n📦 စုစုပေါင်း config: {count}\n",
        "edit_topup_current": "💰 *လက်ရှိ ငွေဖြည့်ပမာဏများ*: {amounts}\n\nကော်မာခံပြီး ဂဏန်းအသစ်များ ပို့ပါ။ ဥပမာ: `30,60,100,200`\nသို့မဟုတ် /cancel",
        "edit_topup_success": "✅ ငွေဖြည့်ပမာဏများကို {amounts} ฿ သို့ ပြောင်းပြီးပါပြီ။",
    },
    "th": {
        "buy_plan": "🛒 ซื้อแพ็กเกจ",
        "topup": "💰 เติมเงิน",
        "account": "👤 บัญชี",
        "balance": "💰 ยอดเงิน",
        "contact": "📞 ติดต่อ",
        "admin_panel": "⚙️ แอดมิน",
        "language": "🌐 ภาษา",
        "back": "🔙 กลับ",
        "main_menu": "🏠 เมนูหลัก",
        "select_service": "📡 เลือกบริการ",
        "select_plan": "📦 เลือกแพ็กเกจ",
        "select_amount": "💰 เลือกจำนวนเงินเติม",
        "enter_username": "👤 *ส่ง username*\n\nอนุญาต: `A-Z a-z 0-9 _ . -`\nตัวอย่าง: `mgmg123`\n\n/cancel เพื่อยกเลิก",
        "invalid_username": "❌ Username ไม่ถูกต้อง",
        "username_exists_db": "❌ Username นี้ถูกใช้แล้ว",
        "username_exists_panel": "❌ Username นี้มีใน X-UI แล้ว",
        "insufficient_balance": "❌ ยอดเงินไม่พอ\nBalance: {balance} ฿\nPrice: {price} ฿\nNeed: {need} ฿",
        "creating_client": "⏳ กำลังสร้าง VLESS client...",
        "purchase_success": "✅ ซื้อสำเร็จ\nPackage: {plan}\nPrice: {price} ฿\nLimit: {total_gb} GB\nหมดอายุ: {expiry}\nUsername: {email}\nService: {service}",
        "vless_config": "🔐 VLESS CONFIG\n\n`{config}`",
        "copy_fallback": "\n\n📋 กดปุ่ม Copy VLESS หรือกดค้างเพื่อ copy",
        "copy_btn": "📋 Copy VLESS",
        "copy_not_supported_alert": "Telegram app นี้ไม่รองรับ direct copy กรุณากดค้างเพื่อ copy",
        "account_info": "👤 บัญชี\nจำนวน Config: {count}",
        "no_active_plan": "ไม่มีแพ็กเกจที่ใช้งานอยู่",
        "config_header": "━━━━━━ Config {idx} ━━━━━━",
        "config_status": "Package: {plan}\nUsername: {email}\nExpiry: {expiry}\nStatus: {status}\nService: {service}\nUsed: {used} / {limit}\nUUID: `{uuid}`",
        "balance_text": "💰 ยอดเงิน: {balance} ฿",
        "balance_unlimited": "💰 ยอดเงิน: ♾️ ไม่จำกัด",
        "topup_prompt": "เติมเงิน {amount} ฿\nโอนแล้วส่ง slip",
        "bank_caption": "🏦 {name}\n💳 {number}\n👤 {holder}\nจำนวน: {amount} ฿",
        "send_slip": "ส่งรูป slip",
        "topup_sent": "ส่งคำขอเติมเงินแล้ว",
        "topup_approved": "เติมเงินสำเร็จ",
        "topup_cancelled": "ยกเลิกการเติมเงิน",
        "contact_text": "📞 *ติดต่อ*\n\nTelegram: {username}\n\nกดปุ่มด้านล่างเพื่อแชท",
        "contact_btn": "📩 แชทเลย",
        "admin_add_bank": "เพิ่มธนาคาร",
        "admin_pending_topups": "คำขอที่รออนุมัติ",
        "admin_manage_banks": "จัดการธนาคาร",
        "admin_broadcast": "ส่งข้อความถึงผู้ใช้ทั้งหมด",
        "admin_edit_plans": "แก้ไขราคา",
        "admin_edit_topups": "แก้ไขจำนวนเงินเติม",
        "admin_stats": "สถิติ",
        "admin_user_mgmt": "จัดการผู้ใช้",
        "bank_name_prompt": "ชื่อธนาคาร:",
        "bank_number_prompt": "เลขบัญชี:",
        "bank_holder_prompt": "ชื่อบัญชี:",
        "bank_qr_prompt": "ส่ง QR หรือ URL หรือ /skip",
        "bank_added": "เพิ่มธนาคารสำเร็จ",
        "bank_updated": "อัปเดตธนาคารสำเร็จ",
        "no_banks": "ไม่มีธนาคาร กรุณาเพิ่มธนาคารใน Admin Panel ก่อน",
        "no_pending_topups": "ไม่มีคำขอเติมเงิน",
        "admin_note": "บันทึกหรือ /skip",
        "cancel": "ยกเลิก",
        "back_to_menu": "กลับเมนูหลัก",
        "confirm_delete": "ลบ Config?",
        "delete_confirm_btn": "ยืนยัน",
        "delete_cancel_btn": "ยกเลิก",
        "config_deleted": "ลบ {email} สำเร็จ",
        "delete_failed": "ลบไม่สำเร็จ: {error}",
        "select_lang": "เลือกภาษา:",
        "lang_my": "พม่า",
        "lang_th": "ไทย",
        "lang_en": "อังกฤษ",
        "lang_changed": "เปลี่ยนภาษาเป็น {lang}",
        "broadcast_prompt": "ส่งข้อความประชาสัมพันธ์",
        "broadcast_sending": "กำลังส่ง...",
        "broadcast_result": "ส่งเสร็จ\nส่งสำเร็จ: {sent}\nล้มเหลว: {failed}",
        "total_users": "ผู้ใช้ทั้งหมด: {count}",
        "total_online": "🟢 ออนไลน์ทั้งหมด: {count}",
        "total_offline": "🔴 ออฟไลน์ทั้งหมด: {count}",
        "list_all_users": "รายชื่อผู้ใช้ (พร้อม config)",
        "list_online_cfgs": "รายการ Config ออนไลน์",
        "list_offline_cfgs": "รายการ Config ออฟไลน์",
        "add_credit": "เพิ่มเครดิต",
        "enter_user_id": "ป้อน User ID:",
        "enter_credit_amount": "ป้อนจำนวนเงิน (บาท):",
        "credit_added": "เพิ่ม {amount} บาท ให้ผู้ใช้ {user_id} แล้ว",
        "user_not_found": "ไม่พบผู้ใช้",
        "select_service_to_view": "เลือกบริการเพื่อดู Config",
        "no_configs_for_service": "ไม่มี Config สำหรับบริการนี้",
        "config_qr_caption": "📱 *QR Code for* `{email}`\n🛜 Service: {service}\n{status_emoji} Status: {status}",
        "user_configs_title": "👤 *User ID:* `{user_id}`\n💰 ยอดเงิน: {balance} ฿\n📦 จำนวน config: {count}\n",
        "edit_topup_current": "💰 *จำนวนเงินเติมปัจจุบัน*: {amounts}\n\nส่งรายการใหม่ คั่นด้วยจุลภาค เช่น `30,60,100,200`\nหรือ /cancel",
        "edit_topup_success": "✅ อัปเดตจำนวนเงินเติมเป็น {amounts} ฿ แล้ว",
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

    def _column_exists(self, conn, table, column):
        cur = conn.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cur.fetchall())

    def _add_column_if_missing(self, conn, table, column, definition):
        if not self._column_exists(conn, table, column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
        await self.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (delta, user_id),
        )

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
        return await self.execute(
            "SELECT * FROM topup_requests WHERE status='pending' ORDER BY created_at"
        )

    async def add_client(
        self,
        user_id,
        uuid_str,
        email,
        service_name,
        inbound_id,
        total_gb,
        expiry_at,
        plan_name,
        plan_days,
        price,
    ):
        await self.execute(
            """
            INSERT INTO user_clients
            (user_id, uuid, email, service_name, inbound_id, expiry_at, total_gb, plan_name, plan_days, price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                uuid_str,
                email,
                service_name,
                inbound_id,
                expiry_at.isoformat(),
                total_gb,
                plan_name,
                plan_days,
                price,
            ),
        )

    async def get_clients(self, user_id):
        return await self.execute(
            """
            SELECT rowid, * FROM user_clients WHERE user_id=? ORDER BY created_at DESC
            """,
            (user_id,),
        )

    async def get_client_by_row_id(self, row_id):
        rows = await self.execute(
            """
            SELECT rowid, * FROM user_clients WHERE rowid=? LIMIT 1
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

    async def get_clients_by_service(self, user_id, service_name):
        return await self.execute(
            "SELECT rowid, * FROM user_clients WHERE user_id=? AND service_name=? ORDER BY created_at DESC",
            (user_id, service_name),
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
            raise Exception(f"Add client error: {result.get('msg', 'Unknown')}")
        return result

    def get_inbounds(self):
        urls = [
            f"{self.base_url}/xui/API/inbounds/list",
            f"{self.base_url}/panel/api/inbounds/list",
        ]
        for url in urls:
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
        urls = [
            f"{self.base_url}/xui/API/inbounds/onlines",
            f"{self.base_url}/panel/api/inbounds/onlines",
        ]
        for url in urls:
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
                if obj is None:
                    return set()
                if isinstance(obj, list):
                    result = set()
                    for item in obj:
                        if isinstance(item, str):
                            result.add(item.lower())
                        elif isinstance(item, dict):
                            email = item.get("email") or item.get("user") or item.get("remark")
                            if email:
                                result.add(str(email).lower())
                    return result
                if isinstance(obj, dict):
                    result = set()
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
            settings_raw = inbound.get("settings")
            if not settings_raw:
                continue
            try:
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
                ("POST", f"{self.base_url}/xui/API/inbounds/delClient/{inbound_id}/{uuid_str}", None),
                ("GET", f"{self.base_url}/xui/API/inbounds/delClient/{inbound_id}/{uuid_str}", None),
                ("POST", f"{self.base_url}/panel/api/inbounds/delClient/{inbound_id}/{uuid_str}", None),
                ("GET", f"{self.base_url}/panel/api/inbounds/delClient/{inbound_id}/{uuid_str}", None),
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
                if method == "POST":
                    resp = self.session.post(url, data=form_data, timeout=20)
                else:
                    resp = self.session.get(url, timeout=20)
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

def get_service_by_index(index):
    services = CONFIG.get("SERVICES", [])
    if 0 <= index < len(services):
        return services[index]
    return None

def get_plan_by_index(service, index):
    plans = service.get("plans", [])
    if 0 <= index < len(plans):
        return plans[index]
    return None

def get_service_config(service_name):
    for svc in CONFIG["SERVICES"]:
        if svc["name"] == service_name:
            return svc
    return None

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
    try:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton(get_text("copy_btn", lang), copy_text=CopyTextButton(text=vless_link))]]
        )
    except Exception:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton(get_text("copy_btn", lang), callback_data="copy_not_supported")]]
        )

def get_config_action_keyboard(row_id, lang):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(get_text("confirm_delete", lang), callback_data=f"delcfg_{row_id}")]]
    )

def get_delete_confirm_keyboard(row_id, lang):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(get_text("delete_confirm_btn", lang), callback_data=f"confirmdelcfg_{row_id}"),
                InlineKeyboardButton(get_text("delete_cancel_btn", lang), callback_data=f"canceldelcfg_{row_id}"),
            ]
        ]
    )

def get_contact_keyboard(lang):
    username = CONFIG.get("CONTACT_USERNAME", "@Juevpn").strip()
    clean = username[1:] if username.startswith("@") else username
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(get_text("contact_btn", lang), url=f"https://t.me/{clean}")]]
    )

def get_contact_text(lang):
    username = CONFIG.get("CONTACT_USERNAME", "@Juevpn").strip()
    if not username.startswith("@"):
        username = "@" + username
    return get_text("contact_text", lang, username=username)

def get_config_status_emoji_and_text(client, traffic, online_emails=None):
    """Return (emoji, status_text)"""
    download = int(traffic.get("downlink", client.get("download_used", 0)) or 0)
    upload = int(traffic.get("uplink", client.get("upload_used", 0)) or 0)
    total_used = download + upload
    total_limit_bytes = int(client.get("total_gb", 0) or 0)
    if total_limit_bytes == 0:
        total_limit_bytes = 150 * 1024**3
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
        is_expired = expiry < now
    else:
        is_expired = False
    traffic_exhausted = total_limit_bytes > 0 and total_used >= total_limit_bytes

    if not enabled:
        return "🔴", "Disabled"
    if is_expired:
        return "🟡", "Expired"
    if traffic_exhausted:
        return "🔴", "Traffic Finished"
    if online_emails is not None:
        email_lower = str(client["email"]).lower()
        if email_lower in online_emails:
            return "🟢", "Online"
        else:
            return "🔴", "Offline"
    return "🟢", "Online" if enabled else "🔴"

def build_client_status_text(client, traffic, lang, online_emails=None):
    service_name = client["service_name"]
    download = int(traffic.get("downlink", client.get("download_used", 0)) or 0)
    upload = int(traffic.get("uplink", client.get("upload_used", 0)) or 0)
    total_used = download + upload
    total_limit_bytes = int(client.get("total_gb", 0) or 0)
    if total_limit_bytes == 0:
        total_limit_bytes = 150 * 1024**3
    panel_expiry_ms = int(traffic.get("expiryTime", 0) or 0)
    if panel_expiry_ms > 0:
        expiry = datetime.utcfromtimestamp(panel_expiry_ms / 1000)
    elif client.get("expiry_at"):
        expiry = datetime.fromisoformat(client["expiry_at"])
    else:
        expiry = None
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
        expiry_str = "Unlimited"
    usage_percent = (total_used / total_limit_bytes * 100) if total_limit_bytes > 0 else 0
    status_emoji, status_text = get_config_status_emoji_and_text(client, traffic, online_emails)
    plan_name = client.get("plan_name") or "Package"
    limit_text = format_bytes(total_limit_bytes)
    return get_text(
        "config_status",
        lang,
        plan=plan_name,
        email=client["email"],
        expiry=expiry_str,
        status_emoji=status_emoji,
        status=status_text,
        service=service_name,
        down=format_bytes(download),
        up=format_bytes(upload),
        used=format_bytes(total_used),
        limit=limit_text,
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
    await message.reply_text(get_text("main_menu", lang), reply_markup=keyboard, parse_mode="Markdown")

async def send_main_menu_to_chat(context, chat_id, user_id, lang=None):
    if lang is None:
        lang = await db.get_user_lang(user_id)
    is_admin = await db.is_admin(user_id)
    keyboard = await get_main_keyboard(is_admin, lang)
    await context.bot.send_message(chat_id, get_text("main_menu", lang), reply_markup=keyboard, parse_mode="Markdown")

async def send_client_config_block(message_obj, client, lang):
    svc = get_service_config(client["service_name"])
    if not svc:
        raise Exception("Service config missing")
    link = generate_vless_link(client["uuid"], client["email"], svc)
    config_text = get_text("vless_config", lang, config=html.escape(link))
    keyboard = get_vless_copy_keyboard(link, lang)
    await message_obj.reply_text(
        config_text + get_text("copy_fallback", lang),
        parse_mode="Markdown",
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
    # Send pretty welcome message
    await update.message.reply_text(get_welcome_text(lang), parse_mode="Markdown")
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

    # State machine
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
    # Price editing states
    if state == "edit_plans_select_service":
        await handle_edit_plans_select_service(update, context, text)
        return
    if state == "edit_plans_select_plan":
        await handle_edit_plans_select_plan(update, context, text)
        return
    if state == "edit_plans_enter_price":
        await handle_edit_plans_enter_price(update, context, text)
        return
    # Topup amounts editing
    if state == "edit_topup_amounts":
        await handle_edit_topup_amounts(update, context, text)
        return
    # Admin add credit
    if state == "admin_add_credit_user_id":
        await handle_add_credit_user_id(update, context, text)
        return
    if state == "admin_add_credit_amount":
        await handle_add_credit_amount(update, context, text)
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
        await show_account_grouped(update, context, lang)
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
    for idx, svc in enumerate(services):
        keyboard.append([InlineKeyboardButton(svc["name"], callback_data=f"service_{idx}")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])
    await update.message.reply_text(
        get_text("select_service", lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def show_plan_selection_from_service(query, context, service_index):
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)
    service = get_service_by_index(service_index)
    if not service:
        await query.answer("Service not found.", show_alert=True)
        return
    keyboard = []
    for plan_index, plan in enumerate(service.get("plans", [])):
        btn_text = f"{plan['name']} - {plan['price']} ฿"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"buyplan_{service_index}_{plan_index}")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])
    try:
        await query.message.delete()
    except Exception:
        pass
    # Send plan selection
    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=get_text("select_plan", lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def start_buy_plan_from_plan(query, context, service_index, plan_index):
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)
    service = get_service_by_index(service_index)
    if not service:
        await query.answer("Service not found.", show_alert=True)
        return
    plan = get_plan_by_index(service, plan_index)
    if not plan:
        await query.answer("Plan not found.", show_alert=True)
        return
    context.user_data.clear()
    context.user_data["state"] = "buy_username"
    context.user_data["selected_service_index"] = service_index
    context.user_data["selected_plan_index"] = plan_index
    try:
        await query.message.delete()
    except Exception:
        pass
    # Send username prompt
    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=(f"{plan['name']} - {plan['price']} ฿\n\n" + get_text("enter_username", lang)),
        parse_mode="Markdown",
    )

async def handle_buy_username(update, context):
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)
    username = sanitize_username(text)
    service_index = context.user_data.get("selected_service_index")
    plan_index = context.user_data.get("selected_plan_index")
    service = get_service_by_index(service_index) if service_index is not None else None
    plan = get_plan_by_index(service, plan_index) if service and plan_index is not None else None
    if not service or not plan:
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
    if xui_client and xui_client.email_exists(username):
        await update.message.reply_text(get_text("username_exists_panel", lang))
        return
    await process_buy_plan(update, context, username, service, plan, lang)
    context.user_data.clear()

async def process_buy_plan(update, context, desired_username, service, plan, lang):
    user_id = update.effective_user.id
    price = int(plan.get("price", 30))
    days = int(plan.get("days", 30))
    total_gb_value = int(plan.get("total_gb", 150))
    total_bytes = total_gb_value * 1024**3
    is_admin = await db.is_admin(user_id)
    if not is_admin:
        balance = await db.get_balance(user_id)
        if balance < price:
            need = price - balance
            await update.message.reply_text(
                get_text("insufficient_balance", lang, balance=balance, price=price, need=need),
                parse_mode="Markdown",
            )
            await send_main_menu_by_message(update.message, user_id, lang)
            return
        await db.update_balance(user_id, -price)
    await update.message.reply_text(get_text("creating_client", lang))
    try:
        email = desired_username
        uuid_str = str(uuid.uuid4())
        expiry_dt = datetime.utcnow() + timedelta(days=days)
        expiry_ms = int(expiry_dt.timestamp() * 1000)
        if xui_client.email_exists(email):
            raise Exception("Username already exists in panel.")
        xui_client.add_client(
            service["inbound_id"],
            email,
            uuid_str,
            total_gb=total_bytes,
            expiry_time=expiry_ms,
        )
        await db.add_client(
            user_id=user_id,
            uuid_str=uuid_str,
            email=email,
            service_name=service["name"],
            inbound_id=service["inbound_id"],
            total_gb=total_bytes,
            expiry_at=expiry_dt,
            plan_name=plan["name"],
            plan_days=days,
            price=price,
        )
        link = generate_vless_link(uuid_str, email, service)
        qr_bytes = generate_qr_bytes(link)
        caption = get_text(
            "purchase_success",
            lang,
            plan=plan["name"],
            price=price,
            total_gb=total_gb_value,
            expiry=expiry_dt.strftime("%d %b %Y"),
            email=email,
            service=service["name"],
        )
        await update.message.reply_photo(photo=qr_bytes, caption=caption, parse_mode="Markdown")
        config_text = get_text("vless_config", lang, config=html.escape(link))
        keyboard = get_vless_copy_keyboard(link, lang)
        await update.message.reply_text(
            config_text + get_text("copy_fallback", lang),
            parse_mode="Markdown",
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
    user_id = update.effective_user.id
    is_admin = await db.is_admin(user_id)
    if is_admin:
        await update.message.reply_text(get_text("balance_unlimited", lang), parse_mode="Markdown")
    else:
        balance = await db.get_balance(user_id)
        await update.message.reply_text(get_text("balance_text", lang, balance=balance), parse_mode="Markdown")

async def show_contact(update, lang):
    await update.message.reply_text(
        get_contact_text(lang),
        parse_mode="Markdown",
        reply_markup=get_contact_keyboard(lang),
    )

async def show_language_selector(update, current_lang):
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(get_text("lang_my", current_lang), callback_data="lang_my")],
            [InlineKeyboardButton(get_text("lang_th", current_lang), callback_data="lang_th")],
            [InlineKeyboardButton(get_text("lang_en", current_lang), callback_data="lang_en")],
            [InlineKeyboardButton(get_text("back", current_lang), callback_data="menu_back")],
        ]
    )
    await update.message.reply_text(get_text("select_lang", current_lang), reply_markup=keyboard)

async def start_topup(update, lang):
    amounts = CONFIG.get("TOPUP_AMOUNTS", [30, 60, 90, 300, 500])
    keyboard = [[InlineKeyboardButton(f"💵 {a} ฿", callback_data=f"topup_amt_{a}")] for a in amounts]
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])
    await update.message.reply_text(
        get_text("select_amount", lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

# ---------- Grouped Account ----------
async def show_account_grouped(update, context, lang):
    user_id = update.effective_user.id
    services = CONFIG.get("SERVICES", [])
    keyboard = []
    for svc in services:
        count = len(await db.get_clients_by_service(user_id, svc["name"]))
        keyboard.append([InlineKeyboardButton(f"{svc['name']} ({count})", callback_data=f"acc_svc_{svc['name']}")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])
    await update.message.reply_text(
        get_text("select_service_to_view", lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def show_configs_for_service(query, context, service_name):
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)
    clients = await db.get_clients_by_service(user_id, service_name)
    if not clients:
        await query.message.reply_text(get_text("no_configs_for_service", lang))
        return
    online_emails = xui_client.get_online_emails() if xui_client else None
    for idx, client in enumerate(clients, start=1):
        traffic = xui_client.get_client_traffic(client["email"]) if xui_client else {}
        down = int(traffic.get("downlink", client.get("download_used", 0)) or 0)
        up = int(traffic.get("uplink", client.get("upload_used", 0)) or 0)
        await db.update_client_usage_by_email(client["email"], down, up)
        status_text = build_client_status_text(client, traffic, lang, online_emails)
        await query.message.reply_text(
            f"{get_text('config_header', lang, idx=idx)}\n{status_text}",
            parse_mode="Markdown",
            reply_markup=get_config_action_keyboard(client["rowid"], lang),
        )
        try:
            svc = get_service_config(client["service_name"])
            if svc:
                link = generate_vless_link(client["uuid"], client["email"], svc)
                qr_bytes = generate_qr_bytes(link)
                # Get status emoji for QR caption
                _, status_text_short = get_config_status_emoji_and_text(client, traffic, online_emails)
                emoji, _ = get_config_status_emoji_and_text(client, traffic, online_emails)
                caption = get_text("config_qr_caption", lang, email=client["email"], service=svc["name"], status_emoji=emoji, status=status_text_short)
                await query.message.reply_photo(
                    photo=qr_bytes,
                    caption=caption,
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.warning(f"QR failed: {e}")
        await send_client_config_block(query.message, client, lang)
    await query.message.reply_text(get_text("back_to_menu", lang))

# ---------- Top-up handling ----------
async def start_topup_from_callback(query, context, amount):
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)
    banks = await db.get_banks()
    if not banks:
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(query.message.chat.id, get_text("no_banks", lang))
        await send_main_menu_to_chat(context, query.message.chat.id, user_id, lang)
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
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{topup_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{topup_id}"),
            ]
        ]
    )
    mention = f"[{update.effective_user.full_name}](tg://user?id={user_id})"
    try:
        await context.bot.send_photo(
            chat_id=CONFIG["ADMIN_ID"],
            photo=file_id,
            caption=(
                f"🔔 *New Top-up Request*\n\n"
                f"👤 User: {mention}\n"
                f"💵 Amount: *{amount} ฿*\n"
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
        [InlineKeyboardButton(get_text("admin_edit_plans", lang), callback_data="admin_edit_plans")],
        [InlineKeyboardButton(get_text("admin_edit_topups", lang), callback_data="admin_edit_topups")],
        [InlineKeyboardButton(get_text("admin_stats", lang), callback_data="admin_stats")],
        [InlineKeyboardButton(get_text("admin_user_mgmt", lang), callback_data="admin_user_mgmt")],
        [InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")],
    ]
    await update.message.reply_text("⚙️ *Admin Panel*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ------- Edit Plan Prices -------
async def admin_edit_plans(query, lang):
    services = CONFIG.get("SERVICES", [])
    keyboard = []
    for idx, svc in enumerate(services):
        keyboard.append([InlineKeyboardButton(svc["name"], callback_data=f"editplan_svc_{idx}")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="admin_panel")])
    await query.message.reply_text("Select service to edit prices:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_edit_plans_select_service(query, context, service_idx):
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)
    service = get_service_by_index(int(service_idx))
    if not service:
        await query.answer("Service not found")
        return
    context.user_data["edit_plans_service_idx"] = int(service_idx)
    keyboard = []
    for plan_idx, plan in enumerate(service["plans"]):
        keyboard.append([InlineKeyboardButton(f"{plan['name']} - {plan['price']} ฿", callback_data=f"editplan_plan_{plan_idx}")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="admin_panel")])
    await query.message.reply_text(f"Edit prices for {service['name']}:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_edit_plan_price(query, context, service_idx, plan_idx):
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)
    context.user_data["state"] = "edit_plans_enter_price"
    context.user_data["edit_plans_service_idx"] = int(service_idx)
    context.user_data["edit_plans_plan_idx"] = int(plan_idx)
    await query.message.reply_text("Enter new price (in ฿):")

async def handle_edit_plans_enter_price(update, context, text):
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)
    try:
        new_price = int(text.strip())
        if new_price < 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ Invalid price. Enter a positive number.")
        return
    service_idx = context.user_data.get("edit_plans_service_idx")
    plan_idx = context.user_data.get("edit_plans_plan_idx")
    if service_idx is None or plan_idx is None:
        context.user_data.clear()
        await update.message.reply_text("Session expired.")
        await send_main_menu_by_message(update.message, user_id, lang)
        return
    service = get_service_by_index(service_idx)
    if not service or plan_idx >= len(service["plans"]):
        await update.message.reply_text("Plan not found.")
        context.user_data.clear()
        return
    service["plans"][plan_idx]["price"] = new_price
    save_config()
    await update.message.reply_text(f"✅ Price updated to {new_price} ฿ for {service['plans'][plan_idx]['name']}")
    context.user_data.clear()
    await send_main_menu_by_message(update.message, user_id, lang)

# ------- Edit Topup Amounts -------
async def admin_edit_topups(query, lang):
    current = CONFIG.get("TOPUP_AMOUNTS", [30, 60, 90, 300, 500])
    await query.message.reply_text(
        get_text("edit_topup_current", lang, amounts=", ".join(str(a) for a in current)),
        parse_mode="Markdown",
    )
    query._context.user_data["state"] = "edit_topup_amounts"

async def handle_edit_topup_amounts(update, context, text):
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)
    if text == "/cancel":
        context.user_data.clear()
        await update.message.reply_text(get_text("cancel", lang))
        await send_main_menu_by_message(update.message, user_id, lang)
        return
    try:
        amounts = [int(x.strip()) for x in text.split(",") if x.strip().isdigit()]
        if not amounts:
            raise ValueError
        CONFIG["TOPUP_AMOUNTS"] = amounts
        save_config()
        await update.message.reply_text(get_text("edit_topup_success", lang, amounts=", ".join(str(a) for a in amounts)), parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Invalid format. Use comma separated numbers, e.g. 30,60,100")
        return
    context.user_data.clear()
    await send_main_menu_by_message(update.message, user_id, lang)

# ------- Admin Statistics ----------
async def admin_stats_menu(query, lang):
    all_users = await db.get_all_users()
    total_users = len(all_users)
    online_emails = xui_client.get_online_emails() if xui_client else set()
    total_online = len(online_emails) if online_emails else 0
    # Count active (non-expired, not traffic exhausted, enabled) configs that are offline
    all_configs = []
    for user in all_users:
        configs = await db.get_clients(user["user_id"])
        all_configs.extend(configs)
    active_offline_count = 0
    now = datetime.utcnow()
    for cfg in all_configs:
        traffic = xui_client.get_client_traffic(cfg["email"]) if xui_client else {}
        status_emoji, _ = get_config_status_emoji_and_text(cfg, traffic, online_emails)
        if status_emoji == "🔴":  # offline or disabled or finished
            # But we want only active (non-expired, enabled, not finished) that are offline
            # Actually get_config_status_emoji_and_text already returns "🔴" for offline, disabled, traffic finished
            # For total_offline count we want those that are not online and not expired? Let's compute proper:
            # We'll count all configs that are not online and not expired? But later we show list.
            # Simpler: total_offline = total active configs (non-expired, enabled, not finished) that are not in online set.
        pass
    # We'll compute offline count as: active configs (non-expired, enabled, not finished) minus online configs
    active_configs = []
    for cfg in all_configs:
        # check expiry
        expiry = None
        if cfg.get("expiry_at"):
            expiry = datetime.fromisoformat(cfg["expiry_at"])
        if expiry and expiry < now:
            continue
        traffic = xui_client.get_client_traffic(cfg["email"]) if xui_client else {}
        total_limit = int(cfg.get("total_gb", 0))
        down = int(traffic.get("downlink", cfg.get("download_used", 0)) or 0)
        up = int(traffic.get("uplink", cfg.get("upload_used", 0)) or 0)
        if total_limit > 0 and (down + up) >= total_limit:
            continue
        if not traffic.get("enable", True):
            continue
        active_configs.append(cfg)
    active_online = [c for c in active_configs if c["email"].lower() in (online_emails or set())]
    total_online = len(active_online)
    total_offline = len(active_configs) - total_online
    msg = (
        f"{get_text('total_users', lang, count=total_users)}\n"
        f"{get_text('total_online', lang, count=total_online)}\n"
        f"{get_text('total_offline', lang, count=total_offline)}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text("list_all_users", lang), callback_data="admin_list_all_users")],
        [InlineKeyboardButton(get_text("list_online_cfgs", lang), callback_data="admin_list_online")],
        [InlineKeyboardButton(get_text("list_offline_cfgs", lang), callback_data="admin_list_offline")],
        [InlineKeyboardButton(get_text("add_credit", lang), callback_data="admin_add_credit")],
        [InlineKeyboardButton(get_text("back", lang), callback_data="admin_panel")],
    ])
    await query.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")

async def admin_list_all_users(query, lang):
    users = await db.get_all_users()
    if not users:
        await query.message.reply_text("No users.")
        return
    online_emails = xui_client.get_online_emails() if xui_client else set()
    for u in users:
        balance = u["balance"]
        configs = await db.get_clients(u["user_id"])
        # Build message with all configs for this user
        msg = get_text("user_configs_title", lang, user_id=u["user_id"], balance=balance, count=len(configs))
        for idx, cfg in enumerate(configs, 1):
            traffic = xui_client.get_client_traffic(cfg["email"]) if xui_client else {}
            status_emoji, status_text = get_config_status_emoji_and_text(cfg, traffic, online_emails)
            limit_gb = int(cfg.get("total_gb", 0)) // (1024**3)
            exp = cfg.get("expiry_at", "N/A")
            msg += f"\n{idx}. `{cfg['email']}` | {status_emoji} {status_text} | {limit_gb} GB | Exp: {exp[:10]}"
        # Add inline keyboard for adding credit
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text("add_credit", lang), callback_data=f"admin_add_credit_to_{u['user_id']}")]
        ])
        # Send message with configs (split if too long)
        if len(msg) > 4000:
            await query.message.reply_text(f"👤 User ID: `{u['user_id']}`, Balance: {balance} ฿, Configs: {len(configs)}", parse_mode="Markdown")
            for cfg in configs:
                traffic = xui_client.get_client_traffic(cfg["email"]) if xui_client else {}
                status_emoji, status_text = get_config_status_emoji_and_text(cfg, traffic, online_emails)
                limit_gb = int(cfg.get("total_gb", 0)) // (1024**3)
                exp = cfg.get("expiry_at", "N/A")
                await query.message.reply_text(
                    f"📧 `{cfg['email']}`\n{status_emoji} {status_text}\nGB: {limit_gb}\nExp: {exp}\nService: {cfg['service_name']}",
                    parse_mode="Markdown"
                )
                # Also send QR for each config
                try:
                    svc = get_service_config(cfg["service_name"])
                    if svc:
                        link = generate_vless_link(cfg["uuid"], cfg["email"], svc)
                        qr_bytes = generate_qr_bytes(link)
                        await query.message.reply_photo(
                            photo=qr_bytes,
                            caption=get_text("config_qr_caption", lang, email=cfg["email"], service=svc["name"], status_emoji=status_emoji, status=status_text),
                            parse_mode="Markdown",
                        )
                except Exception as e:
                    logger.warning(f"QR failed for admin list: {e}")
            await query.message.reply_text("─"*20, reply_markup=keyboard)
        else:
            await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)

async def admin_list_online_configs(query, lang):
    if not xui_client:
        await query.message.reply_text("X-UI not connected.")
        return
    online_emails = xui_client.get_online_emails() or set()
    if not online_emails:
        await query.message.reply_text("No online configs.")
        return
    all_configs = []
    users = await db.get_all_users()
    for user in users:
        configs = await db.get_clients(user["user_id"])
        all_configs.extend(configs)
    online_configs = [c for c in all_configs if c["email"].lower() in online_emails]
    if not online_configs:
        await query.message.reply_text("No matching online configs in DB.")
        return
    for cfg in online_configs:
        await query.message.reply_text(
            f"👤 User ID: `{cfg['user_id']}`\n📧 Email: `{cfg['email']}`\n🛜 Service: {cfg['service_name']}\n📅 Expiry: {cfg['expiry_at']}",
            parse_mode="Markdown"
        )

async def admin_list_offline_configs(query, lang):
    if not xui_client:
        await query.message.reply_text("X-UI not connected.")
        return
    online_emails = xui_client.get_online_emails() or set()
    users = await db.get_all_users()
    all_configs = []
    for user in users:
        configs = await db.get_clients(user["user_id"])
        all_configs.extend(configs)
    now = datetime.utcnow()
    offline = []
    for cfg in all_configs:
        expiry = None
        if cfg.get("expiry_at"):
            expiry = datetime.fromisoformat(cfg["expiry_at"])
        if expiry and expiry < now:
            continue
        traffic = xui_client.get_client_traffic(cfg["email"]) if xui_client else {}
        total_limit = int(cfg.get("total_gb", 0))
        down = int(traffic.get("downlink", cfg.get("download_used", 0)) or 0)
        up = int(traffic.get("uplink", cfg.get("upload_used", 0)) or 0)
        if total_limit > 0 and (down + up) >= total_limit:
            continue
        if not traffic.get("enable", True):
            continue
        if cfg["email"].lower() not in online_emails:
            offline.append(cfg)
    if not offline:
        await query.message.reply_text("No offline active configs.")
        return
    for cfg in offline:
        await query.message.reply_text(
            f"👤 User ID: `{cfg['user_id']}`\n📧 Email: `{cfg['email']}`\n🛜 Service: {cfg['service_name']}\n📅 Expiry: {cfg['expiry_at']}",
            parse_mode="Markdown"
        )

# ------- Admin Add Credit -------
async def admin_add_credit_start(query, context, user_id=None):
    lang = await db.get_user_lang(query.from_user.id)
    if user_id:
        context.user_data["admin_add_credit_user_id"] = user_id
        await query.message.reply_text(get_text("enter_credit_amount", lang))
        context.user_data["state"] = "admin_add_credit_amount"
    else:
        await query.message.reply_text(get_text("enter_user_id", lang))
        context.user_data["state"] = "admin_add_credit_user_id"

async def handle_add_credit_user_id(update, context, text):
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)
    try:
        target_id = int(text.strip())
    except:
        await update.message.reply_text("❌ Invalid User ID. Enter a number.")
        return
    user = await db.get_user(target_id)
    if not user:
        await update.message.reply_text(get_text("user_not_found", lang))
        context.user_data.clear()
        return
    context.user_data["admin_add_credit_user_id"] = target_id
    context.user_data["state"] = "admin_add_credit_amount"
    await update.message.reply_text(get_text("enter_credit_amount", lang))

async def handle_add_credit_amount(update, context, text):
    admin_id = update.effective_user.id
    lang = await db.get_user_lang(admin_id)
    try:
        amount = int(text.strip())
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ Enter a positive number.")
        return
    target_id = context.user_data.get("admin_add_credit_user_id")
    if not target_id:
        context.user_data.clear()
        await update.message.reply_text("Session expired.")
        return
    await db.update_balance(target_id, amount)
    await update.message.reply_text(get_text("credit_added", lang, amount=amount, user_id=target_id))
    context.user_data.clear()
    await send_main_menu_by_message(update.message, admin_id, lang)

# ================= Admin Existing =================

async def show_pending_topups(query, context, lang):
    pending = await db.get_pending_topups()
    if not pending:
        await query.message.reply_text(get_text("no_pending_topups", lang))
        return
    await query.message.reply_text(f"📋 Pending TopUps: {len(pending)}")
    for req in pending:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{req['id']}"),
                    InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{req['id']}"),
                ]
            ]
        )
        caption = (
            f"🔔 *Pending Top-up*\n\n"
            f"🆔 ID: `{req['id']}`\n"
            f"👤 User ID: `{req['user_id']}`\n"
            f"💵 Amount: *{req['amount']} ฿*\n"
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
        await update.message.reply_text(f"✅ Top-up {topup['amount']} ฿ approved.")
    else:
        await db.update_topup_status(topup_id, "cancelled")
        msg = get_text("topup_cancelled", user_lang, amount=topup["amount"])
        if note:
            msg += f"\n📝 Admin Note: {note}"
        try:
            await context.bot.send_message(topup["user_id"], msg)
        except Exception:
            pass
        await update.message.reply_text(f"❌ Top-up {topup['amount']} ฿ cancelled.")
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
            await context.bot.send_message(user["user_id"], text, parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1
    context.user_data.clear()
    await update.message.reply_text(
        get_text("broadcast_result", "en", sent=sent, failed=failed)
    )
    await send_main_menu_by_message(update.message, user_id)

# ================= Callback =================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)

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
        service_index = int(data.split("_")[1])
        await show_plan_selection_from_service(query, context, service_index)
        return

    if data.startswith("buyplan_"):
        _, svc_idx, plan_idx = data.split("_")
        await start_buy_plan_from_plan(query, context, int(svc_idx), int(plan_idx))
        return

    if data.startswith("topup_amt_"):
        amount = int(data.split("_")[2])
        await start_topup_from_callback(query, context, amount)
        return

    # Account grouped view
    if data.startswith("acc_svc_"):
        service_name = data[8:]  # after "acc_svc_"
        await show_configs_for_service(query, context, service_name)
        return

    # Config deletion
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
            logger.error(f"Delete config failed: {e}")
            await query.edit_message_text(
                get_text("delete_failed", lang, error=str(e)[:300]),
                parse_mode="Markdown",
            )
        return

    # Top-up approvals
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

    # Admin panel actions
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

    # Edit plans
    if data == "admin_edit_plans":
        await admin_edit_plans(query, lang)
        return
    if data.startswith("editplan_svc_"):
        svc_idx = data.split("_")[-1]
        await admin_edit_plans_select_service(query, context, svc_idx)
        return
    if data.startswith("editplan_plan_"):
        parts = data.split("_")
        service_idx = context.user_data.get("edit_plans_service_idx")
        if service_idx is None:
            await query.answer("Session expired")
            return
        plan_idx = int(parts[-1])
        await admin_edit_plan_price(query, context, service_idx, plan_idx)
        return
    # Edit topup amounts
    if data == "admin_edit_topups":
        await admin_edit_topups(query, lang)
        return
    # Statistics
    if data == "admin_stats":
        await admin_stats_menu(query, lang)
        return
    if data == "admin_list_all_users":
        await admin_list_all_users(query, lang)
        return
    if data == "admin_list_online":
        await admin_list_online_configs(query, lang)
        return
    if data == "admin_list_offline":
        await admin_list_offline_configs(query, lang)
        return
    if data == "admin_add_credit":
        await admin_add_credit_start(query, context)
        return
    if data.startswith("admin_add_credit_to_"):
        target_id = int(data.split("_")[-1])
        await admin_add_credit_start(query, context, target_id)
        return
    if data == "admin_panel":
        # Show admin panel again
        await query.message.reply_text("⚙️ *Admin Panel*", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text("admin_add_bank", lang), callback_data="admin_addbank")],
            [InlineKeyboardButton(get_text("admin_pending_topups", lang), callback_data="admin_pending")],
            [InlineKeyboardButton(get_text("admin_manage_banks", lang), callback_data="admin_listbanks")],
            [InlineKeyboardButton(get_text("admin_broadcast", lang), callback_data="admin_broadcast")],
            [InlineKeyboardButton(get_text("admin_edit_plans", lang), callback_data="admin_edit_plans")],
            [InlineKeyboardButton(get_text("admin_edit_topups", lang), callback_data="admin_edit_topups")],
            [InlineKeyboardButton(get_text("admin_stats", lang), callback_data="admin_stats")],
            [InlineKeyboardButton(get_text("admin_user_mgmt", lang), callback_data="admin_user_mgmt")],
            [InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")],
        ]), parse_mode="Markdown")
        return
    if data == "admin_user_mgmt":
        await admin_list_all_users(query, lang)
        return

    # Fallback
    await send_main_menu_to_chat(context, query.message.chat.id, user_id, lang)

# ================= Main =================

def main():
    global xui_client
    kill_old_bot()
    ensure_config()
    try:
        xui_client = XUIClient(
            CONFIG["PANEL_URL"],
            CONFIG["PANEL_USER"],
            CONFIG["PANEL_PASS"],
        )
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
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
