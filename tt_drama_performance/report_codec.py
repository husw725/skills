"""Lossless compact JSON for the single-file report; no external data requests."""
from collections import Counter
import json


def pack_payload(payload):
    counts = Counter()

    def count(value):
        if isinstance(value, str):
            counts[value] += 1
        elif isinstance(value, dict):
            for child in value.values():
                count(child)
        elif isinstance(value, list):
            for child in value:
                count(child)

    count(payload)
    strings = sorted((s for s, n in counts.items() if n > 1 and len(s) >= 4),
                     key=lambda s: -counts[s] * (len(s) - 5))
    refs = {s: i for i, s in enumerate(strings)}
    shapes, shape_ids = [], {}

    def pack(value):
        if isinstance(value, str):
            return [-2, refs[value]] if value in refs else value
        if isinstance(value, list):
            return [-1, *map(pack, value)]
        if isinstance(value, dict):
            keys = tuple(value)
            if keys not in shape_ids:
                shape_ids[keys] = len(shapes)
                shapes.append(list(keys))
            return [shape_ids[keys], *(pack(v) for v in value.values())]
        return value

    root = pack(payload)
    return dict(_reportEncoding='compact-v1', shapes=shapes, strings=strings, root=root)


def unpack_payload(payload):
    if not isinstance(payload, dict) or payload.get('_reportEncoding') != 'compact-v1':
        return payload
    shapes, strings = payload['shapes'], payload['strings']

    def unpack(value):
        if not isinstance(value, list):
            return value
        if not value or type(value[0]) is not int:
            raise ValueError('Invalid compact report tag')
        tag = value[0]
        if tag == -1:
            return [unpack(child) for child in value[1:]]
        if tag == -2:
            if len(value) != 2 or type(value[1]) is not int or not 0 <= value[1] < len(strings):
                raise ValueError('Invalid compact string reference')
            return strings[value[1]]
        if not 0 <= tag < len(shapes):
            raise ValueError('Invalid compact shape reference')
        keys = shapes[tag]
        if len(value) != len(keys) + 1:
            raise ValueError('Compact report object length mismatch')
        return {key: unpack(child) for key, child in zip(keys, value[1:])}

    return unpack(payload['root'])


def encode_payload(payload):
    return json.dumps(pack_payload(payload), ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).replace('</', '<\\/')


def read_report_payload(html):
    """Read both previously published plain JSON and compact reports."""
    value = html.split('const DATA = ', 1)[1].lstrip()
    if value.startswith('decodeReportData('):
        value = value[len('decodeReportData('):]
    encoded, _ = json.JSONDecoder().raw_decode(value)
    return unpack_payload(encoded)
