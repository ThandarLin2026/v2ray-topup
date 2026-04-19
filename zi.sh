#!/bin/bash
# =====================================================
# ZIVPN UDP + Full Management System (Complete Fix)
# No Prefix, Slip Upload, Telegram Bot, HTML Panel
# =====================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

clear
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   ZIVPN UDP + Panel + Telegram Bot    ${NC}"
echo -e "${GREEN}       Complete Fix Installer          ${NC}"
echo -e "${GREEN}========================================${NC}"

# ------------------------------
# Collect User Inputs
# ------------------------------
echo -e "${YELLOW}Please enter the following information:${NC}"
echo ""
read -p "Bot Token (from @BotFather): " BOT_TOKEN
read -p "Admin Telegram Chat ID (e.g., 123456789): " ADMIN_CHAT_ID
read -p "Hostname/Domain (e.g., vpn.yourdomain.com): " HOSTNAME
read -p "Panel Web Port (default 80): " PANEL_PORT
PANEL_PORT=${PANEL_PORT:-80}
echo ""

PUBLIC_IP=$(curl -s ifconfig.me)
SERVER_IP=${PUBLIC_IP}

echo -e "${GREEN}Configuration Summary:${NC}"
echo "--------------------------------------"
echo "Bot Token:       ${BOT_TOKEN}"
echo "Admin Chat ID:   ${ADMIN_CHAT_ID}"
echo "Hostname:        ${HOSTNAME}"
echo "Panel Port:      ${PANEL_PORT}"
echo "Server IP:       ${SERVER_IP}"
echo "VPN Prefix:      (none - exact username)"
echo "--------------------------------------"
read -p "Continue with installation? (y/n): " CONFIRM
if [[ "$CONFIRM" != "y" ]]; then
    echo "Installation aborted."
    exit 1
fi

# ------------------------------
# 1. System Update & Base Packages
# ------------------------------
echo -e "${YELLOW}[1/10] Updating system...${NC}"
apt-get update && apt-get upgrade -y
apt-get install -y curl wget git nginx python3 python3-pip python3-venv \
    mariadb-server openssl iptables ufw net-tools certbot python3-certbot-nginx

# ------------------------------
# 2. Install ZIVPN UDP Service
# ------------------------------
echo -e "${YELLOW}[2/10] Installing ZIVPN UDP...${NC}"
systemctl stop zivpn.service 2>/dev/null || true
wget -q https://github.com/zahidbd2/udp-zivpn/releases/download/udp-zivpn_1.4.9/udp-zivpn-linux-amd64 -O /usr/local/bin/zivpn
chmod +x /usr/local/bin/zivpn
mkdir -p /etc/zivpn
wget -q https://raw.githubusercontent.com/zahidbd2/udp-zivpn/main/config.json -O /etc/zivpn/config.json

openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 \
    -subj "/C=US/ST=California/L=Los Angeles/O=Example Corp/OU=IT Department/CN=zivpn" \
    -keyout "/etc/zivpn/zivpn.key" -out "/etc/zivpn/zivpn.crt"

sysctl -w net.core.rmem_max=16777216
sysctl -w net.core.wmem_max=16777216

cat <<EOF > /etc/systemd/system/zivpn.service
[Unit]
Description=zivpn VPN Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/etc/zivpn
ExecStart=/usr/local/bin/zivpn server -c /etc/zivpn/config.json
Restart=always
RestartSec=3
Environment=ZIVPN_LOG_LEVEL=info
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

DEFAULT_IFACE=$(ip -4 route ls | grep default | grep -Po '(?<=dev )(\S+)' | head -1)
iptables -t nat -A PREROUTING -i ${DEFAULT_IFACE} -p udp --dport 6000:19999 -j DNAT --to-destination :5667 2>/dev/null || true
ufw allow 6000:19999/udp
ufw allow 5667/udp
ufw allow ${PANEL_PORT}/tcp

systemctl enable zivpn.service
systemctl start zivpn.service

# ------------------------------
# 3. Database Setup (Fix MariaDB Access)
# ------------------------------
echo -e "${YELLOW}[3/10] Setting up MariaDB...${NC}"
systemctl start mariadb
systemctl enable mariadb

