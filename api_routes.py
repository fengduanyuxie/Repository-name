# api_routes.py
# API 路由（含频率限制、报告清理、简版甄别、保存原始数据、在线充值）

import re
import hashlib
import httpx
from fastapi import APIRouter, File, UploadFile, HTTPException, Header, Request
from fastapi.responses import JSONResponse, HTMLResponse
from datetime import datetime
import database
import credit_analysis
import auth

router = APIRouter(tags=["api"])

# ========== 原有分析接口 ==========
@router.post("/api/analyze")
async def analyze(
    request: Request,
    file: UploadFile, 
    phone: str = Header(...), 
    api_key: str = Header(...)
):
    # 频率限制：每分钟最多10次
    if not auth.rate_limit(phone, limit=10, window=60):
        remaining = auth.get_rate_limit_remaining(phone, limit=10, window=60)
        raise HTTPException(429, detail=f"请求过于频繁，请稍后再试。剩余可用次数: {remaining}/分钟")
    
    if database.users_collection is None:
        raise HTTPException(500, "数据库未连接")
    
    valid, balance = database.verify_user(phone, api_key)
    if not valid:
        raise HTTPException(401, detail="无效的手机号或 API Key，或次数已用完")
    
    pdf_bytes = await file.read()
    if len(pdf_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件不能超过10MB")
    
    try:
        md = credit_analysis.parse_pdf(pdf_bytes)
        
        # 甄别是否为简版征信报告
        if "个人信用报告" not in md:
            raise HTTPException(400, detail="请上传正确的个人信用报告（未检测到'个人信用报告'关键字）")
        
        if "五级分类" in md:
            raise HTTPException(400, detail="检测到'五级分类'关键字，此为详细版征信报告。请上传个人简版信用报告，再重新分析")
        
        # 保存原始解析内容到数据库（用于管理员导出）
        try:
            if database.db is not None:
                raw_collection = database.db["raw_reports"]
                raw_collection.insert_one({
                    "phone": phone,
                    "raw_text": md,
                    "created_at": datetime.now()
                })
        except Exception as e:
            print(f"保存原始数据失败: {e}")
        
        stats, lines = credit_analysis.generate_report(md)
        
        raw_prompt_response = credit_analysis.call_deepseek(credit_analysis.build_llm_prompt(stats))
        
        cleaned_response = raw_prompt_response
        
        remove_patterns = [
            r'^好的[，,].*?[。：:\n]',
            r'^收到.*?[。：:\n]',
            r'^作为.*?专家[，,].*?[。：:\n]',
            r'^---+\n',
            r'^###?\s*征信分析报告.*?\n',
            r'^###?\s*第二部分.*?\n',
        ]
        
        for pattern in remove_patterns:
            cleaned_response = re.sub(pattern, '', cleaned_response, flags=re.IGNORECASE | re.MULTILINE)
        
        cleaned_response = re.sub(r'#{1,6}\s*', '', cleaned_response)
        cleaned_response = re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned_response)
        cleaned_response = re.sub(r'\*([^*]+)\*', r'\1', cleaned_response)
        cleaned_response = re.sub(r'^[-*]\s+', '', cleaned_response, flags=re.MULTILINE)
        cleaned_response = re.sub(r'---+', '', cleaned_response)
        cleaned_response = re.sub(r'\n{3,}', '\n\n', cleaned_response)
        
        cleaned_response = cleaned_response.lstrip('\n')
        
        part1 = "\n".join(lines)
        
        full_report = ("让您久等了，您的专属征信解读报告已生成，请查阅~\n\n" + 
                       "【第一部分：简要汇总】\n\n" + part1 + "\n\n【第二部分：结构分析】\n\n" + 
                       cleaned_response + 
                       "\n\n\n💡 如有任何疑问或建议，欢迎随时联系管理员（微信：DXNBZ579）")
        
        database.consume_balance(phone, api_key)
        
        return JSONResponse({"success": True, "full_report": full_report})
    except HTTPException:
        raise
    except Exception as e:
        print(f"错误: {str(e)}")
        raise HTTPException(500, f"处理失败: {str(e)}")

@router.get("/api/verify")
async def verify(phone: str, api_key: str):
    valid, balance = database.verify_user(phone, api_key)
    return {"valid": valid, "remaining": balance if valid else 0}

@router.get("/api/balance")
async def get_balance(phone: str, api_key: str):
    valid, balance = database.verify_user(phone, api_key)
    if not valid:
        raise HTTPException(401, detail="无效的 API Key")
    return {"phone": phone, "remaining": balance}

@router.get("/api/health")
async def health():
    db_status = "connected" if database.users_collection is not None else "disconnected"
    return {"status": "ok", "version": "v051211", "database": db_status}


