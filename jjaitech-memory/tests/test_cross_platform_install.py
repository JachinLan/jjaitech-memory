import json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
import test_install
from test_install import i

class CrossPlatformInstallerTests(unittest.TestCase):
    setUp=test_install.InstallerTests.setUp
    tearDown=test_install.InstallerTests.tearDown
    def test_persistent_bash_setting_and_exact_rollback(self):
        original=i.read(self.config/'settings.json');original['env']={'KEEP':'yes','CODEBUDDY_CODE_GIT_BASH_PATH':'old-bash'};i.write(self.config/'settings.json',original)
        def fail(args):
            if args[:2]==['plugin','install']:raise RuntimeError('network failure')
        with self.assertRaises(RuntimeError):i.deploy(self.source,self.config,self.vault,sys.executable,fail,bash='/new/bash')
        self.assertEqual(i.read(self.config/'settings.json'),original)
        r=i.deploy(self.source,self.config,self.vault,sys.executable,lambda args:None,bash='/new/bash')
        self.assertEqual(i.read(self.config/'settings.json')['env'],{'KEEP':'yes','CODEBUDDY_CODE_GIT_BASH_PATH':'/new/bash'})
        self.assertEqual(r['env_changes']['CODEBUDDY_CODE_GIT_BASH_PATH']['before'],'old-bash')

    def test_second_installer_refuses_while_lock_is_held(self):
        code='import sys;sys.path.insert(0,sys.argv[1]);import install_common as i;\nwith i.installation_lock(sys.argv[2]): print("acquired")'
        with i.installation_lock(self.config):
            p=subprocess.run([sys.executable,'-c',code,str(Path(i.__file__).parent),str(self.config)],capture_output=True,text=True,timeout=10)
        self.assertNotEqual(p.returncode,0);self.assertIn('Another jjaitech-memory installer',p.stderr)
        with i.installation_lock(self.config):pass

    def test_registration_verification_failure_rolls_back(self):
        with self.assertRaises(RuntimeError):i.deploy(self.source,self.config,self.vault,sys.executable,lambda args:None,verify=True)
        self.assertEqual(i.read(self.config/'settings.json'),self.original)

class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='jj-install-')
        self.root=Path(self.tmp.name)/"中文 space ' $(literal)";self.root.mkdir()
        self.plugin=self.root/'plugin';source=Path(__file__).parents[1]
        shutil.copytree(source,self.plugin,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        self.config=self.root/'config';self.config.mkdir()
        self.bash=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Git/bin/bash.exe' if os.name=='nt' else Path('/bin/bash')
        if not self.bash.exists():self.skipTest('Git Bash unavailable')
        (self.plugin/'.runtime-python-paths').write_text(Path(sys.executable).as_posix()+'\n',encoding='utf-8')
        (self.plugin/'.runtime-config-root').write_text(self.config.as_posix()+'\n',encoding='utf-8')
        spec=json.loads((self.plugin/'.mcp.json').read_text());spec['mcpServers']['jjaitech-memory'].update(command=str(self.bash),args=['${CODEBUDDY_PLUGIN_ROOT}/scripts/run-memory.sh','mcp']);i.write(self.plugin/'.mcp.json',spec)
    def tearDown(self):self.tmp.cleanup()
    def test_actual_stdio_and_raw_under_unicode_spaces_and_shell_characters(self):
        self.assertIn('passed',i.verify_local_runtime(self.plugin,self.config))
        self.assertFalse((self.root/'literal').exists())
    def test_missing_pinned_python_falls_back_without_network(self):
        (self.plugin/'.runtime-python-paths').write_text('/missing/old/python\n',encoding='utf-8')
        self.assertIn('passed',i.verify_local_runtime(self.plugin,self.config))

if __name__=='__main__':unittest.main()
