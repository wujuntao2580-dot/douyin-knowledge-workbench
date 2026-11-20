import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/knowledge"))
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Lock
from unittest.mock import patch

from library_state import LibraryState, PROJECT

sys.path.insert(0, str(PROJECT / 'app/workflow'))
import workflow


class ImportChoiceTests(unittest.TestCase):
    def test_every_new_batch_requires_choice_and_records_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = workflow.Workflow.__new__(workflow.Workflow)
            service.lock = Lock()
            service.file = Path(temporary) / 'queue.json'
            service.active = None
            service.state = {'settings': workflow.DEFAULTS.copy(), 'batches': []}
            service.start = lambda batch, step, rows: service.save()
            payload = {'name': '测试', 'account': 'fixture', 'destination': str(Path(temporary) / 'media'),
                       'works': [{'id': '9000000000000000001', 'url': 'https://www.douyin.com/video/9000000000000000001'}]}
            with self.assertRaisesRegex(ValueError, '请选择|请为本批'):
                service.create(payload)
            store = LibraryState(Path(temporary) / 'personal.json', Path(temporary) / 'missing.html')
            store.deleted_records = lambda: {'9000000000000000001'}
            with patch.object(workflow, 'legacy_or_registered', return_value={}), patch.object(workflow, 'LibraryState', return_value=store):
                for mode in ('auto', 'manual'):
                    service.create({**payload, 'classificationMode': mode})
                    saved = json.loads(service.file.read_text('utf-8'))
                    self.assertEqual(mode, saved['batches'][0]['classificationMode'])
                    self.assertTrue(saved['batches'][0]['works'][0]['forceImport'])

    def test_import_handoff_marks_manual_before_local_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = LibraryState(root / 'personal.json', root / 'missing.html')
            service = workflow.Workflow.__new__(workflow.Workflow)
            service.stage = lambda *args: None
            service.prepare_import = lambda *args: []
            with patch.object(workflow, 'LibraryState', return_value=store), patch.object(workflow, 'saved_profiles', return_value={}):
                service.import_works({'classificationMode': 'manual', 'account': 'test', 'name': '测试'}, [{'id': 'new'}])
            state = json.loads(store.path.read_text('utf-8'))
            self.assertEqual('manual', state['assignments']['new']['mode'])

    def test_local_summary_schema_accepts_new_topics_without_network(self):
        sys.path.insert(0, str(PROJECT / 'app/summary'))
        spec = importlib.util.spec_from_file_location('summary_for_check', PROJECT / 'app/summary/summarize_offline.py')
        module = importlib.util.module_from_spec(spec)
        with tempfile.TemporaryDirectory() as temporary:
            store = LibraryState(Path(temporary) / 'personal.json', Path(temporary) / 'missing.html')
            with patch('library_state.LibraryState', return_value=store):
                spec.loader.exec_module(module)
        result = module.clean_result({'core': '通过本地模型把文字要求转换为画面，并反复检查输出。', 'tags': [], 'new_topics': ['AI绘画'],
                                      'points': [{'i': 0, 'heading': '检查生成的图像', 'detail': '先用简短要求生成一幅图像，再按具体问题逐步调整描述。'}]}, {0: 0})
        self.assertEqual(['AI绘画'], result['tags'])
        with patch.object(module, 'request', return_value={'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}) as call:
            module.complete(1, 'test', 'test', {0: 0}, 0)
            schema = call.call_args.args[3]['response_format']['schema']
            self.assertIn('new_topics', schema['properties'])


if __name__ == '__main__':
    unittest.main()
