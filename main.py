# main.py
# 征信报告分析系统 - PaddleOCR-VL-1.5 云端 API 版（修复版）

import os
import re
import json
import requests
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import Dict, Any, List, Tuple
import base64

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 配置 ==========
DEEPSEEK_API_KEY = "sk-196eb4e5ceae4449b1c4fd319818a4ab"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# PaddleOCR-VL-1.5 API 配置
PADDLEOCR_API_URL = "https://7ez8g52bxbp3t2m2.aistudio-app.com/layout-parsing"
PADDLEOCR_TOKEN = "9dcb8c9a6b87fb01d65549e9d7f8619299ec53a4"

# 小网贷关键词
MICRO_KEYWORDS = [
    "网商", "微众", "亿联", "金城", "裕民", "海峡", "振兴", "新网",
    "苏商", "中关村", "富民", "锡商", "百信", "长安", "兰州",
    "威海", "众邦", "蓝海", "华通", "华瑞", "友利", "美团", "度小满",
    "京东", "蚂蚁", "小米", "苏宁", "平安普惠", "中融", "招联", "哈银",
    "长银", "中原", "锦程", "苏银凯基", "南银法巴", "北银", "阳光",
    "新网", "众邦", "华通", "富民", "锡商", "亿联", "金城", "裕民",
    "中关村", "蓝海", "华瑞", "友利", "三快", "财付通", "小雨点"
]

HOUSING_KEYWORDS = ["个人住房", "住房贷款", "商用房", "公积金", "住房公积金"]
CAR_KEYWORDS = ["汽车", "车贷"]

BANK_KEYWORDS = [
    "工商银行", "农业银行", "中国银行", "建设银行", "交通银行",
    "招商银行", "浦发银行", "中信银行", "光大银行", "华夏银行",
    "民生银行", "广发银行", "平安银行", "兴业银行", "浙商银行",
    "邮储银行", "北京银行", "上海银行", "江苏银行", "宁波银行",
    "南京银行", "杭州银行", "南昌农村商业银行", "江西万载农村商业银行"
]


def clean_number(num_str: str) -> float:
    """清理数字字符串，移除空格、逗号、中文逗号"""
    if not num_str:
        return 0.0
    # 移除空格、逗号、中文逗号，只保留数字和点号
    cleaned = re.sub(r'[^\d.-]', '', str(num_str).replace(' ', '').replace('，', '').replace(',', ''))
    try:
        return float(cleaned)
    except:
        return 0.0


def parse_pdf_with_paddleocr(pdf_bytes: bytes) -> Dict[str, Any]:
    """调用 PaddleOCR-VL-1.5 API 解析 PDF"""
    file_data = base64.b64encode(pdf_bytes).decode("ascii")
    
    headers = {
        "Authorization": f"token {PADDLEOCR_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "file": file_data,
        "fileType": 0,
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
        "useLayoutDetection": True,
    }
    
    print(f"正在调用 PaddleOCR API: {PADDLEOCR_API_URL}")
    response = requests.post(PADDLEOCR_API_URL, headers=headers, json=payload, timeout=120)
    
    if response.status_code != 200:
        error_msg = response.text[:500] if response.text else "无响应内容"
        raise Exception(f"PaddleOCR API 错误: {response.status_code}, {error_msg}")
    
    result = response.json()
    
    # 检查业务错误码
    if result.get("errorCode") != 0 and result.get("errorCode") is not None:
        raise Exception(f"PaddleOCR 业务错误: {result.get('errorMsg', '未知错误')}")
    
    # 提取 markdown 文本
    full_markdown = ""
    layout_results = result.get("result", {}).get("layoutParsingResults", [])
    
    if layout_results:
        for res in layout_results:
            markdown_text = res.get("markdown", {}).get("text", "")
            if markdown_text:
                full_markdown += markdown_text + "\n"
    else:
        # 兼容直接返回数组的情况
        if isinstance(result, list):
            for page in result:
                if "prunedResult" in page and "markdown" in page["prunedResult"]:
                    full_markdown += page["prunedResult"]["markdown"].get("text", "") + "\n"
        elif "markdown" in result and "text" in result.get("markdown", {}):
            full_markdown = result["markdown"]["text"]
    
    if not full_markdown:
        raise Exception("PaddleOCR 未能提取到文本内容")
    
    print(f"PaddleOCR 解析成功，文本长度: {len(full_markdown)}")
    return {"markdown": full_markdown, "elements": []}


