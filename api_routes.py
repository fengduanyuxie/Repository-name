# api_routes.py
# API 路由（含频率限制、报告清理、简版甄别、保存原始数据、在线充值、订单记录）

import re
import uuid
import hashlib
from fastapi import APIRouter, File, UploadFile, HTTPException, Header, Request
from fastapi.responses import JSONResponse, HTMLResponse
from datetime import datetime, timedelta
import database
import credit_analysis
import auth

router = APIRouter(tags=["api"])


# ========== 辅助函数 ==========
def clean_deepseek_response(text: str) -> str:
    """清洗 DeepSeek 返回内容"""
    remove_patterns = [
        r'^好的[，,].*?[。：:\n]',
        r'^收到.*?[。：:\n]',
        r'^作为.*?专家[，,].*?[。：:\n]',
        r'^---+\n',
        r'^###?\s*征信分析报告.*?\n',
        r'^###?\s*第二部分.*?\n',
    ]
    for pattern in remove_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE)
    
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'---+', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.lstrip('\n')


def format_report_sections(text: str) -> str:
    """格式化报告段落，添加空行和图标"""
    # 在数字序号前添加换行
    text = re.sub(r'(\d+[\.\)、]|\u2460|\u2461|\u2462|\u2463|\u2464|\u2465)', r'\n\n\1', text)
    # 添加关键提示图标
    text = re.sub(r'(建议[：:])', r'💡 \1', text)
    text = re.sub(r'(风险[：:])', r'⚠️ \1', text)
    return text


# ========== 分析接口 ==========
@router.post("/api/analyze")
async def analyze(
    request: Request,
    file: UploadFile,
    phone: str = Header(None),
    api_key: str = Header(None)
):
    # 频率限制
    if phone and not auth.rate_limit(phone, limit=10, window=60):
        remaining = auth.get_rate_limit_remaining(phone, limit=10, window=60)
        return JSONResponse(
            status_code=429,
            content={"code": "RATE_LIMIT", "message": f"请求过于频繁，请稍后再试。剩余可用次数: {remaining}/分钟"}
        )
    
    if database.users_collection is None:
        return JSONResponse(
            status_code=500,
            content={"code": "DB_ERROR", "message": "数据库未连接，请稍后重试"}
        )
    
    # 验证文件
    pdf_bytes = await file.read()
    if len(pdf_bytes) > 10 * 1024 * 1024:
        return JSONResponse(
            status_code=400,
            content={"code": "FILE_TOO_LARGE", "message": "文件不能超过10MB"}
        )
    
    try:
        # 解析 PDF
        md = credit_analysis.parse_pdf(pdf_bytes)
        
        # 甄别简版报告
        if "个人信用报告" not in md:
            return JSONResponse(
                status_code=400,
                content={"code": "NOT_SIMPLE_REPORT", "message": "请上传正确的简版征信报告"}
            )
        if "五级分类" in md:
            return JSONResponse(
                status_code=400,
                content={"code": "DETAILED_REPORT", "message": "此为详版报告，请上传简版"}
            )
        
        # 生成分析报告
        stats, lines = credit_analysis.generate_report(md)
        raw_response = credit_analysis.call_deepseek(credit_analysis.build_llm_prompt(stats))
        cleaned_response = clean_deepseek_response(raw_response)
        formatted_response = format_report_sections(cleaned_response)
        part1 = "\n".join(lines)
        report_content = f"【第一部分：简要汇总】\n\n{part1}\n\n【第二部分：结构分析】\n\n{formatted_response}"
        
        temp_id = str(uuid.uuid4())
        
        # 判断用户状态
        if phone and api_key:
            # 验证用户是否存在及有效期
            exists, user, balance = database.verify_user_exists(phone, api_key)
            
            if not exists:
                # 用户不存在
                database.save_temp_report(temp_id, report_content, phone, api_key)
                return JSONResponse(
                    status_code=401,
                    content={
                        "code": "INVALID_CREDENTIAL",
                        "message": "手机号或 API Key 错误，请核对后重试，或联系管理员（微信:DXNBZ579）",
                        "temp_id": temp_id
                    }
                )
            
            if balance == 0:
                # 次数用完或已过期
                database.save_temp_report(temp_id, report_content, phone, api_key)
                return JSONResponse(
                    status_code=402,
                    content={
                        "code": "INSUFFICIENT_BALANCE",
                        "message": "次数为0，请充值后继续使用",
                        "temp_id": temp_id
                    }
                )
            
            # 有效用户，扣费并返回报告
            database.consume_balance(phone, api_key)
            user_data = database.get_user_by_phone(phone)
            expire_date = user_data.get('expire_at', '永久')
            if isinstance(expire_date, datetime):
                expire_date = expire_date.strftime('%Y-%m-%d')
            
            # 保存原始数据
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
            
            final_report = f"""让您久等了，您的专属征信解读报告已生成，请查阅~

🔑 **您的API Key**: `{api_key}`
💰 **剩余次数**: {user_data.get('balance', 0)}
📅 **有效期至**: {expire_date}
> ⚠️ **请务必保存好您的API Key！**

{report_content}

💡 API Key获取请联系管理员（微信:DXNBZ579）"""
            
            return JSONResponse({"success": True, "full_report": final_report})
        
        else:
            # 新用户，未提供凭证
            database.save_temp_report(temp_id, report_content)
            return JSONResponse(
                status_code=401,
                content={
                    "code": "NO_CREDENTIAL",
                    "message": "请先充值获取API Key",
                    "temp_id": temp_id
                }
            )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"错误: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"code": "SERVER_ERROR", "message": f"处理失败: {str(e)}"}
        )


