#!/bin/bash
set -e

APP_DIR="/opt/zivpn-panel"
PUBLIC_DIR="$APP_DIR/public"
SERVICE_FILE="/etc/systemd/system/zivpn-panel.service"

echo "=== Installing dependencies ==="
apt-get update -y
apt-get install -y nodejs npm ufw openssl

mkdir -p "$APP_DIR" "$PUBLIC_DIR"

echo "=== Enter settings ==="
read -p "Telegram Bot Token: " BOT_TOKEN
read -p "Admin Chat ID: " ADMIN_CHAT_ID
read -p "Hostname (example: linvpn.shop): " HOSTNAME
read -p "Panel Port (example: 8080): " PANEL_PORT
read -p "Server IP (public IP shown in panel): " SERVER_IP

cat > "$APP_DIR/.env" <<EOF
BOT_TOKEN=$BOT_TOKEN
ADMIN_CHAT_ID=$ADMIN_CHAT_ID
HOSTNAME=$HOSTNAME
PANEL_PORT=$PANEL_PORT
SERVER_IP=$SERVER_IP
ZIVPN_CONFIG=/etc/zivpn/config.json
ZIVPN_SERVICE=zivpn.service
EOF

cat > "$APP_DIR/package.json" <<'EOF'
{
  "name": "zivpn-panel",
  "version": "1.0.0",
  "main": "app.js",
  "license": "MIT",
  "dependencies": {
    "dotenv": "^16.4.5",
    "express": "^4.21.2",
    "telegraf": "^4.16.3"
  }
}
EOF

cat > "$APP_DIR/app.js" <<'EOF'
require('dotenv').config();

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const express = require('express');
const { Telegraf, Markup } = require('telegraf');
const { execSync } = require('child_process');

const APP_DIR = '/opt/zivpn-panel';
const DATA_FILE = path.join(APP_DIR, 'data.json');
const PUBLIC_DIR = path.join(APP_DIR, 'public');
const ZIVPN_CONFIG = process.env.ZIVPN_CONFIG || '/etc/zivpn/config.json';
const ZIVPN_SERVICE = process.env.ZIVPN_SERVICE || 'zivpn.service';
const HOSTNAME = process.env.HOSTNAME || 'localhost';
const SERVER_IP = process.env.SERVER_IP || '0.0.0.0';
const PANEL_PORT = Number(process.env.PANEL_PORT || 8080);
const BOT_TOKEN = process.env.BOT_TOKEN || '';
const ADMIN_CHAT_ID = String(process.env.ADMIN_CHAT_ID || '');

const PLAN_PRICES = { 30: 50, 60: 80 };

function now() { return new Date(); }
function isoNow() { return now().toISOString(); }
function daysLeft(exp) {
  const diff = new Date(exp).getTime() - Date.now();
  return Math.max(0, Math.ceil(diff / 86400000));
}
function priceFor(days) { return PLAN_PRICES[Number(days)] || 0; }
function uid(prefix='id') { return `${prefix}_${crypto.randomBytes(6).toString('hex')}`; }

function ensureDataFile() {
  if (!fs.existsSync(DATA_FILE)) {
    const init = {
      users: [],
      accounts: [],
      topups: [],
      botFlows: {}
    };
    fs.writeFileSync(DATA_FILE, JSON.stringify(init, null, 2));
  }
}
function loadData() {
  ensureDataFile();
  return JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
}
function saveData(data) {
  fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 2));
}

function getUser(data, tgId, username = '') {
  let user = data.users.find(u => String(u.tgId) === String(tgId));
  if (!user) {
    user = {
      tgId: String(tgId),
      username: username || '',
      credit: 0,
      createdAt: isoNow()
    };
    data.users.push(user);
  } else if (username && !user.username) {
    user.username = username;
  }
  return user;
}

function sanitizeStr(v) {
  return String(v || '').trim();
}
function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function syncZivpnConfig() {
  try {
    if (!fs.existsSync(ZIVPN_CONFIG)) return;

    const data = loadData();
    const activePasswords = data.accounts
      .filter(a => a.status === 'active' && new Date(a.expiresAt).getTime() > Date.now())
      .map(a => a.password);

    let configJson = {};
    try {
      configJson = JSON.parse(fs.readFileSync(ZIVPN_CONFIG, 'utf8'));
    } catch (e) {
      console.error('Failed to parse Zivpn config.json:', e.message);
      return;
    }

    configJson.config = activePasswords;

    fs.writeFileSync(ZIVPN_CONFIG, JSON.stringify(configJson, null, 2));
    execSync(`systemctl restart ${ZIVPN_SERVICE}`, { stdio: 'ignore' });
  } catch (e) {
    console.error('syncZivpnConfig error:', e.message);
  }
}

