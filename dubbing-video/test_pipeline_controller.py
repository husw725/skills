import unittest
from pipeline_controller import choose_stage,occupied_slots


class EpisodeStageTests(unittest.TestCase):
    def test_independent_episode_advances_when_its_inputs_arrive(self):
        self.assertEqual(choose_stage({}),'prepare')
        self.assertEqual(choose_stage({'plan':True}),'speech_review')
        self.assertEqual(choose_stage({'plan':True,'approval':True}),'generate')
        self.assertEqual(choose_stage({'generation':True}),'fit')
        self.assertEqual(choose_stage({'render':True}),'publish')
        self.assertEqual(choose_stage({'delivered':True}),'delivered')

    def test_two_old_free_workers_occupy_both_recovery_slots(self):
        records={'old1':dict(paid_stage=False),'old2':dict(paid_stage=False)}
        paid,free=occupied_slots({},records,{'old1':True,'old2':True})
        self.assertFalse(paid);self.assertEqual(max(0,2-free),0)

    def test_one_old_free_worker_leaves_one_slot(self):
        records={'old':dict(paid_stage=False),'paid':dict(paid_stage=True)}
        paid,free=occupied_slots({},records,{'old':True,'paid':True})
        self.assertTrue(paid);self.assertEqual(max(0,2-free),1)

    def test_local_source_hold_keeps_paid_audio_without_render(self):
        self.assertEqual(choose_stage({'generation':True},holds=True),'source_holds')
        self.assertEqual(choose_stage({'generation':True},holds=False),'fit')


if __name__=='__main__':unittest.main()
