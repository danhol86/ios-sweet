"""Synthetic offline tests: no Apple images, guest access or QEMU required."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'tools' / 'analyze-qemu-crashes.py'
spec = importlib.util.spec_from_file_location('qemu_crash_analyzer', SOURCE)
analyzer = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = analyzer
spec.loader.exec_module(analyzer)


def trace(base):
    return '\n'.join((
        'exec driverkitd', 'exec SpringBoard',
        f'CRASH driverkitd[66] sig 9 code 0x0 sub 0x0 slide 0xff mh {base:#x}',
        f'CRASH driverkitd pc 0xaaaa lr 0xbbbb sp 0xcccc',
        f'CRASH driverkitd bt 0x1234 0x4567 {base + 0x9e6b4:#x} {base + 0xe937c:#x}',
        'CRASH driverkitd reason ns 1 code 0x7: (none)',
        'exec MobileSafari',
    ))


class CrashAnalysisTests(unittest.TestCase):
    def test_aslr_independent_signature(self):
        a, launches_a = analyzer.analyze(trace(0x100000000))
        b, launches_b = analyzer.analyze(trace(0x110000000))
        self.assertEqual(a, b)
        self.assertEqual(a[0].signal, 9)
        self.assertEqual(a[0].frames, ('external', 'external', '+0x9e6b4', '+0xe937c'))
        self.assertIn('MobileSafari', launches_a & launches_b)

    def test_truncated_and_multiple_processes(self):
        partial = trace(0x100000000).replace('CRASH driverkitd bt 0x1234 0x4567 0x10009e6b4 0x1000e937c\n', '')
        extra = 'CRASH other[12] sig 11 code 0x0 mh 0x123000\nCRASH other bt 0x123060\n'
        crashes, _ = analyzer.analyze(partial + '\n' + extra)
        self.assertEqual(len(crashes), 2)
        self.assertEqual(crashes[0].frames, ())
        self.assertEqual(crashes[1].frames, ('+0x60',))

    def test_compare_counts_distinct_input_logs_not_duplicate_records(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / 'first.log'
            second = Path(directory) / 'second.log'
            first.write_text(trace(0x100000000) + '\n' + trace(0x100000000))
            second.write_text(trace(0x140000000))
            result = analyzer.compare([first, second])
        self.assertEqual(result['files_read'], 2)
        self.assertEqual(len(result['signatures']), 1)
        self.assertEqual(result['signatures'][0]['observations'], 2)
        self.assertEqual(result['signatures'][0]['service_exec_log_count'], 2)
        self.assertEqual(result['signatures'][0]['termination'],
                         {'namespace': 'jetsam', 'cause': 'memory_per_process_limit'})
        self.assertNotIn('0x140000000', str(result))

    def test_reason_classification_does_not_confuse_host_and_guest_memory(self):
        self.assertEqual(analyzer.classify_reason('ns 1 code 0x7: (none)'),
                         {'namespace': 'jetsam', 'cause': 'memory_per_process_limit'})
        self.assertEqual(analyzer.classify_reason('ns 1 code 0x4: (none)'),
                         {'namespace': 'jetsam', 'cause': 'memory_vm_page_shortage'})
        self.assertEqual(analyzer.classify_reason('ns 2 code 0x5: (none)'),
                         {'namespace': 'signal', 'cause': 'signal_code_5'})
        self.assertEqual(analyzer.classify_reason('unreported'),
                         {'namespace': 'unknown', 'cause': 'unknown'})


if __name__ == '__main__':
    unittest.main()