# ========== 在线充值功能 ==========
@router.get("/recharge")
async def recharge_page():
    """充值页面"""
    return HTMLResponse(content='''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>在线充值 - 征信报告分析系统</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f7fa;padding:20px}
        .container{max-width:600px;margin:0 auto}
        .card{background:#fff;border-radius:24px;padding:24px;margin-bottom:20px;box-shadow:0 4px 20px rgba(0,0,0,0.08)}
        h1{color:#1e3c72;border-bottom:3px solid #4a90e2;padding-bottom:12px;margin-bottom:20px}
        h2{color:#333;margin-bottom:16px;font-size:18px}
        .package{background:#f8f9fa;border-radius:16px;padding:20px;margin-bottom:16px;cursor:pointer;transition:all 0.3s;border:2px solid transparent}
        .package:hover{background:#eef4ff}
        .package.selected{background:#eef4ff;border-color:#4a90e2}
        .package-name{font-size:18px;font-weight:bold;color:#1e3c72}
        .package-price{font-size:24px;font-weight:bold;color:#4a90e2;margin:8px 0}
        .package-times{color:#666;font-size:14px}
        .phone-input{margin:20px 0}
        .phone-input input{width:100%;padding:12px;border:1px solid #ddd;border-radius:12px;font-size:16px}
        .btn{background:#4a90e2;color:#fff;border:none;padding:14px;border-radius:40px;width:100%;font-size:16px;font-weight:500;cursor:pointer;margin-top:16px}
        .btn:hover{background:#357abd}
        .loading{display:none;text-align:center;margin:20px 0;color:#4a90e2}
        .qrcode{text-align:center;margin:20px 0;display:none}
        .qrcode img{max-width:200px;border:1px solid #ddd;border-radius:12px;padding:12px}
        .result{background:#f9f9f9;border-radius:12px;padding:16px;margin-top:16px;display:none;text-align:center}
        .info-note{background:#e8f4fd;padding:12px;border-radius:12px;margin-top:20px;font-size:12px;color:#4a90e2;text-align:center}
    </style>
</head>
<body>
<div class="container">
    <div class="card">
        <h1>💰 在线充值</h1>
        <p style="color:#666;margin-bottom:20px">选择套餐后扫码支付，充值次数自动到账</p>
        
        <div class="phone-input">
            <input type="tel" id="phone" placeholder="请输入您的手机号" autocomplete="off">
        </div>
        
        <h2>选择充值套餐</h2>
        
        <div class="package" data-package="trial" data-price="19.9" data-times="3">
            <div class="package-name">🎁 体验卡</div>
            <div class="package-price">¥19.9</div>
            <div class="package-times">当月可用 3 次</div>
        </div>
        
        <div class="package" data-package="month" data-price="29.9" data-times="100">
            <div class="package-name">📅 月卡</div>
            <div class="package-price">¥29.9</div>
            <div class="package-times">当月可用 100 次</div>
        </div>
        
        <button class="btn" onclick="createOrder()">立即充值</button>
        
        <div class="loading" id="loading">⏳ 正在创建订单，请稍候...</div>
        <div class="qrcode" id="qrcode"></div>
        <div class="result" id="result"></div>
        
        <div class="info-note">
            💡 提示：支付成功后，充值次数将自动添加到您的账户。<br>
            如有问题请联系管理员（微信:DXNBZ579）
        </div>
    </div>
</div>

<script>
let selectedPackage = null;
let selectedPrice = 0;
let selectedTimes = 0;

document.querySelectorAll('.package').forEach(pkg => {
    pkg.addEventListener('click', function() {
        document.querySelectorAll('.package').forEach(p => p.classList.remove('selected'));
        this.classList.add('selected');
        selectedPackage = this.dataset.package;
        selectedPrice = parseFloat(this.dataset.price);
        selectedTimes = parseInt(this.dataset.times);
    });
});

async function createOrder() {
    const phone = document.getElementById('phone').value.trim();
    if (!phone) {
        alert('请填写手机号');
        return;
    }
    if (!selectedPackage) {
        alert('请选择充值套餐');
        return;
    }
    
    const loading = document.getElementById('loading');
    const qrcodeDiv = document.getElementById('qrcode');
    const resultDiv = document.getElementById('result');
    
    loading.style.display = 'block';
    qrcodeDiv.style.display = 'none';
    resultDiv.style.display = 'none';
    
    try {
        const resp = await fetch('/api/create_order', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                phone: phone,
                package_type: selectedPackage,
                price: selectedPrice,
                times: selectedTimes
            })
        });
        const data = await resp.json();
        
        if (!resp.ok) {
            throw new Error(data.detail || '创建订单失败');
        }
        
        if (data.qrcode) {
            qrcodeDiv.innerHTML = `<img src="${data.qrcode}"><p style="margin-top:12px">请扫码支付</p><p style="font-size:12px;color:#666">订单号：${data.order_id}</p>`;
            qrcodeDiv.style.display = 'block';
            checkPaymentStatus(data.order_id);
        } else if (data.pay_url) {
            window.open(data.pay_url, '_blank');
            resultDiv.innerHTML = `✅ 订单创建成功！请在新窗口完成支付<br>订单号：${data.order_id}<br><span style="font-size:12px">支付完成后请返回此页面，稍等片刻自动到账</span>`;
            resultDiv.style.display = 'block';
            checkPaymentStatus(data.order_id);
        }
        
    } catch(e) {
        alert('错误：' + e.message);
    } finally {
        loading.style.display = 'none';
    }
}

async function checkPaymentStatus(orderId) {
    let count = 0;
    const maxAttempts = 60;
    
    const interval = setInterval(async () => {
        count++;
        if (count > maxAttempts) {
            clearInterval(interval);
            return;
        }
        
        try {
            const resp = await fetch(`/api/order_status/${orderId}`);
            const data = await resp.json();
            
            if (data.status === 'paid') {
                clearInterval(interval);
                document.getElementById('result').innerHTML = `🎉 充值成功！<br>已为您添加 ${data.times_added} 次<br>当前剩余次数：${data.new_balance}<br><br>您可以<a href="/">返回首页</a>开始使用了！`;
                document.getElementById('result').style.display = 'block';
                document.getElementById('qrcode').style.display = 'none';
            }
        } catch(e) {
            // 继续轮询
        }
    }, 5000);
}
</script>
</body>
</html>
    ''')