def extract_gender(text: str) -> str:
    """从身份证号提取性别"""
    match = re.search(r'证件号码[：:]\s*(\d{17}[\dXx])', text)
    if match:
        gender_code = int(match.group(1)[16])
        return "男" if gender_code % 2 == 1 else "女"
    return "未知"


def extract_age(text: str, report_date: datetime) -> int:
    """从身份证号提取年龄"""
    id_match = re.search(r'证件号码[：:]\s*(\d{17}[\dXx])', text)
    if id_match:
        id_num = id_match.group(1)
        try:
            birth_year = int(id_num[6:10])
            birth_month = int(id_num[10:12])
            birth_day = int(id_num[12:14])
            birth_date = datetime(birth_year, birth_month, birth_day)
            age = report_date.year - birth_date.year
            if (report_date.month, report_date.day) < (birth_date.month, birth_date.day):
                age -= 1
            return age
        except:
            pass
    return 0


def extract_marriage(text: str) -> str:
    """提取婚姻状况"""
    if "已婚" in text:
        return "已婚"
    elif "未婚" in text:
        return "未婚"
    return "未知"


def extract_report_date(text: str) -> datetime:
    """提取报告时间"""
    # 支持格式：2023-03-01 20:00:26 或 2025-05-25 09:30:15
    match = re.search(r'报告时间[：:]\s*(\d{4})-(\d{2})-(\d{2})', text)
    if match:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return datetime.now()


def is_micro_institution(institution_name: str) -> bool:
    """
    判断是否为小网贷机构
    规则：不含"银行"就是小网贷（按文档方案 A）
    """
    # 先检查是否包含银行关键词
    for bk in BANK_KEYWORDS:
        if bk in institution_name:
            return False
    # 检查是否包含小网贷关键词
    for kw in MICRO_KEYWORDS:
        if kw in institution_name:
            return True
    # 不含"银行"就是小网贷
    if "银行" not in institution_name:
        return True
    return False


def extract_asset_disposal(text: str) -> Tuple[int, float]:
    """提取资产处置信息"""
    count = 0
    balance = 0.0
    match = re.search(r'资产处置信息.*?余额[为]?\s*([\d,]+)', text, re.DOTALL)
    if match:
        count = 1
        balance = clean_number(match.group(1)) / 10000
    return count, balance


def extract_advance_payment(text: str) -> Tuple[int, float]:
    """提取垫款信息"""
    count = 0
    amount = 0.0
    match = re.search(r'垫款信息.*?累计代偿金额[为]?\s*([\d,]+)', text, re.DOTALL)
    if match:
        count = 1
        amount = clean_number(match.group(1)) / 10000
    return count, amount


def extract_overdue(text: str) -> Dict[str, int]:
    """提取逾期记录"""
    overdue = {"total_months": 0, "90d_count": 0}
    
    # 匹配：最近5年内有X个月处于逾期状态（支持有空格）
    month_pattern = r'最近\s*5\s*年内有\s*(\d+)\s*个月处于逾期状态'
    months = re.findall(month_pattern, text)
    overdue["total_months"] = sum(int(m) for m in months)
    
    # 匹配：其中X个月逾期超过90天（支持有空格）
    overdue_90_pattern = r'其中\s*(\d+)\s*个月逾期超过\s*90\s*天'
    matches = re.findall(overdue_90_pattern, text)
    overdue["90d_count"] = sum(int(m) for m in matches)
    
    return overdue


