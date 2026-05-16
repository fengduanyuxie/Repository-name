# admin_routes.py
# 管理后台路由（含日志、统计图表、数据导出、访问统计）

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
        .login-box{max-width:400px;margin:100px auto}
        .form-group{margin-bottom:16px}
        label{display:block;margin-bottom:6px;color:#333;font-weight:500}
        input,select{width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:14px}
        button{padding:10px 20px;background:#4a90e2;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px}
        button:hover{background:#357abd}
        .result{margin-top:16px;padding:12px;border-radius:8px;display:none}
        .result.success{background:#e8f8f0;border:1px solid #2e7d32;display:block}
        .result.error{background:#ffebee;border:1px solid #c62828;display:block}
        table{width:100%;border-collapse:collapse;margin-top:16px}
        th,td{padding:12px;text-align:left;border-bottom:1px solid #eee}
        th{background:#f5f5f5;font-weight:600}
        .danger{background:#dc3545}
        .danger:hover{background:#c82333}
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
        .tabs{display:flex;gap:10px;margin-bottom:20px;border-bottom:1px solid #ddd;flex-wrap:wrap}
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
                <div class="tabs">
                    <button class="tab active" onclick="showTab('users')">👥 用户管理</button>
                    <button class="tab" onclick="showTab('stats')">📊 使用统计</button>
                    <button class="tab" onclick="showTab('logs')">📝 操作日志</button>
                    <button class="tab" onclick="showTab('export')">📥 数据导出</button>
                </div>
                <div id="tab-users" class="tab-content active">
                    <h2>➕ 添加/充值用户</h2>
                    <div class="form-group"><label>手机号</label><input type="tel" id="phone" placeholder="13812345678"></div>
                    <div class="form-group"><label>充值次数</label><input type="number" id="balance" value="10"></div>
                    <div class="form-group"><label>有效期（天）</label><input type="number" id="days" value="62"><small style="color:#999">0表示永久有效</small></div>
                    <button onclick="addUser()">生成/充值</button>
                    <div id="addResult" class="result"></div>
                    
                    <h2 style="margin-top:30px">📋 用户列表</h2>
                    <div class="search-box">
                        <input type="text" id="searchInput" placeholder="输入手机号搜索...">
                        <button onclick="searchUser()">🔍 搜索</button>
                        <button onclick="clearSearch()" class="clear-btn" style="background:#6c757d">清除</button>
                        <button onclick="loadUsers()" class="refresh-btn" style="float:none; margin:0">🔄 刷新</button>
                    </div>
                    <div id="userTable">加载中...</div>
                </div>
                <div id="tab-stats" class="tab-content">
                    <div class="stats-grid" id="statsGrid"></div>
                    <canvas id="statsChart" width="400" height="200"></canvas>
                </div>
                <div id="tab-logs" class="tab-content">
                    <div id="logTable">加载中...</div>
                </div>
                <div id="tab-export" class="tab-content">
                    <h2>📥 导出分析数据</h2>
                    <div class="export-box">
                        <div class="form-group">
                            <label>起始日期</label>
                            <input type="date" id="startDate" class="date-input">
                        </div>
                        <div class="form-group">
                            <label>结束日期</label>
                            <input type="date" id="endDate" class="date-input">
                        </div>
                        <div class="form-group">
                            <label>导出格式</label>
                            <select id="exportFormat">
                                <option value="json">JSON</option>
                                <option value="csv">CSV</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <button onclick="exportData()" style="background:#28a745">📥 导出数据</button>
                        </div>
                    </div>
                    <div id="exportResult" class="result"></div>
                    <hr style="margin:20px 0">
                    <h3>📊 导出说明</h3>
                    <ul style="color:#666;font-size:13px;line-height:1.8">
                        <li>• 不选择日期则导出全部数据</li>
                        <li>• 导出内容包含：手机号、报告原始文本、解析时间</li>
                        <li>• JSON格式适合程序处理，CSV格式适合Excel打开</li>
                    </ul>
                </div>
            </div>
        </div>`;
    loadUsers();
    loadStats();
    loadLogs();
}

function showTab(tabName) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.querySelector(`.tab[onclick="showTab('${tabName}')"]`).classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');
}

let allUsers = [];
let statsChart = null;

async function loadUsers() {
    const token = localStorage.getItem(tokenKey);
    const tableDiv = document.getElementById('userTable');
    if (!tableDiv) return;
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
            '<th>手机号</th><th>API Key</th><th>剩余次数</th><th>有效期</th><th>创建时间</th><th>最后使用</th><th>操作</th>' +
            '</table></thead><tbody>';
    for (const u of users) {
        const created = u.created_at ? new Date(u.created_at).toLocaleString('zh-CN') : '-';
        const lastUsed = u.last_used_at ? new Date(u.last_used_at).toLocaleString('zh-CN') : '未使用';
        const expireAt = u.expire_at ? new Date(u.expire_at).toLocaleString('zh-CN') : '永久';
        const escapedPhone = (u.phone || '').replace(/[&<>]/g, function(m) {
            if (m === '&') return '&amp;';
            if (m === '<') return '&lt;';
            if (m === '>') return '&gt;';
            return m;
        });
        html += `<tr>
            <td style="padding:12px;">${escapedPhone}</td>
            <td style="padding:12px;font-family:monospace;font-size:12px;word-break:break-all;">${u.api_key || ''}</td>
            <td style="padding:12px;text-align:center;font-weight:bold;">${u.balance || 0}</td>
            <td style="padding:12px;">${expireAt}</td>
            <td style="padding:12px;">${created}</td>
            <td style="padding:12px;">${lastUsed}</td>
            <td style="padding:12px;">
                <button onclick="recharge('${escapedPhone}')">充值</button>
                <button onclick="del('${escapedPhone}')" style="background:#dc3545">删除</button>
            </td>
        </tr>`;
    }
    html += '</tbody></table>';
    tableDiv.innerHTML = html;
}

function searchUser() {
    const keyword = document.getElementById('searchInput').value.trim().toLowerCase();
    if (!keyword) { renderUserList(allUsers); return; }
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
    const days = document.getElementById('days').value;
    const resDiv = document.getElementById('addResult');
    if (!phone) { resDiv.className='result error'; resDiv.innerHTML='❌ 请填写手机号'; return; }
    try {
        const resp = await fetch('/admin/add_user', { 
            method:'POST', 
            headers:{'Content-Type':'application/x-www-form-urlencoded','Authorization':`Bearer ${token}`}, 
            body:new URLSearchParams({phone, balance, days}) 
        });
        const data = await resp.json();
        if (resp.ok) {
            resDiv.className='result success';
            resDiv.innerHTML = `✅ 成功！<br>手机号: ${data.phone}<br>API Key: <strong style="font-family:monospace;word-break:break-all;">${data.api_key}</strong><br>剩余次数: ${data.balance}`;
            document.getElementById('phone').value = '';
            loadUsers();
            loadStats();
            loadLogs();
        } else { if (resp.status===401) logout(); resDiv.className='result error'; resDiv.innerHTML=`❌ ${data.detail}`; }
    } catch(e) { resDiv.className='result error'; resDiv.innerHTML=`错误: ${e.message}`; }
}

async function recharge(phone) {
    const token = localStorage.getItem(tokenKey);
    const amount = prompt(`为 ${phone} 充值次数:`, '10');
    if (!amount) return;
    try {
        const resp = await fetch('/admin/recharge', { 
            method:'POST', 
            headers:{'Content-Type':'application/x-www-form-urlencoded','Authorization':`Bearer ${token}`}, 
            body:new URLSearchParams({phone, amount}) 
        });
        const data = await resp.json();
        if (resp.ok) { 
            alert(`✅ 充值成功！新余额: ${data.new_balance}`); 
            loadUsers();
            loadStats();
            loadLogs();
        } else { if (resp.status===401) logout(); alert(`❌ ${data.detail}`); }
    } catch(e) { alert(`错误: ${e.message}`); }
}

async function del(phone) {
    const token = localStorage.getItem(tokenKey);
    if (!confirm(`确定删除用户 ${phone} 吗？`)) return;
    try {
        const resp = await fetch('/admin/delete_user', { 
            method:'POST', 
            headers:{'Content-Type':'application/x-www-form-urlencoded','Authorization':`Bearer ${token}`}, 
            body:new URLSearchParams({phone}) 
        });
        const data = await resp.json();
        if (resp.ok) { 
            alert(`✅ 已删除`); 
            loadUsers();
            loadStats();
            loadLogs();
        } else { if (resp.status===401) logout(); alert(`❌ ${data.detail}`); }
    } catch(e) { alert(`错误: ${e.message}`); }
}

async function loadStats() {
    const token = localStorage.getItem(tokenKey);
    try {
        const resp = await fetch('/admin/stats', { headers: {'Authorization': `Bearer ${token}`} });
        if (resp.status === 401) { logout(); return; }
        const data = await resp.json();
        
        const statsGrid = document.getElementById('statsGrid');
        statsGrid.innerHTML = `
            <div class="stat-card"><div class="stat-number">${data.userStats.total}</div><div class="stat-label">总用户数</div></div>
            <div class="stat-card"><div class="stat-number">${data.userStats.total_balance}</div><div class="stat-label">总剩余次数</div></div>
            <div class="stat-card"><div class="stat-number">${data.totalCalls}</div><div class="stat-label">总调用次数</div></div>
            <div class="stat-card"><div class="stat-number">${data.todayVisits || 0}</div><div class="stat-label">今日访问量</div></div>
            <div class="stat-card"><div class="stat-number">${data.totalVisits || 0}</div><div class="stat-label">全部访问量</div></div>
        `;
        
        if (statsChart) statsChart.destroy();
        const ctx = document.getElementById('statsChart').getContext('2d');
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
    const token = localStorage.getItem(tokenKey);
    const logDiv = document.getElementById('logTable');
    if (!logDiv) return;
    logDiv.innerHTML = '加载中...';
    try {
        const resp = await fetch('/admin/logs', { headers: {'Authorization': `Bearer ${token}`} });
        if (resp.status === 401) { logout(); return; }
        const data = await resp.json();
        if (!data.logs || data.logs.length === 0) {
            logDiv.innerHTML = '<div style="padding:20px;text-align:center;color:#666;">暂无操作日志</div>';
            return;
        }
        let html = '<table class="log-table"><thead><tr><th>时间</th><th>操作人</th><th>操作</th><th>目标</th><th>详情</th></tr></thead><tbody>';
        for (const log of data.logs) {
            const time = log.created_at ? new Date(log.created_at).toLocaleString('zh-CN') : '-';
            html += `<tr>
                <td style="padding:8px;">${time}</td>
                <td style="padding:8px;">${log.admin || '-'}</td>
                <td style="padding:8px;">${log.action || '-'}</td>
                <td style="padding:8px;">${log.target || '-'}</td>
                <td style="padding:8px;">${log.details || '-'}</td>
            </tr>`;
        }
        html += '</tbody><table>';
        logDiv.innerHTML = html;
    } catch(e) { logDiv.innerHTML = `<div class="result error">加载失败: ${e.message}</div>`; }
}

async function exportData() {
    const token = localStorage.getItem(tokenKey);
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    const format = document.getElementById('exportFormat').value;
    const resultDiv = document.getElementById('exportResult');
    
    let url = `/admin/export_raw_reports?format=${format}`;
    if (startDate) url += `&start_date=${startDate}`;
    if (endDate) url += `&end_date=${endDate}`;
    
    resultDiv.className = 'result';
    resultDiv.innerHTML = '⏳ 正在导出数据，请稍候...';
    resultDiv.style.display = 'block';
    
    try {
        const resp = await fetch(url, { headers: {'Authorization': `Bearer ${token}`} });
        if (resp.status === 401) { logout(); return; }
        if (!resp.ok) {
            const error = await resp.json();
            resultDiv.className = 'result error';
            resultDiv.innerHTML = `❌ 导出失败: ${error.detail || '未知错误'}`;
            return;
        }
        
        const blob = await resp.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        const filename = `raw_reports_${new Date().toISOString().slice(0,19).replace(/:/g, '-')}.${format === 'csv' ? 'csv' : 'json'}`;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(downloadUrl);
        
        resultDiv.className = 'result success';
        resultDiv.innerHTML = `✅ 导出成功！文件已下载: ${filename}`;
        setTimeout(() => { resultDiv.style.display = 'none'; }, 3000);
    } catch(e) {
        resultDiv.className = 'result error';
        resultDiv.innerHTML = `❌ 网络错误: ${e.message}`;
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