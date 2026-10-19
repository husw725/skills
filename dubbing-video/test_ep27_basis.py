import copy
from unittest import TestCase,main
from carmilla_ep27_basis import SPECS,reconstruct

REVIEW_SHA="0"*64


def words(text,start,step=.1):
    return [{'word':t,'start':start+i*step,'end':start+(i+1)*step,'probability':.95} for i,t in enumerate(text.split())]


class ReconstructionTests(TestCase):
    def fixture(self):
        rows=[{'id':c,'text':s[0],'start':s[1],'end':s[2]} for c,s in SPECS.items()]
        rows.extend([{'id':'e27-20','text':'response','start':34.533,'end':35.833},
                     {'id':'e27-3','text':'response','start':76.366,'end':77.1}]);rows.sort(key=lambda r:r['start'])
        a=[{'words':words('cursed power '+SPECS['e27-12'][4],31)}]
        b=[{'words':words('You must be ready',71.73)},{'words':words(SPECS['e27-2'][4],72.7)}]
        evidence={c:{'models':{m:{'segments':copy.deepcopy(s),'evidence_sha256':m,'source_review_sha256':REVIEW_SHA}
                    for m in ['small.en','medium.en']}} for c,s in [('e27-12',a),('e27-2',b)]}
        board={'entries':[{'storyboard':' '.join(s[3] for s in SPECS.values())}]}
        return rows,evidence,board

    def test_original_caption_and_two_complete_tails_stay_editorial(self):
        rows,evidence,board=self.fixture();r=reconstruct(rows,evidence,board,REVIEW_SHA)
        self.assertEqual(set(r),set(SPECS));self.assertFalse(r['e27-12']['human_listened'])
        self.assertFalse(r['e27-12']['source_speaker_verified'])
        self.assertEqual(r['e27-12']['original_subtitle_text'],SPECS['e27-12'][0])

    def test_no_one_model_low_confidence_or_changed_condition(self):
        for mode in ['missing_model','low_confidence','changed_condition','wrong_review']:
            rows,evidence,board=self.fixture();r=evidence['e27-12']['models']
            if mode=='missing_model':r.pop('small.en')
            elif mode=='low_confidence':r['medium.en']['segments'][0]['words'][-1]['probability']=.1
            elif mode=='changed_condition':r['medium.en']['segments'][0]['words'][-1]['word']='strongest'
            else:r['medium.en']['source_review_sha256']='1'*64
            with self.assertRaises(ValueError):reconstruct(rows,evidence,board,REVIEW_SHA)

    def test_original_scope_next_boundary_and_current_storyboard_required(self):
        rows,evidence,board=self.fixture();rows[0]['text']='changed source'
        with self.assertRaises(ValueError):reconstruct(rows,evidence,board,REVIEW_SHA)
        rows,evidence,board=self.fixture();next(r for r in rows if r['id']=='e27-20')['start']=31.8
        with self.assertRaises(ValueError):reconstruct(rows,evidence,board,REVIEW_SHA)
        rows,evidence,board=self.fixture();board['entries'][0]['storyboard']='unrelated version'
        with self.assertRaises(ValueError):reconstruct(rows,evidence,board,REVIEW_SHA)

    def test_prefix_negation_cannot_be_discarded_as_a_disfluency(self):
        for protected in ['not','thirteen']:
            rows,evidence,board=self.fixture()
            evidence['e27-12']['models']['medium.en']['segments'][0]['words'].insert(0,
                {'word':protected,'start':30.8,'end':30.9,'probability':.99})
            with self.assertRaises(ValueError):reconstruct(rows,evidence,board,REVIEW_SHA)

class BoundaryTests(TestCase):
    def unit(self):
        from rerun_carmilla_season import post_gap_seconds
        phrase=SPECS['e27-2'][4]
        variants={}
        for model,end in [('small.en',75.76),('medium.en',75.84)]:
            ws=words(phrase,72.7,step=(end-72.7)/len(phrase.split()))
            variants[model]={'segments':[{'words':ws}]}
        return {'cue_ids':['e27-1','e27-2'],'source_text':'Irina will return. The seven-day sealing ritual is',
                'start':70.133,'end':74.266,'editorial_source_reconstructions':{'e27-2':{
                'original_subtitle_text':SPECS['e27-2'][0],'editorial_reading':SPECS['e27-2'][3],
                'human_listened':False,'source_speaker_verified':False,'complete_asr_records':variants}}}

    def test_exact_tail_allows_paid_audio_below_speed_ceiling(self):
        from rerun_carmilla_season import post_gap_seconds
        u=self.unit();self.assertEqual(post_gap_seconds(27,u),.8)
        end=u['end']+post_gap_seconds(27,u,ep27_boundary=True)
        self.assertAlmostEqual(end,75.84);self.assertLess(6.77/(end-u['start']),1.2)
        self.assertGreater(76.366-end,.5)

    def test_other_group_or_episode_cannot_use_extended_tail(self):
        from rerun_carmilla_season import post_gap_seconds
        u=self.unit()
        with self.assertRaises(ValueError):post_gap_seconds(5,u,ep27_boundary=True)
        u['cue_ids']=['e27-5'];self.assertEqual(post_gap_seconds(27,u,ep27_boundary=True),.8)

    def test_changed_original_or_incomplete_tail_is_blocked(self):
        from rerun_carmilla_season import post_gap_seconds
        u=self.unit();u['end']+=.1
        with self.assertRaises(ValueError):post_gap_seconds(27,u,ep27_boundary=True)
        u=self.unit();u['editorial_source_reconstructions']['e27-2']['complete_asr_records']['medium.en']['segments'][0]['words'].pop()
        with self.assertRaises(ValueError):post_gap_seconds(27,u,ep27_boundary=True)


if __name__=='__main__':main()
