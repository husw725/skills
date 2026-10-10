import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import export_translation
import translate as tr
from screenplay_context import load_screenplay_context
from test_translation import FakeClient


class ScreenplayContextTests(unittest.TestCase):
    def test_locked_terms_match_whole_source_forms(self):
        glossary={'curse':'maldição','Ana':'Ana'}
        export_translation.validate_locked_terms('I am cursed.','Sou amaldiçoada.',glossary,'a')
        export_translation.validate_locked_terms('banana','banana',glossary,'a')
        with self.assertRaisesRegex(ValueError,'Locked name/term'):
            export_translation.validate_locked_terms('The curse.','O destino.',glossary,'a')
        with self.assertRaisesRegex(ValueError,'Locked name/term'):
            export_translation.validate_locked_terms('Ana, come.','Venha.',glossary,'a')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rows = [{"id":"a", "episode":"1", "text":"Stay.", "start":1., "end":2., "speaker":"unknown"}]
        self.context = {"schema_version":1,"sources":[{"filename":"fictional.docx","sha256":"a"*64,"version":1}],
            "episodes":{"1":{"match_status":"matched_main_dialogue","script_excerpt":"MOTHER (weak): Stay.",
                "cue_annotations":{"a":{"source_text":"Stay.","speaker":"Mother","script_evidence":"MOTHER (weak)"}}}}}

    def write_context(self):
        p=self.root/'context.json';tr.save_json(p,self.context);return p

    def test_rejects_other_cut_and_stale_annotations(self):
        self.context['episodes']['1']['match_status']='different_cut'
        with self.assertRaisesRegex(ValueError,'version match'):
            load_screenplay_context(self.write_context(),self.rows)
        self.context['episodes']['1']['match_status']='matched_main_dialogue'
        self.context['episodes']['1']['cue_annotations']['a']['source_text']='Leave.'
        with self.assertRaisesRegex(ValueError,'stale'):
            load_screenplay_context(self.write_context(),self.rows)

    def test_rejects_unreviewed_episode_or_missing_cue(self):
        with self.assertRaisesRegex(ValueError,'episode 2'):
            load_screenplay_context(self.write_context(),[{**self.rows[0],'episode':'2'}])
        self.context['episodes']['1']['cue_annotations']={}
        with self.assertRaisesRegex(ValueError,'every requested cue'):
            load_screenplay_context(self.write_context(),self.rows)

    def test_script_reaches_translation_and_review_without_new_dialogue(self):
        client=FakeClient([{'segments':[{'id':'a','candidates':['Fique.']}]},{'issues':[]}])
        with contextlib.redirect_stdout(io.StringIO()):
            result=tr.translate_rows(self.rows,{'glossary':[]},client,self.root/'out.json',
                                     tolerance=1,revisions=0,screenplay=self.context)
        self.assertEqual(len(result['segments']),1)
        row=result['segments'][0]
        self.assertEqual((row['start'],row['end'],row['text']),(1.,2.,'Stay.'))
        self.assertEqual(row['speaker'],'Mother')
        self.assertFalse(row['speaker_audio_verified'])
        for _,payload in client.calls:self.assertIn('screenplay_context',payload)
        changed=copy.deepcopy(self.context);changed['episodes']['1']['script_excerpt']+=' Revised performance.'
        with self.assertRaisesRegex(ValueError,'Checkpoint differs'):
            tr.translate_rows(self.rows,{'glossary':[]},FakeClient([]),self.root/'out.json',screenplay=changed,tolerance=1,revisions=0)

    def export_args(self, wrong_fingerprint=False):
        tr.save_json(self.root/'source.json',{'segments':self.rows})
        tr.save_json(self.root/'bible.json',{'glossary':[]})
        canonical=[{k:r[k] for k in ('id','text','start','end')} for r in self.rows]
        tr.save_json(self.root/'draft.json',{'episode':'1','source_fingerprint':tr.fingerprint(canonical),
            'screenplay_context_fingerprint':'wrong' if wrong_fingerprint else tr.fingerprint(self.context),
            'translation_backend':'fixture','segments':[{'id':r['id'],'translation':'Fique.'} for r in self.rows],
            'proposed_speech_groups':[['a','b']] if len(self.rows)>1 else []})
        return ['export_translation.py',str(self.root/'source.json'),str(self.root/'draft.json'),
            '--bible',str(self.root/'bible.json'),'--screenplay-context',str(self.write_context()),
            '--output-dir',str(self.root/'out')]

    def test_export_rejects_unreviewed_context_change(self):
        with patch.object(sys,'argv',self.export_args(True)), self.assertRaisesRegex(ValueError,'not reviewed'):
            export_translation.main()

    def test_export_preserves_script_metadata_and_original_timing(self):
        with patch.object(sys,'argv',self.export_args()),contextlib.redirect_stdout(io.StringIO()):
            export_translation.main()
        saved=tr.read_json(self.root/'out/translated.json')
        self.assertEqual(saved['screenplay_context_fingerprint'],tr.fingerprint(self.context))
        unit=tr.read_json(self.root/'out/speech-units.draft.json')['units'][0]
        self.assertEqual(unit['speaker'],'Mother')
        self.assertFalse(unit['speaker_audio_verified'])
        self.assertEqual(unit['source_cue_windows'],[{'id':'a','start':1.,'end':2.}])

    def test_export_rejects_grouping_different_characters(self):
        self.rows.append({**self.rows[0],'id':'b','text':'Please.','start':2.1,'end':3.})
        self.context['episodes']['1']['cue_annotations']['b']={'source_text':'Please.','speaker':'Father','script_evidence':'FATHER'}
        with patch.object(sys,'argv',self.export_args()),self.assertRaisesRegex(ValueError,'different screenplay speakers'):
            export_translation.main()


if __name__=='__main__':unittest.main()
