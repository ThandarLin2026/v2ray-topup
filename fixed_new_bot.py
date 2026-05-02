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
CURRENCY_SYMBOL = ""

DEFAULT_CONFIG = {
    "BOT_TOKEN": "",
    "ADMIN_ID": 0,
    "PANEL_URL": "",
    "PANEL_USER": "",
    "PANEL_PASS": "",
    "TOPUP_AMOUNTS": [30, 60, 90, 300, 500],
    "SERVICES": [
        {
            "name": " AIS 64/128 KBPS { V2RAY }",
            "inbound_id": 1,
            "port": 443,
            "ws_path": "/ais",
            "server_address": "ais.example.com",
            "ws_host": "ais.example.com",
            "plans": [
                {
                    "name": " AIS 64/128 KBPS { 1 MONTH }",
                    "days": 30,
                    "price": 30,
                    "total_gb": 150,
                },
                {
                    "name": " AIS 64/128 KBPS { 2 MONTHS }",
                    "days": 60,
                    "price": 60,
                    "total_gb": 300,
                },
            ],
        },
        {
            "name": " TRUE VDO ZOOM { V2RAY }",
            "inbound_id": 2,
            "port": 443,
            "ws_path": "/true",
            "server_address": "true.example.com",
            "ws_host": "true.example.com",
            "plans": [
                {
                    "name": " TRUE VDO ZOOM { 1 MONTH }",
                    "days": 30,
                    "price": 30,
                    "total_gb": 150,
                },
                {
                    "name": " TRUE VDO ZOOM { 2 MONTHS }",
                    "days": 60,
                    "price": 60,
                    "total_gb": 300,
                },
            ],
        },
        {
            "name": " Myanmar All Sim Wifi { V2RAY }",
            "inbound_id": 3,
            "port": 443,
            "ws_path": "/mm",
            "server_address": "mm.example.com",
            "ws_host": "mm.example.com",
            "plans": [
                {
                    "name": " Myanmar All Sim Wifi { 1 MONTH }",
                    "days": 30,
                    "price": 30,
                    "total_gb": 150,
                },
                {
                    "name": " Myanmar All Sim Wifi { 2 MONTHS }",
                    "days": 60,
                    "price": 60,
                    "total_gb": 300,
                },
            ],
        },
    ],
    "CONTACT_USERNAME": "@Juevpn",
    "START_MESSAGE_MY": (
        "V2RAY X-UI PANEL  \n"
        "AIS / TRUE / Myanmar All Sim Wifi Service  "
    ),
    "START_MESSAGE_EN": "Welcome to V2RAY X-UI PANEL",
    "START_MESSAGE_TH": " V2RAY X-UI PANEL",
}

CONFIG = DEFAULT_CONFIG.copy()

def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2, ensure_ascii=False)

