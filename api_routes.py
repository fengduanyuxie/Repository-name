# api_routes.py
# API 路由（含频率限制、报告清理、简版甄别、保存原始数据、支付宝AI收支付）

import re
import uuid
import json
from fastapi import APIRouter, File, UploadFile, HTTPException, Header, Request
from fastapi.responses import JSONResponse, HTMLResponse
from datetime import datetime, timedelta
import database
import credit_analysis
import auth

# 支付宝SDK
from alipay import AliPay

router = APIRouter(tags=["api"])

# ========== 支付宝配置 ==========
ALIPAY_APPID = "2021006154645338"
ALIPAY_APP_PRIVATE_KEY = """MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCSGt4g70sMO9/H
09FfyTdE+4xV6rERUMMrih6cYxU7p7yNSd0udaj2eENqgzooq5OHmr2mSZFghyzMI3upswglqy+AmV4c
BcnXUXrCcjisZQRCvUkBmka4oZPOkiyWKybzQ6VGnUG51ykzY1DVpsrIcR90tTESBK5j6rxNXSuZx+2C
VgEQw42zVsy8kYOeHSzcjGH7z7fLTERC8xJ/5EtNmdLGOsiY6sWytjsiIIuSMEzXTGn74fl6jQoH4/ZI
D5PXpHusN91hUk40vIsaWz9p6uxbBwEMC0l3AUjnkrpatd6AUzrB64SnCJMb4f2VZ5RE2lx467WTAcos
LDrA8k8HAgMBAAECggEAVt5ur/pXDsESvscsN911ZSiDOho+iWMRh/OpW6Z123BR5VfDkHoYqeK7grrf
e4r4Pqo8lIAtVc1JT17RigaOk4cCyV1m3RZ7+e/SI4ayN54gOGY+4BsQbXp0XV//7pFdqUnRHPknOQ26
y3kDeOSgsSjBYSzSLjpmTbYlm4IICHgwV/udSxTxT2irEaE3C7hKkeF8B2Emj82ceXBJtXtc0Tz77SL8
pU347kTf8YNbWL7pavuFq/+eQo5ibSyNz/GwChC1y7HeKpMBiAgr0Ddv6MArXTTH7kg/BAfOlyFTO5ZA
3ANsj+zSuh62XQPGipbJT6AhLU4x2WDfqgSrnnlpgQKBgQD0ujNTHm+dgVZj4AW8Pf0G53/0oMStUJi4
+99KiBeAI1CoFtVPSgTqCGM52Rjmjpr2Ku2sc4t+0sh+AjBVbc3c1MJtvqSRiFSUMlYHoeMu4z7LXLxI
z8hDWzjf2nbxVVt+7iEeWp92GtKdBRYT1izcJk/Va2p3juEdMGYWLFn2YQKBgQCY1bje3GjNLQI4QYW+
RtYJ5yV8L0RlXC1BQUpynT9elpWNlimIO6GOezukLNLYAiLkG/w9vUg76Y3GPzvalb/ynUhBbs5fg8ku
LvWAF1UZXimL0qdzsSNPMIMHZB6zKeXVseMBpG1FBL6cTrstEnyWyAHKfTxKdlHWZNLJHvLuZwKBgQDs
nOrqvk6kNlzUi9B/xF9TwZgRaS8/cuF2WO/3G8W8+mgNXKY41xQRQrLNR32vzMk+oRrS1ZRVtm5qhqs8
rcGQdZTWjrCGlQ1Ri6lqD7ebqdMYxDy3GU5C8Xv30z2U8DZabtpOgsgSZLSlZDmITFdrMw+VBRoXJmm4
0wahAZipgQKBgAK26Q2sRIBAaGWvZDy47VxHqrbF8CUMuhEKo9PdTx7S9d0J6brttDTfo3OLCEOl5hC/
Hn/KONo3j7kRrnJ3bm1Utc/Ts/6mTJBxbRLVV0GYFozRNQAtCT+C0RD0ikcMW3SsMCf7T6WGLAyCqXhn
d6cF7mI2TzfTWijAqa3AyvfJAoGAHHBy8JhTU0MEQbDCb2i6krPsokXIezsgfe1hS2gO+SPDZNQxW+eW
UspgglHTlViw9SRsp4jrBv8d+81gUWMBnqCxuj9GCMCol7RP5M8S6eFKxpHzkNc4u+I4n5nac2OtGM1Y
zK47MFKxtCEn7UpRIHhCo5v32LwotHLzng3w2no="""
ALIPAY_PUBLIC_KEY = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAkhreIO9LDDvfx9PRX8k3RPuMVeqxEVDDK4oenGMVO6e8jUndLnWo9nhDaoM6KKuTh5q9pkmRYIcszCN7qbMIJasvgJleHAXJ11F6wnI4rGUEQr1JAZpGuKGTzpIslism80OlRp1BudcpM2NQ1abKyHEfdLUxEgSuY+q8TV0rmcftglYBEMONs1bMvJGDnh0s3Ixh+8+3y0xEQvMSf+RLTZnSxjrImOrFsrY7IiCLkjBM10xp++H5eo0KB+P2SA+T16R7rDfdYVJONLyLGls/aersWwcBDAtJdwFI55K6WrXegFM6weuEpwiTG+H9lWeURNpceOu1kwHKLCw6wPJPBwIDAQAB"

