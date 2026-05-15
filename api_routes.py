# api_routes.py
# API 路由（含频率限制、报告清理、简版甄别、保存原始数据）

import re
import uuid
from fastapi import APIRouter, File, UploadFile, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from datetime import datetime
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
    # 修复：移除数字序号前面的多余换行
    text = re.sub(r'\n{2,}(\d+[\.\)、]|\u2460|\u2461|\u2462|\u2463|\u2464|\u2465)', r'\n\1', text)
    
    # 添加关键提示图标
    text = re.sub(r'(建议[：:])', r'💡 \1', text)
    text = re.sub(r'(风险[：:])', r'⚠️ \1', text)
    
    # 为小节标题添加 📌 图标
    lines = text.split('\n')
    formatted_lines = []
    for line in lines:
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
    api_key: str = Header(None)
):
    """分析接口 - 支持新用户免费试用，老用户API Key验证"""
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
                # 次数用完
                return JSONResponse(
                    status_code=402,
                    content={
                        "code": "INSUFFICIENT_BALANCE",
                        "message": "次数已用完，请联系管理员充值（微信:DXNBZ579）"
                    }
                )
            
            # 有效用户，扣费并返回完整报告
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

💡 19.9元/次 | 定制VIP套餐请联系管理员
📱 微信:DXNBZ579"""
            
            return JSONResponse({"success": True, "full_report": final_report})
        
        else:
            # 新用户：无API Key，返回免费试用一次的报告
            temp_api_key = f"temp_{uuid.uuid4().hex[:16]}"
            final_report = f"""让您久等了，您的专属征信解读报告已生成，请查阅~

🔑 **临时API Key**: {temp_api_key}
💰 **剩余次数**: 0（此为免费试用报告）
📅 **有效期至**: 今日
> ⚠️ **请保存此API Key，后续需充值后方可继续使用**

{report_content}

💡 19.9元/次 | 定制VIP套餐请联系管理员
📱 微信:DXNBZ579"""
            
            return JSONResponse({"success": True, "full_report": final_report, "temp_api_key": temp_api_key})
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"错误: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"code": "SERVER_ERROR", "message": f"处理失败: {str(e)}"}
        )


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
    return {"status": "ok", "version": "v0515_final", "database": db_status}