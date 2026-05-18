# admin_routes.py
# 管理后台路由（含日志、统计图表、数据导出）

from fastapi import APIRouter, HTTPException, Depends, Form, Query
from fastapi.responses import HTMLResponse, StreamingResponse
import database
import auth
import json
import csv
from io import StringIO
from datetime import datetime

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
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f0f2f5;padding:20px}
        .container{max-width:1400px;margin:0 auto}
        .card{background:#fff;border-radius:16px;padding:24px;margin-bottom:20px;box-shadow:0 2px 10px rgba(0,0,0,0.1)}
        h1{color:#1e3c72;margin-bottom:24px;border-bottom:2px solid #4a90e2;padding-bottom:12px}
        h2{color:#333;margin-bottom:16px;font-size:18px}
        h3{color:#555;margin-bottom:12px;font-size:16px}
        .login-box{max-width:400px;margin:100px auto}
        .form-group{margin-bottom:16px}
        label{display:block;margin-bottom:6px;color:#333;font-weight:500}
        input,select{width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:14px}
        button{padding:10px 20px;background:#4a90e2;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px}
        button:hover{background:#357abd}
        .result{margin-top:16px;padding:12px;border-radius:8px;display:none}
        .result.success{background:#e8f8f0;border:1px solid #2e7d32;display:block}
        .result.error{background:#ffebee;border:1px solid #c62828;display:block}
        
        /* 用户列表样式 - 强制换行 */
        .user-table{width:100%;border-collapse:collapse;table-layout:fixed}
        .user-table th,.user-table td{padding:10px 8px;text-align:left;border-bottom:1px solid #eee;vertical-align:top}
        .user-table th{background:#f5f5f5;font-weight:600}
        .user-table .api-key-cell{font-family:monospace;font-size:12px;word-break:break-all;white-space:normal}
        .user-table .date-cell{font-size:12px}
        .user-table .balance-cell{text-align:center;font-weight:bold}
        .user-table .actions{white-space:nowrap}
        .user-table .actions button{padding:4px 10px;margin:0 3px;font-size:12px;border-radius:4px;cursor:pointer}
        .user-table .actions .recharge-btn{background:#4a90e2;color:#fff;border:none}
        .user-table .actions .recharge-btn:hover{background:#357abd}
        .user-table .actions .delete-btn{background:#dc3545;color:#fff;border:none}
        .user-table .actions .delete-btn:hover{background:#c82333}
        
        .logout-btn{float:right;background:#6c757d}
        .logout-btn:hover{background:#5a6268}
        .refresh-btn{background:#28a745;float:right;margin-right:10px}
        .refresh-btn:hover{background:#218838}
        .search-box{display:flex;gap:10px;margin:16px 0;align-items:center}
        .search-box input{flex:1;padding:8px;border:1px solid #ddd;border-radius:8px}
        .search-box button{padding:8px 16px;margin:0}
        .stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:20px}
        .stat-card{background:#f8f9fa;border-radius:12px;padding:16px;text-align:center}
        .stat-number{font-size:28px;font-weight:bold;color:#1e3c72}
        .stat-label{color:#666;margin-top:8px}
        .tabs{display:flex;gap:10px;margin-bottom:20px;border-bottom:1px solid #ddd}
        .tab{padding:10px 20px;cursor:pointer;background:none;border:none;font-size:14px}
        .tab.active{color:#4a90e2;border-bottom:2px solid #4a90e2}
        .tab-content{display:none}
        .tab-content.active{display:block}
        .log-table{font-size:12px}
        .log-table td{word-break:break-all}
        .export-box{display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap}
        .export-box .form-group{flex:1;min-width:180px}
        .export-box button{margin:0}
        .date-input{width:100%}
        .copy-btn{background:#28a745;color:#fff;border:none;border-radius:6px;padding:6px 16px;margin-top:8px;cursor:pointer}
        .copy-btn:hover{background:#218838}
    </style>
</head>
<body>
<div id="app"></div>
<script>
var tokenKey = 'admin_token';
if (localStorage.getItem(tokenKey)) { showAdminPanel(); } else { showLoginPage(); }

function showLoginPage() {
    var html = '<div class="login-box"><div class="card"><h1>🔐 管理员登录</h1>';
    html += '<div class="form-group"><label>密码</label><input type="password" id="password"></div>';
    html += '<button onclick="login()">登录</button><div id="loginResult" class="result"></div></div></div>';
    document.getElementById('app').innerHTML = html;
}

async function login() {
    var pwd = document.getElementById('password').value;
    var resDiv = document.getElementById('loginResult');
    if (!pwd) { resDiv.className='result error'; resDiv.innerHTML='❌ 请输入密码'; return; }
    try {
        var resp = await fetch('/admin/login', { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({password:pwd}) });
        var data = await resp.json();
        if (resp.ok) {
            localStorage.setItem(tokenKey, data.token);
            showAdminPanel();
        } else {
            resDiv.className='result error';
            resDiv.innerHTML='❌ 密码错误';
        }
    } catch(e) { resDiv.className='result error'; resDiv.innerHTML='网络错误: ' + e.message; }
}

function logout() { localStorage.removeItem(tokenKey); showLoginPage(); }

async function showAdminPanel() {
    var token = localStorage.getItem(tokenKey);
    var html = '<div class="container"><div class="card"><h1>🔐 用户管理后台 <button class="logout-btn" onclick="logout()">退出登录</button></h1>';
    html += '<div class="tabs"><button class="tab active" onclick="showTab(\'users\')">👥 用户管理</button>';
    html += '<button class="tab" onclick="showTab(\'stats\')">📊 使用统计</button>';
    html += '<button class="tab" onclick="showTab(\'logs\')">📝 操作日志</button>';
    html += '<button class="tab" onclick="showTab(\'export\')">📥 数据导出</button></div>';
    
    // 用户管理标签页
    html += '<div id="tab-users" class="tab-content active">';
    html += '<h2>➕ 添加/充值用户</h2>';
    html += '<div class="form-group"><label>手机号</label><input type="tel" id="phone" placeholder="13812345678"></div>';
    html += '<div class="form-group"><label>充值次数</label><input type="number" id="balance" value="10"></div>';
    html += '<div class="form-group"><label>有效期（天）</label><input type="number" id="days" value="62"><small>0表示永久有效</small></div>';
    html += '<button onclick="addUser()">生成/充值</button><div id="addResult" class="result"></div>';
    html += '<h2 style="margin-top:30px">📋 用户列表</h2>';
    html += '<div class="search-box"><input type="text" id="searchInput" placeholder="输入手机号搜索...">';
    html += '<button onclick="searchUser()">🔍 搜索</button>';
    html += '<button onclick="clearSearch()" class="clear-btn">清除</button>';
    html += '<button onclick="loadUsers()" class="refresh-btn">🔄 刷新</button></div>';
    html += '<div id="userTable">加载中...</div></div>';
    
    // 统计标签页
    html += '<div id="tab-stats" class="tab-content"><div class="stats-grid" id="statsGrid"></div>';
    html += '<canvas id="statsChart" width="400" height="200"></canvas></div>';
    
    // 日志标签页
    html += '<div id="tab-logs" class="tab-content"><div id="logTable">加载中...</div></div>';
    
    // 导出标签页
    html += '<div id="tab-export" class="tab-content">';
    html += '<h2>📥 导出分析数据</h2><div class="export-box">';
    html += '<div class="form-group"><label>起始日期</label><input type="date" id="startDate" class="date-input"></div>';
    html += '<div class="form-group"><label>结束日期</label><input type="date" id="endDate" class="date-input"></div>';
    html += '<div class="form-group"><label>导出格式</label><select id="exportFormat"><option value="json">JSON</option><option value="csv">CSV</option></select></div>';
    html += '<div class="form-group"><button onclick="exportData()">📥 导出数据</button></div></div>';
    html += '<div id="exportResult" class="result"></div>';
    html += '<hr><h3>📊 导出说明</h3><ul><li>• 不选择日期则导出全部数据</li>';
    html += '<li>• 导出内容包含：手机号、报告原始文本、解析时间</li>';
    html += '<li>• JSON格式适合程序处理，CSV格式适合Excel打开</li></ul></div>';
    
    html += '</div></div>';
    document.getElementById('app').innerHTML = html;
    loadUsers();
    loadStats();
    loadLogs();
}

function showTab(tabName) {
    var tabs = document.querySelectorAll('.tab');
    for (var i = 0; i < tabs.length; i++) { tabs[i].classList.remove('active'); }
    var contents = document.querySelectorAll('.tab-content');
    for (var i = 0; i < contents.length; i++) { contents[i].classList.remove('active'); }
    var targetTab = document.querySelector('.tab[onclick="showTab(\'' + tabName + '\')"]');
    if (targetTab) targetTab.classList.add('active');
    var targetContent = document.getElementById('tab-' + tabName);
    if (targetContent) targetContent.classList.add('active');
}

var allUsers = [];
var statsChart = null;

async function loadUsers() {
    var token = localStorage.getItem(tokenKey);
    var tableDiv = document.getElementById('userTable');
    if (!tableDiv) return;
    tableDiv.innerHTML = '加载中...';
    try {
        var resp = await fetch('/admin/users', { headers: {'Authorization': 'Bearer ' + token} });
        if (resp.status === 401) { logout(); return; }
        var data = await resp.json();
        if (!resp.ok) { tableDiv.innerHTML = '<div class="result error">❌ ' + data.detail + '</div>'; return; }
        allUsers = data.users;
        renderUserList(allUsers);
    } catch(e) { tableDiv.innerHTML = '<div class="result error">网络错误: ' + e.message + '</div>'; }
}

function renderUserList(users) {
    var tableDiv = document.getElementById('userTable');
    if (!users || users.length === 0) {
        tableDiv.innerHTML = '<div style="padding:20px;text-align:center;color:#666;">暂无用户</div>';
        return;
    }
    var html = '<table class="user-table"><thead>';
    html += '<tr><th style="width:10%">手机号</th><th style="width:28%">API Key</th>';
    html += '<th style="width:8%">剩余次数</th><th style="width:12%">有效期</th>';
    html += '<th style="width:15%">创建时间</th><th style="width:15%">最后使用</th>';
    html += '<th style="width:12%">操作</th></tr></thead><tbody>';
    for (var i = 0; i < users.length; i++) {
        var u = users[i];
        var created = u.created_at ? new Date(u.created_at).toLocaleString('zh-CN') : '-';
        var lastUsed = u.last_used_at ? new Date(u.last_used_at).toLocaleString('zh-CN') : '未使用';
        var expireAt = u.expire_at ? new Date(u.expire_at).toLocaleString('zh-CN') : '永久';
        var escapedPhone = (u.phone || '').replace(/[&<>]/g, function(m) {
            if (m === '&') return '&amp;';
            if (m === '<') return '&lt;';
            if (m === '>') return '&gt;';
            return m;
        });
        html += '<tr>';
        html += '<td style="word-break:break-all;">' + escapedPhone + '</td>';
        html += '<td class="api-key-cell">' + (u.api_key || '') + '</td>';
        html += '<td class="balance-cell">' + (u.balance || 0) + '</td>';
        html += '<td style="word-break:break-all;">' + expireAt + '</td>';
        html += '<td class="date-cell">' + created + '</td>';
        html += '<td class="date-cell">' + lastUsed + '</td>';
        html += '<td class="actions"><button class="recharge-btn" onclick="recharge(\'' + escapedPhone + '\')">充值</button>';
        html += '<button class="delete-btn" onclick="del(\'' + escapedPhone + '\')">删除</button></td></table>';
    }
    html += '</tbody></table>';
    tableDiv.innerHTML = html;
}

function searchUser() {
    var keyword = document.getElementById('searchInput').value.trim().toLowerCase();
    if (!keyword) { renderUserList(allUsers); return; }
    var filtered = [];
    for (var i = 0; i < allUsers.length; i++) {
        if (allUsers[i].phone && allUsers[i].phone.toLowerCase().includes(keyword)) {
            filtered.push(allUsers[i]);
        }
    }
    renderUserList(filtered);
}

function clearSearch() {
    document.getElementById('searchInput').value = '';
    renderUserList(allUsers);
}

// 复制新用户信息
function copyNewUserInfo(phone, apiKey, balance) {
    var text = '手机号：' + phone + '\\nAPI Key：' + apiKey + '\\n剩余次数：' + balance + '次\\n有效期：62天\\n\\n请在首页使用手机号和API Key登录分析';
    navigator.clipboard.writeText(text).then(function() {
        alert('✅ 已复制用户信息到剪贴板');
    }).catch(function() {
        alert('❌ 复制失败，请手动复制');
    });
}

async function addUser() {
    var token = localStorage.getItem(tokenKey);
    var phone = document.getElementById('phone').value;
    var balance = document.getElementById('balance').value;
    var days = document.getElementById('days').value;
    var resDiv = document.getElementById('addResult');
    if (!phone) { resDiv.className='result error'; resDiv.innerHTML='❌ 请填写手机号'; return; }
    try {
        var resp = await fetch('/admin/add_user', {
            method:'POST',
            headers:{'Content-Type':'application/x-www-form-urlencoded','Authorization':'Bearer ' + token},
            body:new URLSearchParams({phone: phone, balance: balance, days: days})
        });
        var data = await resp.json();
        if (resp.ok) {
            resDiv.className='result success';
            var copyBtn = '<button class="copy-btn" onclick="copyNewUserInfo(\\'' + data.phone + '\\', \\'' + data.api_key + '\\', ' + data.balance + ')">📋 复制信息</button>';
            resDiv.innerHTML = '✅ 成功！<br>手机号: ' + data.phone + '<br>API Key: <strong style="font-family:monospace;word-break:break-all;">' + data.api_key + '</strong><br>剩余次数: ' + data.balance + '<br><br>' + copyBtn;
            document.getElementById('phone').value = '';
            loadUsers();
            loadStats();
            loadLogs();
        } else {
            if (resp.status===401) logout();
            resDiv.className='result error';
            resDiv.innerHTML='❌ ' + (data.detail || '添加失败');
        }
    } catch(e) { resDiv.className='result error'; resDiv.innerHTML='错误: ' + e.message; }
}

async function recharge(phone) {
    var token = localStorage.getItem(tokenKey);
    var amount = prompt('为 ' + phone + ' 充值次数:', '10');
    if (!amount) return;
    try {
        var resp = await fetch('/admin/recharge', {
            method:'POST',
            headers:{'Content-Type':'application/x-www-form-urlencoded','Authorization':'Bearer ' + token},
            body:new URLSearchParams({phone: phone, amount: amount})
        });
        var data = await resp.json();
        if (resp.ok) {
            alert('✅ 充值成功！新余额: ' + data.new_balance);
            loadUsers();
            loadStats();
            loadLogs();
        } else {
            if (resp.status===401) logout();
            alert('❌ ' + (data.detail || '充值失败'));
        }
    } catch(e) { alert('错误: ' + e.message); }
}

async function del(phone) {
    var token = localStorage.getItem(tokenKey);
    if (!confirm('确定删除用户 ' + phone + ' 吗？')) return;
    try {
        var resp = await fetch('/admin/delete_user', {
            method:'POST',
            headers:{'Content-Type':'application/x-www-form-urlencoded','Authorization':'Bearer ' + token},
            body:new URLSearchParams({phone: phone})
        });
        var data = await resp.json();
        if (resp.ok) {
            alert('✅ 已删除');
            loadUsers();
            loadStats();
            loadLogs();
        } else {
            if (resp.status===401) logout();
            alert('❌ ' + (data.detail || '删除失败'));
        }
    } catch(e) { alert('错误: ' + e.message); }
}

async function loadStats() {
    var token = localStorage.getItem(tokenKey);
    try {
        var resp = await fetch('/admin/stats', { headers: {'Authorization': 'Bearer ' + token} });
        if (resp.status === 401) { logout(); return; }
        var data = await resp.json();
        var statsGrid = document.getElementById('statsGrid');
        statsGrid.innerHTML = '<div class="stat-card"><div class="stat-number">' + data.userStats.total + '</div><div class="stat-label">总用户数</div></div>';
        statsGrid.innerHTML += '<div class="stat-card"><div class="stat-number">' + data.userStats.total_balance + '</div><div class="stat-label">总剩余次数</div></div>';
        statsGrid.innerHTML += '<div class="stat-card"><div class="stat-number">' + data.totalCalls + '</div><div class="stat-label">总调用次数</div></div>';
        statsGrid.innerHTML += '<div class="stat-card"><div class="stat-number">' + (data.todayVisits || 0) + '</div><div class="stat-label">今日访问量</div></div>';
        statsGrid.innerHTML += '<div class="stat-card"><div class="stat-number">' + (data.totalVisits || 0) + '</div><div class="stat-label">全部访问量</div></div>';
        
        if (statsChart) statsChart.destroy();
        var ctx = document.getElementById('statsChart').getContext('2d');
        statsChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.chartLabels,
                datasets: [{
                    label: '每日调用次数',
                    data: data.chartData,
                    borderColor: '#4a90e2',
                    backgroundColor: 'rgba(74,144,226,0.1)',
                    fill: true
                }]
            },
            options: { responsive: true, maintainAspectRatio: true }
        });
    } catch(e) { console.error(e); }
}

async function loadLogs() {
    var token = localStorage.getItem(tokenKey);
    var logDiv = document.getElementById('logTable');
    if (!logDiv) return;
    logDiv.innerHTML = '加载中...';
    try {
        var resp = await fetch('/admin/logs', { headers: {'Authorization': 'Bearer ' + token} });
        if (resp.status === 401) { logout(); return; }
        var data = await resp.json();
        if (!data.logs || data.logs.length === 0) {
            logDiv.innerHTML = '<div style="padding:20px;text-align:center;color:#666;">暂无操作日志</div>';
            return;
        }
        var html = '<table class="log-table"><thead><tr><th>时间</th><th>操作人</th><th>操作</th><th>目标</th><th>详情</th></tr></thead><tbody>';
        for (var i = 0; i < data.logs.length; i++) {
            var log = data.logs[i];
            var time = log.created_at ? new Date(log.created_at).toLocaleString('zh-CN') : '-';
            html += '<tr><td style="padding:8px;">' + time + '</td><td style="padding:8px;">' + (log.admin || '-') + '</td><td style="padding:8px;">' + (log.action || '-') + '</td><td style="padding:8px;">' + (log.target || '-') + '</td><td style="padding:8px;">' + (log.details || '-') + '</td></tr>';
        }
        html += '</tbody></td>';
        logDiv.innerHTML = html;
    } catch(e) { logDiv.innerHTML = '<div class="result error">加载失败: ' + e.message + '</div>'; }
}

async function exportData() {
    var token = localStorage.getItem(tokenKey);
    var startDate = document.getElementById('startDate').value;
    var endDate = document.getElementById('endDate').value;
    var format = document.getElementById('exportFormat').value;
    var resultDiv = document.getElementById('exportResult');
    var url = '/admin/export_raw_reports?format=' + format;
    if (startDate) url += '&start_date=' + startDate;
    if (endDate) url += '&end_date=' + endDate;
    resultDiv.className = 'result';
    resultDiv.innerHTML = '⏳ 正在导出数据，请稍候...';
    resultDiv.style.display = 'block';
    try {
        var resp = await fetch(url, { headers: {'Authorization': 'Bearer ' + token} });
        if (resp.status === 401) { logout(); return; }
        if (!resp.ok) {
            var error = await resp.json();
            resultDiv.className = 'result error';
            resultDiv.innerHTML = '❌ 导出失败: ' + (error.detail || '未知错误');
            return;
        }
        var blob = await resp.blob();
        var downloadUrl = window.URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = downloadUrl;
        var filename = 'raw_reports_' + new Date().toISOString().slice(0,19).replace(/:/g, '-') + (format === 'csv' ? '.csv' : '.json');
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(downloadUrl);
        resultDiv.className = 'result success';
        resultDiv.innerHTML = '✅ 导出成功！文件已下载: ' + filename;
        setTimeout(function() { resultDiv.style.display = 'none'; }, 3000);
    } catch(e) {
        resultDiv.className = 'result error';
        resultDiv.innerHTML = '❌ 网络错误: ' + e.message;
    }
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
async def add_user(phone: str = Form(...), balance: int = Form(10), days: int = Form(62), _=Depends(auth.verify_admin_request)):
    if not phone or balance <= 0:
        raise HTTPException(400, detail="参数错误")
    api_key, new_balance = database.add_or_recharge_user(phone, balance, days)
    database.add_admin_log("admin", "add_user", phone, f"充值{balance}次，有效期{days}天")
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
    database.add_admin_log("admin", "recharge", phone, f"充值{amount}次")
    return {"success": True, "phone": phone, "added": amount, "new_balance": new_user["balance"]}


@router.post("/admin/delete_user")
async def admin_delete_user(phone: str = Form(...), _=Depends(auth.verify_admin_request)):
    if database.delete_user(phone):
        database.add_admin_log("admin", "delete_user", phone, "删除用户")
        return {"success": True, "phone": phone}
    raise HTTPException(404, detail="用户不存在")


@router.get("/admin/users")
async def list_users(_=Depends(auth.verify_admin_request)):
    return {"users": database.get_all_users()}


@router.get("/admin/stats")
async def get_stats(_=Depends(auth.verify_admin_request)):
    user_stats = database.get_user_stats()
    usage_stats = database.get_usage_stats(30)
    total_calls = sum(s.get("total_calls", 0) for s in usage_stats)
    chart_labels = [s.get("date", "") for s in usage_stats]
    chart_data = [s.get("total_calls", 0) for s in usage_stats]
    
    # 获取访问统计
    today_visits = database.get_today_visits()
    total_visits = database.get_total_visits()
    
    return {
        "userStats": user_stats,
        "totalCalls": total_calls,
        "chartLabels": chart_labels,
        "chartData": chart_data,
        "todayVisits": today_visits,
        "totalVisits": total_visits
    }


@router.get("/admin/logs")
async def get_logs(_=Depends(auth.verify_admin_request)):
    return {"logs": database.get_admin_logs(100)}


# ========== 数据导出接口 ==========
@router.get("/admin/export_raw_reports")
async def export_raw_reports(
    start_date: str = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: str = Query(None, description="结束日期 YYYY-MM-DD"),
    format: str = Query("json", description="导出格式 json/csv"),
    _=Depends(auth.verify_admin_request)
):
    if database.db is None:
        raise HTTPException(500, detail="数据库未连接")
    
    raw_collection = database.db["raw_reports"]
    
    query = {}
    if start_date or end_date:
        date_filter = {}
        if start_date:
            try:
                start = datetime.strptime(start_date, "%Y-%m-%d")
                date_filter["$gte"] = start
            except:
                pass
        if end_date:
            try:
                end = datetime.strptime(end_date, "%Y-%m-%d")
                end = end.replace(hour=23, minute=59, second=59)
                date_filter["$lte"] = end
            except:
                pass
        if date_filter:
            query["created_at"] = date_filter
    
    cursor = raw_collection.find(query, {"_id": 0}).sort("created_at", -1)
    reports = list(cursor)
    
    if not reports:
        raise HTTPException(404, detail="未找到符合条件的数据")
    
    for r in reports:
        if "created_at" in r and isinstance(r["created_at"], datetime):
            r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
    
    if format.lower() == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["手机号", "解析时间", "报告文本长度", "报告文本摘要"])
        for r in reports:
            raw_text = r.get("raw_text", "")
            writer.writerow([
                r.get("phone", ""),
                r.get("created_at", ""),
                len(raw_text),
                raw_text[:200] + "..." if len(raw_text) > 200 else raw_text
            ])
        
        return StreamingResponse(
            iter([output.getvalue().encode('utf-8-sig')]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=raw_reports_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    else:
        json_str = json.dumps(reports, ensure_ascii=False, indent=2)
        return StreamingResponse(
            iter([json_str.encode('utf-8')]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=raw_reports_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"}
        )