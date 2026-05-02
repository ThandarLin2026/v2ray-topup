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
    "CURRENCY_SYMBOL": "à¸¿",
    "TOPUP_AMOUNTS": [30, 60, 90, 300, 500],
    "SERVICES": [
        {
            "name": "ðŸ‡¹ðŸ‡­ AIS 64/128 KBPS { V2RAY }",
            "inbound_id": 1,
            "port": 443,
            "ws_path": "/ais",
            "server_address": "ais.example.com",
            "ws_host": "ais.example.com",
            "plans": [
                {
                    "name": "ðŸ‡¹ðŸ‡­ AIS 64/128 KBPS { 1 MONTH }",
                    "days": 30,
                    "price": 30,
                    "total_gb": 150,
                },
                {
                    "name": "ðŸ‡¹ðŸ‡­ AIS 64/128 KBPS { 2 MONTHS }",
                    "days": 60,
                    "price": 60,
                    "total_gb": 300,
                },
            ],
        },
        {
            "name": "ðŸ‡¹ðŸ‡­ TRUE VDO ZOOM { V2RAY }",
            "inbound_id": 2,
            "port": 443,
            "ws_path": "/true",
            "server_address": "true.example.com",
            "ws_host": "true.example.com",
            "plans": [
                {
                    "name": "ðŸ‡¹ðŸ‡­ TRUE VDO ZOOM { 1 MONTH }",
                    "days": 30,
                    "price": 30,
                    "total_gb": 150,
                },
                {
                    "name": "ðŸ‡¹ðŸ‡­ TRUE VDO ZOOM { 2 MONTHS }",
                    "days": 60,
                    "price": 60,
                    "total_gb": 300,
                },
            ],
        },
        {
            "name": "ðŸ‡²ðŸ‡² Myanmar All Sim Wifi { V2RAY }",
            "inbound_id": 3,
            "port": 443,
            "ws_path": "/mm",
            "server_address": "mm.example.com",
            "ws_host": "mm.example.com",
            "plans": [
                {
                    "name": "ðŸ‡²ðŸ‡² Myanmar All Sim Wifi { 1 MONTH }",
                    "days": 30,
                    "price": 30,
                    "total_gb": 150,
                },
                {
                    "name": "ðŸ‡²ðŸ‡² Myanmar All Sim Wifi { 2 MONTHS }",
                    "days": 60,
                    "price": 60,
                    "total_gb": 300,
                },
            ],
        },
    ],
    "CONTACT_USERNAME": "@Juevpn",
    "START_MESSAGE_MY": (
        "V2RAY X-UI PANEL á€™á€¾á€¬ á€€á€¼á€­á€¯á€†á€­á€¯á€•á€«á€á€šá€º\n"
        "AIS / TRUE / Myanmar All Sim Wifi Service á€™á€»á€¬á€¸ á€¡á€žá€¯á€¶á€¸á€•á€¼á€¯á€”á€­á€¯á€„á€ºá€•á€«á€á€šá€ºá‹"
    ),
    "START_MESSAGE_EN": "Welcome to V2RAY X-UI PANEL",
    "START_MESSAGE_TH": "à¸¢à¸´à¸™à¸”à¸µà¸•à¹‰à¸­à¸™à¸£à¸±à¸šà¸ªà¸¹à¹ˆ V2RAY X-UI PANEL",
}

CONFIG = DEFAULT_CONFIG.copy()


def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2, ensure_ascii=False)


def normalize_services():
    if "CURRENCY_SYMBOL" not in CONFIG or not CONFIG.get("CURRENCY_SYMBOL"):
        CONFIG["CURRENCY_SYMBOL"] = "à¸¿"

    if "TOPUP_AMOUNTS" not in CONFIG or not isinstance(CONFIG.get("TOPUP_AMOUNTS"), list):
        CONFIG["TOPUP_AMOUNTS"] = [30, 60, 90, 300, 500]

    try:
        CONFIG["TOPUP_AMOUNTS"] = sorted(
            list(set(int(a) for a in CONFIG.get("TOPUP_AMOUNTS", []) if int(a) > 0))
        )
    except Exception:
        CONFIG["TOPUP_AMOUNTS"] = [30, 60, 90, 300, 500]

    for svc in CONFIG.get("SERVICES", []):
        if "plans" not in svc or not isinstance(svc["plans"], list) or not svc["plans"]:
            svc["plans"] = [
                {
                    "name": f"{svc.get('name', 'Service')} {{ 1 MONTH }}",
                    "days": 30,
                    "price": 30,
                    "total_gb": 150,
                },
                {
                    "name": f"{svc.get('name', 'Service')} {{ 2 MONTHS }}",
                    "days": 60,
                    "price": 60,
                    "total_gb": 300,
                },
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
    print("\nðŸ”§ First-time configuration\n")

    CONFIG["BOT_TOKEN"] = input("Enter Bot Token: ").strip()
    CONFIG["ADMIN_ID"] = int(input("Enter Admin Telegram ID: ").strip())
    CONFIG["PANEL_URL"] = input("Enter X-UI Panel URL: ").strip().rstrip("/")
    CONFIG["PANEL_USER"] = input("Enter Panel Username: ").strip()
    CONFIG["PANEL_PASS"] = input("Enter Panel Password: ").strip()

    print("\nNow configure 3 services:")
    service_names = [
        "ðŸ‡¹ðŸ‡­ AIS 64/128 KBPS { V2RAY }",
        "ðŸ‡¹ðŸ‡­ TRUE VDO ZOOM { V2RAY }",
        "ðŸ‡²ðŸ‡² Myanmar All Sim Wifi { V2RAY }",
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
                    {
                        "name": svc_name.replace("{ V2RAY }", "{ 1 MONTH }"),
                        "days": 30,
                        "price": 30,
                        "total_gb": 150,
                    },
                    {
                        "name": svc_name.replace("{ V2RAY }", "{ 2 MONTHS }"),
                        "days": 60,
                        "price": 60,
                        "total_gb": 300,
                    },
                ],
            }
        )

    CONFIG["SERVICES"] = services

    contact = input("\nContact Username [default: @Juevpn]: ").strip()
    if contact:
        CONFIG["CONTACT_USERNAME"] = contact

    save_config()
    print(f"\nâœ… Saved to {CONFIG_FILE}\n")


