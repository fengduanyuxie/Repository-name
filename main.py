# main.py
# 征信报告分析系统 - PaddleOCR-VL-1.5 云端 API 版（最终修复版）

import os
import re
import json
import requests
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import Dict, Any, Tuple
import base64

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ========== 配置 ==========
DEEPSEEK_API_KEY = "sk-196eb4e5ceae4449b1c4fd319818a4ab"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
PADDLEOCR_API_URL = "https://7ez8g52bxbp3t2m2.aistudio-app.com/layout-parsing"
PADDLEOCR_TOKEN = "9dcb8c9a6b87fb01d65549e9d7f8619299ec53a4"

MICRO_KEYWORDS = ["网商", "微众", "亿联", "金城", "裕民", "海峡", "振兴", "新网", "苏商", "中关村", "富民", "锡商", "百信", "长安", "兰州", "威海", "众邦", "蓝海", "华通", "华瑞", "友利", "美团", "度小满", "京东", "蚂蚁", "小米", "苏宁", "平安普惠", "中融", "招联", "哈银", "长银", "中原", "锦程", "苏银凯基", "南银法巴", "北银", "阳光", "新网", "众邦", "华通", "富民", "锡商", "亿联", "金城", "裕民", "中关村", "蓝海", "华瑞", "友利", "三快", "财付通", "小雨点"]
HOUSING_KEYWORDS = ["个人住房", "住房贷款", "商用房", "公积金", "住房公积金"]
CAR_KEYWORDS = ["汽车", "车贷"]
BANK_KEYWORDS = ["工商银行", "农业银行", "中国银行", "建设银行", "交通银行", "招商银行", "浦发银行", "中信银行", "光大银行", "华夏银行", "民生银行", "广发银行", "平安银行", "兴业银行", "浙商银行", "邮储银行", "北京银行", "上海银行", "江苏银行", "宁波银行", "南京银行", "杭州银行", "南昌农村商业银行", "江西万载农村商业银行"]


def clean_number(num_str: str) -> float:
    if not num_str:
        return 0.0
    try:
        return float(re.sub(r'[^\d.-]', '', str(num_str).replace(' ', '').replace('，', '').replace(',', '')))
    except:
        return 0.0


def parse_pdf_with_paddleocr(pdf_bytes: bytes) -> str:
    """调用 PaddleOCR API 解析 PDF，返回 Markdown 文本"""
    file_data = base64.b64encode(pdf_bytes).decode("ascii")
    headers = {"Authorization": f"token {PADDLEOCR_TOKEN}", "Content-Type": "application/json"}
    payload = {"file": file_data, "fileType": 0, "useLayoutDetection": True}
    
    response = requests.post(PADDLEOCR_API_URL, headers=headers, json=payload, timeout=120)
    if response.status_code != 200:
        raise Exception(f"PaddleOCR API 错误: {response.status_code}")
    
    result = response.json()
    if result.get("errorCode") != 0 and result.get("errorCode") is not None:
        raise Exception(f"PaddleOCR 业务错误: {result.get('errorMsg', '未知错误')}")
    
    full_markdown = ""
    for res in result.get("result", {}).get("layoutParsingResults", []):
        full_markdown += res.get("markdown", {}).get("text", "") + "\n"
    
    if not full_markdown:
        raise Exception("PaddleOCR 未能提取到文本内容")
    return full_markdown


def extract_gender(text: str) -> str:
    match = re.search(r'证件号码[：:]\s*(\d{17}[\dXx])', text)
    return "男" if match and int(match.group(1)[16]) % 2 == 1 else "女" if match else "未知"


def extract_age(text: str, report_date: datetime) -> int:
    match = re.search(r'证件号码[：:]\s*(\d{17}[\dXx])', text)
    if match:
        id_num = match.group(1)
        try:
            birth = datetime(int(id_num[6:10]), int(id_num[10:12]), int(id_num[12:14]))
            age = report_date.year - birth.year
            if (report_date.month, report_date.day) < (birth.month, birth.day):
                age -= 1
            return age
        except:
            pass
    return 0


def extract_marriage(text: str) -> str:
    return "已婚" if "已婚" in text else "未婚" if "未婚" in text else "未知"


def extract_report_date(text: str) -> datetime:
    match = re.search(r'报告时间[：:]\s*(\d{4})-(\d{2})-(\d{2})', text)
    return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else datetime.now()


def is_micro_institution(institution_name: str) -> bool:
    if any(bk in institution_name for bk in BANK_KEYWORDS):
        return False
    if any(kw in institution_name for kw in MICRO_KEYWORDS):
        return True
    return "银行" not in institution_name


