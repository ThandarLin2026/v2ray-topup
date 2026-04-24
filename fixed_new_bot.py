#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram VLESS Bot - Alireza0 X-UI Panel
- Full i18n (Myanmar / Thai / English)
- Balance as separate button
- Removed user Banks button
- Auto cleanup & dependency install
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
except ImportError:
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

try:
    import qrcode
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'qrcode[pil]'])
    import qrcode

# ==================== Config ====================
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "BOT_TOKEN": "",
    "ADMIN_ID": 0,
    "PANEL_URL": "",
    "API_BASE_URL": "",
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
        "7777067# 29 ဘတ်စမတ်\n"
        "7777068# 34 ဘတ်စမတ်\n"
        "V2BOX IOS ANDROID စတာတွေနဲ့သုံးနိုင်ပါတယ်"
    ),
    "START_MESSAGE_EN": "Welcome to V2RAY X-UI PANEL",
    "START_MESSAGE_TH": "ยินดีต้อนรับสู่ V2RAY X-UI PANEL",
}

CONFIG = DEFAULT_CONFIG.copy()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_FILE = "bot_data.db"

# ==================== i18n ====================
TEXTS = {
    'en': {
        'buy_plan': "🛒 Buy Plan",
        'topup': "💰 TopUp",
        'account': "👤 Account",
        'balance': "💰 Balance",
        'contact': "📞 Contact",
        'admin_panel': "⚙️ Admin Panel",
        'language': "🌐 Language",
        'back': "🔙 Back",
        'main_menu': "🏠 Main Menu",
        'select_plan': "📦 *Select a plan*",
        'select_amount': "💰 *Select top-up amount*",
        'enter_username': (
            "👤 Please send username for this config.\n"
            "This username will be used as X-UI email and remark.\n\n"
            "Allowed: `A-Z a-z 0-9 _ . -`\n"
            "Example: `mgmg123`\n\n"
            "Use /cancel to stop."
        ),
        'invalid_username': (
            "❌ Invalid username.\n\n"
            "Only letters, numbers, underscore (_), dot (.), dash (-)\n"
            "Length: 3 to 32 characters\n\n"
            "Try again or /cancel."
        ),
        'username_exists_db': "❌ This username is already used in bot database.\nPlease send another username or /cancel.",
        'username_exists_panel': "❌ This username already exists in X-UI panel.\nPlease send another username or /cancel.",
        'insufficient_balance': (
            "❌ *Insufficient balance*\n\n"
            "💰 Your balance: *{balance} THB*\n"
            "📦 Plan price: *{price} THB*\n"
            "➕ Need more: *{need} THB*\n\n"
            "Please top up first."
        ),
        'creating_client': "⏳ Creating VLESS client...",
        'purchase_success': (
            "✅ *Plan Purchased Successfully!*\n\n"
            "📦 Plan: *{plan}*\n"
            "📅 Expires: {expiry}\n"
            "👤 Username: `{email}`\n"
            "🏷 Remarks: `{email}`\n"
            "📱 Scan QR code to import"
        ),
        'vless_config': "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        'copy_fallback': "\n\n📋 Native copy button not supported. Long press config to copy.",
        'account_info': "👤 *Account Information*\n\n📦 Total Configs: *{count}*",
        'no_active_plan': "👤 *Account Information*\n\n📡 Status: ⚪ No active plan\n\nPurchase a plan to get started!",
        'config_header': "━━━━━━ Config {idx} ━━━━━━",
        'config_status': (
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
        'balance_text': "💰 *Your balance:* `{balance} THB`",
        'topup_prompt': (
            "💰 *Top-up Amount:* `{amount} THB`\n\n"
            "🏦 Please transfer to one of the bank accounts below and then send your payment slip."
        ),
        'bank_caption': (
            "🏦 *{name}*\n"
            "💳 `{number}`\n"
            "👤 {holder}\n\n"
            "💵 Amount: *{amount} THB*"
        ),
        'send_slip': "📸 *Now send the payment slip photo.*\nUse /cancel to go back.",
        'topup_sent': "✅ Top-up request for {amount} THB has been sent to admin.",
        'topup_approved': "✅ Your top-up of {amount} THB has been approved.",
        'topup_cancelled': "❌ Your top-up request of {amount} THB was cancelled.",
        'admin_note': "📝 *Enter a note for the user (optional)*\nSend /skip to proceed without a note.",
        'config_deleted': "✅ *Config deleted successfully*\n\n👤 Username: `{email}`\n🔑 UUID: `{uuid}`",
        'delete_failed': "❌ Failed to delete config.\n\nError: `{error}`",
        'confirm_delete': "🗑 Delete Config?",
        'delete_confirm_btn': "✅ Confirm Delete",
        'delete_cancel_btn': "❌ Cancel",
        'copy_btn': "📋 Copy VLESS",
        'copy_not_supported_alert': "Native copy button not supported on this client. Long press config text to copy.",
        'contact_text': (
            "📞 Contact Support\n\n"
            "Telegram: {username}\n\n"
            "အကူအညီလိုရင် အပေါ်က account ကိုဆက်သွယ်နိုင်ပါတယ်။"
        ),
        'contact_btn': "📩 Open Contact",
        'admin_add_bank': "➕ Add Bank",
        'admin_pending_topups': "📋 Pending TopUps",
        'admin_manage_banks': "🏦 Manage Banks",
        'admin_broadcast': "📢 Broadcast Message",
        'bank_name_prompt': "🏦 Enter bank name (e.g., KBank):",
        'bank_number_prompt': "💳 Enter account number:",
        'bank_holder_prompt': "👤 Enter account holder name:",
        'bank_qr_prompt': "📷 Send QR code photo (or logo), or send an image URL.\nSend /skip if no image.",
        'bank_added': "✅ Bank added successfully.",
        'no_banks': "ℹ️ No bank accounts available.",
        'bank_list_header': "🏦 *Available Bank Accounts*",
        'no_pending_topups': "📭 No pending requests.",
        'pending_header': "📋 Found *{count}* pending request(s).\nRequests are being sent below.",
        'pending_caption': (
            "🔔 *Pending Top-up*\n\n"
            "🆔 ID: `{id}`\n"
            "👤 User ID: `{user_id}`\n"
            "💵 Amount: *{amount} THB*\n"
            "📅 Created: `{created}`"
        ),
        'broadcast_prompt': "📢 Send the message you want to broadcast to all users.\nUse /cancel to stop.",
        'broadcast_sending': "⏳ Broadcasting message...",
        'broadcast_result': "✅ Broadcast finished.\n\n📤 Sent: {sent}\n❌ Failed: {failed}",
        'cancel': "↩️ Cancelled.",
        'back_to_menu': "↩️ Back to main menu.",
        'lang_changed': "✅ Language changed to {lang}.",
        'select_lang': "🌐 Please select your language:",
        'lang_my': "🇲🇲 Myanmar",
        'lang_th': "🇹🇭 Thai",
        'lang_en': "🇬🇧 English",
    },
    'my': {
        'buy_plan': "🛒 အစီအစဉ်ဝယ်ရန်",
        'topup': "💰 ငွေဖြည့်ရန်",
        'account': "👤 အကောင့်",
        'balance': "💰 လက်ကျန်ငွေ",
        'contact': "📞 ဆက်သွယ်ရန်",
        'admin_panel': "⚙️ အက်ဒမင်ဘောင်",
        'language': "🌐 ဘာသာစကား",
        'back': "🔙 နောက်သို့",
        'main_menu': "🏠 ပင်မမီနူး",
        'select_plan': "📦 *အစီအစဉ်တစ်ခုရွေးပါ*",
        'select_amount': "💰 *ငွေပမာဏရွေးပါ*",
        'enter_username': (
            "👤 ဤ config အတွက် username ပေးပို့ပါ။\n"
            "ဤ username ကို X-UI email နှင့် remark အဖြစ် သုံးမည်။\n\n"
            "ခွင့်ပြုသော စာလုံးများ: `A-Z a-z 0-9 _ . -`\n"
            "ဥပမာ: `mgmg123`\n\n"
            "/cancel နှိပ်ပါက ပယ်ဖျက်မည်။"
        ),
        'invalid_username': (
            "❌ username မမှန်ကန်ပါ။\n\n"
            "စာလုံး၊ နံပါတ်၊ underscore (_)၊ dot (.)၊ dash (-) သာ ခွင့်ပြုသည်။\n"
            "အလျား ၃ မှ ၃၂ လုံးအထိ\n\n"
            "ထပ်ကြိုးစားပါ သို့ /cancel နှိပ်ပါ။"
        ),
        'username_exists_db': "❌ ဤ username ကို database တွင် အသုံးပြုထားပြီးဖြစ်သည်။\nအခြား username ပေးပါ သို့ /cancel နှိပ်ပါ။",
        'username_exists_panel': "❌ ဤ username သည် X-UI panel တွင် ရှိနှင့်ပြီးဖြစ်သည်။\nအခြား username ပေးပါ သို့ /cancel နှိပ်ပါ။",
        'insufficient_balance': (
            "❌ *လက်ကျန်ငွေ မလုံလောက်ပါ*\n\n"
            "💰 သင့်လက်ကျန်: *{balance} THB*\n"
            "📦 plan စျေးနှုန်း: *{price} THB*\n"
            "➕ ထပ်လိုအပ်ငွေ: *{need} THB*\n\n"
            "ကျေးဇူးပြု၍ top-up လုပ်ပါ။"
        ),
        'creating_client': "⏳ VLESS client ဖန်တီးနေသည်...",
        'purchase_success': (
            "✅ *Plan အောင်မြင်စွာဝယ်ယူပြီးစီး!*\n\n"
            "📦 Plan: *{plan}*\n"
            "📅 သက်တမ်းကုန်ဆုံး: {expiry}\n"
            "👤 Username: `{email}`\n"
            "🏷 Remarks: `{email}`\n"
            "📱 QR code အားစကင်န်ဖတ်ပါ"
        ),
        'vless_config': "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        'copy_fallback': "\n\n📋 Native copy button မထောက်ပံ့ပါ။ config ကို ဖိထား၍ ကူးယူပါ။",
        'account_info': "👤 *အကောင့်အချက်အလက်*\n\n📦 Config အရေအတွက်: *{count}*",
        'no_active_plan': "👤 *အကောင့်အချက်အလက်*\n\n📡 အခြေအနေ: ⚪ active plan မရှိပါ\n\nPlan တစ်ခုဝယ်ယူရန်!",
        'config_header': "━━━━━━ Config {idx} ━━━━━━",
        'config_status': (
            "📦 Plan: *{plan}*\n"
            "👤 Username: `{email}`\n"
            "📅 သက်တမ်းကုန်: {expiry}\n"
            "{status_emoji} အခြေအနေ: *{status}*\n\n"
            "📊 *Traffic*\n"
            "📥 ဒေါင်းလုပ်: `{down}`\n"
            "📤 အပ်လုဒ်: `{up}`\n"
            "💾 စုစုပေါင်းသုံးစွဲ: `{used} / {limit} GB` ({percent:.1f}%)\n\n"
            "🔑 UUID: `{uuid}`"
        ),
        'balance_text': "💰 *သင့်လက်ကျန်ငွေ:* `{balance} THB`",
        'topup_prompt': (
            "💰 *Top-up ငွေပမာဏ:* `{amount} THB`\n\n"
            "🏦 အောက်ပါဘဏ်အကောင့်များထဲမှ တစ်ခုသို့ လွှဲပြီး ငွေလွှဲပြေစာ (slip) ပေးပို့ပါ။"
        ),
        'bank_caption': (
            "🏦 *{name}*\n"
            "💳 `{number}`\n"
            "👤 {holder}\n\n"
            "💵 ပမာဏ: *{amount} THB*"
        ),
        'send_slip': "📸 *ငွေလွှဲပြေစာဓာတ်ပုံ ပေးပို့ပါ။*\n/cancel နှိပ်ပါက ပယ်ဖျက်မည်။",
        'topup_sent': "✅ {amount} THB အတွက် top-up တောင်းဆိုမှုကို admin ထံ ပေးပို့ပြီးပါပြီ။",
        'topup_approved': "✅ သင်၏ {amount} THB top-up ကို အတည်ပြုပြီးပါပြီ။",
        'topup_cancelled': "❌ သင်၏ {amount} THB top-up တောင်းဆိုမှုကို ပယ်ဖျက်လိုက်ပါသည်။",
        'admin_note': "📝 *အသုံးပြုသူအတွက် မှတ်ချက် (လိုအပ်မှသာ) ရိုက်ထည့်ပါ*\nမှတ်ချက်မပါလိုပါက /skip ပို့ပါ။",
        'config_deleted': "✅ *Config ကိုဖျက်ပြီးပါပြီ*\n\n👤 Username: `{email}`\n🔑 UUID: `{uuid}`",
        'delete_failed': "❌ Config ဖျက်ရာတွင် မအောင်မြင်ပါ။\n\nအမှား: `{error}`",
        'confirm_delete': "🗑 Config ဖျက်မည်?",
        'delete_confirm_btn': "✅ ဖျက်ရန်အတည်ပြု",
        'delete_cancel_btn': "❌ မဖျက်တော့ပါ",
        'copy_btn': "📋 VLESS ကူးယူရန်",
        'copy_not_supported_alert': "Native copy button မထောက်ပံ့ပါ။ config စာသားကို ဖိထား၍ ကူးယူပါ။",
        'contact_text': (
            "📞 အကူအညီလိုပါက\n\n"
            "Telegram: {username}\n\n"
            "အပေါ်က account ကို ဆက်သွယ်နိုင်ပါတယ်။"
        ),
        'contact_btn': "📩 ဆက်သွယ်ရန် ဖွင့်မည်",
        'admin_add_bank': "➕ ဘဏ်အသစ်ထည့်",
        'admin_pending_topups': "📋 ဆိုင်းငံ့တောင်းဆိုမှုများ",
        'admin_manage_banks': "🏦 ဘဏ်များစီမံ",
        'admin_broadcast': "📢 သတင်းပို့ရန်",
        'bank_name_prompt': "🏦 ဘဏ်အမည် ရိုက်ထည့်ပါ (ဥပမာ KBank):",
        'bank_number_prompt': "💳 အကောင့်နံပါတ် ရိုက်ထည့်ပါ:",
        'bank_holder_prompt': "👤 အကောင့်အမည် ရိုက်ထည့်ပါ:",
        'bank_qr_prompt': "📷 QR code ဓာတ်ပုံ (သို့) ပုံ URL ပေးပို့ပါ။\nမပါလိုပါက /skip ပို့ပါ။",
        'bank_added': "✅ ဘဏ်အသစ် ထည့်သွင်းပြီးပါပြီ။",
        'no_banks': "ℹ️ ဘဏ်အကောင့် မရှိသေးပါ။",
        'bank_list_header': "🏦 *ရရှိနိုင်သောဘဏ်များ*",
        'no_pending_topups': "📭 ဆိုင်းငံ့တောင်းဆိုမှု မရှိပါ။",
        'pending_header': "📋 ဆိုင်းငံ့တောင်းဆိုမှု *{count}* ခုရှိသည်။\nအောက်တွင် ပေးပို့နေပါသည်။",
        'pending_caption': (
            "🔔 *ဆိုင်းငံ့ Top-up*\n\n"
            "🆔 ID: `{id}`\n"
            "👤 အသုံးပြုသူ ID: `{user_id}`\n"
            "💵 ပမာဏ: *{amount} THB*\n"
            "📅 ဖန်တီးချိန်: `{created}`"
        ),
        'broadcast_prompt': "📢 သုံးစွဲသူအားလုံးသို့ ပို့လိုသော မက်ဆေ့ခ်ျကို ရိုက်ထည့်ပါ။\nပယ်ဖျက်ရန် /cancel နှိပ်ပါ။",
        'broadcast_sending': "⏳ သတင်းပို့နေသည်...",
        'broadcast_result': "✅ သတင်းပို့ခြင်း ပြီးဆုံးပါပြီ။\n\n📤 ပို့ပြီး: {sent}\n❌ မပို့ရသေးသော: {failed}",
        'cancel': "↩️ ပယ်ဖျက်လိုက်ပါပြီ။",
        'back_to_menu': "↩️ ပင်မမီနူးသို့ ပြန်သွားသည်။",
        'lang_changed': "✅ ဘာသာစကားကို {lang} သို့ ပြောင်းလဲပြီးပါပြီ။",
        'select_lang': "🌐 ကျေးဇူးပြု၍ ဘာသာစကားရွေးချယ်ပါ:",
        'lang_my': "🇲🇲 မြန်မာ",
        'lang_th': "🇹🇭 ထိုင်း",
        'lang_en': "🇬🇧 အင်္ဂလိပ်",
    },
    'th': {  # Thai placeholders – copy from English for now, user can edit
        'buy_plan': "🛒 ซื้อแผน",
        'topup': "💰 เติมเงิน",
        'account': "👤 บัญชี",
        'balance': "💰 ยอดเงิน",
        'contact': "📞 ติดต่อ",
        'admin_panel': "⚙️ แผงแอดมิน",
        'language': "🌐 ภาษา",
        'back': "🔙 กลับ",
        'main_menu': "🏠 เมนูหลัก",
        'select_plan': "📦 *เลือกแผน*",
        'select_amount': "💰 *เลือกจำนวนเงิน*",
        'enter_username': "👤 กรุณาส่ง username สำหรับ config นี้\n\nอนุญาต: `A-Z a-z 0-9 _ . -`\nตัวอย่าง: `mgmg123`\n\nใช้ /cancel เพื่อยกเลิก",
        'invalid_username': "❌ Username ไม่ถูกต้อง\n\nเฉพาะตัวอักษร ตัวเลข _ . - เท่านั้น\nความยาว 3-32 ตัวอักษร\n\nลองใหม่หรือ /cancel",
        'username_exists_db': "❌ Username นี้ถูกใช้ในฐานข้อมูลแล้ว\nกรุณาส่ง username อื่นหรือ /cancel",
        'username_exists_panel': "❌ Username นี้มีอยู่ใน X-UI panel แล้ว\nกรุณาส่ง username อื่นหรือ /cancel",
        'insufficient_balance': "❌ *ยอดเงินไม่เพียงพอ*\n\n💰 ยอดเงินของคุณ: *{balance} THB*\n📦 ราคาแผน: *{price} THB*\n➕ ต้องการเพิ่ม: *{need} THB*\n\nกรุณาเติมเงินก่อน",
        'creating_client': "⏳ กำลังสร้าง VLESS client...",
        'purchase_success': "✅ *ซื้อแผนสำเร็จ!*\n\n📦 แผน: *{plan}*\n📅 หมดอายุ: {expiry}\n👤 Username: `{email}`\n🏷 Remarks: `{email}`\n📱 สแกน QR code เพื่อนำเข้า",
        'vless_config': "🔐 <b>VLESS CONFIG</b>\n\n<code>{config}</code>",
        'copy_fallback': "\n\n📋 ปุ่มคัดลอกไม่รองรับ กดค้างเพื่อคัดลอก",
        'account_info': "👤 *ข้อมูลบัญชี*\n\n📦 จำนวน Config: *{count}*",
        'no_active_plan': "👤 *ข้อมูลบัญชี*\n\n📡 สถานะ: ⚪ ไม่มีแผน\n\nซื้อแผนเพื่อเริ่มต้น!",
        'config_header': "━━━━━━ Config {idx} ━━━━━━",
        'config_status': "📦 แผน: *{plan}*\n👤 Username: `{email}`\n📅 หมดอายุ: {expiry}\n{status_emoji} สถานะ: *{status}*\n\n📊 *การใช้งาน*\n📥 ดาวน์โหลด: `{down}`\n📤 อัปโหลด: `{up}`\n💾 ใช้ไปแล้ว: `{used} / {limit} GB` ({percent:.1f}%)\n\n🔑 UUID: `{uuid}`",
        'balance_text': "💰 *ยอดเงินของคุณ:* `{balance} THB`",
        'topup_prompt': "💰 *จำนวนเงินเติม:* `{amount} THB`\n\n🏦 โอนไปยังบัญชีธนาคารด้านล่างแล้วส่งสลิป",
        'bank_caption': "🏦 *{name}*\n💳 `{number}`\n👤 {holder}\n\n💵 จำนวน: *{amount} THB*",
        'send_slip': "📸 *ส่งรูปสลิปการโอนเงิน*\nใช้ /cancel เพื่อยกเลิก",
        'topup_sent': "✅ คำขอเติมเงิน {amount} THB ถูกส่งไปยังแอดมินแล้ว",
        'topup_approved': "✅ การเติมเงิน {amount} THB ของคุณได้รับการอนุมัติแล้ว",
        'topup_cancelled': "❌ คำขอเติมเงิน {amount} THB ของคุณถูกยกเลิก",
        'admin_note': "📝 *ป้อนหมายเหตุสำหรับผู้ใช้ (ถ้ามี)*\nส่ง /skip เพื่อไม่ใส่หมายเหตุ",
        'config_deleted': "✅ *ลบ config สำเร็จ*\n\n👤 Username: `{email}`\n🔑 UUID: `{uuid}`",
        'delete_failed': "❌ ลบ config ไม่สำเร็จ\n\nข้อผิดพลาด: `{error}`",
        'confirm_delete': "🗑 ลบ Config?",
        'delete_confirm_btn': "✅ ยืนยันการลบ",
        'delete_cancel_btn': "❌ ยกเลิก",
        'copy_btn': "📋 คัดลอก VLESS",
        'copy_not_supported_alert': "ปุ่มคัดลอกไม่รองรับ กดค้างที่ข้อความ config เพื่อคัดลอก",
        'contact_text': "📞 ติดต่อสนับสนุน\n\nTelegram: {username}",
        'contact_btn': "📩 เปิดการติดต่อ",
        'admin_add_bank': "➕ เพิ่มธนาคาร",
        'admin_pending_topups': "📋 คำขอที่รออนุมัติ",
        'admin_manage_banks': "🏦 จัดการธนาคาร",
        'admin_broadcast': "📢 ข้อความกระจายข่าว",
        'bank_name_prompt': "🏦 ป้อนชื่อธนาคาร (เช่น KBank):",
        'bank_number_prompt': "💳 ป้อนหมายเลขบัญชี:",
        'bank_holder_prompt': "👤 ป้อนชื่อเจ้าของบัญชี:",
        'bank_qr_prompt': "📷 ส่งรูป QR code หรือ URL รูปภาพ\n/skip ถ้าไม่มี",
        'bank_added': "✅ เพิ่มธนาคารสำเร็จ",
        'no_banks': "ℹ️ ไม่มีบัญชีธนาคาร",
        'bank_list_header': "🏦 *บัญชีธนาคารที่มี*",
        'no_pending_topups': "📭 ไม่มีคำขอที่รออนุมัติ",
        'pending_header': "📋 พบ *{count}* คำขอที่รออนุมัติ\nกำลังส่งคำขอด้านล่าง",
        'pending_caption': "🔔 *Top-up ที่รออนุมัติ*\n\n🆔 ID: `{id}`\n👤 User ID: `{user_id}`\n💵 จำนวน: *{amount} THB*\n📅 สร้างเมื่อ: `{created}`",
        'broadcast_prompt': "📢 ส่งข้อความที่ต้องการกระจายไปยังผู้ใช้ทั้งหมด\nใช้ /cancel เพื่อยกเลิก",
        'broadcast_sending': "⏳ กำลังกระจายข้อความ...",
        'broadcast_result': "✅ กระจายข้อความเสร็จสิ้น\n\n📤 ส่งสำเร็จ: {sent}\n❌ ล้มเหลว: {failed}",
        'cancel': "↩️ ยกเลิกแล้ว",
        'back_to_menu': "↩️ กลับสู่เมนูหลัก",
        'lang_changed': "✅ เปลี่ยนภาษาเป็น {lang}",
        'select_lang': "🌐 กรุณาเลือกภาษา:",
        'lang_my': "🇲🇳 พม่า",
        'lang_th': "🇹🇭 ไทย",
        'lang_en': "🇬🇧 อังกฤษ",
    }
}

def get_text(key, lang='en', **kwargs):
    """Get localized text by key and language, fallback to English."""
    lang_dict = TEXTS.get(lang, TEXTS['en'])
    text = lang_dict.get(key, TEXTS['en'].get(key, key))
    if kwargs:
        return text.format(**kwargs)
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
                cur = conn.execute("SELECT id FROM plans WHERE name = ?", (name,))
                exists = cur.fetchone()
                if exists:
                    conn.execute(
                        "UPDATE plans SET days=?, data_gb=?, price=? WHERE name=?",
                        (days, gb, price, name)
                    )
                else:
                    conn.execute(
                        "INSERT INTO plans (name, days, data_gb, price) VALUES (?,?,?,?)",
                        (name, days, gb, price)
                    )

    async def execute(self, query: str, params: tuple = ()):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self._execute_sync, query, params))

    def _execute_sync(self, query: str, params: tuple):
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(query, params)
            conn.commit()
            if query.strip().upper().startswith("SELECT"):
                return [dict(row) for row in cur.fetchall()]
            return cur.lastrowid

    async def get_user(self, user_id: int):
        rows = await self.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return rows[0] if rows else None

    async def get_user_lang(self, user_id: int) -> str:
        user = await self.get_user(user_id)
        return user['lang'] if user else 'my'

    async def set_user_lang(self, user_id: int, lang: str):
        await self.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id))

    async def get_all_users(self):
        return await self.execute("SELECT * FROM users ORDER BY user_id")

    async def create_user(self, user_id: int, username: str):
        await self.execute(
            "INSERT OR IGNORE INTO users (user_id, username, lang) VALUES (?,?,?)",
            (user_id, username, 'my')
        )

    async def update_balance(self, user_id: int, delta: int):
        await self.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (delta, user_id)
        )

    async def get_balance(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        return user["balance"] if user else 0

    async def set_admin(self, user_id: int):
        await self.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (user_id,))

    async def is_admin(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return bool(user and user["is_admin"])

    async def create_topup(self, user_id: int, amount: int, slip_file_id: str = None):
        return await self.execute(
            "INSERT INTO topup_requests (user_id, amount, slip_file_id) VALUES (?,?,?)",
            (user_id, amount, slip_file_id)
        )

    async def get_topup(self, topup_id: int):
        rows = await self.execute("SELECT * FROM topup_requests WHERE id = ?", (topup_id,))
        return rows[0] if rows else None

    async def update_topup_status(self, topup_id: int, status: str):
        await self.execute("UPDATE topup_requests SET status = ? WHERE id = ?", (status, topup_id))

    async def get_pending_topups(self):
        return await self.execute(
            "SELECT * FROM topup_requests WHERE status = 'pending' ORDER BY created_at"
        )

    async def add_bank(self, name: str, number: str, holder: str, qr_file_id: str = None, qr_url: str = None):
        await self.execute(
            "INSERT INTO banks (name, number, holder, qr_file_id, qr_url) VALUES (?,?,?,?,?)",
            (name, number, holder, qr_file_id, qr_url)
        )

    async def update_bank(self, bank_id: int, name: str, number: str, holder: str, qr_file_id: str = None, qr_url: str = None):
        await self.execute(
            """UPDATE banks SET name=?, number=?, holder=?, qr_file_id=?, qr_url=? WHERE id=?""",
            (name, number, holder, qr_file_id, qr_url, bank_id)
        )

    async def get_bank(self, bank_id: int):
        rows = await self.execute("SELECT * FROM banks WHERE id = ?", (bank_id,))
        return rows[0] if rows else None

    async def get_banks(self):
        return await self.execute("SELECT * FROM banks ORDER BY id")

    async def delete_bank(self, bank_id: int):
        await self.execute("DELETE FROM banks WHERE id = ?", (bank_id,))

    async def get_plans(self):
        return await self.execute("SELECT * FROM plans ORDER BY price")

    async def get_plan(self, plan_id: int):
        rows = await self.execute("SELECT * FROM plans WHERE id = ?", (plan_id,))
        return rows[0] if rows else None

    async def add_client(self, user_id: int, uuid_str: str, email: str, plan_id: int, total_gb: int, expiry_at: datetime):
        await self.execute(
            """INSERT INTO user_clients (user_id, uuid, email, plan_id, expiry_at, total_gb) VALUES (?,?,?,?,?,?)""",
            (user_id, uuid_str, email, plan_id, expiry_at.isoformat(), total_gb)
        )

    async def get_client(self, user_id: int):
        rows = await self.execute(
            """SELECT uc.rowid AS row_id, uc.*, p.name as plan_name, p.days, p.data_gb FROM user_clients uc LEFT JOIN plans p ON uc.plan_id = p.id WHERE uc.user_id = ? ORDER BY uc.created_at DESC LIMIT 1""",
            (user_id,)
        )
        return rows[0] if rows else None

    async def get_clients(self, user_id: int):
        return await self.execute(
            """SELECT uc.rowid AS row_id, uc.*, p.name as plan_name, p.days, p.data_gb, p.price FROM user_clients uc LEFT JOIN plans p ON uc.plan_id = p.id WHERE uc.user_id = ? ORDER BY uc.created_at DESC""",
            (user_id,)
        )

    async def get_client_by_row_id(self, row_id: int):
        rows = await self.execute(
            """SELECT uc.rowid AS row_id, uc.*, p.name as plan_name, p.days, p.data_gb, p.price FROM user_clients uc LEFT JOIN plans p ON uc.plan_id = p.id WHERE uc.rowid = ? LIMIT 1""",
            (row_id,)
        )
        return rows[0] if rows else None

    async def delete_client_by_row_id(self, row_id: int):
        await self.execute("DELETE FROM user_clients WHERE rowid = ?", (row_id,))

    async def email_exists(self, email: str) -> bool:
        rows = await self.execute(
            "SELECT email FROM user_clients WHERE LOWER(email) = LOWER(?) LIMIT 1",
            (email,)
        )
        return bool(rows)

    async def update_client_usage_by_email(self, email: str, download: int, upload: int):
        await self.execute(
            "UPDATE user_clients SET download_used = ?, upload_used = ? WHERE email = ?",
            (download, upload, email)
        )

db = Database()

# ==================== X-UI Client ====================
class XUIClient:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = self._detect_api_base()
        self.api_inbounds_path = "/xui/API/inbounds"

    def _detect_api_base(self):
        panel_url = CONFIG["PANEL_URL"].rstrip("/")
        root_url = "/".join(panel_url.split("/")[:3])
        if self._try_login(root_url):
            logger.info(f"API base detected as root: {root_url}")
            return root_url
        if self._try_login(panel_url):
            logger.info(f"API base detected as custom: {panel_url}")
            return panel_url
        raise Exception("Could not login with any API base URL")

    def _try_login(self, base_url: str) -> bool:
        url = f"{base_url}/login"
        data = {"username": CONFIG["PANEL_USER"], "password": CONFIG["PANEL_PASS"]}
        try:
            resp = self.session.post(url, data=data, timeout=10)
            if resp.status_code == 200:
                try:
                    payload = resp.json()
                    if payload.get("success"):
                        self.base_url = base_url
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    def add_client(self, inbound_id: int, email: str, uuid_str: str, total_gb: int = 0, expiry_time: int = 0) -> dict:
        url = f"{self.base_url}{self.api_inbounds_path}/addClient/"
        settings = {
            "clients": [{
                "email": email,
                "id": uuid_str,
                "enable": True,
                "flow": "",
                "totalGB": total_gb,
                "expiryTime": expiry_time,
                "limitIp": 0,
            }]
        }
        data = {"id": inbound_id, "settings": json.dumps(settings)}
        resp = self.session.post(url, data=data, timeout=20)
        if resp.status_code != 200:
            raise Exception(f"Add client HTTP {resp.status_code}: {resp.text[:200]}")
        result = resp.json()
        if not result.get("success"):
            raise Exception(f"Add client error: {result.get('msg', 'Unknown error')}")
        return result

    def _request_json(self, method: str, url: str, **kwargs):
        if method == "POST":
            resp = self.session.post(url, timeout=20, **kwargs)
        else:
            resp = self.session.get(url, timeout=20, **kwargs)
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, {"raw": resp.text}

    def delete_client(self, uuid_str: str, inbound_id: int = None, email: str = None) -> bool:
        inbound_id = inbound_id or CONFIG["INBOUND_ID"]
        candidates = [
            ("POST", f"{self.base_url}{self.api_inbounds_path}/delClient/{uuid_str}", {}),
            ("GET", f"{self.base_url}{self.api_inbounds_path}/delClient/{uuid_str}", {}),
            ("POST", f"{self.base_url}{self.api_inbounds_path}/delClient/{uuid_str}/", {}),
            ("GET", f"{self.base_url}{self.api_inbounds_path}/delClient/{uuid_str}/", {}),
            ("POST", f"{self.base_url}{self.api_inbounds_path}/delClient/{inbound_id}/{uuid_str}", {}),
            ("GET", f"{self.base_url}{self.api_inbounds_path}/delClient/{inbound_id}/{uuid_str}", {}),
            ("POST", f"{self.base_url}{self.api_inbounds_path}/delClient/", {"data": {"id": uuid_str}}),
            ("POST", f"{self.base_url}{self.api_inbounds_path}/delClient/", {"data": {"id": inbound_id, "clientId": uuid_str}}),
            ("POST", f"{self.base_url}{self.api_inbounds_path}/delClient/", {"data": {"clientId": uuid_str}}),
        ]
        if email:
            candidates.extend([
                ("POST", f"{self.base_url}{self.api_inbounds_path}/delClient/", {"data": {"email": email}}),
                ("POST", f"{self.base_url}{self.api_inbounds_path}/delClient/", {"data": {"id": inbound_id, "email": email}}),
            ])
        for method, url, kwargs in candidates:
            try:
                status, data = self._request_json(method, url, **kwargs)
                if status == 200:
                    if isinstance(data, dict) and data.get("success") is True:
                        return True
                    raw = json.dumps(data, ensure_ascii=False).lower()
                    if isinstance(data, dict) else str(data).lower()
                    if '"success": true' in raw or '"success":true' in raw:
                        return True
            except Exception as e:
                logger.warning(f"Delete client try failed {method} {url}: {e}")
        raise Exception("Failed to delete client from X-UI panel. Your panel endpoint may differ.")

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

    def _normalize_traffic_obj(self, obj: dict) -> dict:
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

    def _extract_traffic_from_inbounds_list(self, email: str, payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {}
        inbounds = payload.get("obj") or []
        for inbound in inbounds:
            client_stats = inbound.get("clientStats") or inbound.get("clientTraffic") or []
            if isinstance(client_stats, list):
                for stat in client_stats:
                    if stat.get("email") == email:
                        return self._normalize_traffic_obj(stat)
            settings_raw = inbound.get("settings")
            if settings_raw:
                try:
                    settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
                    clients = settings.get("clients", [])
                    for client in clients:
                        if client.get("email") == email:
                            normalized = self._normalize_traffic_obj(client)
                            if isinstance(client_stats, list):
                                for stat in client_stats:
                                    if stat.get("email") == email:
                                        stat_n = self._normalize_traffic_obj(stat)
                                        normalized["downlink"] = stat_n.get("downlink", 0)
                                        normalized["uplink"] = stat_n.get("uplink", 0)
                                        if stat_n.get("total"):
                                            normalized["total"] = stat_n["total"]
                                        if stat_n.get("expiryTime"):
                                            normalized["expiryTime"] = stat_n["expiryTime"]
                                        normalized["enable"] = stat_n.get("enable", normalized["enable"])
                            return normalized
                except Exception:
                    pass
        return {}

    def _extract_all_client_emails(self, payload: dict):
        emails = set()
        if not isinstance(payload, dict):
            return emails
        inbounds = payload.get("obj") or []
        for inbound in inbounds:
            client_stats = inbound.get("clientStats") or inbound.get("clientTraffic") or []
            if isinstance(client_stats, list):
                for stat in client_stats:
                    email = (stat.get("email") or "").strip()
                    if email:
                        emails.add(email.lower())
            settings_raw = inbound.get("settings")
            if settings_raw:
                try:
                    settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
                    clients = settings.get("clients", [])
                    for client in clients:
                        email = (client.get("email") or "").strip()
                        if email:
                            emails.add(email.lower())
                except Exception:
                    pass
        return emails

    def get_client_traffic(self, email: str) -> dict:
        try:
            encoded_email = quote(email, safe="")
            url = f"{self.base_url}{self.api_inbounds_path}/getClientTraffics/{encoded_email}"
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    obj = data.get("obj", {})
                    normalized = self._normalize_traffic_obj(obj)
                    if normalized:
                        return normalized
        except Exception as e:
            logger.warning(f"Direct traffic endpoint failed for {email}: {e}")
        try:
            url = f"{self.base_url}{self.api_inbounds_path}/list"
            resp = self.session.get(url, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    found = self._extract_traffic_from_inbounds_list(email, data)
                    if found:
                        return found
        except Exception as e:
            logger.error(f"Failed to fallback traffic search for {email}: {e}")
        return {}

    def email_exists(self, email: str) -> bool:
        try:
            encoded_email = quote(email, safe="")
            url = f"{self.base_url}{self.api_inbounds_path}/getClientTraffics/{encoded_email}"
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and data.get("obj"):
                    obj = data.get("obj") or {}
                    existing_email = (obj.get("email") or "").strip().lower()
                    if existing_email == email.strip().lower():
                        return True
        except Exception as e:
            logger.warning(f"Direct email-exists endpoint failed for {email}: {e}")
        try:
            url = f"{self.base_url}{self.api_inbounds_path}/list"
            resp = self.session.get(url, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    emails = self._extract_all_client_emails(data)
                    return email.strip().lower() in emails
        except Exception as e:
            logger.error(f"Failed to check panel email exists for {email}: {e}")
        return False

xui = None

# ==================== Helpers ====================
def generate_vless_link(uuid_str: str, remark: str = "") -> str:
    address = CONFIG["SERVER_ADDRESS"]
    port = CONFIG["PORT"]
    path = CONFIG["WS_PATH"] or "/"
    ws_host = CONFIG["WS_HOST"]
    link = (
        f"vless://{uuid_str}@{address}:{port}"
        f"?path={quote(path, safe='/')}&security=none&encryption=none&type=ws&host={quote(ws_host, safe='')}"
    )
    if remark:
        link += f"#{quote(remark.replace(' ', '_'), safe='')}"
    return link

def generate_qr_bytes(data: str) -> io.BytesIO:
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio

def format_bytes(size: int) -> str:
    size = int(size or 0)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def get_effective_message(target):
    if isinstance(target, Update):
        return target.effective_message
    return getattr(target, "message", None)

def get_vless_copy_keyboard(vless_link: str, lang):
    if HAS_COPY_TEXT_BUTTON and CopyTextButton is not None:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text('copy_btn', lang), copy_text=CopyTextButton(vless_link))]
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text('copy_btn', lang), callback_data="copy_not_supported")]
    ])