def ensure_config():
    loaded = load_config()

    if loaded and config_is_valid():
        logger.info("config.json loaded.")
        return

    print("\nâš ï¸ config.json not found or incomplete.\n")

    if sys.stdin.isatty():
        get_config()
        if not config_is_valid():
            print("âŒ Config invalid. Please check config.json.")
            sys.exit(1)
        return

    print("âŒ Run manually first: python3 bot_updated.py")
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
        "buy_plan": "ðŸ›’ Buy Plan",
        "topup": "ðŸ’° TopUp",
        "account": "ðŸ‘¤ Account",
        "balance": "ðŸ’° Balance",
        "contact": "ðŸ“ž Contact",
        "admin_panel": "âš™ï¸ Admin Panel",
        "language": "ðŸŒ Language",
        "back": "ðŸ”™ Back",
        "main_menu": "ðŸ  Main Menu",
        "select_service": "ðŸ“¡ *Select service*",
        "select_plan": "ðŸ“¦ *Select package*",
        "select_amount": "ðŸ’° *Select top-up amount*",
        "enter_username": (
            "ðŸ‘¤ Please send username for this config.\n\n"
            "Allowed: `A-Z a-z 0-9 _ . -`\n"
            "Example: `mgmg123`\n\n"
            "Use /cancel to stop."
        ),
        "invalid_username": (
            "âŒ Invalid username.\n"
            "Only A-Z a-z 0-9 _ . - allowed.\n"
            "Length 3 to 32 characters."
        ),
        "username_exists_db": "âŒ This username is already used in bot database.",
        "username_exists_panel": "âŒ This username already exists in X-UI panel.",
        "insufficient_balance": (
            "âŒ *Insufficient balance*\n\n"
            "ðŸ’° Balance: *{balance}*\n"
            "ðŸ“¦ Price: *{price}*\n"
            "âž• Need: *{need}*"
        ),
        "creating_client": "â³ Creating VLESS client...",
        "purchase_success": (
            "âœ… *Plan Purchased Successfully!*\n\n"
            "ðŸ“¦ Package: {plan}\n"
            "ðŸ’µ Price: {price}\n"
            "ðŸ“Š Limit: {total_gb} GB\n"
            "ðŸ“… Expires: {expiry}\n"
            "ðŸ‘¤ Username: `{email}`\n"
            "ðŸ”§ Service: {service}"
        ),
        "vless_config": "ðŸ” <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        "copy_fallback": "\n\nðŸ“‹ Press the Copy VLESS button, or long press config text to copy.",
        "copy_btn": "ðŸ“‹ Copy VLESS",
        "copy_not_supported_alert": "Your Telegram app does not support direct copy. Long press config text to copy.",
        "account_info": "ðŸ‘¤ *Account Information*\n\nðŸ“¦ Total Configs: *{count}*",
        "no_active_plan": "ðŸ‘¤ *Account Information*\n\nðŸ“¡ No active plan.",
        "config_header": "â”â”â”â”â”â” Config {idx} â”â”â”â”â”â”",
        "config_status": (
            "ðŸ“¦ Package: {plan}\n"
            "ðŸ‘¤ Username: `{email}`\n"
            "ðŸ“… Expiry: {expiry}\n"
            "{status_emoji} Status: *{status}*\n"
            "ðŸ›œ Service: {service}\n\n"
            "ðŸ“Š *Traffic*\n"
            "ðŸ“¥ Download: `{down}`\n"
            "ðŸ“¤ Upload: `{up}`\n"
            "ðŸ’¾ Used: `{used} / {limit}` ({percent:.1f}%)\n\n"
            "ðŸ”‘ UUID: `{uuid}`"
        ),
        "balance_text": "ðŸ’° *Your balance:* `{balance}`",
        "topup_prompt": (
            "ðŸ’° *Top-up Amount:* `{amount}`\n\n"
            "ðŸ¦ Transfer to one bank account below, then send slip photo."
        ),
        "bank_caption": (
            "ðŸ¦ *{name}*\n"
            "ðŸ’³ `{number}`\n"
            "ðŸ‘¤ {holder}\n\n"
            "ðŸ’µ Amount: *{amount}*"
        ),
        "send_slip": "ðŸ“¸ Send payment slip photo.\nUse /cancel to stop.",
        "topup_sent": "âœ… Top-up request for {amount} sent to admin.",
        "topup_approved": "âœ… Your top-up of {amount} has been approved.",
        "topup_cancelled": "âŒ Your top-up request of {amount} was cancelled.",
        "contact_text": "ðŸ“ž Contact Support\n\nTelegram: {username}",
        "contact_btn": "ðŸ“© Open Contact",
        "admin_add_bank": "âž• Add Bank",
        "admin_pending_topups": "ðŸ“‹ Pending TopUps",
        "admin_manage_banks": "ðŸ¦ Manage Banks",
        "admin_broadcast": "ðŸ“¢ Broadcast",
        "bank_name_prompt": "ðŸ¦ Enter bank name:",
        "bank_number_prompt": "ðŸ’³ Enter account number:",
        "bank_holder_prompt": "ðŸ‘¤ Enter account holder:",
        "bank_qr_prompt": "ðŸ“· Send QR photo, image URL, or /skip.",
        "bank_added": "âœ… Bank added.",
        "bank_updated": "âœ… Bank updated.",
        "no_banks": "â„¹ï¸ No bank accounts. Admin must add a bank first.",
        "no_pending_topups": "ðŸ“­ No pending topups.",
        "admin_note": "ðŸ“ Enter note for user, or /skip.",
        "cancel": "â†©ï¸ Cancelled.",
        "back_to_menu": "â†©ï¸ Back to main menu.",
        "confirm_delete": "ðŸ—‘ Delete Config?",
        "delete_confirm_btn": "âœ… Confirm Delete",
        "delete_cancel_btn": "âŒ Cancel",
        "config_deleted": "âœ… *Config deleted successfully*\n\nðŸ‘¤ Username: `{email}`\nðŸ”‘ UUID: `{uuid}`",
        "delete_failed": "âŒ Failed to delete config.\n\nError: `{error}`",
        "select_lang": "ðŸŒ Please select language:",
        "lang_my": "ðŸ‡²ðŸ‡² Myanmar",
        "lang_th": "ðŸ‡¹ðŸ‡­ Thai",
        "lang_en": "ðŸ‡¬ðŸ‡§ English",
        "lang_changed": "âœ… Language changed to {lang}.",
        "broadcast_prompt": "ðŸ“¢ Send message to broadcast.\nUse /cancel to stop.",
        "broadcast_sending": "â³ Broadcasting...",
        "broadcast_result": "âœ… Broadcast finished.\n\nðŸ“¤ Sent: {sent}\nâŒ Failed: {failed}",
    },
    "my": {
        "buy_plan": "ðŸ›’ Package á€á€šá€ºá€›á€”á€º",
        "topup": "ðŸ’° á€„á€½á€±á€–á€¼á€Šá€·á€ºá€›á€”á€º",
        "account": "ðŸ‘¤ á€¡á€€á€±á€¬á€„á€·á€º",
        "balance": "ðŸ’° á€œá€€á€ºá€€á€»á€”á€ºá€„á€½á€±",
        "contact": "ðŸ“ž á€†á€€á€ºá€žá€½á€šá€ºá€›á€”á€º",
        "admin_panel": "âš™ï¸ Admin Panel",
        "language": "ðŸŒ á€˜á€¬á€žá€¬á€…á€€á€¬á€¸",
        "back": "ðŸ”™ á€”á€±á€¬á€€á€ºá€žá€­á€¯á€·",
        "main_menu": "ðŸ  Main Menu",
        "select_service": "ðŸ“¡ *Service á€›á€½á€±á€¸á€•á€«*",
        "select_plan": "ðŸ“¦ *Package á€›á€½á€±á€¸á€•á€«*",
        "select_amount": "ðŸ’° *á€„á€½á€±á€–á€¼á€Šá€·á€ºá€™á€Šá€·á€º á€•á€™á€¬á€ á€›á€½á€±á€¸á€•á€«*",
        "enter_username": (
            "ðŸ‘¤ á€’á€® config á€¡á€á€½á€€á€º username á€•á€­á€¯á€·á€•á€«á‹\n\n"
            "á€á€½á€„á€·á€ºá€•á€¼á€¯á€‘á€¬á€¸á€á€¬: `A-Z a-z 0-9 _ . -`\n"
            "á€¥á€•á€™á€¬: `mgmg123`\n\n"
            "/cancel á€–á€¼á€„á€·á€º á€›á€•á€ºá€”á€­á€¯á€„á€ºá€žá€Šá€ºá‹"
        ),
        "invalid_username": (
            "âŒ Username á€™á€™á€¾á€”á€ºá€•á€«á‹\n"
            "A-Z a-z 0-9 _ . - á€žá€¬ á€á€½á€„á€·á€ºá€•á€¼á€¯á€žá€Šá€ºá‹\n"
            "á€…á€¬á€œá€¯á€¶á€¸á€›á€± 3 á€™á€¾ 32 á€¡á€á€½á€„á€ºá€¸ á€–á€¼á€…á€ºá€›á€™á€Šá€ºá‹"
        ),
        "username_exists_db": "âŒ á€’á€® username á€€á€­á€¯ bot database á€‘á€²á€™á€¾á€¬ á€žá€¯á€¶á€¸á€‘á€¬á€¸á€•á€¼á€®á€¸á€•á€«á€•á€¼á€®á‹",
        "username_exists_panel": "âŒ á€’á€® username á€€ X-UI panel á€‘á€²á€™á€¾á€¬ á€›á€¾á€­á€•á€¼á€®á€¸á€žá€¬á€¸á€•á€«á‹",
        "insufficient_balance": (
            "âŒ *á€œá€€á€ºá€€á€»á€”á€ºá€„á€½á€± á€™á€œá€¯á€¶á€œá€±á€¬á€€á€ºá€•á€«*\n\n"
            "ðŸ’° á€œá€€á€ºá€€á€»á€”á€º: *{balance}*\n"
            "ðŸ“¦ á€…á€»á€±á€¸á€”á€¾á€¯á€”á€ºá€¸: *{price}*\n"
            "âž• á€œá€­á€¯á€¡á€•á€ºá€„á€½á€±: *{need}*"
        ),
        "creating_client": "â³ VLESS client á€–á€”á€ºá€á€®á€¸á€”á€±á€žá€Šá€º...",
        "purchase_success": (
            "âœ… *Package á€á€šá€ºá€šá€°á€™á€¾á€¯ á€¡á€±á€¬á€„á€ºá€™á€¼á€„á€ºá€•á€«á€•á€¼á€®!*\n\n"
            "ðŸ“¦ Package: {plan}\n"
            "ðŸ’µ á€…á€»á€±á€¸á€”á€¾á€¯á€”á€ºá€¸: {price}\n"
            "ðŸ“Š Data Limit: {total_gb} GB\n"
            "ðŸ“… á€žá€€á€ºá€á€™á€ºá€¸á€€á€¯á€”á€º: {expiry}\n"
            "ðŸ‘¤ Username: `{email}`\n"
            "ðŸ”§ Service: {service}"
        ),
        "vless_config": "ðŸ” <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        "copy_fallback": "\n\nðŸ“‹ Copy VLESS á€á€œá€¯á€á€ºá€”á€¾á€­á€•á€ºá€•á€«á‹ á€™á€›á€•á€«á€€ config á€…á€¬á€žá€¬á€¸á€€á€­á€¯ á€–á€­á€‘á€¬á€¸á€•á€¼á€®á€¸ copy á€€á€°á€¸á€•á€«á‹",
        "copy_btn": "ðŸ“‹ Copy VLESS",
        "copy_not_supported_alert": "á€žá€„á€·á€º Telegram app á€™á€¾á€¬ direct copy á€™á€›á€•á€«á‹ Config á€…á€¬á€žá€¬á€¸á€€á€­á€¯ á€–á€­á€‘á€¬á€¸á€•á€¼á€®á€¸ copy á€€á€°á€¸á€•á€«á‹",
        "account_info": "ðŸ‘¤ *á€¡á€€á€±á€¬á€„á€·á€ºá€¡á€á€»á€€á€ºá€¡á€œá€€á€º*\n\nðŸ“¦ Config á€¡á€›á€±á€¡á€á€½á€€á€º: *{count}*",
        "no_active_plan": "ðŸ‘¤ *á€¡á€€á€±á€¬á€„á€·á€ºá€¡á€á€»á€€á€ºá€¡á€œá€€á€º*\n\nðŸ“¡ Active plan á€™á€›á€¾á€­á€žá€±á€¸á€•á€«á‹",
        "config_header": "â”â”â”â”â”â” Config {idx} â”â”â”â”â”â”",
        "config_status": (
            "ðŸ“¦ Package: {plan}\n"
            "ðŸ‘¤ Username: `{email}`\n"
            "ðŸ“… Expiry: {expiry}\n"
            "{status_emoji} Status: *{status}*\n"
            "ðŸ›œ Service: {service}\n\n"
            "ðŸ“Š *Traffic*\n"
            "ðŸ“¥ Download: `{down}`\n"
            "ðŸ“¤ Upload: `{up}`\n"
            "ðŸ’¾ Used: `{used} / {limit}` ({percent:.1f}%)\n\n"
            "ðŸ”‘ UUID: `{uuid}`"
        ),
        "balance_text": "ðŸ’° *á€žá€„á€·á€ºá€œá€€á€ºá€€á€»á€”á€ºá€„á€½á€±:* `{balance}`",
        "topup_prompt": (
            "ðŸ’° *á€„á€½á€±á€–á€¼á€Šá€·á€ºá€™á€Šá€·á€ºá€•á€™á€¬á€:* `{amount}`\n\n"
            "ðŸ¦ á€¡á€±á€¬á€€á€ºá€•á€« bank account á€á€…á€ºá€á€¯á€žá€­á€¯á€· á€œá€½á€¾á€²á€•á€¼á€®á€¸ slip á€•á€­á€¯á€·á€•á€«á‹"
        ),
        "bank_caption": (
            "ðŸ¦ *{name}*\n"
            "ðŸ’³ `{number}`\n"
            "ðŸ‘¤ {holder}\n\n"
            "ðŸ’µ á€•á€™á€¬á€: *{amount}*"
        ),
        "send_slip": "ðŸ“¸ á€„á€½á€±á€œá€½á€¾á€² slip á€“á€¬á€á€ºá€•á€¯á€¶ á€•á€­á€¯á€·á€•á€«á‹\n/cancel á€–á€¼á€„á€·á€º á€›á€•á€ºá€”á€­á€¯á€„á€ºá€žá€Šá€ºá‹",
        "topup_sent": "âœ… {amount} á€„á€½á€±á€–á€¼á€Šá€·á€ºá€á€±á€¬á€„á€ºá€¸á€†á€­á€¯á€™á€¾á€¯á€€á€­á€¯ admin á€‘á€¶ á€•á€­á€¯á€·á€•á€¼á€®á€¸á€•á€«á€•á€¼á€®á‹",
        "topup_approved": "âœ… á€žá€„á€·á€º {amount} á€„á€½á€±á€–á€¼á€Šá€·á€ºá€™á€¾á€¯á€€á€­á€¯ á€¡á€á€Šá€ºá€•á€¼á€¯á€•á€¼á€®á€¸á€•á€«á€•á€¼á€®á‹",
        "topup_cancelled": "âŒ á€žá€„á€·á€º {amount} á€„á€½á€±á€–á€¼á€Šá€·á€ºá€á€±á€¬á€„á€ºá€¸á€†á€­á€¯á€™á€¾á€¯á€€á€­á€¯ á€•á€šá€ºá€–á€»á€€á€ºá€œá€­á€¯á€€á€ºá€•á€«á€žá€Šá€ºá‹",
        "contact_text": "ðŸ“ž á€†á€€á€ºá€žá€½á€šá€ºá€›á€”á€º\n\nTelegram: {username}",
        "contact_btn": "ðŸ“© Contact á€–á€½á€„á€·á€ºá€›á€”á€º",
        "admin_add_bank": "âž• Bank á€‘á€Šá€·á€ºá€›á€”á€º",
        "admin_pending_topups": "ðŸ“‹ Pending TopUps",
        "admin_manage_banks": "ðŸ¦ Bank á€™á€»á€¬á€¸á€…á€®á€™á€¶á€›á€”á€º",
        "admin_broadcast": "ðŸ“¢ Broadcast",
        "bank_name_prompt": "ðŸ¦ Bank name á€›á€­á€¯á€€á€ºá€‘á€Šá€·á€ºá€•á€«:",
        "bank_number_prompt": "ðŸ’³ Account number á€›á€­á€¯á€€á€ºá€‘á€Šá€·á€ºá€•á€«:",
        "bank_holder_prompt": "ðŸ‘¤ Account holder á€›á€­á€¯á€€á€ºá€‘á€Šá€·á€ºá€•á€«:",
        "bank_qr_prompt": "ðŸ“· QR photo, image URL, á€žá€­á€¯á€·á€™á€Ÿá€¯á€á€º /skip á€•á€­á€¯á€·á€•á€«á‹",
        "bank_added": "âœ… Bank á€‘á€Šá€·á€ºá€•á€¼á€®á€¸á€•á€«á€•á€¼á€®á‹",
        "bank_updated": "âœ… Bank á€•á€¼á€„á€ºá€•á€¼á€®á€¸á€•á€«á€•á€¼á€®á‹",
        "no_banks": "â„¹ï¸ Bank account á€™á€›á€¾á€­á€žá€±á€¸á€•á€«á‹ Admin á€€ Bank á€¡á€›á€„á€ºá€‘á€Šá€·á€ºá€•á€«á‹",
        "no_pending_topups": "ðŸ“­ Pending TopUp á€™á€›á€¾á€­á€•á€«á‹",
        "admin_note": "ðŸ“ User á€¡á€á€½á€€á€º note á€›á€­á€¯á€€á€ºá€•á€«á‹ á€™á€œá€­á€¯á€•á€«á€€ /skip á€•á€­á€¯á€·á€•á€«á‹",
        "cancel": "â†©ï¸ á€•á€šá€ºá€–á€»á€€á€ºá€œá€­á€¯á€€á€ºá€•á€«á€•á€¼á€®á‹",
        "back_to_menu": "â†©ï¸ Main Menu á€žá€­á€¯á€· á€•á€¼á€”á€ºá€žá€½á€¬á€¸á€žá€Šá€ºá‹",
        "confirm_delete": "ðŸ—‘ Config á€–á€»á€€á€ºá€™á€Šá€º?",
        "delete_confirm_btn": "âœ… á€–á€»á€€á€ºá€›á€”á€º á€¡á€á€Šá€ºá€•á€¼á€¯",
        "delete_cancel_btn": "âŒ á€™á€–á€»á€€á€ºá€á€±á€¬á€·á€•á€«",
        "config_deleted": "âœ… *Config á€€á€­á€¯ á€–á€»á€€á€ºá€•á€¼á€®á€¸á€•á€«á€•á€¼á€®*\n\nðŸ‘¤ Username: `{email}`\nðŸ”‘ UUID: `{uuid}`",
        "delete_failed": "âŒ Config á€–á€»á€€á€ºá€™á€¡á€±á€¬á€„á€ºá€™á€¼á€„á€ºá€•á€«á‹\n\nError: `{error}`",
        "select_lang": "ðŸŒ á€˜á€¬á€žá€¬á€…á€€á€¬á€¸ á€›á€½á€±á€¸á€•á€«:",
        "lang_my": "ðŸ‡²ðŸ‡² á€™á€¼á€”á€ºá€™á€¬",
        "lang_th": "ðŸ‡¹ðŸ‡­ á€‘á€­á€¯á€„á€ºá€¸",
        "lang_en": "ðŸ‡¬ðŸ‡§ English",
        "lang_changed": "âœ… á€˜á€¬á€žá€¬á€…á€€á€¬á€¸á€€á€­á€¯ {lang} á€žá€­á€¯á€· á€•á€¼á€±á€¬á€„á€ºá€¸á€•á€¼á€®á€¸á€•á€«á€•á€¼á€®á‹",
        "broadcast_prompt": "ðŸ“¢ User á€¡á€¬á€¸á€œá€¯á€¶á€¸á€žá€­á€¯á€· á€•á€­á€¯á€·á€™á€Šá€·á€º message á€›á€­á€¯á€€á€ºá€•á€«á‹\n/cancel á€–á€¼á€„á€·á€º á€›á€•á€ºá€”á€­á€¯á€„á€ºá€žá€Šá€ºá‹",
        "broadcast_sending": "â³ Broadcasting...",
        "broadcast_result": "âœ… Broadcast á€•á€¼á€®á€¸á€•á€«á€•á€¼á€®á‹\n\nðŸ“¤ Sent: {sent}\nâŒ Failed: {failed}",
    },
    "th": {
        "buy_plan": "ðŸ›’ à¸‹à¸·à¹‰à¸­à¹à¸žà¹‡à¸à¹€à¸à¸ˆ",
        "topup": "ðŸ’° à¹€à¸•à¸´à¸¡à¹€à¸‡à¸´à¸™",
        "account": "ðŸ‘¤ à¸šà¸±à¸à¸Šà¸µ",
        "balance": "ðŸ’° à¸¢à¸­à¸”à¹€à¸‡à¸´à¸™",
        "contact": "ðŸ“ž à¸•à¸´à¸”à¸•à¹ˆà¸­",
        "admin_panel": "âš™ï¸ à¹à¸­à¸”à¸¡à¸´à¸™",
        "language": "ðŸŒ à¸ à¸²à¸©à¸²",
        "back": "ðŸ”™ à¸à¸¥à¸±à¸š",
        "main_menu": "ðŸ  à¹€à¸¡à¸™à¸¹à¸«à¸¥à¸±à¸",
        "select_service": "ðŸ“¡ *à¹€à¸¥à¸·à¸­à¸à¸šà¸£à¸´à¸à¸²à¸£*",
        "select_plan": "ðŸ“¦ *à¹€à¸¥à¸·à¸­à¸à¹à¸žà¹‡à¸à¹€à¸à¸ˆ*",
        "select_amount": "ðŸ’° *à¹€à¸¥à¸·à¸­à¸à¸ˆà¸³à¸™à¸§à¸™à¹€à¸‡à¸´à¸™à¹€à¸•à¸´à¸¡*",
        "enter_username": "ðŸ‘¤ à¸ªà¹ˆà¸‡ username\n/cancel à¹€à¸žà¸·à¹ˆà¸­à¸¢à¸à¹€à¸¥à¸´à¸",
        "invalid_username": "âŒ Username à¹„à¸¡à¹ˆà¸–à¸¹à¸à¸•à¹‰à¸­à¸‡",
        "username_exists_db": "âŒ Username à¸™à¸µà¹‰à¸–à¸¹à¸à¹ƒà¸Šà¹‰à¹à¸¥à¹‰à¸§",
        "username_exists_panel": "âŒ Username à¸™à¸µà¹‰à¸¡à¸µà¹ƒà¸™ X-UI à¹à¸¥à¹‰à¸§",
        "insufficient_balance": "âŒ à¸¢à¸­à¸”à¹€à¸‡à¸´à¸™à¹„à¸¡à¹ˆà¸žà¸­\nBalance: {balance}\nPrice: {price}\nNeed: {need}",
        "creating_client": "â³ à¸à¸³à¸¥à¸±à¸‡à¸ªà¸£à¹‰à¸²à¸‡ VLESS client...",
        "purchase_success": "âœ… à¸‹à¸·à¹‰à¸­à¸ªà¸³à¹€à¸£à¹‡à¸ˆ\nPackage: {plan}\nPrice: {price}\nLimit: {total_gb} GB\nà¸«à¸¡à¸”à¸­à¸²à¸¢à¸¸: {expiry}\nUsername: `{email}`\nService: {service}",
        "vless_config": "ðŸ” <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        "copy_fallback": "\n\nðŸ“‹ à¸à¸”à¸›à¸¸à¹ˆà¸¡ Copy VLESS à¸«à¸£à¸·à¸­à¸à¸”à¸„à¹‰à¸²à¸‡à¹€à¸žà¸·à¹ˆà¸­ copy",
        "copy_btn": "ðŸ“‹ Copy VLESS",
        "copy_not_supported_alert": "Telegram app à¸™à¸µà¹‰à¹„à¸¡à¹ˆà¸£à¸­à¸‡à¸£à¸±à¸š direct copy à¸à¸£à¸¸à¸“à¸²à¸à¸”à¸„à¹‰à¸²à¸‡à¹€à¸žà¸·à¹ˆà¸­ copy",
        "account_info": "ðŸ‘¤ à¸šà¸±à¸à¸Šà¸µ\nà¸ˆà¸³à¸™à¸§à¸™ Config: {count}",
        "no_active_plan": "à¹„à¸¡à¹ˆà¸¡à¸µà¹à¸žà¹‡à¸à¹€à¸à¸ˆà¸—à¸µà¹ˆà¹ƒà¸Šà¹‰à¸‡à¸²à¸™à¸­à¸¢à¸¹à¹ˆ",
        "config_header": "â”â”â”â”â”â” Config {idx} â”â”â”â”â”â”",
        "config_status": "Package: {plan}\nUsername: `{email}`\nExpiry: {expiry}\n{status_emoji} Status: *{status}*\nService: {service}\nUsed: `{used} / {limit}`\nUUID: `{uuid}`",
        "balance_text": "ðŸ’° à¸¢à¸­à¸”à¹€à¸‡à¸´à¸™: `{balance}`",
        "topup_prompt": "à¹€à¸•à¸´à¸¡à¹€à¸‡à¸´à¸™ {amount}\nà¹‚à¸­à¸™à¹à¸¥à¹‰à¸§à¸ªà¹ˆà¸‡ slip",
        "bank_caption": "ðŸ¦ {name}\nðŸ’³ `{number}`\nðŸ‘¤ {holder}\nà¸ˆà¸³à¸™à¸§à¸™: {amount}",
        "send_slip": "à¸ªà¹ˆà¸‡à¸£à¸¹à¸› slip",
        "topup_sent": "à¸ªà¹ˆà¸‡à¸„à¸³à¸‚à¸­à¹€à¸•à¸´à¸¡à¹€à¸‡à¸´à¸™à¹à¸¥à¹‰à¸§: {amount}",
        "topup_approved": "à¹€à¸•à¸´à¸¡à¹€à¸‡à¸´à¸™à¸ªà¸³à¹€à¸£à¹‡à¸ˆ: {amount}",
        "topup_cancelled": "à¸¢à¸à¹€à¸¥à¸´à¸à¸à¸²à¸£à¹€à¸•à¸´à¸¡à¹€à¸‡à¸´à¸™: {amount}",
        "contact_text": "à¸•à¸´à¸”à¸•à¹ˆà¸­: {username}",
        "contact_btn": "à¹€à¸›à¸´à¸”à¸•à¸´à¸”à¸•à¹ˆà¸­",
        "admin_add_bank": "à¹€à¸žà¸´à¹ˆà¸¡à¸˜à¸™à¸²à¸„à¸²à¸£",
        "admin_pending_topups": "à¸„à¸³à¸‚à¸­à¸—à¸µà¹ˆà¸£à¸­à¸­à¸™à¸¸à¸¡à¸±à¸•à¸´",
        "admin_manage_banks": "à¸ˆà¸±à¸”à¸à¸²à¸£à¸˜à¸™à¸²à¸„à¸²à¸£",
        "admin_broadcast": "à¸ªà¹ˆà¸‡à¸‚à¹‰à¸­à¸„à¸§à¸²à¸¡à¸–à¸¶à¸‡à¸œà¸¹à¹‰à¹ƒà¸Šà¹‰à¸—à¸±à¹‰à¸‡à¸«à¸¡à¸”",
        "bank_name_prompt": "à¸Šà¸·à¹ˆà¸­à¸˜à¸™à¸²à¸„à¸²à¸£:",
        "bank_number_prompt": "à¹€à¸¥à¸‚à¸šà¸±à¸à¸Šà¸µ:",
        "bank_holder_prompt": "à¸Šà¸·à¹ˆà¸­à¸šà¸±à¸à¸Šà¸µ:",
        "bank_qr_prompt": "à¸ªà¹ˆà¸‡ QR à¸«à¸£à¸·à¸­ URL à¸«à¸£à¸·à¸­ /skip",
        "bank_added": "à¹€à¸žà¸´à¹ˆà¸¡à¸˜à¸™à¸²à¸„à¸²à¸£à¸ªà¸³à¹€à¸£à¹‡à¸ˆ",
        "bank_updated": "à¸­à¸±à¸›à¹€à¸”à¸•à¸˜à¸™à¸²à¸„à¸²à¸£à¸ªà¸³à¹€à¸£à¹‡à¸ˆ",
        "no_banks": "à¹„à¸¡à¹ˆà¸¡à¸µà¸˜à¸™à¸²à¸„à¸²à¸£ à¸à¸£à¸¸à¸“à¸²à¹€à¸žà¸´à¹ˆà¸¡à¸˜à¸™à¸²à¸„à¸²à¸£à¹ƒà¸™ Admin Panel à¸à¹ˆà¸­à¸™",
        "no_pending_topups": "à¹„à¸¡à¹ˆà¸¡à¸µà¸„à¸³à¸‚à¸­à¹€à¸•à¸´à¸¡à¹€à¸‡à¸´à¸™",
        "admin_note": "à¸šà¸±à¸™à¸—à¸¶à¸à¸«à¸£à¸·à¸­ /skip",
        "cancel": "à¸¢à¸à¹€à¸¥à¸´à¸",
        "back_to_menu": "à¸à¸¥à¸±à¸šà¹€à¸¡à¸™à¸¹à¸«à¸¥à¸±à¸",
        "confirm_delete": "à¸¥à¸š Config?",
        "delete_confirm_btn": "à¸¢à¸·à¸™à¸¢à¸±à¸™",
        "delete_cancel_btn": "à¸¢à¸à¹€à¸¥à¸´à¸",
        "config_deleted": "à¸¥à¸š `{email}` à¸ªà¸³à¹€à¸£à¹‡à¸ˆ",
        "delete_failed": "à¸¥à¸šà¹„à¸¡à¹ˆà¸ªà¸³à¹€à¸£à¹‡à¸ˆ: `{error}`",
        "select_lang": "à¹€à¸¥à¸·à¸­à¸à¸ à¸²à¸©à¸²:",
        "lang_my": "à¸žà¸¡à¹ˆà¸²",
        "lang_th": "à¹„à¸—à¸¢",
        "lang_en": "à¸­à¸±à¸‡à¸à¸¤à¸©",
        "lang_changed": "à¹€à¸›à¸¥à¸µà¹ˆà¸¢à¸™à¸ à¸²à¸©à¸²à¹€à¸›à¹‡à¸™ {lang}",
        "broadcast_prompt": "à¸ªà¹ˆà¸‡à¸‚à¹‰à¸­à¸„à¸§à¸²à¸¡à¸›à¸£à¸°à¸Šà¸²à¸ªà¸±à¸¡à¸žà¸±à¸™à¸˜à¹Œ",
        "broadcast_sending": "à¸à¸³à¸¥à¸±à¸‡à¸ªà¹ˆà¸‡...",
        "broadcast_result": "à¸ªà¹ˆà¸‡à¹€à¸ªà¸£à¹‡à¸ˆ\nà¸ªà¹ˆà¸‡à¸ªà¸³à¹€à¸£à¹‡à¸ˆ: {sent}\nà¸¥à¹‰à¸¡à¹€à¸«à¸¥à¸§: {failed}",
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

    async def get_all_clients(self):
        return await self.execute(
            """
            SELECT uc.rowid, uc.*, u.username, u.balance, u.lang
            FROM user_clients uc
            LEFT JOIN users u ON u.user_id = uc.user_id
            ORDER BY uc.created_at DESC
            """
        )

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
                                traffic["expiryTime"] = client.get(
                                    "expiryTime",
                                    traffic.get("expiryTime", 0),
                                )
                                traffic["total"] = client.get(
                                    "totalGB",
                                    traffic.get("total", 0),
                                )
                                traffic["email"] = client.get("email", email)
                                break

                        return traffic
            except Exception:
                pass

        return {}

    def _normalize_traffic(self, obj):
        return {
            "downlink": self._safe_int(
                obj.get("downlink", obj.get("down", obj.get("download", 0)))
            ),
            "uplink": self._safe_int(
                obj.get("uplink", obj.get("up", obj.get("upload", 0)))
            ),
            "total": self._safe_int(
                obj.get("total", obj.get("totalGB", obj.get("total_gb", 0)))
            ),
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
            candidates.extend(
                [
                    ("POST", f"{self.base_url}/xui/API/inbounds/{inbound_id}/delClient/{uuid_str}", None),
                    ("GET", f"{self.base_url}/xui/API/inbounds/{inbound_id}/delClient/{uuid_str}", None),
                    ("POST", f"{self.base_url}/panel/api/inbounds/{inbound_id}/delClient/{uuid_str}", None),
                    ("GET", f"{self.base_url}/panel/api/inbounds/{inbound_id}/delClient/{uuid_str}", None),
                    ("POST", f"{self.base_url}/xui/API/inbounds/delClient/{inbound_id}/{uuid_str}", None),
                    ("GET", f"{self.base_url}/xui/API/inbounds/delClient/{inbound_id}/{uuid_str}", None),
                    ("POST", f"{self.base_url}/panel/api/inbounds/delClient/{inbound_id}/{uuid_str}", None),
                    ("GET", f"{self.base_url}/panel/api/inbounds/delClient/{inbound_id}/{uuid_str}", None),
                ]
            )

        candidates.extend(
            [
                ("POST", f"{self.base_url}/xui/API/inbounds/delClient/{uuid_str}", None),
                ("GET", f"{self.base_url}/xui/API/inbounds/delClient/{uuid_str}", None),
                ("POST", f"{self.base_url}/panel/api/inbounds/delClient/{uuid_str}", None),
                ("GET", f"{self.base_url}/panel/api/inbounds/delClient/{uuid_str}", None),
                ("POST", f"{self.base_url}/xui/API/inbounds/delClient/", {"id": inbound_id, "clientId": uuid_str}),
                ("POST", f"{self.base_url}/panel/api/inbounds/delClient/", {"id": inbound_id, "clientId": uuid_str}),
            ]
        )

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

        raise Exception(
            "Failed to delete client from X-UI panel. Tried endpoints: "
            + " | ".join(errors[-5:])
        )

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

def currency():
    return CONFIG.get("CURRENCY_SYMBOL", "à¸¿")


def money(amount):
    try:
        amount = int(amount)
    except Exception:
        amount = 0
    return f"{amount} {currency()}"


def get_topup_amounts():
    amounts = CONFIG.get("TOPUP_AMOUNTS", [30, 60, 90, 300, 500])
    result = []
    for amount in amounts:
        try:
            amount = int(amount)
            if amount > 0:
                result.append(amount)
        except Exception:
            pass
    return sorted(list(set(result))) or [30, 60, 90, 300, 500]


def save_config_runtime():
    normalize_services()
    save_config()


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
    if index is None:
        return None
    try:
        index = int(index)
    except Exception:
        return None
    if 0 <= index < len(services):
        return services[index]
    return None


def get_plan_by_index(service, index):
    if not service:
        return None
    plans = service.get("plans", [])
    if index is None:
        return None
    try:
        index = int(index)
    except Exception:
        return None
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
            [
                [
                    InlineKeyboardButton(
                        get_text("copy_btn", lang),
                        copy_text=CopyTextButton(text=vless_link),
                    )
                ]
            ]
        )
    except Exception:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        get_text("copy_btn", lang),
                        callback_data="copy_not_supported",
                    )
                ]
            ]
        )