# Fix: Set root password without requiring current password
mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('zivpn123');" 2>/dev/null || \
mysql -e "SET PASSWORD FOR 'root'@'localhost' = PASSWORD('zivpn123');" 2>/dev/null || \
mysql -e "FLUSH PRIVILEGES;" 2>/dev/null || true

mysql -u root -pzivpn123 <<EOF 2>/dev/null || mysql <<EOF
CREATE DATABASE IF NOT EXISTS zivpn_panel;
CREATE USER IF NOT EXISTS 'zivpn'@'localhost' IDENTIFIED BY 'zivpn_pass';
GRANT ALL PRIVILEGES ON zivpn_panel.* TO 'zivpn'@'localhost';
FLUSH PRIVILEGES;
EOF

# ------------------------------
# 4. Python Backend Setup
# ------------------------------
echo -e "${YELLOW}[4/10] Installing Python Backend...${NC}"
mkdir -p /opt/zivpn-panel /opt/zivpn-panel/uploads
cd /opt/zivpn-panel
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install flask flask-sqlalchemy flask-cors flask-login pymysql python-telegram-bot[job-queue] gunicorn pyyaml werkzeug

# Create app.py (No Prefix)
cat > app.py <<PYCODE
import os
import json
import subprocess
import secrets
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='/var/www/zivpn-panel', static_url_path='')
CORS(app, supports_credentials=True)

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://zivpn:zivpn_pass@localhost/zivpn_panel'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['UPLOAD_FOLDER'] = '/opt/zivpn-panel/uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)

HOSTNAME = "${HOSTNAME}"
ADMIN_CHAT_ID = ${ADMIN_CHAT_ID}
BOT_TOKEN = "${BOT_TOKEN}"

# ------------------------------
# Models
# ------------------------------
class PanelUser(UserMixin, db.Model):
    __tablename__ = 'panel_users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    balance = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class VPNAccount(db.Model):
    __tablename__ = 'vpn_accounts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('panel_users.id'), nullable=False)
    vpn_username = db.Column(db.String(128), unique=True, nullable=False)
    vpn_password = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expired_at = db.Column(db.DateTime, nullable=False)
    active = db.Column(db.Boolean, default=True)

class TopupRequest(db.Model):
    __tablename__ = 'topup_requests'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('panel_users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    slip_filename = db.Column(db.String(255))
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime)

@login_manager.user_loader
def load_user(user_id):
    return PanelUser.query.get(int(user_id))

def update_zivpn_config():
    active_accounts = VPNAccount.query.filter_by(active=True).filter(VPNAccount.expired_at > datetime.utcnow()).all()
    passwords = [acc.vpn_password for acc in active_accounts]
    if not passwords:
        passwords = ["zivpn"]
    with open('/etc/zivpn/config.json', 'r') as f:
        config = json.load(f)
    config['config'] = passwords
    with open('/etc/zivpn/config.json', 'w') as f:
        json.dump(config, f, indent=2)
    subprocess.run(['systemctl', 'reload', 'zivpn'], check=False)

def send_telegram_message(chat_id, text, photo=None):
    import requests
    try:
        if photo:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
            files = {'photo': open(photo, 'rb')}
            data = {'chat_id': chat_id, 'caption': text}
            requests.post(url, files=files, data=data)
        else:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            requests.post(url, json={'chat_id': chat_id, 'text': text})
    except Exception as e:
        print(f"Telegram error: {e}")

# ------------------------------
# Auth Routes
# ------------------------------
@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    if not username.isalnum():
        return jsonify({'error': 'Username must be alphanumeric'}), 400
    if PanelUser.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already taken'}), 409
    user = PanelUser(username=username, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'Registration successful'})

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    user = PanelUser.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
        login_user(user)
        return jsonify({'message': 'Login successful', 'username': user.username, 'balance': user.balance})
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/auth/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return jsonify({'message': 'Logged out'})

@app.route('/api/auth/status')
def auth_status():
    if current_user.is_authenticated:
        return jsonify({'authenticated': True, 'username': current_user.username, 'balance': current_user.balance})
    return jsonify({'authenticated': False})

# ------------------------------
# Topup Routes
# ------------------------------
@app.route('/api/topup/request', methods=['POST'])
@login_required
def create_topup():
    amount = request.form.get('amount')
    if 'slip' not in request.files:
        return jsonify({'error': 'Slip image required'}), 400
    file = request.files['slip']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    req = TopupRequest(user_id=current_user.id, amount=float(amount), slip_filename=filename)
    db.session.add(req)
    db.session.commit()
    text = f"🔔 New Topup Request\\nUser: {current_user.username}\\nAmount: {amount} THB"
    send_telegram_message(ADMIN_CHAT_ID, text, photo=filepath)
    return jsonify({'message': 'Topup request submitted'})

