"""Template routing and content preservation; no model or media generation."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inkpress_template as template
import whole_film_renderer as film


def plan(count=11, duration=30):
    return film.validate_plan({'title': 'Content', 'duration': duration, 'scenes': [
        {'kind': 'statement', 'title': f'Point {i}', 'seconds': 3,
         'narration': f'Sentence {i}.', 'items': [f'Fact {i}']}
        for i in range(count)]})


class TemplateContract(unittest.TestCase):
    def test_legacy_selection_and_other_modes(self):
        self.assertEqual(template.selected_template({'mode': 'template'}), 'ink-press')
        for mode in ('autonomous', 'guided', ''):
            self.assertEqual(template.selected_template({'mode': mode}), '')

    def test_unknown_selection_cannot_fall_back(self):
        with self.assertRaisesRegex(ValueError, '执行器'):
            template.selected_template({'templateId': 'missing-template'})

    def test_native_slots_keep_every_sentence_and_source(self):
        original = plan()
        snapshot = copy.deepcopy(original)
        bound = template.bind(original)
        self.assertEqual(original, snapshot)
        self.assertEqual([s['templateSlot'] for s in bound['scenes']], [s[0] for s in template.SLOTS])
        self.assertEqual(bound['durationInFrames'], 1085)
        self.assertEqual(''.join(s['narration'] for s in bound['scenes']), ''.join(s['narration'] for s in original['scenes']))
        self.assertEqual(bound['templateSourceScenes'], original['scenes'])

    def test_retry_preserves_edited_content_and_does_not_inflate(self):
        bound = template.bind(plan())
        bound['scenes'][3]['title'] = 'User edit'
        again = template.bind(film.validate_plan(bound))
        self.assertEqual(again['durationInFrames'], bound['durationInFrames'])
        self.assertEqual(again['scenes'][3]['title'], 'User edit')
        self.assertEqual([s['narration'] for s in again['scenes']], [s['narration'] for s in bound['scenes']])

    def test_short_source_never_duplicates_narration(self):
        original = plan(3)
        result = template.bind(original)
        self.assertEqual(''.join(s['narration'] for s in result['scenes']), ''.join(s['narration'] for s in original['scenes']))

    def test_template_prepare_and_generic_prepare_are_distinct(self):
        class Store:
            def list_documents(self, namespace): return []
        class Api:
            def backend_request(self, *args):
                self.system = args[-1]['messages'][0]['content']
                return {'choices': [{'message': {'content': json.dumps(plan(10))}}]}
        api = Api()
        with patch.object(film, 'project_context', return_value=(Store(), {'ratio': '16:9'}, {'script': 'User facts'})), patch.object(film, 'assets_for', return_value=[]):
            native = film.prepare(api, {'model': 'fixture', 'brief': {'mode': 'template', 'duration': 30}})['plan']
            self.assertEqual(native['templateId'], 'ink-press')
            self.assertIn('1085', api.system)
            self.assertNotIn('开场不超过约2秒', api.system)
            generic = film.prepare(api, {'model': 'fixture', 'brief': {'mode': 'autonomous', 'duration': 30}})['plan']
            self.assertNotIn('templateId', generic)
            self.assertEqual(generic['rendererVersion'], 2)


if __name__ == '__main__':
    unittest.main()
