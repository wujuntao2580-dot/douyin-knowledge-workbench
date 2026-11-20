import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/knowledge"))
import json
import tempfile
import unittest
from pathlib import Path

from library_state import LibraryState
from deletion import delete_selected


class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ids = ['9000000000000000001', '9000000000000000002']
        (self.root / 'data').mkdir()
        (self.root / 'app/catalog').mkdir(parents=True)
        self.page = self.root / 'data/library.html'
        self.catalog = {'videos': [{'id': key, 'tags': ['时间管理'], 'core': '测试摘要', 'transcript': '测试口播',
                                   'local': (self.root / 'data' / (key + '.mp4')).as_uri()} for key in self.ids]}
        self.page.write_text('<script id="catalog" type="application/json">' + json.dumps(self.catalog) + '</script>', 'utf-8')
        self.store = LibraryState(self.root / 'data/personal.json', self.page)
        self.store.sync(self.catalog)
        for name in ['records', 'subtitles', 'summaries']:
            (self.root / 'data' / name).mkdir()
        registry = {'test': {'records': 'data/records', 'subtitles': 'data/subtitles', 'summaries': 'data/summaries', 'catalogs': []}}
        (self.root / 'data/creators.json').write_text(json.dumps(registry), 'utf-8')
        for key in self.ids:
            for path in [self.root / 'data' / (key + '.mp4'), self.root / 'data/records' / (key + '.json'),
                         self.root / 'data/subtitles' / (key + '.md'), self.root / 'data/subtitles' / (key + '.srt'),
                         self.root / 'data/summaries' / (key + '.json')]:
                path.write_text('test', 'utf-8')

    def tearDown(self):
        self.temporary.cleanup()

    def delete(self, choices, callback=None):
        return delete_selected(self.store, {'ids': [self.ids[0]], 'choices': choices}, self.catalog,
                               recycle_file=callback or (lambda path: path.unlink()))

    def test_all_four_only_selected_files_and_favorite_reference(self):
        self.store.act({'action': 'favorite.set', 'kind': 'video', 'id': self.ids[0], 'folders': ['default']}, self.catalog)
        result = self.delete(dict.fromkeys(['record', 'media', 'transcript', 'summary'], True))
        self.assertEqual(5, result['deletionResult']['filesRemoved'])
        self.assertEqual([], result['folders']['default']['items'])
        self.assertNotIn(self.ids[0], result['videos'])
        self.assertTrue((self.root / 'data' / (self.ids[1] + '.mp4')).exists())
        self.assertTrue((self.root / 'data/creators.json').exists())
        self.assertEqual(1, len(self.store.effective_catalog(self.catalog)['videos']))

    def test_record_only_preserves_every_file(self):
        self.delete({'record': True})
        self.assertTrue((self.root / 'data' / (self.ids[0] + '.mp4')).is_file())

    def test_only_summary_clears_cached_summary_not_transcript(self):
        self.delete({'summary': True})
        video = self.store.effective_catalog(self.catalog)['videos'][0]
        self.assertEqual('', video['core'])
        self.assertEqual('测试口播', video['transcript'])
        self.assertTrue((self.root / 'data/subtitles' / (self.ids[0] + '.srt')).exists())

    def test_invalid_and_stale_requests_never_touch_files(self):
        with self.assertRaises(ValueError):
            delete_selected(self.store, {'ids': ['../../test'], 'choices': {'media': True}}, self.catalog)
        with self.assertRaises(ValueError):
            delete_selected(self.store, {'ids': [self.ids[0]], 'revision': -1, 'choices': {'media': True}}, self.catalog)
        self.assertTrue((self.root / 'data' / (self.ids[0] + '.mp4')).is_file())

    def test_shared_media_is_rejected(self):
        self.catalog['videos'][1]['local'] = self.catalog['videos'][0]['local']
        with self.assertRaisesRegex(ValueError, '其他视频引用'):
            self.delete({'media': True})

    def test_failure_keeps_record_for_retry_and_reimport_restores(self):
        def fail(path):
            raise OSError('测试占用')
        result = self.delete({'record': True, 'media': True}, fail)
        self.assertTrue(result['deletionResult']['failures'])
        self.assertIn(self.ids[0], result['videos'])
        self.delete({'record': True})
        self.store.restore_import([self.ids[0]])
        self.assertIn(self.ids[0], self.store.sync(self.catalog)['videos'])


if __name__ == '__main__':
    unittest.main()
