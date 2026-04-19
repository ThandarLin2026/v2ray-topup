#!/bin/bash
# ZIVPN UDP + Topup Panel v6 - Fixed for Ubuntu 20.04
set -e

echo "=== ZIVPN Panel Installer ==="
read -p "Telegram Bot Token: " BOT_TOKEN
read -p "Admin Telegram ID: " ADMIN_ID
read -p "Enter Hostname (eg: vpn.example.com): " HOSTNAME
HOSTNAME=${HOSTNAME:-eg.linvpn.shop}

apt-get update -y
apt-get install -y python3 python3-pip curl sqlite3

echo "=== Installing ZIVPN ==="
systemctl stop zivpn 2>/dev/null || true
wget -q https://github.com/zahidbd2/udp-zivpn/releases/download/udp-zivpn_1.4.9/udp-zivpn-linux-amd64 -O /usr/local/bin/zivpn
chmod +x /usr/local/bin/zivpn
mkdir -p /etc/zivpn
wget -qO /etc/zivpn/config.json https://raw.githubusercontent.com/zahidbd2/udp-zivpn/main/config.json
openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 -subj "/CN=zivpn" -keyout /etc/zivpn/zivpn.key -out /etc/zivpn/zivpn.crt 2>/dev/null
sysctl -w net.core.rmem_max=16777216 >/dev/null
sysctl -w net.core.wmem_max=16777216 >/dev/null

cat > /etc/systemd/system/zivpn.service <<'SERVICE'
[Unit]
Description=zivpn VPN Server
After=network.target
[Service]
Type=simple
ExecStart=/usr/local/bin/zivpn server -c /etc/zivpn/config.json
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable --now zivpn
iptables -t nat -C PREROUTING -p udp --dport 6000:19999 -j DNAT --to-destination :5667 2>/dev/null || iptables -t nat -A PREROUTING -p udp --dport 6000:19999 -j DNAT --to-destination :5667
ufw allow 6000:19999/udp >/dev/null 2>&1 || true
ufw allow 5667/udp >/dev/null 2>&1 || true
ufw allow 8888/tcp >/dev/null 2>&1 || true

echo "=== Panel Setup ==="
mkdir -p /opt/zivpn-panel/templates /opt/zivpn-panel/uploads

# Fix pip for old Ubuntu
pip3 install --upgrade pip >/dev/null 2>&1 || true
pip3 install flask requests "python-telegram-bot==21.4"

cat > /opt/zivpn-panel/config.env <<EOF
BOT_TOKEN=$BOT_TOKEN
ADMIN_ID=$ADMIN_ID
HOSTNAME=$HOSTNAME
EOF

# --- web.py ---
cat > /opt/zivpn-panel/web.py <<'PY'
import sqlite3, json, subprocess, datetime, os, requests
from flask import Flask, render_template, request, jsonify
from datetime import timedelta
from werkzeug.utils import secure_filename

ENV=dict(l.split('=',1) for l in open('/opt/zivpn-panel/config.env').read().splitlines())
DB='/opt/zivpn-panel/database.db'
CFG='/etc/zivpn/config.json'
IP=subprocess.getoutput("curl -s ifconfig.me")
HOST=ENV['HOSTNAME']
BOT=ENV['BOT_TOKEN']
ADMIN=ENV['ADMIN_ID']
UP='/opt/zivpn-panel/uploads'