def get_config_action_keyboard(row_id, lang):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_text("confirm_delete", lang),
                    callback_data=f"delcfg_{row_id}",
                )
            ]
        ]
    )


def get_delete_confirm_keyboard(row_id, lang):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_text("delete_confirm_btn", lang),
                    callback_data=f"confirmdelcfg_{row_id}",
                ),
                InlineKeyboardButton(
                    get_text("delete_cancel_btn", lang),
                    callback_data=f"canceldelcfg_{row_id}",
                ),
            ]
        ]
    )


def get_contact_keyboard(lang):
    username = CONFIG.get("CONTACT_USERNAME", "@Juevpn").strip()
    clean = username[1:] if username.startswith("@") else username

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_text("contact_btn", lang),
                    url=f"https://t.me/{clean}",
                )
            ]
        ]
    )


def get_contact_text(lang):
    username = CONFIG.get("CONTACT_USERNAME", "@Juevpn").strip()
    if not username.startswith("@"):
        username = "@" + username

    return get_text("contact_text", lang, username=username)


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

    usage_percent = (total_used / total_limit_bytes * 100) if total_limit_bytes > 0 else 0
    traffic_exhausted = total_limit_bytes > 0 and total_used >= total_limit_bytes

    email_lower = str(client["email"]).lower()

    if not enabled:
        status_text = "Disabled"
        status_emoji = "ðŸ”´"
    elif is_expired:
        status_text = "Expired"
        status_emoji = "ðŸ”´"
    elif traffic_exhausted:
        status_text = "Traffic Finished"
        status_emoji = "ðŸ”´"
    else:
        if online_emails is not None:
            if email_lower in online_emails:
                status_text = "Online"
                status_emoji = "ðŸŸ¢"
            else:
                status_text = "Offline"
                status_emoji = "âšª"
        else:
            status_text = "Online" if enabled else "Offline"
            status_emoji = "ðŸŸ¢" if enabled else "âšª"

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


