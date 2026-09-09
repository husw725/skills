import sys
import json
import urllib.request
import urllib.error
import io

# 强制设置标准输出和错误输出为 UTF-8，解决 Windows 控制台乱码问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    # stdin 同样要包：管道模式（推荐）读的就是 stdin，UTF-8 内容按 GBK 解码正是乱码源头
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')

def send_message(webhook_url, text):
    headers = {'Content-Type': 'application/json; charset=utf-8'}
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": "Gemini CLI 通知",
            "text": text
        }
    }
    
    payload = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url=webhook_url, data=payload, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get("errcode") == 0:
                print("Success: 消息发送成功。")
            else:
                print(f"Failed: 钉钉接口返回错误 - {result.get('errmsg')} (错误码: {result.get('errcode')})")
                sys.exit(1)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', errors='replace')
        print(f"Error: HTTP 请求失败 - 状态码 {e.code}")
        print(f"服务器响应内容: {error_body}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: 发生未知错误 - {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    # 如果参数不足，或者第二个参数是 '-'，则尝试从 stdin 读取消息内容
    if len(sys.argv) < 2:
        print("用法: python send.py <webhook_url> [markdown_message]")
        sys.exit(1)
        
    webhook = sys.argv[1]
    
    if len(sys.argv) == 2:
        # 模式1: 从标准输入读取消息 (更推荐用于 Windows 复杂字符)
        message = sys.stdin.read().strip()
    else:
        # 模式2: 从命令行参数读取
        message = sys.argv[2]
        
    if not message:
        print("Error: 消息内容不能为空。")
        sys.exit(1)
        
    send_message(webhook, message)