function expireJob() {
  const data = loadData();
  let changed = false;
  const nowTs = Date.now();

  for (const acc of data.accounts) {
    if (acc.status === 'active' && new Date(acc.expiresAt).getTime() <= nowTs) {
      acc.status = 'expired';
      changed = true;
    }
  }

  if (changed) {
    saveData(data);
    syncZivpnConfig();
  }
}

function createAccountForUser({ tgId, panelUsername, panelPassword, days }) {
  const d = loadData();
  const user = getUser(d, tgId);

  const daysNum = Number(days);
  const price = priceFor(daysNum);
  if (!price) return { ok: false, error: 'Invalid plan.' };

  const username = sanitizeStr(panelUsername);
  const password = sanitizeStr(panelPassword);

  if (!username || !password) return { ok: false, error: 'Username and password are required.' };
  if (d.accounts.some(a => a.username === username && a.status === 'active')) {
    return { ok: false, error: 'Username already exists.' };
  }
  if (d.accounts.some(a => a.password === password && a.status === 'active')) {
    return { ok: false, error: 'Password already exists.' };
  }
  if (user.credit < price) {
    return { ok: false, error: `Not enough credit. Need ${price} THB.` };
  }

  user.credit -= price;

  const expiresAt = new Date(Date.now() + daysNum * 86400000).toISOString();
  const acc = {
    id: uid('acc'),
    tgId: String(tgId),
    username,
    password,
    days: daysNum,
    price,
    status: 'active',
    createdAt: isoNow(),
    expiresAt
  };
  d.accounts.push(acc);

  saveData(d);
  syncZivpnConfig();

  return { ok: true, account: acc, user };
}

function approveTopup(topupId) {
  const d = loadData();
  const topup = d.topups.find(t => t.id === topupId);
  if (!topup || topup.status !== 'pending') return { ok: false, error: 'Topup not found or already processed.' };

  const user = getUser(d, topup.tgId);
  user.credit += Number(topup.amount);

  topup.status = 'approved';
  topup.approvedAt = isoNow();

  saveData(d);
  return { ok: true, user, topup };
}

function cancelTopup(topupId) {
  const d = loadData();
  const topup = d.topups.find(t => t.id === topupId);
  if (!topup || topup.status !== 'pending') return { ok: false, error: 'Topup not found or already processed.' };

  topup.status = 'cancelled';
  topup.cancelledAt = isoNow();

  saveData(d);
  return { ok: true, topup };
}

function getActiveAccountsForUser(tgId) {
  const d = loadData();
  expireJob();
  return d.accounts.filter(a => String(a.tgId) === String(tgId)).sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
}

function getTopUsers() {
  const d = loadData();
  const map = new Map();
  for (const t of d.topups.filter(t => t.status === 'approved')) {
    const key = String(t.tgId);
    map.set(key, (map.get(key) || 0) + Number(t.amount));
  }
  const arr = [...map.entries()].map(([tgId, total]) => {
    const user = d.users.find(u => String(u.tgId) === tgId) || { tgId, username: '' };
    return { tgId, username: user.username || '', total };
  });
  arr.sort((a, b) => b.total - a.total);
  return arr;
}

function renderAccountCard(acc) {
  return `
    <div class="card">
      <div class="row"><span>Username</span><b>${esc(acc.username)}</b></div>
      <div class="row"><span>Password</span><b>${esc(acc.password)}</b></div>
      <div class="row"><span>Days</span><b>${esc(acc.days)}</b></div>
      <div class="row"><span>Status</span><b>${esc(acc.status)}</b></div>
      <div class="row"><span>Expired Date</span><b>${esc(acc.expiresAt)}</b></div>
      <div class="row"><span>Days Left</span><b>${daysLeft(acc.expiresAt)}</b></div>
    </div>`;
}

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(PUBLIC_DIR));

