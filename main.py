# main.py
# 征信报告分析系统 - 使用 Supabase PostgreSQL 存储用户数据

import os
import re
import json
import base64
import secrets
import asyncpg
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import uvicorn

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ========== 配置（从环境变量读取）==========
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
PADDLEOCR_API_URL = os.environ.get("PADDLEOCR_API_URL", "https://7ez8g52bxbp3t2m2.aistudio-app.com/layout-parsing")
PADDLEOCR_TOKEN = os.environ.get("PADDLEOCR_TOKEN", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# 全局数据库连接池
db_pool = None

# ========== 数据库操作 ==========
async def init_db_pool():
    global db_pool
    if DATABASE_URL:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        await create_tables()
        print("✅ Supabase 数据库连接成功")
    else:
        print("⚠️ DATABASE_URL 未设置，用户数据将不会持久化")

async def create_tables():
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                phone TEXT PRIMARY KEY,
                api_key TEXT UNIQUE NOT NULL,
                balance INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                last_used_at TIMESTAMP
            )
        ''')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_api_key ON users(api_key)')

async def get_user_balance(phone: str, api_key: str) -> Tuple[bool, int]:
    if not db_pool:
        return False, 0
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('SELECT balance FROM users WHERE phone = $1 AND api_key = $2', phone, api_key)
        if row and row['balance'] > 0:
            return True, row['balance']
        return False, 0

async def consume_balance(phone: str, api_key: str) -> bool:
    if not db_pool:
        return False
    async with db_pool.acquire() as conn:
        result = await conn.execute(
            'UPDATE users SET balance = balance - 1, last_used_at = NOW() WHERE phone = $1 AND api_key = $2 AND balance > 0',
            phone, api_key
        )
        return 'UPDATE 1' in result

async def create_or_update_user(phone: str, api_key: str, balance: int) -> int:
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow('SELECT phone FROM users WHERE phone = $1', phone)
        if existing:
            await conn.execute('UPDATE users SET balance = balance + $1, api_key = $2 WHERE phone = $3', balance, api_key, phone)
        else:
            await conn.execute('INSERT INTO users (phone, api_key, balance) VALUES ($1, $2, $3)', phone, api_key, balance)
        row = await conn.fetchrow('SELECT balance FROM users WHERE phone = $1', phone)
        return row['balance']

def generate_api_key(phone: str) -> str:
    return f"ak_{phone[-6:]}_{secrets.token_hex(8)}"

# ========== 应用生命周期 ==========
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db_pool()
    yield
    if db_pool:
        await db_pool.close()

app.router.lifespan_context = lifespan

# ========== 关键词库 ==========
MICRO_KEYWORDS = ["网商", "微众", "亿联", "金城", "裕民", "海峡", "振兴", "新网", "苏商", "中关村", "富民", "锡商", "百信", "长安", "兰州", "威海", "众邦", "蓝海", "华通", "华瑞", "友利", "美团", "度小满", "京东", "蚂蚁", "小米", "苏宁", "平安普惠", "中融", "招联", "哈银", "长银", "中原", "锦程", "苏银凯基", "南银法巴", "北银", "阳光", "三快", "财付通", "小雨点", "消费金融", "海峡银行", "中关村银行", "锡商银行", "华瑞银行", "友利银行", "蓝海银行", "众邦银行"]
HOUSING_KEYWORDS = ["个人住房", "住房贷款", "商用房", "公积金", "住房公积金"]
CAR_KEYWORDS = ["汽车", "车贷"]
BANK_KEYWORDS = ["工商银行", "农业银行", "中国银行", "建设银行", "交通银行", "招商银行", "浦发银行", "中信银行", "光大银行", "华夏银行", "民生银行", "广发银行", "平安银行", "兴业银行", "浙商银行", "邮储银行", "北京银行", "上海银行", "江苏银行", "宁波银行", "南京银行", "杭州银行", "南昌农村商业银行", "江西万载农村商业银行"]

# ========== 辅助函数 ==========
def clean_number(num: str) -> float:
    if not num:
        return 0.0
    try:
        return float(re.sub(r'[^\d.-]', '', num.replace(',', '').replace('，', '').replace(' ', '')))
    except:
        return 0.0

def parse_pdf(pdf_bytes: bytes) -> str:
    resp = requests.post(PADDLEOCR_API_URL, 
        headers={"Authorization": f"token {PADDLEOCR_TOKEN}", "Content-Type": "application/json"},
        json={"file": base64.b64encode(pdf_bytes).decode("ascii"), "fileType": 0, "useLayoutDetection": True},
        timeout=120)
    if resp.status_code != 200:
        raise Exception(f"PaddleOCR API 错误: {resp.status_code}")
    result = resp.json()
    if result.get("errorCode"):
        raise Exception(f"PaddleOCR 业务错误: {result.get('errorMsg')}")
    md = ""
    for res in result.get("result", {}).get("layoutParsingResults", []):
        md += res.get("markdown", {}).get("text", "") + "\n"
    if not md:
        raise Exception("PaddleOCR 未能提取到文本内容")
    return md

def extract_basic_info(text: str, report_date: datetime):
    id_match = re.search(r'证件号码[：:]\s*(\d{17}[\dXx])', text)
    gender = "男" if id_match and int(id_match.group(1)[16]) % 2 == 1 else "女" if id_match else "未知"
    age = 0
    if id_match:
        try:
            birth = datetime(int(id_match.group(1)[6:10]), int(id_match.group(1)[10:12]), int(id_match.group(1)[12:14]))
            age = report_date.year - birth.year
            if (report_date.month, report_date.day) < (birth.month, birth.day):
                age -= 1
        except:
            pass
    marriage = "已婚" if "已婚" in text else "未婚" if "未婚" in text else "未知"
    return gender, age, marriage

def extract_report_date(text: str) -> datetime:
    match = re.search(r'报告时间[：:]\s*(\d{4})-(\d{2})-(\d{2})', text)
    return datetime(*map(int, match.groups())) if match else datetime.now()

def is_micro(inst: str) -> bool:
    if any(bk in inst for bk in BANK_KEYWORDS):
        return False
    return any(kw in inst for kw in MICRO_KEYWORDS) or "银行" not in inst

def extract_loans(text: str):
    insts = {}
    for line in text.split('\n'):
        line = line.strip()
        if not line or not re.match(r'^\d+\.', line) or "贷记卡" in line:
            continue
        if "发放" not in line and "授信" not in line:
            continue
        if any(x in line for x in ["已结清", "已转出", "销户"]):
            continue
        balance_match = re.search(r'余额[为]?\s*([\d,]+)', line)
        balance = clean_number(balance_match.group(1)) if balance_match else 0
        inst = ""
        if "日" in line and "发放" in line:
            inst = line.split("日")[1].split("发放")[0].strip()
        elif "日" in line and "为" in line and "授信" in line:
            inst = line.split("日")[1].split("为")[0].strip()
        if not inst:
            continue
        is_h = any(kw in line for kw in HOUSING_KEYWORDS)
        is_c = any(kw in line for kw in CAR_KEYWORDS)
        is_m = is_micro(inst) and not is_h and not is_c
        typ = "housing" if is_h else "car" if is_c else "micro" if is_m else "other"
        if inst not in insts:
            insts[inst] = {"bal": 0, "typ": typ, "ovd": False}
        insts[inst]["bal"] += balance
        if "当前有逾期" in line:
            insts[inst]["ovd"] = True
    loans = {"count": len(insts), "balance": 0.0, "housing_count": 0, "housing_balance": 0.0,
             "car_count": 0, "car_balance": 0.0, "micro_count": 0, "micro_balance": 0.0, "overdue_count": 0}
    for data in insts.values():
        bal_yuan = data["bal"] / 10000
        loans["balance"] += bal_yuan
        if data["typ"] == "housing":
            loans["housing_count"] += 1
            loans["housing_balance"] += bal_yuan
        elif data["typ"] == "car":
            loans["car_count"] += 1
            loans["car_balance"] += bal_yuan
        elif data["typ"] == "micro":
            loans["micro_count"] += 1
            loans["micro_balance"] += bal_yuan
        if data["ovd"]:
            loans["overdue_count"] += 1
    return loans

def extract_credits(text: str):
    credits = {"count": 0, "limit": 0.0, "used": 0.0, "overdue": 0, "abnormal": {"stop_payment": 0, "frozen": 0, "doubtful": 0}}
    for line in text.split('\n'):
        line = line.strip()
        if not line or "贷记卡" not in line:
            continue
        if any(x in line for x in ["美元", "销户", "尚未激活"]):
            continue
        limit_match = re.search(r'信用额度\s*([\d,]+)', line)
        if not limit_match:
            continue
        limit = clean_number(limit_match.group(1))
        used_match = re.search(r'已使用额度\s*([\d,]+)', line) or re.search(r'余额\s*([\d,]+)', line)
        used = clean_number(used_match.group(1)) if used_match else 0
        credits["count"] += 1
        credits["limit"] += limit / 10000
        credits["used"] += used / 10000
        if "当前有逾期" in line:
            credits["overdue"] += 1
        if "呆账" in line:
            credits["abnormal"]["doubtful"] += 1
        if "止付" in line:
            credits["abnormal"]["stop_payment"] += 1
        if "冻结" in line:
            credits["abnormal"]["frozen"] += 1
    credits["usage_rate"] = round(credits["used"] / credits["limit"] * 100) if credits["limit"] > 0 else 0
    abnormal = []
    if credits["abnormal"]["stop_payment"]:
        abnormal.append(f"止付{credits['abnormal']['stop_payment']}个")
    if credits["abnormal"]["frozen"]:
        abnormal.append(f"冻结{credits['abnormal']['frozen']}个")
    if credits["abnormal"]["doubtful"]:
        abnormal.append(f"呆账{credits['abnormal']['doubtful']}个")
    credits["abnormal_display"] = "；".join(abnormal)
    return credits

def extract_guarantee(text: str):
    count, balance = 0, 0.0
    for amt_str, bal_str in re.findall(r'相关还款责任金额[为]?\s*([\d,]+|--).*?余额[为]?\s*([\d,]+)', text, re.DOTALL):
        loan_bal = clean_number(bal_str)
        if amt_str == '--':
            if loan_bal > 0:
                count += 1
                balance += loan_bal / 10000
        else:
            amt = clean_number(amt_str)
            if amt > 0 or loan_bal > 0:
                count += 1
                balance += (min(amt, loan_bal) if amt > 0 and loan_bal > 0 else amt) / 10000
    if count == 0:
        for amt_str in re.findall(r'相关还款责任金额[为]?\s*([\d,]+)', text):
            if amt_str and amt_str != '--':
                count += 1
                balance += clean_number(amt_str) / 10000
    return count, balance

def extract_queries(text: str, report_date: datetime):
    queries = {"30d": 0, "31_90d": 0, "91_180d": 0, "181_360d": 0, "micro_60d": 0, "self_60d": 0}
    valid_reasons = ["贷款审批", "信用卡审批", "资信审查", "担保资格审查", "保前审查", "法人代表"]
    pattern_with_id = r'<td[^>]*>\d+</td>\s*<td[^>]*>(\d{4}年\d{1,2}月\d{1,2}日)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>'
    pattern_no_id = r'<td[^>]*>(\d{4}年\d{1,2}月\d{1,2}日)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>'
    matches = re.findall(pattern_with_id, text) or re.findall(pattern_no_id, text)
    for date_str, institution, reason in matches:
        if "贷后" in reason or not any(v in reason for v in valid_reasons):
            continue
        try:
            y, m, d = map(int, re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str).groups())
            diff = (report_date - datetime(y, m, d)).days
            if 0 <= diff <= 360:
                if diff <= 30:
                    queries["30d"] += 1
                elif diff <= 90:
                    queries["31_90d"] += 1
                elif diff <= 180:
                    queries["91_180d"] += 1
                else:
                    queries["181_360d"] += 1
                if diff <= 60 and is_micro(institution.strip()):
                    queries["micro_60d"] += 1
        except:
            pass
    self_pattern = r'<td[^>]*>\d+</td>\s*<td[^>]*>(\d{4}年\d{1,2}月\d{1,2}日)</td>\s*<td[^>]*>本人</td>'
    for match in re.finditer(self_pattern, text):
        try:
            y, m, d = map(int, re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', match.group(1)).groups())
            if 0 <= (report_date - datetime(y, m, d)).days <= 60:
                queries["self_60d"] += 1
        except:
            pass
    return queries

def extract_overdue(text: str):
    total = sum(int(m) for m in re.findall(r'最近\s*5\s*年内有\s*(\d+)\s*个月处于逾期状态', text))
    cnt = len(re.findall(r'其中\s*\d+\s*个月逾期超过\s*90\s*天', text))
    return {"total_months": total, "90d_count": cnt}

def extract_public_records(text: str):
    records = []
    tax = re.search(r'欠税总额[：:]\s*([\d,]+)', text)
    if tax:
        records.append(f"欠税1条，金额{clean_number(tax.group(1))/10000:.2f}万元")
    jud = re.findall(r'诉讼标的金额[：:]\s*([\d,]+)', text)
    if jud:
        records.append(f"民事判决{len(jud)}件，金额{sum(clean_number(a) for a in jud)/10000:.2f}万元")
    enf = re.findall(r'申请执行标的金额[：:]\s*([\d,]+)', text)
    if enf:
        records.append(f"强制执行{len(enf)}件，金额{sum(clean_number(a) for a in enf)/10000:.2f}万元")
    pen = re.search(r'处罚金额[：:]\s*([\d,]+)', text)
    if pen:
        records.append(f"行政处罚1条，金额{clean_number(pen.group(1))/10000:.2f}万元")
    return "\n".join(records)

def extract_asset_disposal(text: str):
    m = re.search(r'资产处置信息.*?余额[为]?\s*([\d,]+)', text, re.DOTALL)
    return (1, clean_number(m.group(1))/10000) if m else (0, 0.0)

def extract_advance_payment(text: str):
    m = re.search(r'垫款信息.*?累计代偿金额[为]?\s*([\d,]+)', text, re.DOTALL)
    return (1, clean_number(m.group(1))/10000) if m else (0, 0.0)

def build_risk_warning(asset_cnt, asset_bal, adv_cnt, adv_amt, loans, credits, pub_rec):
    warns = []
    if asset_cnt:
        warns.append(f"资产处置{asset_cnt}笔，余额{asset_bal:.2f}万元")
    if adv_cnt:
        warns.append(f"垫款{adv_cnt}笔，金额{adv_amt:.2f}万元")
    if loans.get("overdue_count"):
        warns.append(f"贷款当逾{loans['overdue_count']}个")
    if credits.get("overdue"):
        warns.append(f"信用卡当逾{credits['overdue']}个")
    if credits.get("abnormal_display"):
        warns.append(credits["abnormal_display"])
    if pub_rec:
        warns.append(pub_rec.replace("\n", "；"))
    return "；".join(warns) if warns else "无"

def build_llm_prompt(stats):
    q, l, c, o = stats["queries"], stats["loans"], stats["credits"], stats["overdue"]
    return f"""你是一名资深的助贷风控专家。请基于以下【真实统计数据】生成专业征信分析报告（仅第二部分：展开分析）。

### 基础信息
- 性别：{stats['gender']}，年龄：{stats['age']}，婚姻：{stats['marriage']}

### 查询记录
- 30天内：{q['30d']}次，31-90天：{q['31_90d']}次，91-180天：{q['91_180d']}次，181-360天：{q['181_360d']}次
- 60天内小网贷查询：{q['micro_60d']}次，60天内本人查询：{q['self_60d']}次

### 贷款数据
- 总机构数：{l['count']}家，总余额：{round(l['balance'], 2)}万元
- 房贷：{l['housing_count']}笔，余额：{round(l['housing_balance'], 2)}万元
- 车贷：{l['car_count']}笔，余额：{round(l['car_balance'], 2)}万元
- 小网贷：{l['micro_count']}家，余额：{round(l['micro_balance'], 2)}万元
- 当前逾期：{l['overdue_count']}个

### 信用卡数据
- 机构数：{c['count']}家，授信额：{round(c['limit'], 2)}万元，已用额度：{round(c['used'], 2)}万元，使用率：{c['usage_rate']}%
- 当前逾期：{c['overdue']}个

### 逾期记录
- 总逾期月数：{o['total_months']}个月，90天以上账户：{o['90d_count']}个

请按以下结构输出：1.基本信息解读 2.查询记录分析 3.逾期记录分析 4.贷款信息分析 5.信用卡信息分析 6.综合评估与风控建议。每个判断都要有数据支撑。"""

def call_deepseek(prompt: str) -> str:
    resp = requests.post(DEEPSEEK_API_URL, 
        json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.5},
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
        timeout=120)
    if resp.status_code != 200:
        raise Exception(f"DeepSeek API 错误: {resp.status_code}")
    return resp.json()["choices"][0]["message"]["content"]

# ========== API 接口 ==========
@app.post("/api/analyze")
async def analyze(file: UploadFile, phone: str = Header(...), api_key: str = Header(...)):
    valid, balance = await get_user_balance(phone, api_key)
    if not valid:
        raise HTTPException(401, detail="无效的手机号或 API Key，或次数已用完")
    
    pdf_bytes = await file.read()
    if len(pdf_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件不能超过10MB")
    
    try:
        md = parse_pdf(pdf_bytes)
        report_date = extract_report_date(md)
        gender, age, marriage = extract_basic_info(md, report_date)
        
        loans = extract_loans(md)
        credits = extract_credits(md)
        g_cnt, g_bal = extract_guarantee(md)
        overdue = extract_overdue(md)
        a_cnt, a_bal = extract_asset_disposal(md)
        ad_cnt, ad_amt = extract_advance_payment(md)
        pub_rec = extract_public_records(md)
        queries = extract_queries(md, report_date)
        risk_warn = build_risk_warning(a_cnt, a_bal, ad_cnt, ad_amt, loans, credits, pub_rec)
        
        stats = {"gender": gender, "age": age, "marriage": marriage, "queries": queries, "loans": loans, "credits": credits, "overdue": overdue}
        
        lines = [
            "### 第一部分：简要汇总", "",
            "*基本信息", f"性别：{gender}", f"年龄：{age}", f"婚姻：{marriage}", f"风险预警：{risk_warn}", "",
            "*查询记录", "机构", f"30天内：{queries['30d']}", f"31-90天：{queries['31_90d']}", f"90-180天：{queries['91_180d']}", f"180-360天：{queries['181_360d']}", f"60天内小网贷：{queries['micro_60d']}", "本人", f"60天内本人：{queries['self_60d']}", "",
            "*5年内逾期", f"总月数：{overdue['total_months']}", f"90天以上的账户数：{overdue['90d_count']}", "",
            "*贷款"
        ]
        if loans['overdue_count']:
            lines.append(f"当逾：{loans['overdue_count']}个")
        if loans['count'] == 0 and loans['balance'] == 0:
            lines.append("无")
        else:
            lines.extend([f"机构数：{loans['count']}", f"总余额：{round(loans['balance'], 2)}万元"])
            if loans['housing_count']:
                lines.extend([f"房贷数：{loans['housing_count']}", f"房贷余额：{round(loans['housing_balance'], 2)}万元"])
            if loans['car_count']:
                lines.extend([f"车贷数：{loans['car_count']}", f"车贷余额：{round(loans['car_balance'], 2)}万元"])
            lines.extend([f"小网贷的机构数：{loans['micro_count']}", f"小网贷的余额：{round(loans['micro_balance'], 2)}万元"])
        lines.append("")
        
        lines.append("*信用卡")
        if credits['overdue']:
            lines.append(f"当逾：{credits['overdue']}个")
        if credits['abnormal_display']:
            lines.append(f"非正常：{credits['abnormal_display']}")
        if credits['count'] == 0 and credits['limit'] == 0 and credits['used'] == 0:
            lines.append("无")
        else:
            lines.extend([f"机构数：{credits['count']}", f"授信额：{round(credits['limit'], 2)}万元", f"已用额度：{round(credits['used'], 2)}万元", f"使用率：{credits['usage_rate']}%"])
        lines.append("")
        
        if g_cnt or g_bal:
            lines.extend(["*担保信息", f"担保户数：{g_cnt}", f"担保余额：{round(g_bal, 2)}万元", ""])
        if pub_rec:
            lines.extend(["*公共记录", pub_rec])
        
        part1 = "\n".join(lines)
        part2 = call_deepseek(build_llm_prompt(stats))
        
        await consume_balance(phone, api_key)
        
        return JSONResponse({"success": True, "full_report": part1 + "\n\n### 第二部分：展开分析\n\n" + part2})
    except Exception as e:
        print(f"错误: {str(e)}")
        raise HTTPException(500, f"处理失败: {str(e)}")

# ========== 管理后台 ==========
@app.get("/admin")
async def admin_page():
    return HTMLResponse(content='''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <title>管理后台</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f0f2f5;padding:20px}
        .container{max-width:500px;margin:0 auto;background:#fff;border-radius:16px;padding:24px;box-shadow:0 2px 10px rgba(0,0,0,0.1)}
        h1{color:#1e3c72;margin-bottom:24px;font-size:22px;border-bottom:2px solid #4a90e2;padding-bottom:12px}
        .form-group{margin-bottom:20px}
        label{display:block;margin-bottom:8px;color:#333;font-weight:500}
        input{width:100%;padding:12px;border:1px solid #ddd;border-radius:8px;font-size:16px}
        button{width:100%;padding:12px;background:#4a90e2;color:#fff;border:none;border-radius:8px;font-size:16px;cursor:pointer}
        button:hover{background:#357abd}
        .result{margin-top:20px;padding:16px;border-radius:8px;display:none}
        .result.success{background:#e8f8f0;border:1px solid #2e7d32;display:block}
        .result.error{background:#ffebee;border:1px solid #c62828;display:block}
        .api-key{font-family:monospace;word-break:break-all;background:#fff;padding:8px;border-radius:4px;margin-top:8px}
    </style>
</head>
<body>
<div class="container">
    <h1>🔐 用户管理后台</h1>
    <div class="form-group"><label>管理员密码</label><input type="password" id="adminPassword" placeholder="输入管理员密码"></div>
    <div class="form-group"><label>手机号</label><input type="tel" id="phone" placeholder="例如: 13812345678"></div>
    <div class="form-group"><label>充值次数</label><input type="number" id="balance" value="10"></div>
    <button onclick="generateKey()">生成 API Key</button>
    <div id="result" class="result"></div>
</div>
<script>
async function generateKey() {
    const password = document.getElementById('adminPassword').value;
    const phone = document.getElementById('phone').value;
    const balance = document.getElementById('balance').value;
    const resultDiv = document.getElementById('result');
    if (!password || !phone) {
        resultDiv.className = 'result error';
        resultDiv.innerHTML = '❌ 请填写管理员密码和手机号';
        return;
    }
    try {
        const resp = await fetch('/admin/add_user', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: new URLSearchParams({password, phone, balance})
        });
        const data = await resp.json();
        if (resp.ok) {
            resultDiv.className = 'result success';
            resultDiv.innerHTML = `✅ 用户创建成功！<br>手机号: ${data.phone}<br>API Key: <strong class="api-key">${data.api_key}</strong><br>剩余次数: ${data.balance}`;
            document.getElementById('phone').value = '';
        } else {
            resultDiv.className = 'result error';
            resultDiv.innerHTML = `❌ ${data.detail || '操作失败'}`;
        }
    } catch (err) {
        resultDiv.className = 'result error';
        resultDiv.innerHTML = `❌ 网络错误: ${err.message}`;
    }
}
</script>
</body>
</html>
    ''')

@app.post("/admin/add_user")
async def add_user(password: str = Form(...), phone: str = Form(...), balance: int = Form(10)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(403, detail="密码错误")
    if not phone or balance <= 0:
        raise HTTPException(400, detail="参数错误")
    api_key = generate_api_key(phone)
    new_balance = await create_or_update_user(phone, api_key, balance)
    return {"success": True, "phone": phone, "api_key": api_key, "balance": new_balance}

# ========== 其他接口 ==========
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "v4.0_supabase"}

@app.get("/")
async def frontend():
    return HTMLResponse(content='''
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>征信报告分析系统</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,sans-serif;background:#f5f7fa;padding:16px}.container{max-width:600px;margin:0 auto;background:#fff;border-radius:24px;padding:20px}.auth-box{background:#f0f2f5;border-radius:12px;padding:16px;margin-bottom:20px}.auth-box input{width:100%;padding:10px;margin-bottom:10px;border:1px solid #ddd;border-radius:8px}.upload-area{border:2px dashed #4a90e2;border-radius:20px;padding:40px 20px;text-align:center;cursor:pointer}.upload-icon{font-size:48px}button{background:#4a90e2;color:#fff;border:none;padding:14px;border-radius:40px;width:100%;margin-top:8px;cursor:pointer}.result{background:#f9f9f9;border-radius:16px;padding:16px;font-family:monospace;font-size:12px;white-space:pre-wrap;max-height:500px;overflow:auto}</style>
</head>
<body>
<div class="container">
    <h1>📄 征信结构解读</h1>
    <div class="auth-box">
        <input type="tel" id="phone" placeholder="手机号">
        <input type="text" id="apiKey" placeholder="API Key">
    </div>
    <div class="upload-area" id="uploadArea">
        <div class="upload-icon">📎</div>
        <div>点击或拖拽上传PDF文件</div>
        <div id="fileName"></div>
        <input type="file" id="fileInput" accept=".pdf" style="display:none">
    </div>
    <button id="analyzeBtn" disabled>开始分析</button>
    <div class="result" id="result" style="display:none"></div>
</div>
<script>
const phoneInput=document.getElementById('phone'),apiKeyInput=document.getElementById('apiKey');
let selectedFile=null;
function checkAuth(){document.getElementById('analyzeBtn').disabled=!(selectedFile&&phoneInput.value&&apiKeyInput.value);}
phoneInput.addEventListener('input',checkAuth);
apiKeyInput.addEventListener('input',checkAuth);
document.getElementById('uploadArea').addEventListener('click',()=>document.getElementById('fileInput').click());
document.getElementById('fileInput').addEventListener('change',e=>{if(e.target.files[0]){selectedFile=e.target.files[0];document.getElementById('fileName').innerHTML=selectedFile.name;checkAuth();}});
document.getElementById('analyzeBtn').addEventListener('click',async()=>{
    const fd=new FormData();fd.append('file',selectedFile);
    document.getElementById('analyzeBtn').disabled=true;
    document.getElementById('result').style.display='block';
    document.getElementById('result').innerHTML='正在分析...';
    try{
        const resp=await fetch('/api/analyze',{method:'POST',headers:{'phone':phoneInput.value,'api-key':apiKeyInput.value},body:fd});
        const data=await resp.json();
        if(!resp.ok)throw new Error(data.detail);
        document.getElementById('result').innerHTML=data.full_report;
    }catch(err){document.getElementById('result').innerHTML='错误：'+err.message;}
    finally{document.getElementById('analyzeBtn').disabled=false;}
});
</script>
</body>
</html>
    ''')

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))