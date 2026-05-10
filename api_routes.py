# api_routes.py
# API 路由

from fastapi import APIRouter, File, UploadFile, HTTPException, Header
from fastapi.responses import JSONResponse
import database
import credit_analysis

router = APIRouter(tags=["api"])

@router.post("/api/analyze")
async def analyze(file: UploadFile, phone: str = Header(...), api_key: str = Header(...)):
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
        part1 = "\n".join(lines)
        part2 = credit_analysis.call_deepseek(credit_analysis.build_llm_prompt(stats))
        
        database.consume_balance(phone, api_key)
        
        # 添加温馨提示，放在报告最前面
        full_report = "温馨提示：\n请先将解读报告复制保存，以免丢失。\n\n" + part1 + "\n\n### 第二部分 结构分析\n\n" + part2
        
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
    return {"status": "ok", "version": "v6.0_modular", "database": db_status}