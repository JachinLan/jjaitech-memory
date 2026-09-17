import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

spec=importlib.util.spec_from_file_location('install_common',Path(__file__).parents[1]/'scripts/install_common.py')
i=importlib.util.module_from_spec(spec);spec.loader.exec_module(i)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.config=self.root/'config';self.config.mkdir()
        self.source=self.root/'source';(self.source/'.codebuddy-plugin').mkdir(parents=True)
        (self.source/'hooks').mkdir()
        i.write(self.source/'.codebuddy-plugin/plugin.json',{'name':'jjaitech-memory','version':'1.2.0-rc.1'})
        i.write(self.source/'hooks/hooks.json',{'hooks':{'Stop':[{'hooks':[{'type':'command','command':'python3 script.py'}]}]}})
        self.original={'theme':'dark','sandbox':{'enabled':True,'filesystem':{'denyWrite':['/protected'],'allowWrite':['/existing']}}}
        i.write(self.config/'settings.json',self.original)
        self.vault=self.root/'AI-Wiki'

    def tearDown(self):self.tmp.cleanup()

    def test_validation_failure_changes_no_permissions(self):
        def fail(args):raise RuntimeError('validator failure')
        with self.assertRaises(RuntimeError):i.deploy(self.source,self.config,self.vault,sys.executable,fail)
        self.assertEqual(i.read(self.config/'settings.json'),self.original)
        self.assertFalse(self.vault.exists())

    def test_failure_rolls_back_own_keys_preserving_concurrent_change(self):
        def run(args):
            if args[:2]==['plugin','install']:
                changed=i.read(self.config/'settings.json');changed['theme']='light';changed['enabledPlugins']={i.PLUGIN:True,'other@market':True};i.write(self.config/'settings.json',changed)
                i.write(self.config/'plugins/installed_plugins.json',{'version':2,'plugins':{i.PLUGIN:[{'version':'broken'}],'other@market':[{'version':'safe'}]}})
                raise RuntimeError('simulated installation failure')
        with self.assertRaises(RuntimeError):i.deploy(self.source,self.config,self.vault,sys.executable,run)
        result=i.read(self.config/'settings.json')
        self.assertEqual(result['theme'],'light')
        self.assertEqual(result['sandbox'],self.original['sandbox'])
        self.assertEqual(result['enabledPlugins'],{'other@market':True})
        self.assertNotIn(i.PLUGIN,i.read(self.config/'plugins/installed_plugins.json')['plugins'])

    def test_success_only_appends_vault_and_binds_python(self):
        before=copy.deepcopy(self.original)
        result=i.deploy(self.source,self.config,self.vault,sys.executable,lambda args:None)
        expected=copy.deepcopy(before);expected['sandbox']['filesystem']['allowWrite'].append(self.vault.as_posix())
        self.assertEqual(i.read(self.config/'settings.json'),expected)
        self.assertTrue(result['permission_added'])
        hooks=i.read(self.config/'local-marketplaces/jjaitech-local/jjaitech-memory/hooks/hooks.json')
        self.assertIn('-X utf8',hooks['hooks']['Stop'][0]['hooks'][0]['command'])

    def test_existing_vault_permission_not_owned_or_revoked(self):
        config=copy.deepcopy(self.original);config['sandbox']['filesystem']['allowWrite'].append(self.vault.as_posix());i.write(self.config/'settings.json',config)
        result=i.deploy(self.source,self.config,self.vault,sys.executable,lambda args:None)
        self.assertFalse(result['permission_added'])
        self.assertFalse(i.revoke_owned_permission(self.config,result))
        self.assertEqual(i.read(self.config/'settings.json'),config)

    def test_invalid_settings_rejected_before_change(self):
        bad={'sandbox':{'filesystem':{'allowWrite':'wrong type'}}};i.write(self.config/'settings.json',bad)
        with self.assertRaises(ValueError):i.deploy(self.source,self.config,self.vault,sys.executable,lambda args:None)
        self.assertEqual(i.read(self.config/'settings.json'),bad)

    def test_old_plugin_directory_restored_on_failure(self):
        target=self.config/'local-marketplaces/jjaitech-local/jjaitech-memory';target.mkdir(parents=True);(target/'old.txt').write_text('old-version')
        def fail(args):
            if args[:2]==['plugin','update']:raise RuntimeError('update failed')
        with self.assertRaises(RuntimeError):i.deploy(self.source,self.config,self.vault,sys.executable,fail)
        self.assertEqual((target/'old.txt').read_text(),'old-version')

    def test_same_permission_grant_is_idempotent(self):
        once,added=i.with_vault_permission(self.original,self.vault)
        twice,again=i.with_vault_permission(once,self.vault)
        self.assertTrue(added);self.assertFalse(again);self.assertEqual(once,twice)


    def test_mcp_permissions_are_narrow_and_rollback_owned_only(self):
        i.write(self.source/'.mcp.json',{'mcpServers':{'jjaitech-memory':{'command':'python3','args':['server.py']}}})
        original=copy.deepcopy(self.original);original['permissions']={'allow':['Read',i.MEMORY_TOOLS[0]]}
        i.write(self.config/'settings.json',original)
        def fail(args):
            if args[:2]==['plugin','install']:raise RuntimeError('test rollback')
        with self.assertRaises(RuntimeError):i.deploy(self.source,self.config,self.vault,sys.executable,fail)
        self.assertEqual(i.read(self.config/'settings.json'),original)
        receipt=i.deploy(self.source,self.config,self.vault,sys.executable,lambda args:None)
        actual=i.read(self.config/'settings.json')['permissions']['allow']
        self.assertEqual(set(actual),{'Read',*i.MEMORY_TOOLS})
        self.assertNotIn('DeferExecuteTool',actual)
        self.assertNotIn(i.MEMORY_TOOLS[0],receipt['added_tool_rules'])

if __name__=='__main__':unittest.main(verbosity=2)