def extract_asset_disposal(text: str) -> Tuple[int, float]:
    match = re.search(r'资产处置信息.*?余额[为]?\s*([\d,]+)', text, re.DOTALL)
    return (1, clean_number(match.group(1)) / 10000) if match else (0, 0.0)


def extract_advance_payment(text: str) -> Tuple[int, float]:
    match = re.search(r'垫款信息.*?累计代偿金额[为]?\s*([\d,]+)', text, re.DOTALL)
    return (1, clean_number(match.group(1)) / 10000) if match else (0, 0.0)


def extract_overdue(text: str) -> Dict[str, int]:
    overdue = {"total_months": 0, "90d_count": 0}
    # 总逾期月数：累加所有 "最近5年内有X个月处于逾期状态"
    for m in re.findall(r'最近\s*5\s*年内有\s*(\d+)\s*个月处于逾期状态', text):
        overdue["total_months"] += int(m)
    # 90天以上账户数：统计有多少个账户包含 "其中X个月逾期超过90天"（每个账户计1）
    # 正确值应该是出现次数，而不是累加月份数
    overdue["90d_count"] = len(re.findall(r'其中\s*\d+\s*个月逾期超过\s*90\s*天', text))
    return overdue


def extract_public_records(text: str) -> str:
    records = []
    # 欠税
    tax_match = re.search(r'欠税总额[：:]\s*([\d,]+)', text)
    if tax_match:
        records.append(f"欠税1条，金额{clean_number(tax_match.group(1))/10000:.2f}万元")
    # 民事判决 - 诉讼标的金额
    judgment_amounts = re.findall(r'诉讼标的金额[：:]\s*([\d,]+)', text)
    if judgment_amounts:
        records.append(f"民事判决{len(judgment_amounts)}件，金额{sum(clean_number(a) for a in judgment_amounts)/10000:.2f}万元")
    # 强制执行 - 申请执行标的金额
    enforcement_amounts = re.findall(r'申请执行标的金额[：:]\s*([\d,]+)', text)
    if enforcement_amounts:
        records.append(f"强制执行{len(enforcement_amounts)}件，金额{sum(clean_number(a) for a in enforcement_amounts)/10000:.2f}万元")
    # 行政处罚
    penalty_match = re.search(r'处罚金额[：:]\s*([\d,]+)', text)
    if penalty_match:
        records.append(f"行政处罚1条，金额{clean_number(penalty_match.group(1))/10000:.2f}万元")
    return "\n".join(records) if records else ""


def extract_loans_from_text(text: str) -> Dict[str, Any]:
    """只统计余额 > 0 的贷款账户"""
    loans = {"count": 0, "balance": 0.0, "housing_count": 0, "housing_balance": 0.0, "car_count": 0, "car_balance": 0.0, "micro_count": 0, "micro_balance": 0.0, "overdue_count": 0}
    
    for line in text.split('\n'):
        line = line.strip()
        if not line or not re.match(r'^\d+\.', line):
            continue
        if "发放" not in line and "授信" not in line:
            continue
        if "已结清" in line or "已转出" in line or "销户" in line:
            continue
        
        balance_match = re.search(r'余额[为]?\s*([\d,]+)', line)
        balance = clean_number(balance_match.group(1)) if balance_match else 0
        
        # 只统计余额 > 0 的账户（按用户选择 B）
        if balance <= 0:
            continue
        
        inst_match = re.search(r'\d{4}\s*年\d{1,2}\s*月\d{1,2}\s*日([^发放授信]+?)(?:发放|为)', line)
        institution = inst_match.group(1).strip() if inst_match else ""
        
        loans["count"] += 1
        loans["balance"] += balance / 10000
        
        is_housing = any(kw in line for kw in HOUSING_KEYWORDS)
        is_car = any(kw in line for kw in CAR_KEYWORDS)
        is_micro = is_micro_institution(institution) and not is_housing and not is_car
        
        if is_housing:
            loans["housing_count"] += 1
            loans["housing_balance"] += balance / 10000
        elif is_car:
            loans["car_count"] += 1
            loans["car_balance"] += balance / 10000
        elif is_micro:
            loans["micro_count"] += 1
            loans["micro_balance"] += balance / 10000
        
        if "当前有逾期" in line:
            loans["overdue_count"] += 1
    return loans


