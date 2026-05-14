# a2m_payment.py
# 支付宝A2M智能收产品对接（基于HTTP 402协议）
# 参考官方Java示例代码实现

import json
import base64
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import requests
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
import os


class A2MPaymentService:
    """A2M智能收支付服务"""
    
    def __init__(self, app_id: str, private_key_pem: str, alipay_public_key_pem: str, seller_id: str):
        self.app_id = app_id
        self.private_key_pem = private_key_pem
        self.alipay_public_key_pem = alipay_public_key_pem
        self.seller_id = seller_id
        self.gateway_url = "https://openapi.alipay.com/gateway.do"
        
        # 加载私钥用于签名
        try:
            self.private_key = RSA.import_key(private_key_pem)
        except Exception as e:
            print(f"加载私钥失败: {e}")
            self.private_key = None
    
    def _rsa2_sign(self, content: str) -> str:
        """RSA2签名"""
        if not self.private_key:
            raise ValueError("私钥未正确加载")
        h = SHA256.new(content.encode('utf-8'))
        signature = pkcs1_15.new(self.private_key).sign(h)
        return base64.b64encode(signature).decode('utf-8')
    
    def _generate_seller_signature(self, params: Dict[str, str]) -> str:
        """生成商家签名（seller_signature）"""
        # 1. 按key字典序排序
        sorted_keys = sorted(params.keys())
        
        # 2. 拼接签名内容
        sign_parts = []
        for key in sorted_keys:
            value = params.get(key)
            if value is not None and str(value).strip():
                sign_parts.append(f"{key}={value}")
        
        sign_content = "&".join(sign_parts)
        
        # 3. RSA2签名
        return self._rsa2_sign(sign_content)
    
    def create_payment_needed_response(
        self, 
        out_trade_no: str, 
        amount: str, 
        resource_id: str,
        goods_name: str = "征信报告分析服务",
        seller_name: str = "征信报告分析系统"
    ):
        """
        构造402 Payment-Needed响应
        当用户第一次请求时返回，要求用户支付
        返回 FastAPI Response 对象
        """
        from fastapi.responses import JSONResponse
        
        currency = "CNY"
        pay_before = (datetime.now() + timedelta(minutes=30)).isoformat()
        service_id = "credit_report_service_001"
        
        # 构造签名参数
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
        
        # 生成签名
        seller_signature = self._generate_seller_signature(sign_params)
        
        # 构造 Payment-Needed Header 内容
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
        
        # Base64URL编码（去掉填充）
        payment_needed_json = json.dumps(payment_needed, separators=(',', ':'))
        payment_needed_encoded = base64.urlsafe_b64encode(
            payment_needed_json.encode('utf-8')
        ).decode('utf-8').rstrip('=')
        
        # 返回402响应
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
    
    def verify_payment_proof(
        self, 
        payment_proof: str, 
        trade_no: str,
        out_trade_no: str,
        client_session: str = None
    ) -> Dict:
        """
        验证支付凭证
        调用支付宝 alipay.aipay.agent.payment.verify 接口
        """
        # 构建请求参数
        # 参考 Java 代码: AlipayAipayAgentPaymentVerifyRequest
        
        # 构建业务参数
        biz_content = {
            "payment_proof": payment_proof,
            "trade_no": trade_no,
        }
        if client_session:
            biz_content["client_session"] = client_session
        
        # 构建公共请求参数
        params = {
            "app_id": self.app_id,
            "method": "alipay.aipay.agent.payment.verify",
            "format": "JSON",
            "charset": "UTF-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "biz_content": json.dumps(biz_content, separators=(',', ':'))
        }
        
        # 生成签名
        sorted_keys = sorted(params.keys())
        sign_str = "&".join([f"{k}={params[k]}" for k in sorted_keys if params[k]])
        params["sign"] = self._rsa2_sign(sign_str)
        
        # 发送请求
        try:
            response = requests.post(self.gateway_url, data=params, timeout=30)
            result = response.json()
            
            # 解析响应
            if "alipay_aipay_agent_payment_verify_response" in result:
                resp_data = result["alipay_aipay_agent_payment_verify_response"]
                if resp_data.get("code") == "10000":
                    return {
                        "success": True,
                        "trade_no": resp_data.get("trade_no"),
                        "out_trade_no": resp_data.get("out_trade_no"),
                        "resource_id": resp_data.get("resource_id"),
                        "active": resp_data.get("active", False),
                        "amount": resp_data.get("amount"),
                        "sub_code": None,
                        "sub_msg": None
                    }
                else:
                    return {
                        "success": False,
                        "active": False,
                        "sub_code": resp_data.get("sub_code"),
                        "sub_msg": resp_data.get("sub_msg")
                    }
            else:
                return {"success": False, "active": False, "sub_msg": "响应格式错误"}
                
        except Exception as e:
            return {"success": False, "active": False, "sub_msg": str(e)}
    
    def send_fulfillment_confirm(self, trade_no: str) -> bool:
        """
        发送履约确认
        调用支付宝 alipay.aipay.agent.fulfillment.confirm 接口
        """
        # 构建业务参数
        biz_content = {
            "trade_no": trade_no
        }
        
        # 构建公共请求参数
        params = {
            "app_id": self.app_id,
            "method": "alipay.aipay.agent.fulfillment.confirm",
            "format": "JSON",
            "charset": "UTF-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "biz_content": json.dumps(biz_content, separators=(',', ':'))
        }
        
        # 生成签名
        sorted_keys = sorted(params.keys())
        sign_str = "&".join([f"{k}={params[k]}" for k in sorted_keys if params[k]])
        params["sign"] = self._rsa2_sign(sign_str)
        
        # 发送请求
        try:
            response = requests.post(self.gateway_url, data=params, timeout=30)
            result = response.json()
            
            if "alipay_aipay_agent_fulfillment_confirm_response" in result:
                resp_data = result["alipay_aipay_agent_fulfillment_confirm_response"]
                if resp_data.get("code") == "10000":
                    print(f"履约确认成功: trade_no={trade_no}")
                    return True
                else:
                    print(f"履约确认失败: {resp_data.get('sub_msg')}")
                    return False
            else:
                print(f"履约确认响应格式错误: {result}")
                return False
                
        except Exception as e:
            print(f"履约确认异常: {e}")
            return False


def get_a2m_service():
    """从环境变量初始化A2M服务"""
    app_id = os.environ.get("ALIPAY_APP_ID", "")
    private_key = os.environ.get("ALIPAY_PRIVATE_KEY", "")
    alipay_public_key = os.environ.get("ALIPAY_PUBLIC_KEY", "")
    seller_id = os.environ.get("SELLER_ID", "2088302959332295")
    
    if not app_id or not private_key:
        print("警告: 支付宝配置不完整，A2M支付功能将不可用")
        return None
    
    return A2MPaymentService(
        app_id=app_id,
        private_key_pem=private_key,
        alipay_public_key_pem=alipay_public_key,
        seller_id=seller_id
    )