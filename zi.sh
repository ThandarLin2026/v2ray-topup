#!/bin/bash set -euo pipefail

APP_DIR="/opt/zivpn-panel" PUBLIC_DIR="$APP_DIR/public" UPLOAD_DIR="$APP_DIR/uploads" SERVICE_FILE="/etc/systemd/system/zivpn-panel.service" ENV_FILE="$APP_DIR/.env"

install_node18_if_needed() { if command -v node >/dev/null 2>&1; then major="$(node -v | sed 's/^v//' | cut -d. -f1)" else major=0 fi if [ "$major" -lt 18 ]; then echo "Installing Node.js 18..." curl -fsSL https://deb.nodesource.com/setup_18.x | bash - apt-get install -y nodejs fi }

echo "=== Updating packages ===" apt-get update -y apt-get install -y curl openssl ufw ca-certificates install_node18_if_needed apt-get install -y nodejs npm

mkdir -p "$APP_DIR" "$PUBLIC_DIR" "$UPLOAD_DIR"

read -p "Telegram Bot Token: " BOT_TOKEN read -p "Admin Chat ID: " ADMIN_CHAT_ID read -p "Hostname (example: linvpn.shop): " HOSTNAME read -p "Panel Port (example: 3000): " PANEL_PORT read -p "Server IP (public IP shown in panel): " SERVER_IP read -p "Zivpn config path [/etc/zivpn/config.json]: " ZIVPN_CONFIG_PATH ZIVPN_CONFIG_PATH="${ZIVPN_CONFIG_PATH:-/etc/zivpn/config.json}"

cat > "$ENV_FILE" <<EOF BOT_TOKEN=$BOT_TOKEN ADMIN_CHAT_ID=$ADMIN_CHAT_ID HOSTNAME=$HOSTNAME PANEL_PORT=$PANEL_PORT SERVER_IP=$SERVER_IP ZIVPN_CONFIG_PATH=$ZIVPN_CONFIG_PATH ZIVPN_SERVICE=zivpn.service APP_DIR=$APP_DIR EOF

cat > "$APP_DIR/package.json" <<'EOF' { "name": "zivpn-panel", "version": "2.0.0", "main": "app.js", "license": "MIT", "dependencies": { "dotenv": "^16.4.5", "express": "^4.21.2", "multer": "^1.4.5-lts.2", "telegraf": "^4.16.3" } } EOF

cat > "$APP_DIR/app.js" <<'EOF' require('dotenv').config();

const fs = require('fs'); const path = require('path'); const crypto = require('crypto'); const express = require('express'); const multer = require('multer'); const { Telegraf, Markup } = require('telegraf'); const { execSync } = require('child_process');

const APP_DIR = process.env.APP_DIR || '/opt/zivpn-panel'; const DATA_FILE = path.join(APP_DIR, 'data.json'); const UPLOAD_DIR = path.join(APP_DIR, 'uploads'); const PUBLIC_DIR = path.join(APP_DIR, 'public'); const ZIVPN_CONFIG_PATH = process.env.ZIVPN_CONFIG_PATH || '/etc/zivpn/config.json'; const ZIVPN_SERVICE = process.env.ZIVPN_SERVICE || 'zivpn.service'; const HOSTNAME = process.env.HOSTNAME || 'localhost'; const SERVER_IP = process.env.SERVER_IP || '0.0.0.0'; const PANEL_PORT = Number(process.env.PANEL_PORT || 3000); const BOT_TOKEN = process.env.BOT_TOKEN || ''; const ADMIN_CHAT_ID = String(process.env.ADMIN_CHAT_ID || '');

const PLANS = [ { days: 30, price: 50 }, { days: 60, price: 80 } ];

function uid(prefix) { return ${prefix}_${crypto.randomBytes(6).toString('hex')}; }

function nowIso() { return new Date().toISOString(); }

function daysLeft(expiresAt) { const ms = new Date(expiresAt).getTime() - Date.now(); return Math.max(0, Math.ceil(ms / 86400000)); }

function formatDate(d) { try { return new Date(d).toLocaleString('en-GB', { hour12: false }); } catch (_) { return String(d || ''); } }

function ensureData() { if (!fs.existsSync(DATA_FILE)) { fs.writeFileSync(DATA_FILE, JSON.stringify({ users: [], accounts: [], topups: [] }, null, 2)); } }

function loadData() { ensureData(); return JSON.parse(fs.readFileSync(DATA_FILE, 'utf8')); }

function saveData(data) { fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 2)); }