# ------------------------------
# Account Routes (No Prefix)
# ------------------------------
@app.route('/api/account/create', methods=['POST'])
@login_required
def create_account():
    data = request.json
    vpn_username = data.get('username')
    vpn_password = data.get('password')
    days = int(data.get('days', 0))
    prices = {30: 50, 60: 80}
    if days not in prices:
        return jsonify({'error': 'Invalid package'}), 400
    cost = prices[days]
    if current_user.balance < cost:
        return jsonify({'error': 'Insufficient balance'}), 402
    if VPNAccount.query.filter_by(vpn_username=vpn_username).first():
        return jsonify({'error': 'Username taken'}), 409
    current_user.balance -= cost
    expired_at = datetime.utcnow() + timedelta(days=days)
    acc = VPNAccount(user_id=current_user.id, vpn_username=vpn_username,
                     vpn_password=vpn_password, expired_at=expired_at, active=True)
    db.session.add(acc)
    db.session.commit()
    update_zivpn_config()
    return jsonify({
        'message': 'Account created',
        'server_ip': '${SERVER_IP}',
        'hostname': HOSTNAME,
        'username': vpn_username,
        'password': vpn_password,
        'expired_at': expired_at.strftime('%Y-%m-%d %H:%M:%S'),
        'days_left': days
    })

@app.route('/api/account/list')
@login_required
def list_accounts():
    accs = VPNAccount.query.filter_by(user_id=current_user.id).all()
    return jsonify([{
        'username': a.vpn_username,
        'password': a.vpn_password,
        'expired_at': a.expired_at.strftime('%Y-%m-%d %H:%M:%S'),
        'days_left': (a.expired_at - datetime.utcnow()).days,
        'active': a.active and a.expired_at > datetime.utcnow()
    } for a in accs])

# ------------------------------
# Admin API
# ------------------------------
@app.route('/api/admin/topup/<int:req_id>/<action>', methods=['POST'])
def process_topup(req_id, action):
    req = TopupRequest.query.get(req_id)
    if not req:
        return jsonify({'error': 'Not found'}), 404
    if action == 'approve':
        user = PanelUser.query.get(req.user_id)
        user.balance += req.amount
        req.status = 'approved'
        req.processed_at = datetime.utcnow()
        db.session.commit()
    elif action == 'reject':
        req.status = 'rejected'
        req.processed_at = datetime.utcnow()
        db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/admin/accounts')
def admin_accounts():
    accs = VPNAccount.query.all()
    return jsonify([{
        'username': a.vpn_username,
        'password': a.vpn_password,
        'panel_user': PanelUser.query.get(a.user_id).username,
        'expired_at': a.expired_at.strftime('%Y-%m-%d %H:%M:%S'),
        'days_left': (a.expired_at - datetime.utcnow()).days,
        'active': a.active and a.expired_at > datetime.utcnow()
    } for a in accs])

@app.route('/api/admin/pending_requests')
def pending_requests():
    reqs = TopupRequest.query.filter_by(status='pending').all()
    return jsonify([{
        'id': r.id,
        'username': PanelUser.query.get(r.user_id).username,
        'amount': r.amount,
        'slip': f"/uploads/{r.slip_filename}",
        'created_at': r.created_at.strftime('%Y-%m-%d %H:%M:%S')
    } for r in reqs])

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
PYCODE

# Create expire_check.py
cat > expire_check.py <<EXPCODE
import sys
sys.path.insert(0, '/opt/zivpn-panel')
from app import app, db, VPNAccount, update_zivpn_config
from datetime import datetime
with app.app_context():
    expired = VPNAccount.query.filter(VPNAccount.active==True, VPNAccount.expired_at <= datetime.utcnow()).all()
    for a in expired:
        a.active = False
    db.session.commit()
    if expired:
        update_zivpn_config()
EXPCODE

deactivate