@router.post("/api/create_order")
async def create_order(request: Request):
    """创建充值订单，返回易支付链接"""
    body = await request.json()
    phone = body.get("phone")
    package_type = body.get("package_type")
    
    if not phone or not package_type:
        raise HTTPException(400, detail="参数错误")
    
    packages = {
        "trial": {"name": "体验卡", "price": 19.9, "times": 3},
        "month": {"name": "月卡", "price": 29.9, "times": 100}
    }
    
    if package_type not in packages:
        raise HTTPException(400, detail="套餐不存在")
    
    pkg = packages[package_type]
    
    order_id = database.create_recharge_order(phone, package_type, pkg["price"], pkg["times"])
    if not order_id:
        raise HTTPException(500, detail="创建订单失败")
    
    # 易支付配置
    pid = "3311"
    key = "god9VY5h17lac585ovKZOld6fsziLjnT"
    api_url = "https://www.ezfpy.cn/submit.php"
    notify_url = f"https://{request.headers.get('host')}/api/pay_callback"
    return_url = f"https://{request.headers.get('host')}/recharge"
    
    params = {
        "pid": pid,
        "type": "alipay",
        "out_trade_no": order_id,
        "notify_url": notify_url,
        "return_url": return_url,
        "name": f"征信报告-{pkg['name']}",
        "money": str(pkg["price"]),
        "sitename": "征信报告分析系统"
    }
    
    sign_str = "&".join([f"{k}={params[k]}" for k in sorted(params.keys())]) + key
    params["sign"] = hashlib.md5(sign_str.encode()).hexdigest()
    params["sign_type"] = "MD5"
    
    pay_url = api_url + "?" + "&".join([f"{k}={params[k]}" for k in params])
    
    return {
        "success": True,
        "order_id": order_id,
        "pay_url": pay_url,
        "qrcode": None
    }


@router.post("/api/pay_callback")
async def pay_callback(request: Request):
    """易支付回调接口 - 支付成功后自动充值"""
    form_data = await request.form()
    params = dict(form_data)
    
    key = "god9VY5h17lac585ovKZOld6fsziLjnT"
    
    sign = params.get("sign", "")
    sign_params = {k: v for k, v in params.items() if k != "sign"}
    sign_str = "&".join([f"{k}={sign_params[k]}" for k in sorted(sign_params.keys())]) + key
    calc_sign = hashlib.md5(sign_str.encode()).hexdigest()
    
    if sign != calc_sign:
        print(f"签名验证失败")
        return "fail"
    
    order_id = params.get("out_trade_no")
    trade_status = params.get("trade_status")
    
    if trade_status != "TRADE_SUCCESS":
        return "fail"
    
    order = database.get_order_by_id(order_id)
    if not order:
        print(f"订单不存在: {order_id}")
        return "fail"
    
    if order.get("status") == "paid":
        return "success"
    
    database.update_order_paid(order_id)
    
    phone = order.get("phone")
    times_to_add = order.get("times", 0)
    
    if phone and times_to_add > 0:
        user = database.get_user_by_phone(phone)
        if user:
            new_balance = user.get("balance", 0) + times_to_add
            database.users_collection.update_one(
                {"phone": phone},
                {"$set": {"balance": new_balance}}
            )
            database.add_admin_log("system", "auto_recharge", phone, f"支付{order.get('price')}元，增加{times_to_add}次，订单号{order_id}")
        else:
            database.add_or_recharge_user(phone, times_to_add, 30)
            database.add_admin_log("system", "auto_recharge", phone, f"新用户充值，增加{times_to_add}次，订单号{order_id}")
    
    return "success"


@router.get("/api/order_status/{order_id}")
async def order_status(order_id: str):
    """查询订单支付状态"""
    order = database.get_order_by_id(order_id)
    if not order:
        raise HTTPException(404, detail="订单不存在")
    
    status = order.get("status", "pending")
    result = {"order_id": order_id, "status": status}
    
    if status == "paid":
        phone = order.get("phone")
        if phone:
            user = database.get_user_by_phone(phone)
            if user:
                result["new_balance"] = user.get("balance", 0)
                result["times_added"] = order.get("times", 0)
    
    return result