def extract_public_records(text: str) -> str:
    """提取公共记录（欠税、民事判决、强制执行、行政处罚）"""
    records = []
    
    # 欠税记录
    tax_match = re.search(r'欠税总额[：:]\s*([\d,]+)', text)
    if tax_match:
        amount = clean_number(tax_match.group(1))
        records.append(f"欠税1条，金额{amount/10000:.2f}万元")
    
    # 民事判决
    judgment_matches = re.findall(r'诉讼标的金额[：:]\s*([\d,]+)', text)
    if judgment_matches:
        total = sum(clean_number(m) for m in judgment_matches)
        records.append(f"民事判决{len(judgment_matches)}件，金额{total/10000:.2f}万元")
    
    # 强制执行
    enforcement_matches = re.findall(r'申请执行标的金额[：:]\s*([\d,]+)', text)
    if enforcement_matches:
        total = sum(clean_number(m) for m in enforcement_matches)
        records.append(f"强制执行{len(enforcement_matches)}件，金额{total/10000:.2f}万元")
    
    # 行政处罚
    penalty_match = re.search(r'处罚金额[：:]\s*([\d,]+)', text)
    if penalty_match:
        amount = clean_number(penalty_match.group(1))
        records.append(f"行政处罚1条，金额{amount/10000:.2f}万元")
    
    return "\n".join(records) if records else ""


def extract_loans_from_text(text: str) -> Dict[str, Any]:
    """
    从 Markdown 文本中提取贷款信息
    修复版：正确遍历每一行，正确提取余额
    """
    loans = {
        "count": 0,              # 总机构数
        "balance": 0.0,          # 总余额
        "housing_count": 0,      # 房贷笔数
        "housing_balance": 0.0,  # 房贷余额
        "car_count": 0,          # 车贷笔数
        "car_balance": 0.0,      # 车贷余额
        "micro_count": 0,        # 小网贷机构数
        "micro_balance": 0.0,    # 小网贷余额
        "overdue_count": 0       # 当前逾期数量
    }
    
    lines = text.split('\n')
    seen = set()
    
    for line in lines:
        line = line.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        
        # 匹配以数字加点号开头的行（贷款记录行）
        if not re.match(r'^\d+\.', line):
            continue
        
        # 必须包含"发放"或"授信"
        if "发放" not in line and "授信" not in line:
            continue
        
        # 跳过已结清、已转出、销户的账户
        if "已结清" in line or "已转出" in line or "销户" in line:
            continue
        
        # 提取余额（支持"余额"和"余额为"两种格式，支持有空格）
        balance_match = re.search(r'余额[为]?\s*([\d,]+)', line)
        balance = clean_number(balance_match.group(1)) if balance_match else 0
        
        # 提取机构名称
        # 格式：2024年05月28日深圳前海微众银行股份有限公司发放的
        inst_match = re.search(r'\d{4}\s*年\d{1,2}\s*月\d{1,2}\s*日([^发放授信]+?)(?:发放|为)', line)
        institution = inst_match.group(1).strip() if inst_match else ''
        
        # 如果没匹配到，尝试另一种模式
        if not institution:
            inst_match2 = re.search(r'日([^发放授信]+?)(?:发放|为)', line)
            institution = inst_match2.group(1).strip() if inst_match2 else ''
        
        loans["count"] += 1
        
        if balance > 0:
            loans["balance"] += balance / 10000
        
        # 判断贷款类型
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
        
        # 检查当前逾期
        if "当前有逾期" in line:
            loans["overdue_count"] += 1
    
    return loans


