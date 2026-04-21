import json, uuid, requests, sqlite3
from telegram import *
from telegram.ext import *

# === SETUP ===
print("=== FIRST RUN SETUP ===")
BOT_TOKEN = input("BOT TOKEN: ").strip()
ADMIN_ID = int(input("ADMIN ID: ").strip())
PANEL_URL = input("PANEL URL: ").strip()
USERNAME = input("PANEL USERNAME: ").strip()
PASSWORD = input("PANEL PASSWORD: ").strip()
INBOUND_ID = int(input("INBOUND ID: ").strip())
PORT = input("PORT: ").strip()
PATH = input("WS PATH: ").strip()
HOST = input("HOST: ").strip()

# === DATABASE (SQLite for persistence) ===
conn = sqlite3.connect("bot_db.sqlite3")
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0)''')
c.execute('''CREATE TABLE IF NOT EXISTS banks(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, number TEXT, holder TEXT, qr TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS topups(id TEXT PRIMARY KEY, user_id INTEGER, amount REAL, status TEXT, slip TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY, name TEXT, days INTEGER, gb INTEGER, price REAL)''')
conn.commit()

# === PRESET PLANS ===
def init_plans():
    c.execute("SELECT COUNT(*) FROM plans")
    if c.fetchone()[0] == 0:
        plans = [
            ("30 DAYS", 30, 200, 40),
            ("60 DAYS", 60, 300, 60)
        ]
        for p in plans:
            c.execute("INSERT INTO plans(name, days, gb, price) VALUES(?,?,?,?)", p)
        conn.commit()
init_plans()

# === Keyboards ===
main_menu = ReplyKeyboardMarkup([
    ["🛒 Buy 30D","🛒 Buy 60D"],
    ["💰 TopUp","👤 Account"],
    ["🏦 Banks"]
], resize_keyboard=True)

topup_menu = ReplyKeyboardMarkup([
    ["💵 40","💵 60"],
    ["💵 100"],["🔙 Back"]
], resize_keyboard=True)

# === X-UI CREATE CLIENT ===
def create_vless(user, days, gb):
    s = requests.Session()
    s.post(f"{PANEL_URL}/login", data={"username": USERNAME,"password": PASSWORD})
    uid = str(uuid.uuid4())
    # Add client
    data = {"id": INBOUND_ID,"settings":json.dumps({"clients":[{"id":uid,"email":user}]})}
    s.post(f"{PANEL_URL}/panel/inbound/addClient", data=data)
    ip = PANEL_URL.split("//")[1].split("/")[0].split(":")[0]
    link = f"vless://{uid}@{ip}:{PORT}?type=ws&security=none&path=%2F{PATH.strip('/')}&host={HOST}#{user}"
    return link

# === HANDLER ===
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.message.from_user
    uid = user.id

    if text == "/start":
        await update.message.reply_text("Welcome!", reply_markup=main_menu)

    # ---------- BUY PLAN ----------
    elif text in ["🛒 Buy 30D","🛒 Buy 60D"]:
        plan_name = "30 DAYS" if "30D" in text else "60 DAYS"
        c.execute("SELECT days, gb, price FROM plans WHERE name=?", (plan_name,))
        days, gb, price = c.fetchone()
        # Admin unlimited
        if uid != ADMIN_ID:
            c.execute("SELECT balance FROM users WHERE id=?",(uid,))
            row = c.fetchone()
            bal = row[0] if row else 0
            if bal < price:
                await update.message.reply_text("❌ Balance not enough")
                return
            c.execute("INSERT OR IGNORE INTO users(id,username) VALUES(?,?)",(uid,user.username or f"user_{uid}"))
            c.execute("UPDATE users SET balance=balance-? WHERE id=?",(price,uid))
            conn.commit()
        link = create_vless(user.username or f"user_{uid}", days, gb)
        await update.message.reply_text(f"✅ {plan_name}\n{gb}GB\nPrice: {price}\n\n{link}")

    # ---------- TOPUP ----------
    elif text == "💰 TopUp":
        await update.message.reply_text("Choose amount:", reply_markup=topup_menu)

    elif text.startswith("💵"):
        amount = int(text.replace("💵","").strip())
        req_id = str(uuid.uuid4())[:6]
        c.execute("INSERT INTO topups(id,user_id,amount,status) VALUES(?,?,?,?)",(req_id,uid,amount,"pending"))
        conn.commit()
        # Show banks
        c.execute("SELECT id,name FROM banks")
        banks = c.fetchall()
        if not banks:
            await update.message.reply_text("No bank added by admin.")
            return
        buttons=[[InlineKeyboardButton(b[1], callback_data=f"bank_{req_id}_{b[0]}")] for b in banks]
        await update.message.reply_text("Select bank:", reply_markup=InlineKeyboardMarkup(buttons))

    # ---------- ACCOUNT ----------
    elif text == "👤 Account":
        if uid == ADMIN_ID:
            await update.message.reply_text("👑 Admin Unlimited")
        else:
            c.execute("SELECT balance FROM users WHERE id=?",(uid,))
            bal = c.fetchone()[0] if c.fetchone() else 0
            await update.message.reply_text(f"Balance: {bal}")

    # ---------- BANKS ADMIN ----------
    elif text == "🏦 Banks" and uid == ADMIN_ID:
        await update.message.reply_text("Add bank format:\nName,Number,Holder\nSend QR after text")

    elif text == "🔙 Back":
        await update.message.reply_text("Back", reply_markup=main_menu)

# === CALLBACK HANDLER ===
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data.split("_")
    if data[0]=="bank":
        req_id,user_id,bank_id = data[1],int(data[1]),int(data[2])
        await q.message.reply_text(f"Send payment slip to admin for approval")
    elif data[0] in ["ok","no"]:
        c.execute("SELECT user_id,amount FROM topups WHERE id=?",(data[1],))
        row = c.fetchone()
        if not row: return
        uid,amt = row
        if data[0]=="ok":
            c.execute("INSERT OR IGNORE INTO users(id,username,balance) VALUES(?,?,?)",(uid,"user",0))
            c.execute("UPDATE users SET balance=balance+? WHERE id=?",(amt,uid))
            c.execute("UPDATE topups SET status='approved' WHERE id=?",(data[1],))
        else:
            c.execute("UPDATE topups SET status='cancel' WHERE id=?",(data[1],))
        conn.commit()
        await q.edit_message_text(f"TopUp {data[0].upper()} for user {uid}")

# === RUN ===
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT, handle))
app.add_handler(CallbackQueryHandler(callback))

print("🚀 Pro Bot running...")
app.run_polling()