# ------------------------------
# 5. Telegram Bot
# ------------------------------
echo -e "${YELLOW}[5/10] Setting up Telegram Bot...${NC}"
cat > /opt/zivpn-panel/bot.py <<BOTCODE
import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = "${BOT_TOKEN}"
API_BASE = "http://127.0.0.1:5000/api"
ADMIN_CHAT_ID = ${ADMIN_CHAT_ID}
UPLOAD_FOLDER = "/opt/zivpn-panel/uploads"

logging.basicConfig(level=logging.INFO)

def api_req(endpoint):
    try:
        r = requests.get(f"{API_BASE}{endpoint}")
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Admin Bot ready. /pending to view requests, /userlist for accounts.")

async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        return
    reqs = api_req("/admin/pending_requests")
    if not reqs:
        await update.message.reply_text("No pending requests.")
        return
    for r in reqs:
        kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{r['id']}"),
               InlineKeyboardButton("❌ Reject", callback_data=f"reject_{r['id']}")]]
        text = f"*Request #{r['id']}*\nUser: {r['username']}\nAmount: {r['amount']} THB\nTime: {r['created_at']}"
        slip_path = f"{UPLOAD_FOLDER}/{r['slip'].split('/')[-1]}"
        if os.path.exists(slip_path):
            await update.message.reply_photo(photo=open(slip_path, 'rb'), caption=text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

async def userlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        return
    accs = api_req("/admin/accounts")
    if not accs:
        await update.message.reply_text("No accounts.")
        return
    for a in accs:
        txt = f"*{a['username']}* / {a['password']}\nUser: {a['panel_user']}\nExpires: {a['expired_at']} ({a['days_left']}d left)\nActive: {'✅' if a['active'] else '❌'}"
        await update.message.reply_text(txt, parse_mode='Markdown')

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(ADMIN_CHAT_ID):
        return
    act, rid = q.data.split('_')
    requests.post(f"{API_BASE}/admin/topup/{rid}/{act}")
    await q.edit_message_caption(caption=f"Request {rid} {act}d.")

def main():
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("pending", pending))
    app_bot.add_handler(CommandHandler("userlist", userlist))
    app_bot.add_handler(CallbackQueryHandler(button))
    app_bot.run_polling()

if __name__ == '__main__':
    main()
BOTCODE

# ------------------------------
# 6. Frontend HTML (with SVG Icons)
# ------------------------------
echo -e "${YELLOW}[6/10] Creating Web Panel...${NC}"
mkdir -p /var/www/zivpn-panel
cat > /var/www/zivpn-panel/index.html <<HTMLCODE
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ZIVPN Panel</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        .svg-icon { width: 24px; height: 24px; fill: currentColor; }
        .hidden { display: none !important; }
    </style>
