from fastapi import APIRouter, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse
import database
import auth

router = APIRouter(tags=["admin"])

@router.get("/admin")
async def admin_page():
    """管理后台页面"""
    return HTMLResponse(content='''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>管理后台</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f0f2f5;padding:20px}
        .container{max-width:1200px;margin:0 auto}
        .card{background:#fff;border-radius:16px;padding:24px;margin-bottom:20px;box-shadow:0 2px 10px rgba(0,0,0,0.1)}
        h1{color:#1e3c72;margin-bottom:24px;border-bottom:2px solid #4a90e2;padding-bottom:12px}
        h2{color:#333;margin-bottom:16px;font-size:18px}
        .login-box{max-width:400px;margin:100px auto}
        .form-group{margin-bottom:16px}
        label{display:block;margin-bottom:6px;color:#333;font-weight:500}
        input{width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:14px}
        button{padding:10px 20px;background:#4a90e2;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px}
        button:hover{background:#357abd}
        .result{margin-top:16px;padding:12px;border-radius:8px;display:none}
        .result.success{background:#e8f8f0;border:1px solid #2e7d32;display:block}
        .result.error{background:#ffebee;border:1px solid #c62828;display:block}
        table{width:100%;border-collapse:collapse;margin-top:16px}
        th,td{padding:12px;text-align:left;border-bottom:1px solid #eee}
        th{background:#f5f5f5;font-weight:600}
        .actions button{padding:4px 12px;margin:0 4px;font-size:12px}
        .danger{background:#dc3545}
        .danger:hover{background:#c82333}
        .logout-btn{float:right;background:#6c757d}
        .logout-btn:hover{background:#5a6268}
        .refresh-btn{background:#28a745;float:right;margin-right:10px}
        .refresh-btn:hover{background:#218838}
        .search-box{display:flex;gap:10px;margin:16px 0;align-items:center}
        .search-box input{flex:1;padding:8px;border:1px solid #ddd;border-radius:8px}
        .search-box button{padding:8px 16px;margin:0;background:#17a2b8}
        .search-box button:hover{background:#138496}
        .clear-btn{background:#6c757d}
        .clear-btn:hover{background:#5a6268}
        .api-key-cell{font-family:monospace;font-size:12px;word-break:break-all;max-width:300px}
    </style>
</head>
<body>
<div id="app"></div>
<script>
const tokenKey = 'admin_token';
if (localStorage.getItem(tokenKey)) { showAdminPanel(); } else { showLoginPage(); }

function showLoginPage() {
    document.getElementById('app').innerHTML = `
        <div class="login-box"><div class="card"><h1>🔐 管理员登录</h1>
        <div class="form-group"><label>密码</label><input type="password" id="password"></div>
        <button onclick="login()">登录</button><div id="loginResult" class="result"></div></div></div>`;
}

async function login() {
    const pwd = document.getElementById('password').value;
    const resDiv = document.getElementById('loginResult');
    if (!pwd) { resDiv.className='result error'; resDiv.innerHTML='❌ 请输入密码'; return; }
    try {
        const resp = await fetch('/admin/login', { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({password:pwd}) });
        const data = await resp.json();
        if (resp.ok) {
            localStorage.setItem(tokenKey, data.token);
            resDiv.className='result success';
            resDiv.innerHTML='✅ 登录成功';
            setTimeout(()=>showAdminPanel(), 1000);
        } else {
            resDiv.className='result error';
            resDiv.innerHTML=`❌ ${data.detail}`;
        }
    } catch(e) { resDiv.className='result error'; resDiv.innerHTML=`网络错误: ${e.message}`; }
}

function logout() { localStorage.removeItem(tokenKey); showLoginPage(); }

async function showAdminPanel() {
    const token = localStorage.getItem(tokenKey);
    document.getElementById('app').innerHTML = `
        <div class="container">
            <div class="card">
                <h1>🔐 用户管理后台 <button class="logout-btn" onclick="logout()">退出登录</button></h1>
                <h2>➕ 添加/充值用户</h2>
                <div class="form-group"><label>手机号</label><input type="tel" id="phone" placeholder="13812345678"></div>
                <div class="form-group"><label>次数</label><input type="number" id="balance" value="10"></div>
                <button onclick="addUser()">生成/充值</button>
                <div id="addResult" class="result"></div>
            </div>
            <div class="card">
                <h2>📋 用户列表</h2>
                <div class="search-box">
                    <input type="text" id="searchInput" placeholder="输入手机号搜索...">
                    <button onclick="searchUser()">🔍 搜索</button>
                    <button onclick="clearSearch()" class="clear-btn">清除</button>
                    <button onclick="loadUsers()" class="refresh-btn" style="float:none; margin:0">🔄 刷新</button>
                </div>
                <div id="userTable">加载中...</div>
            </div>
        </div>`;
    loadUsers();
}

let allUsers = [];

async function loadUsers() {
    const token = localStorage.getItem(tokenKey);
    const tableDiv = document.getElementById('userTable');
    tableDiv.innerHTML = '加载中...';
    try {
        const resp = await fetch('/admin/users', { headers: {'Authorization': `Bearer ${token}`} });
        if (resp.status === 401) { logout(); return; }
        const data = await resp.json();
        if (!resp.ok) { tableDiv.innerHTML = `<div class="result error">❌ ${data.detail}</div>`; return; }
        allUsers = data.users;
        renderUserList(allUsers);
    } catch(e) { tableDiv.innerHTML = `<div class="result error">网络错误: ${e.message}</div>`; }
}

function renderUserList(users) {
    const tableDiv = document.getElementById('userTable');
    if (!users || users.length === 0) { 
        tableDiv.innerHTML = '<div style="padding:20px;text-align:center;color:#666;">暂无用户</div>'; 
        return; 
    }
    let html = '<table style="width:100%;border-collapse:collapse;">';
    html += '<thead><tr>' +
            '<th style="padding:12px;text-align:left;border-bottom:1px solid #eee;background:#f5f5f5;">手机号</th>' +
            '<th style="padding:12px;text-align:left;border-bottom:1px solid #eee;background:#f5f5f5;">API Key</th>' +
            '<th style="padding:12px;text-align:center;border-bottom:1px solid #eee;background:#f5f5f5;">剩余次数</th>' +
            '<th style="padding:12px;text-align:left;border-bottom:1px solid #eee;background:#f5f5f5;">创建时间</th>' +
            '<th style="padding:12px;text-align:left;border-bottom:1px solid #eee;background:#f5f5f5;">最后使用</th>' +
            '<th style="padding:12px;text-align:left;border-bottom:1px solid #eee;background:#f5f5f5;">操作</th>' +
            '</tr></thead><tbody>';
    for (const u of users) {
        const created = u.created_at ? new Date(u.created_at).toLocaleString('zh-CN') : '-';
        const lastUsed = u.last_used_at ? new Date(u.last_used_at).toLocaleString('zh-CN') : '未使用';
        html += `<tr>
            <td style="padding:12px;border-bottom:1px solid #eee;">${escapeHtml(u.phone)}</td>
            <td style="padding:12px;border-bottom:1px solid #eee;font-family:monospace;font-size:12px;word-break:break-all;max-width:300px;">${escapeHtml(u.api_key)}</td>
            <td style="padding:12px;border-bottom:1px solid #eee;text-align:center;font-weight:bold;">${u.balance}</td>
            <td style="padding:12px;border-bottom:1px solid #eee;">${created}</td>
            <td style="padding:12px;border-bottom:1px solid #eee;">${lastUsed}</td>
            <td style="padding:12px;border-bottom:1px solid #eee;">
                <button onclick="recharge('${escapeHtml(u.phone)}')" style="padding:4px 12px;margin:0 4px;background:#4a90e2;color:#fff;border:none;border-radius:6px;cursor:pointer;">充值</button>
                <button onclick="del('${escapeHtml(u.phone)}')" style="padding:4px 12px;margin:0 4px;background:#dc3545;color:#fff;border:none;border-radius:6px;cursor:pointer;">删除</button>
            </td>
        </tr>`;
    }
    html += '</tbody></table>';
    tableDiv.innerHTML = html;
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>]/g, function(m) {
        if (m === '&') return '&amp;';
        if (m === '<') return '&lt;';
        if (m === '>') return '&gt;';
        return m;
    });
}

function searchUser() {
    const keyword = document.getElementById('searchInput').value.trim().toLowerCase();
    if (!keyword) {
        renderUserList(allUsers);
        return;
    }
    const filtered = allUsers.filter(u => u.phone && u.phone.toLowerCase().includes(keyword));
    renderUserList(filtered);
}

function clearSearch() {
    document.getElementById('searchInput').value = '';
    renderUserList(allUsers);
}

async function addUser() {
    const token = localStorage.getItem(tokenKey);
    const phone = document.getElementById('phone').value;
    const balance = document.getElementById('balance').value;
    const resDiv = document.getElementById('addResult');
    if (!phone) { resDiv.className='result error'; resDiv.innerHTML='❌ 请填写手机号'; return; }
    try {
        const resp = await fetch('/admin/add_user', { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded','Authorization':`Bearer ${token}`}, body:new URLSearchParams({phone,balance}) });
        const data = await resp.json();
        if (resp.ok) {
            resDiv.className='result success';
            resDiv.innerHTML = `✅ 成功！<br>手机号: ${data.phone}<br>API Key: <strong style="font-family:monospace;word-break:break-all;">${data.api_key}</strong><br>剩余次数: ${data.balance}`;
            document.getElementById('phone').value = '';
            loadUsers();
        } else { if (resp.status===401) logout(); resDiv.className='result error'; resDiv.innerHTML=`❌ ${data.detail}`; }
    } catch(e) { resDiv.className='result error'; resDiv.innerHTML=`错误: ${e.message}`; }
}

async function recharge(phone) {
    const token = localStorage.getItem(tokenKey);
    const amount = prompt(`为 ${phone} 充值次数:`, '10');
    if (!amount) return;
    try {
        const resp = await fetch('/admin/recharge', { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded','Authorization':`Bearer ${token}`}, body:new URLSearchParams({phone,amount}) });
        const data = await resp.json();
        if (resp.ok) { alert(`✅ 充值成功！新余额: ${data.new_balance}`); loadUsers(); }
        else { if (resp.status===401) logout(); alert(`❌ ${data.detail}`); }
    } catch(e) { alert(`错误: ${e.message}`); }
}

async function del(phone) {
    const token = localStorage.getItem(tokenKey);
    if (!confirm(`确定删除用户 ${phone} 吗？`)) return;
    try {
        const resp = await fetch('/admin/delete_user', { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded','Authorization':`Bearer ${token}`}, body:new URLSearchParams({phone}) });
        const data = await resp.json();
        if (resp.ok) { alert(`✅ 已删除`); loadUsers(); }
        else { if (resp.status===401) logout(); alert(`❌ ${data.detail}`); }
    } catch(e) { alert(`错误: ${e.message}`); }
}
</script>
</body>
</html>
    ''')

