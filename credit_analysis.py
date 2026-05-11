# credit_analysis.py
# 征信分析核心逻辑（精度优化版：先加后除）

import re
import base64
from datetime import datetime
from typing import Dict, Any, Tuple
import requests
import config

# ========== 关键词库 ==========
MICRO_KEYWORDS = ["网商", "微众", "亿联", "金城", "裕民", "海峡", "振兴", "新网", "苏商", "中关村", "富民", "锡商", "百信", "长安", "兰州", "威海", "众邦", "蓝海", "华通", "华瑞", "友利", "美团", "度小满", "京东", "蚂蚁", "小米", "苏宁", "平安普惠", "中融", "招联", "哈银", "长银", "中原", "锦程", "苏银凯基", "南银法巴", "北银", "阳光", "三快", "财付通", "小雨点", "消费金融", "海峡银行", "中关村银行", "锡商银行", "华瑞银行", "友利银行", "蓝海银行", "众邦银行"]
HOUSING_KEYWORDS = ["个人住房", "住房贷款", "商用房", "公积金", "住房公积金"]
CAR_KEYWORDS = ["汽车", "车贷"]
BANK_KEYWORDS = ["工商银行", "农业银行", "中国银行", "建设银行", "交通银行", "招商银行", "浦发银行", "中信银行", "光大银行", "华夏银行", "民生银行", "广发银行", "平安银行", "兴业银行", "浙商银行", "邮储银行", "北京银行", "上海银行", "江苏银行", "宁波银行", "南京银行", "杭州银行", "南昌农村商业银行", "江西万载农村商业银行"]

def clean_number(num: str) -> float:
    if not num:
        return 0.0
    try:
        return float(re.sub(r'[^\d.-]', '', num.replace(',', '').replace('，', '').replace(' ', '')))
    except:
        return 0.0

