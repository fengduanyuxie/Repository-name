# main.py
# 征信报告分析系统 - PaddleOCR-VL-1.5 云端 API 版（最终完整版）

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

# 小网贷关键词（包含名称中含"银行"的小贷机构）
MICRO_KEYWORDS = [
    "网商", "微众", "亿联", "金城", "裕民", "海峡", "振兴", "新网",
    "苏商", "中关村", "富民", "锡商", "百信", "长安", "兰州",
    "威海", "众邦", "蓝海", "华通", "华瑞", "友利", "美团", "度小满",
    "京东", "蚂蚁", "小米", "苏宁", "平安普惠", "中融", "招联", "哈银",
    "长银", "中原", "锦程", "苏银凯基", "南银法巴", "北银", "阳光",
    "三快", "财付通", "小雨点", "消费金融", "海峡银行", "中关村银行",
    "锡商银行", "华瑞银行", "友利银行", "蓝海银行", "众邦银行"
]

HOUSING_KEYWORDS = ["个人住房", "住房贷款", "商用房", "公积金", "住房公积金"]
CAR_KEYWORDS = ["汽车", "车贷"]

# 传统大银行（不是小网贷）
BANK_KEYWORDS = [
    "工商银行", "农业银行", "中国银行", "建设银行", "交通银行",
    "招商银行", "浦发银行", "中信银行", "光大银行", "华夏银行",
    "民生银行", "广发银行", "平安银行", "兴业银行", "浙商银行",
    "邮储银行", "北京银行", "上海银行", "江苏银行", "宁波银行",
    "南京银行", "杭州银行", "南昌农村商业银行", "江西万载农村商业银行"
]


def clean_number(num_str: str) -> float:
    if not num_str:
        return 0.0
    try:
        cleaned = re.sub(r'[^\d.-]', '', str(num_str).replace(' ', '').replace('，', '').replace(',', ''))
        return float(cleaned) if cleaned else 0.0
    except:
        return 0.0


def parse_pdf_with_paddleocr(pdf_bytes: bytes) -> str:
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
    """判断是否为小网贷机构"""
    if any(bk in institution_name for bk in BANK_KEYWORDS):
        return False
    if any(kw in institution_name for kw in MICRO_KEYWORDS):
        return True
    if "银行" not in institution_name:
        return True
    return False


def extract_asset_disposal(text: str) -> Tuple[int, float]:
    match = re.search(r'资产处置信息.*?余额[为]?\s*([\d,]+)', text, re.DOTALL)
    return (1, clean_number(match.group(1)) / 10000) if match else (0, 0.0)


def extract_advance_payment(text: str) -> Tuple[int, float]:
    match = re.search(r'垫款信息.*?累计代偿金额[为]?\s*([\d,]+)', text, re.DOTALL)
    return (1, clean_number(match.group(1)) / 10000) if match else (0, 0.0)


def extract_overdue(text: str) -> Dict[str, int]:
    overdue = {"total_months": 0, "90d_count": 0}
    for m in re.findall(r'最近\s*5\s*年内有\s*(\d+)\s*个月处于逾期状态', text):
        overdue["total_months"] += int(m)
    overdue["90d_count"] = len(re.findall(r'其中\s*\d+\s*个月逾期超过\s*90\s*天', text))
    return overdue


def extract_public_records(text: str) -> str:
    records = []
    tax_match = re.search(r'欠税总额[：:]\s*([\d,]+)', text)
    if tax_match:
        records.append(f"欠税1条，金额{clean_number(tax_match.group(1))/10000:.2f}万元")
    
    judgment_amounts = re.findall(r'诉讼标的金额[：:]\s*([\d,]+)', text)
    if judgment_amounts:
        total = sum(clean_number(a) for a in judgment_amounts)
        records.append(f"民事判决{len(judgment_amounts)}件，金额{total/10000:.2f}万元")
    
    enforcement_amounts = re.findall(r'申请执行标的金额[：:]\s*([\d,]+)', text)
    if enforcement_amounts:
        total = sum(clean_number(a) for a in enforcement_amounts)
        records.append(f"强制执行{len(enforcement_amounts)}件，金额{total/10000:.2f}万元")
    
    penalty_match = re.search(r'处罚金额[：:]\s*([\d,]+)', text)
    if penalty_match:
        records.append(f"行政处罚1条，金额{clean_number(penalty_match.group(1))/10000:.2f}万元")
    return "\n".join(records) if records else ""


