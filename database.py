from datetime import datetime
from typing import Dict, Any, Tuple, List, Optional
from pymongo import MongoClient
import config

mongo_client = None
db = None
users_collection = None

def init_db():
    """初始化数据库连接"""
    global mongo_client, db, users_collection
    if not config.MONGO_URI:
        print("警告: MONGO_URI 未设置")
        return False
    
    try:
        mongo_client = MongoClient(config.MONGO_URI)
        db = mongo_client[config.MONGO_DB]
        users_collection = db["users"]
        users_collection.create_index("phone", unique=True)
        users_collection.create_index("api_key", unique=True)
        print("MongoDB 连接成功")
        return True
    except Exception as e:
        print(f"MongoDB 连接失败: {e}")
        return False

def verify_user(phone: str, api_key: str) -> tuple:
    """验证用户"""
    if users_collection is None:
        return False, 0
    user = users_collection.find_one({"phone": phone, "api_key": api_key})
    if user and user.get("balance", 0) > 0:
        return True, user["balance"]
    return False, 0

def consume_balance(phone: str, api_key: str) -> bool:
    """扣减次数"""
    if users_collection is None:
        return False
    result = users_collection.update_one(
        {"phone": phone, "api_key": api_key, "balance": {"$gt": 0}},
        {"$inc": {"balance": -1}, "$set": {"last_used_at": datetime.now()}}
    )
    return result.modified_count > 0

def generate_api_key(phone: str) -> str:
    """生成 API Key"""
    import secrets
    return f"ak_{phone[-6:]}_{secrets.token_hex(8)}"

def add_or_recharge_user(phone: str, balance: int) -> tuple:
    """添加或充值用户"""
    api_key = generate_api_key(phone)
    result = users_collection.update_one(
        {"phone": phone},
        {"$setOnInsert": {"phone": phone, "api_key": api_key, "created_at": datetime.now()},
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

def get_all_users() -> List[Dict]:
    """获取所有用户"""
    if users_collection is None:
        return []
    return list(users_collection.find({}, {"_id": 0}).sort("created_at", -1))

def get_user_by_phone(phone: str) -> Optional[Dict]:
    """根据手机号获取用户"""
    if users_collection is None:
        return None
    return users_collection.find_one({"phone": phone}, {"_id": 0})