@router.post("/api/get_report")
async def get_report(request: Request):
    """获取已分析的报告（用于支付后展示）"""
    body = await request.json()
    phone = body.get("phone")
    api_key = body.get("api_key")
    temp_id = body.get("temp_id")
    
    if not phone or not api_key or not temp_id:
        return JSONResponse(
            status_code=400,
            content={"code": "MISSING_PARAMS", "message": "参数错误"}
        )
    
    # 验证用户
    exists, user, balance = database.verify_user_exists(phone, api_key)
    if not exists:
        return JSONResponse(
            status_code=401,
            content={"code": "INVALID_CREDENTIAL", "message": "手机号或 API Key 错误，请核对后重试"}
        )
    
    if balance == 0:
        return JSONResponse(
            status_code=402,
            content={"code": "INSUFFICIENT_BALANCE", "message": "次数为0，请充值后继续使用"}
        )
    
    # 获取临时报告
    temp = database.get_temp_report(temp_id)
    if not temp:
        return JSONResponse(
            status_code=404,
            content={"code": "REPORT_EXPIRED", "message": "报告已过期，请重新上传"}
        )
    
    # 扣费
    database.consume_balance(phone, api_key)
    user_data = database.get_user_by_phone(phone)
    expire_date = user_data.get('expire_at', '永久')
    if isinstance(expire_date, datetime):
        expire_date = expire_date.strftime('%Y-%m-%d')
    
    # 删除临时报告
    database.delete_temp_report(temp_id)
    
    final_report = f"""让您久等了，您的专属征信解读报告已生成，请查阅~

🔑 **您的API Key**: `{api_key}`
💰 **剩余次数**: {user_data.get('balance', 0)}
📅 **有效期至**: {expire_date}
> ⚠️ **请务必保存好您的API Key！**

{temp.get('report', '')}

💡 API Key获取请联系管理员（微信:DXNBZ579）"""
    
    return JSONResponse({"success": True, "full_report": final_report})


@router.get("/api/verify")
async def verify(phone: str, api_key: str):
    valid, balance = database.verify_user(phone, api_key)
    return {"valid": valid, "remaining": balance if valid else 0}


