from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch

import rerun_carmilla_season as season
from repair_carmilla_measured import selected_pending
from cartesia_pilot import bind


class MeasuredRepairTests(TestCase):
    def test_only_measured_failures_and_never_completed_or_source_errors(self):
        error='Measured speech too long: revise faithfully; no automatic paid speed retries'
        baseline={'episodes':{
            '9':{'stage':'requires_review','detail':error},
            '10':{'stage':'requires_review','detail':'Unresolved textual/source error; no synthesis permitted'},
            '11':{'stage':'requires_review','detail':error},
            '12':{'stage':'requires_review','detail':error},
            '15':{'stage':'rendered_candidate','detail':error}}}
        state={'episodes':{'11':{'stage':'rendered_candidate'}}}
        self.assertEqual(selected_pending(baseline,state),[9])

    def test_final_cache_reuses_same_request_and_blocks_ambiguous_prior(self):
        with TemporaryDirectory() as temp:
            final=Path(temp);folder=final/'episode-09/utterances/a';folder.mkdir(parents=True)
            req={'text':'Saved utterance','speed':1,'voiceId':'existing'};bind(folder/'request-fingerprint.json',req)
            with patch.object(season,'FINAL_ROOT',final):
                self.assertEqual(season.paid_audio_folder(9,req,final/'target',final),folder)
                pending=folder/'submission.private.submission-pending.json';pending.write_text('{}')
                with self.assertRaises(ValueError):season.paid_audio_folder(9,{'text':'Different text'},final/'target',final)


if __name__=='__main__':main()