def extract_credits_from_text(text: str) -> Dict[str, Any]:
    """
    从 Markdown 文本中提取信用卡信息
    修复版：正确提取信用额度和已使用额度
    """
    credits = {
        "count": 0,
        "limit": 0.0,
        "used": 0.0,
        "overdue": 0,
        "abnormal": {"stop_payment": 0, "frozen": 0, "doubtful": 0}
    }
    
    lines = text.split('\n')
    seen = set()
    
    for line in lines:
        line = line.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        
        # 匹配以数字加点号开头的行
        if not re.match(r'^\d+\.', line):
            continue
        
        # 只处理贷记卡（人民币账户）
        if '贷记卡' not in line:
            continue
        
        # 排除美元账户、尚未激活、已销户
        if '美元' in line:
            continue
        if '尚未激活' in line:
            continue
        if '销户' in line:
            continue
        
        # 提取信用额度（支持有空格）
        limit_match = re.search(r'信用额度\s*([\d,]+)', line)
        if not limit_match:
            limit_match = re.search(r'授信额度\s*([\d,]+)', line)
        if not limit_match:
            continue
        
        limit = clean_number(limit_match.group(1))
        
        # 提取已使用额度或余额
        used_match = re.search(r'已使用额度\s*([\d,]+)', line)
        if not used_match:
            used_match = re.search(r'余额\s*([\d,]+)', line)
        used = clean_number(used_match.group(1)) if used_match else 0
        
        if limit > 0:
            credits["count"] += 1
            credits["limit"] += limit / 10000
            credits["used"] += used / 10000
        
        # 检查异常状态
        if "当前有逾期" in line:
            credits["overdue"] += 1
        if "呆账" in line:
            credits["abnormal"]["doubtful"] += 1
        if "止付" in line:
            credits["abnormal"]["stop_payment"] += 1
        if "冻结" in line:
            credits["abnormal"]["frozen"] += 1
    
    # 计算使用率
    credits["usage_rate"] = round((credits["used"] / credits["limit"] * 100)) if credits["limit"] > 0 else 0
    
    # 构建异常显示文本
    abnormal_parts = []
    if credits["abnormal"]["stop_payment"] > 0:
        abnormal_parts.append(f"止付{credits['abnormal']['stop_payment']}个")
    if credits["abnormal"]["frozen"] > 0:
        abnormal_parts.append(f"冻结{credits['abnormal']['frozen']}个")
    if credits["abnormal"]["doubtful"] > 0:
        abnormal_parts.append(f"呆账{credits['abnormal']['doubtful']}个")
    credits["abnormal_display"] = "；".join(abnormal_parts) if abnormal_parts else ""
    
    return credits


def extract_guarantee_from_text(text: str) -> Tuple[int, float]:
    """提取担保信息"""
    count = 0
    balance = 0.0
    
    # 匹配：相关还款责任金额XXX...余额XXX
    pattern = r'相关还款责任金额[为]?\s*([\d,]+).*?余额[为]?\s*([\d,]+)'
    matches = re.findall(pattern, text, re.DOTALL)
    
    for amount_str, balance_str in matches:
        count += 1
        amount = clean_number(amount_str)
        loan_balance = clean_number(balance_str)
        # 取两者较小值
        min_val = min(amount, loan_balance) if amount > 0 and loan_balance > 0 else amount
        balance += min_val / 10000
    
    # 如果没有匹配到余额，只取相关还款责任金额
    if count == 0:
        amount_matches = re.findall(r'相关还款责任金额[为]?\s*([\d,]+)', text)
        for amount_str in amount_matches:
            if amount_str and amount_str != '--':
                count += 1
                balance += clean_number(amount_str) / 10000
    
    return count, balance