def parse_pdf(pdf_bytes: bytes) -> str:
    """调用 PaddleOCR 解析 PDF"""
    resp = requests.post(config.PADDLEOCR_API_URL, 
        headers={"Authorization": f"token {config.PADDLEOCR_TOKEN}", "Content-Type": "application/json"},
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

def extract_report_date(text: str) -> datetime:
    match = re.search(r'报告时间[：:]\s*(\d{4})-(\d{2})-(\d{2})', text)
    return datetime(*map(int, match.groups())) if match else datetime.now()

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

def is_micro(inst: str) -> bool:
    if any(bk in inst for bk in BANK_KEYWORDS):
        return False
    return any(kw in inst for kw in MICRO_KEYWORDS) or "银行" not in inst

def extract_loans(text: str) -> Dict[str, Any]:
    """提取贷款信息（精度优化：先加后除）"""
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
    
    loans = {
        "count": len(insts),
        "balance": 0.0,
        "housing_count": 0,
        "housing_balance": 0.0,
        "car_count": 0,
        "car_balance": 0.0,
        "micro_count": 0,
        "micro_balance": 0.0,
        "overdue_count": 0
    }
    
    balance_raw = 0
    housing_balance_raw = 0
    car_balance_raw = 0
    micro_balance_raw = 0
    
    for data in insts.values():
        balance_raw += data["bal"]
        if data["typ"] == "housing":
            loans["housing_count"] += 1
            housing_balance_raw += data["bal"]
        elif data["typ"] == "car":
            loans["car_count"] += 1
            car_balance_raw += data["bal"]
        elif data["typ"] == "micro":
            loans["micro_count"] += 1
            micro_balance_raw += data["bal"]
        if data["ovd"]:
            loans["overdue_count"] += 1
    
    loans["balance"] = balance_raw / 10000
    loans["housing_balance"] = housing_balance_raw / 10000
    loans["car_balance"] = car_balance_raw / 10000
    loans["micro_balance"] = micro_balance_raw / 10000
    
    return loans

def extract_credits(text: str) -> Dict[str, Any]:
    """提取信用卡信息（精度优化：先加后除）"""
    credits = {
        "count": 0, 
        "limit": 0.0, 
        "used": 0.0, 
        "overdue": 0, 
        "abnormal": {"stop_payment": 0, "frozen": 0, "doubtful": 0}
    }
    
    limit_raw = 0
    used_raw = 0
    
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
        limit_raw += limit
        used_raw += used
        
        if "当前有逾期" in line:
            credits["overdue"] += 1
        if "呆账" in line:
            credits["abnormal"]["doubtful"] += 1
        if "止付" in line:
            credits["abnormal"]["stop_payment"] += 1
        if "冻结" in line:
            credits["abnormal"]["frozen"] += 1
    
    credits["limit"] = limit_raw / 10000
    credits["used"] = used_raw / 10000
    credits["usage_rate"] = round((credits["used"] / credits["limit"] * 100)) if credits["limit"] > 0 else 0
    
    abnormal = []
    if credits["abnormal"]["stop_payment"]:
        abnormal.append(f"止付{credits['abnormal']['stop_payment']}个")
    if credits["abnormal"]["frozen"]:
        abnormal.append(f"冻结{credits['abnormal']['frozen']}个")
    if credits["abnormal"]["doubtful"]:
        abnormal.append(f"呆账{credits['abnormal']['doubtful']}个")
    credits["abnormal_display"] = "；".join(abnormal)
    
    return credits

def extract_guarantee(text: str) -> Tuple[int, float]:
    """提取担保信息"""
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

def extract_queries(text: str, report_date: datetime) -> Dict[str, int]:
    """从 HTML 表格中提取查询记录"""
    queries = {"30d": 0, "31_90d": 0, "91_180d": 0, "181_360d": 0, "micro_60d": 0, "self_60d": 0}
    valid_reasons = ["贷款审批", "信用卡审批", "资信审查", "担保资格审查", "保前审查", "法人代表"]
    
    pattern_with_id = r'<td[^>]*>\d+<tr>\s*<td[^>]*>(\d{4}年\d{1,2}月\d{1,2}日)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</tr>'
    pattern_no_id = r'<td[^>]*>(\d{4}年\d{1,2}月\d{1,2}日)<tr>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>'
    
    matches = re.findall(pattern_with_id, text)
    if not matches:
        matches = re.findall(pattern_no_id, text)
    
    for date_str, institution, reason in matches:
        if "贷后" in reason:
            continue
        if not any(v in reason for v in valid_reasons):
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
    
    self_pattern_with_id = r'<td[^>]*>\d+</td>\s*<td[^>]*>(\d{4}年\d{1,2}月\d{1,2}日)</td>\s*<td[^>]*>本人</td>'
    self_pattern_no_id = r'<td[^>]*>(\d{4}年\d{1,2}月\d{1,2}日)</td>\s*<td[^>]*>本人</td>'
    
    self_matches = re.findall(self_pattern_with_id, text)
    if not self_matches:
        self_matches = re.findall(self_pattern_no_id, text)
    
    for date_str in self_matches:
        try:
            if isinstance(date_str, tuple):
                date_str = date_str[0]
            y, m, d = map(int, re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str).groups())
            diff = (report_date - datetime(y, m, d)).days
            if 0 <= diff <= 60:
                queries["self_60d"] += 1
        except:
            pass
    
    return queries

def extract_overdue(text: str) -> Dict[str, int]:
    total = sum(int(m) for m in re.findall(r'最近\s*5\s*年内有\s*(\d+)\s*个月处于逾期状态', text))
    cnt = len(re.findall(r'其中\s*\d+\s*个月逾期超过\s*90\s*天', text))
    return {"total_months": total, "90d_count": cnt}

def extract_public_records(text: str) -> str:
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

def extract_asset_disposal(text: str) -> Tuple[int, float]:
    m = re.search(r'资产处置信息.*?余额[为]?\s*([\d,]+)', text, re.DOTALL)
    return (1, clean_number(m.group(1))/10000) if m else (0, 0.0)

