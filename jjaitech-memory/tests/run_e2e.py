#!/usr/bin/env python3
"""Real current-account/model test, using a separate synthetic wiki and workspace."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import sqlite3
import uuid
from acceptance_checks import unsupported_execution_status

plugin = Path(os.environ.get('JJAITECH_TEST_PLUGIN', str(Path(__file__).resolve().parents[1])))
cli = Path('/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy')
test = Path(sys.argv[1]) if len(sys.argv)>1 else Path(tempfile.mkdtemp(prefix='jjaitech-memory-test-'))
test.mkdir(parents=True, exist_ok=True)
if (test/'report.json').exists() or (test/'plugin-snapshot').exists():
    raise RuntimeError('Use a fresh test directory; never reuse old answers as evidence.')
shutil.copytree(plugin,test/'plugin-snapshot',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
plugin=test/'plugin-snapshot'
nonce=uuid.uuid4().hex[:8]
worker='验收样例-'+nonce
project='青竹验收-'+nonce
amount=20000+int(nonce[:4],16)%50000
env = dict(os.environ, CODEBUDDY_CONFIG_DIR=str(Path.home()/'.workbuddy'),
           JJAITECH_WIKI_ROOT=str(test/'wiki'), CODEBUDDY_DISABLE_AUTO_MEMORY='1',
           DISABLE_TELEMETRY='1', DISABLE_GALILEO='1')
subprocess.run([sys.executable,str(plugin/'scripts/memory.py'),'init'],env=env,check=True,capture_output=True)
cfg = test/'wiki/.state/config.json'
settings = json.loads(cfg.read_text());settings['synthetic_test_vault']=True
cfg.write_text(json.dumps(settings))
mcp_config=json.loads((plugin/'.mcp.json').read_text())
for server in mcp_config['mcpServers'].values():
    server['args']=[x.replace('${CODEBUDDY_PLUGIN_ROOT}',str(plugin)) for x in server.get('args',[])]
    server['defer_loading']=False
common = [str(cli),'--plugin-dir',str(plugin), '--allowedTools','Read','mcp__jjaitech-memory__write_memory','mcp__jjaitech-memory__defer_memory','mcp__jjaitech-memory__search_memory',
          '--settings','{"enabledPlugins":{"jjaitech-memory@jjaitech-local":false}}',
          '--strict-mcp-config','--mcp-config',json.dumps(mcp_config), '--max-turns','8',
          '--output-format','stream-json','--verbose']
prompts = {
    'writer':f'我叫{worker}，长期不喝咖啡，喜欢无糖桂花茶。我写工作邮件长期习惯先列结论再列行动项。我负责客户云帆验收公司-{nonce}，联系人验收联系人-{nonce}，项目{project}采用验收助手产品。我们已决定先做两周试点。当前报价人民币{amount}元，不含税，有效至2026年11月30日。请给一句简短跟进建议，不要假定试点已经开始或完成。',
    'recall':f'{worker}喜欢喝什么、不喝什么？工作邮件长期习惯是什么？{project}报价金额、含税情况和有效期是什么？金额请用阿拉伯数字。只按已有资料回答，找不到不要猜。'
}
results = {}
for name, prompt in prompts.items():
    workspace = test/('workspace-'+name)
    workspace.mkdir(exist_ok=True)
    with (test/(name+'.jsonl')).open('w') as out, (test/(name+'.stderr')).open('w') as err:
        proc = subprocess.run([*common,'-p',prompt],env=env,cwd=workspace,stdout=out,stderr=err,timeout=240)
    if proc.returncode:
        raise RuntimeError(f'{name} returned {proc.returncode}; inspect local logs')
    stream = [json.loads(x) for x in (test/(name+'.jsonl')).read_text().splitlines() if x.startswith('{')]
    text = '\n'.join(c.get('text','') for x in stream if x.get('type')=='assistant'
                     for c in x.get('message',{}).get('content',[]) if c.get('type')=='text')
    results[name] = {'text':text, 'session_id':next(x['session_id'] for x in stream if x.get('session_id')),
                     'runtime_success':any(x.get('type')=='result' and x.get('subtype')=='success' and not x.get('is_error') for x in stream) and 'Empty stream:' not in text,
                     'models':sorted(set(x.get('message',{}).get('model','') for x in stream if x.get('type')=='assistant'))}
    print(name,results[name]['session_id'],flush=True)

wiki = test/'wiki'
checks = {
    'runtime_success':all(x['runtime_success'] for x in results.values()),
    'personal_updated':any('桂花茶' in p.read_text() for p in (wiki/'Personal').glob('*.md')),
    'work_updated':any('行动项' in p.read_text() for p in (wiki/'Work').glob('*.md')),
    'recall_tea':'桂花茶' in results['recall']['text'],
    'recall_no_coffee':'咖啡' in results['recall']['text'],
    'recall_quote':str(amount) in results['recall']['text'].replace(',',''),
    'recall_tax':'不含税' in results['recall']['text'],
    'recall_validity':any(s in results['recall']['text'] for s in ['2026年11月30日','2026-11-30','2026 年 11 月 30 日']),
    'share_empty':not list((wiki/'Share').iterdir())}
raw_matches = []
for p in (wiki/'Raw').glob('*.meta.json'):
    meta = json.loads(p.read_text())
    copied = p.with_name(p.name.replace('.meta.json','.jsonl')).read_bytes()
    raw_matches.append(copied == Path(meta['transcript_path']).read_bytes() and hashlib.sha256(copied).hexdigest()==meta['sha256'])
checks['raw_exact'] = len(raw_matches)==2 and all(raw_matches)
events = [json.loads(x) for x in (wiki/'.state/events.jsonl').read_text().splitlines()]
checks['bounded_writers'] = sum(x['event']=='writer_requested' and x['session']==results['writer']['session_id'] for x in events)==1 and sum(x['event']=='writer_requested' and x['session']==results['recall']['session_id'] for x in events)==0
with sqlite3.connect(wiki/'.state/memory.sqlite3') as db:
    # Domain is the sharing/privacy boundary; Experience is also a valid Work category.
    checks['work_updated']=bool(db.execute("SELECT 1 FROM facts f JOIN entities e ON e.id=f.entity_id WHERE e.domain='Work' AND f.text LIKE '%行动项%'").fetchone())
    project_facts=[r[0] for r in db.execute('SELECT f.text FROM facts f JOIN entities e ON e.id=f.entity_id WHERE e.name=?',(project,))]
# A saved decision must not acquire an unsupported negative or positive execution
# status from the assistant's answer. This fixture check is not a semantic verifier.
checks['decision_recorded']=any('两周试点' in t and '决定' in t for t in project_facts)
checks['no_invented_execution_status']=not unsupported_execution_status(project_facts)
report = {'plugin_version':json.loads((plugin/'.codebuddy-plugin/plugin.json').read_text())['version'],
          'randomized_fixture':{'worker':worker,'project':project,'amount':amount},
          'runtime_sha256':hashlib.sha256((plugin/'scripts/memory.py').read_bytes()).hexdigest(),
          'test_root':str(test),'checks':checks,'results':results,'all_passed':all(checks.values())}
(test/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(checks,ensure_ascii=False,indent=2))
sys.exit(0 if report['all_passed'] else 1)
