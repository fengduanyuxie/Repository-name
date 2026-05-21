# database.py
# MongoDB 数据库操作（完全免费版 - 无余额/充值功能）

from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, List, Optional
from pymongo import MongoClient
import config

mongo_client = None
db = None
users_collection = None
logs_collection = None
stats_collection = None

def init_db():
    """初始化数据库连接"""
    global mongo_client, db, users_collection, logs_collection, stats_collection
    if not config.MONGO_URI:
        print("警告: MONGO_URI 未设置")
        return False
    
    try:
        mongo_client = MongoClient(config.MONGO_URI)
        db = mongo_client[config.MONGO_DB]
        users_collection = db["users"]
        logs_collection = db["admin_logs"]
        stats_collection = db["usage_stats"]
        
        users_collection.create_index("phone", unique=True)
        users_collection.create_index("api_key", unique=True)
        users_collection.create_index("expire_at")
        logs_collection.create_index("created_at")
        stats_collection.create_index("date", unique=True)
        
        print("MongoDB 连接成功")
        return True
    except Exception as e:
        print(f"MongoDB 连接失败: {e}")
        return False

# ========== 用户相关 ==========
def verify_user(phone: str, api_key: str) -> tuple:
    """验证用户，返回 (是否存在, 用户信息)"""
    if users_collection is None:
        return False, None
    user = users_collection.find_one({
        "phone": phone, 
        "api_key": api_key
    })
    if user:
        return True, user
    return False, None

def verify_user_exists(phone: str, api_key: str) -> tuple:
    """验证用户是否存在，返回 (是否存在, 用户信息, 余额始终为0)"""
    if users_collection is None:
        return False, None, 0
    user = users_collection.find_one({
        "phone": phone, 
        "api_key": api_key
    })
    if user:
        return True, user, 0
    return False, None, 0

def generate_api_key(phone: str) -> str:
    """生成 API Key（8位随机字符串）"""
    import secrets
    return f"ak_{phone[-6:]}_{secrets.token_hex(4)}"

def add_user(phone: str, days_valid: int = 62) -> str:
    """添加用户，返回 api_key"""
    api_key = generate_api_key(phone)
    expire_at = datetime.now() + timedelta(days=days_valid) if days_valid > 0 else None
    
    users_collection.update_one(
        {"phone": phone},
        {"$setOnInsert": {
            "phone": phone, 
            "api_key": api_key, 
            "created_at": datetime.now(),
            "expire_at": expire_at
        }},
        upsert=True
    )
    return api_key

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
        return {"total": 0}
    total = users_collection.count_documents({})
    return {"total": total}

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

def record_usage():
    """记录一次使用"""
    if stats_collection is None:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    stats_collection.update_one(
        {"date": today},
        {"$inc": {"total_calls": 1}, "$setOnInsert": {"date": today}},
        upsert=True
    )