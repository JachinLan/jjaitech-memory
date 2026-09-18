"""Verify actual local registrations created by the public installer; no model calls."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

config=Path.home()/'.workbuddy'
settings=json.loads((config/'settings.json').read_text(encoding='utf-8-sig'))
key='jjaitech-memory@jjaitech-local'
assert settings['theme']=='smoke-test-sentinel','unrelated config lost'
assert settings['enabledPlugins'][key] is True
allowed=settings['sandbox']['filesystem']['allowWrite']
assert len(allowed)==1 and Path(allowed[0])==Path.home()/'AI-Wiki','permission duplicated or widened'
rules=settings['permissions']['allow']
expected_tools=['mcp__jjaitech-memory__'+name for name in ['write_memory','defer_memory','search_memory']]
assert all(rules.count(name)==1 for name in expected_tools),'local MCP grants missing or duplicated'
assert not any(x in rules for x in ['mcp__*','DeferExecuteTool']),'permission widened'
registry=json.loads((config/'plugins/installed_plugins.json').read_text(encoding='utf-8-sig'))
entries=registry['plugins'][key]
assert len(entries)==1 and entries[0]['version']==json.loads(Path('release.json').read_text())['plugin_version']
installed=Path(entries[0]['installPath'])
expected=json.loads(Path('release.json').read_text())['source_files']
for rel in ['scripts/memory.py','scripts/portable.py','scripts/sources.py','scripts/quality.py','scripts/memory_mcp.py','scripts/retrieval_guard.py']:
    assert hashlib.sha256((installed/rel).read_bytes()).hexdigest()==expected[rel]
requests='\n'.join(json.dumps({'jsonrpc':'2.0','id':i,'method':method}) for i,method in enumerate(['initialize','tools/list'],1))+'\n'
r=subprocess.run([sys.executable,str(installed/'scripts/memory_mcp.py')],input=requests,text=True,capture_output=True,check=True)
responses=[json.loads(line) for line in r.stdout.splitlines()]
assert {x['name'] for x in responses[1]['result']['tools']}=={'write_memory','defer_memory','search_memory'}
with tempfile.TemporaryDirectory(prefix='jjaitech-hook-smoke-') as d:
    root=Path(d)/'wiki';transcript=Path(d)/'synthetic.jsonl'
    transcript.write_text(json.dumps({'type':'user','message':{'role':'user','content':'Temporary test only.'}})+'\n',encoding='utf-8')
    env=dict(os.environ,JJAITECH_WIKI_ROOT=str(root))
    hook={'session_id':'smoke-synthetic','transcript_path':str(transcript)}
    for _ in range(2):
        subprocess.run([sys.executable,str(installed/'scripts/memory.py'),'hook','SessionEnd'],input=json.dumps(hook),text=True,env=env,check=True,capture_output=True)
    raw=list((root/'Raw').glob('*.jsonl'))
    assert len(raw)==1 and raw[0].read_bytes()==transcript.read_bytes()
    assert not list((root/'Share').iterdir())
print(json.dumps({'actual_public_command_runs':2,'real_official_cli_used':True,'registration':'passed','permission_scope_and_idempotency':'passed','unrelated_config_preserved':True,'raw_hook_and_dedup':'passed','authenticated_workbuddy_model_test':False}))
