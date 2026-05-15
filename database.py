# ========== 订单表查询方法（追加到 database.py 末尾）==========

def get_order_by_out_trade_no(out_trade_no: str):
    """根据商户订单号获取订单"""
    if orders_collection is None:
        return None
    return orders_collection.find_one({"out_trade_no": out_trade_no}, {"_id": 0})


def is_order_already_fulfilled(out_trade_no: str) -> bool:
    """检查订单是否已履约（防重放）"""
    if orders_collection is None:
        return False
    order = orders_collection.find_one({"out_trade_no": out_trade_no})
    return order and order.get("status") in ["paid", "fulfilled"]