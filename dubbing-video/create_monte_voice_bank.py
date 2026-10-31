"""Create at most five approved role voices once; never synthesize dialogue."""
import argparse
from pathlib import Path
import re
import sys
import hashlib
from urllib.parse import urlsplit
from dub_episode import digest, safe_submit
from cartesia_pilot import bind
from process_lock import process_lock
from translate import read_json, save_json, fingerprint

REFERENCES=Path('output/review-project-100/voice-preparation-20261031')
ROOT=Path('output/review-project-100/voice-bank-minimax-20261031')


def approved_inputs():
    proposal=read_json(REFERENCES/'reference-proposal.private.json');fp=fingerprint(proposal)
    approval=read_json(REFERENCES/'voice-reference-approval.private.json')
    if (proposal['project_id']!=100 or proposal['episode']!=1 or len(proposal['roles'])!=5
        or any(not re.fullmatch(r'[a-z][a-z0-9_]{0,60}',role) for role in proposal['roles'])
        or proposal['clone_calls']!=0 or proposal['tts_calls']!=0 or proposal['ready_for_clone'] is not False
        or approval['input_fingerprint']!=fp or approval['proposal_sha256']!=digest(REFERENCES/'reference-proposal.private.json')
        or approval['clone_reference_candidates_approved'] is not True
        or approval['native_listening_passed'] is not False or approval['max_new_clones']!=5
        or digest(approval['audit_report_path'])!=approval['audit_report_sha256']):
        raise ValueError('Actual independently reviewed reference approval required')
    search=read_json(approval['existing_voice_search_path'])
    if (digest(approval['existing_voice_search_path'])!=approval['existing_voice_search_sha256']
        or search['project_id']!=100 or search['no_reusable_voice_identified'] is not True
        or search['catalog_coverage'] not in ('complete','partial_no_voice_listing_tool')):
        raise ValueError('Existing voice search evidence required; do not claim unavailable full catalog coverage')
    if set(approval['reference_receipt_sha256'])!=set(proposal['roles']):
        raise ValueError('Approval must cover exactly the five reference roles')
    for role in proposal['roles']:
        receipt=REFERENCES/role/'receipt.private.json';r=read_json(receipt);wav=REFERENCES/role/'reference.wav'
        if (r['role']!=role or r['input_fingerprint']!=fp or not 10<=r['seconds']<=45
            or digest(receipt)!=approval['reference_receipt_sha256'][role]
            or wav.stat().st_size>16*1024*1024 or digest(wav)!=r['sha256']):
            raise ValueError('Approved reference evidence changed')
    for path,sha in proposal['inputs_sha256'].items():
        if digest(path)!=sha:raise ValueError('Reference source changed')
    return proposal,fp


def has_project(data):
    if isinstance(data,dict):
        if any(str(data.get(key))=='100' for key in ('project_id','projectId')):return True
        return any(has_project(value) for value in data.values())
    return isinstance(data,list) and any(has_project(value) for value in data)


def external_cache_gate(roles):
    canonical_bank=(ROOT/'voice-bank.private.json').resolve()
    receipts={(ROOT/role/'clone.private.json').resolve() for role in roles}
    for path in Path('output').rglob('*.json'):
        name=path.name.lower();is_pending=name.endswith('.submission-pending.json')
        is_bank='voice' in name and 'bank' in name
        is_clone='clone' in name and path.resolve() not in receipts
        if not (is_pending or is_bank or is_clone):continue
        if path.resolve()==canonical_bank:continue
        value=read_json(path)
        in_project=Path('output/review-project-100').resolve() in path.resolve().parents or has_project(value)
        if is_pending:
            # An unattributed uploadVoice pending may be this project; never assume otherwise.
            if not isinstance(value,dict) or value.get('tool')=='uploadVoice' or in_project:
                raise ValueError('Unknown paid/clone submission requires reconciliation')
        elif in_project and (is_bank or is_clone):
            raise ValueError('Another project100 bank or clone cache exists; reconcile before new cloning')


