import tempfile,copy
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch,Mock
import requests
from publish_season_candidates import verify_remote_subtitle
from resume_season_publication import retained_delivery
from translate import save_json,fingerprint
from dub_episode import digest
from cartesia_pilot import bind


class PublicationRecoveryTests(TestCase):
    def test_ssl_retries_only_get_and_keeps_exact_bytes_requirement(self):
        response=Mock();response.content=b'final'
        with patch('requests.get',side_effect=[requests.exceptions.SSLError('read interrupted'),response]) as get,patch('time.sleep'):
            verify_remote_subtitle('https://example.test/final.srt',b'final')
            self.assertEqual(get.call_count,2);response.close.assert_called_once()
        with patch('requests.get',return_value=response) as get:
            with self.assertRaises(ValueError):verify_remote_subtitle('https://example.test/final.srt',b'different')
            self.assertEqual(get.call_count,1)

    def test_failed_reads_are_bounded_and_do_not_expose_url(self):
        with patch('requests.get',side_effect=requests.exceptions.SSLError('https://private.test/secret')) as get,patch('time.sleep'):
            with self.assertRaises(RuntimeError) as error:verify_remote_subtitle('https://private.test/secret',b'x')
            self.assertEqual(get.call_count,3);self.assertNotIn('private.test',str(error.exception))

    def test_merge_requires_the_same_latest_candidate_receipt_and_subtitle(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);sub=folder/'Carmilla_EP03_pt-BR_revised.srt';sub.write_text('Texto.',encoding='utf-8')
            save_json(folder/'reviewed.json',{'text':'reviewed'});save_json(folder/'screenplay-context.json',{'source':'bound'})
            plan={'reviewed_response_sha256':digest(folder/'reviewed.json'),'reviewed_context_sha256':digest(folder/'screenplay-context.json'),'episode':3,'project_id':59,'blocking_issues':[],'translation_srt_sha256':digest(sub)}
            save_json(folder/'plan.json',plan);bind(folder/'reviewed-plan-fingerprint.json',plan)
            save_json(folder/'render-report.json',{'episode':3,'status':'rendered_season_revision_candidate','video_payload_identical':True,'source_audio_in_output':False,'new_clone_count':0,'output_sha256':'video-sha'})
            r={'episode':3,'video_sha256':'video-sha','subtitle_sha256':digest(sub)}
            marker=folder/'candidate.json';bind(marker,{'folder':str(folder),'video_sha256':r['video_sha256'],'subtitle_sha256':r['subtitle_sha256'],'plan_sha256':digest(folder/'plan.json')})
            retained_delivery(3,folder,r,r,marker)
            for field,value in [('episode',5),('video_sha256','another'),('subtitle_sha256','another')]:
                changed={**r,field:value}
                with self.assertRaises(ValueError):retained_delivery(3,folder,changed,changed,marker)
            with self.assertRaises(ValueError):retained_delivery(3,folder,r,{**r,'verified_at':1},marker)

            changed_plan={**plan,'approved_new_revision':'changed'}
            save_json(folder/'plan.json',changed_plan);save_json(folder/'reviewed-plan-fingerprint.json',{'fingerprint':fingerprint(changed_plan)})
            with self.assertRaises(ValueError):retained_delivery(3,folder,r,r,marker)