app.get('/api/state', (req, res) => {
  const tgId = req.query.telegramId;
  if (!tgId) return res.status(400).json({ ok: false, error: 'telegramId required' });

  const d = loadData();
  const user = getUser(d, tgId);
  saveData(d);

  const accounts = d.accounts
    .filter(a => String(a.tgId) === String(tgId))
    .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

  res.json({
    ok: true,
    hostname: HOSTNAME,
    serverIp: SERVER_IP,
    panelPort: PANEL_PORT,
    plans: [
      { days: 30, price: 50 },
      { days: 60, price: 80 }
    ],
    user: {
      tgId: String(tgId),
      credit: user.credit || 0
    },
    accounts
  });
});

app.post('/api/create-account', (req, res) => {
  const { telegramId, username, password, days } = req.body;
  if (!telegramId || !username || !password || !days) {
    return res.status(400).json({ ok: false, error: 'Missing fields' });
  }

  const result = createAccountForUser({
    tgId: telegramId,
    panelUsername: username,
    panelPassword: password,
    days
  });

  if (!result.ok) return res.status(400).json(result);

  res.json({
    ok: true,
    message: 'Create Account Successfully',
    serverIp: SERVER_IP,
    hostname: HOSTNAME,
    username: result.account.username,
    password: result.account.password,
    expiresAt: result.account.expiresAt,
    daysLeft: daysLeft(result.account.expiresAt),
    credit: result.user.credit,
    account: result.account
  });
});

app.get('/', (req, res) => {
  res.sendFile(path.join(PUBLIC_DIR, 'index.html'));
});

const bot = BOT_TOKEN ? new Telegraf(BOT_TOKEN) : null;
const flows = {};

function mainKeyboard(isAdmin = false) {
  const rows = [
    ['💳 Balance', '➕ Create Account'],
    ['🧾 My Accounts', '💰 Topup']
  ];
  if (isAdmin) rows.push(['👥 Userlist', '🏆 Top Users']);
  rows.push(['ℹ️ Help']);
  return Markup.keyboard(rows).resize();
}

function adminOnly(id) {
  return String(id) === String(ADMIN_CHAT_ID);
}

function fmtAccount(acc) {
  return (
    `🧾 <b>Account</b>\n` +
    `Username: <code>${esc(acc.username)}</code>\n` +
    `Password: <code>${esc(acc.password)}</code>\n` +
    `Plan: ${esc(acc.days)} days\n` +
    `Status: ${esc(acc.status)}\n` +
    `Expired: ${esc(acc.expiresAt)}\n` +
    `Days Left: ${daysLeft(acc.expiresAt)}\n`
  );
}