</head>
<body>
    <div id="app" class="container py-4">
        <div id="auth-section" class="row justify-content-center">
            <div class="col-md-6">
                <div class="card shadow">
                    <div class="card-header bg-primary text-white d-flex align-items-center">
                        <svg class="svg-icon me-2" viewBox="0 0 24 24" fill="white"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
                        Login / Register
                    </div>
                    <div class="card-body">
                        <input type="text" id="username" class="form-control mb-2" placeholder="Username (alphanumeric)">
                        <input type="password" id="password" class="form-control mb-2" placeholder="Password">
                        <button class="btn btn-primary w-100 mb-2" onclick="login()">Login</button>
                        <button class="btn btn-outline-secondary w-100" onclick="register()">Register</button>
                        <div id="auth-error" class="text-danger mt-2"></div>
                    </div>
                </div>
            </div>
        </div>
        <div id="main-panel" class="hidden">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2 class="d-flex align-items-center"><svg class="svg-icon me-2" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14H9V8h2v8zm4 0h-2V8h2v8z"/></svg>ZIVPN Panel</h2>
                <div>Welcome, <span id="display-username"></span> | Balance: <span id="display-balance"></span> THB <button class="btn btn-sm btn-outline-danger ms-2" onclick="logout()">Logout</button></div>
            </div>
            <div class="row g-4">
                <div class="col-md-6">
                    <div class="card shadow">
                        <div class="card-header bg-success text-white d-flex align-items-center">
                            <svg class="svg-icon me-2" viewBox="0 0 24 24" fill="white"><path d="M20 4H4c-1.11 0-1.99.89-1.99 2L2 18c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V6c0-1.11-.89-2-2-2zm0 14H4v-6h16v6z"/></svg>
                            Top Up
                        </div>
                        <div class="card-body">
                            <select id="topup_amount" class="form-select mb-2">
                                <option value="50">50 THB</option>
                                <option value="100">100 THB</option>
                                <option value="150">150 THB</option>
                            </select>
                            <input type="file" id="slip_file" class="form-control mb-2" accept="image/*">
                            <button class="btn btn-success w-100" onclick="submitTopup()">Upload Slip & Request</button>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card shadow">
                        <div class="card-header bg-warning text-dark d-flex align-items-center">
                            <svg class="svg-icon me-2" viewBox="0 0 24 24"><path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/></svg>
                            Create VPN Account
                        </div>
                        <div class="card-body">
                            <input type="text" id="vpn_username" class="form-control mb-2" placeholder="Desired Username">
                            <input type="password" id="vpn_password" class="form-control mb-2" placeholder="VPN Password">
                            <select id="package_days" class="form-select mb-2">
                                <option value="30">30 Days - 50 THB</option>
                                <option value="60">60 Days - 80 THB</option>
                            </select>
                            <button class="btn btn-warning w-100" onclick="createAccount()">Create Account</button>
                        </div>
                    </div>
                </div>
            </div>
            <div class="card shadow mt-4">
                <div class="card-header bg-info text-white d-flex align-items-center">
                    <svg class="svg-icon me-2" viewBox="0 0 24 24" fill="white"><path d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z"/></svg>
                    My VPN Accounts
                </div>
                <div class="card-body">
                    <div id="accounts_list"></div>
                    <button class="btn btn-info mt-2" onclick="loadAccounts()">Refresh</button>
                </div>
            </div>
        </div>
    </div>
    <div class="modal fade" id="accountModal" tabindex="-1">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header bg-success text-white">
                    <h5 class="modal-title">✅ Account Created</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                </div>
                <div class="modal-body" id="modal_body"></div>
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        const API = '/api';
        let currentUser = null;
        async function apiCall(url, method='GET', data=null, isFormData=false) {
            const opts = { method, credentials: 'same-origin' };
            if (data && !isFormData) { opts.headers = {'Content-Type': 'application/json'}; opts.body = JSON.stringify(data); }
            else if (data && isFormData) { opts.body = data; }
            const resp = await fetch(API + url, opts);
            return resp.json();
        }
        async function checkAuth() {
            const resp = await apiCall('/auth/status');
            if (resp.authenticated) {
                currentUser = resp;
                document.getElementById('auth-section').classList.add('hidden');
                document.getElementById('main-panel').classList.remove('hidden');
                document.getElementById('display-username').innerText = resp.username;
                document.getElementById('display-balance').innerText = resp.balance;
                loadAccounts();
            } else {
                document.getElementById('auth-section').classList.remove('hidden');
                document.getElementById('main-panel').classList.add('hidden');
            }
        }
        async function login() {
            const u = document.getElementById('username').value;
            const p = document.getElementById('password').value;
            const resp = await apiCall('/auth/login', 'POST', {username: u, password: p});
            if (resp.error) document.getElementById('auth-error').innerText = resp.error;
            else checkAuth();
        }
        async function register() {
            const u = document.getElementById('username').value;
            const p = document.getElementById('password').value;
            const resp = await apiCall('/auth/register', 'POST', {username: u, password: p});
            if (resp.error) document.getElementById('auth-error').innerText = resp.error;
            else alert('Registration successful, please login.');
        }
        async function logout() { await apiCall('/auth/logout', 'POST'); checkAuth(); }
        async function submitTopup() {
            const amount = document.getElementById('topup_amount').value;
            const file = document.getElementById('slip_file').files[0];
            if (!file) { alert('Select slip image'); return; }
            const fd = new FormData(); fd.append('amount', amount); fd.append('slip', file);
            const resp = await fetch(API + '/topup/request', { method: 'POST', body: fd, credentials: 'same-origin' });
            const data = await resp.json();
            alert(data.message || 'Request submitted');
            document.getElementById('slip_file').value = '';
        }
        async function createAccount() {
            const u = document.getElementById('vpn_username').value;
            const p = document.getElementById('vpn_password').value;
            const d = document.getElementById('package_days').value;
            if (!u || !p) { alert('Enter username and password'); return; }
            const resp = await apiCall('/account/create', 'POST', {username: u, password: p, days: parseInt(d)});
            if (resp.error) { alert(resp.error); return; }
            document.getElementById('modal_body').innerHTML = `
                <p><strong>Server IP:</strong> ${resp.server_ip}</p>
                <p><strong>Hostname:</strong> ${resp.hostname}</p>
                <p><strong>Username:</strong> ${resp.username}</p>
                <p><strong>Password:</strong> ${resp.password}</p>
                <p><strong>Expired:</strong> ${resp.expired_at}</p>
                <p><strong>Days Left:</strong> ${resp.days_left}</p>`;
            new bootstrap.Modal(document.getElementById('accountModal')).show();
            checkAuth(); loadAccounts();
        }
        async function loadAccounts() {
            const resp = await apiCall('/account/list');
            const c = document.getElementById('accounts_list');
            if (!resp.length) { c.innerHTML = '<p>No accounts.</p>'; return; }
            c.innerHTML = resp.map(a => `<div class="border rounded p-2 mb-2"><strong>${a.username}</strong> (${a.password})<br>Expires: ${a.expired_at} | Days left: ${a.days_left} | ${a.active?'🟢':'🔴'}</div>`).join('');
        }
        checkAuth();
    </script>