def get_config_action_keyboard(row_id: int, lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text('confirm_delete', lang), callback_data=f"delcfg_{row_id}")]
    ])

def get_delete_confirm_keyboard(row_id: int, lang):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(get_text('delete_confirm_btn', lang), callback_data=f"confirmdelcfg_{row_id}"),
            InlineKeyboardButton(get_text('delete_cancel_btn', lang), callback_data=f"canceldelcfg_{row_id}")
        ]
    ])

def get_contact_text(lang):
    username = CONFIG.get("CONTACT_USERNAME", "@Juevpn").strip()
    if not username.startswith("@"):
        username = f"@{username}"
    return get_text('contact_text', lang, username=username)

def get_contact_keyboard(lang):
    username = CONFIG.get("CONTACT_USERNAME", "@Juevpn").strip()
    clean = username[1:] if username.startswith("@") else username
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text('contact_btn', lang), url=f"https://t.me/{clean}")]
    ])

def get_welcome_text(lang):
    if lang == 'my':
        return CONFIG.get("START_MESSAGE_MY", DEFAULT_CONFIG["START_MESSAGE_MY"])
    elif lang == 'th':
        return CONFIG.get("START_MESSAGE_TH", DEFAULT_CONFIG["START_MESSAGE_TH"])
    else:
        return CONFIG.get("START_MESSAGE_EN", DEFAULT_CONFIG["START_MESSAGE_EN"])

