import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import test_memory as base
m=base.m

spec=importlib.util.spec_from_file_location('portable',Path(__file__).parents[1]/'scripts/portable.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


class ResilienceTests(unittest.TestCase):
    setUp=base.MemoryTests.setUp
    tearDown=base.MemoryTests.tearDown
    request=base.MemoryTests.request
    plan=base.MemoryTests.plan

    def ingest(self):
        _,job=self.request();m.apply(job,self.plan());return job

    def test_desktop_broker_existing_directory_compatibility(self):
        original=Path.mkdir
        def desktop_mkdir(path, mode=0o777, parents=False, exist_ok=False):
            # Observed 5.5.6 shim forwards recursive=parents, but omits exist_ok.
            if path.exists() and not parents:
                raise PermissionError('EEXIST: desktop broker mkdir')
            return original(path,mode=mode,parents=parents,exist_ok=exist_ok)
        with patch.object(Path,'mkdir',desktop_mkdir):
            with m.lock():pass

    def test_test_label_cannot_break_portable_fact_limit(self):
        _,job=self.request()
        cfg=m.jread(m.ROOT/'.state/config.json',{});cfg['synthetic_test_vault']=True
        m.jwrite(m.ROOT/'.state/config.json',cfg)
        plan=self.plan();plan['entities'][0]['facts'][0]['text']='甲'*2000
        with self.assertRaises(ValueError):m.apply(job,plan)
        with m.dbopen() as db:self.assertEqual(db.execute('SELECT count(*) FROM facts').fetchone()[0],0)

    def test_legacy_schema_migration_preserves_facts_and_backup(self):
        self.ingest()
        with m.dbopen() as db:
            before=[tuple(r) for r in db.execute('SELECT * FROM facts ORDER BY id')]
            for table in ('applied_jobs','rendered_files','render_pending'):
                db.execute('DROP TABLE '+table)
            db.execute('PRAGMA user_version=0')
        with m.lock():pass
        with m.dbopen() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],2)
            self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM facts ORDER BY id')],before)
        backup=next((m.ROOT/'.state/backups').glob('before-schema-0-*.sqlite3'))
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT * FROM facts ORDER BY id').fetchall(),before)

    def test_disable_rejects_already_pending_apply(self):
        _,job=self.request()
        cfg=m.jread(m.ROOT/'.state/config.json',{});cfg['enabled']=False;m.jwrite(m.ROOT/'.state/config.json',cfg)
        with self.assertRaises(ValueError):m.apply(job,self.plan())
        self.assertEqual(list((m.ROOT/'Personal').glob('*.md')),[])

    def test_revoke_model_consent_rejects_pending_apply(self):
        _,job=self.request()
        cfg=m.jread(m.ROOT/'.state/config.json',{});cfg['model_processing_allowed']=False;m.jwrite(m.ROOT/'.state/config.json',cfg)
        with self.assertRaises(ValueError):m.apply(job,self.plan())

    def test_late_old_apply_does_not_consume_new_user_turn(self):
        _,old=self.request()
        text='林青现在长期也喝绿茶'
        self.raw.write_text(self.raw.read_text()+json.dumps({'type':'user','message':{'role':'user','content':text}})+'\n')
        m.hook('UserPromptSubmit',{**self.p,'prompt':text})
        m.apply(old,self.plan())
        m.hook('Stop',self.p)
        state=m.jread(m.statepath(self.p['session_id']),{})
        newer=m.jread(m.ROOT/'.state/jobs'/(state['pending_job']+'.json'),{})
        self.assertIn(text,json.dumps(newer['messages'],ensure_ascii=False))

    def test_pending_job_retries_same_id_without_duplicate(self):
        _,job=self.request()
        m.hook('UserPromptSubmit',{**self.p,'prompt':'请继续'})
        response=m.hook('Stop',self.p)
        self.assertFalse(response['continue'])
        self.assertEqual(len(list((m.ROOT/'.state/jobs').glob('*.json'))),1)
        self.assertIn(job,response['reason'])

    def test_model_maintenance_answer_is_not_new_evidence(self):
        rows=[{'role':'user','content':'我的实际陈述'},
              {'role':'user','providerData':{'isMeta':True},'content':'Stop hook feedback: memory'},
              {'role':'assistant','content':'已记录一些建议'},
              {'role':'user','content':'新的实际陈述'},
              {'role':'assistant','content':'正常建议'}]
        parsed=m.dialogue('\n'.join(json.dumps(x) for x in rows))
        self.assertEqual([x['text'] for x in parsed],['我的实际陈述','新的实际陈述','正常建议'])

    def test_interrupted_render_has_atomic_db_commit_and_recovery(self):
        _,job=self.request()
        with patch.object(m,'render',side_effect=OSError('simulated crash')):
            with self.assertRaises(OSError):m.apply(job,self.plan())
        with m.dbopen() as db:
            before=db.execute('SELECT COUNT(*) FROM facts').fetchone()[0]
            self.assertEqual(db.execute('SELECT COUNT(*) FROM applied_jobs').fetchone()[0],1)
        self.assertIn('32000',json.dumps(m.search('星桥实验公司'),ensure_ascii=False))
        self.assertEqual(m.apply(job,self.plan())['status'],'already_applied')
        with m.dbopen() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM facts').fetchone()[0],before)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM render_pending').fetchone()[0],0)

    def test_manual_changes_survive_rebuild(self):
        self.ingest()
        page=next((m.ROOT/'Personal').glob('*.md'))
        page.write_text(page.read_text()+'\n人工补充：不要覆盖。')
        with m.dbopen() as db:m.render(db)
        self.assertIn('不要覆盖',page.read_text())
        self.assertGreater(m.health()['manual_page_conflicts'],0)

    def test_unowned_index_is_preserved(self):
        (m.ROOT/'index.md').write_text('员工自己的目录')
        self.ingest()
        self.assertEqual((m.ROOT/'index.md').read_text(),'员工自己的目录')

    def test_new_fact_after_long_page_is_recalled(self):
        self.ingest()
        with m.dbopen() as db:
            eid=db.execute("SELECT id FROM entities WHERE category='Customers'").fetchone()[0]
            for i in range(40):
                db.execute('INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?)',(m.digest(str(i)),eid,'旧资料'*100,'reported','2026-09-15T10:00:00+08:00','older','证据','[]','older'))
            db.execute('INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?)',(m.digest('newest'),eid,'最新报价人民币88888元','reported','2026-09-18T10:00:00+08:00','newest','证据','[]','newest'))
            m.render(db)
        self.assertIn('88888',json.dumps(m.search('星桥实验公司'),ensure_ascii=False))

    def test_recency_uses_timezones_not_string_sort(self):
        self.ingest()
        with m.dbopen() as db:
            eid=db.execute("SELECT id FROM entities WHERE category='Customers'").fetchone()[0]
            for marker,date in [('older-local-clock','2026-12-01T10:00:00+08:00'),('newer-actual-time','2026-12-01T07:00:00-08:00')]:
                db.execute('INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?)',(m.digest(marker),eid,marker,'reported',date,'source','quote','[]','source'))
            m.reindex_entity(db,eid)
        answer=m.search('星桥实验公司')[0]['text']
        self.assertLess(answer.index('newer-actual-time'),answer.index('older-local-clock'))

    def test_backup_restores_unmanaged_attachments_and_shared_material(self):
        self.ingest()
        (m.ROOT/'Work/example.eml').write_bytes(b'From: example@example.test\r\n\r\nEvidence body')
        (m.ROOT/'Share/manual-note.md').write_text('人工选择的工作资料')
        bundle=p.export(m)['path'];old=m.ROOT
        m.ROOT=Path(self.tmp.name)/'restored';m.init()
        try:
            p.restore(m,bundle)
            self.assertIn(b'Evidence body',(m.ROOT/'Work/example.eml').read_bytes())
            self.assertEqual((m.ROOT/'Share/manual-note.md').read_text(),'人工选择的工作资料')
        finally:m.ROOT=old

    def test_share_export_has_exact_local_review_file(self):
        self.ingest();result=p.export(m,[x['id'] for x in p.preview(m)])
        review=Path(result['review_path']).read_text()
        self.assertIn('客户接受报价',review)
        self.assertNotIn('不喝咖啡',review)

    def test_database_connections_close_on_context_exit(self):
        with m.dbopen() as db:db.execute('SELECT 1')
        with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')

    def test_production_test_vault_facts_are_marked_by_code(self):
        cfg=m.jread(m.ROOT/'.state/config.json',{});cfg['synthetic_test_vault']=True;m.jwrite(m.ROOT/'.state/config.json',cfg)
        self.ingest()
        with m.dbopen() as db:
            self.assertTrue(all(r[0].startswith('【测试数据】') for r in db.execute('SELECT text FROM facts')))

    def test_corrupt_pending_chunk_rejected(self):
        ref=m.queue_chunks([{'role':'user','text':'durable fact'}],1000)[0]
        m.jwrite(m.ROOT/'.state/chunks'/(ref['ref']+'.json'),{'role':'user','text':'changed'})
        with self.assertRaises(ValueError):m.load_chunk(ref)

    def test_repeated_failure_is_bounded_across_turns(self):
        self.request()
        for n in range(3):
            m.hook('UserPromptSubmit',{**self.p,'prompt':'retry '+str(n)})
            result=m.hook('Stop',self.p)
        self.assertNotIn('continue',result)
        self.assertIn('停止自动重试',result['systemMessage'])

    def test_share_path_cannot_be_generated_via_database(self):
        with m.dbopen() as db:
            with self.assertRaises(ValueError):m.write_generated(db,'Share/secret.md','do not write')
        self.assertFalse((m.ROOT/'Share/secret.md').exists())

    def test_transcript_rewrite_with_larger_file_is_not_skipped(self):
        self.ingest()
        text='改正：林青长期不喝酒。'+'补充'*300
        self.raw.write_text(json.dumps({'role':'user','content':text},ensure_ascii=False)+'\n')
        m.hook('UserPromptSubmit',{**self.p,'prompt':text})
        m.hook('Stop',self.p)
        state=m.jread(m.statepath(self.p['session_id']),{})
        job=m.jread(m.ROOT/'.state/jobs'/(state['pending_job']+'.json'),{})
        self.assertIn('不喝酒',json.dumps(job['messages'],ensure_ascii=False))

    def test_partial_jsonl_record_is_not_consumed(self):
        partial=json.dumps({'role':'assistant','content':'一条尚未刷完的正常建议'},ensure_ascii=False)
        self.raw.write_text(self.raw.read_text()+partial[:12])
        _,job=self.request()
        j=m.jread(m.ROOT/'.state/jobs'/(job+'.json'),{})
        self.assertLess(j['end_bytes'],self.raw.stat().st_size)

    def test_future_schema_refused(self):
        with m.dbopen() as db:db.execute('PRAGMA user_version=99')
        with self.assertRaises(ValueError):m.init()

    def test_markdown_embeds_are_escaped(self):
        escaped=m.md('![tracker](https://example.test/a)<img src="remote">')
        self.assertNotIn('![',escaped)
        self.assertNotIn('<img',escaped)

    def test_daily_database_snapshot_exists(self):
        self.ingest()
        backup=next((m.ROOT/'.state/backups').glob('*.sqlite3'))
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM facts').fetchone()[0],0)

    def test_full_export_restore_to_new_machine_path(self):
        self.ingest();old=m.ROOT
        bundle=p.export(m)['path']
        with m.dbopen() as db:expected=db.execute('SELECT COUNT(*) FROM facts').fetchone()[0]
        m.ROOT=Path(self.tmp.name)/'另一台电脑 空格/wiki';m.init()
        try:
            result=p.restore(m,bundle)
            self.assertEqual(result['restored_facts'],expected)
            self.assertIn('32000',json.dumps(m.search('星桥实验公司'),ensure_ascii=False))
            self.assertFalse(m.jread(m.ROOT/'.state/config.json',{})['enabled'])
            self.assertFalse(m.jread(m.ROOT/'.state/config.json',{})['model_processing_allowed'])
            self.assertEqual(len(list((m.ROOT/'Raw').glob('*.jsonl'))),1)
        finally:m.ROOT=old

    def test_restore_never_overwrites_nonempty_vault(self):
        self.ingest();bundle=p.export(m)['path']
        with self.assertRaises(ValueError):p.restore(m,bundle)

    def test_share_excludes_personal_raw_and_user_quotes(self):
        self.ingest()
        selection=p.preview(m)
        self.assertTrue(selection)
        bundle=p.export(m,[e['id'] for e in selection])['path']
        manifest,data=p.read_bundle(bundle)
        self.assertEqual(set(data),{'entities.jsonl','facts.jsonl'})
        self.assertNotIn('Personal',data['entities.jsonl'].decode())
        self.assertNotIn('不喝咖啡',b''.join(data.values()).decode())
        self.assertNotIn(self.p['session_id'],data['facts.jsonl'].decode())

    def test_share_requires_selected_work_entities(self):
        self.ingest()
        with m.dbopen() as db:personal=db.execute("SELECT id FROM entities WHERE domain='Personal'").fetchone()[0]
        with self.assertRaises(ValueError):p.export(m,[personal])
        with self.assertRaises(ValueError):p.export(m,[])

    def test_share_import_does_not_merge_or_enable_search(self):
        self.ingest();bundle=p.export(m,[e['id'] for e in p.preview(m)])['path']
        with m.dbopen() as db:before=db.execute('SELECT COUNT(*) FROM facts').fetchone()[0]
        result=p.share_import(m,bundle)
        self.assertFalse(result['search_enabled'])
        with m.dbopen() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM facts').fetchone()[0],before)

    def test_private_archive_cannot_be_shared_import(self):
        self.ingest()
        with self.assertRaises(ValueError):p.share_import(m,p.export(m)['path'])

    def test_zip_traversal_and_future_schema_rejected(self):
        archive=Path(self.tmp.name)/'hostile.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('../escape','bad');z.writestr('manifest.json','{}')
        with self.assertRaises(ValueError):p.read_bundle(archive)
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('manifest.json',json.dumps({'schema':'future/99','kind':'private-backup','files':{}}))
        with self.assertRaises(ValueError):p.read_bundle(archive)

    def test_tampered_bundle_checksum_rejected(self):
        self.ingest();archive=p.export(m)['path'];manifest,data=p.read_bundle(archive)
        bad=Path(self.tmp.name)/'tampered.zip'
        with zipfile.ZipFile(bad,'w') as z:
            z.writestr('manifest.json',json.dumps(manifest))
            for name,body in data.items():z.writestr(name,body+b'corrupt' if name=='facts.jsonl' else body)
        with self.assertRaises(ValueError):p.read_bundle(bad)

    def test_two_processes_serialize_writes(self):
        script=Path(__file__).parents[1]/'scripts/memory.py'
        env=dict(os.environ,JJAITECH_WIKI_ROOT=str(m.ROOT))
        processes=[subprocess.Popen([sys.executable,str(script),'init'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(4)]
        for proc in processes:
            _,error=proc.communicate(timeout=20)
            self.assertEqual(proc.returncode,0,error.decode())
        self.assertEqual(m.health()['integrity'],'ok')

    def test_two_processes_apply_without_lost_facts(self):
        jobs=[]
        for sid in ['parallel-a','parallel-b']:
            payload={**self.p,'session_id':sid}
            m.hook('UserPromptSubmit',{**payload,'prompt':self.text})
            m.hook('Stop',payload)
            jobs.append(m.jread(m.statepath(sid),{})['pending_job'])
        script=Path(__file__).parents[1]/'scripts/memory.py'
        env=dict(os.environ,JJAITECH_WIKI_ROOT=str(m.ROOT))
        workers=[subprocess.Popen([sys.executable,str(script),'apply',job],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for job in jobs]
        for worker in workers:worker.stdin.write(json.dumps(self.plan()).encode());worker.stdin.close();worker.stdin=None
        for worker in workers:
            _,error=worker.communicate(timeout=20);self.assertEqual(worker.returncode,0,error.decode())
        with m.dbopen() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM entities').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM facts').fetchone()[0],6)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM applied_jobs').fetchone()[0],2)

if __name__=='__main__':unittest.main(verbosity=2)
