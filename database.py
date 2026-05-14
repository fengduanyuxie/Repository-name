# database.py
# MongoDB 数据库操作（含日志、统计、有效期、临时存储、订单表）

from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, List, Optional
from pymongo import MongoClient
import config

mongo_client = None
db = None
users_collection = None
logs_collection = None
stats_collection = None
temp_reports_collection = None
orders_collection = None

def init_db():
    """初始化数据库连接"""
    global mongo_client, db, users_collection, logs_collection, stats_collection, temp_reports_collection, orders_collection
    if not config.MONGO_URI:
        print("警告: MONGO_URI 未设置")
        return False
    
    try:
        mongo_client = MongoClient(config.MONGO_URI)
        db = mongo_client[config.MONGO_DB]
        users_collection = db["users"]
        logs_collection = db["admin_logs"]
        stats_collection = db["usage_stats"]
        temp_reports_collection = db["temp_reports"]
        orders_collection = db["orders"]
        
        users_collection.create_index("phone", unique=True)
        users_collection.create_index("api_key", unique=True)
        users_collection.create_index("expire_at")
        logs_collection.create_index("created_at")
        stats_collection.create_index("date", unique=True)
        temp_reports_collection.create_index("expires_at", expireAfterSeconds=0)
        orders_collection.create_index("order_id", unique=True)
        orders_collection.create_index("out_trade_no")
        orders_collection.create_index("trade_no")
        orders_collection.create_index("status")
        
        print("MongoDB 连接成功")
        return True
    except Exception as e:
        print(f"MongoDB 连接失败: {e}")
        return False

# ========== 用户相关 ==========
def verify_user(phone: str, api_key: str) -> tuple:
    """验证用户，返回 (是否有效, 剩余次数)"""
    if users_collection is None:
        return False, 0
    user = users_collection.find_one({
        "phone": phone, 
        "api_key": api_key,
        "balance": {"$gt": 0},
        "$or": [
            {"expire_at": {"$exists": False}},
            {"expire_at": {"$gt": datetime.now()}}
        ]
    })
    if user:
        return True, user.get("balance", 0)
    return False, 0

def verify_user_exists(phone: str, api_key: str) -> tuple:
    """验证用户是否存在（不计次数），返回 (是否存在, 用户信息, 剩余次数)"""
    if users_collection is None:
        return False, None, 0
    user = users_collection.find_one({
        "phone": phone, 
        "api_key": api_key
    })
    if user:
        balance = user.get("balance", 0)
        expire_at = user.get("expire_at")
        is_valid = balance > 0 and (expire_at is None or expire_at > datetime.now())
        return True, user, balance if is_valid else 0
    return False, None, 0

def consume_balance(phone: str, api_key: str) -> bool:
    """扣减一次使用次数"""
    if users_collection is None:
        return False
    result = users_collection.update_one(
        {"phone": phone, "api_key": api_key, "balance": {"$gt": 0}},
        {"$inc": {"balance": -1}, "$set": {"last_used_at": datetime.now()}}
    )
    if result.modified_count > 0:
        today = datetime.now().strftime("%Y-%m-%d")
        stats_collection.update_one(
            {"date": today},
            {"$inc": {"total_calls": 1}, "$setOnInsert": {"date": today}},
            upsert=True
        )
        return True
    return False

def generate_api_key(phone: str) -> str:
    """生成 API Key"""
    import secrets
    return f"ak_{phone[-6:]}_{secrets.token_hex(8)}"

def add_or_recharge_user(phone: str, balance: int, days_valid: int = 62) -> Tuple[str, int]:
    """添加或充值用户，返回 (api_key, 新余额)"""
    api_key = generate_api_key(phone)
    expire_at = datetime.now() + timedelta(days=days_valid) if days_valid > 0 else None
    
    result = users_collection.update_one(
        {"phone": phone},
        {"$setOnInsert": {
            "phone": phone, 
            "api_key": api_key, 
            "created_at": datetime.now(),
            "expire_at": expire_at
        },
         "$inc": {"balance": balance}},
        upsert=True
    )
    if result.upserted_id:
        return api_key, balance
    else:
        user = users_collection.find_one({"phone": phone})
        return user["api_key"], user["balance"] + balance

def delete_user(phone: str) -> bool:
    """删除用户"""
    if users_collection is None:
        return False
    result = users_collection.delete_one({"phone": phone})
    return result.deleted_count > 0

def get_all_users():
    """获取所有用户"""
    if users_collection is None:
        return []
    return list(users_collection.find({}, {"_id": 0}).sort("created_at", -1))

def get_user_by_phone(phone: str):
    """根据手机号获取用户"""
    if users_collection is None:
        return None
    return users_collection.find_one({"phone": phone}, {"_id": 0})

