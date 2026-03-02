import base64
import requests
import json
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

# 原始 RSA 公钥
public_key_str = 'MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBAKoR8mX0rGKLqzcWmOzbfj64K8ZIgOdHnzkXSOVOZbFu/TJhZ7rFAN+eaGkl3C4buccQd/EjEsj9ir7ijT7h96MCAwEAAQ=='

def encrypt_full_body(data_dict, pub_key_str):
    pem_key = f"-----BEGIN PUBLIC KEY-----\n{pub_key_str}\n-----END PUBLIC KEY-----"
    pub_key = RSA.importKey(pem_key)
    cipher = PKCS1_v1_5.new(pub_key)
    
    # 将字典转为紧凑的 JSON 字符串
    json_str = json.dumps(data_dict, separators=(',', ':'))
    print(f"Original JSON String (Length: {len(json_str)}): {json_str}")
    
    encrypted_bytes = cipher.encrypt(json_str.encode('utf-8'))
    return base64.b64encode(encrypted_bytes).decode('utf-8')

# 准备数据
url = "https://mflixapi.starlitshorts.com/adsmanager/auth/login"
payload = {
    "username": "husw",
    "password": "123qwe",
    "clientId": "428a8310cd442757ae699df5d894f051",
    "grantType": "password",
    "tenantId": "107184"
}

# 1. 尝试对整个 Body 加密并作为 raw 内容发送
print("\n--- Testing: Encrypt Full Body ---")
encrypted_body = encrypt_full_body(payload, public_key_str)

try:
    # 某些系统可能需要 {"data": "..."} 这种格式，也可能直接发送密文串
    # 我们先尝试直接发送 Base64 密文串
    resp = requests.post(url, data=encrypted_body, headers={"Accept": "application/json", "Content-Type": "application/json"})
    print(f"Response Code: {resp.status_code}")
    print(f"Response Body: {resp.text}")
except Exception as e:
    print(f"Error: {e}")

# 2. 尝试明文发送密码（作为对比）
print("\n--- Testing: Plain Text Body ---")
try:
    resp = requests.post(url, json=payload, headers={"Accept": "application/json", "Content-Type": "application/json"})
    print(f"Response Code: {resp.status_code}")
    print(f"Response Body: {resp.text}")
except Exception as e:
    print(f"Error: {e}")

