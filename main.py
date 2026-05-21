# main.py
# 征信报告分析系统 - 主入口（完全免费版 + 功能说明）

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
        
        /* 功能说明区域样式 */
        .feature-card{background:linear-gradient(135deg,#e8f4fd 0%,#d4eaf7 100%);border-radius:20px;padding:20px;margin-bottom:20px}
        .feature-title{font-size:18px;font-weight:bold;color:#1e3c72;margin-bottom:16px;padding-bottom:8px;border-bottom:2px solid #4a90e2}
        .feature-grid{display:flex;flex-wrap:wrap;gap:20px}
        .feature-col{flex:1;min-width:250px}
        .feature-item{display:flex;gap:12px;margin-bottom:16px;font-size:13px;line-height:1.5}
        .feature-icon{font-size:24px;min-width:36px;text-align:center}
        .feature-content strong{color:#1e3c72;font-size:14px}
        .feature-note{color:#666;font-size:12px}
        .feature-warning{color:#e67e22;font-size:12px}
        
        .upload-area{border:2px dashed #4a90e2;border-radius:20px;padding:40px 20px;text-align:center;cursor:pointer;margin:16px 0;transition:all 0.3s}
        .upload-area:hover{background:#eef4ff;border-color:#357abd}
        .upload-icon{font-size:48px;margin-bottom:12px}
        .upload-text{font-size:14px;color:#666}
        .blue-text{color:#4a90e2}
        .file-name{color:#2e7d32;font-size:14px;margin-top:8px}
        .progress-container{display:none;margin-top:16px}
        .progress-bar{background:#e0e0e0;border-radius:20px;height:8px;overflow:hidden}
        .progress-fill{background:#4a90e2;width:0%;height:100%;transition:width 0.3s}
        .progress-text{text-align:center;font-size:12px;color:#666;margin-top:8px}
        button{background:#4a90e2;color:#fff;border:none;padding:14px 28px;border-radius:40px;font-size:16px;font-weight:500;cursor:pointer;width:100%;margin-top:8px}
        button:hover{background:#357abd}
        button:disabled{background:#ccc;cursor:not-allowed}
        .loading{display:none;text-align:center;margin:24px 0;color:#4a90e2}
        .result-container{display:none;margin-top:24px}
        .result-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
        .result-header button{padding:8px 16px;width:auto;margin:0;background:#17a2b8}
        .result-header button:hover{background:#138496}
        .result{background:#f9f9f9;border-radius:16px;padding:16px;font-family:monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;max-height:500px;overflow:auto;border:1px solid #e0e0e0}
        .info-note{background:#e8f4fd;padding:12px;border-radius:12px;margin-top:20px;font-size:12px;text-align:center}
        .copy-success{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#28a745;color:#fff;padding:10px 20px;border-radius:40px;font-size:14px;z-index:1000;display:none}
    </style>
</head>
<body>
<div class="container">
    <h1>📄 征信结构解读</h1>
    
    <!-- 功能说明区域 -->
    <div class="feature-card">
        <div class="feature-title">🔍 简版报告智能分析</div>
        <div class="feature-grid">
            <div class="feature-col">
                <div class="feature-item">
                    <div class="feature-icon">📊</div>
                    <div class="feature-content">
                        <strong>贷款分类</strong><br>
                        房贷：X家，X万元<br>
                        车贷：X家，X万元<br>
                        网贷：X家，X万元<br>
                        <span class="feature-note">识别来源：微众、网商、借呗等</span>
                    </div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">💰</div>
                    <div class="feature-content">
                        <strong>金额统计</strong><br>
                        总贷款金额：X万元
                    </div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">💳</div>
                    <div class="feature-content">
                        <strong>信用卡分析</strong><br>
                        使用率：X%<br>
                        <span class="feature-warning">⚠️ 超70%银行会谨慎</span>
                    </div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">📅</div>
                    <div class="feature-content">
                        <strong>查询统计</strong><br>
                        近1个月：X次<br>
                        近3个月：X次<br>
                        近6个月：X次<br>
                        其中网贷查询：X次
                    </div>
                </div>
            </div>
            <div class="feature-col">
                <div class="feature-item">
                    <div class="feature-icon">🧠</div>
                    <div class="feature-content">
                        <strong>AI 智能评估</strong><br>
                        • 综合评估：可正常申请<br>
                        • 需优化：网贷家数过多<br>
                        • 风险提示：使用率过高<br>
                        • 查询提醒：近3个月查询X次
                    </div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">💡</div>
                    <div class="feature-content">
                        <strong>优化建议</strong><br>
                        • 先结清：借呗、微粒贷<br>
                        • 建议停查：3-6个月<br>
                        • 信用卡使用率降至70%以下
                    </div>
                </div>
            </div>
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
            <span style="font-size:14px;font-weight:500;">📋 分析结果</span>
            <button id="copyBtn" style="display:none;background:#17a2b8;width:auto;padding:8px 16px;">📋 复制报告</button>
        </div>
        <div class="result" id="result"></div>
    </div>
    <div class="info-note">
        有问题联系我：📱1599052952（同微信）
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
    
    // 进度条模拟
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
        setTimeout(function() { progressContainer.style.display = 'none'; }, 1000);
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