def extract_credits_from_text(text: str) -> Dict[str, Any]:
    credits = {"count": 0, "limit": 0.0, "used": 0.0, "overdue": 0, "abnormal": {"stop_payment": 0, "frozen": 0, "doubtful": 0}}
    
    for line in text.split('\n'):
        line = line.strip()
        if not line or not re.match(r'^\d+\.', line) or '贷记卡' not in line:
            continue
        if any(x in line for x in ['美元', '尚未激活', '销户']):
            continue
        
        limit_match = re.search(r'信用额度\s*([\d,]+)', line) or re.search(r'授信额度\s*([\d,]+)', line)
        if not limit_match:
            continue
        limit = clean_number(limit_match.group(1))
        used_match = re.search(r'已使用额度\s*([\d,]+)', line) or re.search(r'余额\s*([\d,]+)', line)
        used = clean_number(used_match.group(1)) if used_match else 0
        
        if limit > 0:
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
    
    credits["usage_rate"] = round((credits["used"] / credits["limit"] * 100)) if credits["limit"] > 0 else 0
    abnormal_parts = []
    if credits["abnormal"]["stop_payment"]:
        abnormal_parts.append(f"止付{credits['abnormal']['stop_payment']}个")
    if credits["abnormal"]["frozen"]:
        abnormal_parts.append(f"冻结{credits['abnormal']['frozen']}个")
    if credits["abnormal"]["doubtful"]:
        abnormal_parts.append(f"呆账{credits['abnormal']['doubtful']}个")
    credits["abnormal_display"] = "；".join(abnormal_parts)
    return credits


def extract_guarantee_from_text(text: str) -> Tuple[int, float]:
    count = 0
    balance = 0.0
    for amount_str, balance_str in re.findall(r'相关还款责任金额[为]?\s*([\d,]+).*?余额[为]?\s*([\d,]+)', text, re.DOTALL):
        count += 1
        amount = clean_number(amount_str)
        loan_balance = clean_number(balance_str)
        balance += (min(amount, loan_balance) if amount > 0 and loan_balance > 0 else amount) / 10000
    if count == 0:
        for amount_str in re.findall(r'相关还款责任金额[为]?\s*([\d,]+)', text):
            if amount_str and amount_str != '--':
                count += 1
                balance += clean_number(amount_str) / 10000
    return count, balance


def extract_queries_from_html(text: str, report_date: datetime) -> Dict[str, int]:
    """从 HTML 表格中提取查询记录"""
    queries = {"30d": 0, "31_90d": 0, "91_180d": 0, "181_360d": 0, "micro_60d": 0, "self_60d": 0}
    
    # 机构查询 - 从 HTML 表格中提取
    # 匹配模式：<td>查询日期</td><td>机构</td><td>原因</td>
    inst_pattern = r'<td style=\'text-align: center; word-wrap: break-word;\'>(\d{4}年\d{1,2}月\d{1,2}日)</td>\s*<td style=\'text-align: center; word-wrap: break-word;\'>([^<]+)</td>\s*<td style=\'text-align: center; word-wrap: break-word;\'>(贷款审批|信用卡审批|资信审查|担保资格审查|保前审查)</td>'
    
    for match in re.finditer(inst_pattern, text):
        date_str, institution, reason = match.group(1), match.group(2).strip(), match.group(3)
        # 跳过贷后管理
        if "贷后" in reason:
            continue
        try:
            date_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
            if date_match:
                y, m, d = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                query_date = datetime(y, m, d)
                diff_days = (report_date - query_date).days
                if 0 <= diff_days <= 360:
                    if diff_days <= 30:
                        queries["30d"] += 1
                    elif diff_days <= 90:
                        queries["31_90d"] += 1
                    elif diff_days <= 180:
                        queries["91_180d"] += 1
                    else:
                        queries["181_360d"] += 1
                    if diff_days <= 60 and is_micro_institution(institution):
                        queries["micro_60d"] += 1
        except:
            pass
    
    # 本人查询
    self_pattern = r'<td style=\'text-align: center; word-wrap: break-word;\'>(\d{4}年\d{1,2}月\d{1,2}日)</td>\s*<td style=\'text-align: center; word-wrap: break-word;\'>本人</td>'
    for match in re.finditer(self_pattern, text):
        date_str = match.group(1)
        try:
            date_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
            if date_match:
                y, m, d = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                query_date = datetime(y, m, d)
                diff_days = (report_date - query_date).days
                if 0 <= diff_days <= 60:
                    queries["self_60d"] += 1
        except:
            pass
    
    return queries


