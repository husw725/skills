from pathlib import Path
import tempfile
import unittest
from publish_review import register,document
from translate import read_json
from zipfile import ZipFile

class FakeReview:
    def __init__(self):self.rows=[];self.creates=0;self.fail_after_create=False
    def call(self,name,args):
        if name=='getProjectReviewMaterials':return {'finalCutMaterials':self.rows}
        self.creates+=1;self.rows.append({**args['material'],'assetId':123,'status':8})
        if self.fail_after_create:raise RuntimeError('Ambiguous timeout')
        return self.rows[-1]

class ReviewPublicationTests(unittest.TestCase):
    def spec(self):return {'projectId':148,'gateType':'FINAL_CUT','name':'Carmilla | EP.01 | pt-BR','url':'https://example.invalid/final.mp4','tags':['Carmilla','pt-BR']}
    def test_receipt_readback_and_resume_do_not_duplicate(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'ledger.json';ledger={'items':{}};client=FakeReview()
            self.assertEqual(register(client,self.spec(),ledger,path),123)
            register(client,self.spec(),read_json(path),path)
            self.assertEqual(client.creates,1)
    def test_ambiguous_create_reconciles_and_missing_outcome_blocks(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'ledger.json';ledger={'items':{}};client=FakeReview();client.fail_after_create=True
            with self.assertRaises(RuntimeError):register(client,self.spec(),ledger,path)
            self.assertEqual(read_json(path)['items']['FINAL_CUT|'+self.spec()['name']]['status'],'submitting')
            register(client,self.spec(),read_json(path),path)
            self.assertEqual(client.creates,1)
            client.rows=[]
            with self.assertRaises(ValueError):register(client,self.spec(),read_json(path),path)
            self.assertEqual(client.creates,1)
    def test_existing_missing_film_tag_cannot_be_silently_reused(self):
        with tempfile.TemporaryDirectory() as root:
            client=FakeReview();client.rows=[{**self.spec(),'assetId':1,'tags':['pt-BR']}]
            with self.assertRaises(ValueError):register(client,self.spec(),{'items':{}},Path(root)/'ledger.json')
            self.assertEqual(client.creates,0)
    def test_document_is_deterministic_and_valid_unicode_xml(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'script.docx';document(path,['Camila & Laura','Você escolheu?']);content=path.read_bytes()
            document(path,['Camila & Laura','Você escolheu?']);self.assertEqual(content,path.read_bytes())
            with ZipFile(path) as z:self.assertIn('Você',z.read('word/document.xml').decode())

if __name__=='__main__':unittest.main()
