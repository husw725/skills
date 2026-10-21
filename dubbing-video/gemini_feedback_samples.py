"""Generate checkpointed pt-BR audition audio on Windows without cloning voices."""
import argparse
import base64
import hashlib
import io
import os
from pathlib import Path
import re
import sys
import time
import wave

from process_lock import process_lock
from translate import fingerprint, read_json, save_json
from dub_episode import digest

MODEL = 'gemini-2.5-pro-preview-tts'


def payload(item):
    prompt = ('Interprete SOMENTE o texto entre <fala> e </fala>, em português brasileiro '
              'nativo, com pronúncia brasileira consistente e sem sotaque inglês ou europeu. '
              'Não leia as instruções nem acrescente palavras. Preserve a identidade vocal. '
              + item['direction'] + '\n<fala>' + item['text'] + '</fala>')
    return {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
            'generationConfig': {'responseModalities': ['AUDIO'], 'speechConfig': {
                'languageCode': 'pt-BR',
                'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': item['voice']}}}}}


def decode_audio(response):
    candidates = response.get('candidates', [])
    if len(candidates) != 1 or candidates[0].get('finishReason') != 'STOP':
        raise ValueError('Incomplete synthesis; retain response, do not resubmit')
    parts = candidates[0].get('content', {}).get('parts', [])
    blocks = [p['inlineData'] for p in parts if 'inlineData' in p]
    if len(blocks) != 1:
        raise ValueError('Expected one audio block; retain response')
    block = blocks[0]; mime = block.get('mimeType', '')
    raw = base64.b64decode(block['data'], validate=True)
    if mime in ('audio/wav', 'audio/x-wav'):
        result = raw
    elif mime.startswith('audio/L16') and 'rate=24000' in mime:
        if not raw or len(raw) % 2:
            raise ValueError('Invalid PCM payload')
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000); wav.writeframes(raw)
        result = buf.getvalue()
    else:
        raise ValueError('Unsupported audio format; response retained')
    with wave.open(io.BytesIO(result), 'rb') as wav:
        duration = wav.getnframes() / wav.getframerate()
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or not .1 <= duration <= 90:
            raise ValueError('Unexpected audition audio shape')
    return result, duration


def generate(item, root, http):
    folder = root / item['id']; folder.mkdir(parents=True, exist_ok=True)
    request = payload(item)
    signature = fingerprint({'model': MODEL, 'item': item, 'request': request})
    state_path = folder / 'request-state.private.json'
    response_path = folder / 'response.private.json'
    audio_path = folder / 'gemini.wav'
    with process_lock(folder / 'request.lock', timeout=0):
        if state_path.exists():
            state = read_json(state_path)
            if state['fingerprint'] != signature:
                raise ValueError('Audition request changed; preserve prior paid result')
            if state['status'] == 'completed':
                if digest(audio_path) != state['audio_sha256']:
                    raise ValueError('Cached audio changed')
                return state
            if not response_path.exists():
                raise ValueError('Prior submission unresolved or rejected; no automatic retry')
        else:
            if response_path.exists() or audio_path.exists():
                raise ValueError('Orphan audition output; inspect before submission')
            state = {'fingerprint': signature, 'model': MODEL, 'request': request,
                     'item': item, 'status': 'submitting', 'started_at': time.time()}
            save_json(state_path, state)
            import requests
            try:
                response = http.post(
                    'https://generativelanguage.googleapis.com/v1beta/models/' + MODEL + ':generateContent',
                    headers={'x-goog-api-key': os.environ['GEMINI_API_KEY']},
                    json=request, timeout=150, allow_redirects=False)
            except requests.RequestException:
                raise RuntimeError('Gemini connection outcome uncertain; checkpoint retained, no retry') from None
            if response.status_code != 200:
                state.update(status='http_rejected', http_status=response.status_code)
                try:
                    error=response.json().get('error', {})
                    state['error_status']=error.get('status')
                    state['error_details']=error.get('details', [])
                except ValueError:
                    pass
                save_json(state_path, state)
                raise RuntimeError('Gemini HTTP ' + str(response.status_code) + '; private diagnostics retained')
            save_json(response_path, response.json())
        body, duration = decode_audio(read_json(response_path))
        temp = folder / 'gemini.tmp.wav'; temp.write_bytes(body); temp.replace(audio_path)
        state.update(status='completed', audio_sha256=hashlib.sha256(body).hexdigest(),
                     duration_seconds=duration, completed_at=time.time(), cloning_performed=False,
                     native_listening_passed=False)
        save_json(state_path, state)
        return state


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--limit',type=int,default=1)
    a=p.parse_args()
    if sys.platform!='win32':p.error('Business execution runs on Windows')
    if not os.environ.get('GEMINI_API_KEY'):p.error('Existing Gemini key required')
    manifest=read_json(a.manifest)
    items=manifest['items']
    if not 1<=a.limit<=len(items)<=40:p.error('Expected bounded audition manifest')
    if len({i['id'] for i in items})!=len(items):p.error('Duplicate audition identifiers')
    for item in items:
        if not re.fullmatch(r'ep\d{2}-[a-z0-9-]+',item['id']):p.error('Invalid audition identifier')
        if item['voice'] not in ('Kore','Leda','Charon','Gacrux','Fenrir','Zephyr'):p.error('Unexpected predefined voice')
        if not item['text'].strip() or len(item['text'])>1000 or not item['comment_ids']:p.error('Unscoped audition')
        for source,sha in item['input_sha256'].items():
            if digest(Path(source))!=sha:p.error('Reviewed audition source changed')
    import requests
    reused={};aliases={}
    with requests.Session() as http:
        for item in items[:a.limit]:
            key=fingerprint({'model':MODEL,'request':payload(item)})
            if key in reused:
                source=reused[key]
                aliases[item['id']]={'source_item_id':source['item']['id'],
                    'audio_sha256':source['audio_sha256'],'request_fingerprint':key}
                save_json(a.output/'aliases.private.json',aliases)
                print('GEMINI_SAMPLE_EXACT_REUSE',item['id'],source['item']['id'],flush=True)
                continue
            result=generate(item,a.output,http)
            reused[key]=result
            print('GEMINI_SAMPLE_READY',item['id'],round(result['duration_seconds'],3),flush=True)


if __name__=='__main__':main()
