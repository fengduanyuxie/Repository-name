# api_routes.py
# API 路由（含频率限制、报告清理、简版甄别、保存原始数据、A2M智能收支付）

import re
import uuid
from fastapi import APIRouter, File, UploadFile, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from datetime import datetime
import database
import credit_analysis
import auth
from a2m_payment import get_a2m_service

router = APIRouter(tags=["api"])

# 初始化A2M支付服务
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
    """
    格式化报告段落，添加空行和图标
    修正数字序号后多余换行的问题
    """
    # 修复：移除数字序号前面的多余换行
    # 将 \n\n1️⃣ 改为 \n1️⃣
    text = re.sub(r'\n{2,}(\d+[\.\)、]|\u2460|\u2461|\u2462|\u2463|\u2464|\u2465)', r'\n\1', text)
    
    # 添加关键提示图标
    text = re.sub(r'(建议[：:])', r'💡 \1', text)
    text = re.sub(r'(风险[：:])', r'⚠️ \1', text)
    
    # 为小节标题添加 📌 图标（如果没有的话）
    lines = text.split('\n')
    formatted_lines = []
    for line in lines:
        # 匹配数字序号开头的小节标题
        if re.match(r'^\d+[\.\)、]', line) or re.match(r'^[\u2460-\u2465]', line):
            if not line.startswith('📌'):
                line = '📌 ' + line
        formatted_lines.append(line)
    
    return '\n'.join(formatted_lines)


# ========== 用户端API ==========
@router.post("/api/analyze")
async def analyze(
    request: Request,
    file: UploadFile, 
    phone: str = Header(None), 
    api_key: str = Header(None),
    payment_proof: str = Header(None)
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
            # 从请求中解析支付凭证信息，实际需要完整验证
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
                # 有效用户，扣费并返回完整报告（去掉API Key的引号）
                database.consume_balance(phone, api_key)
                user_data = database.get_user_by_phone(phone)
                expire_date = user_data.get('expire_at', '永久')
                if isinstance(expire_date, datetime):
                    expire_date = expire_date.strftime('%Y-%m-%d')
                
                final_report = f"""让您久等了，您的专属征信解读报告已生成，请查阅~

🔑 **您的API Key**: {api_key}
💰 **剩余次数**: {user_data.get('balance', 0)}
📅 **有效期至**: {expire_date}
> ⚠️ **请务必保存好您的API Key！**

{report_content}

💡 定价：19.9元/次 | 定制VIP套餐请联系
📱 管理员微信:DXNBZ579"""
                
                return JSONResponse({"success": True, "full_report": final_report})
        
        # 情况3：需要支付（新用户 或 老用户次数用完）
        temp_id = f"TEMP_{uuid.uuid4().hex[:16]}"
        database.save_temp_report(temp_id, report_content, phone, api_key)
        
        out_trade_no = f"ORDER_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        database.create_order(
            order_id=str(uuid.uuid4()),
            out_trade_no=out_trade_no,
            phone=phone or "new_user",
            amount="1990",
            resource_id=f"/api/claim_report?temp_id={temp_id}",
            temp_id=temp_id
        )
        
        if a2m_service:
            return a2m_service.create_payment_needed_response(
                out_trade_no=out_trade_no,
                amount="1990",
                resource_id=f"/api/claim_report?temp_id={temp_id}",
                goods_name="征信报告分析服务"
            )
        else:
            return JSONResponse(
                status_code=402,
                content={
                    "code": "Payment-Needed",
                    "message": "需要支付",
                    "out_trade_no": out_trade_no,
                    "amount": "19.90",
                    "currency": "CNY",
                    "goods_name": "征信报告分析服务"
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
    """处理已支付用户的请求（完整验证）"""
    # 解析 Payment-Proof
    try:
        import base64
        decoded = base64.urlsafe_b64decode(payment_proof + '==').decode('utf-8')
        import json
        proof_data = json.loads(decoded)
        
        protocol = proof_data.get("protocol", {})
        payment_proof_value = protocol.get("payment_proof")
        trade_no = protocol.get("trade_no")
        out_trade_no = protocol.get("out_trade_no")
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"code": "INVALID_PAYMENT_PROOF", "message": f"支付凭证解析失败: {str(e)}"}
        )
    
    if not payment_proof_value or not trade_no:
        return JSONResponse(
            status_code=400,
            content={"code": "INVALID_PAYMENT_PROOF", "message": "支付凭证缺少必要字段"}
        )
    
    # 调用支付宝API验证凭证
    if a2m_service:
        verify_result = a2m_service.verify_payment_proof(
            payment_proof=payment_proof_value,
            trade_no=trade_no,
            out_trade_no=out_trade_no or ""
        )
        
        if not verify_result.get("success") or not verify_result.get("active"):
            return JSONResponse(
                status_code=400,
                content={"code": "INVALID_PAYMENT_PROOF", "message": f"支付凭证无效: {verify_result.get('error')}"}
            )
        
        # 更新订单状态
        if out_trade_no:
            database.update_order_paid(out_trade_no, trade_no)
            database.update_order_fulfilled(out_trade_no)
            
            # 发送履约确认
            a2m_service.send_fulfillment_confirm(trade_no)
    
    # 为用户创建账号并充值
    if not phone:
        phone = f"user_{uuid.uuid4().hex[:8]}"
    
    new_api_key, new_balance = database.add_or_recharge_user(phone, 1, 62)
    
    user_data = database.get_user_by_phone(phone)
    expire_date = user_data.get('expire_at', '62天内')
    if isinstance(expire_date, datetime):
        expire_date = expire_date.strftime('%Y-%m-%d')
    
    # 去掉API Key的引号
    final_report = f"""让您久等了，您的专属征信解读报告已生成，请查阅~

🔑 **您的API Key**: {new_api_key}
💰 **剩余次数**: {new_balance}
📅 **有效期至**: {expire_date}
> ⚠️ **请务必保存好您的API Key！**

{report_content}

💡 定价：19.9元/次 | 定制VIP套餐请联系
📱 管理员微信:DXNBZ579"""
    
    return JSONResponse({
        "success": True, 
        "full_report": final_report,
        "api_key": new_api_key,
        "balance": new_balance
    })


