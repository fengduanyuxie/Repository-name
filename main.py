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

# 前端页面（可选，也可以放在 static 文件夹）
@app.get("/")
async def frontend():
    return HTMLResponse(content='''
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>征信报告分析系统</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,sans-serif;background:#f5f7fa;padding:16px}.container{max-width:600px;margin:0 auto;background:#fff;border-radius:24px;padding:20px;box-shadow:0 4px 20px rgba(0,0,0,0.08)}h1{color:#1e3c72;border-bottom:3px solid #4a90e2;padding-bottom:12px;margin-bottom:16px}.auth-box{background:#f0f2f5;border-radius:12px;padding:16px;margin-bottom:20px}.auth-box input{width:100%;padding:10px;margin-bottom:10px;border:1px solid #ddd;border-radius:8px}.upload-area{border:2px dashed #4a90e2;border-radius:20px;padding:40px 20px;text-align:center;cursor:pointer;margin:16px 0}.upload-icon{font-size:48px}button{background:#4a90e2;color:#fff;border:none;padding:14px;border-radius:40px;width:100%;margin-top:8px;cursor:pointer}.result{background:#f9f9f9;border-radius:16px;padding:16px;font-family:monospace;font-size:12px;white-space:pre-wrap;max-height:500px;overflow:auto;margin-top:16px;display:none}</style>
</head>
<body><div class="container"><h1>📄 征信结构解读</h1><div class="auth-box"><input type="tel" id="phone" placeholder="手机号"><input type="text" id="apiKey" placeholder="API Key"></div><div class="upload-area" id="uploadArea"><div class="upload-icon">📎</div><div>点击或拖拽上传PDF文件</div><div id="fileName"></div><input type="file" id="fileInput" accept=".pdf" style="display:none"></div><button id="analyzeBtn" disabled>开始分析</button><div class="result" id="result"></div></div><script>
const phone=document.getElementById('phone'),apiKey=document.getElementById('apiKey');
let selected=null;
function check(){document.getElementById('analyzeBtn').disabled=!(selected&&phone.value&&apiKey.value);}
phone.oninput=check;apiKey.oninput=check;
document.getElementById('uploadArea').onclick=()=>document.getElementById('fileInput').click();
document.getElementById('fileInput').onchange=e=>{if(e.target.files[0]){selected=e.target.files[0];document.getElementById('fileName').innerHTML=selected.name;check();}};
document.getElementById('analyzeBtn').onclick=async()=>{const fd=new FormData();fd.append('file',selected);const btn=document.getElementById('analyzeBtn'),resDiv=document.getElementById('result');btn.disabled=true;resDiv.style.display='block';resDiv.innerHTML='正在分析...';try{const resp=await fetch('/api/analyze',{method:'POST',headers:{'phone':phone.value,'api-key':apiKey.value},body:fd});const data=await resp.json();if(!resp.ok)throw new Error(data.detail);resDiv.innerHTML=data.full_report;}catch(err){resDiv.innerHTML='错误：'+err.message;}finally{btn.disabled=false;}};
</script></body></html>
    ''')

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))