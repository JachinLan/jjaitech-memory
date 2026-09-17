#!/usr/bin/env python3
"""Real WorkBuddy CLI account/model, frozen plugin, synthetic source, separate sessions."""
import hashlib,json,os,shutil,sqlite3,subprocess,sys,time,uuid
from pathlib import Path
src=Path(__file__).resolve().parents[1]
root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=False)
plugin=root/'plugin';shutil.copytree(src,plugin,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
nonce=uuid.uuid4().hex[:8];topic='青竹会务-'+nonce;amount=27000+int(nonce[:4],16)%20000
file=root/('会议记录-'+nonce+'.md')
file.write_text(f'''# {topic} 项目会议记录
日期：2026-09-17。以下是隔离测试的虚构企业资料。
项目：{topic}；客户：星桥-{nonce}；联系人：林舟-{nonce}。
主管：下一期展会回顾以汉堡展会为重点。每场展会需要名称、日期、现场照片。先收齐素材，再写短文。
主管：本次内容制作预算人民币{amount}元，不含税，有效至2026-11-30。已决定先做两周试点；开始日期还未确定。
员工：长期邮件习惯先写结论，再写行动项。
''',encoding='utf-8')
cli='/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy'
env=dict(os.environ,CODEBUDDY_CONFIG_DIR=str(Path.home()/'.workbuddy'),JJAITECH_WIKI_ROOT=str(root/'wiki'),CODEBUDDY_DISABLE_AUTO_MEMORY='1',DISABLE_TELEMETRY='1',DISABLE_GALILEO='1')
subprocess.run([sys.executable,str(plugin/'scripts/memory.py'),'init'],env=env,capture_output=True,check=True)
cfg=root/'wiki/.state/config.json';c=json.loads(cfg.read_text());c['synthetic_test_vault']=True;cfg.write_text(json.dumps(c))
common=[cli,'--plugin-dir',str(plugin),'--settings','{"enabledPlugins":{"jjaitech-memory@jjaitech-local":false}}','--strict-mcp-config','--mcp-config',json.dumps({'mcpServers':{'jjaitech-memory':{'command':sys.executable,'args':['-X','utf8',str(plugin/'scripts/memory_mcp.py')],'defer_loading':False}}}),'--allowedTools','Read','mcp__jjaitech-memory__write_memory','mcp__jjaitech-memory__defer_memory','mcp__jjaitech-memory__search_memory','--max-turns','8','--output-format','stream-json','--verbose']
prompts={
 'ingest':f'请用Read读取这个会议文件并用三句话概括：@"{file}"。请保留资料自己的日期和不确定性。',
 'recall':f'之前{topic}项目提到的新一期展会回顾，重点是哪场？每场要准备什么？预算多少、含税吗？有效到什么时候？只按已有资料回答，不要猜。'}
results={}
for name,prompt in prompts.items():
 work=root/('workspace-'+name);work.mkdir();start=time.perf_counter()
 with (root/(name+'.jsonl')).open('w') as out,(root/(name+'.stderr')).open('w') as err:
  run=subprocess.run([*common,'-p',prompt],cwd=work,env=env,stdout=out,stderr=err,timeout=240)
 elapsed=time.perf_counter()-start
 rows=[json.loads(l) for l in (root/(name+'.jsonl')).read_text().splitlines() if l.startswith('{')]
 texts=[];calls=[]
 for row in rows:
  if row.get('type')=='assistant':
   for block in row.get('message',{}).get('content',[]):
    if block.get('type')=='text':texts.append(block['text'])
    if block.get('type')=='tool_use':calls.append({'name':block.get('name'),'input':block.get('input')})
 results[name]={'seconds':round(elapsed,3),'returncode':run.returncode,'session':next((x['session_id'] for x in rows if x.get('session_id')),None),'text':'\n'.join(texts),'calls':calls,'runtime_success':any(x.get('type')=='result' and x.get('subtype')=='success' and not x.get('is_error') for x in rows)}
 print(name,results[name]['session'],round(elapsed,2),flush=True)
 if name=='ingest':file.rename(file.with_suffix('.removed')) # Recall must use the saved source, not a surviving original.
with sqlite3.connect(root/'wiki/.state/memory.sqlite3') as db:
 facts=[dict(zip(['kind','text','evidence'],r)) for r in db.execute('select kind,text,evidence from facts')]
 source_count=db.execute('select count(*) from sources').fetchone()[0]
 provenance_count=db.execute('select count(*) from fact_sources').fetchone()[0]
events=[json.loads(l) for l in (root/'wiki/.state/events.jsonl').read_text().splitlines()]
checks={
 'both_sessions_success':all(x['runtime_success'] for x in results.values()),
 'source_captured':source_count==1,
 'source_facts_with_provenance':provenance_count>0 and any(f['kind']=='documented' for f in facts),
 'structured_mcp_write_used':any('write_memory' in x['name'] or 'write_memory' in x.get('input',{}).get('toolName','') for x in results['ingest']['calls']),
 'recall_hamburg':'汉堡' in results['recall']['text'],
 'recall_materials':all(x in results['recall']['text'] for x in ['名称','日期','照片']),
 'recall_budget':str(amount) in results['recall']['text'].replace(',',''),
 'recall_tax':'不含税' in results['recall']['text'],
 'no_shell_scanning':not any(c['name'] in ['Bash','Grep','Glob'] for x in results.values() for c in x['calls']),
 'no_second_writer_for_recall':not any(e['session']==results['recall']['session'] and e['event']=='writer_requested' for e in events),
 'share_empty':not list((root/'wiki/Share').iterdir())}
report={'version':json.loads((plugin/'.codebuddy-plugin/plugin.json').read_text())['version'],'runtime_sha256':hashlib.sha256((plugin/'scripts/memory.py').read_bytes()).hexdigest(),'source_module_sha256':hashlib.sha256((plugin/'scripts/sources.py').read_bytes()).hexdigest(),'fixture':{'topic':topic,'amount':amount},'checks':checks,'results':results,'facts':facts,'all_passed':all(checks.values())}
(root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(checks,ensure_ascii=False,indent=2));sys.exit(0 if report['all_passed'] else 1)
