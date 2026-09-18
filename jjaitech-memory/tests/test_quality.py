import json,unittest
import test_memory as base
m=base.m

class QualityTests(unittest.TestCase):
    setUp=base.MemoryTests.setUp
    tearDown=base.MemoryTests.tearDown
    request=base.MemoryTests.request
    plan=base.MemoryTests.plan

    def test_ordinary_preference_cannot_disappear_next_to_private_marker(self):
        self.text='我个人长期喜欢无糖菊花茶，私人备注编号PRIVATE-CANARY。客户报价五万元。'
        self.raw.write_text(json.dumps({'role':'user','content':self.text})+'\n')
        _,job=self.request()
        r=m.submit(job,{'entities':[]})
        self.assertEqual(r['status'],'invalid');self.assertIn('Ordinary preference omitted',r['error'])
        plan={'entities':[{'category':'Personal','domain':'Personal','name':'用户偏好','facts':[{'text':'喜欢无糖菊花茶','kind':'reported','evidence':'我个人长期喜欢无糖菊花茶'}]}]}
        self.assertEqual(m.submit(job,plan)['status'],'applied')
        r=m.quality.receipt(m.memory_module(),self.p['session_id'])
        self.assertTrue(r['raw_archived']);self.assertEqual(r['facts_in_last_job'],1)
        self.assertIn('PRIVATE-CANARY',next((m.ROOT/'Raw').glob('*.jsonl')).read_text())

    def test_question_example_and_explicit_optout_are_not_required_facts(self):
        for text in ['我长期喜欢茶吗？','例如我长期喜欢菊花茶。','我长期喜欢茶，但不要保存。']:
            self.assertEqual(m.quality.preference_clauses({'messages':[{'role':'user','text':text}]}),[])

    def test_post_writer_finishes_only_verified_current_job(self):
        _,job=self.request();m.apply(job,self.plan())
        p={**self.p,'tool_name':'DeferExecuteTool','tool_input':{'toolName':'mcp__jjaitech-memory__write_memory','params':{'job_id':job}}}
        result=m.hook('PostToolUse',p)
        self.assertNotIn('continue',result);self.assertIn('3条',result['systemMessage'])
        self.assertEqual(m.hook('PostToolUse',p),{})
        self.assertEqual(m.hook('PostToolUse',{**p,'session_id':'different-session'}),{})

    def test_invalid_first_submission_does_not_end_correction(self):
        _,job=self.request();m.submit(job,{'entities':[]})
        p={**self.p,'tool_name':'mcp__jjaitech-memory__write_memory','tool_input':{'job_id':job},'tool_response':{'status':'applied'}}
        self.assertEqual(m.hook('PostToolUse',p),{}) # ignore forged success response
        m.submit(job,{'entities':[]})
        result=m.hook('PostToolUse',p)
        self.assertNotIn('continue',result);self.assertIn('待复核',result['systemMessage'])
        self.assertEqual(m.quality.receipt(m.memory_module(),self.p['session_id'])['structured_status'],'needs_review')

    def test_old_completed_job_cannot_finish_new_turn(self):
        _,job=self.request();m.apply(job,self.plan())
        m.hook('UserPromptSubmit',{**self.p,'prompt':'新的工作'})
        self.assertEqual(m.hook('PostToolUse',{**self.p,'tool_name':'mcp__jjaitech-memory__write_memory','tool_input':{'job_id':job}}),{})

    def test_receipt_does_not_claim_archive_when_missing(self):
        r=m.quality.receipt(m.memory_module(),'missing')
        self.assertFalse(r['raw_archived']);self.assertEqual(r['facts_in_last_job'],0)

    def test_contact_identity_survives_role_change_without_cross_company_merge(self):
        self.text='甲公司陈澈负责采购，乙公司陈澈负责技术。'
        self.raw.write_text(json.dumps({'role':'user','content':self.text})+'\n');_,job=self.request()
        def ent(org,role):return {'category':'Contacts','domain':'Work','person_name':'陈澈','organization':org,'name':'陈澈'+role,'aliases':['陈澈'],'facts':[{'text':org+'陈澈负责'+role,'kind':'reported','evidence':org+'陈澈负责'+role}]}
        self.assertEqual(m.apply(job,{'entities':[ent('甲公司','采购'),ent('乙公司','技术')]})['facts'],2)
        self.text='甲公司陈澈负责财务。';self.raw.write_text(self.raw.read_text()+json.dumps({'role':'user','content':self.text})+'\n')
        m.hook('UserPromptSubmit',{**self.p,'prompt':self.text});m.hook('Stop',self.p)
        new=m.jread(m.statepath(self.p['session_id']),{})['pending_job'];m.apply(new,{'entities':[ent('甲公司','财务')]})
        with m.dbopen() as db:
            names=[r[0] for r in db.execute('SELECT name FROM entities ORDER BY name')]
            self.assertEqual(set(names),{'陈澈（甲公司）','陈澈（乙公司）'})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM facts').fetchone()[0],3)

    def test_legacy_contact_title_upgrades_without_moving_page_or_id(self):
        self.text='甲公司陈澈负责采购。';self.raw.write_text(json.dumps({'role':'user','content':self.text})+'\n');_,job=self.request()
        jp=m.ROOT/'.state/jobs'/(job+'.json');j=m.jread(jp,{});j['contract_version']=3;m.jwrite(jp,j)
        e={'category':'Contacts','domain':'Work','name':'陈澈（甲公司 采购）','facts':[{'text':self.text,'kind':'reported','evidence':self.text}]};m.apply(job,{'entities':[e]})
        with m.dbopen() as db:old=dict(db.execute('SELECT * FROM entities').fetchone())
        self.text='甲公司陈澈负责财务。';self.raw.write_text(self.raw.read_text()+json.dumps({'role':'user','content':self.text})+'\n');m.hook('UserPromptSubmit',{**self.p,'prompt':self.text});m.hook('Stop',self.p)
        new=m.jread(m.statepath(self.p['session_id']),{})['pending_job'];e.update(person_name='陈澈',organization='甲公司');e['facts']=[{'text':self.text,'kind':'reported','evidence':self.text}];m.apply(new,{'entities':[e]})
        with m.dbopen() as db:
            rows=db.execute('SELECT * FROM entities').fetchall();self.assertEqual(len(rows),1);updated=dict(rows[0])
        self.assertEqual(updated['id'],old['id']);self.assertEqual(updated['path'],old['path']);self.assertEqual(updated['name'],'陈澈（甲公司）')