def normalize_services():
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
        if "TOPUP_AMOUNTS" not in CONFIG:
            CONFIG["TOPUP_AMOUNTS"] = [30, 60, 90, 300, 500]
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
    print("\n First-time configuration\n")

    CONFIG["BOT_TOKEN"] = input("Enter Bot Token: ").strip()
    CONFIG["ADMIN_ID"] = int(input("Enter Admin Telegram ID: ").strip())
    CONFIG["PANEL_URL"] = input("Enter X-UI Panel URL: ").strip().rstrip("/")
    CONFIG["PANEL_USER"] = input("Enter Panel Username: ").strip()
    CONFIG["PANEL_PASS"] = input("Enter Panel Password: ").strip()
    print("\nNow configure 3 services:")
    service_names = [
        " AIS 64/128 KBPS { V2RAY }",
        " TRUE VDO ZOOM { V2RAY }",
        " Myanmar All Sim Wifi { V2RAY }",
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
    print(f"\n Saved to {CONFIG_FILE}\n")

def ensure_config():
    loaded = load_config()

    if loaded and config_is_valid():
        logger.info("config.json loaded.")
        return
    print("\n config.json not found or incomplete.\n")
    if sys.stdin.isatty():
        get_config()
        if not config_is_valid():
            print(" Config invalid. Please check config.json.")
            sys.exit(1)
        return
    print(" Run manually first: python3 bot_updated.py")
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

# replace all "THB" with currency symbol
def replace_thb(text):
    return text.replace("THB", CURRENCY_SYMBOL)

TEXTS = {
    "en": {
        "buy_plan": " Buy Plan",
        "topup": " TopUp",
        "account": " Account",
        "balance": " Balance",
        "contact": " Contact",
        "admin_panel": " Admin Panel",
        "language": " Language",
        "back": " Back",
        "main_menu": " Main Menu",
        "select_service": " Select service",
        "select_plan": " Select package",
        "select_amount": " Select top-up amount",
        "enter_username": (
            " Please send username for this config.\n\n"
            "Allowed: A-Z a-z 0-9 _ . -\n"
            "Example: mgmg123\n\n"
            "Use /cancel to stop."
        ),
        "invalid_username": (
            " Invalid username.\n"
            "Only A-Z a-z 0-9 _ . - allowed.\n"
            "Length 3 to 32 characters."
        ),
        "username_exists_db": " This username is already used in bot database.",
        "username_exists_panel": " This username already exists in X-UI panel.",
        "insufficient_balance": (
            " Insufficient balance\n\n"
            " Balance: {balance} {symbol}\n"
            " Price: {price} {symbol}\n"
            " Need: {need} {symbol}"
        ),
        "creating_client": " Creating VLESS client...",
        "purchase_success": (
            " Plan Purchased Successfully!\n\n"
            " Package: {plan}\n"
            " Price: {price} {symbol}\n"
            " Limit: {total_gb} GB\n"
            " Expires: {expiry}\n"
            " Username: {email}\n"
            " Service: {service}"
        ),
        "vless_config": " VLESS CONFIG\n\n{config}",
        "copy_fallback": "\n\n Press the Copy VLESS button, or long press config text to copy.",
        "copy_btn": "Copy VLESS",
        "copy_not_supported_alert": "Your Telegram app does not support direct copy. Long press config text to copy.",
        "account_info": " Account Information\n\n Total Configs: {count}",
        "no_active_plan": " Account Information\n\n No active plan.",
        "config_header": " Config {idx} ",
        "config_status": (
            " Package: {plan}\n"
            " Username: {email}\n"
            " Expiry: {expiry}\n"
            "{status_emoji} Status: {status}\n"
            " Service: {service}\n\n"
            " Traffic\n"
            " Download: {down}\n"
            " Upload: {up}\n"
            " Used: {used} / {limit} ({percent:.1f}%)\n\n"
            " UUID: {uuid}"
        ),
        "balance_text": " Your balance: {balance} {symbol}",
        "topup_prompt": (
            " Top-up Amount: {amount} {symbol}\n\n"
            " Transfer to one bank account below, then send slip photo."
        ),
        "bank_caption": (
            " {name}\n"
            " {number}\n"
            " {holder}\n\n"
            " Amount: {amount} {symbol}"
        ),
        "send_slip": " Send payment slip photo.\nUse /cancel to stop.",
        "topup_sent": " Top-up request for {amount} {symbol} sent to admin.",
        "topup_approved": " Your top-up of {amount} {symbol} has been approved.",
        "topup_cancelled": " Your top-up request of {amount} {symbol} was cancelled.",
        "contact_text": " Contact Support\n\nTelegram: {username}",
        "contact_btn": " Open Contact",
        "admin_add_bank": " Add Bank",
        "admin_pending_topups": " Pending TopUps",
        "admin_manage_banks": " Manage Banks",
        "admin_broadcast": " Broadcast",
        "admin_edit_prices": " Edit Prices",
        "admin_edit_topup_amounts": " Edit Topup Amounts",
        "admin_stats": " Statistics",
        "bank_name_prompt": " Enter bank name:",
        "bank_number_prompt": " Enter account number:",
        "bank_holder_prompt": " Enter account holder:",
        "bank_qr_prompt": " Send QR photo, image URL, or /skip.",
        "bank_added": " Bank added.",
        "bank_updated": " Bank updated.",
        "no_banks": " No bank accounts. Admin must add a bank first.",
        "no_pending_topups": " No pending topups.",
        "admin_note": " Enter note for user, or /skip.",
        "cancel": " Cancelled.",
        "back_to_menu": " Back to main menu.",
        "confirm_delete": " Delete Config?",
        "delete_confirm_btn": " Confirm Delete",
        "delete_cancel_btn": " Cancel",
        "config_deleted": " Config deleted successfully\n\n Username: {email}\n UUID: {uuid}",
        "delete_failed": " Failed to delete config.\n\nError: {error}",
        "select_lang": " Please select language:",
        "lang_my": " Myanmar",
        "lang_th": " Thai",
        "lang_en": " English",
        "lang_changed": " Language changed to {lang}.",
        "broadcast_prompt": " Send message to broadcast.\nUse /cancel to stop.",
        "broadcast_sending": " Broadcasting...",
        "broadcast_result": " Broadcast finished.\n\n Sent: {sent}\n Failed: {failed}",
        "select_service_for_account": " Select service to view configs",
        "total_users": " Total Users",
        "total_online": " Total Online",
        "total_offline": " Total Offline",
        "all_user_configs": " All User Configs",
        "page": "Page {page}/{total_pages}",
        "prev": " Prev",
        "next": "Next ",
        "add_credit": " Add Credit",
        "enter_credit_amount": " Enter amount to add (in {symbol}):",
        "credit_added": " Added {amount} {symbol} to user {user_id}",
        "unlimited_balance": " Balance:  (Unlimited)",
    },
    "my": {
        "buy_plan": " Package ",
        "topup": " ",
        "account": " ",
        "balance": " ",
        "contact": " ",
        "admin_panel": " Admin Panel",
        "language": " ",
        "back": " ",
        "main_menu": " Main Menu",
        "select_service": " Service ",
        "select_plan": " Package ",
        "select_amount": "   ",
        "enter_username": (
            "  config  username \n\n"
            ": A-Z a-z 0-9 _ . -\n"
            ": mgmg123\n\n"
            "/cancel  "
        ),
        "invalid_username": (
            " Username \n"
            "A-Z a-z 0-9 _ . -  \n"
            " 3  32  "
        ),
        "username_exists_db": "  username  bot database  ",
        "username_exists_panel": "  username  X-UI panel  ",
        "insufficient_balance": (
            "  \n\n"
            " : {balance} {symbol}\n"
            " : {price} {symbol}\n"
            " : {need} {symbol}"
        ),
        "creating_client": " VLESS client ...",
        "purchase_success": (
            " Package  !\n\n"
            " Package: {plan}\n"
            " : {price} {symbol}\n"
            " Data Limit: {total_gb} GB\n"
            " : {expiry}\n"
            " Username: {email}\n"
            " Service: {service}"
        ),
        "vless_config": " VLESS CONFIG\n\n{config}",
        "copy_fallback": "\n\n Copy VLESS   config   copy ",
        "copy_btn": " Copy VLESS",
        "copy_not_supported_alert": " Telegram app  direct copy  Config   copy ",
        "account_info": " \n\n Config : {count}",
        "no_active_plan": " \n\n Active plan ",
        "config_header": " Config {idx} ",
        "config_status": (
            " Package: {plan}\n"
            " Username: {email}\n"
            " Expiry: {expiry}\n"
            "{status_emoji} Status: {status}\n"
            " Service: {service}\n\n"
            " Traffic\n"
            " Download: {down}\n"
            " Upload: {up}\n"
            " Used: {used} / {limit} ({percent:.1f}%)\n\n"
            " UUID: {uuid}"
        ),
        "balance_text": " : {balance} {symbol}",
        "topup_prompt": (
            " : {amount} {symbol}\n\n"
            "  bank account   slip "
        ),
        "bank_caption": (
            " {name}\n"
            " {number}\n"
            " {holder}\n\n"
            " : {amount} {symbol}"
        ),
        "send_slip": "  slip  \n/cancel  ",
        "topup_sent": " {amount} {symbol}  admin  ",
        "topup_approved": "  {amount} {symbol}  ",
        "topup_cancelled": "  {amount} {symbol}  ",
        "contact_text": " \n\nTelegram: {username}",
        "contact_btn": " Contact ",
        "admin_add_bank": " Bank ",
        "admin_pending_topups": " Pending TopUps",
        "admin_manage_banks": " Bank ",
        "admin_broadcast": " Broadcast",
        "admin_edit_prices": " Price ",
        "admin_edit_topup_amounts": " Topup ",
        "admin_stats": " ",
        "bank_name_prompt": " Bank name :",
        "bank_number_prompt": " Account number :",
        "bank_holder_prompt": " Account holder :",
        "bank_qr_prompt": " QR photo, image URL,  /skip ",
        "bank_added": " Bank ",
        "bank_updated": " Bank ",
        "no_banks": " Bank account  Admin  Bank ",
        "no_pending_topups": " Pending TopUp ",
        "admin_note": " User  note   /skip ",
        "cancel": " ",
        "back_to_menu": " Main Menu  ",
        "confirm_delete": " Config ?",
        "delete_confirm_btn": "  ",
        "delete_cancel_btn": " ",
        "config_deleted": " Config  \n\n Username: {email}\n UUID: {uuid}",
        "delete_failed": " Config \n\nError: {error}",
        "select_lang": "  :",
        "lang_my": " ",
        "lang_th": " ",
        "lang_en": " English",
        "lang_changed": "  {lang}  ",
        "broadcast_prompt": " User   message \n/cancel  ",
        "broadcast_sending": " Broadcasting...",
        "broadcast_result": " Broadcast \n\n Sent: {sent}\n Failed: {failed}",
        "select_service_for_account": " Config  Service ",
        "total_users": " ",
        "total_online": " ",
        "total_offline": " ",
        "all_user_configs": " User Config ",
        "page": " {page}/{total_pages}",
        "prev": " ",
        "next": " ",
        "add_credit": " ",
        "enter_credit_amount": "  ({symbol}) :",
        "credit_added": "  {user_id}  {amount} {symbol} ",
        "unlimited_balance": " :  ()",
    },
    "th": {
        "buy_plan": " ",
        "topup": " ",
        "account": " ",
        "balance": " ",
        "contact": " ",
        "admin_panel": " ",
        "language": " ",
        "back": " ",
        "main_menu": " ",
        "select_service": " ",
        "select_plan": " ",
        "select_amount": " ",
        "enter_username": "  username\n/cancel ",
        "invalid_username": " Username ",
        "username_exists_db": " Username ",
        "username_exists_panel": " Username  X-UI ",
        "insufficient_balance": " \nBalance: {balance} {symbol}\nPrice: {price} {symbol}\nNeed: {need} {symbol}",
        "creating_client": "  VLESS client...",
        "purchase_success": " \nPackage: {plan}\nPrice: {price} {symbol}\nLimit: {total_gb} GB\n: {expiry}\nUsername: {email}\nService: {service}",
        "vless_config": " VLESS CONFIG\n\n{config}",
        "copy_fallback": "\n\n  Copy VLESS  copy",
        "copy_btn": " Copy VLESS",
        "copy_not_supported_alert": "Telegram app  direct copy  copy",
        "account_info": " \n Config: {count}",
        "no_active_plan": "",
        "config_header": " Config {idx} ",
        "config_status": "Package: {plan}\nUsername: {email}\nExpiry: {expiry}\nStatus: {status}\nService: {service}\nUsed: {used} / {limit}\nUUID: {uuid}",
        "balance_text": " : {balance} {symbol}",
        "topup_prompt": " {amount} {symbol}\n slip",
        "bank_caption": " {name}\n {number}\n {holder}\n: {amount} {symbol}",
        "send_slip": " slip",
        "topup_sent": "",
        "topup_approved": "",
        "topup_cancelled": "",
        "contact_text": ": {username}",
        "contact_btn": "",
        "admin_add_bank": "",
        "admin_pending_topups": "",
        "admin_manage_banks": "",
        "admin_broadcast": "",
        "admin_edit_prices": "",
        "admin_edit_topup_amounts": "",
        "admin_stats": "",
        "bank_name_prompt": ":",
        "bank_number_prompt": ":",
        "bank_holder_prompt": ":",
        "bank_qr_prompt": " QR  URL  /skip",
        "bank_added": "",
        "bank_updated": "",
        "no_banks": "  Admin Panel ",
        "no_pending_topups": "",
        "admin_note": " /skip",
        "cancel": "",
        "back_to_menu": "",
        "confirm_delete": " Config?",
        "delete_confirm_btn": "",
        "delete_cancel_btn": "",
        "config_deleted": " {email} ",
        "delete_failed": ": {error}",
        "select_lang": ":",
        "lang_my": "",
        "lang_th": "",
        "lang_en": "",
        "lang_changed": " {lang}",
        "broadcast_prompt": "",
        "broadcast_sending": "...",
        "broadcast_result": "\n: {sent}\n: {failed}",
        "select_service_for_account": " config",
        "total_users": "",
        "total_online": "",
        "total_offline": "",
        "all_user_configs": "",
        "page": " {page}/{total_pages}",
        "prev": " ",
        "next": " ",
        "add_credit": " ",
        "enter_credit_amount": "  ({symbol}):",
        "credit_added": "  {amount} {symbol}  {user_id} ",
        "unlimited_balance": " :  ()",
    },
}

def get_text(key, lang="en", **kwargs):
    lang_dict = TEXTS.get(lang, TEXTS["en"])
    text = lang_dict.get(key, TEXTS["en"].get(key, key))

    if kwargs:
        # inject symbol automatically if not provided
        if "symbol" not in kwargs:
            kwargs["symbol"] = CURRENCY_SYMBOL
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
            INSERT INTO user_clients (user_id, uuid, email, service_name, inbound_id, expiry_at, total_gb, plan_name, plan_days, price)
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

    async def get_all_clients(self):
        return await self.execute(
            """
            SELECT rowid, * FROM user_clients ORDER BY created_at DESC
            """
        )

    async def get_clients_by_service(self, service_name):
        return await self.execute(
            "SELECT rowid, * FROM user_clients WHERE service_name=? ORDER BY created_at DESC",
            (service_name,),
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
                            "expiryTime", traffic.get("expiryTime", 0)
                        )
                        traffic["total"] = client.get(
                            "totalGB", traffic.get("total", 0)
                        )
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
            "Failed to delete client from X-UI panel. Tried endpoints: " + " | ".join(errors[-5:])
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
        status_emoji = ""
    elif is_expired:
        status_text = "Expired"
        status_emoji = ""
    elif traffic_exhausted:
        status_text = "Traffic Finished"
        status_emoji = ""
    else:
        if online_emails is not None:
            if email_lower in online_emails:
                status_text = "Online"
                status_emoji = ""
            else:
                status_text = "Offline"
                status_emoji = ""
        else:
            status_text = "Online" if enabled else "Offline"
            status_emoji = "" if enabled else ""
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
        await update.message.reply_text(" Enter new account number, or /skip:")
        return
    if state == "edit_bank_number":
        bank = context.user_data["edit_bank"]
        context.user_data["edit_bank_number"] = bank["number"] if text == "/skip" else text
        context.user_data["state"] = "edit_bank_holder"
        await update.message.reply_text(" Enter new account holder, or /skip:")
        return
    if state == "edit_bank_holder":
        bank = context.user_data["edit_bank"]
        context.user_data["edit_bank_holder"] = bank["holder"] if text == "/skip" else text
        context.user_data["state"] = "edit_bank_qr"
        await update.message.reply_text(" Send new QR photo, URL, or /skip:")
        return
    if state == "edit_bank_qr":
        await handle_edit_bank_qr(update, context)
        return
    if state == "broadcast":
        await handle_broadcast(update, context)
        return
    if state == "add_credit":
        await handle_add_credit_amount(update, context)
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
        await show_account_service_selector(update, lang)
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
        keyboard.append(
            [
                InlineKeyboardButton(
                    svc["name"], callback_data=f"service_{idx}"
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
        btn_text = f"{plan['name']} - {plan['price']} {CURRENCY_SYMBOL}"
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
            f"{plan['name']} - {plan['price']} {CURRENCY_SYMBOL}\n\n"
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
        await update.message.reply_text(" Buy session expired.")
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
                    "insufficient_balance", lang,
                    balance=balance, price=price, need=need,
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
            "purchase_success", lang,
            plan=plan["name"], price=price, total_gb=total_gb_value,
            expiry=expiry_dt.strftime("%d %b %Y"), email=email, service=service["name"],
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
        await update.message.reply_text(f" Failed: {str(e)[:600]}")
        await send_main_menu_by_message(update.message, user_id, lang)

async def show_balance(update, lang):
    user_id = update.effective_user.id
    if await db.is_admin(user_id):
        await update.message.reply_text(get_text("unlimited_balance", lang), parse_mode="Markdown")
    else:
        balance = await db.get_balance(user_id)
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
    amounts = CONFIG.get("TOPUP_AMOUNTS", [30, 60, 90, 300, 500])

    keyboard = [[InlineKeyboardButton(f" {a} {CURRENCY_SYMBOL}", callback_data=f"topup_amt_{a}")] for a in amounts]
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])
    await update.message.reply_text(
        get_text("select_amount", lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

# ===== Grouped Account Display =====
async def show_account_service_selector(update, lang):
    services = CONFIG.get("SERVICES", [])
    keyboard = []
    for svc in services:
        keyboard.append([InlineKeyboardButton(svc["name"], callback_data=f"acc_service_{svc['name']}")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])
    await update.message.reply_text(
        get_text("select_service_for_account", lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def show_account_for_service(query, context, service_name):
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)
    clients = await db.get_clients_by_service(service_name)
    if not clients:
        await query.answer("No configs for this service.", show_alert=True)
        return
    await query.answer()
    await query.message.reply_text(get_text("account_info", lang, count=len(clients)), parse_mode="Markdown")
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
                await query.message.reply_photo(
                    photo=qr_bytes,
                    caption=f" *QR:* `{client['email']}`",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.warning(f"QR failed: {e}")
        await send_client_config_block(query.message, client, lang)

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
            "bank_caption", lang,
            name=bank["name"], number=bank["number"], holder=bank["holder"], amount=amount,
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
        await update.message.reply_text(" Please send slip photo.")
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
                InlineKeyboardButton(" Approve", callback_data=f"approve_{topup_id}"),
                InlineKeyboardButton(" Cancel", callback_data=f"cancel_{topup_id}"),
            ]
        ]
    )
    mention = f"[{update.effective_user.full_name}](tg://user?id={user_id})"
    try:
        await context.bot.send_photo(
            chat_id=CONFIG["ADMIN_ID"],
            photo=file_id,
            caption=(
                f" *New Top-up Request*\n\n"
                f" User: {mention}\n"
                f" Amount: *{amount} {CURRENCY_SYMBOL}*\n"
                f" Request ID: `{topup_id}`"
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
        [InlineKeyboardButton(get_text("admin_edit_prices", lang), callback_data="admin_editprices")],
        [InlineKeyboardButton(get_text("admin_edit_topup_amounts", lang), callback_data="admin_edittopup")],
        [InlineKeyboardButton(get_text("admin_broadcast", lang), callback_data="admin_broadcast")],
        [InlineKeyboardButton(get_text("admin_stats", lang), callback_data="admin_stats")],
        [InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")],
    ]

    await update.message.reply_text(
        " Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def show_pending_topups(query, context, lang):
    pending = await db.get_pending_topups()

    if not pending:
        await query.message.reply_text(get_text("no_pending_topups", lang))
        return
    await query.message.reply_text(f" Pending TopUps: {len(pending)}")
    for req in pending:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(" Approve", callback_data=f"approve_{req['id']}"),
                    InlineKeyboardButton(" Cancel", callback_data=f"cancel_{req['id']}"),
                ]
            ]
        )
        caption = (
            f" *Pending Top-up*\n\n"
            f" ID: `{req['id']}`\n"
            f" User ID: `{req['user_id']}`\n"
            f" Amount: *{req['amount']} {CURRENCY_SYMBOL}*\n"
            f" Created: `{req['created_at']}`"
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
                    f" Edit {bank['name']}", callback_data=f"editbank_{bank['id']}",
                ),
                InlineKeyboardButton(
                    " Delete", callback_data=f"delbank_{bank['id']}",
                ),
            ]
        )
    keyboard.append([InlineKeyboardButton(get_text("admin_add_bank", lang), callback_data="admin_addbank")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="menu_back")])
    await query.message.reply_text(
        " *Manage Banks*",
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
            msg += f"\n Admin Note: {note}"
        try:
            await context.bot.send_message(topup["user_id"], msg)
        except Exception:
            pass
        await update.message.reply_text(f" Top-up {topup['amount']} {CURRENCY_SYMBOL} approved.")
    else:
        await db.update_topup_status(topup_id, "cancelled")
        msg = get_text("topup_cancelled", user_lang, amount=topup["amount"])
        if note:
            msg += f"\n Admin Note: {note}"
        try:
            await context.bot.send_message(topup["user_id"], msg)
        except Exception:
            pass
        await update.message.reply_text(f" Top-up {topup['amount']} {CURRENCY_SYMBOL} cancelled.")
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
        await update.message.reply_text(" Send photo, URL, or /skip.")
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
        await update.message.reply_text(" Send photo, URL, or /skip.")
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
        await update.message.reply_text(" Admin only.")
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

# ===== Admin Price Editing =====
async def admin_edit_prices(query, context, lang):
    services = CONFIG.get("SERVICES", [])
    keyboard = []
    for svc_idx, svc in enumerate(services):
        for plan_idx, plan in enumerate(svc.get("plans", [])):
            btn_text = f"{svc['name']} - {plan['name']}: {plan['price']} {CURRENCY_SYMBOL}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"editprice_{svc_idx}_{plan_idx}")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="admin_panel")])
    await query.message.edit_text(" Select plan to edit price:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_edit_price_prompt(query, context, svc_idx, plan_idx):
    lang = await db.get_user_lang(query.from_user.id)
    service = CONFIG["SERVICES"][svc_idx]
    plan = service["plans"][plan_idx]
    context.user_data["edit_price_svc_idx"] = svc_idx
    context.user_data["edit_price_plan_idx"] = plan_idx
    context.user_data["state"] = "edit_price"
    await query.message.reply_text(f"Current price: {plan['price']} {CURRENCY_SYMBOL}\nEnter new price (number only):")

# add to message handler
async def handle_edit_price(update, context):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        return
    try:
        new_price = int(update.message.text.strip())
        svc_idx = context.user_data.get("edit_price_svc_idx")
        plan_idx = context.user_data.get("edit_price_plan_idx")
        if svc_idx is None or plan_idx is None:
            raise ValueError
        CONFIG["SERVICES"][svc_idx]["plans"][plan_idx]["price"] = new_price
        save_config()
        await update.message.reply_text(f" Price updated to {new_price} {CURRENCY_SYMBOL}")
    except Exception:
        await update.message.reply_text(" Invalid price. Must be a number.")
    context.user_data.clear()
    await send_main_menu_by_message(update.message, user_id)

async def admin_edit_topup_amounts(query, context, lang):
    amounts = CONFIG.get("TOPUP_AMOUNTS", [])
    keyboard = []
    for amt in amounts:
        keyboard.append([InlineKeyboardButton(f"{amt} {CURRENCY_SYMBOL} - Delete", callback_data=f"del_topup_{amt}")])
    keyboard.append([InlineKeyboardButton(" Add New", callback_data="add_topup")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="admin_panel")])
    await query.message.edit_text(" Edit Topup Amounts:\nClick amount to delete, or add new.", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_add_topup_prompt(query, context, lang):
    context.user_data["state"] = "add_topup"
    await query.message.reply_text(f"Enter new topup amount (number, {CURRENCY_SYMBOL}):")

async def handle_add_topup_amount(update, context):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        return
    try:
        new_amt = int(update.message.text.strip())
        if new_amt <= 0:
            raise ValueError
        amounts = CONFIG.get("TOPUP_AMOUNTS", [])
        if new_amt not in amounts:
            amounts.append(new_amt)
            amounts.sort()
            CONFIG["TOPUP_AMOUNTS"] = amounts
            save_config()
            await update.message.reply_text(f" Added {new_amt} {CURRENCY_SYMBOL} to topup amounts.")
        else:
            await update.message.reply_text(" Amount already exists.")
    except Exception:
        await update.message.reply_text(" Invalid amount.")
    context.user_data.clear()
    await send_main_menu_by_message(update.message, user_id)

async def admin_delete_topup_amount(query, context, amount):
    user_id = query.from_user.id
    if not await db.is_admin(user_id):
        await query.answer("Admin only")
        return
    amounts = CONFIG.get("TOPUP_AMOUNTS", [])
    if amount in amounts:
        amounts.remove(amount)
        CONFIG["TOPUP_AMOUNTS"] = amounts
        save_config()
        await query.answer(f"Removed {amount} {CURRENCY_SYMBOL}")
    else:
        await query.answer("Amount not found")
    lang = await db.get_user_lang(user_id)
    await admin_edit_topup_amounts(query, context, lang)

# ===== Admin Statistics =====
async def admin_stats(query, context, lang):
    keyboard = [
        [InlineKeyboardButton(get_text("total_users", lang), callback_data="stat_total_users")],
        [InlineKeyboardButton(get_text("total_online", lang), callback_data="stat_online")],
        [InlineKeyboardButton(get_text("total_offline", lang), callback_data="stat_offline")],
        [InlineKeyboardButton(get_text("back", lang), callback_data="admin_panel")],
    ]
    await query.message.edit_text(" Statistics Menu", reply_markup=InlineKeyboardMarkup(keyboard))

async def stat_total_users(query, context, lang):
    all_clients = await db.get_all_clients()
    users_map = {}
    for client in all_clients:
        uid = client["user_id"]
        if uid not in users_map:
            users_map[uid] = []
        users_map[uid].append(client)
    total_users = len(users_map)
    text = f" *Total Users with configs:* {total_users}\n\n"
    for uid, clients in users_map.items():
        user = await db.get_user(uid)
        username = user["username"] if user else "Unknown"
        text += f" User ID: `{uid}` (@{username})\n"
        text += f"    Configs: {len(clients)}\n"
    if len(text) > 4000:
        text = text[:4000] + "\n...(truncated)"
    await query.message.reply_text(text, parse_mode="Markdown")

async def stat_online_offline(query, context, lang, mode="online"):
    all_clients = await db.get_all_clients()
    online_emails = xui_client.get_online_emails() if xui_client else set()
    result = []
    for client in all_clients:
        email_lower = client["email"].lower()
        traffic = xui_client.get_client_traffic(client["email"]) if xui_client else {}
        enabled = bool(traffic.get("enable", True))
        expiry_ms = traffic.get("expiryTime", 0)
        is_expired = expiry_ms > 0 and expiry_ms < datetime.utcnow().timestamp() * 1000
        is_online = email_lower in online_emails
        if mode == "online":
            if is_online and enabled and not is_expired:
                result.append(client)
        else:  # offline
            if not is_online or not enabled or is_expired:
                result.append(client)
    total = len(result)
    text = f"{' Total Online Configs' if mode=='online' else ' Total Offline Configs'}: {total}\n\n"
    for idx, client in enumerate(result[:50], 1):
        text += f"{idx}. {client['email']} - {client['service_name']}\n"
        text += f"   User ID: `{client['user_id']}`\n"
    if len(result) > 50:
        text += f"\n... and {len(result)-50} more."
    if not result:
        text += "None."
    await query.message.reply_text(text, parse_mode="Markdown")

# ===== Add Credit to User =====
async def admin_add_credit_prompt(query, context, user_id):
    lang = await db.get_user_lang(query.from_user.id)
    context.user_data["state"] = "add_credit"
    context.user_data["credit_user_id"] = user_id
    await query.message.reply_text(get_text("enter_credit_amount", lang))

async def handle_add_credit_amount(update, context):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        return
    try:
        amount = int(update.message.text.strip())
        target_user = context.user_data.get("credit_user_id")
        if not target_user:
            raise ValueError
        await db.update_balance(target_user, amount)
        await update.message.reply_text(get_text("credit_added", "en", amount=amount, user_id=target_user))
    except Exception:
        await update.message.reply_text(" Invalid amount.")
    context.user_data.clear()
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
        await start_buy_plan_from_plan(query, context, int(service_index_s), int(plan_index_s))
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
    if data == "admin_editprices":
        await admin_edit_prices(query, context, lang)
        return
    if data == "admin_edittopup":
        await admin_edit_topup_amounts(query, context, lang)
        return
    if data == "admin_stats":
        await admin_stats(query, context, lang)
        return
    if data == "stat_total_users":
        await stat_total_users(query, context, lang)
        return
    if data == "stat_online":
        await stat_online_offline(query, context, lang, "online")
        return
    if data == "stat_offline":
        await stat_online_offline(query, context, lang, "offline")
        return
    if data.startswith("editprice_"):
        _, svc_idx, plan_idx = data.split("_")
        await admin_edit_price_prompt(query, context, int(svc_idx), int(plan_idx))
        return
    if data.startswith("del_topup_"):
        amt = int(data.split("_")[2])
        await admin_delete_topup_amount(query, context, amt)
        return
    if data == "add_topup":
        await admin_add_topup_prompt(query, context, lang)
        return
    if data.startswith("acc_service_"):
        service_name = data[12:]  # after "acc_service_"
        await show_account_for_service(query, context, service_name)
        return
    if data.startswith("add_credit_"):
        target_uid = int(data.split("_")[2])
        await admin_add_credit_prompt(query, context, target_uid)
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
            f" Editing bank: {bank['name']}\n\nEnter new name, or /skip:"
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
        print("\n X-UI Login failed.")
        print("Check PANEL_URL, PANEL_USER, PANEL_PASS, panel path.")
        print(f"Error: {e}\n")
        sys.exit(1)
    try:
        app = Application.builder().token(CONFIG["BOT_TOKEN"]).build()
    except Exception as e:
        logger.error(f"Telegram app failed: {e}")
        print("\n BOT_TOKEN invalid.")
        print(f"Error: {e}\n")
        sys.exit(1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started.")
    print("\n Bot started successfully.")
    print("Open Telegram and press /start.\n")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()