def voice_id(result,role):
    if (not isinstance(result,dict) or any(k in result for k in ('taskId','taskStatus','error','status'))
      or not isinstance(result.get('voiceId'),str)
      or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}',result['voiceId'])
      or ('projectId' in result and str(result['projectId'])!='100')
      or ('platform' in result and str(result['platform']).lower()!='minimax')
      or ('name' in result and result['name']!=f'project100_{role}')):
        raise ValueError('Unknown clone result preserved; no automatic resubmission')
    return result['voiceId']


def upload_url(value):
    if not isinstance(value,str):raise ValueError('Invalid uploaded reference URL')
    u=urlsplit(value)
    if (u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443)
      or u.query or u.fragment):raise ValueError('Unsigned HTTPS reference upload required')
    return value


def source_basis(role,fp):
    return {'project_id':100,'platform':'minimax','role':role,'reference_fingerprint':fp,
      'reference_sha256':digest(REFERENCES/role/'reference.wav'),
      'reference_receipt_sha256':digest(REFERENCES/role/'receipt.private.json'),
      'approval_sha256':digest(REFERENCES/'voice-reference-approval.private.json')}


def request_for(role,url):
    return {'request':{'projectId':100,'platform':'minimax','name':f'project100_{role}',
      'referenceAudioUrl':upload_url(url),'remark':'Reusable role voice; source attribution from reviewed reference candidate. Brazilian pronunciation and acting require separate listening review.'}}


def check_cached_role(role,basis,bank):
    folder=ROOT/role;folder.mkdir(exist_ok=True)
    marker=folder/'source-binding.private.json';upload_path=folder/'upload.private.json'
    request_marker=folder/'request-fingerprint.private.json';receipt=folder/'clone.private.json'
    if not marker.exists() and any(p.exists() for p in (upload_path,request_marker,receipt)):
        raise ValueError('Unbound existing voice operation; preserve for reconciliation')
    bind(marker,basis)
    upload=None;request=None;result=None
    if upload_path.exists():
        upload=read_json(upload_path)
        if (upload['role']!=role or upload['source_binding']!=fingerprint(basis)
          or upload['reference_sha256']!=basis['reference_sha256']
          or read_json(folder/'upload-fingerprint.private.json')['fingerprint']!=fingerprint(upload)):
            raise ValueError('Cached upload changed role, reference or approval')
        request=request_for(role,upload['url'])
    elif request_marker.exists() or receipt.exists() or (folder/'upload-fingerprint.private.json').exists():
        raise ValueError('Orphan clone/upload evidence requires reconciliation')
    if request_marker.exists():
        if request is None or read_json(request_marker)['fingerprint']!=fingerprint(request):
            raise ValueError('Immutable clone request differs')
    if receipt.exists():
        if not request_marker.exists():raise ValueError('Clone receipt lacks original request binding')
        result=read_json(receipt);voice_id(result,role)
    if role in bank['voices']:
        saved=bank['voices'][role]
        if (result is None or saved['role']!=role or saved['voice_id']!=voice_id(result,role)
          or saved['source_binding']!=fingerprint(basis) or saved['reference_sha256']!=basis['reference_sha256']
          or saved['receipt_sha256']!=digest(receipt) or saved['upload_sha256']!=digest(upload_path)
          or saved['request_fingerprint']!=fingerprint(request)
          or saved['source_speaker_audio_verified'] is not False or saved['native_listening_passed'] is not False):
            raise ValueError('Existing bank voice differs from its immutable source/clone receipts')
    return upload,request,result


