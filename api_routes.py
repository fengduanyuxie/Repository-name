# api_routes.py
# API 路由（含频率限制、报告清理、简版甄别、美化排版）

import re
from fastapi import APIRouter, File, UploadFile, HTTPException, Header, Request
from fastapi.responses import JSONResponse
import database
import credit_analysis
import auth

router = APIRouter(tags=["api"])

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
        
        stats, lines = credit_analysis.generate_report(md)
        
        raw_prompt_response = credit_analysis.call_deepseek(credit_analysis.build_llm_prompt(stats))
        
        cleaned_response = raw_prompt_response
        
        # 去除常见的开头提示语
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
        
        # 去除 Markdown 格式符号
        cleaned_response = re.sub(r'#{1,6}\s*', '', cleaned_response)           # 删除 #
        cleaned_response = re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned_response)  # 删除 **粗体**
        cleaned_response = re.sub(r'\*([^*]+)\*', r'\1', cleaned_response)      # 删除 *斜体*
        cleaned_response = re.sub(r'^[-*]\s+', '', cleaned_response, flags=re.MULTILINE)  # 删除列表符号
        cleaned_response = re.sub(r'---+', '', cleaned_response)                 # 删除分割线
        cleaned_response = re.sub(r'\n{3,}', '\n\n', cleaned_response)           # 多余空行合并
        
        cleaned_response = cleaned_response.lstrip('\n')
        
        part1 = "\n".join(lines)
        
        # 组装最终报告
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
    return {"status": "ok", "version": "v051114", "database": db_status}