def extract_queries_from_text(text: str, report_date: datetime) -> Dict[str, int]:
    """从文本中提取查询记录"""
    queries = {
        "30d": 0, "31_90d": 0, "91_180d": 0, "181_360d": 0,
        "micro_60d": 0, "self_60d": 0
    }
    
    # 机构查询（排除贷后管理）
    # 匹配格式：2023年02月24日 哈尔滨哈银消费金融有限责任公司 贷款审批
    pattern = r'(\d{4})年(\d{1,2})月(\d{1,2})日\s+([^\d\n]+?)\s+(?:贷款审批|信用卡审批|资信审查|担保资格审查|保前审查|法人代表)'
    
    for match in re.finditer(pattern, text):
        y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
        institution = match.group(4).strip()
        query_date = datetime(y, m, d)
        diff_days = (report_date - query_date).days
        
        if diff_days < 0 or diff_days > 360:
            continue
        
        if diff_days <= 30:
            queries["30d"] += 1
        elif diff_days <= 90:
            queries["31_90d"] += 1
        elif diff_days <= 180:
            queries["91_180d"] += 1
        elif diff_days <= 360:
            queries["181_360d"] += 1
        
        if diff_days <= 60 and is_micro_institution(institution):
            queries["micro_60d"] += 1
    
    # 本人查询
    self_pattern = r'(\d{4})年(\d{1,2})月(\d{1,2})日\s+本人'
    for match in re.finditer(self_pattern, text):
        y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
        query_date = datetime(y, m, d)
        diff_days = (report_date - query_date).days
        if 0 <= diff_days <= 60:
            queries["self_60d"] += 1
    
    return queries


def build_risk_warning(asset_count: int, asset_balance: float, 
                       advance_count: int, advance_amount: float,
                       loans: Dict, credits: Dict, public_records: str) -> str:
    """构建风险预警文本"""
    warnings = []
    if asset_count > 0:
        warnings.append(f"资产处置{asset_count}笔，余额{asset_balance:.2f}万元")
    if advance_count > 0:
        warnings.append(f"垫款{advance_count}笔，金额{advance_amount:.2f}万元")
    if loans.get("overdue_count", 0) > 0:
        warnings.append(f"贷款当逾{loans['overdue_count']}个")
    if credits.get("overdue", 0) > 0:
        warnings.append(f"信用卡当逾{credits['overdue']}个")
    if credits.get("abnormal_display"):
        warnings.append(credits["abnormal_display"])
    if public_records:
        records_str = public_records.replace("\n", "；")
        warnings.append(records_str)
    return "；".join(warnings) if warnings else "无"


def build_llm_prompt(stats: Dict[str, Any]) -> str:
    """构建 DeepSeek 提示词"""
    q = stats["queries"]
    l = stats["loans"]
    c = stats["credits"]
    o = stats["overdue"]
    return f"""你是一名资深的助贷风控专家。

请基于以下【真实统计数据】，生成一份专业的征信分析报告（仅需第二部分：展开分析），不要简单重复第一部分的数字。

### 基础信息
- 性别：{stats['gender']}，年龄：{stats['age']}，婚姻：{stats['marriage']}

### 查询记录分析数据
- 30天内：{q['30d']}次
- 31-90天：{q['31_90d']}次
- 91-180天：{q['91_180d']}次
- 181-360天：{q['181_360d']}次
- 60天内小网贷查询：{q['micro_60d']}次
- 60天内本人查询：{q['self_60d']}次

### 贷款数据分析
- 总机构数：{l['count']}家
- 总余额：{round(l['balance'], 2)}万元
- 房贷：{l['housing_count']}笔，余额：{round(l['housing_balance'], 2)}万元
- 车贷：{l['car_count']}笔，余额：{round(l['car_balance'], 2)}万元
- 小网贷：{l['micro_count']}家，余额：{round(l['micro_balance'], 2)}万元
- 当前逾期：{l['overdue_count']}个

### 信用卡数据分析
- 机构数：{c['count']}家
- 授信额：{round(c['limit'], 2)}万元
- 已用额度：{round(c['used'], 2)}万元
- 使用率：{c['usage_rate']}%
- 当前逾期：{c['overdue']}个

### 逾期记录
- 总逾期月数：{o['total_months']}个月
- 90天以上账户：{o['90d_count']}个

请按以下结构输出：
1. 基本信息解读
2. 查询记录分析
3. 逾期记录分析
4. 贷款信息分析
5. 信用卡信息分析
6. 综合评估与风控建议

要求：语言专业、逻辑清晰、每个判断都要有数据支撑。"""


