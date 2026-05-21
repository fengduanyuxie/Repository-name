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
    """
    格式化报告段落
    1. 删除所有 📌 图标（包括独立和连在一起的）
    2. 修正数字标题前的换行
    3. 标题与内容之间无多余空行
    """
    import re
    
    # 1. 删除所有 📌 图标（全局替换）
    text = text.replace('📌', '')
    
    # 2. 删除 📌 后面可能跟着的空格
    text = re.sub(r'📌\s*', '', text)
    
    # 3. 修正数字标题前的换行（将 \n\n1️⃣ 改为 \n1️⃣）
    text = re.sub(r'\n{2,}([1-9]️\d)', r'\n\1', text)
    text = re.sub(r'\n{2,}(\d+[\.\)、])', r'\n\1', text)
    
    # 4. 将数字序号 1. 2. 等转换为 1️⃣ 2️⃣ 等
    def replace_number(match):
        num = match.group(1)
        emoji_map = {
            '1': '1️⃣', '2': '2️⃣', '3': '3️⃣',
            '4': '4️⃣', '5': '5️⃣', '6': '6️⃣',
            '7': '7️⃣', '8': '8️⃣', '9': '9️⃣'
        }
        return emoji_map.get(num, num + '️⃣')
    
    text = re.sub(r'(\d+)[\.\)、]', replace_number, text)
    
    # 5. 为段落添加首行缩进
    lines = text.split('\n')
    formatted_lines = []
    
    for line in lines:
        is_title = bool(re.match(r'^[1-9]️⃣', line.strip()))
        if not line.strip():
            formatted_lines.append(line)
            continue
        if is_title:
            formatted_lines.append(line)
        else:
            if not line.startswith('    '):
                formatted_lines.append('    ' + line)
            else:
                formatted_lines.append(line)
    
    result = '\n'.join(formatted_lines)
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    return result


# ========== 用户端API ==========
@router.post("/api/analyze")
async def analyze(
    request: Request,
    file: UploadFile
):
    """分析接口 - 完全免费版，无需登录"""
    
    # 频率限制（使用IP或匿名标识）
    client_ip = request.client.host if request.client else "unknown"
    if not auth.rate_limit(client_ip, limit=10, window=60):
        remaining = auth.get_rate_limit_remaining(client_ip, limit=10, window=60)
        return JSONResponse(
            status_code=429,
            content={"code": "RATE_LIMIT", "message": f"请求过于频繁，请稍后再试。剩余可用次数: {remaining}/分钟"}
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
                    "phone": "anonymous",
                    "raw_text": md,
                    "created_at": datetime.now()
                })
        except Exception as e:
            print(f"保存原始数据失败: {e}")
        
        # 返回完整报告（免费版）
        final_report = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

免费报告已生成

如需更详细的分析或建议，欢迎联系我们：

📱1599052952（同微信）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{report_content}"""
        
        return JSONResponse({"success": True, "full_report": final_report})
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"错误: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"code": "SERVER_ERROR", "message": f"处理失败: {str(e)}"}
        )


@router.get("/api/health")
async def health():
    db_status = "connected" if database.users_collection is not None else "disconnected"
    return {"status": "ok", "version": "v051514_free", "database": db_status}