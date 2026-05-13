# main.py
# 征信报告分析系统 - 主入口（模块化版本 v051214）

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn
import os

import database
from api_routes import router as api_router
from admin_routes import router as admin_router

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 初始化数据库
database.init_db()

# 注册路由
app.include_router(api_router)
app.include_router(admin_router)


# 前端页面
@app.get("/")
async def frontend():
    return HTMLResponse(content='''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <title>征信报告分析系统</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f7fa;padding:16px}
        .container{max-width:600px;margin:0 auto;background:#fff;border-radius:24px;padding:20px;box-shadow:0 4px 20px rgba(0,0,0,0.08)}
        h1{color:#1e3c72;border-bottom:3px solid #4a90e2;padding-bottom:12px;margin-bottom:16px;font-size:22px}
        .desc{color:#666;font-size:14px;margin-bottom:20px;line-height:1.6}
        .desc strong{color:#1e3c72;font-weight:700}
        .auth-box{background:#f0f2f5;border-radius:12px;padding:16px;margin-bottom:20px}
        .auth-box input{width:100%;padding:10px;margin-bottom:10px;border:1px solid #ddd;border-radius:8px;font-size:14px}
        .remember-row{display:flex;justify-content:space-between;align-items:center;margin-top:8px}
        .remember-row label{display:flex;align-items:center;gap:6px;font-size:12px;color:#666;cursor:pointer}
        .clear-btn{background:none;border:none;color:#dc3545;font-size:12px;cursor:pointer}
        .upload-area{border:2px dashed #4a90e2;border-radius:20px;padding:30px 20px;text-align:center;cursor:pointer;margin:16px 0;transition:all 0.3s}
        .upload-area:hover{background:#eef4ff;border-color:#357abd}
        .upload-icon{font-size:48px;margin-bottom:12px}
        .file-name{color:#2e7d32;font-size:14px;margin-top:8px}
        .progress-container{display:none;margin-top:16px}
        .progress-bar{background:#e0e0e0;border-radius:20px;height:8px;overflow:hidden}
        .progress-fill{background:#4a90e2;width:0%;height:100%;transition:width 0.3s}
        .progress-text{text-align:center;font-size:12px;color:#666;margin-top:8px}
        .button-group{display:flex;gap:12px;margin-top:8px}
        .button-group button{flex:1;margin-top:0}
        button{background:#4a90e2;color:#fff;border:none;padding:14px 28px;border-radius:40px;font-size:16px;font-weight:500;cursor:pointer}
        button:hover{background:#357abd}
        button:disabled{background:#ccc;cursor:not-allowed}
        .btn-recharge{background:#28a745}
        .btn-recharge:hover{background:#218838}
        .loading{display:none;text-align:center;margin:24px 0;color:#4a90e2}
        .result-container{display:none;margin-top:24px}
        .result-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px}
        .font-controls{display:flex;gap:8px}
        .font-controls button{padding:4px 12px;font-size:12px;width:auto;background:#e0e0e0;color:#333}
        .font-controls button:hover{background:#ccc}
        .result{background:#f9f9f9;border-radius:16px;padding:16px;font-family:monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;max-height:500px;overflow:auto;border:1px solid #e0e0e0}
        .info-note{background:#e8f4fd;padding:12px;border-radius:12px;margin-top:20px;font-size:12px;color:#4a90e2;text-align:center}
        .copy-success{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#28a745;color:#fff;padding:10px 20px;border-radius:40px;font-size:14px;z-index:1000;display:none}
        
        /* Toast 提示 */
        .toast{position:fixed;top:20px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:12px 24px;border-radius:40px;font-size:14px;z-index:2000;display:none;white-space:nowrap}
        .toast.success{background:#28a745}
        .toast.error{background:#dc3545}
        .toast.info{background:#17a2b8}
        
        /* 引导浮层 */
        .tour-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:3000;display:none}
        .tour-card{position:absolute;background:#fff;border-radius:16px;padding:20px;max-width:280px;box-shadow:0 4px 20px rgba(0,0,0,0.2)}
        .tour-card h4{margin-bottom:8px;color:#1e3c72}
        .tour-card p{margin-bottom:12px;font-size:14px;color:#666}
        .tour-buttons{display:flex;gap:8px;justify-content:flex-end}
        .tour-buttons button{padding:6px 16px;font-size:12px;width:auto}
        
        /* 二维码弹窗 */
        .qrcode-modal{display:none;position:fixed;z-index:4000;left:0;top:0;width:100%;height:100%;background:rgba(0,0,0,0.5);justify-content:center;align-items:center}
        .qrcode-content{background:#fff;border-radius:16px;padding:24px;text-align:center;max-width:280px;width:90%}
        .qrcode-content img{width:100%;max-width:200px;border-radius:12px}
        .qrcode-content p{margin-top:12px;color:#666}
    </style>
</head>
<body>
<div class="container">
    <h1>📄 征信结构解读</h1>
    <p class="desc">请上传个人<strong>简版</strong>信用报告（PDF）。</p>
    
    <div class="auth-box">
        <input type="tel" id="phone" placeholder="手机号" autocomplete="off">
        <input type="text" id="apiKey" placeholder="API Key" autocomplete="off">
        <div class="remember-row">
            <label>
                <input type="checkbox" id="rememberMe"> 记住我
            </label>
            <button id="clearRememberBtn" class="clear-btn">清除记录</button>
        </div>
    </div>
    
    <div class="upload-area" id="uploadArea">
        <div class="upload-icon">📎</div>
        <div class="upload-text">点击或拖拽上传PDF文件</div>
        <div class="file-name" id="fileName"></div>
        <input type="file" id="fileInput" accept=".pdf" style="display:none">
    </div>
    
    <div class="progress-container" id="progressContainer">
        <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
        <div class="progress-text" id="progressText">准备上传...</div>
    </div>
    
    <div class="button-group">
        <button id="analyzeBtn" disabled>开始分析</button>
        <button id="rechargeBtn" class="btn-recharge">💰 充值</button>
    </div>
    
    <div class="loading" id="loading">正在为您分析，请稍候...</div>
    <div class="result-container" id="resultContainer">
        <div class="result-header">
            <span style="font-size:14px;font-weight:500;">📋 分析结果</span>
            <div class="font-controls">
                <button id="fontSmall">A⁻</button>
                <button id="fontMedium">A</button>
                <button id="fontLarge">A⁺</button>
                <button id="copyBtn" style="display:none;background:#17a2b8;width:auto;padding:8px 16px;">📋 复制</button>
            </div>
        </div>
        <div class="result" id="result"></div>
    </div>
    <div class="info-note">
        💡 API Key获取请联系管理员 <a href="javascript:void(0)" id="showWechatQrcode" style="color:#4a90e2;text-decoration:underline;">📱 点击添加微信</a>
    </div>
</div>
<div id="copySuccess" class="copy-success">✅ 已复制到剪贴板</div>

<!-- Toast -->
<div id="toast" class="toast"></div>

<!-- 引导浮层 -->
<div id="tourOverlay" class="tour-overlay">
    <div id="tourCard" class="tour-card">
        <h4 id="tourTitle">🔐 已有账号？</h4>
        <p id="tourDesc">在此输入您的手机号和API Key，新用户请点击下方“充值”按钮获取API Key</p>
        <div class="tour-buttons">
            <button id="tourNextBtn">下一步</button>
            <button id="tourSkipBtn">跳过</button>
        </div>
    </div>
</div>

<!-- 二维码弹窗 -->
<div id="qrcodeModal" class="qrcode-modal">
    <div class="qrcode-content">
        <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAMAAAADACAYAAABS3GwHAAAACXBIWXMAAAsTAAALEwEAmpwYAAAEiUlEQVR4nO3dQW7bMBQG4Vn2Hnvvsfcee+...（Base64编码）" alt="管理员微信二维码">
        <p>微信扫码添加管理员</p>
        <p style="font-size:12px;color:#999">微信号：DXNBZ579</p>
        <button onclick="closeQrcodeModal()" style="margin-top:16px;padding:8px 20px;background:#4a90e2;color:#fff;border:none;border-radius:20px;cursor:pointer">关闭</button>
    </div>
</div>

<script>
    // DOM 元素
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const rechargeBtn = document.getElementById('rechargeBtn');
    const loadingDiv = document.getElementById('loading');
    const resultDiv = document.getElementById('result');
    const resultContainer = document.getElementById('resultContainer');
    const fileNameSpan = document.getElementById('fileName');
    const phoneInput = document.getElementById('phone');
    const apiKeyInput = document.getElementById('apiKey');
    const copyBtn = document.getElementById('copyBtn');
    const copySuccess = document.getElementById('copySuccess');
    const rememberCheckbox = document.getElementById('rememberMe');
    const clearRememberBtn = document.getElementById('clearRememberBtn');
    const progressContainer = document.getElementById('progressContainer');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    
    let selectedFile = null;
    let currentReport = '';
    let currentTempId = null;
    
    // ========== 字体大小控制 ==========
    const fontSizes = {small: '12px', medium: '14px', large: '16px'};
    let currentFont = localStorage.getItem('reportFont') || 'medium';
    function applyFont() { resultDiv.style.fontSize = fontSizes[currentFont]; }
    document.getElementById('fontSmall').onclick = () => { currentFont = 'small'; applyFont(); localStorage.setItem('reportFont', 'small'); showToast('字号已调整为小', 'info'); };
    document.getElementById('fontMedium').onclick = () => { currentFont = 'medium'; applyFont(); localStorage.setItem('reportFont', 'medium'); showToast('字号已调整为中', 'info'); };
    document.getElementById('fontLarge').onclick = () => { currentFont = 'large'; applyFont(); localStorage.setItem('reportFont', 'large'); showToast('字号已调整为大', 'info'); };
    applyFont();
    
    // ========== Toast 提示 ==========
    function showToast(message, type = 'info') {
        const toast = document.getElementById('toast');
        toast.textContent = message;
        toast.className = `toast ${type}`;
        toast.style.display = 'block';
        setTimeout(() => { toast.style.display = 'none'; }, 3000);
    }
    
    // ========== 记住我功能 ==========
    function loadSavedCredentials() {
        const savedPhone = localStorage.getItem('saved_phone');
        const savedApiKey = localStorage.getItem('saved_api_key');
        if (savedPhone && savedApiKey) {
            phoneInput.value = savedPhone;
            apiKeyInput.value = savedApiKey;
            rememberCheckbox.checked = true;
        }
    }
    function saveCredentials() {
        if (rememberCheckbox.checked) {
            localStorage.setItem('saved_phone', phoneInput.value.trim());
            localStorage.setItem('saved_api_key', apiKeyInput.value.trim());
        } else {
            localStorage.removeItem('saved_phone');
            localStorage.removeItem('saved_api_key');
        }
    }
    clearRememberBtn.onclick = () => {
        localStorage.removeItem('saved_phone');
        localStorage.removeItem('saved_api_key');
        phoneInput.value = '';
        apiKeyInput.value = '';
        rememberCheckbox.checked = false;
        showToast('已清除保存的账号信息', 'info');
    };
    loadSavedCredentials();
    
    // ========== 进度条模拟 ==========
    let progressInterval = null;
    function startProgress(steps = ['上传中...', '解析PDF中...', '生成报告中...']) {
        progressContainer.style.display = 'block';
        let percent = 0;
        progressInterval = setInterval(() => {
            if (percent >= 90) { clearInterval(progressInterval); return; }
            percent += Math.random() * 15;
            if (percent > 90) percent = 90;
            progressFill.style.width = percent + '%';
            const stepIndex = Math.floor(percent / 30);
            progressText.textContent = steps[Math.min(stepIndex, steps.length - 1)] || '处理中...';
        }, 500);
    }
    function completeProgress() {
        if (progressInterval) clearInterval(progressInterval);
        progressFill.style.width = '100%';
        progressText.textContent = '完成！';
        setTimeout(() => { progressContainer.style.display = 'none'; }, 1000);
    }
    function resetProgress() { if (progressInterval) clearInterval(progressInterval); progressContainer.style.display = 'none'; progressFill.style.width = '0%'; }
    
    // ========== 首次引导 ==========
    const hasVisited = localStorage.getItem('has_visited');
    if (!hasVisited) {
        setTimeout(() => { startTour(); }, 500);
        localStorage.setItem('has_visited', 'true');
    }
    let tourStep = 0;
    const tourSteps = [
        { element: '.auth-box', title: '🔐 已有账号？', desc: '在此输入您的手机号和API Key。新用户请点击下方“充值”按钮获取API Key。', position: 'top' },
        { element: '.upload-area', title: '📄 上传报告', desc: '点击或拖拽上传PDF格式的个人简版信用报告。', position: 'bottom' },
        { element: '#analyzeBtn', title: '🚀 开始分析', desc: '上传完成后，点击开始分析，系统将为您生成专业解读报告。', position: 'bottom' }
    ];
    function startTour() {
        const overlay = document.getElementById('tourOverlay');
        const card = document.getElementById('tourCard');
        const titleEl = document.getElementById('tourTitle');
        const descEl = document.getElementById('tourDesc');
        tourStep = 0;
        overlay.style.display = 'flex';
        showTourStep();
        document.getElementById('tourNextBtn').onclick = () => { tourStep++; if (tourStep >= tourSteps.length) endTour(); else showTourStep(); };
        document.getElementById('tourSkipBtn').onclick = () => endTour();
    }
    function showTourStep() {
        const step = tourSteps[tourStep];
        const element = document.querySelector(step.element);
        if (!element) return;
        const rect = element.getBoundingClientRect();
        const card = document.getElementById('tourCard');
        document.getElementById('tourTitle').innerHTML = step.title;
        document.getElementById('tourDesc').innerHTML = step.desc;
        let top, left;
        if (step.position === 'top') { top = rect.top - card.offsetHeight - 10; left = rect.left + (rect.width / 2) - (card.offsetWidth / 2); }
        else { top = rect.bottom + 10; left = rect.left + (rect.width / 2) - (card.offsetWidth / 2); }
        card.style.top = Math.max(10, top) + 'px';
        card.style.left = Math.max(10, left) + 'px';
        if (tourStep === tourSteps.length - 1) document.getElementById('tourNextBtn').innerHTML = '完成';
        else document.getElementById('tourNextBtn').innerHTML = '下一步';
    }
    function endTour() { document.getElementById('tourOverlay').style.display = 'none'; }
    
    // ========== 二维码弹窗 ==========
    document.getElementById('showWechatQrcode').onclick = () => { document.getElementById('qrcodeModal').style.display = 'flex'; };
    window.closeQrcodeModal = () => { document.getElementById('qrcodeModal').style.display = 'none'; };
    window.addEventListener('click', (e) => { if (e.target === document.getElementById('qrcodeModal')) closeQrcodeModal(); });
    
    // ========== 充值按钮 ==========
    rechargeBtn.onclick = () => { window.location.href = '/recharge'; };
    
    // ========== 复制报告 ==========
    copyBtn.onclick = () => {
        if (!currentReport) return;
        navigator.clipboard.writeText(currentReport).then(() => {
            copySuccess.style.display = 'block';
            setTimeout(() => { copySuccess.style.display = 'none'; }, 2000);
        }).catch(() => showToast('复制失败', 'error'));
    };
    
    // ========== 文件上传 ==========
    function checkAuth() { analyzeBtn.disabled = !(selectedFile && phoneInput.value.trim() && apiKeyInput.value.trim()); }
    phoneInput.oninput = checkAuth;
    apiKeyInput.oninput = checkAuth;
    
    function handleFile(file) {
        if (!file || file.type !== 'application/pdf') {
            showToast('请上传PDF格式的文件', 'error');
            reset();
            return;
        }
        selectedFile = file;
        analyzeBtn.disabled = false;
        document.querySelector('.upload-icon').innerHTML = '✅';
        document.querySelector('.upload-text').innerHTML = '文件已就绪';
        fileNameSpan.innerHTML = file.name;
    }
    function reset() {
        document.querySelector('.upload-icon').innerHTML = '📎';
        document.querySelector('.upload-text').innerHTML = '点击或拖拽上传PDF文件';
        fileNameSpan.innerHTML = '';
        selectedFile = null;
        analyzeBtn.disabled = true;
        currentReport = '';
        copyBtn.style.display = 'none';
        resetProgress();
    }
    uploadArea.onclick = () => fileInput.click();
    fileInput.onchange = e => e.target.files.length > 0 && handleFile(e.target.files[0]);
    uploadArea.ondragover = e => { e.preventDefault(); uploadArea.style.background = '#eef4ff'; };
    uploadArea.ondragleave = e => { e.preventDefault(); uploadArea.style.background = '#fafcff'; };
    uploadArea.ondrop = e => {
        e.preventDefault();
        uploadArea.style.background = '#fafcff';
        if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
    };
    
    // ========== 分析 ==========
    analyzeBtn.onclick = async () => {
        if (!selectedFile) return;
        const phone = phoneInput.value.trim();
        const apiKey = apiKeyInput.value.trim();
        if (!phone || !apiKey) {
            showToast('请填写手机号和API Key', 'error');
            return;
        }
        saveCredentials();
        analyzeBtn.disabled = true;
        loadingDiv.style.display = 'block';
        resultContainer.style.display = 'none';
        copyBtn.style.display = 'none';
        startProgress(['上传中...', '解析PDF中...', '生成报告中...']);
        
        const formData = new FormData();
        formData.append('file', selectedFile);
        
        try {
            const resp = await fetch('/api/analyze', {
                method: 'POST',
                headers: { 'phone': phone, 'api-key': apiKey },
                body: formData
            });
            const data = await resp.json();
            completeProgress();
            
            if (!resp.ok) {
                if (data.code === 'NO_CREDENTIAL') {
                    currentTempId = data.temp_id;
                    showToast('请先充值获取API Key', 'info');
                    window.location.href = `/recharge?temp_id=${currentTempId}`;
                } else if (data.code === 'INSUFFICIENT_BALANCE') {
                    currentTempId = data.temp_id;
                    showToast('次数为0，请充值后继续使用', 'error');
                    window.location.href = `/recharge?temp_id=${currentTempId}`;
                } else if (data.code === 'INVALID_CREDENTIAL') {
                    showToast('手机号或API Key错误，请核对后重试', 'error');
                } else if (data.code === 'NOT_SIMPLE_REPORT') {
                    showToast('请上传正确的简版征信报告', 'error');
                } else if (data.code === 'DETAILED_REPORT') {
                    showToast('此为详版报告，请上传简版', 'error');
                } else {
                    showToast(data.message || '分析失败，请重试', 'error');
                }
                return;
            }
            currentReport = data.full_report;
            resultDiv.innerText = currentReport;
            resultContainer.style.display = 'block';
            copyBtn.style.display = 'inline-block';
            resultContainer.scrollIntoView({ behavior: 'smooth' });
        } catch (err) {
            completeProgress();
            showToast('网络错误，请稍后重试', 'error');
        } finally {
            loadingDiv.style.display = 'none';
            analyzeBtn.disabled = false;
            resetProgress();
        }
    };
    
    // ========== URL 参数检测 ==========
    function checkUrlParams() {
        const urlParams = new URLSearchParams(window.location.search);
        const autoReport = urlParams.get('auto_report');
        const phone = urlParams.get('phone');
        const apiKey = urlParams.get('api_key');
        const tempId = urlParams.get('temp_id');
        
        if (autoReport === 'true' && phone && apiKey) {
            phoneInput.value = decodeURIComponent(phone);
            apiKeyInput.value = decodeURIComponent(apiKey);
            if (tempId) currentTempId = tempId;
            showToast('✅ 充值成功！请重新上传您的报告文件查看结果', 'success');
            window.history.replaceState({}, document.title, window.location.pathname);
        }
    }
    checkUrlParams();
</script>
</body>
</html>
    ''')


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))