def call_deepseek(prompt: str) -> str:
    """调用 DeepSeek API"""
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    response = requests.post(DEEPSEEK_API_URL, json=payload, headers=headers, timeout=120)
    if response.status_code != 200:
        raise Exception(f"DeepSeek API 错误: {response.status_code} - {response.text[:200]}")
    data = response.json()
    return data["choices"][0]["message"]["content"]


@app.post("/api/analyze")
async def analyze(file: UploadFile):
    """分析征信报告"""
    if not DEEPSEEK_API_KEY:
        raise HTTPException(500, "缺少 DeepSeek API Key")
    
    pdf_bytes = await file.read()
    if len(pdf_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件不能超过10MB")
    
    try:
        # 解析 PDF
        parse_result = parse_pdf_with_paddleocr(pdf_bytes)
        markdown_text = parse_result.get("markdown", "")
        
        if not markdown_text:
            raise Exception("PaddleOCR 未能提取到文本内容")
        
        print(f"解析成功，文本长度: {len(markdown_text)}")
        
        # 提取基础信息
        report_date = extract_report_date(markdown_text)
        gender = extract_gender(markdown_text)
        age = extract_age(markdown_text, report_date)
        marriage = extract_marriage(markdown_text)
        
        # 提取各项数据
        loans = extract_loans_from_text(markdown_text)
        credits = extract_credits_from_text(markdown_text)
        guarantee_count, guarantee_balance = extract_guarantee_from_text(markdown_text)
        overdue = extract_overdue(markdown_text)
        asset_count, asset_balance = extract_asset_disposal(markdown_text)
        advance_count, advance_amount = extract_advance_payment(markdown_text)
        public_records = extract_public_records(markdown_text)
        queries = extract_queries_from_text(markdown_text, report_date)
        
        # 构建风险预警
        risk_warning = build_risk_warning(asset_count, asset_balance, advance_count, advance_amount,
                                          loans, credits, public_records)
        
        # 构建统计数据
        stats = {
            "gender": gender, "age": age, "marriage": marriage,
            "queries": queries, "loans": loans, "credits": credits, "overdue": overdue
        }
        
        # 构建第一部分：简要汇总
        part1_lines = []
        part1_lines.append("### 第一部分：简要汇总\n")
        
        part1_lines.append("*基本信息")
        part1_lines.append(f"性别：{gender}")
        part1_lines.append(f"年龄：{age}")
        part1_lines.append(f"婚姻：{marriage}")
        part1_lines.append(f"风险预警：{risk_warning}")
        part1_lines.append("")
        
        part1_lines.append("*查询记录")
        part1_lines.append("机构")
        part1_lines.append(f"30天内：{queries['30d']}")
        part1_lines.append(f"31-90天：{queries['31_90d']}")
        part1_lines.append(f"90-180天：{queries['91_180d']}")
        part1_lines.append(f"180-360天：{queries['181_360d']}")
        part1_lines.append(f"60天内小网贷：{queries['micro_60d']}")
        part1_lines.append("本人")
        part1_lines.append(f"60天内本人：{queries['self_60d']}")
        part1_lines.append("")
        
        part1_lines.append("*5年内逾期")
        part1_lines.append(f"总月数：{overdue['total_months']}")
        part1_lines.append(f"90天以上的账户数：{overdue['90d_count']}")
        part1_lines.append("")
        
        part1_lines.append("*贷款")
        if loans.get('overdue_count', 0) > 0:
            part1_lines.append(f"当逾：{loans['overdue_count']}个")
        part1_lines.append(f"机构数：{loans['count']}")
        part1_lines.append(f"总余额：{round(loans['balance'], 2)}万元")
        if loans['housing_count'] > 0:
            part1_lines.append(f"房贷数：{loans['housing_count']}")
            part1_lines.append(f"房贷余额：{round(loans['housing_balance'], 2)}万元")
        if loans['car_count'] > 0:
            part1_lines.append(f"车贷数：{loans['car_count']}")
            part1_lines.append(f"车贷余额：{round(loans['car_balance'], 2)}万元")
        part1_lines.append(f"小网贷的机构数：{loans['micro_count']}")
        part1_lines.append(f"小网贷的余额：{round(loans['micro_balance'], 2)}万元")
        part1_lines.append("")
        
        part1_lines.append("*信用卡")
        if credits.get('overdue', 0) > 0:
            part1_lines.append(f"当逾：{credits['overdue']}个")
        if credits.get('abnormal_display'):
            part1_lines.append(f"非正常：{credits['abnormal_display']}")
        part1_lines.append(f"机构数：{credits['count']}")
        part1_lines.append(f"授信额：{round(credits['limit'], 2)}万元")
        part1_lines.append(f"已用额度：{round(credits['used'], 2)}万元")
        part1_lines.append(f"使用率：{credits['usage_rate']}%")
        part1_lines.append("")
        
        if guarantee_count > 0 or guarantee_balance > 0:
            part1_lines.append("*担保信息")
            part1_lines.append(f"担保户数：{guarantee_count}")
            part1_lines.append(f"担保余额：{round(guarantee_balance, 2)}万元")
            part1_lines.append("")
        
        if public_records:
            part1_lines.append("*公共记录")
            part1_lines.append(public_records)
        
        part1 = "\n".join(part1_lines)
        
        # 调用 DeepSeek 生成第二部分
        llm_prompt = build_llm_prompt(stats)
        part2 = call_deepseek(llm_prompt)
        
        full_report = part1 + "\n\n### 第二部分：展开分析\n\n" + part2
        return JSONResponse({"success": True, "full_report": full_report})
        
    except Exception as e:
        print(f"错误: {str(e)}")
        raise HTTPException(500, f"处理失败: {str(e)}")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "paddleocr_v2_fixed"}