def extract_loans_from_text(text: str) -> Dict[str, Any]:
    """提取贷款信息，按机构去重，余额=0也计入"""
    institutions = {}
    
    for line in text.split('\n'):
        line = line.strip()
        if not line or not re.match(r'^\d+\.', line):
            continue
        
        # 排除信用卡行
        if "信用卡" in line or "贷记卡" in line:
            continue
        
        if "发放" not in line and "授信" not in line:
            continue
        
        # 跳过已结清、已转出、销户
        if "已结清" in line or "已转出" in line or "销户" in line:
            continue
        
        balance_match = re.search(r'余额[为]?\s*([\d,]+)', line)
        balance = clean_number(balance_match.group(1)) if balance_match else 0
        
        # 提取机构名
        institution = ""
        if "日" in line and "发放" in line:
            institution = line.split("日")[1].split("发放")[0].strip()
        elif "日" in line and "为" in line and "授信" in line:
            institution = line.split("日")[1].split("为")[0].strip()
        
        if not institution:
            continue
        
        # 判断类型
        is_housing = any(kw in line for kw in HOUSING_KEYWORDS)
        is_car = any(kw in line for kw in CAR_KEYWORDS)
        is_micro = is_micro_institution(institution) and not is_housing and not is_car
        
        if is_housing:
            loan_type = "housing"
        elif is_car:
            loan_type = "car"
        elif is_micro:
            loan_type = "micro"
        else:
            loan_type = "other"
        
        if institution not in institutions:
            institutions[institution] = {"balance": 0, "type": loan_type, "overdue": False}
        
        institutions[institution]["balance"] += balance
        if "当前有逾期" in line:
            institutions[institution]["overdue"] = True
    
    # 汇总
    loans = {
        "count": len(institutions),
        "balance": 0.0,
        "housing_count": 0,
        "housing_balance": 0.0,
        "car_count": 0,
        "car_balance": 0.0,
        "micro_count": 0,
        "micro_balance": 0.0,
        "overdue_count": 0
    }
    
    for inst, data in institutions.items():
        balance_yuan = data["balance"] / 10000
        loans["balance"] += balance_yuan
        
        if data["type"] == "housing":
            loans["housing_count"] += 1
            loans["housing_balance"] += balance_yuan
        elif data["type"] == "car":
            loans["car_count"] += 1
            loans["car_balance"] += balance_yuan
        elif data["type"] == "micro":
            loans["micro_count"] += 1
            loans["micro_balance"] += balance_yuan
        
        if data["overdue"]:
            loans["overdue_count"] += 1
    
    return loans


def extract_credits_from_text(text: str) -> Dict[str, Any]:
    """提取信用卡信息，不包括尚未激活的"""
    credits = {"count": 0, "limit": 0.0, "used": 0.0, "overdue": 0, "abnormal": {"stop_payment": 0, "frozen": 0, "doubtful": 0}}
    
    for line in text.split('\n'):
        line = line.strip()
        if not line or not re.match(r'^\d+\.', line):
            continue
        
        # 排除贷款
        if "发放" in line or "授信" in line:
            continue
        
        # 必须包含信用额度
        limit_match = re.search(r'信用额度\s*([\d,]+)', line) or re.search(r'授信额度\s*([\d,]+)', line)
        if not limit_match:
            continue
        
        # 排除销户
        if "销户" in line:
            continue
        
        # 排除尚未激活的信用卡
        if "尚未激活" in line:
            continue
        
        limit = clean_number(limit_match.group(1))
        if limit <= 0:
            continue
        
        # 提取已用额度
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
    """提取担保信息，正确处理金额为"--"的情况"""
    count = 0
    balance = 0.0
    
    # 匹配相关还款责任金额和余额
    pattern = r'相关还款责任金额[为]?\s*([\d,]+|--).*?余额[为]?\s*([\d,]+)'
    for amount_str, balance_str in re.findall(pattern, text, re.DOTALL):
        loan_balance = clean_number(balance_str)
        if amount_str == '--':
            # 责任金额为"--"，只取余额
            if loan_balance > 0:
                count += 1
                balance += loan_balance / 10000
        else:
            amount = clean_number(amount_str)
            if amount > 0 or loan_balance > 0:
                count += 1
                balance += min(amount, loan_balance) / 10000 if amount > 0 and loan_balance > 0 else amount / 10000
    
    # 如果没匹配到，尝试只匹配相关还款责任金额
    if count == 0:
        for amount_str in re.findall(r'相关还款责任金额[为]?\s*([\d,]+)', text):
            if amount_str and amount_str != '--':
                count += 1
                balance += clean_number(amount_str) / 10000
    
    return count, balance


