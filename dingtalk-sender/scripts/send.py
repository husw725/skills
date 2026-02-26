import sys
import json
import urllib.request

def send_message(webhook_url, text):
    headers = {'Content-Type': 'application/json;charset=utf-8'}
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": "Gemini CLI 通知",
            "text": text
        }
    }
    
    req = urllib.request.Request(url=webhook_url, data=json.dumps(data).encode('utf-8'), headers=headers)
    try:
        response = urllib.request.urlopen(req)
        result = json.loads(response.read().decode('utf-8'))
        if result.get("errcode") == 0:
            print("Success: Message sent successfully.")
        else:
            print(f"Failed: DingTalk returned error - {result.get('errmsg')}")
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python send.py <webhook_url> <markdown_message>")
        sys.exit(1)
        
    webhook = sys.argv[1]
    message = sys.argv[2]
    send_message(webhook, message)