@app.get("/")
def frontend():
    html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes, viewport-fit=cover">
    <title>征信报告分析系统</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background: #f5f7fa; padding: 16px; min-height: 100vh; }
        .container { max-width: 600px; margin: 0 auto; background: white; border-radius: 24px; padding: 20px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08); }
        h1 { color: #1e3c72; border-bottom: 3px solid #4a90e2; padding-bottom: 12px; margin-bottom: 16px; font-size: 22px; display: flex; align-items: center; gap: 8px; }
        .desc { color: #666; font-size: 14px; line-height: 1.5; margin-bottom: 20px; padding: 0 4px; }
        .upload-area { border: 2px dashed #4a90e2; border-radius: 20px; padding: 40px 20px; text-align: center; background: #fafcff; margin: 16px 0; cursor: pointer; transition: all 0.2s ease; }
        .upload-area:hover { background: #eef4ff; border-color: #357abd; }
        .upload-area .upload-icon { font-size: 48px; margin-bottom: 12px; }
        .upload-area .upload-text { color: #4a90e2; font-size: 16px; }
        .upload-area .file-name { color: #2e7d32; font-size: 14px; margin-top: 8px; font-weight: 500; }
        input[type="file"] { display: none; }
        button { background: #4a90e2; color: white; border: none; padding: 14px 28px; border-radius: 40px; font-size: 16px; font-weight: 500; cursor: pointer; width: 100%; transition: background 0.2s ease; margin-top: 8px; }
        button:hover { background: #357abd; }
        button:disabled { background: #ccc; cursor: not-allowed; }
        .loading { display: none; text-align: center; margin: 24px 0; color: #4a90e2; font-size: 14px; }
        .loading::before { content: "⏳"; display: inline-block; animation: spin 1s linear infinite; margin-right: 8px; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .result-container { display: none; margin-top: 24px; }
        .result { background: #f9f9f9; border-radius: 16px; padding: 16px; font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace; font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; max-height: 500px; overflow-y: auto; border: 1px solid #e0e0e0; }
        .info-note { background: #e8f4fd; padding: 12px; border-radius: 12px; margin-top: 20px; font-size: 12px; color: #4a90e2; text-align: center; }
        .bottom-space { height: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <h1><span>📄</span>征信结构解读</h1>
        <p class="desc">上传PDF格式的个人简版信用报告，系统将自动解析并生成专业风控报告。</p>

        <div class="upload-area" id="uploadArea">
            <div class="upload-icon">📎</div>
            <div class="upload-text">点击或拖拽上传PDF文件</div>
            <div class="file-name" id="fileName"></div>
            <input type="file" id="fileInput" accept=".pdf">
        </div>

        <button id="analyzeBtn" disabled>开始分析</button>

        <div class="loading" id="loading">正在解析并分析报告，请稍候...（可能需要30-60秒）</div>

        <div class="result-container" id="resultContainer">
            <div class="result" id="result"></div>
        </div>

        <div class="info-note">💡 提示：分析结果包含两部分 — 简要汇总 + 展开分析</div>
        <div class="bottom-space"></div>
    </div>

    <script>
        const uploadArea = document.getElementById('uploadArea');
        const fileInput = document.getElementById('fileInput');
        const analyzeBtn = document.getElementById('analyzeBtn');
        const loadingDiv = document.getElementById('loading');
        const resultDiv = document.getElementById('result');
        const resultContainer = document.getElementById('resultContainer');
        const fileNameSpan = document.getElementById('fileName');

        let selectedFile = null;

        function resetUploadDisplay() {
            const uploadIcon = uploadArea.querySelector('.upload-icon');
            const uploadText = uploadArea.querySelector('.upload-text');
            uploadIcon.innerHTML = '📎';
            uploadText.innerHTML = '点击或拖拽上传PDF文件';
            fileNameSpan.innerHTML = '';
        }

        function showFileSelected(fileName) {
            const uploadIcon = uploadArea.querySelector('.upload-icon');
            const uploadText = uploadArea.querySelector('.upload-text');
            uploadIcon.innerHTML = '✅';
            uploadText.innerHTML = '文件已就绪';
            fileNameSpan.innerHTML = fileName;
        }

        function handleFile(file) {
            if (!file || file.type !== 'application/pdf') {
                alert('请上传PDF格式的文件');
                resetUploadDisplay();
                selectedFile = null;
                analyzeBtn.disabled = true;
                return;
            }
            selectedFile = file;
            analyzeBtn.disabled = false;
            showFileSelected(file.name);
        }

        uploadArea.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', (e) => e.target.files.length > 0 && handleFile(e.target.files[0]));

        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.style.background = '#eef4ff';
            uploadArea.style.borderColor = '#357abd';
        });

        uploadArea.addEventListener('dragleave', (e) => {
            e.preventDefault();
            uploadArea.style.background = '#fafcff';
            uploadArea.style.borderColor = '#4a90e2';
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.style.background = '#fafcff';
            uploadArea.style.borderColor = '#4a90e2';
            e.dataTransfer.files.length > 0 && handleFile(e.dataTransfer.files[0]);
        });

        analyzeBtn.addEventListener('click', async () => {
            if (!selectedFile) return;
            analyzeBtn.disabled = true;
            loadingDiv.style.display = 'block';
            resultContainer.style.display = 'none';
            resultDiv.innerText = '';

            const formData = new FormData();
            formData.append('file', selectedFile);

            try {
                const response = await fetch('/api/analyze', { method: 'POST', body: formData });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || '分析失败');
                resultDiv.innerText = data.full_report;
                resultContainer.style.display = 'block';
                resultContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
            } catch (err) {
                alert('错误：' + err.message);
            } finally {
                loadingDiv.style.display = 'none';
                analyzeBtn.disabled = false;
            }
        });
    </script>
</body>
</html>'''
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)