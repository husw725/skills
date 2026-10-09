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
        self.counter=0
        self.rpc('initialize',{'protocolVersion':'2024-11-05','capabilities':{},
                 'clientInfo':{'name':'windows-drama-dubbing','version':'1'}})

    def rpc(self,method,params):
        self.counter+=1
        payload=json.dumps({'jsonrpc':'2.0','id':self.counter,'method':method,'params':params}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url,data=payload,headers=self.headers),timeout=180) as response:
                session=response.headers.get('Mcp-Session-Id')
                if session:self.headers['Mcp-Session-Id']=session
                raw=response.read().decode()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'MCP HTTP {exc.code}; response omitted') from None
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
        try:
            with urllib.request.urlopen(urllib.request.Request(signed,data=path.read_bytes(),method='PUT'),timeout=180) as response:
                if response.status not in (200,201,204):raise RuntimeError('Upload failed')
        except urllib.error.HTTPError as exc:raise RuntimeError(f'Upload HTTP {exc.code}; URL omitted') from None
        return signed.split('?')[0]

    def task(self,task_id):
        return self.call('getTaskById',{'taskId':int(task_id)})
