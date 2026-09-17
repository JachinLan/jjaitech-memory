import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec=importlib.util.spec_from_file_location('release',Path(__file__).parents[1]/'distribution/build_release.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class DistributionTests(unittest.TestCase):
    def test_rejects_http_credentials_and_command_injection(self):
        for u in ['http://example.com/x.zip','https://u:p@example.com/x.zip',"https://example.com/x';exit;.zip",'https://example.com/x.zip?secret=1','https://example.com/x%0a.zip']:
            with self.subTest(url=u),self.assertRaises(ValueError):m.command(u,'a'*64)

    def test_verifies_before_unpack_and_execution(self):
        c=m.command('https://example.com/releases/x.zip','a'*64)
        self.assertLess(c.index('Get-FileHash'),c.index('Expand-Archive'))
        self.assertLess(c.index('Expand-Archive'),c.index('[scriptblock]::Create'))
        self.assertNotIn('Set-ExecutionPolicy',c)
        self.assertNotIn('Bypass',c)
        self.assertNotIn('\n',c)

    def test_allowlisted_code_only_release(self):
        with tempfile.TemporaryDirectory() as d:
            result=m.build(d)
            with zipfile.ZipFile(Path(d)/result['asset']) as z:
                self.assertEqual(set(z.namelist()),{'jjaitech-memory/'+p for p in m.FILES}|{'SOURCE_SHA256.json'})
            self.assertFalse(result['wiki_data_included'])
            with self.assertRaises(ValueError):m.build(d)
