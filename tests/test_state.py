import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/knowledge"))
import json
import tempfile
import unittest
from pathlib import Path

from library_state import LibraryState


class PersonalStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog = {'topics': {}, 'videos': [self.video('1', ['时间管理']), self.video('2', ['注意力管理'])]}
        self.page = self.root / 'catalog.html'
        self.page.write_text('<script id="catalog" type="application/json">' + json.dumps(self.catalog) + '</script>', 'utf-8')
        self.store = LibraryState(self.root / 'personal.json', self.page)
        self.state = self.store.sync(self.catalog)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def video(ident, tags):
        return {'id': ident, 'tags': tags, 'core': '真实测试摘要', 'transcript': '已有转写内容'}

    def act(self, action, **kwargs):
        self.state = self.store.act({'action': action, **kwargs}, self.catalog)
        return self.state

    def test_baseline_and_new_video_requires_choice(self):
        self.assertEqual(8, len(self.state['groups']) - 1)
        self.assertFalse(self.state['videos']['1']['pending'])
        self.catalog['videos'].append(self.video('3', ['时间管理']))
        state = self.store.sync(self.catalog)
        self.assertEqual('choose', state['videos']['3']['mode'])
        self.assertTrue(state['videos']['3']['pending'])

    def test_manual_recommend_confirm_and_preserve_on_reimport(self):
        self.store.mark_import(['3'], 'manual')
        self.catalog['videos'].append(self.video('3', ['时间管理']))
        state = self.store.sync(self.catalog)
        self.assertEqual(['时间管理'], state['videos']['3']['suggested'])
        self.assertEqual([], state['videos']['3']['topics'])
        self.act('video.assign', id='3', topics=['注意力管理'])
        self.store.mark_import(['3'], 'auto')
        self.assertEqual(['注意力管理'], self.store.sync(self.catalog)['videos']['3']['topics'])

    def test_auto_and_unknown_or_duplicate_topic_review(self):
        self.store.mark_import(['3', '4', '5'], 'auto')
        self.catalog['videos'] += [self.video('3', ['AI绘画']), self.video('4', ['深海生态']), self.video('5', ['时间管理法'])]
        state = self.store.sync(self.catalog)
        self.assertFalse(state['videos']['3']['pending'])
        self.assertEqual('ai', state['topics']['AI绘画']['group'])
        self.assertTrue(state['videos']['4']['pending'])
        self.assertEqual('时间管理', state['topics']['时间管理法']['similar'])
        self.act('topic.merge', id='时间管理法', target='时间管理')
        self.assertEqual(['时间管理'], self.state['videos']['5']['topics'])
        self.act('topic.move', id='深海生态', group='health')
        self.assertFalse(self.state['videos']['4']['pending'])

    def test_folders_favorites_persist_and_merge_canonical(self):
        self.act('folder.create', name='工作')
        folder = next(key for key, value in self.state['folders'].items() if value['name'] == '工作')
        self.act('favorite.set', kind='video', id='1', folders=[folder])
        self.act('favorite.set', kind='topic', id='时间管理', folders=[folder])
        self.act('topic.rename', id='时间管理', name='日程安排')
        self.act('topic.merge', id='时间管理', target='注意力管理')
        reloaded = LibraryState(self.store.path, self.page).sync(self.catalog)
        self.assertIn(['topic', '注意力管理'], reloaded['folders'][folder]['items'])
        self.assertIn(['video', '1'], reloaded['folders'][folder]['items'])
        self.assertEqual(['注意力管理'], reloaded['videos']['1']['topics'])
        self.act('folder.delete', id=folder)
        self.assertIn('1', self.state['videos'])

    def test_group_merge_keeps_future_routing(self):
        self.act('group.merge', id='ai', target='business')
        self.catalog['videos'].append(self.video('3', ['智能体设计']))
        state = self.store.sync(self.catalog)
        self.assertEqual('business', state['topics']['智能体设计']['group'])

    def test_stale_revision_and_invalid_input_do_not_overwrite(self):
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.act({'action': 'group.rename', 'id': 'business', 'name': '新名称', 'revision': 0}, self.catalog)
        with self.assertRaises(ValueError):
            self.store.act({'action': 'favorite.set', 'kind': 'video', 'id': 'missing', 'folders': ['default']}, self.catalog)
        self.assertEqual(before, self.store.path.read_bytes())


if __name__ == '__main__':
    unittest.main()