def sanitize_username(username: str) -> str:
    return username.strip()

def is_valid_xui_email_value(username: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username))

def build_client_status_text(client: dict, traffic: dict, lang: str) -> str:
    download = int(traffic.get("downlink", client.get("download_used", 0)) or 0)
    upload = int(traffic.get("uplink", client.get("upload_used", 0)) or 0)
    total_used = download + upload

    panel_total = int(traffic.get("total", 0) or 0)
    total_limit_bytes = panel_total if panel_total > 0 else int(client.get("total_gb", 0) or 0)
    panel_expiry_ms = int(traffic.get("expiryTime", 0) or 0)
    if panel_expiry_ms > 0:
        expiry = datetime.utcfromtimestamp(panel_expiry_ms / 1000)
    else:
        expiry = datetime.fromisoformat(client["expiry_at"]) if client.get("expiry_at") else None
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

    limit_gb = (total_limit_bytes / (1024**3)) if total_limit_bytes > 0 else 0
    usage_percent = (total_used / total_limit_bytes * 100) if total_limit_bytes > 0 else 0
    traffic_exhausted = total_limit_bytes > 0 and total_used >= total_limit_bytes
    is_active = enabled and (not is_expired) and (not traffic_exhausted)
    status_emoji = "🟢" if is_active else "🔴"
    status_text = get_text('config_status', lang).split('\n')[0]  # simplified
    return get_text('config_status', lang,
                    plan=client.get('plan_name', 'Unknown'),
                    email=client['email'],
                    expiry=expiry_str,
                    status_emoji=status_emoji,
                    status="Active" if is_active else "Expired",
                    down=format_bytes(download),
                    up=format_bytes(upload),
                    used=format_bytes(total_used),
                    limit=f"{limit_gb:.0f}",
                    percent=usage_percent,
                    uuid=client['uuid'])

