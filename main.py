# main.py
# 征信报告分析系统 - 主入口（紧凑版）

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
    <title>简版助手 - 征信分析</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f7fa;padding:12px}
        .container{max-width:600px;margin:0 auto;background:#fff;border-radius:16px;padding:12px;box-shadow:0 1px 8px rgba(0,0,0,0.05)}
        
        /* 标题区 */
        h1{color:#1e3c72;border-bottom:2px solid #4a90e2;padding-bottom:6px;margin-bottom:2px;font-size:20px}
        .slogan{font-size:11px;color:#e67e22;margin-bottom:12px;padding:4px 0;text-align:left}
        
        /* 介绍区域 */
        .intro-card{background:#f8f9fa;border-radius:10px;padding:10px;margin-bottom:12px}
        .intro-title{font-size:11px;font-weight:bold;color:#1e3c72;margin-bottom:6px}
        .scene-row{display:block;margin-bottom:8px;font-size:11px}
        .scene-good{display:block;color:#2e7d32;margin-bottom:4px}
        .scene-bad{display:block;color:#e67e22}
        .feature-item{margin-bottom:6px;font-size:11px;line-height:1.4}
        .feature-icon{font-weight:bold;color:#1e3c72;margin-right:6px}
        .feature-desc{color:#555;margin-left:22px}
        .divider{border-top:1px solid #e0e0e0;margin:8px 0}
        
        /* 上传区 */
        .upload-area{border:2px dashed #4a90e2;border-radius:14px;padding:20px 12px;text-align:center;cursor:pointer;margin:10px 0;transition:all 0.2s}
        .upload-area:hover{background:#eef4ff;border-color:#357abd}
        .upload-icon{font-size:36px;margin-bottom:4px}
        .upload-text{font-size:12px;color:#666}
        .blue-text{color:#4a90e2}
        .file-name{color:#2e7d32;font-size:11px;margin-top:4px}
        
        /* 进度条 */
        .progress-container{display:none;margin-top:10px}
        .progress-bar{background:#e0e0e0;border-radius:20px;height:4px;overflow:hidden}
        .progress-fill{background:#4a90e2;width:0%;height:100%;transition:width 0.3s}
        .progress-text{text-align:center;font-size:10px;color:#666;margin-top:4px}
        
        /* 按钮 */
        button{background:#4a90e2;color:#fff;border:none;padding:10px 16px;border-radius:40px;font-size:14px;font-weight:500;cursor:pointer;width:100%;margin:8px 0}
        button:hover{background:#357abd}
        
        .loading{display:none;text-align:center;margin:12px 0;color:#4a90e2;font-size:12px}
        .result-container{display:none;margin-top:12px}
        .result-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
        .result-header button{padding:5px 12px;width:auto;margin:0;background:#17a2b8;font-size:11px}
        .result-header button:hover{background:#138496}
        .result{background:#f9f9f9;border-radius:10px;padding:12px;font-family:monospace;font-size:10px;line-height:1.4;white-space:pre-wrap;max-height:400px;overflow:auto;border:1px solid #e0e0e0}
        
        .bottom-note{background:#e8f4fd;padding:8px;border-radius:10px;margin-top:12px;font-size:11px;text-align:center;color:#1e3c72}
        .copy-success{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#28a745;color:#fff;padding:6px 14px;border-radius:40px;font-size:11px;z-index:1000;display:none}
    </style>
</head>
<body>
<div class="container">
    <h1>📄 简版助手</h1>
    <div class="slogan">💡 替您省下“没必要请的假、没必要花的钱、没必要浪费的时间”</div>
    
    <div class="intro-card">
        <div class="intro-title">📌 介绍</div>
        <div class="scene-row">
            <span class="scene-good">✅ 逾期少 → 简版+简报够用</span>
            <span class="scene-bad">⚠️ 逾期多 → 详版必要，简报做初筛</span>
        </div>
        <div class="divider"></div>
        <div class="feature-item">
            <span class="feature-icon">📊 贷款分类</span>
            <div class="feature-desc">房贷 · 车贷 · 网贷</div>
        </div>
        <div class="feature-item">
            <span class="feature-icon">💳 信用卡</span>
            <div class="feature-desc">使用率：X% (分级警示)</div>
        </div>
        <div class="feature-item">
            <span class="feature-icon">📅 查询统计</span>
            <div class="feature-desc">阶段统计 · 分类展示 · 近1/3/6个月 · 网贷/本人</div>
        </div>
        <div class="feature-item">
            <span class="feature-icon">🧠 AI评估 + 优化建议</span>
            <div class="feature-desc">综合评分 · 风险提示 · 结清策略 · 停查建议</div>
        </div>
    </div>
    
    <div class="upload-area" id="uploadArea">
        <div class="upload-icon">📎</div>
        <div class="upload-text">点击或拖拽上传<span class="blue-text"><strong>简版</strong></span>信用报告（PDF）</div>
        <div class="file-name" id="fileName"></div>
        <input type="file" id="fileInput" accept=".pdf" style="display:none">
    </div>
    
    <div class="progress-container" id="progressContainer">
        <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
        <div class="progress-text" id="progressText">准备上传...</div>
    </div>
    
    <button id="analyzeBtn">开始分析</button>
    
    <div class="loading" id="loading">正在为您分析，请稍候...</div>
    <div class="result-container" id="resultContainer">
        <div class="result-header">
            <span>📋 分析结果</span>
            <button id="copyBtn" style="display:none">📋 复制报告</button>
        </div>
        <div class="result" id="result"></div>
    </div>
    
    <div class="bottom-note">
        有建议欢迎联系：📱15990529652（同微信）
    </div>
</div>
<div id="copySuccess" class="copy-success">✅ 已复制到剪贴板</div>

<script>
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const loadingDiv = document.getElementById('loading');
    const resultDiv = document.getElementById('result');
    const resultContainer = document.getElementById('resultContainer');
    const fileNameSpan = document.getElementById('fileName');
    const copyBtn = document.getElementById('copyBtn');
    const copySuccess = document.getElementById('copySuccess');
    const progressContainer = document.getElementById('progressContainer');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    
    let selectedFile = null;
    let currentReport = '';
    
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
        document.querySelector('.upload-text').innerHTML = '点击或拖拽上传<span class="blue-text"><strong>简版</strong></span>信用报告（PDF）';
        fileNameSpan.innerHTML = '';
        selectedFile = null;
        analyzeBtn.disabled = false;
        currentReport = '';
        copyBtn.style.display = 'none';
        resetProgress();
    }
    
    function copyReport() {
        if (!currentReport) return;
        navigator.clipboard.writeText(currentReport).then(() => {
            copySuccess.style.display = 'block';
            setTimeout(() => { copySuccess.style.display = 'none'; }, 2000);
        }).catch(err => {
            alert('复制失败：' + err);
        });
    }
    
    copyBtn.addEventListener('click', copyReport);
    
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
    
    let progressInterval = null;
    function startProgress(steps) {
        steps = steps || ['上传中...', '解析PDF中...', '生成报告中...'];
        progressContainer.style.display = 'block';
        let percent = 0;
        progressInterval = setInterval(function() {
            if (percent >= 90) { clearInterval(progressInterval); return; }
            percent = percent + Math.random() * 15;
            if (percent > 90) percent = 90;
            progressFill.style.width = percent + '%';
            var stepIndex = Math.floor(percent / 30);
            progressText.textContent = steps[Math.min(stepIndex, steps.length - 1)] || '处理中...';
        }, 500);
    }
    function completeProgress() {
        if (progressInterval) clearInterval(progressInterval);
        progressFill.style.width = '100%';
        progressText.textContent = '完成！';
        setTimeout(function() { progressContainer.style.display = 'none'; }, 800);
    }
    function resetProgress() { 
        if (progressInterval) clearInterval(progressInterval); 
        progressContainer.style.display = 'none'; 
        progressFill.style.width = '0%'; 
    }
    
    analyzeBtn.addEventListener('click', async () => {
        if (!selectedFile) return;
        
        analyzeBtn.disabled = true;
        loadingDiv.style.display = 'block';
        resultContainer.style.display = 'none';
        copyBtn.style.display = 'none';
        startProgress();
        
        const formData = new FormData();
        formData.append('file', selectedFile);
        
        try {
            const resp = await fetch('/api/analyze', {
                method: 'POST',
                body: formData
            });
            const data = await resp.json();
            completeProgress();
            
            if (!resp.ok) {
                if (data.code === 'NOT_SIMPLE_REPORT') {
                    alert('请上传正确的简版征信报告');
                } else if (data.code === 'DETAILED_REPORT') {
                    alert('此为详版报告，请上传简版');
                } else {
                    alert(data.message || '分析失败，请重试');
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
            alert('网络错误，请稍后重试');
        } finally {
            loadingDiv.style.display = 'none';
            analyzeBtn.disabled = false;
            resetProgress();
        }
    });
</script>
</body>
</html>
    ''')

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))