@router.post("/api/claim_report")
async def claim_report(request: Request):
    """支付完成后获取报告"""
    body = await request.json()
    phone = body.get("phone")
    temp_id = body.get("temp_id")
    out_trade_no = body.get("out_trade_no")
    trade_no = body.get("trade_no")
    
    if not phone or not temp_id:
        return JSONResponse(
            status_code=400,
            content={"code": "MISSING_PARAMS", "message": "参数错误"}
        )
    
    temp_data = database.get_temp_report(temp_id)
    if not temp_data:
        return JSONResponse(
            status_code=404,
            content={"code": "REPORT_EXPIRED", "message": "报告已过期，请重新上传"}
        )
    
    # 检查是否已履约（防重放）
    if out_trade_no and database.is_order_already_fulfilled(out_trade_no):
        return JSONResponse(
            status_code=400,
            content={"code": "ALREADY_FULFILLED", "message": "订单已履约"}
        )
    
    # 为用户创建账号并充值
    new_api_key, new_balance = database.add_or_recharge_user(phone, 1, 62)
    
    if out_trade_no:
        database.update_order_paid(out_trade_no, trade_no)
        database.update_order_fulfilled(out_trade_no)
        
        if a2m_service and trade_no:
            a2m_service.send_fulfillment_confirm(trade_no)
    
    database.delete_temp_report(temp_id)
    report_content = temp_data.get("report", "")
    
    # 去掉API Key的引号
    final_report = f"""让您久等了，您的专属征信解读报告已生成，请查阅~

🔑 **您的API Key**: {new_api_key}
💰 **剩余次数**: {new_balance}
📅 **有效期至**: 62天内有效
> ⚠️ **请务必保存好您的API Key！**

{report_content}

💡 定价：19.9元/次 | 定制VIP套餐请联系
📱 管理员微信:DXNBZ579"""
    
    return JSONResponse({"success": True, "full_report": final_report, "api_key": new_api_key})


@router.get("/api/order_status/{out_trade_no}")
async def order_status(out_trade_no: str):
    """查询订单支付状态（前端轮询用）"""
    # 先从数据库查询
    order = database.get_order_by_out_trade_no(out_trade_no)
    if not order:
        return JSONResponse({"status": "not_found", "message": "订单不存在"})
    
    if order.get("status") == "paid" or order.get("status") == "fulfilled":
        return JSONResponse({
            "status": "paid",
            "out_trade_no": out_trade_no,
            "trade_no": order.get("trade_no")
        })
    
    # 如果数据库中是pending，调用支付宝查询
    if a2m_service:
        result = a2m_service.query_order_status(out_trade_no)
        if result.get("status") == "paid":
            database.update_order_paid(out_trade_no, result.get("trade_no"))
            return JSONResponse({
                "status": "paid",
                "out_trade_no": out_trade_no,
                "trade_no": result.get("trade_no")
            })
    
    return JSONResponse({"status": "pending"})


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