def build_risk_warning(asset_count, asset_balance, advance_count, advance_amount, loans, credits, public_records):
    warnings = []
    if asset_count:
        warnings.append(f"资产处置{asset_count}笔，余额{asset_balance:.2f}万元")
    if advance_count:
        warnings.append(f"垫款{advance_count}笔，金额{advance_amount:.2f}万元")
    if loans.get("overdue_count"):
        warnings.append(f"贷款当逾{loans['overdue_count']}个")
    if credits.get("overdue"):
        warnings.append(f"信用卡当逾{credits['overdue']}个")
    if credits.get("abnormal_display"):
        warnings.append(credits["abnormal_display"])
    if public_records:
        warnings.append(public_records.replace("\n", "；"))
    return "；".join(warnings) if warnings else "无"


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
    response = requests.post(DEEPSEEK_API_URL, json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.5}, headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}, timeout=120)
    if response.status_code != 200:
        raise Exception(f"DeepSeek API 错误: {response.status_code}")
    return response.json()["choices"][0]["message"]["content"]


@app.post("/api/analyze")
async def analyze(file: UploadFile):
    pdf_bytes = await file.read()
    if len(pdf_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件不能超过10MB")
    
    try:
        markdown_text = parse_pdf_with_paddleocr(pdf_bytes)
        report_date = extract_report_date(markdown_text)
        gender = extract_gender(markdown_text)
        age = extract_age(markdown_text, report_date)
        marriage = extract_marriage(markdown_text)
        
        loans = extract_loans_from_text(markdown_text)
        credits = extract_credits_from_text(markdown_text)
        guarantee_count, guarantee_balance = extract_guarantee_from_text(markdown_text)
        overdue = extract_overdue(markdown_text)
        asset_count, asset_balance = extract_asset_disposal(markdown_text)
        advance_count, advance_amount = extract_advance_payment(markdown_text)
        public_records = extract_public_records(markdown_text)
        queries = extract_queries_from_html(markdown_text, report_date)
        risk_warning = build_risk_warning(asset_count, asset_balance, advance_count, advance_amount, loans, credits, public_records)
        
        stats = {"gender": gender, "age": age, "marriage": marriage, "queries": queries, "loans": loans, "credits": credits, "overdue": overdue}
        
        # 构建报告
        report = f"""### 第一部分：简要汇总

*基本信息
性别：{gender}
年龄：{age}
婚姻：{marriage}
风险预警：{risk_warning}

*查询记录
机构
30天内：{queries['30d']}
31-90天：{queries['31_90d']}
90-180天：{queries['91_180d']}
180-360天：{queries['181_360d']}
60天内小网贷：{queries['micro_60d']}
本人
60天内本人：{queries['self_60d']}

*5年内逾期
总月数：{overdue['total_months']}
90天以上的账户数：{overdue['90d_count']}

*贷款
{f"当逾：{loans['overdue_count']}个" if loans['overdue_count'] else ""}
机构数：{loans['count']}
总余额：{round(loans['balance'], 2)}万元
{f"房贷数：{loans['housing_count']}\n房贷余额：{round(loans['housing_balance'], 2)}万元" if loans['housing_count'] else ""}
{f"车贷数：{loans['car_count']}\n车贷余额：{round(loans['car_balance'], 2)}万元" if loans['car_count'] else ""}
小网贷的机构数：{loans['micro_count']}
小网贷的余额：{round(loans['micro_balance'], 2)}万元

*信用卡
{f"当逾：{credits['overdue']}个" if credits['overdue'] else ""}
{f"非正常：{credits['abnormal_display']}" if credits['abnormal_display'] else ""}
机构数：{credits['count']}
授信额：{round(credits['limit'], 2)}万元
已用额度：{round(credits['used'], 2)}万元
使用率：{credits['usage_rate']}%

{f"*担保信息\n担保户数：{guarantee_count}\n担保余额：{round(guarantee_balance, 2)}万元" if guarantee_count or guarantee_balance else ""}

{f"*公共记录\n{public_records}" if public_records else ""}

### 第二部分：展开分析

{call_deepseek(build_llm_prompt(stats))}"""
        
        return JSONResponse({"success": True, "full_report": report})
    except Exception as e:
        print(f"错误: {str(e)}")
        raise HTTPException(500, f"处理失败: {str(e)}")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "paddleocr_v4_final"}


