"""Versioned, same-origin report sections; retain the standalone business report."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from report_codec import encode_payload, pack_payload, read_report_payload


SECTION_KEYS = {
    'details': ('seriesDetails', 'episodeDetails'),
    'archive': ('seriesHistory',),
    'legacy': ('legacyDaily',),
    'history': ('dayDetails',),
}


def verify_asset(relative, path):
    expected = Path(relative).stem.rsplit('-', 1)[-1]
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
        raise ValueError(f'Report section checksum mismatch: {relative}')


def write_asset(path, body):
    if path.exists() and path.read_bytes() == body:
        return
    # Never leave a half-written immutable file after an interrupted generation.
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build_web_report(base, payload=None):
    base = Path(base)
    if payload is None:
        payload = read_report_payload((base / 'report.html').read_text(encoding='utf-8'))
    core = dict(payload)
    manifest, assets = {}, []
    directory = base / 'output' / 'report-web'
    (directory / 'data').mkdir(parents=True, exist_ok=True)
    for name, keys in SECTION_KEYS.items():
        values = {key: core.pop(key) for key in keys if key in core}
        if not values:
            continue
        body = json.dumps(pack_payload(dict(section=name, data=values)), ensure_ascii=False,
                          allow_nan=False, separators=(',', ':')).encode('utf-8')
        digest = hashlib.sha256(body).hexdigest()
        relative = f'data/{name}-{digest}.json'
        path = directory / relative
        write_asset(path, body)
        manifest[name] = dict(path=relative, sha256=digest, keys=list(values))
        assets.append((relative, path))
    core['_sections'] = manifest
    template = (base / 'template.html').read_text(encoding='utf-8')
    web = directory / 'index.html'
    tmp = directory / 'index.html.tmp'
    tmp.write_text(template.replace('/*__DATA__*/null', encode_payload(core)), encoding='utf-8')
    tmp.replace(web)
    return web, assets