if (bot) {
  bot.start(async (ctx) => {
    const data = loadData();
    getUser(data, ctx.from.id, ctx.from.username || '');
    saveData(data);

    await ctx.reply(
      `Welcome.\nTelegram ID: ${ctx.from.id}\nCredit balance is managed here.`,
      mainKeyboard(adminOnly(ctx.from.id))
    );
  });

  bot.hears('💳 Balance', async (ctx) => {
    const d = loadData();
    const user = getUser(d, ctx.from.id, ctx.from.username || '');
    saveData(d);
    await ctx.reply(`Your balance: ${user.credit} THB`, mainKeyboard(adminOnly(ctx.from.id)));
  });

  bot.hears('🧾 My Accounts', async (ctx) => {
    const accounts = getActiveAccountsForUser(ctx.from.id);
    if (!accounts.length) return ctx.reply('No accounts found.');
    for (const acc of accounts) {
      await ctx.reply(fmtAccount(acc), { parse_mode: 'HTML' });
    }
  });

  bot.hears('➕ Create Account', async (ctx) => {
    flows[ctx.from.id] = { step: 'create_username' };
    await ctx.reply('Send Username for the new account.');
  });

  bot.hears('💰 Topup', async (ctx) => {
    flows[ctx.from.id] = { step: 'topup_amount' };
    await ctx.reply('Send topup amount: 50 / 100 / 150');
  });

  bot.hears('👥 Userlist', async (ctx) => {
    if (!adminOnly(ctx.from.id)) return;
    const d = loadData();
    const accounts = d.accounts.slice().sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt)).slice(0, 50);
    if (!accounts.length) return ctx.reply('No accounts yet.');
    for (const acc of accounts) {
      await ctx.reply(fmtAccount(acc), { parse_mode: 'HTML' });
    }
  });

  bot.hears('🏆 Top Users', async (ctx) => {
    if (!adminOnly(ctx.from.id)) return;
    const list = getTopUsers().slice(0, 20);
    if (!list.length) return ctx.reply('No approved topups yet.');
    const text = list.map((u, i) => `${i + 1}. ${u.username || u.tgId} — ${u.total} THB`).join('\n');
    await ctx.reply(`🏆 Top Users\n\n${text}`);
  });

  bot.hears('ℹ️ Help', async (ctx) => {
    await ctx.reply(
      'Use Balance, Create Account, My Accounts, Topup.\nAdmins can see Userlist and Top Users.',
      mainKeyboard(adminOnly(ctx.from.id))
    );
  });

  bot.on('text', async (ctx) => {
    const flow = flows[ctx.from.id];
    if (!flow) return;

    const text = ctx.message.text.trim();

    if (flow.step === 'topup_amount') {
      const amount = Number(text);
      if (![50, 100, 150].includes(amount)) {
        return ctx.reply('Please send only 50, 100, or 150.');
      }
      flows[ctx.from.id] = { step: 'topup_slip', amount };
      return ctx.reply(`Now send the slip photo for ${amount} THB.`);
    }

    if (flow.step === 'create_username') {
      flows[ctx.from.id].username = text;
      flows[ctx.from.id].step = 'create_password';
      return ctx.reply('Send Password.');
    }

    if (flow.step === 'create_password') {
      flows[ctx.from.id].password = text;
      flows[ctx.from.id].step = 'create_days';
      return ctx.reply('Choose plan: send 30 or 60');
    }

    if (flow.step === 'create_days') {
      const days = Number(text);
      if (![30, 60].includes(days)) return ctx.reply('Send only 30 or 60.');
      const result = createAccountForUser({
        tgId: ctx.from.id,
        panelUsername: flow.username,
        panelPassword: flow.password,
        days
      });
      delete flows[ctx.from.id];
      if (!result.ok) return ctx.reply(`Failed: ${result.error}`);

      return ctx.reply(
        `Create Account Successfully\n\nServer IP: ${SERVER_IP}\nHostname: ${HOSTNAME}\nUsername: ${result.account.username}\nPassword: ${result.account.password}\nExpired Date: ${result.account.expiresAt}\nDays Left: ${daysLeft(result.account.expiresAt)}\nCredit Left: ${result.user.credit} THB`
      );
    }
  });

  bot.on('photo', async (ctx) => {
    const flow = flows[ctx.from.id];
    if (!flow || flow.step !== 'topup_slip') return;

    const amount = flow.amount;
    const photo = ctx.message.photo[ctx.message.photo.length - 1];
    const fileId = photo.file_id;

    const d = loadData();
    const user = getUser(d, ctx.from.id, ctx.from.username || '');
    const topup = {
      id: uid('topup'),
      tgId: String(ctx.from.id),
      username: user.username || '',
      amount,
      slipFileId: fileId,
      status: 'pending',
      createdAt: isoNow()
    };
    d.topups.push(topup);
    saveData(d);
    delete flows[ctx.from.id];

    const caption =
      `📥 New Topup Request\n` +
      `User: ${user.username || ctx.from.id}\n` +
      `TG ID: ${ctx.from.id}\n` +
      `Amount: ${amount} THB\n` +
      `Status: pending`;

    const kb = Markup.inlineKeyboard([
      [
        Markup.button.callback('✅ Approve', `topup:approve:${topup.id}`),
        Markup.button.callback('❌ Cancel', `topup:cancel:${topup.id}`)
      ]
    ]);

    await ctx.reply('Slip sent to admin for approval.');
    try {
      await bot.telegram.sendPhoto(ADMIN_CHAT_ID, fileId, { caption, parse_mode: 'HTML', ...kb });
    } catch (e) {
      await bot.telegram.sendMessage(ADMIN_CHAT_ID, caption + '\n\n(photo forward failed)');
    }
  });

  bot.action(/topup:approve:(.+)/, async (ctx) => {
    if (!adminOnly(ctx.from.id)) return ctx.answerCbQuery('Admin only');
    const topupId = ctx.match[1];
    const result = approveTopup(topupId);
    if (!result.ok) return ctx.answerCbQuery(result.error);

    await ctx.answerCbQuery('Approved');
    await ctx.editMessageCaption(`✅ Approved\nUser: ${result.user.username || result.user.tgId}\nAmount: ${result.topup.amount} THB`);

    try {
      await bot.telegram.sendMessage(
        result.topup.tgId,
        `Your topup was approved.\nCredit added: ${result.topup.amount} THB\nCurrent balance: ${result.user.credit} THB`
      );
    } catch (e) {}
  });

  bot.action(/topup:cancel:(.+)/, async (ctx) => {
    if (!adminOnly(ctx.from.id)) return ctx.answerCbQuery('Admin only');
    const topupId = ctx.match[1];
    const result = cancelTopup(topupId);
    if (!result.ok) return ctx.answerCbQuery(result.error);

    await ctx.answerCbQuery('Cancelled');
    await ctx.editMessageCaption(`❌ Cancelled\nTG ID: ${result.topup.tgId}\nAmount: ${result.topup.amount} THB`);

    try {
      await bot.telegram.sendMessage(result.topup.tgId, `Your topup request was cancelled.`);
    } catch (e) {}
  });

  bot.launch().then(() => console.log('Telegram bot started'));
}

