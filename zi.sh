```bash
#!/bin/bash
# Zivpn UDP + Web Panel + Telegram Bot Installer
# Coded to meet custom requirements

clear
echo "==================================================="
echo "  Zivpn UDP Auto Installer with Web Panel & Bot    "
echo "==================================================="

# 1. Ask Requirements
read -p "Enter Telegram Bot Token: " BOT_TOKEN
read -p "Enter Admin Chat ID: " CHAT_ID
read -p "Enter VPS Hostname (eg. linvpn.shop): " HOSTNAME
read -p "Enter Web Panel Port (eg. 8080): " PANEL_PORT

# 2. System Update & Install Dependencies
echo -e "\n[+] Updating system and installing dependencies..."
apt-get update && apt-get upgrade -y
apt-get install -y curl wget jq openssl iptables ufw sqlite3

# 3. Install Node.js
curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
apt-get install -y nodejs

# 4. Install Zivpn UDP
echo -e "\n[+] Installing Zivpn UDP Service..."
systemctl stop zivpn.service 1> /dev/null 2> /dev/null
wget https://github.com/zahidbd2/udp-zivpn/releases/download/udp-zivpn_1.4.9/udp-zivpn-linux-amd64 -O /usr/local/bin/zivpn 1> /dev/null 2> /dev/null
chmod +x /usr/local/bin/zivpn
mkdir -p /etc/zivpn
wget https://raw.githubusercontent.com/zahidbd2/udp-zivpn/main/config.json -O /etc/zivpn/config.json 1> /dev/null 2> /dev/null

echo "Generating cert files..."
openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 -subj "/C=US/ST=CA/L=LA/O=VPN/OU=IT/CN=zivpn" -keyout "/etc/zivpn/zivpn.key" -out "/etc/zivpn/zivpn.crt" 2>/dev/null
sysctl -w net.core.rmem_max=16777216 1> /dev/null 2> /dev/null
sysctl -w net.core.wmem_max=16777216 1> /dev/null 2> /dev/null

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

systemctl enable zivpn.service
iptables -t nat -A PREROUTING -i $(ip -4 route ls|grep default|grep -Po '(?<=dev )(\S+)'|head -1) -p udp --dport 6000:19999 -j DNAT --to-destination :5667
ufw allow 6000:19999/udp
ufw allow 5667/udp
ufw allow $PANEL_PORT/tcp

# 5. Setup Web Panel & Backend
echo -e "\n[+] Setting up Web Panel & Bot Backend..."
mkdir -p /opt/vpnpanel/public
cd /opt/vpnpanel

# Create .env file
cat <<EOF > /opt/vpnpanel/.env
BOT_TOKEN=$BOT_TOKEN
CHAT_ID=$CHAT_ID
HOSTNAME=$HOSTNAME
PORT=$PANEL_PORT
VPS_IP=$(curl -s ifconfig.me)
EOF

# Initialize Node Project
cat <<EOF > /opt/vpnpanel/package.json
{
  "name": "vpnpanel",
  "version": "1.0.0",
  "main": "server.js",
  "dependencies": {
    "express": "^4.18.2",
    "telegraf": "^4.12.2",
    "sqlite3": "^5.1.6",
    "cors": "^2.8.5",
    "dotenv": "^16.3.1",
    "multer": "^1.4.5-lts.1",
    "moment": "^2.29.4"
  }
}
EOF

npm install

# Create Server Code
cat <<'EOF' > /opt/vpnpanel/server.js
require('dotenv').config();
const express = require('express');
const { Telegraf, Markup } = require('telegraf');
const sqlite3 = require('sqlite3').verbose();
const cors = require('cors');
const multer = require('multer');
const fs = require('fs');
const { exec } = require('child_process');
const moment = require('moment');
const path = require('path');

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static('public'));

const upload = multer({ dest: 'uploads/' });
const bot = new Telegraf(process.env.BOT_TOKEN);
const adminChatId = process.env.CHAT_ID;

// Database Setup
const db = new sqlite3.Database('./vpn.db');
db.serialize(() => {
    db.run("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, credit INTEGER DEFAULT 0)");
    db.run("CREATE TABLE IF NOT EXISTS vpn_accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, vpn_user TEXT, vpn_pass TEXT, expire_date TEXT)");
    db.run("CREATE TABLE IF NOT EXISTS topups (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, status TEXT DEFAULT 'pending')");
});

// Helper: Sync Zivpn Config
const syncZivpn = () => {
    db.all("SELECT vpn_pass FROM vpn_accounts WHERE expire_date > datetime('now')", (err, rows) => {
        if (err) return console.error(err);
        let passwords = rows.map(r => r.vpn_pass);
        if(passwords.length === 0) passwords = ["default_zi"]; // fallback
        
        let configPath = '/etc/zivpn/config.json';
        if(fs.existsSync(configPath)) {
            let config = JSON.parse(fs.readFileSync(configPath));
            config.config = passwords;
            fs.writeFileSync(configPath, JSON.stringify(config, null, 2));
            exec('systemctl restart zivpn.service');
        }
    });
};

// --- Web API Routes ---

// Register / Login
app.post('/api/auth', (req, res) => {
    const { username, password } = req.body;
    db.get("SELECT * FROM users WHERE username = ?", [username], (err, user) => {
        if (user) {
            if (user.password === password) res.json({ success: true, user });
            else res.json({ success: false, msg: "Password မှားနေပါသည်။" });
        } else {
            db.run("INSERT INTO users (username, password) VALUES (?, ?)", [username, password], function(err) {
                res.json({ success: true, user: { id: this.lastID, username, credit: 0 } });
            });
        }
    });
});

// Request Topup
app.post('/api/topup', upload.single('slip'), (req, res) => {
    const { userId, amount, username } = req.body;
    const slipPath = req.file.path;

    db.run("INSERT INTO topups (user_id, amount) VALUES (?, ?)", [userId, amount], function(err) {
        const topupId = this.lastID;
        
        // Send to Telegram
        bot.telegram.sendPhoto(adminChatId, { source: slipPath }, {
            caption: `📥 <b>Topup Request</b>\n\n👤 User: ${username}\n💰 Amount: ${amount} THB\n🆔 Request ID: ${topupId}`,
            parse_mode: 'HTML',
            reply_markup: {
                inline_keyboard: [
                    [{ text: "✅ Approve", callback_data: `approve_${topupId}_${userId}_${amount}` },
                     { text: "❌ Cancel", callback_data: `cancel_${topupId}` }]
                ]
            }
        });
        res.json({ success: true, msg: "Admin ထံသို့ ပို့ပေးလိုက်ပါပြီ။" });
    });
});

// Create VPN Account
app.post('/api/create_vpn', (req, res) => {
    const { userId, vpnUser, vpnPass, days } = req.body;
    const cost = days === 30 ? 50 : 80;

    db.get("SELECT credit, username FROM users WHERE id = ?", [userId], (err, user) => {
        if (user.credit < cost) return res.json({ success: false, msg: "Credit မလောက်ပါ။ ကျေးဇူးပြု၍ ငွေသွင်းပါ။" });

        const expireDate = moment().add(days, 'days').format('YYYY-MM-DD HH:mm:ss');
        
        db.run("UPDATE users SET credit = credit - ? WHERE id = ?", [cost, userId], () => {
            db.run("INSERT INTO vpn_accounts (user_id, vpn_user, vpn_pass, expire_date) VALUES (?, ?, ?, ?)", 
            [userId, vpnUser, vpnPass, expireDate], function() {
                syncZivpn();
                
                // Notify Admin
                db.get("SELECT count(*) as total FROM vpn_accounts WHERE user_id = ?", [userId], (err, row) => {
                    bot.telegram.sendMessage(adminChatId, `🆕 <b>New VPN Created!</b>\n\n👤 User: ${user.username}\n📦 Accounts Owned: ${row.total}\n\n🔐 VPN Username: ${vpnUser}\n🔑 VPN Pass: ${vpnPass}\n⏳ Days: ${days}\n📉 THB Deducted: ${cost}`, {parse_mode: 'HTML'});
                });

                res.json({ 
                    success: true, 
                    ip: process.env.VPS_IP,
                    hostname: process.env.HOSTNAME,
                    vpnUser, vpnPass, expireDate, days 
                });
            });
        });
    });
});

// Get User Data
app.get('/api/user/:id', (req, res) => {
    db.get("SELECT credit FROM users WHERE id = ?", [req.params.id], (err, user) => res.json(user));
});


// --- Telegram Bot Logic ---
bot.action(/approve_(\d+)_(\d+)_(\d+)/, (ctx) => {
    const [_, topupId, userId, amount] = ctx.match;
    db.run("UPDATE topups SET status = 'approved' WHERE id = ? AND status = 'pending'", [topupId], function() {
        if(this.changes > 0) {
            db.run("UPDATE users SET credit = credit + ? WHERE id = ?", [amount, userId]);
            ctx.editMessageCaption(`✅ <b>Approved!</b>\nAdded ${amount} THB to user.`, {parse_mode: 'HTML'});
        } else {
            ctx.answerCbQuery("Already processed.");
        }
    });
});

bot.action(/cancel_(\d+)/, (ctx) => {
    const topupId = ctx.match[1];
    db.run("UPDATE topups SET status = 'canceled' WHERE id = ?", [topupId]);
    ctx.editMessageCaption(`❌ <b>Canceled!</b> Request denied.`, {parse_mode: 'HTML'});
});

bot.command('menu', (ctx) => {
    ctx.reply('👨‍💻 Admin Panel', Markup.inlineKeyboard([
        [Markup.button.callback('👥 Total Users List', 'userlist')]
    ]));
});

bot.action('userlist', (ctx) => {
    db.all("SELECT users.username, users.credit, count(vpn_accounts.id) as vpn_count FROM users LEFT JOIN vpn_accounts ON users.id = vpn_accounts.user_id GROUP BY users.id", (err, rows) => {
        let msg = "👥 <b>User List</b>\n\n";
        rows.forEach(r => msg += `👤 ${r.username} | 💰 ${r.credit} THB | 📱 VPNs: ${r.vpn_count}\n`);
        ctx.reply(msg, {parse_mode: 'HTML'});
    });
});

bot.launch();

// Auto Expiration Cron (Runs every hour)
setInterval(() => {
    db.run("DELETE FROM vpn_accounts WHERE expire_date <= datetime('now')", function() {
        if(this.changes > 0) syncZivpn();
    });
}, 3600000);

app.listen(process.env.PORT, () => console.log(`Panel running on port ${process.env.PORT}`));
EOF

# Create Frontend Code (HTML)
cat <<'EOF' > /opt/vpnpanel/public/index.html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zivpn Panel</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
</head>
<body class="bg-gray-900 text-white font-sans antialiased p-5">

    <!-- Login Section -->
    <div id="login-sec" class="max-w-md mx-auto bg-gray-800 p-8 rounded-xl shadow-lg mt-20">
        <h2 class="text-3xl font-bold text-center mb-6 text-blue-500">ZIVPN Login</h2>
        <input type="text" id="log-user" placeholder="Username (User ID)" class="w-full p-3 mb-4 bg-gray-700 rounded outline-none focus:ring-2 focus:ring-blue-500">
        <input type="password" id="log-pass" placeholder="Password" class="w-full p-3 mb-6 bg-gray-700 rounded outline-none focus:ring-2 focus:ring-blue-500">
        <button onclick="login()" class="w-full bg-blue-600 hover:bg-blue-700 p-3 rounded font-bold transition">Login / Register</button>
    </div>

    <!-- Dashboard Section -->
    <div id="dash-sec" class="max-w-4xl mx-auto hidden mt-10">
        <div class="flex justify-between items-center mb-8 bg-gray-800 p-5 rounded-lg shadow">
            <h2 class="text-2xl font-bold">Welcome, <span id="dash-user" class="text-blue-400"></span></h2>
            <div class="text-xl font-bold">Credit: <span id="dash-credit" class="text-green-400">0</span> THB</div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <!-- Topup Box -->
            <div class="bg-gray-800 p-6 rounded-xl shadow-lg border border-gray-700">
                <h3 class="text-xl font-bold mb-4 text-green-500">💸 Topup Account</h3>
                <select id="topup-amount" class="w-full p-3 mb-4 bg-gray-700 rounded outline-none">
                    <option value="50">50 THB</option>
                    <option value="100">100 THB</option>
                    <option value="150">150 THB</option>
                </select>
                <label class="block mb-2 text-sm text-gray-400">Upload Slip Photo:</label>
                <input type="file" id="topup-slip" accept="image/*" class="w-full p-2 mb-4 bg-gray-700 rounded outline-none">
                <button onclick="requestTopup()" class="w-full bg-green-600 hover:bg-green-700 p-3 rounded font-bold transition">Request Topup</button>
            </div>

            <!-- Create VPN Box -->
            <div class="bg-gray-800 p-6 rounded-xl shadow-lg border border-gray-700">
                <h3 class="text-xl font-bold mb-4 text-blue-500">🚀 Create VPN Account</h3>
                <input type="text" id="vpn-user" placeholder="VPN Username" class="w-full p-3 mb-4 bg-gray-700 rounded outline-none">
                <input type="text" id="vpn-pass" placeholder="VPN Password" class="w-full p-3 mb-4 bg-gray-700 rounded outline-none">
                <select id="vpn-days" class="w-full p-3 mb-6 bg-gray-700 rounded outline-none">
                    <option value="30">30 Days (50 THB)</option>
                    <option value="60">60 Days (80 THB)</option>
                </select>
                <button onclick="createVpn()" class="w-full bg-blue-600 hover:bg-blue-700 p-3 rounded font-bold transition">Create Account</button>
            </div>
        </div>
    </div>

    <script>
        let currentUser = null;

        async function login() {
            const u = document.getElementById('log-user').value;
            const p = document.getElementById('log-pass').value;
            if(!u || !p) return Swal.fire('Error', 'Username/Password ဖြည့်ပါ', 'error');

            const res = await fetch('/api/auth', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username: u, password: p})
            });
            const data = await res.json();
            
            if(data.success) {
                currentUser = data.user;
                document.getElementById('login-sec').classList.add('hidden');
                document.getElementById('dash-sec').classList.remove('hidden');
                updateDash();
                setInterval(refreshCredit, 5000); // Auto update credit
            } else {
                Swal.fire('Error', data.msg, 'error');
            }
        }

        async function refreshCredit() {
            if(!currentUser) return;
            const res = await fetch('/api/user/' + currentUser.id);
            const data = await res.json();
            currentUser.credit = data.credit;
            updateDash();
        }

        function updateDash() {
            document.getElementById('dash-user').innerText = currentUser.username;
            document.getElementById('dash-credit').innerText = currentUser.credit;
        }

        async function requestTopup() {
            const amount = document.getElementById('topup-amount').value;
            const fileInput = document.getElementById('topup-slip');
            
            if(fileInput.files.length === 0) return Swal.fire('Error', 'Slip ပုံတင်ပေးပါ', 'warning');

            const formData = new FormData();
            formData.append('slip', fileInput.files[0]);
            formData.append('userId', currentUser.id);
            formData.append('username', currentUser.username);
            formData.append('amount', amount);

            Swal.fire({title: 'Sending...', allowOutsideClick: false, didOpen: () => Swal.showLoading()});

            const res = await fetch('/api/topup', { method: 'POST', body: formData });
            const data = await res.json();
            
            if(data.success) {
                Swal.fire('Success', data.msg, 'success');
                fileInput.value = '';
            }
        }

        async function createVpn() {
            const vUser = document.getElementById('vpn-user').value;
            const vPass = document.getElementById('vpn-pass').value;
            const days = parseInt(document.getElementById('vpn-days').value);

            if(!vUser || !vPass) return Swal.fire('Error', 'VPN User/Pass အပြည့်အစုံဖြည့်ပါ', 'warning');

            const cost = days === 30 ? 50 : 80;
            if(currentUser.credit < cost) {
                return Swal.fire('Oops!', 'Credit မလုံလောက်ပါ။ Topup အရင်လုပ်ပါ။', 'error');
            }

            Swal.fire({title: 'Creating...', allowOutsideClick: false, didOpen: () => Swal.showLoading()});

            const res = await fetch('/api/create_vpn', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({userId: currentUser.id, vpnUser: vUser, vpnPass: vPass, days})
            });
            const data = await res.json();

            if(data.success) {
                refreshCredit();
                Swal.fire({
                    title: '✅ Create Account Successfully',
                    html: `
                        <div class="text-left mt-4 bg-gray-100 p-4 rounded text-gray-800 text-sm font-mono">
                            <p><b>Server IP:</b> ${data.ip}</p>
                            <p><b>Hostname:</b> ${data.hostname}</p>
                            <p><b>Username:</b> ${data.vpnUser}</p>
                            <p><b>Password:</b> ${data.vpnPass}</p>
                            <p><b>Days Left:</b> ${data.days} Days</p>
                            <p><b>Expired Date:</b> ${data.expireDate}</p>
                        </div>
                    `,
                    icon: 'success'
                });
            } else {
                Swal.fire('Error', data.msg, 'error');
            }
        }
    </script>
</body>
</html>
EOF

# 6. Setup Systemd Service for Panel
echo -e "\n[+] Setting up Web Panel Service..."
cat <<EOF > /etc/systemd/system/vpnpanel.service
[Unit]
Description=VPN Web Panel and Bot Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/vpnpanel
ExecStart=/usr/bin/node /opt/vpnpanel/server.js
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable vpnpanel.service
systemctl start vpnpanel.service
systemctl start zivpn.service

# 7. Finish
clear
echo "=========================================================="
echo " ✅ Zivpn & Web Panel Successfully Installed!"
echo "=========================================================="
echo " 🌐 Web Panel URL : http://$(curl -s ifconfig.me):$PANEL_PORT"
echo " 🤖 Telegram Bot  : Send /menu to your bot to view userlist."
echo "=========================================================="
echo " Please configure your custom DNS (Hostname) to point to your VPS IP."

```