def get_user_stats():
    """获取用户统计"""
    if users_collection is None:
        return {"total": 0, "total_balance": 0}
    total = users_collection.count_documents({})
    pipeline = [{"$group": {"_id": None, "total_balance": {"$sum": "$balance"}}}]
    result = list(users_collection.aggregate(pipeline))
    total_balance = result[0]["total_balance"] if result else 0
    return {"total": total, "total_balance": total_balance}

# ========== 操作日志 ==========
def add_admin_log(admin: str, action: str, target: str, details: str = ""):
    """添加管理员操作日志"""
    if logs_collection is None:
        return
    logs_collection.insert_one({
        "admin": admin,
        "action": action,
        "target": target,
        "details": details,
        "created_at": datetime.now()
    })

def get_admin_logs(limit: int = 100):
    """获取操作日志"""
    if logs_collection is None:
        return []
    return list(logs_collection.find({}, {"_id": 0}).sort("created_at", -1).limit(limit))

# ========== 使用统计 ==========
def get_usage_stats(days: int = 30):
    """获取使用统计"""
    if stats_collection is None:
        return []
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return list(stats_collection.find(
        {"date": {"$gte": start_date}},
        {"_id": 0}
    ).sort("date", 1))

# ========== 临时存储（MongoDB TTL）==========
def save_temp_report(temp_id: str, report_content: str, phone: str = None, api_key: str = None):
    """保存临时报告，24小时后自动过期"""
    if temp_reports_collection is None:
        return False
    temp_reports_collection.insert_one({
        "temp_id": temp_id,
        "report": report_content,
        "phone": phone,
        "api_key": api_key,
        "created_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(hours=24)
    })
    return True

def get_temp_report(temp_id: str):
    """获取临时报告"""
    if temp_reports_collection is None:
        return None
    return temp_reports_collection.find_one({"temp_id": temp_id}, {"_id": 0})

def delete_temp_report(temp_id: str):
    """删除临时报告"""
    if temp_reports_collection is None:
        return
    temp_reports_collection.delete_one({"temp_id": temp_id})

def update_temp_report_phone(temp_id: str, phone: str, api_key: str):
    """更新临时报告关联的用户信息"""
    if temp_reports_collection is None:
        return
    temp_reports_collection.update_one(
        {"temp_id": temp_id},
        {"$set": {"phone": phone, "api_key": api_key}}
    )

# ========== 订单表（A2M支付）==========
def create_order(
    order_id: str,
    out_trade_no: str,
    phone: str,
    amount: str,
    resource_id: str,
    temp_id: str = None,
    expires_minutes: int = 30
) -> bool:
    """创建订单"""
    if orders_collection is None:
        return False
    expires_at = datetime.now() + timedelta(minutes=expires_minutes)
    orders_collection.insert_one({
        "order_id": order_id,
        "out_trade_no": out_trade_no,
        "trade_no": None,
        "phone": phone,
        "amount": amount,
        "resource_id": resource_id,
        "temp_id": temp_id,
        "status": "pending",  # pending, paid, fulfilled
        "created_at": datetime.now(),
        "expires_at": expires_at,
        "paid_at": None,
        "fulfilled_at": None
    })
    return True

def get_order_by_out_trade_no(out_trade_no: str):
    """根据商户订单号获取订单"""
    if orders_collection is None:
        return None
    return orders_collection.find_one({"out_trade_no": out_trade_no}, {"_id": 0})

def get_order_by_trade_no(trade_no: str):
    """根据支付宝交易号获取订单"""
    if orders_collection is None:
        return None
    return orders_collection.find_one({"trade_no": trade_no}, {"_id": 0})

def update_order_paid(out_trade_no: str, trade_no: str) -> bool:
    """更新订单为已支付"""
    if orders_collection is None:
        return False
    result = orders_collection.update_one(
        {"out_trade_no": out_trade_no, "status": "pending"},
        {"$set": {
            "status": "paid",
            "trade_no": trade_no,
            "paid_at": datetime.now()
        }}
    )
    return result.modified_count > 0

def update_order_fulfilled(out_trade_no: str) -> bool:
    """更新订单为已履约"""
    if orders_collection is None:
        return False
    result = orders_collection.update_one(
        {"out_trade_no": out_trade_no, "status": "paid"},
        {"$set": {
            "status": "fulfilled",
            "fulfilled_at": datetime.now()
        }}
    )
    return result.modified_count > 0

def get_orders_by_phone(phone: str, limit: int = 50):
    """获取用户的所有订单"""
    if orders_collection is None:
        return []
    return list(orders_collection.find(
        {"phone": phone},
        {"_id": 0}
    ).sort("created_at", -1).limit(limit))

def is_order_already_fulfilled(out_trade_no: str) -> bool:
    """检查订单是否已履约（防重放）"""
    if orders_collection is None:
        return False
    order = orders_collection.find_one({"out_trade_no": out_trade_no})
    return order and order.get("status") in ["paid", "fulfilled"]