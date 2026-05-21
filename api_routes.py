# api_routes.py
# API 路由（完全免费版 - 无付费功能）

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
    text = re.sub(r'(\d+[\.\)、]|\u2460|\u2461|\u2462|\u2463|\u2464|\u2465)', r'\n\n\1', text)
    text = re.sub(r'(建议[：:])', r'💡 \1', text)
    text = re.sub(r'(风险[：:])', r'⚠️ \1', text)
    
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
    """分析接口 - 完全免费版"""
    
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
    
    # 验证手机号和API Key是否提供
    if not phone or not api_key:
        return JSONResponse(
            status_code=401,
            content={"code": "MISSING_CREDENTIAL", "message": "请填写手机号和API Key。新用户请联系管理员获取API Key"}
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
        
        # 验证用户是否存在
        exists, user, _ = database.verify_user_exists(phone, api_key)
        
        if not exists:
            return JSONResponse(
                status_code=401,
                content={"code": "INVALID_CREDENTIAL", "message": "手机号或API Key错误，请核对后重试。新用户请联系管理员获取API Key"}
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
                    "phone": phone,
                    "raw_text": md,
                    "created_at": datetime.now()
                })
        except Exception as e:
            print(f"保存原始数据失败: {e}")
        
        # 返回完整报告（免费版，不扣费）
        final_report = f"""让您久等了，您的专属征信解读报告已生成，请查阅~

🔑 **您的API Key**: {api_key}

{report_content}

📱 遇到问题请联系管理员（微信:DXNBZ579）"""
        
        return JSONResponse({"success": True, "full_report": final_report})
        
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
    """验证用户凭证"""
    exists, user, _ = database.verify_user_exists(phone, api_key)
    return {"valid": exists}


@router.get("/api/health")
async def health():
    db_status = "connected" if database.users_collection is not None else "disconnected"
    return {"status": "ok", "version": "v051514_free", "database": db_status}