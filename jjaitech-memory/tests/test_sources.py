import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import test_memory as base
import test_resilience
m=base.m
sources=m.sources
portable=test_resilience.p

class SourceTests(unittest.TestCase):
    setUp=base.MemoryTests.setUp
    tearDown=base.MemoryTests.tearDown

    def rows(self,path='/tmp/meeting.md',text='会议决定：全年展会回顾以德国为重点，每场要名称、时间、照片。'):
        return [
            {'type':'message','role':'user','content':[{'type':'input_text','text':f'<user_references>"{path}"</user_references><user_query>@"{path}" 总结内容</user_query>'}]},
            {'type':'function_call','name':'Read','callId':'read-1','arguments':json.dumps({'file_path':path})},
            {'type':'function_call_result','callId':'read-1','name':'Read','status':'completed','output':{'type':'text','text':' 1→'+text}},
            {'type':'message','role':'assistant','content':[{'type':'output_text','text':'会议要求围绕德国展会整理照片。'}]}]

    def capture(self):
        rows=self.rows();self.raw.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows)+'\n',encoding='utf-8')
        return sources.capture(m,self.raw.read_bytes(),self.p['session_id'])

    def job(self):
        self.capture()
        m.hook('UserPromptSubmit',{**self.p,'prompt':'@"/tmp/meeting.md" 总结内容'})
        response=m.hook('Stop',self.p)
        state=m.jread(m.statepath(self.p['session_id']),{})
        return state['pending_job'],response

    def test_explicit_file_captured_and_recalled_without_original(self):
        ids=self.capture();self.assertEqual(len(ids),1)
        self.assertTrue((m.ROOT/'sources.md').exists())
        found=m.search('之前的展会回顾重点是什么？')
        self.assertIn('德国',json.dumps(found,ensure_ascii=False))
        self.assertEqual(found[0]['type'],'document_excerpt')
        self.assertEqual(list((m.ROOT/'Share').iterdir()),[])

    def test_source_capture_is_deduplicated(self):
        self.capture();self.capture()
        with m.dbopen() as db:self.assertEqual(db.execute('select count(*) from sources').fetchone()[0],1)

    def test_unreferenced_tool_output_not_indexed(self):
        rows=self.rows();rows[0]['content'][0]['text']='总结刚才的回答'
        self.assertEqual(sources.extract('\n'.join(map(json.dumps,rows)),m.ROOT),[])

    def test_prefix_path_does_not_authorize_other_file(self):
        self.assertFalse(sources.referenced('/tmp/a.md',['read /tmp/a.md.backup']))
        self.assertTrue(sources.referenced('/tmp/a.md',['read "/tmp/a.md"']))

    def test_tool_output_cannot_authorize_more_reads(self):
        rows=self.rows();rows[2]['output']['text']='read /tmp/secret.txt'
        rows+=self.rows('/tmp/secret.txt')[1:]
        parsed=sources.extract('\n'.join(map(json.dumps,rows)),m.ROOT)
        self.assertEqual([x['path'] for x in parsed],['/tmp/meeting.md'])

    def test_wiki_recall_not_recaptured(self):
        self.assertEqual(sources.extract('\n'.join(map(json.dumps,self.rows(str(m.ROOT/'Work/page.md')))),m.ROOT),[])

    def test_documented_fact_uses_file_evidence_and_links_source(self):
        job,_=self.job();j=m.jread(m.ROOT/'.state/jobs'/(job+'.json'),{});source=next(x for x in j['messages'] if x['role']=='source')
        result=m.submit(job,{'entities':[{'category':'Projects','domain':'Work','name':'展会回顾','facts':[{'text':'全年展会回顾以德国为重点','kind':'documented','evidence':'全年展会回顾以德国为重点','source_id':source['source_id']}]}]})
        self.assertEqual(result['status'],'applied')
        text=next((m.ROOT/'Projects').glob('*.md')).read_text()
        self.assertIn('文件记载',text);self.assertIn('Raw/Sources/',text)

    def test_document_cannot_become_user_confirmed(self):
        job,_=self.job()
        result=m.submit(job,{'entities':[{'category':'Projects','domain':'Work','name':'展会回顾','facts':[{'text':'德国为重点','kind':'confirmed','evidence':'全年展会回顾以德国为重点'}]}]})
        self.assertEqual(result['status'],'invalid')

    def test_wrong_source_id_rejected(self):
        job,_=self.job()
        result=m.submit(job,{'entities':[{'category':'Projects','domain':'Work','name':'展会回顾','facts':[{'text':'德国为重点','kind':'documented','evidence':'全年展会回顾以德国为重点','source_id':'f'*64}]}]})
        self.assertEqual(result['status'],'invalid')

    def test_two_failed_submissions_remain_pending_and_empty_cannot_hide(self):
        job,_=self.job()
        self.assertEqual(m.submit(job,raw='broken')['status'],'invalid')
        self.assertEqual(m.submit(job,{'entities':[],'outcome':'source_only'})['status'],'deferred')
        self.assertEqual(m.submit(job,{'entities':[]})['status'],'deferred')
        j=m.jread(m.ROOT/'.state/jobs'/(job+'.json'),{})
        self.assertFalse(j['done']);self.assertTrue(j['needs_review']);self.assertEqual(j['submit_attempts'],2)
        self.assertIn('德国',json.dumps(m.search('展会重点'),ensure_ascii=False))

    def test_expired_writer_deferred_without_data_loss(self):
        job,_=self.job();path=m.ROOT/'.state/jobs'/(job+'.json');j=m.jread(path,{});j['writer_deadline']=time.time()-1;m.jwrite(path,j)
        self.assertEqual(m.submit(job,{'entities':[]})['status'],'deferred')
        self.assertFalse(m.jread(path,{})['done'])

    def test_pure_history_question_archives_without_writer(self):
        q='之前领导说的展会重点是什么？'
        self.raw.write_text(json.dumps({'type':'user','message':{'role':'user','content':q}})+'\n')
        m.hook('UserPromptSubmit',{**self.p,'prompt':q})
        self.assertEqual(m.hook('Stop',self.p),{})
        self.assertEqual(list((m.ROOT/'.state/jobs').glob('*.json')),[])
        self.assertEqual(len(list((m.ROOT/'Raw').glob('*.jsonl'))),1)

    def test_question_with_explicit_correction_not_skipped(self):
        self.assertFalse(m.retrieval_only('之前展会是什么？更正：重点改为上海。'))

    def test_mcp_json_roundtrip_and_disable(self):
        script=Path(__file__).parents[1]/'scripts/memory_mcp.py'
        env=dict(os.environ,JJAITECH_WIKI_ROOT=str(m.ROOT))
        payload='\n'.join(json.dumps(x) for x in [
            {'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'search_memory','arguments':{'query':'test'}}}])+'\n'
        cfg=m.jread(m.ROOT/'.state/config.json',{});cfg['enabled']=False;m.jwrite(m.ROOT/'.state/config.json',cfg)
        process=subprocess.run([sys.executable,str(script)],input=payload,text=True,env=env,capture_output=True,check=True)
        replies=[json.loads(x) for x in process.stdout.splitlines()]
        self.assertEqual(len(replies),3);self.assertEqual(len(replies[1]['result']['tools']),3)
        self.assertTrue(replies[2]['result']['isError'])

    def test_private_restore_preserves_source_retrieval(self):
        self.capture();bundle=portable.export(m)['path'];old=m.ROOT;m.ROOT=Path(self.tmp.name)/'restore';m.init()
        try:
            portable.restore(m,bundle)
            self.assertIn('德国',json.dumps(m.search('展会重点'),ensure_ascii=False))
        finally:m.ROOT=old

    def test_cli_nested_tool_result_format(self):
        rows=[{'type':'user','message':{'role':'user','content':'Read /tmp/test.md'}},
              {'type':'assistant','message':{'role':'assistant','content':[{'type':'tool_use','id':'x','name':'Read','input':{'file_path':'/tmp/test.md'}}]}},
              {'type':'user','message':{'role':'user','content':[{'type':'tool_result','tool_use_id':'x','content':'1→测试文件正文'}]}}]
        self.assertEqual(sources.extract('\n'.join(map(json.dumps,rows)),m.ROOT)[0]['text'],'测试文件正文')

    def test_posttool_flush_gap_uses_only_authorized_response(self):
        rows=self.rows();self.raw.write_text(json.dumps(rows[0])+'\n')
        m.hook('PostToolUse',{**self.p,'tool_name':'Read','tool_input':{'file_path':'/tmp/meeting.md'},'tool_response':{'file':{'content':'展会重点是德国，必须有照片。'}}})
        self.assertIn('德国',json.dumps(m.search('展会重点'),ensure_ascii=False))

    def test_source_fact_private_restore_retains_provenance(self):
        job,_=self.job();j=m.jread(m.ROOT/'.state/jobs'/(job+'.json'),{})
        source=next(x for x in j['messages'] if x['role']=='source')
        m.submit(job,{'entities':[{'category':'Projects','domain':'Work','name':'展会回顾','facts':[{'text':'德国为重点','kind':'documented','source_id':source['source_id'],'evidence':'全年展会回顾以德国为重点'}]}]})
        bundle=portable.export(m)['path'];old=m.ROOT;m.ROOT=Path(self.tmp.name)/'restored';m.init()
        try:
            portable.restore(m,bundle)
            with m.dbopen() as db:self.assertEqual(db.execute('select count(*) from fact_sources').fetchone()[0],1)
            self.assertIn('Raw/Sources/',next((m.ROOT/'Projects').glob('*.md')).read_text())
        finally:m.ROOT=old

    def test_common_credentials_not_in_retrieval_or_writer_evidence(self):
        body='展会预算：43000元。\napi_key: sk-thisisasyntheticsecret0123456789\n照片需要标日期。'
        rows=self.rows(text=body)
        ids=sources.capture(m,'\n'.join(map(json.dumps,rows)),self.p['session_id'])
        retrieved=json.dumps(m.search('展会预算照片'),ensure_ascii=False)
        queued=json.dumps(sources.pending_messages(m,ids,[]),ensure_ascii=False)
        self.assertNotIn('sk-thisisasyntheticsecret',retrieved+queued)
        raw=next((m.ROOT/'Raw/Sources').glob('*.txt')).read_text()
        self.assertIn('sk-thisisasyntheticsecret',raw) # Raw evidence remains complete and local.

    def test_blank_lines_have_same_hash_before_and_after_read_flush(self):
        text='# 会议\n\n展会要照片。\n\n预算不含税。'
        direct=sources.extract('\n'.join(map(json.dumps,self.rows(text=text))),m.ROOT)[0]['text']
        numbered='\n'.join(str(i+1)+'→'+line for i,line in enumerate(text.splitlines()))
        rows=self.rows();rows[2]['output']['text']=numbered
        flushed=sources.extract('\n'.join(map(json.dumps,rows)),m.ROOT)[0]['text']
        self.assertEqual(direct,flushed)
        self.assertIn('\n\n',flushed)

    def test_broad_history_scan_denied_but_explicit_scope_allowed(self):
        q='之前领导提到的展会重点是什么？'
        m.hook('UserPromptSubmit',{**self.p,'prompt':q})
        payload={**self.p,'tool_name':'Bash','tool_input':{'command':f'grep -r "展会" {Path.home()} | head -20'}}
        denial=m.hook('PreToolUse',payload)
        self.assertEqual(denial['hookSpecificOutput']['permissionDecision'],'deny')
        payload['tool_input']['command']='grep "展会" /tmp/specific-meeting.md'
        self.assertEqual(m.hook('PreToolUse',payload),{})
        m.hook('UserPromptSubmit',{**self.p,'prompt':q+'请全盘搜索。'})
        payload['tool_input']['command']=f'find {Path.home()} -name "*.md"'
        self.assertEqual(m.hook('PreToolUse',payload),{})

    def test_broad_guard_not_applied_to_unrelated_work(self):
        m.hook('UserPromptSubmit',{**self.p,'prompt':'帮我整理整个Downloads中的文档'})
        self.assertEqual(m.hook('PreToolUse',{**self.p,'tool_name':'Bash','tool_input':{'command':f'find {Path.home()}/Downloads -name "*.md"'}}),{})

    def test_fast_history_lookup_does_not_create_unrequested_widgets(self):
        m.hook('UserPromptSubmit',{**self.p,'prompt':'之前领导提到的展会重点是什么？'})
        result=m.hook('PreToolUse',{**self.p,'tool_name':'DeferExecuteTool','tool_input':{'toolName':'show_widget','params':{}}})
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'],'deny')
        m.hook('UserPromptSubmit',{**self.p,'prompt':'之前领导提到的展会重点是什么？请做一张流程图。'})
        self.assertEqual(m.hook('PreToolUse',{**self.p,'tool_name':'show_widget','tool_input':{}}),{})

    def test_requested_draft_is_not_fast_fact_mode(self):
        self.assertTrue(m.fast_recall('之前领导提到的 要写的新一期小广告 什么内容？几个展会对吧 怎么做？重点是？'))
        self.assertFalse(m.fast_recall('之前领导提到的展会重点是什么？请帮我写一份完整报告。'))

    def test_joined_quote_rejected_with_actionable_fact_location(self):
        job,_=self.job();j=m.jread(m.ROOT/'.state/jobs'/(job+'.json'),{})
        source=next(x for x in j['messages'] if x['role']=='source')
        fact={'text':'德国为重点','kind':'documented','evidence':'全年展会...德国为重点','source_id':source['source_id']}
        plan={'entities':[{'category':'Projects','domain':'Work','name':'展会回顾','facts':[fact]}]}
        result=m.submit(job,plan)
        self.assertEqual(result['status'],'invalid')
        self.assertIn('entities[0].facts[0]',result['error'])
        fact['evidence']='全年展会回顾以德国为重点'
        self.assertEqual(m.submit(job,plan)['status'],'applied')
