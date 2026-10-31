import unittest
from repair_cached_alignment import joint_groups


def group(key, start, words, role='actor', mode='dialogue', emotion='calm', voice='saved'):
    return dict(id=key, start=start, end=start+.5, text=words, role=role, delivery_mode=mode,
                cue_ids=[key+'-cue'], unit_ids=[key+'-unit'], cache_key=key,
                request=dict(speed=1., emotion=emotion, voiceId=voice))


class CachedThoughtTests(unittest.TestCase):
    def test_complete_thought_preserves_all_words_and_cues_without_tts_request(self):
        rows=[group('a',0,'My name'),group('b',1,'is Edmond.'),group('c',3,'Next role',role='other')]
        result=joint_groups(rows,[dict(id='joint-a-b',ids=['a','b'],source_context_evidence='One complete thought')])
        self.assertEqual(result[0]['text'],'My name is Edmond.')
        self.assertEqual(result[0]['cue_ids'],['a-cue','b-cue'])
        self.assertEqual(result[0]['source_group_ids'],['a','b'])
        self.assertNotIn('model',result[0]['request'])
        self.assertTrue(result[0]['request']['derived_cached_audio_only'])
        self.assertEqual(result[1],rows[2])
        self.assertEqual(rows[0]['text'],'My name')

    def test_different_role_mode_emotion_or_voice_cannot_be_joined(self):
        for changes in [dict(role='other'),dict(mode='narration'),dict(emotion='angry'),dict(voice='other')]:
            with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,'Never join'):
                joint_groups([group('a',0,'First'),group('b',1,'Second',**changes)],
                             [dict(id='joint',ids=['a','b'],source_context_evidence='Claim')])

    def test_omitted_neighbor_cannot_be_jumped(self):
        with self.assertRaisesRegex(ValueError,'adjacent'):
            joint_groups([group('a',0,'A'),group('b',1,'B'),group('c',2,'C')],
                         [dict(id='joint',ids=['a','c'],source_context_evidence='Claim')])


if __name__=='__main__':unittest.main()