# 初始化支付宝客户端
alipay = AliPay(
    appid=ALIPAY_APPID,
    app_notify_url=None,
    app_private_key_string=ALIPAY_APP_PRIVATE_KEY,
    alipay_public_key_string=ALIPAY_PUBLIC_KEY,
    sign_type="RSA2",
    debug=False
)


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
    text = re.sub(r'(\d+[\.\)、]|\u2460|\u2461|\u2462|\u2463|\u2464|\u2465)', r'\n\n\1', text)
    text = re.sub(r'(建议[：:])', r'💡 \1', text)
    text = re.sub(r'(风险[：:])', r'⚠️ \1', text)
    return text


# ========== 用户端API ==========
@router.post("/api/analyze")
async def analyze(
    request: Request,
    file: UploadFile,
    phone: str = Header(None),
    api_key: str = Header(None)
):
    """分析接口 - 支持新用户直接上传，老用户API Key验证"""
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
        
        # 保存原始数据
        try:
            if database.db is not None:
                raw_collection = database.db["raw_reports"]
                raw_collection.insert_one({
                    "phone": phone or "anonymous",
                    "raw_text": md,
                    "created_at": datetime.now()
                })
        except Exception as e:
            print(f"保存原始数据失败: {e}")
        
        # ========== 用户状态判断 ==========
        if phone and api_key:
            # 老用户：验证API Key
            exists, user, balance = database.verify_user_exists(phone, api_key)
            
            if not exists:
                return JSONResponse(
                    status_code=401,
                    content={"code": "INVALID_CREDENTIAL", "message": "手机号或 API Key 错误，请核对后重试，或联系管理员"}
                )
            
            if balance == 0:
                # 次数用完，返回支付二维码
                order_id = f"ORDER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
                database.save_temp_report(order_id, report_content, phone, api_key)
                
                pay_result = alipay.api_alipay_trade_precreate(
                    out_trade_no=order_id,
                    total_amount="19.90",
                    subject="征信报告分析服务",
                    body="个人简版信用报告专业分析"
                )
                
                if pay_result.get("code") == "10000":
                    qr_code = pay_result.get("qr_code", "")
                    return JSONResponse({
                        "code": "NEED_PAY",
                        "message": "次数已用完，请支付后继续使用",
                        "order_id": order_id,
                        "qr_code": qr_code,
                        "amount": "19.90"
                    })
                else:
                    return JSONResponse(
                        status_code=500,
                        content={"code": "PAY_ERROR", "message": f"创建支付订单失败: {pay_result.get('msg', '未知错误')}"}
                    )
            
            # 有效用户，扣费并返回完整报告
            database.consume_balance(phone, api_key)
            user_data = database.get_user_by_phone(phone)
            expire_date = user_data.get('expire_at', '永久')
            if isinstance(expire_date, datetime):
                expire_date = expire_date.strftime('%Y-%m-%d')
            
            final_report = f"""让您久等了，您的专属征信解读报告已生成，请查阅~

🔑 **您的API Key**: `{api_key}`
💰 **剩余次数**: {user_data.get('balance', 0)}
📅 **有效期至**: {expire_date}
> ⚠️ **请务必保存好您的API Key！**

{report_content}

💡 如需多次分析，请联系管理员定制套餐（微信:DXNBZ579）"""
            
            return JSONResponse({"success": True, "full_report": final_report})
        
        else:
            # 新用户：无API Key，先展示报告摘要 + 支付提示
            # 生成临时ID关联这份报告
            temp_id = f"TEMP_{uuid.uuid4().hex[:16]}"
            database.save_temp_report(temp_id, report_content)
            
            # 只返回第一部分（简要汇总），第二部分隐藏
            summary_only = f"""【第一部分：简要汇总】

{part1}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ **完整报告包含「结构分析」部分，需支付 19.9 元后查看**

💡 支付完成后，系统将自动为您生成API Key，并展示完整分析报告

---

**请扫描下方二维码支付 19.9 元：**

> （支付二维码将显示在此处）

支付完成后，请点击下方按钮获取完整报告：

[我已支付，获取完整报告]
"""
            
            # 创建支付订单
            order_id = f"ORDER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
            database.save_temp_report(order_id, report_content)
            
            pay_result = alipay.api_alipay_trade_precreate(
                out_trade_no=order_id,
                total_amount="19.90",
                subject="征信报告分析服务",
                body="个人简版信用报告专业分析"
            )
            
            if pay_result.get("code") == "10000":
                qr_code = pay_result.get("qr_code", "")
                return JSONResponse({
                    "code": "NEED_PAY",
                    "message": "请支付后查看完整报告",
                    "temp_id": temp_id,
                    "order_id": order_id,
                    "qr_code": qr_code,
                    "amount": "19.90",
                    "summary": summary_only
                })
            else:
                return JSONResponse(
                    status_code=500,
                    content={"code": "PAY_ERROR", "message": f"创建支付订单失败: {pay_result.get('msg', '未知错误')}"}
                )
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"错误: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"code": "SERVER_ERROR", "message": f"处理失败: {str(e)}"}
        )


