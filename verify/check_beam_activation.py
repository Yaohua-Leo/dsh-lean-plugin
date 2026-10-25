"""Controller regression tests; mocked transport is NOT Beam runtime evidence."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'tools'))
import probe_beam_project as beam
import set_lean_mode as modes
from lean_capabilities import read_spec


class FakeClient:
    fail = None
    calls = []
    def __init__(self, **kwargs):
        self.project = Path(kwargs['cwd'])
    def send(self, *args, **kwargs): pass
    def close(self): pass
    def request(self, method, params):
        if method == 'initialize': return {'result':{'protocolVersion':'2025-11-25'}}
        if method == 'tools/list':
            names = read_spec()['mcp']['capabilityProfiles']['beam']['requiredTools']['lean-beam']
            return {'result':{'tools':[{'name':n} for n in names if not (self.fail == 'missing' and n == 'lean_sync')]}}
        name = params['name']
        self.calls.append(name)
        if name == 'beam_version':
            result = {'name':'lean-beam-mcp','source_commit':read_spec()['skills']['beam']['commit']}
            if self.fail == 'pin': result['source_commit'] = '0'*40
            if self.fail == 'stale': result['runtime_current'] = False
        elif name == 'lean_sync':
            if self.fail == 'tool': return {'result':{'isError':True,'structuredContent':{'message':'failure'}}}
            result = {'path':'Test.lean','workspace':{'root':str(self.project)},'version':1,
                      'readiness':{'save_ready':True,'blocking_error_count':0},'diagnostics':{'counts':{'error':0}}}
            if self.fail == 'version': result.pop('version')
            if self.fail == 'workspace': result['workspace']['root'] = str(self.project.parent)
        else: result = {'dropped':True}
        return {'result':{'isError':False, 'structuredContent':result}}


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.lf-activation-', dir=REPO)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        for name, content in {'Test.lean':'theorem t : True := by trivial\n', 'lean-toolchain':'leanprover/lean4:v4.35.0',
                              'lakefile.toml':'name = "test"', 'lean-formalization.json':json.dumps({'mode':'lsp-fallback','library':'Test','targets':['t'],'custom':'preserved'})}.items():
            (self.project / name).write_text(content, encoding='utf-8')
        self.command = self.root / 'fake-command'
        self.command.write_text('test fixture, never executed')
        FakeClient.calls = []
        FakeClient.fail = None
    def tearDown(self): self.tmp.cleanup()
    def probe(self):
        with patch.object(beam, 'StdioClient', FakeClient):
            return beam.probe(self.project, 'Test.lean', str(self.command))
    def test_probe_success(self):
        result = self.probe()
        self.assertEqual(result['status'], 'project-sync-compatible')
        self.assertEqual(result['proofAcceptance'], 'unknown')
        self.assertEqual(FakeClient.calls[-1], 'lean_drop_workspace')
    def test_probe_rejections(self):
        for failure in ['pin','stale','missing','tool','version','workspace']:
            with self.subTest(failure=failure):
                FakeClient.fail = failure
                with self.assertRaises(ValueError): self.probe()
    def test_switch_refusal_no_mutation(self):
        shutil.copytree(REPO / 'preset', self.root / 'preset')
        shutil.copyfile(REPO / 'harnesses.json', self.root / 'harnesses.json')
        before = beam.digest(self.root / 'preset/cordis.patch.yml')
        original = (self.project / 'lean-formalization.json').read_bytes()
        with patch.object(modes, 'probe', side_effect=ValueError('incompatible')):
            with self.assertRaises(ValueError): modes.switch(self.root,'beam',self.project,'Test.lean',str(self.command))
        self.assertEqual(before, beam.digest(self.root / 'preset/cordis.patch.yml'))
        self.assertEqual(original, (self.project / 'lean-formalization.json').read_bytes())
        self.assertFalse((self.root / 'mode-backups').exists())
    def test_mode_roundtrip(self):
        shutil.copytree(REPO / 'preset', self.root / 'preset')
        shutil.copytree(REPO / 'skills', self.root / 'skills')
        for name in ['harnesses.json','contract.md']: shutil.copyfile(REPO / name, self.root / name)
        receipt = self.probe()
        with patch.object(modes, 'probe', return_value=receipt):
            result = modes.switch(self.root,'beam',self.project,'Test.lean',str(self.command))
        self.assertTrue((Path(result['backup'])/'beam-probe.json').exists())
        self.assertTrue((self.root/'preset/skills/lean-beam').exists())
        result = modes.switch(self.root,'lsp-fallback',self.project)
        self.assertEqual(json.loads((self.project/'lean-formalization.json').read_text())['custom'],'preserved')
        self.assertFalse((self.root/'preset/skills/lean-beam').exists())
        self.assertEqual(json.loads((self.root/'preset/runtime-policy.json').read_text())['mode'],'lsp-fallback')
    def test_write_failure_rolls_back(self):
        shutil.copytree(REPO/'preset',self.root/'preset')
        shutil.copytree(REPO/'skills',self.root/'skills')
        for name in ['harnesses.json','contract.md']: shutil.copyfile(REPO/name,self.root/name)
        original = (self.project/'lean-formalization.json').read_bytes()
        old_policy = (self.root/'preset/runtime-policy.json').read_bytes()
        write_text = Path.write_text
        def fail_mode(path, *args, **kwargs):
            if path == self.root/'mode.txt': raise OSError('simulated publication failure')
            return write_text(path, *args, **kwargs)
        with patch.object(Path,'write_text',fail_mode):
            with self.assertRaises(OSError): modes.switch(self.root,'lsp-fallback',self.project)
        self.assertEqual((self.project/'lean-formalization.json').read_bytes(),original)
        self.assertEqual((self.root/'preset/runtime-policy.json').read_bytes(),old_policy)
        self.assertFalse((self.root/'mode.txt').exists())


if __name__ == '__main__':
    print('MOCK CONTROLLER TESTS ONLY: no Beam runtime acceptance')
    unittest.main()
