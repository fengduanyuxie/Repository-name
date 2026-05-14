# api_routes.py
# API 路由（含频率限制、报告清理、简版甄别、保存原始数据、A2M智能收支付）

import re
import uuid
from fastapi import APIRouter, File, UploadFile, HTTPException, Header, Request
from fastapi.responses import JSONResponse, HTMLResponse
from datetime import datetime
import database
import credit_analysis
import auth
from a2m_payment import get_a2m_service

router = APIRouter(tags=["api"])

# 初始化A2M支付服务（从环境变量读取配置）
a2m_service = get_a2m_service()


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
    api_key: str = Header(None),
    payment_proof: str = Header(None)  # A2M支付凭证（二次请求时携带）
):
    """分析接口 - 支持A2M智能收支付"""
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
        
        # ========== A2M支付流程 ==========
        
        # 情况1：用户已提供 Payment-Proof（支付后二次请求）
        if payment_proof:
            # 从请求中解析支付凭证信息
            # 实际需要通过支付宝API验证，这里简化
            return await handle_paid_request(phone, api_key, report_content, payment_proof)
        
        # 情况2：老用户有API Key且余额充足
        if phone and api_key:
            exists, user, balance = database.verify_user_exists(phone, api_key)
            
            if not exists:
                return JSONResponse(
                    status_code=401,
                    content={"code": "INVALID_CREDENTIAL", "message": "手机号或 API Key 错误，请核对后重试，或联系管理员"}
                )
            
            if balance > 0:
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
        
        # 情况3：需要支付（新用户 或 老用户次数用完）
        # 保存临时报告
        temp_id = f"TEMP_{uuid.uuid4().hex[:16]}"
        database.save_temp_report(temp_id, report_content, phone, api_key)
        
        # 生成商户订单号
        out_trade_no = f"ORDER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        # 创建订单记录
        database.create_order(
            order_id=str(uuid.uuid4()),
            out_trade_no=out_trade_no,
            phone=phone or "new_user",
            amount="1990",  # 19.90元 = 1990分
            resource_id=f"/api/claim_report?temp_id={temp_id}",
            temp_id=temp_id
        )
        
        # 返回402 Payment-Needed响应
        if a2m_service:
            return a2m_service.create_payment_needed_response(
                out_trade_no=out_trade_no,
                amount="1990",
                resource_id=f"/api/claim_report?temp_id={temp_id}",
                goods_name="征信报告分析服务"
            )
        else:
            # A2M服务未配置，返回提示
            return JSONResponse(
                status_code=402,
                content={
                    "code": "Payment-Needed",
                    "message": "支付功能配置中，请稍后再试",
                    "out_trade_no": out_trade_no,
                    "amount": "19.90",
                    "currency": "CNY"
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


async def handle_paid_request(phone: str, api_key: str, report_content: str, payment_proof: str):
    """处理已支付用户的请求"""
    # TODO: 解析 Payment-Proof，获取 trade_no 和 out_trade_no
    # 然后调用支付宝API验证凭证
    
    # 简化实现：假设用户已支付，创建/充值账号
    if not phone:
        phone = f"user_{uuid.uuid4().hex[:8]}"
    
    # 为用户创建账号并充值1次
    new_api_key, new_balance = database.add_or_recharge_user(phone, 1, 62)
    
    user_data = database.get_user_by_phone(phone)
    expire_date = user_data.get('expire_at', '62天内')
    if isinstance(expire_date, datetime):
        expire_date = expire_date.strftime('%Y-%m-%d')
    
    final_report = f"""让您久等了，您的专属征信解读报告已生成，请查阅~

🔑 **您的API Key**: `{new_api_key}`
💰 **剩余次数**: {new_balance}
📅 **有效期至**: {expire_date}
> ⚠️ **请务必保存好您的API Key！**

{report_content}

💡 如需多次分析，请联系管理员定制套餐（微信:DXNBZ579）"""
    
    return JSONResponse({
        "success": True, 
        "full_report": final_report,
        "api_key": new_api_key,
        "balance": new_balance
    })


@router.post("/api/claim_report")
async def claim_report(request: Request):
    """支付完成后获取报告（A2M回调）"""
    body = await request.json()
    phone = body.get("phone")
    temp_id = body.get("temp_id")
    out_trade_no = body.get("out_trade_no")
    trade_no = body.get("trade_no")
    payment_proof = body.get("payment_proof")
    
    if not phone or not temp_id:
        return JSONResponse(
            status_code=400,
            content={"code": "MISSING_PARAMS", "message": "参数错误"}
        )
    
    # 验证订单状态
    order = database.get_order_by_out_trade_no(out_trade_no) if out_trade_no else None
    
    # 获取临时报告
    temp_data = database.get_temp_report(temp_id)
    if not temp_data:
        return JSONResponse(
            status_code=404,
            content={"code": "REPORT_EXPIRED", "message": "报告已过期，请重新上传"}
        )
    
    # 为用户创建账号并充值1次
    api_key, new_balance = database.add_or_recharge_user(phone, 1, 62)
    
    # 更新订单状态
    if out_trade_no:
        database.update_order_paid(out_trade_no, trade_no)
        database.update_order_fulfilled(out_trade_no)
    
    # 删除临时报告
    database.delete_temp_report(temp_id)
    
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
    return {"status": "ok", "version": "v0515_a2m", "database": db_status}