async def send_client_config_block(message_obj, client: dict, lang: str):
    remark = client["email"]
    link = generate_vless_link(client["uuid"], remark)
    config_text = get_text('vless_config', lang, config=html.escape(link))
    copy_keyboard = get_vless_copy_keyboard(link, lang)

    if HAS_COPY_TEXT_BUTTON and CopyTextButton is not None:
        await message_obj.reply_text(config_text, parse_mode="HTML", reply_markup=copy_keyboard)
    else:
        await message_obj.reply_text(
            config_text + get_text('copy_fallback', lang),
            parse_mode="HTML",
            reply_markup=copy_keyboard
        )

async def send_main_menu(target, lang: str = None):
    user_id = None
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
        await msg.reply_text(get_text('main_menu', lang), reply_markup=keyboard)

async def get_main_keyboard(is_admin: bool, lang: str) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(get_text('buy_plan', lang)), KeyboardButton(get_text('topup', lang))],
        [KeyboardButton(get_text('account', lang)), KeyboardButton(get_text('balance', lang))],
        [KeyboardButton(get_text('contact', lang)), KeyboardButton(get_text('language', lang))],
    ]
    if is_admin:
        buttons.append([KeyboardButton(get_text('admin_panel', lang))])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

async def route_main_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)

    if text == get_text('buy_plan', lang):
        await show_plans(update, lang)
    elif text == get_text('topup', lang):
        await start_topup(update, lang)
    elif text == get_text('account', lang):
        await show_account(update, context, lang)
    elif text == get_text('balance', lang):
        await show_balance(update, lang)
    elif text == get_text('contact', lang):
        await show_contact(update, lang)
    elif text == get_text('language', lang):
        await show_language_selector(update, lang)
    elif text == get_text('admin_panel', lang):
        if await db.is_admin(user_id):
            await show_admin_panel(update, lang)
        else:
            await send_main_menu(update, lang)
    else:
        await send_main_menu(update, lang)

