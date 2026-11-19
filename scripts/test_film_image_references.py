"""Exercise image requirements separately from renderable illustration data."""
from pathlib import Path
import copy
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import whole_film_renderer as film


class Store:
    def __init__(self, root): self.root=Path(root)
    def find_file(self, fid):
        if fid not in {'file-ready','file-deleted','file-audio'}: raise ValueError('missing')
        return {'bucket':'images','contentType':'audio/wav' if fid=='file-audio' else 'image/png'}
    def file_directory(self,bucket,fid): return self.root/bucket/fid


def plan(**scene):
    return film.validate_plan({'title':'植物科普','theme':'botanical','duration':5,
        'scenes':[{'kind':'diagram','title':'叶绿体','illustration':'chloroplast','narration':'原旁白，保留。','seconds':5,**scene}]})


class ImageReferences(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=Store(self.temp.name)
        for fid in ['file-ready','file-audio']:
            p=self.store.file_directory('images',fid)/'content.bin';p.parent.mkdir(parents=True);p.write_bytes(b'fixture')
        self.assets=[{'id':'leaf','name':'叶片图','fileId':'file-ready'},
                     {'id':'pending','name':'待生图叶绿体','fileId':''},
                     {'id':'deleted','name':'已删除图片','fileId':'file-deleted'},
                     {'id':'audio','name':'音频不是图片','fileId':'file-audio'}]

    def test_image_kind_with_supported_diagram_needs_no_external_image(self):
        raw=plan(kind='image',assetId=None);before=copy.deepcopy(raw)
        result=film.resolve_plan_images(raw,self.store,self.assets,'ink-press')
        self.assertEqual(result['scenes'][0]['kind'],'diagram')
        self.assertEqual(result['scenes'][0]['illustration'],'chloroplast')
        self.assertEqual(result['scenes'][0]['narration'],raw['scenes'][0]['narration'])
        self.assertEqual(raw,before);self.assertTrue(result['imageWarnings'])

    def test_unready_optional_reference_cannot_block_text_or_diagram(self):
        result=film.resolve_plan_images(plan(assetId='pending'),self.store,self.assets,'ink-press')
        self.assertEqual(result['scenes'][0]['assetId'],'');self.assertIn('待生图叶绿体',result['imageWarnings'][0])

    def test_true_photo_requirement_still_blocks_and_names_the_segment(self):
        for attributes in [dict(kind='image',illustration='',assetId='pending'),dict(imageRequired=True,assetId='pending')]:
            with self.assertRaisesRegex(ValueError,'第1段.*待生图叶绿体'):
                film.resolve_plan_images(plan(**attributes),self.store,self.assets,'ink-press')

    def test_deleted_and_audio_files_are_not_offered_as_images(self):
        self.assertEqual(list(film.ready_image_assets(self.store,self.assets)),['leaf'])

    def test_unique_name_or_file_id_can_resolve_only_to_own_ready_asset(self):
        for reference in ['leaf','叶片图','file-ready']:
            result=film.resolve_plan_images(plan(kind='image',assetId=reference),self.store,self.assets,'ink-press')
            self.assertEqual(result['scenes'][0]['assetId'],'leaf')
        with self.assertRaises(ValueError):
            film.resolve_plan_images(plan(kind='image',illustration='',assetId='other-project-file'),self.store,self.assets,'ink-press')

    def test_ambiguous_name_is_not_guessed(self):
        self.assets.append({'id':'duplicate','name':'叶片图','fileId':'file-ready'})
        with self.assertRaises(ValueError):
            film.resolve_plan_images(plan(kind='image',illustration='',assetId='叶片图'),self.store,self.assets,'ink-press')

    def test_nonbotanical_renderer_cannot_pretend_it_drew_a_plant(self):
        raw=plan(kind='image');raw['theme']='technology'
        with self.assertRaises(ValueError):film.resolve_plan_images(raw,self.store,self.assets)

    def test_requirements_and_notices_survive_round_trip(self):
        raw=plan(imageRequired=True);raw['imageWarnings']=['保留提示']
        again=film.validate_plan(raw)
        self.assertTrue(again['scenes'][0]['imageRequired']);self.assertEqual(again['imageWarnings'],['保留提示'])


if __name__=='__main__':unittest.main()
