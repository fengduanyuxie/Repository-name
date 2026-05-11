from datetime import datetime, timedelta
from typing import Optional, Dict
from fastapi import HTTPException, Header
from jose import JWTError, jwt
import config

rate_limit_store: Dict[str, list] = {}

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT Token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.ALGORITHM)

def verify_admin_token(token: str) -> bool:
    """验证管理员 Token"""
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        return payload.get("role") == "admin"
    except JWTError:
        return False

def verify_admin_request(authorization: Optional[str] = Header(None)):
    """验证管理员请求的依赖函数"""
    if not authorization:
        raise HTTPException(401, detail="缺少认证信息")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, detail="认证格式错误")
    token = authorization[7:]
    if not verify_admin_token(token):
        raise HTTPException(401, detail="Token 无效或已过期")
    return True

def rate_limit(phone: str, limit: int = 10, window: int = 60) -> bool:
    """频率限制"""
    now = datetime.now()
    key = f"rate_limit_{phone}"
    
    if key not in rate_limit_store:
        rate_limit_store[key] = []
    
    rate_limit_store[key] = [t for t in rate_limit_store[key] if now - t < timedelta(seconds=window)]
    
    if len(rate_limit_store[key]) >= limit:
        return False
    
    rate_limit_store[key].append(now)
    return True

def get_rate_limit_remaining(phone: str, limit: int = 10, window: int = 60) -> int:
    """获取剩余可用次数"""
    now = datetime.now()
    key = f"rate_limit_{phone}"
    
    if key not in rate_limit_store:
        return limit
    
    valid = [t for t in rate_limit_store[key] if now - t < timedelta(seconds=window)]
    return max(0, limit - len(valid))