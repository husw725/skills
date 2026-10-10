import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from notification_watch import events,tick
from translate import read_json,save_json


class NotificationTests(unittest.TestCase):
    def test_stop_is_sent_once_across_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=root/'output/config.json'
            save_json(cfg,{'webhook_url':'fixture'})
            save_json(root/'output/drama-01/queue-progress.json',{'stage':'stopped','episode':20,'updated_at':1})
            with patch('notification_watch.send') as sender:
                tick(root,cfg);tick(root,cfg)
                save_json(root/'output/drama-01/queue-progress.json',{'stage':'stopped','episode':20,'updated_at':1,'public_detail':'More precise explanation'})
                tick(root,cfg)
                self.assertEqual(sender.call_count,1)
            self.assertEqual(read_json(root/'output/notifications/watch-status.json')['sent'],1)

    def test_uncertain_delivery_is_not_spammed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=root/'config.json';save_json(cfg,{'webhook_url':'fixture'})
            save_json(root/'output/drama-01/queue-progress.json',{'stage':'stopped','updated_at':1})
            with patch('notification_watch.send',side_effect=TimeoutError) as sender:
                tick(root,cfg);tick(root,cfg)
                self.assertEqual(sender.call_count,1)

    def test_running_queue_is_not_a_stop_but_dead_heartbeat_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);save_json(root/'output/drama-01/queue-progress.json',{'stage':'rendering','updated_at':100})
            self.assertEqual(events(root,150),[])
            self.assertEqual(events(root,221)[0]['kind'],'heartbeat')
