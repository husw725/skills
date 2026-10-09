"""Authenticated MCP access; private configuration stays outside the repository."""
import json
from pathlib import Path
import time
import urllib.error
import urllib.request


class Mflix:
    def __init__(self, config):
        cfg=json.loads(Path(config).read_text(encoding='utf-8-sig'))
        self.url=cfg['url']
        if not self.url.startswith('https://'):
            raise ValueError('MCP must use HTTPS')
        self.headers={**cfg['headers'],'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
        import requests
        self.http=requests.Session()
        self.counter=0
        self.rpc('initialize',{'protocolVersion':'2024-11-05','capabilities':{},
                 'clientInfo':{'name':'windows-drama-dubbing','version':'1'}})

    def rpc(self,method,params):
        self.counter+=1
        payload=json.dumps({'jsonrpc':'2.0','id':self.counter,'method':method,'params':params}).encode()
        import requests
        safe = method == 'initialize' or (method == 'tools/call' and params.get('name') in
                  ('getTaskById','getModels','getProjects','createFilePresignedUrl'))
        for attempt in range(3 if safe else 1):
            try:
                response=self.http.post(self.url,data=payload,headers=self.headers,timeout=180)
                if response.status_code!=200:raise RuntimeError(f'MCP HTTP {response.status_code}; response omitted')
                session=response.headers.get('Mcp-Session-Id')
                if session:self.headers['Mcp-Session-Id']=session
                raw=response.text
                break
            except requests.RequestException:
                if not safe or attempt==2:raise RuntimeError('MCP connection failed; submission status may be unknown') from None
                time.sleep(2**attempt)
        if raw.lstrip().startswith('{'):
            result=json.loads(raw)
        else:
            messages=[json.loads(line[6:]) for line in raw.splitlines() if line.startswith('data: ')]
            result=next((m for m in messages if m.get('id')==self.counter),None)
            if result is None:raise RuntimeError('MCP response had no matching request ID')
        if 'error' in result:raise RuntimeError('MCP rejected RPC request; credentials and response omitted')
        if 'result' not in result:raise RuntimeError(f'MCP service rejected request (code {result.get("code")})')
        return result['result']

    def call(self,name,arguments):
        result=self.rpc('tools/call',{'name':name,'arguments':arguments})
        if result.get('isError'):raise RuntimeError(f'MCP tool {name} failed; raw response omitted')
        texts=[c['text'] for c in result.get('content',[]) if c.get('type')=='text']
        if not texts:raise RuntimeError('MCP tool returned no JSON content')
        obj=json.loads(texts[0])
        if obj.get('code') not in (None,200):raise RuntimeError(f'MCP tool {name} service code {obj.get("code")}; response omitted')
        return obj['data'] if obj.get('data') is not None else obj.get('msg',obj)

    def upload(self,path):
        path=Path(path)
        signed=self.call('createFilePresignedUrl',{'originalFileName':path.name})
        if not isinstance(signed,str) or not signed.startswith('https://'):
            raise RuntimeError('No HTTPS presigned upload URL')
        import requests
        for attempt in range(3):
            try:
                response=self.http.put(signed,data=path.read_bytes(),timeout=180)
                if response.status_code not in (200,201,204):raise RuntimeError(f'Upload HTTP {response.status_code}; URL omitted')
                break
            except requests.RequestException:
                if attempt==2:raise RuntimeError('Reference upload connection failed; URL omitted') from None
                time.sleep(2**attempt)
        return signed.split('?')[0]

    def task(self,task_id):
        return self.call('getTaskById',{'taskId':int(task_id)})