async def show_language_selector(update: Update, current_lang: str):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text('lang_my', current_lang), callback_data="lang_my")],
        [InlineKeyboardButton(get_text('lang_th', current_lang), callback_data="lang_th")],
        [InlineKeyboardButton(get_text('lang_en', current_lang), callback_data="lang_en")],
        [InlineKeyboardButton(get_text('back', current_lang), callback_data="menu_back")]
    ])
    await update.message.reply_text(get_text('select_lang', current_lang), reply_markup=keyboard)

async def set_language(query, lang_code):
    user_id = query.from_user.id
    await db.set_user_lang(user_id, lang_code)
    new_lang = await db.get_user_lang(user_id)
    await query.answer(get_text('lang_changed', new_lang, lang=new_lang.upper()))
    await query.message.delete()
    # Send a new main menu
    await send_main_menu(query, new_lang)

# ==================== Handlers ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    await db.create_user(user_id, user.username or user.full_name)
    if user_id == CONFIG["ADMIN_ID"]:
        await db.set_admin(user_id)
    lang = await db.get_user_lang(user_id)
    await update.message.reply_text(get_welcome_text(lang))
    await send_main_menu(update, lang)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    text = update.message.text
    await db.create_user(user_id, user.username or user.full_name)
    if user_id == CONFIG["ADMIN_ID"]:
        await db.set_admin(user_id)
    await route_main_menu_text(update, context, text)