app=Flask(__name__)

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init():
    c=db();cur=c.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE,credit INTEGER DEFAULT 0,created TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY,user_id INTEGER,vpn_user TEXT,vpn_pass TEXT,expiry_date TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS topups(id INTEGER PRIMARY KEY,user_id INTEGER,amount INTEGER,bank_id INTEGER,status TEXT DEFAULT "pending",slip TEXT,created TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS banks(id INTEGER PRIMARY KEY,name TEXT,account TEXT,number TEXT)')
    c.commit()
init()

def update_cfg():
    con=db();cur=con.cursor()
    cur.execute("SELECT vpn_pass FROM accounts WHERE expiry_date>datetime('now')")
    pw=[r[0] for r in cur.fetchall()] or ["zi"]
    with open(CFG) as f: j=json.load(f)
    j['auth']['config']=pw
    with open(CFG,'w') as f: json.dump(j,f,indent=2)
    subprocess.run(['systemctl','restart','zivpn'],stdout=subprocess.DEVNULL)

@app.route('/')
def home(): return render_template('index.html',ip=IP,host=HOST)

@app.route('/api/user')
def user():
    u=request.args.get('u','').strip()
    if not u: return jsonify(ok=False)
    con=db();cur=con.cursor()
    cur.execute("INSERT OR IGNORE INTO users(username,created) VALUES(?,datetime('now'))",(u,))
    con.commit()
    r=con.execute("SELECT id,username,credit FROM users WHERE username=?",(u,)).fetchone()
    return jsonify(ok=True,id=r['id'],username=r['username'],credit=r['credit'])

@app.route('/api/banks')
def banks():
    r=db().execute("SELECT * FROM banks").fetchall()
    return jsonify([dict(x) for x in r])

@app.route('/api/status')
def status():
    s=subprocess.getoutput("systemctl is-active zivpn")
    c=db().execute("SELECT COUNT(*) c FROM accounts WHERE expiry_date>datetime('now')").fetchone()['c']
    u=subprocess.getoutput("uptime -p")
    return jsonify(zivpn=s,active=c,uptime=u,host=HOST,ip=IP)

@app.route('/api/topup',methods=['POST'])
def topup():
    u=request.form.get('u','').strip()
    amt=int(request.form.get('amount',0))
    bank_id=int(request.form.get('bank',0))
    file=request.files.get('slip')
    if not all([u,amt,bank_id,file]): return jsonify(ok=False,msg='အကုန်ဖြည့်ပါ')
    con=db();cur=con.cursor()
    cur.execute("INSERT OR IGNORE INTO users(username,created) VALUES(?,datetime('now'))",(u,))
    con.commit()
    user=con.execute("SELECT * FROM users WHERE username=?",(u,)).fetchone()
    bank=con.execute("SELECT * FROM banks WHERE id=?",(bank_id,)).fetchone()
    if not bank: return jsonify(ok=False,msg='Bank မရှိ')
    fn=secure_filename(f"{u}_{datetime.datetime.now().timestamp()}.jpg")
    path=os.path.join(UP,fn); file.save(path)
    cur.execute("INSERT INTO topups(user_id,amount,bank_id,slip,created) VALUES(?,?,?,?,datetime('now'))",(user['id'],amt,bank_id,fn))
    tid=cur.lastrowid; con.commit()
    cap=f"Topup #{tid}\nUser: {u}\nAmount: {amt} THB\nBank: {bank['name']} {bank['number']}"
    requests.post(f"https://api.telegram.org/bot{BOT}/sendPhoto",data={'chat_id':ADMIN,'caption':cap,'reply_markup':json.dumps({'inline_keyboard':[[{'text':'✅ Approve','callback_data':f'a_{tid}'},{'text':'❌ Cancel','callback_data':f'c_{tid}'}]]})},files={'photo':open(path,'rb')})
    return jsonify(ok=True,msg='Request ပို့ပြီး')

@app.route('/create',methods=['POST'])
def create():
    d=request.json; u=d.get('user','').strip(); p=d.get('pass','').strip(); days=int(d.get('days',30))
    if not u or not p: return jsonify(ok=False,msg='Username/Password လို')
    price={30:50,60:80,90:120}.get(days,50)
    con=db();cur=con.cursor()
    cur.execute("INSERT OR IGNORE INTO users(username,created) VALUES(?,datetime('now'))",(u,))
    con.commit()
    user=con.execute("SELECT * FROM users WHERE username=?",(u,)).fetchone()
    if user['credit']<price: return jsonify(ok=False,msg=f'Credit မလောက် ({user["credit"]} THB)')
    exp=datetime.datetime.now()+timedelta(days=days)
    cur.execute("INSERT INTO accounts(user_id,vpn_user,vpn_pass,expiry_date) VALUES(?,?,?,?)",(user['id'],u,p,exp.strftime('%Y-%m-%d %H:%M:%S')))
    cur.execute("UPDATE users SET credit=credit-? WHERE id=?",(price,user['id']))
    con.commit(); update_cfg()
    return jsonify(ok=True,ip=IP,host=HOST,user=u,pwd=p,exp=exp.strftime('%Y-%m-%d'),left=days)

app.run(host='0.0.0.0',port=8888)
PY

# --- bot.py ---
cat > /opt/zivpn-panel/bot.py <<'PY'
import sqlite3,os,datetime,json
from telegram import Update
from telegram.ext import Application,CommandHandler,CallbackQueryHandler

ENV=dict(l.split('=',1) for l in open('/opt/zivpn-panel/config.env').read().splitlines())
DB='/opt/zivpn-panel/database.db'
ADMIN=int(ENV['ADMIN_ID'])
TOKEN=ENV['BOT_TOKEN']
HOST=ENV['HOSTNAME']

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

async def start(u,c):
    if u.effective_user.id!=ADMIN: return
    await u.message.reply_text(f"ZIVPN Admin\nHost: {HOST}\n/banks /addbank /delbank /users")

async def banks(u,c):
    if u.effective_user.id!=ADMIN: return
    rows=db().execute("SELECT * FROM banks").fetchall()
    msg="Banks:\n"+ "\n".join([f"{r['id']}. {r['name']} {r['account']} {r['number']}" for r in rows]) or "မရှိ"
    await u.message.reply_text(msg)

async def addbank(u,c):
    if u.effective_user.id!=ADMIN: return
    try: data=' '.join(c.args); name,acc,num=[x.strip() for x in data.split('|')][:3]
    except: return await u.message.reply_text("Format: /addbank Name|Account|Number")
    db().execute("INSERT INTO banks(name,account,number) VALUES(?,?,?)",(name,acc,num)); db().commit()
    await u.message.reply_text("ထည့်ပြီး")

async def delbank(u,c):
    if u.effective_user.id!=ADMIN: return
    try: bid=int(c.args[0]); db().execute("DELETE FROM banks WHERE id=?",(bid,)); db().commit(); await u.message.reply_text("ဖျက်ပြီး")
    except: await u.message.reply_text("Usage: /delbank ID")

async def users(u,c):
    if u.effective_user.id!=ADMIN: return
    rows=db().execute("SELECT username,credit FROM users ORDER BY id DESC LIMIT 30").fetchall()
    await u.message.reply_text("Users:\n"+ "\n".join([f"{r['username']} - {r['credit']} THB" for r in rows]))

async def cb(u,c):
    q=u.callback_query; act,tid=q.data.split('_'); con=db();cur=con.cursor()
    t=cur.execute("SELECT t.*,u.username FROM topups t JOIN users u ON u.id=t.user_id WHERE t.id=?",(tid,)).fetchone()
    if not t: return await q.answer("မရှိ")
    if act=='a':
        cur.execute("UPDATE topups SET status='ok' WHERE id=?",(tid,)); cur.execute("UPDATE users SET credit=credit+? WHERE id=?",(t['amount'],t['user_id'])); con.commit()
        await q.edit_message_caption(q.message.caption+"\n\nAPPROVED")
    else:
        cur.execute("UPDATE topups SET status='no' WHERE id=?",(tid,)); con.commit()
        await q.edit_message_caption(q.message.caption+"\n\nCANCELLED")
    await q.answer()

def main():
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler('start',start))
    app.add_handler(CommandHandler('banks',banks))
    app.add_handler(CommandHandler('addbank',addbank))
    app.add_handler(CommandHandler('delbank',delbank))
    app.add_handler(CommandHandler('users',users))
    app.add_handler(CallbackQueryHandler(cb,pattern='^[ac]_'))
    app.run_polling()