def extract_advance_payment(text: str) -> Tuple[int, float]:
    m = re.search(r'垫款信息.*?累计代偿金额[为]?\s*([\d,]+)', text, re.DOTALL)
    return (1, clean_number(m.group(1))/10000) if m else (0, 0.0)

def build_risk_warning(asset_cnt, asset_bal, adv_cnt, adv_amt, loans, credits, pub_rec) -> str:
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

def build_llm_prompt(stats: Dict) -> str:
    q, l, c, o = stats["queries"], stats["loans"], stats["credits"], stats["overdue"]
    return f"""您是一名资深的助贷风控专家。请基于以下【真实统计数据】生成专业征信分析报告（仅第二部分：结构分析）。

请使用第二人称"您"来称呼用户，例如"您的贷款余额为xxx"、"您的信用卡使用率为xxx"。

### 基础信息
- 性别：{stats['gender']}，年龄：{stats['age']}，婚姻：{stats['marriage']}

### 查询记录
- 30天内：{q['30d']}次，31-90天：{q['31_90d']}次，91-180天：{q['91_180d']}次，181-360天：{q['181_360d']}次
- 60天内小贷+网贷查询：{q['micro_60d']}次，60天内本人查询：{q['self_60d']}次

### 贷款数据
- 总机构数：{l['count']}家，总余额：{round(l['balance'], 2)}万元
- 房贷：{l['housing_count']}笔，余额：{round(l['housing_balance'], 2)}万元
- 车贷：{l['car_count']}笔，余额：{round(l['car_balance'], 2)}万元
- 小贷+网贷：{l['micro_count']}家，余额：{round(l['micro_balance'], 2)}万元
- 当前逾期：{l['overdue_count']}个

### 信用卡数据
- 机构数：{c['count']}家，授信额：{round(c['limit'], 2)}万元，已用额度：{round(c['used'], 2)}万元，使用率：{c['usage_rate']}%
- 当前逾期：{c['overdue']}个

### 逾期记录
- 总逾期月数：{o['total_months']}个月，90天以上账户：{o['90d_count']}个

请直接输出分析内容，不要输出"好的"、"收到"等开场白。按以下结构输出：1.基本信息解读、2.查询记录分析、3.逾期记录分析、4.贷款信息分析、5.信用卡信息分析、6.综合评估与风控建议。每个判断都要有数据支撑。"""

def call_deepseek(prompt: str) -> str:
    resp = requests.post(config.DEEPSEEK_API_URL, 
        json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.5},
        headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
        timeout=120)
    if resp.status_code != 200:
        raise Exception(f"DeepSeek API 错误: {resp.status_code}")
    return resp.json()["choices"][0]["message"]["content"]

