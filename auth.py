from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, Header
from jose import JWTError, jwt
import config

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