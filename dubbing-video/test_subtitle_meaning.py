import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main

from dub_episode import digest
from resume_carmilla_subtitle_meaning import validate_basis


class SubtitleMeaningTests(TestCase):
    def test_only_reviewed_original_meaning_not_acoustic_confirmation(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp);audit=p/'audit';audit.write_text('independent report')
            srt=p/'original';srt.write_text('unchanged original')
            cue={'id':'e04-16','text':"i'll see you for tonight.",'start':101.233,'end':102.766}
            basis={'kind':'subtitle_semantic_normalization','audio_listened':False,'speaker_verified':False,
                'original_cue':cue,'translation':'Te vejo esta noite.',
                'audit_report':{'path':str(audit),'sha256':digest(audit)},
                'original_subtitle':{'path':str(srt),'sha256':digest(srt)}}
            hints={'4':{'source_basis':basis}}
            self.assertEqual(validate_basis(hints,[cue]),basis)
            for key,value in [('audio_listened',True),('speaker_verified',True),('translation','Vou vê-la esta noite.')]:
                bad=copy.deepcopy(hints);bad['4']['source_basis'][key]=value
                with self.assertRaises(ValueError):validate_basis(bad,[cue])
            with self.assertRaises(ValueError):validate_basis({'5':hints['4']},[cue])
            with self.assertRaises(ValueError):validate_basis(hints,[{**cue,'text':'different source'}])
            srt.write_text('changed original')
            with self.assertRaises(ValueError):validate_basis(hints,[cue])


if __name__=='__main__':main()
