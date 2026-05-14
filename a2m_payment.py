# a2m_payment.py
# 支付宝A2M智能收产品对接（基于HTTP 402协议）

import json
import base64
from datetime import datetime, timedelta
from typing import Dict, Optional
import requests
import os


class A2MPaymentService:
    """A2M智能收支付服务"""
    
    def __init__(self, app_id: str, private_key_pem: str, alipay_public_key_pem: str, seller_id: str):
        self.app_id = app_id
        self.private_key_pem = private_key_pem
        self.alipay_public_key_pem = alipay_public_key_pem
        self.seller_id = seller_id
        self.gateway_url = "https://openapi.alipay.com/gateway.do"
        
        # 加载私钥用于签名（支持多种格式）
        self.private_key = None
        if private_key_pem:
            try:
                # 尝试直接导入
                from Crypto.PublicKey import RSA
                self.private_key = RSA.import_key(private_key_pem)
                print("私钥加载成功 (PKCS#8格式)")
            except Exception as e1:
                try:
                    # 尝试添加 RSA 私钥头尾
                    from Crypto.PublicKey import RSA
                    if not private_key_pem.startswith('-----'):
                        pem_key = f"-----BEGIN RSA PRIVATE KEY-----\n{private_key_pem}\n-----END RSA PRIVATE KEY-----"
                        self.private_key = RSA.import_key(pem_key)
                        print("私钥加载成功 (PKCS#1格式，已添加头尾)")
                    else:
                        raise e1
                except Exception as e2:
                    print(f"私钥加载失败: {e2}")
                    self.private_key = None
    
    def _rsa2_sign(self, content: str) -> str:
        """RSA2签名"""
        if not self.private_key:
            raise ValueError("私钥未正确加载")
        from Crypto.Signature import pkcs1_15
        from Crypto.Hash import SHA256
        h = SHA256.new(content.encode('utf-8'))
        signature = pkcs1_15.new(self.private_key).sign(h)
        return base64.b64encode(signature).decode('utf-8')
    
    def _generate_seller_signature(self, params: Dict[str, str]) -> str:
        """生成商家签名（seller_signature）"""
        sorted_keys = sorted(params.keys())
        sign_parts = []
        for key in sorted_keys:
            value = params.get(key)
            if value is not None and str(value).strip():
                sign_parts.append(f"{key}={value}")
        sign_content = "&".join(sign_parts)
        return self._rsa2_sign(sign_content)
    
    def create_payment_needed_response(
        self, 
        out_trade_no: str, 
        amount: str, 
        resource_id: str,
        goods_name: str = "征信报告分析服务",
        seller_name: str = "征信报告分析系统"
    ):
        from fastapi.responses import JSONResponse
        
        currency = "CNY"
        pay_before = (datetime.now() + timedelta(minutes=30)).isoformat()
        service_id = "credit_report_service_001"
        
        sign_params = {
            "amount": amount,
            "currency": currency,
            "goods_name": goods_name,
            "out_trade_no": out_trade_no,
            "pay_before": pay_before,
            "resource_id": resource_id,
            "seller_id": self.seller_id,
            "service_id": service_id,
        }
        
        try:
            seller_signature = self._generate_seller_signature(sign_params)
        except Exception as e:
            print(f"生成签名失败: {e}")
            seller_signature = "sign_error"
        
        payment_needed = {
            "protocol": {
                "out_trade_no": out_trade_no,
                "amount": amount,
                "currency": currency,
                "resource_id": resource_id,
                "pay_before": pay_before,
                "seller_signature": seller_signature,
                "seller_sign_type": "RSA2",
                "seller_unique_id": self.seller_id
            },
            "method": {
                "seller_name": seller_name,
                "seller_id": self.seller_id,
                "seller_app_id": self.app_id,
                "goods_name": goods_name,
                "seller_unique_id_key": "seller_id",
                "service_id": service_id
            }
        }
        
        payment_needed_json = json.dumps(payment_needed, separators=(',', ':'))
        payment_needed_encoded = base64.urlsafe_b64encode(
            payment_needed_json.encode('utf-8')
        ).decode('utf-8').rstrip('=')
        
        response = JSONResponse(
            status_code=402,
            content={
                "code": "Payment-Needed",
                "message": "需要支付",
                "out_trade_no": out_trade_no,
                "amount": str(amount),
                "currency": currency,
                "goods_name": goods_name
            }
        )
        response.headers["Payment-Needed"] = payment_needed_encoded
        return response
    
    def verify_payment_proof(self, payment_proof: str, trade_no: str, out_trade_no: str) -> Dict:
        """验证支付凭证（简化版，实际需调用支付宝API）"""
        # TODO: 完整实现需要调用支付宝API
        return {
            "success": True,
            "active": True,
            "trade_no": trade_no,
            "out_trade_no": out_trade_no
        }
    
    def send_fulfillment_confirm(self, trade_no: str) -> bool:
        """发送履约确认（简化版）"""
        print(f"履约确认: trade_no={trade_no}")
        return True


def get_a2m_service():
    """从环境变量初始化A2M服务"""
    app_id = os.environ.get("ALIPAY_APP_ID", "")
    private_key = os.environ.get("ALIPAY_PRIVATE_KEY", "")
    alipay_public_key = os.environ.get("ALIPAY_PUBLIC_KEY", "")
    seller_id = os.environ.get("SELLER_ID", "2088302959332295")
    
    if not app_id or not private_key:
        print("警告: 支付宝配置不完整，A2M支付功能将不可用")
        return None
    
    print(f"A2M服务初始化: app_id={app_id}, seller_id={seller_id}")
    return A2MPaymentService(
        app_id=app_id,
        private_key_pem=private_key,
        alipay_public_key_pem=alipay_public_key,
        seller_id=seller_id
    )