if __name__=='__main__': main()
PY

# --- index.html ---
cat > /opt/zivpn-panel/templates/index.html <<'HTML'
<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ZIVPN PANEL</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body{background:#0a0e1a;color:#e2e8f0;font-family:system-ui}
.card{background:#1e293b;border:1px solid #334155}
.nav-tabs .nav-link{color:#94a3b8;border:none}
.nav-tabs .nav-link.active{background:#1e293b;color:#fff}
svg{width:18px;height:18px;vertical-align:-3px;margin-right:6px}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem}
</style>
</head><body class="p-3"><div class="container" style="max-width:520px">
<div class="topbar">
  <h4><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L2 7v10c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V7l-10-5z"/></svg>ZIVPN PANEL</h4>
  <div id="userinfo"></div>
</div>
<div id="loginbox" class="card p-3 mb-3" style="display:none">
  <h6>Login</h6>
  <input id="loginuser" class="form-control mb-2" placeholder="Username">
  <button onclick="login()" class="btn btn-primary w-100">Login / Register</button>
</div>
<ul class="nav nav-tabs" id="maintabs" style="display:none">
<li class="nav-item"><button class="nav-link active" data-bs-toggle="tab" data-bs-target="#bal"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="M7 16l3-3 4 4 5-5"/></svg>Balance</button></li>
<li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#top"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>TopUp</button></li>
<li class="nav-item"><button class="nav-link" data-bs-toggle="tab" data-bs-target="#srv"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><path d="M6 6h.01M6 18h.01"/></svg>Status</button></li>
</ul>
<div class="tab-content mt-3" id="maincontent" style="display:none">
<div class="tab-pane fade show active" id="bal">
  <div class="card p-3"><h5>Balance: <span id="balval">0</span> THB</h5><button onclick="logout()" class="btn btn-sm btn-secondary mt-2">Logout</button></div>
  <div class="card p-3 mt-3"><h6>Create Account</h6>
  <input id="vpnuser" class="form-control mb-2" placeholder="VPN Username">
  <input id="vpnpass" class="form-control mb-2" placeholder="VPN Password">
  <select id="days" class="form-control mb-2"><option value="30">30 Days - 50 THB</option><option value="60">60 Days - 80 THB</option><option value="90">90 Days - 120 THB</option></select>
  <button onclick="create()" class="btn btn-success w-100">Create</button></div>
</div>
<div class="tab-pane fade" id="top"><div class="card p-3"><select id="bank" class="form-control mb-2"></select><select id="amt" class="form-control mb-2"><option value="50">50 THB</option><option value="100">100 THB</option><option value="150">150 THB</option></select><input type="file" id="slip" class="form-control mb-2" accept="image/*"><button onclick="topup()" class="btn btn-warning w-100">Submit TopUp</button></div></div>
<div class="tab-pane fade" id="srv"><div class="card p-3" id="srvres">Loading...</div></div>
</div></div>
<div class="modal fade" id="m"><div class="modal-dialog"><div class="modal-content bg-dark text-white"><div class="modal-header"><h5>Success</h5></div><div class="modal-body" id="b"></div></div></div></div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
let CUR=null;const $=id=>document.getElementById(id);
function setUser(u){CUR=u;localStorage.setItem('zivpn_user',u.username);$('userinfo').innerHTML=`ID:${u.id} | ${u.username} | ${u.credit} THB`;$('balval').innerText=u.credit;$('loginbox').style.display='none';$('maintabs').style.display='flex';$('maincontent').style.display='block';loadBanks();status();}
function logout(){localStorage.removeItem('zivpn_user');location.reload();}
async function login(){const u=$('loginuser').value.trim();if(!u)return alert('Username');const r=await fetch('/api/user?u='+u);const j=await r.json();if(j.ok)setUser(j);}
async function create(){const d={user:$('vpnuser').value,pass:$('vpnpass').value,days:$('days').value};const r=await fetch('/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});const j=await r.json();if(!j.ok)return alert(j.msg);b.innerHTML=`IP:${j.ip}<br>Host:${j.host}<br>User:${j.user}<br>Pass:${j.pwd}<br>Exp:${j.exp}`;new bootstrap.Modal(m).show();refresh();}
async function loadBanks(){const r=await fetch('/api/banks');const j=await r.json();bank.innerHTML=j.map(x=>`<option value="${x.id}">${x.name} ${x.account} ${x.number}</option>`).join('')}
async function topup(){const fd=new FormData();fd.append('u',CUR.username);fd.append('amount',amt.value);fd.append('bank',bank.value);fd.append('slip',slip.files[0]);const r=await fetch('/api/topup',{method:'POST',body:fd});const j=await r.json();alert(j.msg);}
async function status(){const r=await fetch('/api/status');const j=await r.json();srvres.innerHTML=`<b>Host:</b> ${j.host}<br><b>IP:</b> ${j.ip}<br><b>ZIVPN:</b> ${j.zivpn}<br><b>Active:</b> ${j.active}<br><b>Uptime:</b> ${j.uptime}`}
async function refresh(){const r=await fetch('/api/user?u='+CUR.username);const j=await r.json();if(j.ok)setUser(j);}
window.onload=()=>{const u=localStorage.getItem('zivpn_user');if(u){fetch('/api/user?u='+u).then(r=>r.json()).then(j=>{if(j.ok)setUser(j);else $('loginbox').style.display='block';})}else $('loginbox').style.display='block';}
</script></body></html>
HTML

cat > /opt/zivpn-panel/exp.py <<'PY'
import sqlite3,json,subprocess
c=sqlite3.connect('/opt/zivpn-panel/database.db');cur=c.cursor()
cur.execute("DELETE FROM accounts WHERE expiry_date<=datetime('now')");c.commit()
pw=[r[0] for r in cur.execute("SELECT vpn_pass FROM accounts WHERE expiry_date>datetime('now')")] or ['zi']
j=json.load(open('/etc/zivpn/config.json'));j['auth']['config']=pw;json.dump(j,open('/etc/zivpn/config.json','w'),indent=2)
subprocess.run(['systemctl','restart','zivpn'])
PY

cat > /etc/systemd/system/zivpn-panel.service <<EOF
[Unit] After=network.target
[Service] WorkingDirectory=/opt/zivpn-panel ExecStart=/usr/bin/python3 /opt/zivpn-panel/web.py Restart=always
[Install] WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/zivpn-bot.service <<EOF
[Unit] After=network.target
[Service] WorkingDirectory=/opt/zivpn-panel ExecStart=/usr/bin/python3 /opt/zivpn-panel/bot.py Restart=always
[Install] WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now zivpn-panel zivpn-bot
(crontab -l 2>/dev/null; echo "0 * * * * python3 /opt/zivpn-panel/exp.py")|crontab -

IP=$(curl -s ifconfig.me)
echo "=============================="
echo "✅ Done! Panel: http://$IP:8888"
echo "Hostname: $HOSTNAME"
echo "=============================="