async def show_contact(update: Update, lang: str):
    await update.message.reply_text(
        get_contact_text(lang),
        parse_mode="Markdown",
        reply_markup=get_contact_keyboard(lang)
    )

async def show_balance(update: Update, lang: str):
    balance = await db.get_balance(update.effective_user.id)
    await update.message.reply_text(
        get_text('balance_text', lang, balance=balance),
        parse_mode="Markdown"
    )

async def show_plans(update: Update, lang: str):
    plans = await db.get_plans()
    keyboard = []
    for plan in plans:
        btn_text = f"📦 {plan['name']} • {plan['price']} THB"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"buy_{plan['id']}")])
    keyboard.append([InlineKeyboardButton(get_text('back', lang), callback_data="menu_back")])
    await update.message.reply_text(
        get_text('select_plan', lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def start_topup(update: Update, lang: str):
    amounts = [40, 70, 100]
    keyboard = [[InlineKeyboardButton(f"💵 {amt} THB", callback_data=f"topup_amt_{amt}")] for amt in amounts]
    keyboard.append([InlineKeyboardButton(get_text('back', lang), callback_data="menu_back")])
    await update.message.reply_text(
        get_text('select_amount', lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def topup_amount_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)

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
        await query.edit_message_text(get_text('no_banks', lang))
        return ConversationHandler.END

    try:
        await query.message.delete()
    except Exception:
        pass
    chat_id = query.message.chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text=get_text('topup_prompt', lang, amount=amount),
        parse_mode="Markdown"
    )
    for bank in banks:
        caption = get_text('bank_caption', lang,
                           name=bank['name'],
                           number=bank['number'],
                           holder=bank['holder'],
                           amount=amount)
        if bank.get('qr_file_id'):
            await context.bot.send_photo(chat_id=chat_id, photo=bank['qr_file_id'], caption=caption, parse_mode="Markdown")
        elif bank.get('qr_url'):
            await context.bot.send_photo(chat_id=chat_id, photo=bank['qr_url'], caption=caption, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=chat_id, text=caption, parse_mode="Markdown")
    await context.bot.send_message(
        chat_id=chat_id,
        text=get_text('send_slip', lang),
        parse_mode="Markdown"
    )
    return TO_SLIP

async def receive_slip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)
    photo = update.message.photo[-1]
    file_id = photo.file_id
    amount = context.user_data.get("topup_amount")
    if not amount:
        await update.message.reply_text(get_text('cancel', lang))
        await send_main_menu(update, lang)
        return ConversationHandler.END
    topup_id = await db.create_topup(user_id, amount, file_id)
    await update.message.reply_text(get_text('topup_sent', lang, amount=amount))
    await send_main_menu(update, lang)
    admin_id = CONFIG["ADMIN_ID"]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{topup_id}"),
         InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{topup_id}")]
    ])
    user_mention = f"[{update.effective_user.full_name}](tg://user?id={user_id})"
    await context.bot.send_photo(
        chat_id=admin_id,
        photo=file_id,
        caption=f"🔔 *New Top-up Request*\n\n👤 User: {user_mention}\n💵 Amount: *{amount} THB*\n🆔 Request ID: `{topup_id}`",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    context.user_data.pop("topup_amount", None)
    return ConversationHandler.END

async def show_account(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    user_id = update.effective_user.id
    clients = await db.get_clients(user_id)
    if not clients:
        await update.message.reply_text(get_text('no_active_plan', lang), parse_mode="Markdown")
        return
    await update.message.reply_text(
        get_text('account_info', lang, count=len(clients)),
        parse_mode="Markdown"
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
            reply_markup=get_config_action_keyboard(client["row_id"], lang)
        )
        try:
            link = generate_vless_link(client["uuid"], client["email"])
            qr_bytes = generate_qr_bytes(link)
            await update.message.reply_photo(
                photo=qr_bytes,
                caption=f"📱 *QR for:* `{client['email']}`",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Failed to generate QR: {e}")
        await send_client_config_block(update.message, client, lang)

async def show_admin_panel(update: Update, lang: str):
    keyboard = [
        [InlineKeyboardButton(get_text('admin_add_bank', lang), callback_data="admin_addbank")],
        [InlineKeyboardButton(get_text('admin_pending_topups', lang), callback_data="admin_pending")],
        [InlineKeyboardButton(get_text('admin_manage_banks', lang), callback_data="admin_listbanks")],
        [InlineKeyboardButton(get_text('admin_broadcast', lang), callback_data="admin_broadcast")],
        [InlineKeyboardButton(get_text('back', lang), callback_data="menu_back")],
    ]
    await update.message.reply_text(
        "⚙️ Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    lang = await db.get_user_lang(user_id)

    if data == "copy_not_supported":
        await query.answer(get_text('copy_not_supported_alert', lang), show_alert=True)
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
        # Not used anymore, but kept for compatibility
        return
    if data.startswith("delcfg_"):
        row_id = int(data.split("_")[1])
        client = await db.get_client_by_row_id(row_id)
        if not client:
            await query.answer(get_text('no_active_plan', lang), show_alert=True)
            return
        is_admin = await db.is_admin(user_id)
        if client["user_id"] != user_id and not is_admin:
            await query.answer("You are not allowed to delete this config.", show_alert=True)
            return
        await query.edit_message_reply_markup(reply_markup=get_delete_confirm_keyboard(row_id, lang))
        return
    if data.startswith("canceldelcfg_"):
        row_id = int(data.split("_")[1])
        client = await db.get_client_by_row_id(row_id)
        if not client:
            return
        await query.edit_message_reply_markup(reply_markup=get_config_action_keyboard(row_id, lang))
        return
    if data.startswith("confirmdelcfg_"):
        row_id = int(data.split("_")[1])
        client = await db.get_client_by_row_id(row_id)
        if not client:
            await query.answer(get_text('no_active_plan', lang), show_alert=True)
            return
        is_admin = await db.is_admin(user_id)
        if client["user_id"] != user_id and not is_admin:
            await query.answer("You are not allowed to delete this config.", show_alert=True)
            return
        try:
            if xui:
                xui.delete_client(client["uuid"], inbound_id=CONFIG["INBOUND_ID"], email=client["email"])
            await db.delete_client_by_row_id(row_id)
            await query.edit_message_text(
                get_text('config_deleted', lang, email=client['email'], uuid=client['uuid']),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Delete config failed: {e}")
            await query.edit_message_text(
                get_text('delete_failed', lang, error=str(e)[:300]),
                parse_mode="Markdown"
            )
        return
    if data.startswith("approve_") or data.startswith("cancel_"):
        parts = data.split("_")
        action = parts[0]
        topup_id = int(parts[1])
        context.user_data["admin_action"] = {"action": action, "topup_id": topup_id}
        try:
            await query.edit_message_caption(
                caption=get_text('admin_note', lang),
                parse_mode="Markdown"
            )
        except Exception:
            await query.message.reply_text(
                get_text('admin_note', lang),
                parse_mode="Markdown"
            )
        return ADMIN_NOTE
    if data == "admin_addbank":
        await query.edit_message_text(get_text('bank_name_prompt', lang))
        return BANK_NAME
    if data == "admin_pending":
        await show_pending_topups(query, context, lang)
        return
    if data == "admin_listbanks":
        await manage_banks(query, lang)
        return
    if data == "admin_broadcast":
        await query.edit_message_text(get_text('broadcast_prompt', lang))
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
            await query.answer("Bank not found.")
            return
        context.user_data["edit_bank_id"] = bank_id
        context.user_data["edit_bank"] = bank
        await query.edit_message_text(
            f"✏️ Editing bank: {bank['name']}\n\nEnter new name (or /skip to keep):"
        )
        return BANK_EDIT_NAME
    if not await db.is_admin(user_id):
        await send_main_menu(query, lang)

async def show_pending_topups(query, context: ContextTypes.DEFAULT_TYPE, lang: str):
    pending = await db.get_pending_topups()
    if not pending:
        await query.edit_message_text(get_text('no_pending_topups', lang))
        return
    await query.edit_message_text(
        get_text('pending_header', lang, count=len(pending)),
        parse_mode="Markdown"
    )
    for req in pending:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{req['id']}"),
             InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{req['id']}")]
        ])
        caption = get_text('pending_caption', lang,
                           id=req['id'],
                           user_id=req['user_id'],
                           amount=req['amount'],
                           created=req['created_at'])
        if req.get("slip_file_id"):
            await context.bot.send_photo(chat_id=query.message.chat.id, photo=req["slip_file_id"], caption=caption, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=query.message.chat.id, text=caption, reply_markup=keyboard, parse_mode="Markdown")

async def manage_banks(query, lang: str):
    banks = await db.get_banks()
    keyboard = []
    for bank in banks:
        keyboard.append([
            InlineKeyboardButton(f"✏️ Edit {bank['name']}", callback_data=f"editbank_{bank['id']}"),
            InlineKeyboardButton("❌ Delete", callback_data=f"delbank_{bank['id']}")
        ])
    keyboard.append([InlineKeyboardButton(get_text('admin_add_bank', lang), callback_data="admin_addbank")])
    keyboard.append([InlineKeyboardButton(get_text('back', lang), callback_data="menu_back")])
    await query.edit_message_text(
        "🏦 *Manage Banks*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = update.effective_user.id
    if not await db.is_admin(sender_id):
        await update.message.reply_text("❌ Admin only.")
        return ConversationHandler.END
    text = update.message.text
    users = await db.get_all_users()
    if not users:
        await update.message.reply_text("ℹ️ No users found.")
        await send_main_menu(update)
        return ConversationHandler.END
    await update.message.reply_text(get_text('broadcast_sending', 'en'))
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
        get_text('broadcast_result', 'en', sent=sent, failed=failed)
    )
    await send_main_menu(update)
    return ConversationHandler.END

# ==================== Admin Note Conversation ====================
async def admin_note_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action_data = context.user_data.get("admin_action")
    if not action_data:
        await update.message.reply_text("Session expired.")
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    note = None if text == "/skip" else text
    topup_id = action_data["topup_id"]
    action = action_data["action"]
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)
    if action == "approve":
        await approve_topup_with_note(update, context, topup_id, note, lang)
    else:
        await cancel_topup_with_note(update, context, topup_id, note, lang)
    context.user_data.pop("admin_action", None)
    await send_main_menu(update, lang)
    return ConversationHandler.END

async def approve_topup_with_note(update: Update, context: ContextTypes.DEFAULT_TYPE, topup_id: int, note: str = None, lang: str = 'en'):
    topup = await db.get_topup(topup_id)
    if not topup or topup["status"] != "pending":
        await update.message.reply_text("Already processed.")
        return
    await db.update_topup_status(topup_id, "approved")
    await db.update_balance(topup["user_id"], topup["amount"])
    msg = get_text('topup_approved', lang, amount=topup['amount'])
    if note:
        msg += f"\n📝 Admin Note: {note}"
    await context.bot.send_message(topup["user_id"], msg)
    await update.message.reply_text(f"✅ Top-up {topup['amount']} THB approved and credit added successfully.")

async def cancel_topup_with_note(update: Update, context: ContextTypes.DEFAULT_TYPE, topup_id: int, note: str = None, lang: str = 'en'):
    topup = await db.get_topup(topup_id)
    if not topup or topup["status"] != "pending":
        await update.message.reply_text("Already processed.")
        return
    await db.update_topup_status(topup_id, "cancelled")
    msg = get_text('topup_cancelled', lang, amount=topup['amount'])
    if note:
        msg += f"\n📝 Admin Note: {note}"
    await context.bot.send_message(topup["user_id"], msg)
    await update.message.reply_text(f"❌ Top-up {topup['amount']} THB cancelled.")

# ==================== Bank Addition Conversation ====================
async def start_bank_addition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(get_text('bank_name_prompt', 'en'))
    return BANK_NAME

async def bank_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_name"] = update.message.text
    await update.message.reply_text(get_text('bank_number_prompt', 'en'))
    return BANK_NUMBER

async def bank_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_number"] = update.message.text
    await update.message.reply_text(get_text('bank_holder_prompt', 'en'))
    return BANK_HOLDER

async def bank_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["bank_holder"] = update.message.text
    await update.message.reply_text(get_text('bank_qr_prompt', 'en'))
    return BANK_QR

async def bank_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip() if update.message.text else ""
    if update.message.photo:
        photo = update.message.photo[-1]
        context.user_data["bank_qr_file_id"] = photo.file_id
        context.user_data["bank_qr_url"] = None
    elif text == "/skip":
        context.user_data["bank_qr_file_id"] = None
        context.user_data["bank_qr_url"] = None
    elif text.startswith(("http://", "https://")):
        context.user_data["bank_qr_url"] = text
        context.user_data["bank_qr_file_id"] = None
    else:
        await update.message.reply_text("❌ Please send a photo, a valid URL, or /skip.")
        return BANK_QR
    await db.add_bank(
        context.user_data["bank_name"],
        context.user_data["bank_number"],
        context.user_data["bank_holder"],
        context.user_data.get("bank_qr_file_id"),
        context.user_data.get("bank_qr_url")
    )
    await update.message.reply_text(get_text('bank_added', 'en'))
    await send_main_menu(update)
    return ConversationHandler.END

# ==================== Bank Edit Conversation ====================
async def edit_bank_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "/skip":
        context.user_data["edit_bank_name"] = update.message.text
    else:
        context.user_data["edit_bank_name"] = context.user_data["edit_bank"]["name"]
    await update.message.reply_text("💳 Enter new account number (or /skip):")
    return BANK_EDIT_NUMBER

async def edit_bank_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "/skip":
        context.user_data["edit_bank_number"] = update.message.text
    else:
        context.user_data["edit_bank_number"] = context.user_data["edit_bank"]["number"]
    await update.message.reply_text("👤 Enter new account holder name (or /skip):")
    return BANK_EDIT_HOLDER

async def edit_bank_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "/skip":
        context.user_data["edit_bank_holder"] = update.message.text
    else:
        context.user_data["edit_bank_holder"] = context.user_data["edit_bank"]["holder"]
    await update.message.reply_text("📷 Send new QR code photo or URL (or /skip to keep existing):")
    return BANK_EDIT_QR

async def edit_bank_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("❌ Invalid input. Use /skip to keep existing.")
        return BANK_EDIT_QR
    await db.update_bank(
        bank_id,
        context.user_data["edit_bank_name"],
        context.user_data["edit_bank_number"],
        context.user_data["edit_bank_holder"],
        qr_file_id,
        qr_url
    )
    await update.message.reply_text("✅ Bank updated successfully.")
    await send_main_menu(update)
    return ConversationHandler.END

async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("pending_buy_plan_id", None)
    context.user_data.pop("pending_buy_username", None)
    lang = await db.get_user_lang(update.effective_user.id)
    await update.message.reply_text(get_text('cancel', lang))
    await send_main_menu(update, lang)
    return ConversationHandler.END

# ==================== Buy Plan Conversation ====================
async def buy_plan_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        get_text('enter_username', lang),
        parse_mode="Markdown"
    )
    return BUY_USERNAME

async def buy_username_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    lang = await db.get_user_lang(user_id)
    if text in [get_text('buy_plan', lang), get_text('topup', lang), get_text('account', lang),
                get_text('balance', lang), get_text('contact', lang), get_text('language', lang),
                get_text('admin_panel', lang)]:
        context.user_data.pop("pending_buy_plan_id", None)
        context.user_data.pop("pending_buy_username", None)
        await update.message.reply_text(get_text('back_to_menu', lang))
        await route_main_menu_text(update, context, text)
        return ConversationHandler.END
    username = sanitize_username(text)
    plan_id = context.user_data.get("pending_buy_plan_id")
    if not plan_id:
        await update.message.reply_text("❌ Buy session expired. Please select plan again.")
        await send_main_menu(update, lang)
        return ConversationHandler.END
    if not is_valid_xui_email_value(username):
        await update.message.reply_text(get_text('invalid_username', lang))
        return BUY_USERNAME
    if await db.email_exists(username):
        await update.message.reply_text(get_text('username_exists_db', lang))
        return BUY_USERNAME
    if xui and xui.email_exists(username):
        await update.message.reply_text(get_text('username_exists_panel', lang))
        return BUY_USERNAME
    context.user_data["pending_buy_username"] = username
    await process_buy_plan_from_message(update, context, plan_id, username, lang)
    context.user_data.pop("pending_buy_plan_id", None)
    context.user_data.pop("pending_buy_username", None)
    return ConversationHandler.END

async def process_buy_plan_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_id: int, desired_username: str, lang: str):
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
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(get_text('topup', lang), callback_data="goto_topup")],
                [InlineKeyboardButton(get_text('back', lang), callback_data="menu_back")]
            ])
            await update.message.reply_text(
                get_text('insufficient_balance', lang, balance=balance, price=plan["price"], need=need),
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            return
        await db.update_balance(user_id, -plan["price"])
    await update.message.reply_text(get_text('creating_client', lang))
    try:
        uuid_str = str(uuid.uuid4())
        email = desired_username
        expiry_time_dt = datetime.utcnow() + timedelta(days=plan["days"])
        expiry_time_ms = int(expiry_time_dt.timestamp() * 1000)
        total_bytes = plan["data_gb"] * 1024**3
        if xui and xui.email_exists(email):
            raise Exception("This username already exists in X-UI panel.")
        xui.add_client(
            CONFIG["INBOUND_ID"],
            email,
            uuid_str,
            total_gb=total_bytes,
            expiry_time=expiry_time_ms
        )
        await db.add_client(
            user_id=user_id,
            uuid_str=uuid_str,
            email=email,
            plan_id=plan_id,
            total_gb=total_bytes,
            expiry_at=expiry_time_dt
        )
        link = generate_vless_link(uuid_str, email)
        qr_bytes = generate_qr_bytes(link)
        summary_caption = get_text('purchase_success', lang,
                                   plan=plan['name'],
                                   expiry=expiry_time_dt.strftime('%d %b %Y'),
                                   email=email)
        await update.message.reply_photo(photo=qr_bytes, caption=summary_caption, parse_mode="Markdown")
        config_text = get_text('vless_config', lang, config=html.escape(link))
        copy_keyboard = get_vless_copy_keyboard(link, lang)
        if HAS_COPY_TEXT_BUTTON and CopyTextButton is not None:
            await update.message.reply_text(config_text, parse_mode="HTML", reply_markup=copy_keyboard)
        else:
            await update.message.reply_text(
                config_text + get_text('copy_fallback', lang),
                parse_mode="HTML",
                reply_markup=copy_keyboard
            )
        await send_main_menu(update, lang)
    except Exception as e:
        logger.error(f"Add client error: {e}")
        if not is_admin:
            await db.update_balance(user_id, plan["price"])
        await update.message.reply_text(f"❌ Failed: {str(e)[:300]}")
        await send_main_menu(update, lang)

# ==================== Auto Cleanup & Config ====================
def kill_old_bot():
    """Kill any existing bot process using the same PID file."""
    pid_file = "bot.pid"
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                old_pid = int(f.read().strip())
            # Check if process exists
            os.kill(old_pid, 0)  # signal 0 just checks
            # Process exists, kill it
            os.kill(old_pid, 9)  # SIGKILL
            logger.info(f"Killed old bot process with PID {old_pid}")
        except (ProcessLookupError, ValueError, OSError):
            pass  # No such process or invalid PID
        finally:
            os.remove(pid_file)
    # Write current PID
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

def install_dependencies():
    """Ensure required packages are installed."""
    required = ['requests', 'python-telegram-bot', 'qrcode[pil]']
    for pkg in required:
        try:
            __import__(pkg.split('[')[0])
        except ImportError:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])