function getOrCreateUser(data, userId) { let user = data.users.find(u => String(u.userId) === String(userId)); if (!user) { user = { userId: String(userId), credit: 0, createdAt: nowIso(), updatedAt: nowIso() }; data.users.push(user); } return user; }

function accountState(acc) { const expired = new Date(acc.expiresAt).getTime() <= Date.now(); if (acc.status === 'disabled') return 'offline'; if (expired) return 'offline'; return 'active'; }

function accountBadge(state) { if (state === 'active') return '<span class="badge badge-green">ACTIVE</span>'; return '<span class="badge badge-gray">OFFLINE</span>'; }

function escapeHtml(s) { return String(s ?? '') .replace(/&/g, '&') .replace(/</g, '<') .replace(/>/g, '>') .replace(/"/g, '"') .replace(/'/g, '''); }

function syncZivpnConfig() { try { if (!fs.existsSync(ZIVPN_CONFIG_PATH)) return;

const data = loadData();
const passwords = data.accounts
  .filter(a => a.status === 'active' && new Date(a.expiresAt).getTime() > Date.now())
  .map(a => a.password)
  .filter(Boolean);

let json;
try {
  json = JSON.parse(fs.readFileSync(ZIVPN_CONFIG_PATH, 'utf8'));
} catch (e) {
  console.error('Cannot parse Zivpn config.json:', e.message);
  return;
}

if (Array.isArray(json)) {
  json = { config: passwords };
} else {
  json.config = passwords;
}

fs.writeFileSync(ZIVPN_CONFIG_PATH, JSON.stringify(json, null, 2));
try {
  execSync(`systemctl restart ${ZIVPN_SERVICE}`, { stdio: 'ignore' });
} catch (e) {
  console.error('Failed to restart Zivpn service:', e.message);
}

} catch (e) { console.error('syncZivpnConfig error:', e.message); } }

function expireAccounts() { const data = loadData(); let changed = false; for (const acc of data.accounts) { if (acc.status === 'active' && new Date(acc.expiresAt).getTime() <= Date.now()) { acc.status = 'expired'; changed = true; } } if (changed) { saveData(data); syncZivpnConfig(); } }

function createAccount({ userId, username, password, days }) { const data = loadData(); const user = getOrCreateUser(data, userId); const plan = PLANS.find(p => p.days === Number(days)); if (!plan) return { ok: false, error: 'Invalid plan' };

const cleanUsername = String(username || '').trim(); const cleanPassword = String(password || '').trim(); if (!cleanUsername || !cleanPassword) return { ok: false, error: 'Username and password required' };

if (data.accounts.some(a => a.username === cleanUsername && a.status === 'active' && new Date(a.expiresAt).getTime() > Date.now())) { return { ok: false, error: 'Username already exists' }; }

if (user.credit < plan.price) { return { ok: false, error: Not enough credit. Need ${plan.price} THB. }; }

user.credit -= plan.price; user.updatedAt = nowIso();

const acc = { id: uid('acc'), userId: String(userId), username: cleanUsername, password: cleanPassword, days: plan.days, price: plan.price, status: 'active', createdAt: nowIso(), expiresAt: new Date(Date.now() + plan.days * 86400000).toISOString(), lastSeenAt: null };

data.accounts.push(acc); saveData(data); syncZivpnConfig();

return { ok: true, account: acc, balance: user.credit }; }

function updateUserBalance(userId, amount) { const data = loadData(); const user = getOrCreateUser(data, userId); user.credit += Number(amount); user.updatedAt = nowIso(); saveData(data); return user; }

function markTopup(topupId, status) { const data = loadData(); const topup = data.topups.find(t => t.id === topupId); if (!topup || topup.status !== 'pending') return { ok: false, error: 'Topup not found or already processed' }; topup.status = status; topup.updatedAt = nowIso(); saveData(data); return { ok: true, topup }; }

function approveTopup(topupId) { const data = loadData(); const topup = data.topups.find(t => t.id === topupId); if (!topup || topup.status !== 'pending') return { ok: false, error: 'Topup not found or already processed' };

const user = getOrCreateUser(data, topup.userId); user.credit += Number(topup.amount); user.updatedAt = nowIso(); topup.status = 'approved'; topup.approvedAt = nowIso(); saveData(data); return { ok: true, topup, user }; }

function cancelTopup(topupId) { const data = loadData(); const topup = data.topups.find(t => t.id === topupId); if (!topup || topup.status !== 'pending') return { ok: false, error: 'Topup not found or already processed' }; topup.status = 'cancelled'; topup.cancelledAt = nowIso(); saveData(data); return { ok: true, topup }; }

function getUserAccounts(userId) { const data = loadData(); expireAccounts(); return data.accounts .filter(a => String(a.userId) === String(userId)) .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt)); }

function getUserTopups(userId) { const data = loadData(); return data.topups .filter(t => String(t.userId) === String(userId)) .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt)); }

function getTopUsers() { const data = loadData(); const totals = new Map(); for (const t of data.topups.filter(t => t.status === 'approved')) { totals.set(String(t.userId), (totals.get(String(t.userId)) || 0) + Number(t.amount)); } const out = [...totals.entries()].map(([userId, total]) => { const user = data.users.find(u => String(u.userId) === String(userId)) || { userId, credit: 0 }; return { userId, credit: user.credit || 0, total }; }); out.sort((a, b) => b.total - a.total); return out; }

function accountCard(acc) { const state = accountState(acc); const stateText = state === 'active' ? 'active' : 'offline'; return <div class="card"> <div class="card-top"> <div> <div class="small">User ID</div> <div class="mono">${escapeHtml(acc.userId)}</div> </div> ${accountBadge(state)} </div> <div class="grid2"> <div><div class="small">Username</div><div class="mono">${escapeHtml(acc.username)}</div></div> <div><div class="small">Password</div><div class="mono">${escapeHtml(acc.password)}</div></div> <div><div class="small">Plan</div><div>${escapeHtml(acc.days)} days</div></div> <div><div class="small">Days Left</div><div>${daysLeft(acc.expiresAt)}</div></div> <div><div class="small">Expired Date</div><div class="mono">${escapeHtml(formatDate(acc.expiresAt))}</div></div> <div><div class="small">Status</div><div class="state-${stateText}">${stateText}</div></div> </div> </div>; }

function topupCard(t) { const cls = t.status === 'approved' ? 'badge-green' : t.status === 'cancelled' ? 'badge-red' : 'badge-yellow'; return <div class="card"> <div class="card-top"> <div> <div class="small">Topup ID</div> <div class="mono">${escapeHtml(t.id)}</div> </div> <span class="badge ${cls}">${escapeHtml(t.status)}</span> </div> <div class="grid2"> <div><div class="small">Amount</div><div>${escapeHtml(t.amount)} THB</div></div> <div><div class="small">Created</div><div class="mono">${escapeHtml(formatDate(t.createdAt))}</div></div> </div> </div>; }

function adminKeyboard() { return Markup.keyboard([ ['Pending Topups', 'Users'], ['Accounts', 'Top Users'] ]).resize(); }

const upload = multer({ storage: multer.diskStorage({ destination: (req, file, cb) => cb(null, UPLOAD_DIR), filename: (req, file, cb) => { const ext = path.extname(file.originalname || '').toLowerCase() || '.jpg'; cb(null, ${Date.now()}_${crypto.randomBytes(4).toString('hex')}${ext}); } }), limits: { fileSize: 10 * 1024 * 1024 } });

const app = express(); app.use(express.json()); app.use(express.urlencoded({ extended: true })); app.use('/uploads', express.static(UPLOAD_DIR)); app.use(express.static(PUBLIC_DIR));

app.get('/api/state', (req, res) => { const userId = String(req.query.userId || '').trim(); if (!userId) return res.status(400).json({ ok: false, error: 'userId required' });

const data = loadData(); const user = getOrCreateUser(data, userId); saveData(data); expireAccounts();

const accounts = getUserAccounts(userId); const topups = getUserTopups(userId);

res.json({ ok: true, user: { userId: String(userId), credit: user.credit || 0 }, serverIp: SERVER_IP, hostname: HOSTNAME, panelPort: PANEL_PORT, plans: PLANS, accounts, topups }); });

app.post('/api/create-account', (req, res) => { const { userId, username, password, days } = req.body || {}; const result = createAccount({ userId, username, password, days }); if (!result.ok) return res.status(400).json(result);

const acc = result.account; return res.json({ ok: true, message: 'Create Account Successfully', serverIp: SERVER_IP, hostname: HOSTNAME, username: acc.username, password: acc.password, expiresAt: acc.expiresAt, daysLeft: daysLeft(acc.expiresAt), credit: result.balance, account: acc }); });

app.post('/api/topup', upload.single('slip'), (req, res) => { const userId = String(req.body.userId || '').trim(); const amount = Number(req.body.amount || 0); if (!userId) return res.status(400).json({ ok: false, error: 'userId required' }); if (![50, 100, 150].includes(amount)) return res.status(400).json({ ok: false, error: 'Invalid amount' }); if (!req.file) return res.status(400).json({ ok: false, error: 'Slip image required' });

const data = loadData(); const user = getOrCreateUser(data, userId);

const topup = { id: uid('topup'), userId: String(userId), amount, slipPath: /uploads/${path.basename(req.file.path)}, slipFile: req.file.path, status: 'pending', createdAt: nowIso(), updatedAt: nowIso(), approvedAt: null, cancelledAt: null, username: user.username || '' };

data.topups.push(topup); saveData(data);

if (bot) { const caption = [ '📥 New Topup Request', User ID: ${topup.userId}, Amount: ${topup.amount} THB, Status: pending, Slip: ${SERVER_IP}:${PANEL_PORT}${topup.slipPath} ].join('\n');

const keyboard = Markup.inlineKeyboard([
  [
    Markup.button.callback('✅ Approve', `topup:approve:${topup.id}`),
    Markup.button.callback('❌ Cancel', `topup:cancel:${topup.id}`)
  ]
]);

try {
  bot.telegram.sendPhoto(ADMIN_CHAT_ID, { source: fs.createReadStream(req.file.path) }, { caption, ...keyboard });
} catch (e) {
  bot.telegram.sendMessage(ADMIN_CHAT_ID, caption + '\n\n(photo send failed)');
}

}

res.json({ ok: true, message: 'Topup request submitted', topup }); });

app.get('/api/admin/overview', (req, res) => { const data = loadData(); const pending = data.topups.filter(t => t.status === 'pending').length; const active = data.accounts.filter(a => accountState(a) === 'active').length; const offline = data.accounts.filter(a => accountState(a) === 'offline').length; const users = data.users.length; res.json({ ok: true, pending, active, offline, users }); });

app.get('/', (req, res) => { res.sendFile(path.join(PUBLIC_DIR, 'index.html')); });

const bot = BOT_TOKEN ? new Telegraf(BOT_TOKEN) : null;

if (bot) { bot.start(async (ctx) => { if (String(ctx.from.id) !== ADMIN_CHAT_ID) { return ctx.reply('Admin only bot.'); } await ctx.reply('Zivpn admin bot ready.', adminKeyboard()); });

bot.hears('Pending Topups', async (ctx) => { if (String(ctx.from.id) !== ADMIN_CHAT_ID) return; const data = loadData(); const pending = data.topups.filter(t => t.status === 'pending').slice(0, 20); if (!pending.length) return ctx.reply('No pending topups.'); for (const t of pending) { const txt = [ '📥 Pending Topup', Topup ID: ${t.id}, User ID: ${t.userId}, Amount: ${t.amount} THB ].join('\n'); const kb = Markup.inlineKeyboard([ [ Markup.button.callback('✅ Approve', topup:approve:${t.id}), Markup.button.callback('❌ Cancel', topup:cancel:${t.id}) ] ]); if (t.slipFile && fs.existsSync(t.slipFile)) { await ctx.replyWithPhoto({ source: fs.createReadStream(t.slipFile) }, { caption: txt, ...kb }); } else { await ctx.reply(txt, kb); } } });

bot.hears('Users', async (ctx) => { if (String(ctx.from.id) !== ADMIN_CHAT_ID) return; const data = loadData(); if (!data.users.length) return ctx.reply('No users yet.'); const lines = data.users .slice() .sort((a, b) => Number(b.credit) - Number(a.credit)) .slice(0, 50) .map(u => User ID: ${u.userId} | Balance: ${u.credit} THB) .join('\n'); await ctx.reply(lines || 'No users.'); });

bot.hears('Accounts', async (ctx) => { if (String(ctx.from.id) !== ADMIN_CHAT_ID) return; const data = loadData(); const list = data.accounts.slice().sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt)).slice(0, 30); if (!list.length) return ctx.reply('No accounts yet.'); for (const acc of list) { const state = accountState(acc); const txt = [ '🧾 Account', User ID: ${acc.userId}, Username: ${acc.username}, Password: ${acc.password}, Status: ${state}, Days Left: ${daysLeft(acc.expiresAt)} ].join('\n'); await ctx.reply(txt); } });

bot.hears('Top Users', async (ctx) => { if (String(ctx.from.id) !== ADMIN_CHAT_ID) return; const list = getTopUsers().slice(0, 20); if (!list.length) return ctx.reply('No approved topups yet.'); const text = list.map((u, i) => ${i + 1}. ${u.userId} — ${u.total} THB | Balance: ${u.credit} THB).join('\n'); await ctx.reply(text); });

bot.action(/topup:approve:(.+)/, async (ctx) => { if (String(ctx.from.id) !== ADMIN_CHAT_ID) return ctx.answerCbQuery('Admin only'); const topupId = ctx.match[1]; const result = approveTopup(topupId); if (!result.ok) return ctx.answerCbQuery(result.error); await ctx.answerCbQuery('Approved');

try {
  await ctx.editMessageCaption(`✅ Approved\nUser ID: ${result.topup.userId}\nAmount: ${result.topup.amount} THB`);
} catch (_) {}

try {
  await bot.telegram.sendMessage(
    result.topup.userId,
    `Topup approved.\nAdded: ${result.topup.amount} THB\nCurrent balance: ${result.user.credit} THB`
  );
} catch (_) {}

});

bot.action(/topup:cancel:(.+)/, async (ctx) => { if (String(ctx.from.id) !== ADMIN_CHAT_ID) return ctx.answerCbQuery('Admin only'); const topupId = ctx.match[1]; const result = cancelTopup(topupId); if (!result.ok) return ctx.answerCbQuery(result.error); await ctx.answerCbQuery('Cancelled');

try {
  await ctx.editMessageCaption(`❌ Cancelled\nUser ID: ${result.topup.userId}\nAmount: ${result.topup.amount} THB`);
} catch (_) {}

try {
  await bot.telegram.sendMessage(result.topup.userId, `Your topup request was cancelled.`);
} catch (_) {}

});

bot.launch().then(() => console.log('Telegram admin bot started')); }

setInterval(expireAccounts, 5 * 60 * 1000); expireAccounts();

app.listen(PANEL_PORT, '0.0.0.0', () => { console.log(Panel running on 0.0.0.0:${PANEL_PORT}); console.log(Open: http://${SERVER_IP}:${PANEL_PORT}); }); EOF

cat > "$PUBLIC_DIR/index.html" <<'EOF'

<!DOCTYPE html><html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Zivpn Panel</title>
  <style>
    :root{--bg:#0b1220;--card:#111827;--line:#243041;--text:#e2e8f0;--muted:#94a3b8;--blue:#2563eb;--green:#16a34a;--gray:#64748b;--red:#dc2626;--yellow:#ca8a04}
    *{box-sizing:border-box}
    body{margin:0;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:linear-gradient(180deg,#0f172a,#020617);color:var(--text)}
    .wrap{max-width:1080px;margin:0 auto;padding:18px}
    .hero,.panel,.card{background:rgba(17,24,39,.95);border:1px solid var(--line);border-radius:22px;box-shadow:0 18px 44px rgba(0,0,0,.28)}
    .hero{padding:18px;margin-bottom:16px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
    .panel{padding:16px}
    .card{padding:14px;margin-top:12px}
    h1,h2,h3,p{margin:0 0 10px}
    .muted{color:var(--muted)}
    .row{display:flex;gap:10px;flex-wrap:wrap}
    .row>*{flex:1}
    input,select,button{width:100%;padding:13px 14px;border-radius:14px;border:1px solid #334155;background:#0b1220;color:var(--text);outline:none}
    button{border:none;background:var(--blue);font-weight:700;cursor:pointer}
    button.secondary{background:#334155}
    .pill{display:inline-flex;align-items:center;gap:8px;padding:7px 12px;border-radius:999px;background:#0f172a;border:1px solid #334155}
    .badge{display:inline-flex;align-items:center;padding:7px 12px;border-radius:999px;font-size:12px;font-weight:800;letter-spacing:.04em}
    .badge-green{background:rgba(22,163,74,.15);color:#86efac;border:1px solid rgba(22,163,74,.3)}
    .badge-gray{background:rgba(100,116,139,.16);color:#cbd5e1;border:1px solid rgba(100,116,139,.34)}
    .badge-red{background:rgba(220,38,38,.16);color:#fca5a5;border:1px solid rgba(220,38,38,.34)}
    .badge-yellow{background:rgba(202,138,4,.16);color:#fde68a;border:1px solid rgba(202,138,4,.34)}
    .small{color:var(--muted);font-size:12px;margin-bottom:4px}
    .mono{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;word-break:break-word}
    .grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
    .topline{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
    .state-active{color:#86efac;font-weight:800}
    .state-offline{color:#fca5a5;font-weight:800}
    .topup-list,.account-list{display:grid;gap:12px}
    .hr{height:1px;background:#243041;margin:14px 0}
    .statusbar{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}
    .statusbar .pill b{margin-left:6px}
    .modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.62);padding:18px;align-items:center;justify-content:center;z-index:20}
    .modal.show{display:flex}
    .modal-box{width:min(560px,100%);background:#0b1220;border:1px solid #334155;border-radius:24px;padding:18px}
    .success{color:#86efac}
    .error{color:#fca5a5}
    .hidden{display:none}
    .file{padding:11px 12px;background:#0b1220;border:1px dashed #334155;border-radius:14px;width:100%}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="topline">
        <div>
          <div class="pill">ZIVPN Panel</div>
          <h1 style="margin-top:10px">User Dashboard</h1>
          <p class="muted">Login with your User ID. Balance, accounts, and topup requests are shown here.</p>
        </div>
        <div class="statusbar" id="statusbar"></div>
      </div>
      <div style="height:14px"></div>
      <div class="row">
        <input id="userId" placeholder="Enter User ID" autocomplete="off" />
        <button onclick="loadState()">Load</button>
      </div>
      <div id="loadInfo" class="muted" style="margin-top:10px"></div>
    </div><div class="grid">
  <div class="panel">
    <h2>Balance & Create Account</h2>
    <p class="muted">Current balance and account details will appear below.</p>
    <div class="hr"></div>
    <div id="balanceBox" class="pill">Balance: <b>0 THB</b></div>
    <div style="height:12px"></div>
    <input id="accUsername" placeholder="Username" />
    <div style="height:10px"></div>
    <input id="accPassword" placeholder="Password" />
    <div style="height:10px"></div>
    <select id="accDays">
      <option value="30">30 Days - 50 THB</option>
      <option value="60">60 Days - 80 THB</option>
    </select>
    <div style="height:10px"></div>
    <button onclick="createAccount()">Create Account</button>
    <p id="createNote" class="muted" style="margin-top:10px"></p>
  </div>

  <div class="panel">
    <h2>Topup Request</h2>
    <p class="muted">Choose amount, transfer that amount, then upload the slip.</p>
    <div class="hr"></div>
    <select id="topupAmount">
      <option value="50">50 THB</option>
      <option value="100">100 THB</option>
      <option value="150">150 THB</option>
    </select>
    <div style="height:10px"></div>
    <input id="slip" type="file" accept="image/*" class="file" />
    <div style="height:10px"></div>
    <button onclick="submitTopup()">Submit Topup Slip</button>
    <p id="topupNote" class="muted" style="margin-top:10px"></p>
  </div>
</div>

<div style="height:14px"></div>

<div class="grid">
  <div class="panel">
    <h2>My Accounts</h2>
    <div class="account-list" id="accountList"></div>
  </div>

  <div class="panel">
    <h2>Topup History</h2>
    <div class="topup-list" id="topupList"></div>
  </div>
</div>

  </div>  <div id="modal" class="modal" onclick="if(event.target.id==='modal') closeModal()">
    <div class="modal-box">
      <h2 class="success">Create Account Successfully</h2>
      <div id="modalBody" style="margin-top:12px"></div>
      <div style="height:14px"></div>
      <button onclick="closeModal()">Close</button>
    </div>
  </div>  <script>
    const $ = (id) => document.getElementById(id);
    let state = null;

    function fmtDaysLeft(exp) {
      return Math.max(0, Math.ceil((new Date(exp).getTime() - Date.now()) / 86400000));
    }

    function esc(s) {
      return String(s ?? '')
        .replace(/&/g,'&amp;')
        .replace(/</g,'&lt;')
        .replace(/>/g,'&gt;')
        .replace(/"/g,'&quot;')
        .replace(/'/g,'&#39;');
    }

    function openModal(html) {
      $('modalBody').innerHTML = html;
      $('modal').classList.add('show');
    }

    function closeModal() {
      $('modal').classList.remove('show');
    }

    function accountState(acc) {
      const expired = new Date(acc.expiresAt).getTime() <= Date.now();
      if (acc.status === 'disabled') return 'offline';
      if (expired) return 'offline';
      return 'active';
    }

    function accountBadge(state) {
      return state === 'active'
        ? '<span class="badge badge-green">ACTIVE</span>'
        : '<span class="badge badge-gray">OFFLINE</span>';
    }

    function renderAccounts(accounts) {
      const wrap = $('accountList');
      if (!accounts || !accounts.length) {
        wrap.innerHTML = '<p class="muted">No accounts found.</p>';
        return;
      }
      wrap.innerHTML = accounts.map(acc => {
        const s = accountState(acc);
        return `
          <div class="card">
            <div class="topline">
              <div>
                <div class="small">User ID</div>
                <div class="mono">${esc(acc.userId)}</div>
              </div>
              ${accountBadge(s)}
            </div>
            <div class="hr"></div>
            <div class="grid2">
              <div><div class="small">Username</div><div class="mono">${esc(acc.username)}</div></div>
              <div><div class="small">Password</div><div class="mono">${esc(acc.password)}</div></div>
              <div><div class="small">Plan</div><div>${esc(acc.days)} days</div></div>
              <div><div class="small">Days Left</div><div>${fmtDaysLeft(acc.expiresAt)}</div></div>
              <div><div class="small">Expired Date</div><div class="mono">${esc(acc.expiresAt)}</div></div>
              <div><div class="small">Status</div><div class="state-${s}">${s}</div></div>
            </div>
          </div>
        `;
      }).join('');
    }

    function renderTopups(topups) {
      const wrap = $('topupList');
      if (!topups || !topups.length) {
        wrap.innerHTML = '<p class="muted">No topup history.</p>';
        return;
      }
      wrap.innerHTML = topups.map(t => {
        const cls = t.status === 'approved' ? 'badge-green' : t.status === 'cancelled' ? 'badge-red' : 'badge-yellow';
        return `
          <div class="card">
            <div class="topline">
              <div>
                <div class="small">Topup ID</div>
                <div class="mono">${esc(t.id)}</div>
              </div>
              <span class="badge ${cls}">${esc(t.status)}</span>
            </div>
            <div class="hr"></div>
            <div class="grid2">
              <div><div class="small">Amount</div><div>${esc(t.amount)} THB</div></div>
              <div><div class="small">Created</div><div class="mono">${esc(t.createdAt)}</div></div>
            </div>
          </div>
        `;
      }).join('');
    }

    async function loadState() {
      const userId = $('userId').value.trim();
      if (!userId) return alert('Enter User ID');
      const res = await fetch('/api/state?userId=' + encodeURIComponent(userId));
      const data = await res.json();
      if (!data.ok) return alert(data.error || 'Load failed');
      state = data;

      $('balanceBox').innerHTML = `Balance: <b>${data.user.credit} THB</b>`;
      $('loadInfo').innerHTML = `Loaded for User ID: <span class="pill mono">${esc(userId)}</span>`;
      $('statusbar').innerHTML = `
        <span class="pill">Server <b>${esc(data.serverIp)}</b></span>
        <span class="pill">Host <b>${esc(data.hostname)}</b></span>
        <span class="pill">Port <b>${esc(data.panelPort)}</b></span>
      `;
      renderAccounts(data.accounts);
      renderTopups(data.topups);
      localStorage.setItem('zivpn_user_id', userId);
    }

    async function createAccount() {
      if (!state) return alert('Load User ID first');
      const userId = $('userId').value.trim();
      const username = $('accUsername').value.trim();
      const password = $('accPassword').value.trim();
      const days = $('accDays').value;

      const res = await fetch('/api/create-account', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId, username, password, days })
      });
      const data = await res.json();
      if (!data.ok) {
        $('createNote').innerHTML = `<span class="error">${esc(data.error || 'Create failed')}</span>`;
        return;
      }

      $('createNote').innerHTML = `<span class="success">Account created successfully.</span>`;
      openModal(`
        <div class="card" style="margin-top:0">
          <div class="grid2">
            <div><div class="small">Server IP</div><div class="mono">${esc(data.serverIp)}</div></div>
            <div><div class="small">Hostname</div><div class="mono">${esc(data.hostname)}</div></div>
            <div><div class="small">Username</div><div class="mono">${esc(data.username)}</div></div>
            <div><div class="small">Password</div><div class="mono">${esc(data.password)}</div></div>
            <div><div class="small">Expired Date</div><div class="mono">${esc(data.expiresAt)}</div></div>
            <div><div class="small">Days Left</div><div>${esc(data.daysLeft)}</div></div>
          </div>
        </div>
      `);
      await loadState();
    }

    async function submitTopup() {
      if (!state) return alert('Load User ID first');
      const userId = $('userId').value.trim();
      const amount = $('topupAmount').value;
      const file = $('slip').files[0];
      if (!file) return alert('Choose slip image');

      const fd = new FormData();
      fd.append('userId', userId);
      fd.append('amount', amount);
      fd.append('slip', file);

      const res = await fetch('/api/topup', { method: 'POST', body: fd });
      const data = await res.json();
      if (!data.ok) {
        $('topupNote').innerHTML = `<span class="error">${esc(data.error || 'Topup failed')}</span>`;
        return;
      }
      $('topupNote').innerHTML = `<span class="success">Topup request sent. Wait for admin approval.</span>`;
      $('slip').value = '';
      await loadState();
    }

    window.addEventListener('load', () => {
      const saved = localStorage.getItem('zivpn_user_id');
      if (saved) {
        $('userId').value = saved;
        loadState();
      }
    });
  </script></body>
</html>
EOFcat > "$SERVICE_FILE" <<EOF [Unit] Description=Zivpn Panel + Bot After=network.target

[Service] Type=simple WorkingDirectory=$APP_DIR ExecStart=/usr/bin/node $APP_DIR/app.js Restart=always RestartSec=3 User=root Environment=NODE_ENV=production

[Install] WantedBy=multi-user.target EOF

cd "$APP_DIR" npm install

systemctl daemon-reload systemctl enable zivpn-panel.service systemctl restart zivpn-panel.service

ufw allow "${PANEL_PORT}/tcp" >/dev/null 2>&1 || true

sleep 2

echo "" echo "=== Installation finished ===" echo "Panel URL: http://${SERVER_IP}:${PANEL_PORT}" echo "Service: systemctl status zivpn-panel.service --no-pager" echo "Logs: journalctl -u zivpn-panel.service -f" echo "Check port: ss -lntp | grep :${PANEL_PORT}" echo "Zivpn config synced from: ${ZIVPN_CONFIG_PATH}"