async def send_client_config_block_to_chat(context, chat_id, client, lang):
    svc = get_service_config(client["service_name"])
    if not svc:
        return

    link = generate_vless_link(client["uuid"], client["email"], svc)
    config_text = get_text("vless_config", lang, config=html.escape(link))
    keyboard = get_vless_copy_keyboard(link, lang)

    await context.bot.send_message(
        chat_id=chat_id,
        text=config_text + get_text("copy_fallback", lang),
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

    if state == "admin_price_text":
        await handle_admin_price_text(update, context)
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
        await update.message.reply_text("ðŸ’³ Enter new account number, or /skip:")
        return

    if state == "edit_bank_number":
        bank = context.user_data["edit_bank"]
        context.user_data["edit_bank_number"] = bank["number"] if text == "/skip" else text
        context.user_data["state"] = "edit_bank_holder"
        await update.message.reply_text("ðŸ‘¤ Enter new account holder, or /skip:")
        return

    if state == "edit_bank_holder":
        bank = context.user_data["edit_bank"]
        context.user_data["edit_bank_holder"] = bank["holder"] if text == "/skip" else text
        context.user_data["state"] = "edit_bank_qr"
        await update.message.reply_text("ðŸ“· Send new QR photo, URL, or /skip:")
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
        await show_balance(update, context, lang)
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
        keyboard.append(
            [
                InlineKeyboardButton(
                    svc["name"],
                    callback_data=f"service_{idx}",
                )
            ]
        )

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
        btn_text = f"{plan['name']} - {money(plan['price'])}"
        keyboard.append(
            [
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"buyplan_{service_index}_{plan_index}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])

    try:
        await query.message.delete()
    except Exception:
        pass

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

    await context.bot.send_message(
        chat_id=query.message.chat.id,
        text=(
            f"{plan['name']} - {money(plan['price'])}\n\n"
            + get_text("enter_username", lang)
        ),
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
        await update.message.reply_text("âŒ Buy session expired.")
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
                get_text(
                    "insufficient_balance",
                    lang,
                    balance=money(balance),
                    price=money(price),
                    need=money(need),
                ),
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
            price=money(price),
            total_gb=total_gb_value,
            expiry=expiry_dt.strftime("%d %b %Y"),
            email=email,
            service=service["name"],
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

        await update.message.reply_text(f"âŒ Failed: {str(e)[:600]}")
        await send_main_menu_by_message(update.message, user_id, lang)


async def show_balance(update, context, lang):
    user_id = update.effective_user.id

    if await db.is_admin(user_id):
        await update.message.reply_text(
            f"ðŸ’° *Admin Balance:* `Unlimited {currency()}`",
            parse_mode="Markdown",
        )
        await show_admin_stats(update.message, context, lang)
        return

    balance = await db.get_balance(user_id)

    await update.message.reply_text(
        get_text("balance_text", lang, balance=money(balance)),
        parse_mode="Markdown",
    )


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

    await update.message.reply_text(
        get_text("select_lang", current_lang),
        reply_markup=keyboard,
    )


async def start_topup(update, lang):
    amounts = get_topup_amounts()

    keyboard = [
        [InlineKeyboardButton(f"ðŸ’µ {money(a)}", callback_data=f"topup_amt_{a}")]
        for a in amounts
    ]

    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])

    await update.message.reply_text(
        get_text("select_amount", lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def show_account(update, context, lang):
    user_id = update.effective_user.id

    if await db.is_admin(user_id):
        await show_admin_stats(update.message, context, lang)
        return

    clients = await db.get_clients(user_id)

    if not clients:
        await update.message.reply_text(get_text("no_active_plan", lang), parse_mode="Markdown")
        return

    service_counts = {}
    for client in clients:
        service_counts[client["service_name"]] = service_counts.get(client["service_name"], 0) + 1

    keyboard = []

    for idx, svc in enumerate(CONFIG.get("SERVICES", [])):
        count = service_counts.get(svc["name"], 0)
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{svc['name']} ({count})",
                    callback_data=f"acctsvc_{idx}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton("ðŸ“¦ Show All Configs", callback_data="acctsvc_all")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])

    await update.message.reply_text(
        get_text("account_info", lang, count=len(clients)),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def send_user_configs_by_service(context, chat_id, user_id, lang, service_name=None):
    clients = await db.get_clients(user_id)

    if service_name:
        clients = [client for client in clients if client["service_name"] == service_name]

    if not clients:
        await context.bot.send_message(chat_id, get_text("no_active_plan", lang), parse_mode="Markdown")
        return

    await context.bot.send_message(
        chat_id,
        get_text("account_info", lang, count=len(clients)),
        parse_mode="Markdown",
    )

    online_emails = xui_client.get_online_emails() if xui_client else None

    for idx, client in enumerate(clients, start=1):
        traffic = xui_client.get_client_traffic(client["email"]) if xui_client else {}

        down = int(traffic.get("downlink", client.get("download_used", 0)) or 0)
        up = int(traffic.get("uplink", client.get("upload_used", 0)) or 0)

        await db.update_client_usage_by_email(client["email"], down, up)

        status_text = build_client_status_text(client, traffic, lang, online_emails)

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{get_text('config_header', lang, idx=idx)}\n{status_text}",
            parse_mode="Markdown",
            reply_markup=get_config_action_keyboard(client["rowid"], lang),
        )

        try:
            svc = get_service_config(client["service_name"])
            if svc:
                link = generate_vless_link(client["uuid"], client["email"], svc)
                qr_bytes = generate_qr_bytes(link)

                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=qr_bytes,
                    caption=f"ðŸ“± *QR:* `{client['email']}`",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.warning(f"QR failed: {e}")

        await send_client_config_block_to_chat(context, chat_id, client, lang)


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
        text=get_text("topup_prompt", lang, amount=money(amount)),
        parse_mode="Markdown",
    )

    for bank in banks:
        caption = get_text(
            "bank_caption",
            lang,
            name=bank["name"],
            number=bank["number"],
            holder=bank["holder"],
            amount=money(amount),
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
        await update.message.reply_text("âŒ Please send slip photo.")
        return

    amount = context.user_data.get("topup_amount")

    if not amount:
        context.user_data.clear()
        await update.message.reply_text(get_text("cancel", lang))
        await send_main_menu_by_message(update.message, user_id, lang)
        return

    file_id = update.message.photo[-1].file_id
    topup_id = await db.create_topup(user_id, amount, file_id)

    await update.message.reply_text(get_text("topup_sent", lang, amount=money(amount)))
    await send_main_menu_by_message(update.message, user_id, lang)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("âœ… Approve", callback_data=f"approve_{topup_id}"),
                InlineKeyboardButton("âŒ Cancel", callback_data=f"cancel_{topup_id}"),
            ]
        ]
    )

    mention = f"[{update.effective_user.full_name}](tg://user?id={user_id})"

    try:
        await context.bot.send_photo(
            chat_id=CONFIG["ADMIN_ID"],
            photo=file_id,
            caption=(
                f"ðŸ”” *New Top-up Request*\n\n"
                f"ðŸ‘¤ User: {mention}\n"
                f"ðŸ†” User ID: `{user_id}`\n"
                f"ðŸ’µ Amount: *{money(amount)}*\n"
                f"ðŸ†” Request ID: `{topup_id}`"
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
        [InlineKeyboardButton("ðŸ’µ Manage Plan Prices", callback_data="admin_prices")],
        [InlineKeyboardButton("ðŸ’° Manage TopUp Prices", callback_data="admin_topup_prices")],
        [InlineKeyboardButton("ðŸ“Š Users / Online / Offline", callback_data="admin_stats")],
        [InlineKeyboardButton(get_text("admin_broadcast", lang), callback_data="admin_broadcast")],
        [InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")],
    ]

    await update.message.reply_text(
        "âš™ï¸ Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_pending_topups(query, context, lang):
    pending = await db.get_pending_topups()

    if not pending:
        await query.message.reply_text(get_text("no_pending_topups", lang))
        return

    await query.message.reply_text(f"ðŸ“‹ Pending TopUps: {len(pending)}")

    for req in pending:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("âœ… Approve", callback_data=f"approve_{req['id']}"),
                    InlineKeyboardButton("âŒ Cancel", callback_data=f"cancel_{req['id']}"),
                ]
            ]
        )

        caption = (
            f"ðŸ”” *Pending Top-up*\n\n"
            f"ðŸ†” ID: `{req['id']}`\n"
            f"ðŸ‘¤ User ID: `{req['user_id']}`\n"
            f"ðŸ’µ Amount: *{money(req['amount'])}*\n"
            f"ðŸ“… Created: `{req['created_at']}`"
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
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"âœï¸ Edit {bank['name']}",
                    callback_data=f"editbank_{bank['id']}",
                ),
                InlineKeyboardButton(
                    "âŒ Delete",
                    callback_data=f"delbank_{bank['id']}",
                ),
            ]
        )

    keyboard.append([InlineKeyboardButton(get_text("admin_add_bank", lang), callback_data="admin_addbank")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])

    await query.message.reply_text(
        "ðŸ¦ *Manage Banks*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def show_admin_plan_prices(query, lang):
    keyboard = []

    for svc_idx, svc in enumerate(CONFIG.get("SERVICES", [])):
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"ðŸ“¡ {svc['name']}",
                    callback_data=f"price_svc_{svc_idx}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])

    await query.message.reply_text(
        "ðŸ’µ Select service to edit plan prices:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_admin_service_plan_prices(query, svc_idx, lang):
    service = get_service_by_index(svc_idx)
    if not service:
        await query.answer("Service not found.", show_alert=True)
        return

    keyboard = []

    for plan_idx, plan in enumerate(service.get("plans", [])):
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"âœï¸ {plan['name']} - {money(plan['price'])}",
                    callback_data=f"edit_price_{svc_idx}_{plan_idx}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="admin_prices")])

    await query.message.reply_text(
        f"ðŸ’µ Edit prices for:\n{service['name']}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_admin_topup_prices(query, lang):
    keyboard = []

    for idx, amount in enumerate(get_topup_amounts()):
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"âœï¸ {money(amount)}",
                    callback_data=f"edit_topup_price_{idx}",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton("âž• Add TopUp Amount", callback_data="add_topup_price")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])

    await query.message.reply_text(
        "ðŸ’° Manage TopUp Prices:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_admin_price_text(update, context):
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)

    if not await db.is_admin(user_id):
        context.user_data.clear()
        await update.message.reply_text("âŒ Admin only.")
        return

    text = (update.message.text or "").strip()

    try:
        new_price = int(text)
        if new_price <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text("âŒ Please enter valid number. Example: 30")
        return

    action = context.user_data.get("price_action")

    if action == "plan_price":
        svc_idx = int(context.user_data["price_service_index"])
        plan_idx = int(context.user_data["price_plan_index"])

        service = get_service_by_index(svc_idx)
        plan = get_plan_by_index(service, plan_idx)
        if not service or not plan:
            context.user_data.clear()
            await update.message.reply_text("Session expired.")
            return

        CONFIG["SERVICES"][svc_idx]["plans"][plan_idx]["price"] = new_price
        save_config_runtime()

        plan_name = CONFIG["SERVICES"][svc_idx]["plans"][plan_idx]["name"]
        context.user_data.clear()

        await update.message.reply_text(
            f"âœ… Plan price updated.\n\nðŸ“¦ {plan_name}\nðŸ’µ New Price: {money(new_price)}"
        )
        await send_main_menu_by_message(update.message, user_id, lang)
        return

    if action == "topup_price":
        idx = int(context.user_data["topup_price_index"])

        amounts = get_topup_amounts()
        if idx < 0 or idx >= len(amounts):
            context.user_data.clear()
            await update.message.reply_text("Session expired.")
            return

        amounts[idx] = new_price
        CONFIG["TOPUP_AMOUNTS"] = sorted(list(set(amounts)))
        save_config_runtime()

        context.user_data.clear()

        await update.message.reply_text(f"âœ… TopUp amount updated: {money(new_price)}")
        await send_main_menu_by_message(update.message, user_id, lang)
        return

    if action == "add_topup_price":
        amounts = get_topup_amounts()
        amounts.append(new_price)
        CONFIG["TOPUP_AMOUNTS"] = sorted(list(set(amounts)))
        save_config_runtime()

        context.user_data.clear()

        await update.message.reply_text(f"âœ… TopUp amount added: {money(new_price)}")
        await send_main_menu_by_message(update.message, user_id, lang)
        return

    context.user_data.clear()
    await update.message.reply_text("Session expired.")


async def classify_admin_clients():
    clients = await db.get_all_clients()
    online_emails = xui_client.get_online_emails() if xui_client else None

    online = []
    offline = []

    for client in clients:
        traffic = xui_client.get_client_traffic(client["email"]) if xui_client else {}

        download = int(traffic.get("downlink", client.get("download_used", 0)) or 0)
        upload = int(traffic.get("uplink", client.get("upload_used", 0)) or 0)
        total_used = download + upload
        total_limit = int(client.get("total_gb", 0) or 0)

        panel_expiry_ms = int(traffic.get("expiryTime", 0) or 0)
        if panel_expiry_ms > 0:
            expiry = datetime.utcfromtimestamp(panel_expiry_ms / 1000)
        elif client.get("expiry_at"):
            expiry = datetime.fromisoformat(client["expiry_at"])
        else:
            expiry = None

        enabled = bool(traffic.get("enable", True))
        expired = expiry and expiry < datetime.utcnow()
        traffic_finished = total_limit > 0 and total_used >= total_limit
        email_lower = str(client["email"]).lower()

        is_online = False
        if enabled and not expired and not traffic_finished:
            if online_emails is not None:
                is_online = email_lower in online_emails
            else:
                is_online = True

        if is_online:
            online.append(client)
        else:
            offline.append(client)

    return clients, online, offline


async def show_admin_stats(message_obj, context, lang):
    clients, online, offline = await classify_admin_clients()
    users = await db.get_all_users()
    total_users = len(users)

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"ðŸ‘¥ Total Users: {total_users}", callback_data="admin_view_users")],
            [InlineKeyboardButton(f"ðŸŸ¢ Total Online: {len(online)}", callback_data="admin_view_online")],
            [InlineKeyboardButton(f"âšª Total Offline: {len(offline)}", callback_data="admin_view_offline")],
            [InlineKeyboardButton(f"ðŸ“¦ All User Configs: {len(clients)}", callback_data="admin_view_allconfigs")],
        ]
    )

    text = (
        "ðŸ“Š *Admin Account Dashboard*\n\n"
        f"ðŸ’° Balance: `Unlimited {currency()}`\n"
        f"ðŸ‘¥ Total Users: `{total_users}`\n"
        f"ðŸ“¦ Total Configs: `{len(clients)}`\n"
        f"ðŸŸ¢ Total Online: `{len(online)}`\n"
        f"âšª Total Offline: `{len(offline)}`"
    )

    await message_obj.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def send_admin_client_list(context, chat_id, lang, mode="all"):
    clients, online, offline = await classify_admin_clients()

    if mode == "online":
        selected = online
        title = "ðŸŸ¢ Online Configs"
    elif mode == "offline":
        selected = offline
        title = "âšª Offline Configs"
    else:
        selected = clients
        title = "ðŸ“¦ All User Configs"

    if not selected:
        await context.bot.send_message(chat_id, f"{title}\n\nNo configs found.")
        return

    await context.bot.send_message(chat_id, f"{title}: {len(selected)}")

    online_emails = xui_client.get_online_emails() if xui_client else None

    for idx, client in enumerate(selected, start=1):
        traffic = xui_client.get_client_traffic(client["email"]) if xui_client else {}
        status_text = build_client_status_text(client, traffic, lang, online_emails)

        username = client.get("username") or "-"
        balance = client.get("balance", 0)

        text = (
            f"â”â”â”â”â”â” User Config {idx} â”â”â”â”â”â”\n"
            f"ðŸ†” User ID: `{client['user_id']}`\n"
            f"ðŸ‘¤ Telegram: `{username}`\n"
            f"ðŸ’° User Balance: `{money(balance)}`\n\n"
            f"{status_text}"
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=get_config_action_keyboard(client["rowid"], lang),
        )


