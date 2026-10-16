"""Read-only Carmilla screening before any decision to regenerate the season."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
import sys
from dub_episode import digest
from screenplay_context import load_screenplay_context
from translate import read_json, save_json, validate_bible


def contains(text, term):
    return bool(re.search(r'(?<!\w)'+re.escape(term)+r'(?!\w)', text, re.I))


def source_binding_matches(unit, by_id, annotations):
    rows = [by_id[c] for c in unit['cue_ids']]
    normalize = lambda text: ' '.join(text.split())
    return (normalize(unit['text']) == normalize(' '.join(r['text'] for r in rows))
            and (unit['start'], unit['end']) == (rows[0]['start'], rows[-1]['end'])
            and unit.get('source_cue_windows') == [{k:r[k] for k in ('id','start','end')} for r in rows]
            and unit.get('screenplay_annotations') == [annotations[c] for c in unit['cue_ids']])


def split_provenance_issues(rows):
    """Editorial rows may split a subtitle containing multiple characters."""
    groups = {}
    for row in rows:
        if row.get('original_subtitle_cue'):
            groups.setdefault(row['original_subtitle_cue']['id'], []).append(row)
    issues = set()
    tokens = lambda text: re.findall(r'\w+', text.casefold())
    for group in groups.values():
        group.sort(key=lambda r:r['start']); original = group[0]['original_subtitle_cue']
        if (any(r['original_subtitle_cue'] != original for r in group)
                or tokens(' '.join(r['text'] for r in group)) != tokens(original['text'])
                or group[0]['start'] != original['start'] or group[-1]['end'] != original['end']
                or any(a['end'] != b['start'] for a,b in zip(group,group[1:]))):
            issues.update(r['id'] for r in group)
    return issues


def screen_unit(unit, rendered, following, glossary):
    """Candidates require editorial/listening review; these rules do not prove mistranslation."""
    flags = []
    def flag(category, evidence, priority='P2'):
        flags.append({'category': category, 'evidence': evidence, 'priority': priority,
                      'status': 'candidate_requires_review'})
    src, pt = unit['text'], unit['translation']
    for source, target in glossary.items():
        if contains(src, source) and not contains(pt, target):
            flag('glossary_candidate', f'Explicit source term {source!r}; expected localized form {target!r} absent', 'P3')
    if re.search(r"\b(?:not|never|nothing|nobody|cannot|no one)\b|n['’]t\b", src, re.I):
        if not re.search(r'\b(?:não|nunca|jamais|nada|ninguém|nenhum|nenhuma|sem|nem|impossível)\b', pt, re.I):
            flag('negation_candidate', 'Source has a negative expression; no common Portuguese negative marker. Check full thought, including neighbor cues.', 'P3')
    for source, targets in [('tomorrow', ('amanhã',)), ('tonight', ('noite', 'hoje')),
                            ('fifteen', ('quinze', '15')), ('seven', ('sete', '7'))]:
        if contains(src, source) and not any(contains(pt, word) for word in targets):
            flag('deadline_number_candidate', f'{source!r} has no common local equivalent in this cue; inspect connected phrase.', 'P3')
    if unit.get('speaker') == 'unknown':
        flag('source_speaker_unknown', 'Evidence speaker is unknown. Production voice is a separate provisional decision.')
    if any(re.search(r'ASR|ambigu|uncertain|mismatch|不一致|存疑|误识别', str(a), re.I)
           for a in unit.get('screenplay_annotations', [])):
        flag('source_context_uncertainty', 'Screenplay annotation records uncertainty; verify original timed dialogue before editing.')
    if rendered:
        atempo = rendered.get('atempo_factor', 1)
        speeds = [a.get('speed', 1) for a in rendered.get('attempts', [])]
        if atempo > 1.25:
            flag('post_speedup_above_1_25', f'Measured render setting atempo={atempo:.4f}; listening required')
        if speeds and speeds[-1] > 1.25:
            flag('requested_speed_above_1_25', f'Last generation request speed={speeds[-1]}; not a measurement of natural speaking rate')
        if rendered.get('translation') != pt:
            flag('render_plan_translation_mismatch', 'Saved audio report translation differs from current production plan', 'P1')
        if (rendered.get('start'), rendered.get('end')) != (unit['start'], unit['end']):
            flag('render_plan_window_mismatch', 'Saved render window differs from plan', 'P1')
        end = unit['start']+rendered.get('fitted_duration_seconds', 0)
        if following and end > following['start']+.025:
            flag('audio_crosses_next_start', f'Reported fitted end={end:.3f} > next start={following["start"]:.3f}')
    if following and unit.get('speaker') not in (None, 'unknown'):
        gap = following['start']-unit['end']
        unfinished = not re.search(r'[!?。！？”"]\s*$', pt) and (not pt.endswith('.') or pt.endswith('...'))
        if (unit['speaker'] == following.get('speaker') and unit.get('production_voice') == following.get('production_voice')
                and 0 <= gap <= .6 and unfinished):
            flag('connected_phrase_candidate', f'Same evidence speaker/production voice continues after {gap:.3f}s; grouping requires editorial review', 'P3')
    return flags


def audit(output, feedback):
    root = Path('output/drama-01')
    if not output.resolve().is_relative_to(Path('output').resolve()): raise ValueError('Output must remain under ignored output/')
    if output.exists(): raise ValueError('Use a new output directory; preserve prior screening')
    bible_path = root/'episode-01/translation-v2/series-bible.json'
    manifest = {str(bible_path): digest(bible_path)}
    glossary = validate_bible(read_json(bible_path))
    episodes, findings, corpus = [], [], []
    for n in range(1, 33):
        ep = root/f'episode-{n:02}'
        plan_path, report_path = ep/'dub-plan-v1.json', ep/'dub-v1/render-report.json'
        for p in (plan_path, report_path): manifest[str(p)] = digest(p)
        plan, report = read_json(plan_path), read_json(report_path)
        if plan['episode'] != n or plan['project_id'] != 59 or report['episode'] != n:
            raise ValueError('Episode/project scope differs')
        context_path = ep/('translation-v2/screenplay-context.json' if n == 1 else 'editorial/screenplay-context.json')
        source_path = ep/('script-revision-input/episode-01.source.json' if n == 1 else 'editorial/source.json')
        for p in (context_path, source_path): manifest[str(p)] = digest(p)
        source = read_json(source_path)['segments']; context = load_screenplay_context(context_path, source)
        by_id = {r['id']: r for r in source}; annotations = context['episodes'][str(n)]['cue_annotations']
        split_issues = split_provenance_issues(source)
        covered = [c for u in plan['units'] for c in u['cue_ids']]
        if len(covered) != len(source) or len(set(covered)) != len(covered) or set(covered) != set(by_id):
            raise ValueError(f'EP{n:02} source coverage differs')
        rendered = {u['id']: u for u in report['utterances']}
        if len(rendered) != len(report['utterances']) or set(rendered) != {u['id'] for u in plan['units']}:
            raise ValueError('Saved render unit coverage differs')
        units = plan['units']
        for index, u in enumerate(units):
            entry = {'episode': n, 'unit_id': u['id'], 'cue_ids': u['cue_ids'], 'start': u['start'], 'end': u['end'],
                     'english': u['text'], 'portuguese': u['translation'], 'speaker': u.get('speaker'),
                     'production_voice': u.get('production_voice')}
            corpus.append({**entry, 'screenplay_annotations': u.get('screenplay_annotations', [])})
            fs = screen_unit(u, rendered[u['id']], units[index+1] if index+1 < len(units) else None, glossary)
            if not source_binding_matches(u, by_id, annotations):
                fs.append({'category': 'source_or_context_binding_mismatch', 'evidence': 'Plan no longer matches source text/time or reviewed annotations',
                           'priority': 'P1', 'status': 'requires_provenance_review'})
            if set(u['cue_ids']) & split_issues:
                fs.append({'category':'split_provenance_requires_review','evidence':'Derived source dialogue/window cannot be reconstructed against saved original subtitle',
                           'priority':'P1','status':'requires_provenance_review'})
            findings.extend({**entry, **f} for f in fs)
        original_count = len({r.get('original_subtitle_cue', r)['id'] for r in source})
        episodes.append({'episode': n, 'cue_count': original_count, 'source_rows':len(source), 'unit_count': len(units),
                         'screenplay_context': str(context_path), 'screenplay_sources': context['sources'],
                         'render_report_sha256': digest(report_path), 'video_hash_rechecked': False,
                         'saved_video_payload_identical': report.get('video_payload_identical'),
                         'native_listening_passed': False})
    historical_count = 0
    if feedback:
        manifest[str(feedback)] = digest(feedback)
        for item in read_json(feedback)['items']:
            n = item['episode']; historical_count += 1
            findings.append({'episode': n, 'unit_id': '', 'cue_ids': [], 'start': '', 'end': '',
                'english': '', 'portuguese': '', 'speaker': '', 'production_voice': '', 'priority': 'P2',
                'category': 'historical_professional_comment', 'status': 'historical_not_new_version_acceptance',
                'evidence': item['comment'], 'comment_id': item['comment_id'], 'asset_id': item['asset_id'],
                'quoted_anchor': item.get('quoted_anchor'), 'location_status': item.get('location_status'),
                'candidate_subtitle_units': item.get('candidate_subtitle_units', [])})
    findings.sort(key=lambda f: (f['priority'], f['episode'], str(f['unit_id']), f['category']))
    # Confirm all production input/report files remained unchanged while reading.
    if any(digest(Path(p)) != sha for p, sha in manifest.items()): raise ValueError('Inputs changed during screening')
    output.mkdir(parents=True)
    summary = {'episodes': len(episodes), 'source_cues': sum(e['cue_count'] for e in episodes),
               'editorial_source_rows':sum(e['source_rows'] for e in episodes),
               'units': len(corpus), 'finding_rows': len(findings), 'historical_comments': historical_count,
               'unique_units_with_automated_candidates': len({(f['episode'], f['unit_id']) for f in findings if f['unit_id']}),
               'by_category': dict(Counter(f['category'] for f in findings)), 'new_paid_calls': 0,
               'production_files_modified': False, 'native_listening_performed': False,
               'scope': 'All 32 original v1 production plans/reports; diagnostic EP02 v3 / EP07 v2 / EP29 v2 await feedback separately.'}
    save_json(output/'audit.json', {'summary': summary, 'episodes': episodes, 'findings': findings, 'input_sha256': manifest,
                                    'glossary': glossary, 'limitations': ['Heuristic candidates are not confirmed translation defects.',
                                     'No new listening or video decoding. No claim of Brazilian accent approval.',
                                     'Historical comments retain commentId/assetId; no timestamp inferred from subtitle ordinal.',
                                     'Full semantic/native review remains required; no production text/audio is edited.']})
    save_json(output/'bilingual-corpus.private.json', corpus)
    keys = ['episode','priority','category','status','unit_id','start','end','english','portuguese','speaker','production_voice','evidence','comment_id','asset_id']
    with (output/'repair-candidates.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore'); writer.writeheader(); writer.writerows(findings)
    lines = ['# Carmilla 全剧返修前排查', '', '范围：32集原v1生产数据。三集新候选另等专业反馈。',
             '仅生成待核清单，未改译稿/音频/视频、未调用付费服务。候选条数不是已确认错误数。', '',
             f'覆盖{summary["source_cues"]}条源字幕；自动候选涉及{summary["unique_units_with_automated_candidates"]}个意群；保留{historical_count}条历史评审意见。', '',
             '| 集数 | 字幕数 | P1来源/版本待核 | 时长规则记录（可重叠） | 文字/分组/身份候选 | 历史评论 |', '|---|---:|---:|---:|---:|---:|']
    for e in episodes:
        fs=[f for f in findings if f['episode']==e['episode']]
        counts=Counter(f['category'] for f in fs)
        timing=sum(counts[c] for c in ('post_speedup_above_1_25','requested_speed_above_1_25','audio_crosses_next_start'))
        hist=counts['historical_professional_comment']; p1=sum(f['priority']=='P1' for f in fs)
        lines.append(f'| {e["episode"]:02} | {e["cue_count"]} | {p1} | {timing} | {len(fs)-timing-hist-p1} | {hist} |')
    lines += ['', '优先顺序：先确认来源/版本与未知说话人；再结合历史评论审核时长、连续意群；等三集听审确认有效改法后，定点试制。',
              '时长列为规则命中记录数，同一意群可能命中两条规则；不能直接相加认定错误句数。',
              '详细证据见repair-candidates.csv和audit.json。无评论不等于验收；巴葡口音、尖叫/情绪、音色和混音需听审。']
    (output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True),flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--feedback',type=Path);a=p.parse_args()
    if sys.platform!='win32':p.error('Business execution is Windows-only')
    audit(a.output,a.feedback)
