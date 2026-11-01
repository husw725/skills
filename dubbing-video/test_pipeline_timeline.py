import copy
import os
from pathlib import Path
import tempfile
import unittest
from pipeline_timeline import apply_mapping, apply, subtitle
from translate import save_json, fingerprint
from dub_episode import digest


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.rows=[dict(id='e06-1',episode='6',start=1.,end=2.,text='Original sentence.')]
        self.mapping=[dict(id='e06-1',source_start=1.,source_end=2.,source_text='Original sentence.',
                           start=1.1,end=2.1,evidence='Unique source waveform alignment')]

    def test_mapping_is_derived_and_preserves_original_words_and_window_width(self):
        original=copy.deepcopy(self.rows)
        mapped=apply_mapping(self.rows,self.mapping,5)
        self.assertEqual(self.rows,original)
        self.assertEqual(mapped[0]['text'],original[0]['text'])
        self.assertEqual(mapped[0]['end']-mapped[0]['start'],1.)
        self.assertEqual(mapped[0]['start'],1.1)
        s=subtitle(mapped,{'cues':[dict(id='e06-1',translation='Frase original.')]})
        self.assertIn('00:00:01,100 --> 00:00:02,100',s)

    def test_source_tamper_duplicate_bool_and_overlap_are_rejected(self):
        for update in [dict(source_text='Different sentence.'),dict(start=True),dict(end=6.),dict(start=1.1001)]:
            with self.subTest(update=update),self.assertRaises(ValueError):
                apply_mapping(self.rows,[{**self.mapping[0],**update}],5)
        with self.assertRaises(ValueError):apply_mapping(self.rows,self.mapping*2,5)
        with self.assertRaises(ValueError):
            apply_mapping(self.rows+[dict(self.rows[0],id='e06-2')],
                          self.mapping+[dict(self.mapping[0],id='e06-2',start=2.,end=3.)],5)

    def test_existing_episode_without_mapping_keeps_same_objects(self):
        candidate={'cues':[]}
        rows,out=apply(self.rows,candidate,{}, {}, {}, {})
        self.assertIs(rows,self.rows);self.assertIs(out,candidate)

    def test_incomplete_physical_proof_is_rejected_even_if_approved_bool_is_true(self):
        with tempfile.TemporaryDirectory() as directory:
            previous=os.getcwd()
            try:
                os.chdir(directory)
                save_json('media.json',{})
                context={'scripts':[{'asset_id':1,'text':'Original source screenplay.'}]}
                media={'source':{'video_sha256':'cut'},'output_sha256':{'audio':'dialog'},'video_seconds':5}
                decision=dict(project_id=100,episode=6,source_input_sha256='source',baseline_result_sha256='result',
                              media_receipt_path='media.json',production_time_map_path='map.json')
                proof=dict(approved=True,project_id=100,episode=6,cues=[],source_bindings=dict(
                    selected_picture={'video':'video','video_sha256':'cut'},
                    source_input={'path':'source','sha256':'source'},editorial_result={'path':'result','sha256':'result'},
                    media_manifest={'path':'media.json','sha256':digest('media.json')},
                    selected_dialogue={'path':'audio','sha256':'dialog'},declared_physical_inputs_sha256={}))
                # Missing actual waveform/background/script sources must fail before any production use.
                save_json('acoustic.json',proof)
                reviewed=dict(production_timeline_candidate_approved=True,original_actor_identity_verified=False,
                    native_listening_passed=False,source_input_sha256='source',baseline_result_sha256='result',
                    video_sha256='cut',mapping_fingerprint=fingerprint(self.mapping),
                    screenplay_context_fingerprint=fingerprint(context['scripts']),
                    inputs_sha256={'acoustic.json':digest('acoustic.json')},
                    acoustic_evidence_path='acoustic.json',acoustic_evidence_sha256=digest('acoustic.json'))
                save_json('review.json',reviewed)
                save_json('map.json',dict(project_id=100,episode=6,source_input_sha256='source',baseline_result_sha256='result',
                    video_sha256='cut',media_receipt_sha256=digest('media.json'),reviewed_context_path='review.json',
                    reviewed_context_sha256=digest('review.json'),cues=self.mapping))
                with self.assertRaises((ValueError,KeyError)):
                    apply(self.rows,{'cues':[]},context,decision,media,{})
            finally:os.chdir(previous)


if __name__=='__main__':unittest.main()
