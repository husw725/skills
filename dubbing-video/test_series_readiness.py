import unittest
from audit_series_readiness import contains, screen_unit, source_binding_matches, split_provenance_issues


class SeriesReadinessTests(unittest.TestCase):
    def unit(self, **kw):
        return {'id':'a','text':'Never.','translation':'Jamais.','start':0,'end':1,
                'speaker':'Laura','production_voice':'Laura',**kw}

    def test_names_use_boundaries_and_negative_alternatives(self):
        self.assertFalse(contains('banana', 'Ana'))
        self.assertTrue(contains('Ana!', 'Ana'))
        flags=screen_unit(self.unit(),None,None,{})
        self.assertFalse(any(f['category']=='negation_candidate' for f in flags))
        flags=screen_unit(self.unit(translation='Sempre.'),None,None,{})
        self.assertTrue(any(f['category']=='negation_candidate' and f['status']=='candidate_requires_review' for f in flags))

    def test_grouping_never_suggested_for_unknown_or_different_voice(self):
        following=self.unit(start=1.1,end=2,translation='amanhã.')
        for u in (self.unit(speaker='unknown'),self.unit(production_voice='Carmilla')):
            flags=screen_unit(u,None,following,{})
            self.assertFalse(any(f['category']=='connected_phrase_candidate' for f in flags))

    def test_stale_audio_is_distinct_from_lexical_candidate(self):
        u=self.unit();rendered={'start':0,'end':1,'translation':'Sempre.','atempo_factor':1.3,'fitted_duration_seconds':.8}
        flags=screen_unit(u,rendered,None,{})
        self.assertTrue(any(f['category']=='render_plan_translation_mismatch' and f['priority']=='P1' for f in flags))
        self.assertTrue(any(f['category']=='post_speedup_above_1_25' for f in flags))

    def test_legitimate_multi_cue_group_is_not_stale(self):
        rows={'a':{'id':'a','start':0,'end':1,'text':'Each time'},'b':{'id':'b','start':1.1,'end':2,'text':'she returns'}}
        annotations={'a':{'source_text':'Each time'},'b':{'source_text':'she returns'}}
        u=self.unit(text='Each time she returns',cue_ids=['a','b'],end=2,
                    source_cue_windows=[{k:r[k] for k in ('id','start','end')} for r in rows.values()],
                    screenplay_annotations=list(annotations.values()))
        self.assertTrue(source_binding_matches(u,rows,annotations))
        self.assertFalse(source_binding_matches({**u,'text':'Each time she leaves'},rows,annotations))

    def test_two_readers_split_preserves_original_subtitle(self):
        original={'id':'x','start':0,'end':2,'text':'You will regret this never.'}
        rows=[{'id':'xa','start':0,'end':1.3,'text':'You will regret this.','original_subtitle_cue':original},
              {'id':'xb','start':1.3,'end':2,'text':'Never.','original_subtitle_cue':original}]
        self.assertEqual(split_provenance_issues(rows),set())
        rows[1]['text']='Always.'
        self.assertEqual(split_provenance_issues(rows),{'xa','xb'})


if __name__=='__main__':unittest.main()
