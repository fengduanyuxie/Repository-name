# auth.py 中的 rate_limit 函数修改

def rate_limit(identifier: str, limit: int = 10, window: int = 60) -> bool:
    """频率限制 - 支持手机号或IP"""
    now = datetime.now()
    key = f"rate_limit_{identifier}"
    
    if key not in rate_limit_store:
        rate_limit_store[key] = []
    
    rate_limit_store[key] = [t for t in rate_limit_store[key] if now - t < timedelta(seconds=window)]
    
    if len(rate_limit_store[key]) >= limit:
        return False
    
    rate_limit_store[key].append(now)
    return True

def get_rate_limit_remaining(identifier: str, limit: int = 10, window: int = 60) -> int:
    """获取剩余可用次数"""
    now = datetime.now()
    key = f"rate_limit_{identifier}"
    
    if key not in rate_limit_store:
        return limit
    
    valid = [t for t in rate_limit_store[key] if now - t < timedelta(seconds=window)]
    return max(0, limit - len(valid))