</body>
</html>
HTMLCODE

# ------------------------------
# 7. Nginx Configuration
# ------------------------------
echo -e "${YELLOW}[7/10] Configuring Nginx...${NC}"
rm -f /etc/nginx/sites-enabled/default
cat <<EOF > /etc/nginx/sites-available/zivpn-panel
server {
    listen ${PANEL_PORT};
    server_name _;
    root /var/www/zivpn-panel;
    index index.html;
    client_max_body_size 5M;
    location / {
        try_files \$uri \$uri/ =404;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:5000/api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location /uploads/ {
        alias /opt/zivpn-panel/uploads/;
    }
}
EOF
ln -s /etc/nginx/sites-available/zivpn-panel /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx

# ------------------------------
# 8. Systemd Services
# ------------------------------
echo -e "${YELLOW}[8/10] Creating systemd services...${NC}"
cat <<EOF > /etc/systemd/system/zivpn-panel.service
[Unit]
Description=ZIVPN Panel Backend
After=network.target mariadb.service

[Service]
User=root
WorkingDirectory=/opt/zivpn-panel
Environment="PATH=/opt/zivpn-panel/venv/bin"
ExecStart=/opt/zivpn-panel/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5000 wsgi:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat <<EOF > /etc/systemd/system/zivpn-bot.service
[Unit]
Description=ZIVPN Telegram Bot
After=network.target mariadb.service

[Service]
User=root
WorkingDirectory=/opt/zivpn-panel
Environment="PATH=/opt/zivpn-panel/venv/bin"
ExecStart=/opt/zivpn-panel/venv/bin/python3 /opt/zivpn-panel/bot.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

cat > /opt/zivpn-panel/wsgi.py <<EOF
from app import app
if __name__ == "__main__":
    app.run()
EOF

# ------------------------------
# 9. Cron for Auto Expiry
# ------------------------------
echo -e "${YELLOW}[9/10] Setting up cron...${NC}"
cat <<EOF > /etc/cron.d/zivpn-expiry
* * * * * root /opt/zivpn-panel/venv/bin/python3 /opt/zivpn-panel/expire_check.py >> /var/log/zivpn-expiry.log 2>&1
EOF

# ------------------------------
# 10. Initialize DB and Start
# ------------------------------
echo -e "${YELLOW}[10/10] Initializing database...${NC}"
cd /opt/zivpn-panel
source venv/bin/activate
python3 -c "from app import app, db; app.app_context().push(); db.create_all()"
deactivate

systemctl daemon-reload
systemctl enable zivpn-panel.service zivpn-bot.service
systemctl start zivpn-panel.service zivpn-bot.service

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN} Installation Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "🌐 Web Panel:    http://${PUBLIC_IP}:${PANEL_PORT}"
echo -e "🤖 Bot Token:    ${BOT_TOKEN}"
echo -e "👑 Admin Chat ID: ${ADMIN_CHAT_ID}"
echo -e "📁 Uploads:       /opt/zivpn-panel/uploads"
echo -e "🔐 VPN Username:  Exact as entered (no prefix)"
echo -e "${GREEN}========================================${NC}"