def get_config():
    print("\n🔧 First-time configuration (Alireza0 X-UI Panel)\n")
    CONFIG["BOT_TOKEN"] = input("Enter Bot Token: ").strip()
    CONFIG["ADMIN_ID"] = int(input("Enter Admin Telegram ID: ").strip())
    CONFIG["PANEL_URL"] = input("Enter X-UI Panel URL (with custom path if any): ").strip()
    CONFIG["PANEL_USER"] = input("Enter Panel Username: ").strip()
    CONFIG["PANEL_PASS"] = input("Enter Panel Password: ").strip()
    CONFIG["INBOUND_ID"] = int(input("Enter Inbound ID: ").strip())
    CONFIG["PORT"] = int(input("Enter Port: ").strip())
    ws_path = input("Enter WS Path [default: /]: ").strip()
    CONFIG["WS_PATH"] = ws_path if ws_path else "/"
    CONFIG["SERVER_ADDRESS"] = input("Enter Server Address (VPS IP): ").strip()
    CONFIG["WS_HOST"] = input("Enter WebSocket Host (domain): ").strip()
    save_config()
    print(f"\n✅ Configuration saved to {CONFIG_FILE}\n")

def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2, ensure_ascii=False)

def load_config() -> bool:
    global CONFIG
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update(loaded)
        CONFIG = merged
        return True
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
            return False
    return True