def verify_remote(client,url,reference):
    expected=reference.stat().st_size;sha=hashlib.sha256();received=0
    try:
        with client.http.get(url,stream=True,timeout=90,allow_redirects=False) as response:
            response.raise_for_status()
            if response.status_code!=200:raise ValueError('Unexpected uploaded reference response')
            for chunk in response.iter_content(1024*1024):
                received+=len(chunk)
                if received>expected:raise ValueError('Uploaded reference exceeds approved size')
                sha.update(chunk)
    except Exception:raise RuntimeError('Uploaded reference readback failed; URL omitted') from None
    if received!=expected or sha.hexdigest()!=digest(reference):raise ValueError('Uploaded reference SHA differs')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--mcp-config',required=True,type=Path)
    args=parser.parse_args()
    if sys.platform!='win32':raise ValueError('Windows paid execution only')
    ROOT.mkdir(parents=True,exist_ok=True)
    with process_lock(Path('output/paid-production.lock'),timeout=0),process_lock(ROOT/'bank.lock',timeout=0):
        proposal,fp=approved_inputs();bank_path=ROOT/'voice-bank.private.json'
        bank=read_json(bank_path) if bank_path.exists() else {'project_id':100,'platform':'minimax','reference_fingerprint':fp,'voices':{}}
        if (bank['project_id']!=100 or bank['platform']!='minimax' or bank['reference_fingerprint']!=fp
          or not set(bank['voices']).issubset(proposal['roles'])
          or len({v['voice_id'] for v in bank['voices'].values()})!=len(bank['voices'])):
            raise ValueError('Voice bank source or project changed; do not reclone')
        external_cache_gate(proposal['roles'])
        # Check all five caches before any network call, then repair only proven completed receipts.
        bases={r:source_basis(r,fp) for r in sorted(proposal['roles'])}
        cached={r:check_cached_role(r,bases[r],bank) for r in bases};client=None
        known={r:voice_id(state[2],r) for r,state in cached.items() if state[2] is not None}
        if len(set(known.values()))!=len(known):raise ValueError('Completed clone receipts duplicate voice IDs; reconcile before any new cloning')
        for role,basis in bases.items():
            folder=ROOT/role;receipt=folder/'clone.private.json';reference=REFERENCES/role/'reference.wav'
            upload,request,result=cached[role]
            if role in bank['voices']:continue
            if result is None:
                if client is None:
                    from mflix_client import Mflix
                    client=Mflix(args.mcp_config)
                if upload is None:
                    upload={'role':role,'source_binding':fingerprint(basis),'reference_sha256':basis['reference_sha256'],
                      'url':upload_url(client.upload(reference))}
                    save_json(folder/'upload.private.json',upload);bind(folder/'upload-fingerprint.private.json',upload)
                    request=request_for(role,upload['url'])
                verify_remote(client,upload['url'],reference)
                bind(folder/'request-fingerprint.private.json',request)
                result=safe_submit(client,'uploadVoice',request,receipt)
            voice=voice_id(result,role)
            if any(v['voice_id']==voice for v in bank['voices'].values()):raise ValueError('Voice ID duplicated across roles; reconcile')
            bank['voices'][role]={'role':role,'voice_id':voice,'source_binding':fingerprint(basis),
              'reference_sha256':basis['reference_sha256'],'receipt_sha256':digest(receipt),
              'upload_sha256':digest(folder/'upload.private.json'),'request_fingerprint':fingerprint(request),
              'source_speaker_audio_verified':False,'native_listening_passed':False}
            save_json(bank_path,bank)
            save_json(ROOT/'progress.private.json',{'stage':'creating_approved_role_voice_bank','ready_roles':len(bank['voices']),'max_new_clones':5,'tts_calls':0})
        save_json(ROOT/'progress.private.json',{'stage':'role_voice_bank_ready','ready_roles':5,'tts_calls':0})


if __name__=='__main__':
    try:main()
    except Exception as exc:
        ROOT.mkdir(parents=True,exist_ok=True)
        save_json(ROOT/'progress.private.json',{'stage':'voice_bank_needs_reconciliation','error_type':type(exc).__name__,'automatic_retry':False,'tts_calls':0})
        raise