def generate_report(markdown_text: str) -> Tuple[Dict, list]:
    """生成完整报告，返回 (stats, report_lines)"""
    report_date = extract_report_date(markdown_text)
    gender, age, marriage = extract_basic_info(markdown_text, report_date)
    
    loans = extract_loans(markdown_text)
    credits = extract_credits(markdown_text)
    g_cnt, g_bal = extract_guarantee(markdown_text)
    overdue = extract_overdue(markdown_text)
    a_cnt, a_bal = extract_asset_disposal(markdown_text)
    ad_cnt, ad_amt = extract_advance_payment(markdown_text)
    pub_rec = extract_public_records(markdown_text)
    queries = extract_queries(markdown_text, report_date)
    risk_warn = build_risk_warning(a_cnt, a_bal, ad_cnt, ad_amt, loans, credits, pub_rec)
    
    stats = {
        "gender": gender, 
        "age": age, 
        "marriage": marriage, 
        "queries": queries, 
        "loans": loans, 
        "credits": credits, 
        "overdue": overdue
    }
    
    # 统一约分
    balance_yuan = round(loans["balance"], 2)
    housing_balance_yuan = round(loans["housing_balance"], 2)
    car_balance_yuan = round(loans["car_balance"], 2)
    micro_balance_yuan = round(loans["micro_balance"], 2)
    credit_limit_yuan = round(credits["limit"], 2)
    credit_used_yuan = round(credits["used"], 2)
    
    # 构建报告第一部分（美化排版版）
    lines = [
        "## 1. 👤 基础信息",
        "",
        "| 项目 | 信息 |",
        "|------|------|",
        f"| 性别 | {gender} |",
        f"| 年龄 | {age} |",
        f"| 婚姻状况 | {marriage} |",
        f"| 风险预警 | {risk_warn} |",
        "",
        "---",
        "",
        "## 2. 📊 查询记录",
        "",
        "| 时间范围 | 查询次数 |",
        "|----------|----------|",
        f"| 30天内 | {queries['30d']}次 |",
        f"| 31-90天 | {queries['31_90d']}次 |",
        f"| 90-180天 | {queries['91_180d']}次 |",
        f"| 180-360天 | {queries['181_360d']}次 |",
        "",
        "🔍 特殊标记",
        f"- 60天内小贷+网贷查询：**{queries['micro_60d']}次**",
        f"- 60天内本人查询（本人临柜/网查）：**{queries['self_60d']}次**",
        "",
        "---",
        "",
        "## 3. ✅ 逾期记录（5年内）",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 逾期总月数 | {overdue['total_months']}个月 |",
        f"| 逾期90天以上的账户数 | {overdue['90d_count']}个 {'☑' if overdue['90d_count'] == 0 else '⚠️'} |",
        "",
        "---",
        "",
        "## 4. 💰 贷款总览",
        "",
        "| 项目 | 数值 |",
        "|------|------|",
        f"| 总贷款机构数 | **{loans['count']}家** |",
        f"| 总贷款余额 | **{balance_yuan}万元** |",
        "",
        "**细分如下：**",
        ""
    ]
    
    if loans['housing_count'] > 0:
        lines.extend([
            f"- **🏠 房贷**",
            f"  - 机构数：{loans['housing_count']}家",
            f"  - 余额：**{housing_balance_yuan}万元**",
            ""
        ])
    
    if loans['car_count'] > 0:
        lines.extend([
            f"- **🚗 车贷**",
            f"  - 机构数：{loans['car_count']}家",
            f"  - 余额：**{car_balance_yuan}万元**",
            ""
        ])
    
    if loans['micro_count'] > 0:
        lines.extend([
            f"- **📱 小贷+网贷**",
            f"  - 机构数：{loans['micro_count']}家",
            f"  - 余额：**{micro_balance_yuan}万元**",
            ""
        ])
    
    if loans['housing_count'] == 0 and loans['car_count'] == 0 and loans['micro_count'] == 0:
        lines.append("无贷款记录")
        lines.append("")
    
    lines.extend([
        "---",
        "",
        "## 5. 💳 信用卡使用情况",
        "",
        "| 项目 | 数值 |",
        "|------|------|",
        f"| 发卡机构数 | **{credits['count']}家** |",
        f"| 总授信额度 | **{credit_limit_yuan}万元** |",
        f"| 已用额度 | **{credit_used_yuan}万元** |",
        f"| 使用率 | **{credits['usage_rate']}%** |",
        "",
        "---",
        "",
        "## 6. 📝 结构分析",
        ""
    ])
    
    if credits['overdue']:
        lines.append(f"⚠️ 信用卡当逾：{credits['overdue']}个")
    if credits['abnormal_display']:
        lines.append(f"⚠️ 非正常：{credits['abnormal_display']}")
    if loans['overdue_count']:
        lines.append(f"⚠️ 贷款当逾：{loans['overdue_count']}个")
    
    if g_cnt > 0:
        lines.extend([
            "---",
            "",
            "## 担保信息",
            "",
            f"担保户数：{g_cnt}户",
            f"担保余额：{round(g_bal, 2)}万元",
            ""
        ])
    
    if pub_rec:
        lines.extend([
            "---",
            "",
            "## 公共记录",
            "",
            pub_rec,
            ""
        ])
    
    return stats, lines