@router.post("/api/pay_callback")
async def pay_callback(request: Request):
    """支付宝支付回调接口"""
    form_data = await request.form()
    params = dict(form_data)
    
    order_id = params.get("out_trade_no")
    trade_status = params.get("trade_status")
    
    if trade_status != "TRADE_SUCCESS":
        return "fail"
    
    # 获取订单信息
    temp_data = database.get_temp_report(order_id)
    if not temp_data:
        return "fail"
    
    phone = temp_data.get("phone")
    api_key = temp_data.get("api_key")
    
    if phone and api_key:
        # 老用户充值
        database.add_or_recharge_user(phone, 1, 62)
    else:
        # 新用户：生成API Key并充值
        # phone 需要从其他地方获取，这里简化处理
        # 实际应该让用户输入手机号
        pass
    
    database.delete_temp_report(order_id)
    
    return "success"


@router.post("/api/claim_report")
async def claim_report(request: Request):
    """支付后获取完整报告（新用户）"""
    body = await request.json()
    phone = body.get("phone")
    temp_id = body.get("temp_id")
    order_id = body.get("order_id")
    
    if not phone or not temp_id:
        return JSONResponse(
            status_code=400,
            content={"code": "MISSING_PARAMS", "message": "参数错误"}
        )
    
    # 查询订单支付状态
    result = alipay.api_alipay_trade_query(out_trade_no=order_id)
    
    if result.get("code") != "10000" or result.get("trade_status") != "TRADE_SUCCESS":
        return JSONResponse(
            status_code=402,
            content={"code": "NOT_PAID", "message": "订单未支付，请先完成支付"}
        )
    
    # 获取临时报告
    temp_data = database.get_temp_report(temp_id)
    if not temp_data:
        return JSONResponse(
            status_code=404,
            content={"code": "REPORT_EXPIRED", "message": "报告已过期，请重新上传"}
        )
    
    # 为用户创建账号并充值1次
    api_key, new_balance = database.add_or_recharge_user(phone, 1, 62)
    
    # 删除临时报告
    database.delete_temp_report(temp_id)
    database.delete_temp_report(order_id)
    
    report_content = temp_data.get("report", "")
    
    final_report = f"""让您久等了，您的专属征信解读报告已生成，请查阅~

🔑 **您的API Key**: `{api_key}`
💰 **剩余次数**: {new_balance}
📅 **有效期至**: 62天内有效
> ⚠️ **请务必保存好您的API Key！**

{report_content}

💡 如需多次分析，请联系管理员定制套餐（微信:DXNBZ579）"""
    
    return JSONResponse({"success": True, "full_report": final_report, "api_key": api_key})


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
    return {"status": "ok", "version": "v0514_final", "database": db_status}