def extract_queries_from_html(text: str, report_date: datetime) -> Dict[str, int]:
    """从 HTML 表格中提取查询记录"""
    queries = {"30d": 0, "31_90d": 0, "91_180d": 0, "181_360d": 0, "micro_60d": 0, "self_60d": 0}
    
    valid_reasons = ["贷款审批", "信用卡审批", "资信审查", "担保资格审查", "保前审查", "法人代表"]
    
    # 机构查询
    pattern = r'<td[^>]*>(\d{4}年\d{1,2}月\d{1,2}日)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>'
    
    for match in re.finditer(pattern, text):
        date_str, institution, reason = match.group(1), match.group(2).strip(), match.group(3).strip()
        
        if "贷后" in reason:
            continue
        
        is_valid = any(vr in reason for vr in valid_reasons)
        if not is_valid:
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
    self_pattern = r'<td[^>]*>(\d{4}年\d{1,2}月\d{1,2}日)</td>\s*<td[^>]*>本人</table>'
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
        report_parts = []
        report_parts.append("### 第一部分：简要汇总")
        report_parts.append("")
        report_parts.append("*基本信息")
        report_parts.append(f"性别：{gender}")
        report_parts.append(f"年龄：{age}")
        report_parts.append(f"婚姻：{marriage}")
        report_parts.append(f"风险预警：{risk_warning}")
        report_parts.append("")
        
        report_parts.append("*查询记录")
        report_parts.append("机构")
        report_parts.append(f"30天内：{queries['30d']}")
        report_parts.append(f"31-90天：{queries['31_90d']}")
        report_parts.append(f"90-180天：{queries['91_180d']}")
        report_parts.append(f"180-360天：{queries['181_360d']}")
        report_parts.append(f"60天内小网贷：{queries['micro_60d']}")
        report_parts.append("本人")
        report_parts.append(f"60天内本人：{queries['self_60d']}")
        report_parts.append("")
        
        report_parts.append("*5年内逾期")
        report_parts.append(f"总月数：{overdue['total_months']}")
        report_parts.append(f"90天以上的账户数：{overdue['90d_count']}")
        report_parts.append("")
        
        report_parts.append("*贷款")
        if loans['overdue_count']:
            report_parts.append(f"当逾：{loans['overdue_count']}个")
        report_parts.append(f"机构数：{loans['count']}")
        report_parts.append(f"总余额：{round(loans['balance'], 2)}万元")
        if loans['housing_count']:
            report_parts.append(f"房贷数：{loans['housing_count']}")
            report_parts.append(f"房贷余额：{round(loans['housing_balance'], 2)}万元")
        if loans['car_count']:
            report_parts.append(f"车贷数：{loans['car_count']}")
            report_parts.append(f"车贷余额：{round(loans['car_balance'], 2)}万元")
        report_parts.append(f"小网贷的机构数：{loans['micro_count']}")
        report_parts.append(f"小网贷的余额：{round(loans['micro_balance'], 2)}万元")
        report_parts.append("")
        
        report_parts.append("*信用卡")
        if credits['overdue']:
            report_parts.append(f"当逾：{credits['overdue']}个")
        if credits['abnormal_display']:
            report_parts.append(f"非正常：{credits['abnormal_display']}")
        if credits['count'] > 0:
            report_parts.append(f"机构数：{credits['count']}")
            report_parts.append(f"授信额：{round(credits['limit'], 2)}万元")
            report_parts.append(f"已用额度：{round(credits['used'], 2)}万元")
            report_parts.append(f"使用率：{credits['usage_rate']}%")
        report_parts.append("")
        
        if guarantee_count or guarantee_balance:
            report_parts.append("*担保信息")
            report_parts.append(f"担保户数：{guarantee_count}")
            report_parts.append(f"担保余额：{round(guarantee_balance, 2)}万元")
            report_parts.append("")
        
        if public_records:
            report_parts.append("*公共记录")
            report_parts.append(public_records)
        
        part2 = call_deepseek(build_llm_prompt(stats))
        
        full_report = "\n".join(report_parts) + "\n\n### 第二部分：展开分析\n\n" + part2
        
        return JSONResponse({"success": True, "full_report": full_report})
    except Exception as e:
        print(f"错误: {str(e)}")
        raise HTTPException(500, f"处理失败: {str(e)}")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "paddleocr_final"}


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