setInterval(expireJob, 5 * 60 * 1000);
expireJob();

app.listen(PANEL_PORT, '0.0.0.0', () => {
  console.log(`Panel running on ${PANEL_PORT}`);
  console.log(`Open: http://${SERVER_IP}:${PANEL_PORT}`);
});
EOF

cat > "$PUBLIC_DIR/index.html" <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Zivpn Panel</title>
  <style>
    body{font-family:system-ui,Arial;margin:0;background:#0f172a;color:#e2e8f0}
    .wrap{max-width:980px;margin:0 auto;padding:24px}
    .top{display:grid;grid-template-columns:1fr;gap:12px;margin-bottom:18px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
    .card,.panel{background:#111827;border:1px solid #243041;border-radius:18px;padding:16px;box-shadow:0 8px 30px rgba(0,0,0,.25)}
    input,select,button{width:100%;padding:12px 14px;border-radius:12px;border:1px solid #334155;background:#0b1220;color:#e2e8f0;box-sizing:border-box}
    button{cursor:pointer;background:#2563eb;border:none;font-weight:700}
    button.secondary{background:#334155}
    .row{display:flex;gap:10px;flex-wrap:wrap}
    .row > *{flex:1}
    .muted{color:#94a3b8;font-size:14px}
    h1,h2,h3,p{margin:0 0 10px}
    .badge{display:inline-block;padding:5px 10px;border-radius:999px;background:#1d4ed8;margin-bottom:10px}
    .accounts{display:grid;gap:12px}
    .card .line{display:flex;justify-content:space-between;gap:10px;padding:4px 0;border-bottom:1px dashed #273244}
    .card .line:last-child{border-bottom:none}
    .modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);align-items:center;justify-content:center;padding:18px}
    .modal.show{display:flex}
    .modal-box{max-width:560px;width:100%;background:#0b1220;border:1px solid #334155;border-radius:20px;padding:20px}
    .success{color:#86efac;font-weight:700}
    .error{color:#fca5a5;font-weight:700}
    .pill{padding:8px 12px;border-radius:999px;background:#1e293b;display:inline-block}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top panel">
      <span class="badge">Zivpn Topup Panel</span>
      <h1>Account Panel</h1>
      <p class="muted">Enter your Telegram ID to load balance and create accounts.</p>
      <div class="row">
        <input id="tgId" placeholder="Telegram ID" />
        <button onclick="loadState()">Load</button>
      </div>
      <div id="info" class="muted"></div>
    </div>

    <div class="grid">
      <div class="panel">
        <h2>Create Account</h2>
        <div class="row">
          <input id="username" placeholder="Username" />
          <input id="password" placeholder="Password" />
        </div>
        <div style="height:10px"></div>
        <select id="days">
          <option value="30">30 Days - 50 THB</option>
          <option value="60">60 Days - 80 THB</option>
        </select>
        <div style="height:10px"></div>
        <button onclick="createAccount()">Create Account</button>
        <p id="creditBox" class="muted" style="margin-top:10px"></p>
      </div>

      <div class="panel">
        <h2>Plan / Server</h2>
        <div id="serverBox" class="muted">Load panel first</div>
      </div>
    </div>

    <div style="height:16px"></div>

    <div class="panel">
      <h2>My Accounts</h2>
      <div id="accounts" class="accounts"></div>
    </div>
  </div>

  <div id="modal" class="modal">
    <div class="modal-box">
      <h2 class="success">Create Account Successfully</h2>
      <div id="modalBody" style="margin-top:12px"></div>
      <div style="height:14px"></div>
      <button onclick="closeModal()">Close</button>
    </div>
  </div>

  <script>
    let currentState = null;

    function openModal(html){
      document.getElementById('modalBody').innerHTML = html;
      document.getElementById('modal').classList.add('show');
    }
    function closeModal(){
      document.getElementById('modal').classList.remove('show');
    }

    function escapeHtml(s){
      return String(s ?? '')
        .replace(/&/g,'&amp;')
        .replace(/</g,'&lt;')
        .replace(/>/g,'&gt;')
        .replace(/"/g,'&quot;')
        .replace(/'/g,'&#39;');
    }

    function daysLeft(exp){
      return Math.max(0, Math.ceil((new Date(exp).getTime() - Date.now()) / 86400000));
    }

    async function loadState(){
      const tgId = document.getElementById('tgId').value.trim();
      if(!tgId) return alert('Enter Telegram ID');

      const r = await fetch('/api/state?telegramId=' + encodeURIComponent(tgId));
      const j = await r.json();
      if(!j.ok) return alert(j.error || 'Failed');

      currentState = j;
      document.getElementById('serverBox').innerHTML = `
        <div class="line"><span>Server IP</span><b>${escapeHtml(j.serverIp)}</b></div>
        <div class="line"><span>Hostname</span><b>${escapeHtml(j.hostname)}</b></div>
        <div class="line"><span>Panel Port</span><b>${escapeHtml(j.panelPort)}</b></div>
        <div class="line"><span>30 Days</span><b>50 THB</b></div>
        <div class="line"><span>60 Days</span><b>80 THB</b></div>
      `;
      document.getElementById('creditBox').innerHTML = `Credit: <b>${j.user.credit} THB</b>`;
      renderAccounts(j.accounts);
      document.getElementById('info').innerHTML = `Loaded for Telegram ID: <span class="pill">${escapeHtml(tgId)}</span>`;
    }

    function renderAccounts(accounts){
      const wrap = document.getElementById('accounts');
      if(!accounts || !accounts.length){
        wrap.innerHTML = '<p class="muted">No accounts found.</p>';
        return;
      }
      wrap.innerHTML = accounts.map(acc => `
        <div class="card">
          <div class="line"><span>Username</span><b>${escapeHtml(acc.username)}</b></div>
          <div class="line"><span>Password</span><b>${escapeHtml(acc.password)}</b></div>
          <div class="line"><span>Days</span><b>${escapeHtml(acc.days)}</b></div>
          <div class="line"><span>Status</span><b>${escapeHtml(acc.status)}</b></div>
          <div class="line"><span>Expired Date</span><b>${escapeHtml(acc.expiresAt)}</b></div>
          <div class="line"><span>Days Left</span><b>${daysLeft(acc.expiresAt)}</b></div>
        </div>
      `).join('');
    }

    async function createAccount(){
      if(!currentState) return alert('Load state first');
      const telegramId = document.getElementById('tgId').value.trim();
      const username = document.getElementById('username').value.trim();
      const password = document.getElementById('password').value.trim();
      const days = document.getElementById('days').value;

      const r = await fetch('/api/create-account', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ telegramId, username, password, days })
      });
      const j = await r.json();
      if(!j.ok) return alert(j.error || 'Create failed');

      openModal(`
        <div class="card" style="background:#0f172a">
          <div class="line"><span>Server IP</span><b>${escapeHtml(j.serverIp)}</b></div>
          <div class="line"><span>Hostname</span><b>${escapeHtml(j.hostname)}</b></div>
          <div class="line"><span>Username</span><b>${escapeHtml(j.username)}</b></div>
          <div class="line"><span>Password</span><b>${escapeHtml(j.password)}</b></div>
          <div class="line"><span>Expired Date</span><b>${escapeHtml(j.expiresAt)}</b></div>
          <div class="line"><span>Days Left</span><b>${escapeHtml(j.daysLeft)}</b></div>
        </div>
      `);

      await loadState();
    }

    window.addEventListener('click', (e) => {
      if(e.target.id === 'modal') closeModal();
    });
  </script>
</body>
</html>
EOF

echo "=== Installing npm packages ==="
cd "$APP_DIR"
npm install

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Zivpn Panel + Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/node $APP_DIR/app.js
Restart=always
RestartSec=3
User=root
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable zivpn-panel.service
systemctl start zivpn-panel.service

ufw allow "$PANEL_PORT"/tcp 1>/dev/null 2>/dev/null || true

echo "=== Done ==="
echo "Panel: http://$SERVER_IP:$PANEL_PORT"
echo "Bot: started if token is correct"
echo "Files: $APP_DIR"