@app.get("/")
def frontend():
    return HTMLResponse(content='''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <title>征信报告分析系统</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;background:#f5f7fa;padding:16px}
        .container{max-width:600px;margin:0 auto;background:#fff;border-radius:24px;padding:20px;box-shadow:0 4px 20px rgba(0,0,0,0.08)}
        h1{color:#1e3c72;border-bottom:3px solid #4a90e2;padding-bottom:12px;margin-bottom:16px;font-size:22px}
        .desc{color:#666;font-size:14px;margin-bottom:20px}
        .upload-area{border:2px dashed #4a90e2;border-radius:20px;padding:40px 20px;text-align:center;background:#fafcff;margin:16px 0;cursor:pointer}
        .upload-area:hover{background:#eef4ff;border-color:#357abd}
        .upload-icon{font-size:48px;margin-bottom:12px}
        .file-name{color:#2e7d32;font-size:14px;margin-top:8px}
        input[type="file"]{display:none}
        button{background:#4a90e2;color:#fff;border:none;padding:14px 28px;border-radius:40px;font-size:16px;font-weight:500;cursor:pointer;width:100%;margin-top:8px}
        button:hover{background:#357abd}
        button:disabled{background:#ccc}
        .loading{display:none;text-align:center;margin:24px 0;color:#4a90e2}
        .result-container{display:none;margin-top:24px}
        .result{background:#f9f9f9;border-radius:16px;padding:16px;font-family:monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;max-height:500px;overflow:auto;border:1px solid #e0e0e0}
        .info-note{background:#e8f4fd;padding:12px;border-radius:12px;margin-top:20px;font-size:12px;color:#4a90e2;text-align:center}
    </style>
</head>
<body>
<div class="container">
    <h1>📄 征信结构解读</h1>
    <p class="desc">上传PDF格式的个人简版信用报告，系统将自动解析并生成专业风控报告。</p>
    <div class="upload-area" id="uploadArea">
        <div class="upload-icon">📎</div>
        <div class="upload-text">点击或拖拽上传PDF文件</div>
        <div class="file-name" id="fileName"></div>
        <input type="file" id="fileInput" accept=".pdf">
    </div>
    <button id="analyzeBtn" disabled>开始分析</button>
    <div class="loading" id="loading">正在分析，请稍候...</div>
    <div class="result-container" id="resultContainer"><div class="result" id="result"></div></div>
    <div class="info-note">💡 提示：分析结果包含两部分 — 简要汇总 + 展开分析</div>
</div>
<script>
    const uploadArea=document.getElementById('uploadArea'),fileInput=document.getElementById('fileInput'),analyzeBtn=document.getElementById('analyzeBtn'),loadingDiv=document.getElementById('loading'),resultDiv=document.getElementById('result'),resultContainer=document.getElementById('resultContainer'),fileNameSpan=document.getElementById('fileName');
    let selectedFile=null;
    function handleFile(file){
        if(!file||file.type!=='application/pdf'){alert('请上传PDF格式的文件');reset();return;}
        selectedFile=file;
        analyzeBtn.disabled=false;
        document.querySelector('.upload-icon').innerHTML='✅';
        document.querySelector('.upload-text').innerHTML='文件已就绪';
        fileNameSpan.innerHTML=file.name;
    }
    function reset(){
        document.querySelector('.upload-icon').innerHTML='📎';
        document.querySelector('.upload-text').innerHTML='点击或拖拽上传PDF文件';
        fileNameSpan.innerHTML='';
        selectedFile=null;
        analyzeBtn.disabled=true;
    }
    uploadArea.addEventListener('click',()=>fileInput.click());
    fileInput.addEventListener('change',e=>e.target.files.length>0&&handleFile(e.target.files[0]));
    uploadArea.addEventListener('dragover',e=>{e.preventDefault();uploadArea.style.background='#eef4ff';});
    uploadArea.addEventListener('dragleave',e=>{e.preventDefault();uploadArea.style.background='#fafcff';});
    uploadArea.addEventListener('drop',e=>{e.preventDefault();uploadArea.style.background='#fafcff';e.dataTransfer.files.length>0&&handleFile(e.dataTransfer.files[0]);});
    analyzeBtn.addEventListener('click',async()=>{
        if(!selectedFile)return;
        analyzeBtn.disabled=true;
        loadingDiv.style.display='block';
        resultContainer.style.display='none';
        const formData=new FormData();
        formData.append('file',selectedFile);
        try{
            const resp=await fetch('/api/analyze',{method:'POST',body:formData});
            const data=await resp.json();
            if(!resp.ok)throw new Error(data.detail||'分析失败');
            resultDiv.innerText=data.full_report;
            resultContainer.style.display='block';
            resultContainer.scrollIntoView({behavior:'smooth'});
        }catch(err){alert('错误：'+err.message);
        }finally{loadingDiv.style.display='none';analyzeBtn.disabled=false;}
    });
</script>
</body>
</html>''')


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))