# api_routes.py
# API 路由

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
        stats, lines = credit_analysis.generate_report(md)
        
        # 调用 DeepSeek 生成分析内容
        raw_prompt_response = credit_analysis.call_deepseek(credit_analysis.build_llm_prompt(stats))
        
        # 清理 DeepSeek 返回的内容：删除开头的提示语和多余的标题
        cleaned_response = raw_prompt_response
        
        # 删除常见的开头提示语
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
        
        # 删除开头的空行
        cleaned_response = cleaned_response.lstrip('\n')
        
        # 构建报告：直接从"第一部分：简要汇总"开始
        part1 = "\n".join(lines)
        
        # 删除 part1 中可能存在的 "###" 前缀
        part1 = re.sub(r'^###\s*', '', part1, flags=re.MULTILINE)
        
        # 组装最终报告
        full_report = "温馨提示：\n请先将解读报告复制保存，以免丢失。\n\n" + part1 + "\n\n第二部分 结构分析\n\n" + cleaned_response
        
        database.consume_balance(phone, api_key)
        
        return JSONResponse({"success": True, "full_report": full_report})
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
    return {"status": "ok", "version": "v7.0_optimized", "database": db_status}