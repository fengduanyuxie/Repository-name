# main.py
# 征信报告分析系统 - 主入口（模块化版本）

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn

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
        h1 span{font-size:12px;color:#999;font-weight:normal;display:block;margin-top:4px}
        .auth-box{background:#f0f2f5;border-radius:12px;padding:16px;margin-bottom:20px}
        .auth-box input{width:100%;padding:10px;margin-bottom:10px;border:1px solid #ddd;border-radius:8px;font-size:14px}
        .upload-area{border:2px dashed #4a90e2;border-radius:20px;padding:40px 20px;text-align:center;cursor:pointer;margin:16px 0;transition:all 0.3s}
        .upload-area:hover{background:#eef4ff;border-color:#357abd}
        .upload-icon{font-size:48px;margin-bottom:12px}
        .file-name{color:#2e7d32;font-size:14px;margin-top:8px}
        button{background:#4a90e2;color:#fff;border:none;padding:14px 28px;border-radius:40px;font-size:16px;font-weight:500;cursor:pointer;width:100%;margin-top:8px}
        button:hover{background:#357abd}
        button:disabled{background:#ccc;cursor:not-allowed}
        .loading{display:none;text-align:center;margin:24px 0;color:#4a90e2}
        .result-container{display:none;margin-top:24px}
        .result{background:#f9f9f9;border-radius:16px;padding:16px;font-family:monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;max-height:500px;overflow:auto;border:1px solid #e0e0e0}
        .info-note{background:#e8f4fd;padding:12px;border-radius:12px;margin-top:20px;font-size:12px;color:#4a90e2;text-align:center}
    </style>
</head>
<body>
<div class="container">
    <h1>📄 征信结构解读<span>限个人简版信用报告</span></h1>
    <p class="desc" style="color:#666;font-size:14px;margin-bottom:20px">上传PDF格式的个人简版信用报告，系统将自动解析并生成专业风控报告。</p>
    
    <div class="auth-box">
        <input type="tel" id="phone" placeholder="手机号" autocomplete="off">
        <input type="text" id="apiKey" placeholder="API Key" autocomplete="off">
    </div>
    
    <div class="upload-area" id="uploadArea">
        <div class="upload-icon">📎</div>
        <div class="upload-text">点击或拖拽上传PDF文件</div>
        <div class="file-name" id="fileName"></div>
        <input type="file" id="fileInput" accept=".pdf" style="display:none">
    </div>
    
    <button id="analyzeBtn" disabled>开始分析</button>
    <div class="loading" id="loading">正在分析，请稍候...</div>
    <div class="result-container" id="resultContainer">
        <div class="result" id="result"></div>
    </div>
    <div class="info-note">💡 提示：分析结果包含两部分 — 简要汇总 + 展开分析。需要有效手机号和API Key。</div>
</div>

<script>
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const loadingDiv = document.getElementById('loading');
    const resultDiv = document.getElementById('result');
    const resultContainer = document.getElementById('resultContainer');
    const fileNameSpan = document.getElementById('fileName');
    const phoneInput = document.getElementById('phone');
    const apiKeyInput = document.getElementById('apiKey');
    
    let selectedFile = null;
    
    function checkAuth() {
        analyzeBtn.disabled = !(selectedFile && phoneInput.value.trim() && apiKeyInput.value.trim());
    }
    
    phoneInput.addEventListener('input', checkAuth);
    apiKeyInput.addEventListener('input', checkAuth);
    
    function handleFile(file) {
        if (!file || file.type !== 'application/pdf') {
            alert('请上传PDF格式的文件');
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
    }
    
    uploadArea.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', e => e.target.files.length > 0 && handleFile(e.target.files[0]));
    
    uploadArea.addEventListener('dragover', e => {
        e.preventDefault();
        uploadArea.style.background = '#eef4ff';
    });
    
    uploadArea.addEventListener('dragleave', e => {
        e.preventDefault();
        uploadArea.style.background = '#fafcff';
    });
    
    uploadArea.addEventListener('drop', e => {
        e.preventDefault();
        uploadArea.style.background = '#fafcff';
        if (e.dataTransfer.files.length > 0) {
            handleFile(e.dataTransfer.files[0]);
        }
    });
    
    analyzeBtn.addEventListener('click', async () => {
        if (!selectedFile) return;
        
        const phone = phoneInput.value.trim();
        const apiKey = apiKeyInput.value.trim();
        if (!phone || !apiKey) {
            alert('请填写手机号和API Key');
            return;
        }
        
        analyzeBtn.disabled = true;
        loadingDiv.style.display = 'block';
        resultContainer.style.display = 'none';
        
        const formData = new FormData();
        formData.append('file', selectedFile);
        
        try {
            const resp = await fetch('/api/analyze', {
                method: 'POST',
                headers: {
                    'phone': phone,
                    'api-key': apiKey
                },
                body: formData
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || '分析失败');
            resultDiv.innerText = data.full_report;
            resultContainer.style.display = 'block';
            resultContainer.scrollIntoView({ behavior: 'smooth' });
        } catch (err) {
            alert('错误：' + err.message);
        } finally {
            loadingDiv.style.display = 'none';
            analyzeBtn.disabled = false;
        }
    });
</script>
</body>
</html>
    ''')

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))