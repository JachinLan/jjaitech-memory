import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('memory', Path(__file__).parents[1] / 'scripts/memory.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        m.ROOT = Path(self.tmp.name) / 'wiki'
        m.init()
        self.raw = Path(self.tmp.name) / 'conversation.jsonl'
        self.text = '我是虚构员工林青，我长期不喝咖啡。测试客户星桥实验公司接受人民币32000元的报价。'
        self.raw.write_text(json.dumps({'type':'user','message':{'role':'user','content':self.text}}, ensure_ascii=False)+'\n')
        self.p = {'session_id':'synthetic-session', 'transcript_path':str(self.raw)}

    def tearDown(self):
        self.tmp.cleanup()

    def request(self):
        m.hook('UserPromptSubmit', {**self.p, 'prompt':self.text})
        response = m.hook('Stop', self.p)
        jobs = list((m.ROOT/'.state/jobs').glob('*.json'))
        return response, jobs[-1].stem

    def plan(self):
        return {'entities':[
            {'category':'Personal','domain':'Personal','name':'林青','facts':[
                {'text':'长期不喝咖啡','kind':'reported','evidence':'我长期不喝咖啡'}]},
            {'category':'Customers','domain':'Work','name':'星桥实验公司','facts':[
                {'text':'接受人民币32000元报价','kind':'reported','evidence':'测试客户星桥实验公司接受人民币32000元的报价'}]},
            {'category':'Work','domain':'Work','name':'测试报价决定','facts':[
                {'text':'客户接受报价','kind':'reported','evidence':'测试客户星桥实验公司接受人民币32000元的报价'}]}]}

    def test_raw_exact_and_deduplicated(self):
        m.hook('SessionEnd', self.p)
        m.hook('SessionEnd', self.p)
        files = list((m.ROOT/'Raw').glob('*.jsonl'))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), self.raw.read_bytes())

    def test_stop_double_loop_guard(self):
        response, _ = self.request()
        self.assertFalse(response['continue'])
        self.assertEqual(m.hook('Stop', self.p), {})
        self.assertNotIn('continue',m.hook('Stop', {**self.p,'stop_hook_active':True}))
        self.assertEqual(len(list((m.ROOT/'.state/jobs').glob('*.json'))),1)

    def test_entity_merge_recall_and_dates(self):
        _, job = self.request()
        m.apply(job, self.plan())
        self.assertEqual(m.apply(job, self.plan())['status'], 'already_applied')
        self.assertEqual(len(list((m.ROOT/'Personal').glob('*.md'))),1)
        self.assertEqual(len(list((m.ROOT/'Work').glob('*.md'))),1)
        result = m.hook('UserPromptSubmit', {**self.p,'prompt':'星桥实验公司报价多少？'})
        self.assertIn('32000',result['hookSpecificOutput']['additionalContext'])
        self.assertIn('synthetic-session', result['hookSpecificOutput']['additionalContext'])
        self.assertEqual(list((m.ROOT/'Share').iterdir()),[])

    def test_share_forbidden(self):
        _,job=self.request(); plan=self.plan();plan['entities'][0]['category']='Share'
        with self.assertRaises(ValueError):m.apply(job,plan)
        self.assertEqual(list((m.ROOT/'Personal').iterdir()),[])

    def test_ai_claim_not_confirmed(self):
        self.raw.write_text(self.raw.read_text()+json.dumps({'type':'assistant','message':{'role':'assistant','content':'建议客户预算五万元'}})+'\n')
        _,job=self.request();plan=self.plan();plan['entities'][0]['facts'][0].update(kind='confirmed',evidence='建议客户预算五万元')
        with self.assertRaises(ValueError):m.apply(job,plan)

    def test_fabricated_evidence_rejected(self):
        _,job=self.request();plan=self.plan();plan['entities'][0]['facts'][0]['evidence']='用户没有说过的话'
        with self.assertRaises(ValueError):m.apply(job,plan)

    def test_missing_transcript_does_not_loop(self):
        self.raw.unlink()
        self.assertEqual(m.hook('Stop', self.p),{})

    def test_disabled_no_archive_or_context(self):
        m.jwrite(m.ROOT/'.state/config.json',{'enabled':False})
        self.assertEqual(m.hook('Stop', self.p),{})
        self.assertFalse(list((m.ROOT/'Raw').iterdir()))

    def test_symlink_escape(self):
        (m.ROOT/'Personal/escape.md').symlink_to(Path(self.tmp.name)/'outside')
        with self.assertRaises(ValueError):m.atomic(m.ROOT/'Personal/escape.md','unsafe')

    def test_no_cloud_permission_no_context_or_writer(self):
        m.jwrite(m.ROOT/'.state/config.json',{'enabled':True,'model_processing_allowed':False})
        self.assertEqual(m.hook('UserPromptSubmit',{**self.p,'prompt':self.text}),{})
        self.assertEqual(m.hook('Stop',self.p),{})
        self.assertEqual(len(list((m.ROOT/'Raw').glob('*.jsonl'))),1)

    def test_oversized_delta_is_chunked_without_losing_tail(self):
        text='甲'*2500+'最后的长期偏好'
        self.raw.write_text(json.dumps({'type':'user','message':{'role':'user','content':text}})+'\n')
        m.jwrite(m.ROOT/'.state/config.json',{'enabled':True,'model_processing_allowed':True,'max_delta_chars':1000})
        m.hook('UserPromptSubmit',{**self.p,'prompt':text})
        self.assertFalse(m.hook('Stop',self.p)['continue'])
        job=json.loads(next((m.ROOT/'.state/jobs').glob('*.json')).read_text())
        self.assertEqual(''.join(x['text'] for x in job['messages']+[m.load_chunk(r) for r in job['remaining_refs']]),text)
        self.assertLessEqual(sum(len(x['text']) for x in job['messages']),1000)
        m.apply(job['id'],{'entities':[]})
        refs=m.jread(m.statepath(self.p['session_id']),{})['backlog']
        self.assertIn('最后的长期偏好',json.dumps([m.load_chunk(r) for r in refs],ensure_ascii=False))

    def test_real_workbuddy_transcript_format(self):
        rows = [
            {'type':'message','role':'user','content':[{'type':'input_text','text':'<system-reminder>Never store me</system-reminder><user_query>我喜欢茶</user_query>'}]},
            {'type':'message','role':'assistant','content':[{'type':'output_text','text':'建议下午喝茶'}]},
            {'type':'message','role':'user','providerData':{'isMeta':True},'content':[{'type':'input_text','text':'Stop hook feedback: internal'}]},
            {'type':'function_call_result','output':'tool data must not become a user fact'}]
        self.assertEqual(m.dialogue('\n'.join(json.dumps(x) for x in rows)),[
            {'role':'user','text':'我喜欢茶'}, {'role':'assistant','text':'建议下午喝茶'}])

    def test_internal_prompt_never_rearms_loop_guard(self):
        self.request()
        before=m.jread(m.statepath(self.p['session_id']),{})['generation']
        self.assertEqual(m.hook('UserPromptSubmit',{**self.p,'prompt':'Stop hook feedback:\n[jjaitech-memory] internal'}),{})
        self.assertEqual(m.jread(m.statepath(self.p['session_id']),{})['generation'],before)
        self.assertEqual(m.hook('Stop',self.p),{})

    def test_next_round_updates_same_entity(self):
        _,job=self.request();m.apply(job,self.plan())
        m.hook('Stop',{**self.p,'stop_hook_active':True})
        m.hook('UserPromptSubmit',{**self.p,'prompt':'林青现在也喜欢绿茶'})
        self.raw.write_text(self.raw.read_text()+json.dumps({'type':'user','message':{'role':'user','content':'林青现在也喜欢绿茶'}})+'\n')
        m.hook('Stop',self.p)
        jobs=[json.loads(p.read_text()) for p in (m.ROOT/'.state/jobs').glob('*.json')]
        pending=next(j for j in jobs if not j['done'])
        m.apply(pending['id'],{'entities':[{'category':'Personal','domain':'Personal','name':'林青','facts':[{'text':'也喜欢绿茶','kind':'reported','evidence':'林青现在也喜欢绿茶'}]}]})
        pages=list((m.ROOT/'Personal').glob('*.md'))
        self.assertEqual(len(pages),1)
        self.assertIn('不喝咖啡',pages[0].read_text())
        self.assertIn('也喜欢绿茶',pages[0].read_text())

if __name__ == '__main__':
    unittest.main(verbosity=2)