def ensure_config():
    loaded = load_config()
    if loaded and config_is_valid():
        logger.info(f"Loaded configuration from {CONFIG_FILE}")
        return
    if sys.stdin.isatty():
        get_config()
        return
    logger.error(f"{CONFIG_FILE} not found or incomplete. Run the bot manually once to generate it.")
    sys.exit(1)

# ==================== Main ====================
def main():
    # Auto cleanup & deps
    kill_old_bot()
    install_dependencies()
    ensure_config()
    global xui
    try:
        xui = XUIClient()
        logger.info(f"Successfully connected to Alireza0 X-UI panel. API base: {xui.base_url}")
    except Exception as e:
        logger.error(f"Cannot login to X-UI: {e}")
        print("\n❌ X-UI Login failed. Please check your Panel URL, Username, Password.")
        return
    app = Application.builder().token(CONFIG["BOT_TOKEN"]).build()
    # Conversation handlers
    admin_note_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^(approve|cancel)_")],
        states={ADMIN_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_note_input),
                              CommandHandler("skip", admin_note_input)]},
        fallbacks=[CommandHandler("cancel", cancel_edit)],
        per_message=False,
    )
    buy_plan_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(buy_plan_entry, pattern="^buy_")],
        states={BUY_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_username_input)]},
        fallbacks=[CommandHandler("cancel", cancel_edit)],
        per_message=False,
    )
    topup_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(topup_amount_selected, pattern="^topup_amt_")],
        states={TO_SLIP: [MessageHandler(filters.PHOTO, receive_slip)]},
        fallbacks=[CommandHandler("cancel", cancel_edit)],
        per_message=False,
    )
    bank_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_bank_addition, pattern="^admin_addbank$")],
        states={
            BANK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_name)],
            BANK_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_number)],
            BANK_HOLDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, bank_holder)],
            BANK_QR: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), bank_qr),
                      CommandHandler("skip", bank_qr)],
        },
        fallbacks=[CommandHandler("cancel", cancel_edit)],
        per_message=False,
    )
    bank_edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^editbank_")],
        states={
            BANK_EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bank_name),
                             CommandHandler("skip", edit_bank_name)],
            BANK_EDIT_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bank_number),
                               CommandHandler("skip", edit_bank_number)],
            BANK_EDIT_HOLDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bank_holder),
                               CommandHandler("skip", edit_bank_holder)],
            BANK_EDIT_QR: [MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), edit_bank_qr),
                           CommandHandler("skip", edit_bank_qr)],
        },
        fallbacks=[CommandHandler("cancel", cancel_edit)],
        per_message=False,
    )
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^admin_broadcast$")],
        states={BROADCAST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_input)]},
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
    logger.info("Bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