@router.post("/admin/login")
async def admin_login(password: str = Form(...)):
    import config
    if password != config.ADMIN_PASSWORD:
        raise HTTPException(401, detail="密码错误")
    token = auth.create_access_token(data={"sub": "admin", "role": "admin"})
    return {"success": True, "token": token}

@router.post("/admin/add_user")
async def add_user(phone: str = Form(...), balance: int = Form(10), _=Depends(auth.verify_admin_request)):
    if not phone or balance <= 0:
        raise HTTPException(400, detail="参数错误")
    api_key, new_balance = database.add_or_recharge_user(phone, balance)
    return {"success": True, "phone": phone, "api_key": api_key, "balance": new_balance}

@router.post("/admin/recharge")
async def recharge_user(phone: str = Form(...), amount: int = Form(...), _=Depends(auth.verify_admin_request)):
    if amount <= 0:
        raise HTTPException(400, detail="充值次数必须大于0")
    user = database.get_user_by_phone(phone)
    if not user:
        raise HTTPException(404, detail="用户不存在")
    database.users_collection.update_one({"phone": phone}, {"$inc": {"balance": amount}})
    new_user = database.get_user_by_phone(phone)
    return {"success": True, "phone": phone, "added": amount, "new_balance": new_user["balance"]}

@router.post("/admin/delete_user")
async def admin_delete_user(phone: str = Form(...), _=Depends(auth.verify_admin_request)):
    if database.delete_user(phone):
        return {"success": True, "phone": phone}
    raise HTTPException(404, detail="用户不存在")

@router.get("/admin/users")
async def list_users(_=Depends(auth.verify_admin_request)):
    return {"users": database.get_all_users()}