@router.get("/api/balance")
async def get_balance(phone: str, api_key: str):
    valid, balance = database.verify_user(phone, api_key)
    if not valid:
        return JSONResponse(
            status_code=401,
            content={"code": "INVALID_CREDENTIAL", "message": "无效的 API Key"}
        )
    return {"phone": phone, "remaining": balance}


@router.get("/api/health")
async def health():
    db_status = "connected" if database.users_collection is not None else "disconnected"
    return {"status": "ok", "version": "v051214", "database": db_status}


# ========== 充值页面 ==========
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
        .package{background:#f8f9fa;border-radius:16px;padding:20px;margin-bottom:16px;cursor:pointer;transition:all 0.3s;border:2px solid transparent;position:relative}
        .package:hover{background:#eef4ff}
        .package.selected{background:#eef4ff;border-color:#4a90e2}
        .package-name{font-size:18px;font-weight:bold;color:#1e3c72}
        .package-price{font-size:24px;font-weight:bold;color:#4a90e2;margin:8px 0}
        .package-times{color:#666;font-size:14px}
        .package-price-per{color:#999;font-size:12px;margin-top:4px}
        .recommend-badge{position:absolute;top:12px;right:12px;background:#ff9800;color:#fff;padding:4px 8px;border-radius:20px;font-size:12px;font-weight:bold}
        .phone-input{margin:20px 0}
        .phone-input input{width:100%;padding:12px;border:1px solid #ddd;border-radius:12px;font-size:16px}
        .btn{background:#4a90e2;color:#fff;border:none;padding:14px;border-radius:40px;width:100%;font-size:16px;font-weight:500;cursor:pointer;margin-top:16px}
        .btn:hover{background:#357abd}
        .loading{display:none;text-align:center;margin:20px 0;color:#4a90e2}
        .qrcode{text-align:center;margin:20px 0;display:none}
        .qrcode img{max-width:200px;border:1px solid #ddd;border-radius:12px;padding:12px}
        .result{background:#f9f9f9;border-radius:12px;padding:16px;margin-top:16px;display:none;text-align:center}
        .info-note{background:#e8f4fd;padding:12px;border-radius:12px;margin-top:20px;font-size:12px;color:#4a90e2;text-align:center}
        .orders-link{text-align:center;margin-top:16px}
        .orders-link a{color:#4a90e2;text-decoration:none}
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
        
        <div class="package" data-package="trial" data-price="19.9" data-times="1" data-price-per="19.9">
            <div class="package-name">🎁 次卡</div>
            <div class="package-price">¥19.9</div>
            <div class="package-times">1次</div>
            <div class="package-price-per">单次均价：19.9元/次</div>
        </div>
        
        <div class="package" data-package="month" data-price="29.9" data-times="10" data-price-per="2.99">
            <div class="recommend-badge">🔥 推荐</div>
            <div class="package-name">📅 月卡</div>
            <div class="package-price">¥29.9</div>
            <div class="package-times">10次 / 62天内有效</div>
            <div class="package-price-per">单次均价：2.99元/次（节省85%）</div>
        </div>
        
        <button class="btn" onclick="createOrder()">立即充值</button>
        
        <div class="loading" id="loading">⏳ 正在创建订单，请稍候...</div>
        <div class="qrcode" id="qrcode"></div>
        <div class="result" id="result"></div>
        
        <div class="info-note">
            💡 充值次数将自动添加到您的账户。
        </div>
        
        <div class="orders-link">
            <a href="/orders">📋 查看我的订单</a>
        </div>
    </div>
</div>

<script>
let selectedPackage = null;
let selectedPrice = 0;
let selectedTimes = 0;
let selectedPricePer = 0;
let tempId = null;

// 从 URL 获取 temp_id
const urlParams = new URLSearchParams(window.location.search);
tempId = urlParams.get('temp_id');

document.querySelectorAll('.package').forEach(pkg => {
    pkg.addEventListener('click', function() {
        document.querySelectorAll('.package').forEach(p => p.classList.remove('selected'));
        this.classList.add('selected');
        selectedPackage = this.dataset.package;
        selectedPrice = parseFloat(this.dataset.price);
        selectedTimes = parseInt(this.dataset.times);
        selectedPricePer = parseFloat(this.dataset.pricePer);
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
                times: selectedTimes,
                temp_id: tempId
            })
        });
        const data = await resp.json();
        
        if (!resp.ok) {
            throw new Error(data.message || '创建订单失败');
        }
        
        if (data.qrcode) {
            qrcodeDiv.innerHTML = `<img src="${data.qrcode}"><p style="margin-top:12px">请扫码支付</p><p style="font-size:12px;color:#666">订单号：${data.order_id}</p>`;
            qrcodeDiv.style.display = 'block';
            checkPaymentStatus(data.order_id, phone);
        } else if (data.pay_url) {
            window.open(data.pay_url, '_blank');
            resultDiv.innerHTML = `✅ 订单创建成功！请在新窗口完成支付<br>订单号：${data.order_id}<br><span style="font-size:12px">支付完成后请稍等，自动跳转...</span>`;
            resultDiv.style.display = 'block';
            checkPaymentStatus(data.order_id, phone);
        }
        
    } catch(e) {
        alert('错误：' + e.message);
    } finally {
        loading.style.display = 'none';
    }
}

async function checkPaymentStatus(orderId, phone) {
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
                // 跳转回首页，携带参数自动展示报告
                let url = `/?auto_report=true&phone=${encodeURIComponent(phone)}&api_key=${encodeURIComponent(data.api_key || '')}`;
                if (tempId) {
                    url += `&temp_id=${tempId}`;
                }
                window.location.href = url;
            }
        } catch(e) {
            // 继续轮询
        }
    }, 3000);
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
    temp_id = body.get("temp_id")
    
    if not phone or not package_type:
        return JSONResponse(
            status_code=400,
            content={"code": "MISSING_PARAMS", "message": "参数错误"}
        )
    
    packages = {
        "trial": {"name": "次卡", "price": 19.9, "times": 1, "days": 0},
        "month": {"name": "月卡", "price": 29.9, "times": 10, "days": 62}
    }
    
    if package_type not in packages:
        return JSONResponse(
            status_code=400,
            content={"code": "INVALID_PACKAGE", "message": "套餐不存在"}
        )
    
    pkg = packages[package_type]
    
    # 创建订单（关联 temp_id）
    order_id = database.create_recharge_order(phone, package_type, pkg["price"], pkg["times"])
    if not order_id:
        return JSONResponse(
            status_code=500,
            content={"code": "ORDER_FAILED", "message": "创建订单失败"}
        )
    
    # 保存 temp_id 到订单
    if temp_id:
        database.recharge_orders_collection.update_one(
            {"order_id": order_id},
            {"$set": {"temp_id": temp_id}}
        )
    
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
    """易支付回调接口 - 支付成功后自动充值（幂等 + 重试友好）"""
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
    
    # 幂等：已处理过的订单直接返回成功
    if order.get("status") == "paid":
        return "success"
    
    # 更新订单状态
    database.update_order_paid(order_id)
    
    phone = order.get("phone")
    times_to_add = order.get("times", 0)
    temp_id = order.get("temp_id")
    
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
            # 新用户，创建账号并充值
            days_valid = 62 if order.get("package_type") == "month" else 0
            api_key, new_balance = database.add_or_recharge_user(phone, times_to_add, days_valid)
            database.add_admin_log("system", "auto_recharge", phone, f"新用户充值，增加{times_to_add}次，订单号{order_id}")
            # 更新临时报告关联
            if temp_id:
                database.update_temp_report_phone(temp_id, phone, api_key)
    
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
                result["api_key"] = user.get("api_key", "")
                result["phone"] = phone
    
    return result


# ========== 订单记录页面 ==========
@router.get("/orders")
async def orders_page():
    """我的订单页面"""
    return HTMLResponse(content='''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>我的订单 - 征信报告分析系统</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f7fa;padding:20px}
        .container{max-width:800px;margin:0 auto}
        .card{background:#fff;border-radius:24px;padding:24px;margin-bottom:20px;box-shadow:0 4px 20px rgba(0,0,0,0.08)}
        h1{color:#1e3c72;border-bottom:3px solid #4a90e2;padding-bottom:12px;margin-bottom:20px}
        .auth-box{background:#f0f2f5;border-radius:12px;padding:16px;margin-bottom:20px}
        .auth-box input{width:100%;padding:10px;margin-bottom:10px;border:1px solid #ddd;border-radius:8px}
        button{background:#4a90e2;color:#fff;border:none;padding:10px 20px;border-radius:40px;cursor:pointer}
        table{width:100%;border-collapse:collapse;margin-top:16px}
        th,td{padding:12px;text-align:left;border-bottom:1px solid #eee}
        th{background:#f5f5f5}
        .status-paid{color:#2e7d32}
        .status-pending{color:#ed6c02}
        .empty{text-align:center;padding:40px;color:#999}
        .back-link{display:inline-block;margin-top:20px;color:#4a90e2;text-decoration:none}
    </style>
</head>
<body>
<div class="container">
    <div class="card">
        <h1>📋 我的订单</h1>
        <div class="auth-box">
            <input type="tel" id="phone" placeholder="手机号">
            <input type="text" id="apiKey" placeholder="API Key">
            <button onclick="loadOrders()">查询订单</button>
        </div>
        <div id="ordersTable"></div>
        <a href="/" class="back-link">← 返回首页</a>
    </div>
</div>

<script>
async function loadOrders() {
    const phone = document.getElementById('phone').value.trim();
    const apiKey = document.getElementById('apiKey').value.trim();
    
    if (!phone || !apiKey) {
        alert('请填写手机号和API Key');
        return;
    }
    
    try {
        const resp = await fetch('/api/user_orders', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({phone, api_key: apiKey})
        });
        const data = await resp.json();
        
        if (!resp.ok) {
            alert(data.message || '查询失败');
            return;
        }
        
        const ordersDiv = document.getElementById('ordersTable');
        if (!data.orders || data.orders.length === 0) {
            ordersDiv.innerHTML = '<div class="empty">暂无充值记录</div>';
            return;
        }
        
        let html = '<table><thead><tr><th>订单号</th><th>时间</th><th>套餐</th><th>金额</th><th>次数</th><th>状态</th></tr></thead><tbody>';
        for (const order of data.orders) {
            const time = order.created_at ? new Date(order.created_at).toLocaleString('zh-CN') : '-';
            const statusClass = order.status === 'paid' ? 'status-paid' : 'status-pending';
            const statusText = order.status === 'paid' ? '已完成' : '待支付';
            html += `<tr>
                <td>${order.order_id || '-'}</td>
                <td>${time}</td>
                <td>${order.package_type === 'trial' ? '次卡' : '月卡'}</td>
                <td>¥${order.price}</td>
                <td>${order.times}次</td>
                <td class="${statusClass}">${statusText}</td>
            </tr>`;
        }
        html += '</tbody></table>';
        ordersDiv.innerHTML = html;
    } catch(e) {
        alert('网络错误：' + e.message);
    }
}
</script>
</body>
</html>
    ''')


@router.post("/api/user_orders")
async def user_orders(request: Request):
    """获取用户订单列表"""
    body = await request.json()
    phone = body.get("phone")
    api_key = body.get("api_key")
    
    if not phone or not api_key:
        return JSONResponse(
            status_code=400,
            content={"code": "MISSING_PARAMS", "message": "参数错误"}
        )
    
    # 验证用户
    exists, user, _ = database.verify_user_exists(phone, api_key)
    if not exists:
        return JSONResponse(
            status_code=401,
            content={"code": "INVALID_CREDENTIAL", "message": "手机号或 API Key 错误"}
        )
    
    orders = database.get_orders_by_phone(phone)
    return {"orders": orders}