async def send_admin_users_list(context, chat_id):
    users = await db.get_all_users()

    if not users:
        await context.bot.send_message(chat_id, "No users found.")
        return

    await context.bot.send_message(chat_id, f"ðŸ‘¥ Total Users: {len(users)}")

    for user in users:
        clients = await db.get_clients(user["user_id"])
        text = (
            "ðŸ‘¤ *User*\n\n"
            f"ðŸ†” User ID: `{user['user_id']}`\n"
            f"ðŸ“› Username: `{user.get('username') or '-'}`\n"
            f"ðŸ’° Balance: `{money(user.get('balance', 0))}`\n"
            f"ðŸ“¦ Configs: `{len(clients)}`"
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
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

        msg = get_text("topup_approved", user_lang, amount=money(topup["amount"]))
        if note:
            msg += f"\nðŸ“ Admin Note: {note}"

        try:
            await context.bot.send_message(topup["user_id"], msg)
        except Exception:
            pass

        await update.message.reply_text(f"âœ… Top-up {money(topup['amount'])} approved.")

    else:
        await db.update_topup_status(topup_id, "cancelled")

        msg = get_text("topup_cancelled", user_lang, amount=money(topup["amount"]))
        if note:
            msg += f"\nðŸ“ Admin Note: {note}"

        try:
            await context.bot.send_message(topup["user_id"], msg)
        except Exception:
            pass

        await update.message.reply_text(f"âŒ Top-up {money(topup['amount'])} cancelled.")

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
        await update.message.reply_text("âŒ Send photo, URL, or /skip.")
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
        await update.message.reply_text("âŒ Send photo, URL, or /skip.")
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
        await update.message.reply_text("âŒ Admin only.")
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
        _, service_index_s, plan_index_s = data.split("_")
        await start_buy_plan_from_plan(
            query,
            context,
            int(service_index_s),
            int(plan_index_s),
        )
        return

    if data.startswith("topup_amt_"):
        amount = int(data.split("_")[2])
        await start_topup_from_callback(query, context, amount)
        return

    if data.startswith("acctsvc_"):
        if data == "acctsvc_all":
            await send_user_configs_by_service(context, query.message.chat.id, user_id, lang)
            return

        service_index = int(data.split("_")[1])
        service = get_service_by_index(service_index)
        if not service:
            await query.answer("Service not found.", show_alert=True)
            return

        await send_user_configs_by_service(
            context,
            query.message.chat.id,
            user_id,
            lang,
            service_name=service["name"],
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
            await query.answer("Not allowed.", show_alert=True)
            return

        await query.edit_message_reply_markup(
            reply_markup=get_delete_confirm_keyboard(row_id, lang)
        )
        return

    if data.startswith("canceldelcfg_"):
        row_id = int(data.split("_")[1])

        await query.edit_message_reply_markup(
            reply_markup=get_config_action_keyboard(row_id, lang)
        )
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
                xui_client.delete_client(
                    client["uuid"],
                    inbound_id=client["inbound_id"],
                    email=client["email"],
                )

            await db.delete_client_by_row_id(row_id)

            await query.edit_message_text(
                get_text(
                    "config_deleted",
                    lang,
                    email=client["email"],
                    uuid=client["uuid"],
                ),
                parse_mode="Markdown",
            )

        except Exception as e:
            logger.error(f"Delete config failed: {e}")

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

    if data == "admin_prices":
        await show_admin_plan_prices(query, lang)
        return

    if data.startswith("price_svc_"):
        svc_idx = int(data.split("_")[2])
        await show_admin_service_plan_prices(query, svc_idx, lang)
        return

    if data.startswith("edit_price_"):
        _, _, svc_idx_s, plan_idx_s = data.split("_")
        svc_idx = int(svc_idx_s)
        plan_idx = int(plan_idx_s)

        service = get_service_by_index(svc_idx)
        plan = get_plan_by_index(service, plan_idx)
        if not service or not plan:
            await query.answer("Plan not found.", show_alert=True)
            return

        context.user_data.clear()
        context.user_data["state"] = "admin_price_text"
        context.user_data["price_action"] = "plan_price"
        context.user_data["price_service_index"] = svc_idx
        context.user_data["price_plan_index"] = plan_idx

        await query.message.reply_text(
            f"ðŸ’µ Enter new price for:\n{plan['name']}\n\nCurrent: {money(plan['price'])}\nExample: 30"
        )
        return

    if data == "admin_topup_prices":
        await show_admin_topup_prices(query, lang)
        return

    if data.startswith("edit_topup_price_"):
        idx = int(data.split("_")[3])
        amounts = get_topup_amounts()

        if idx < 0 or idx >= len(amounts):
            await query.answer("TopUp amount not found.", show_alert=True)
            return

        context.user_data.clear()
        context.user_data["state"] = "admin_price_text"
        context.user_data["price_action"] = "topup_price"
        context.user_data["topup_price_index"] = idx

        await query.message.reply_text(
            f"ðŸ’° Enter new TopUp amount.\n\nCurrent: {money(amounts[idx])}\nExample: 30"
        )
        return

    if data == "add_topup_price":
        context.user_data.clear()
        context.user_data["state"] = "admin_price_text"
        context.user_data["price_action"] = "add_topup_price"

        await query.message.reply_text("âž• Enter new TopUp amount.\nExample: 100")
        return

    if data == "admin_stats":
        await show_admin_stats(query.message, context, lang)
        return

    if data == "admin_view_users":
        await send_admin_users_list(context, query.message.chat.id)
        return

    if data == "admin_view_allconfigs":
        await send_admin_client_list(context, query.message.chat.id, lang, mode="all")
        return

    if data == "admin_view_online":
        await send_admin_client_list(context, query.message.chat.id, lang, mode="online")
        return

    if data == "admin_view_offline":
        await send_admin_client_list(context, query.message.chat.id, lang, mode="offline")
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

        await query.message.reply_text(
            f"âœï¸ Editing bank: {bank['name']}\n\nEnter new name, or /skip:"
        )
        return


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
        print("\nâŒ X-UI Login failed.")
        print("Check PANEL_URL, PANEL_USER, PANEL_PASS, panel path.")
        print(f"Error: {e}\n")
        sys.exit(1)

    try:
        app = Application.builder().token(CONFIG["BOT_TOKEN"]).build()
    except Exception as e:
        logger.error(f"Telegram app failed: {e}")
        print("\nâŒ BOT_TOKEN invalid.")
        print(f"Error: {e}\n")
        sys.exit(1)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started.")
    print("\nâœ… Bot started successfully.")
    print("Open Telegram and press /start.\n")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
