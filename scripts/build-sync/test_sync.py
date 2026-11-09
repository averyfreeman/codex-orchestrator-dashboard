import unittest,tempfile,subprocess,json,os
from pathlib import Path

class SyncSafety(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.root=self.base/'build';self.root.mkdir();self.source=self.base/'source';self.source.mkdir()
  self.git(self.source,'init','-b','main');self.git(self.source,'config','user.name','Test');self.git(self.source,'config','user.email','test@example.invalid')
  (self.source/'file.txt').write_text('one\n');self.git(self.source,'add','.');self.git(self.source,'commit','-m','initial')
  self.remote=self.base/'remote.git';subprocess.run(['git','clone','--bare',str(self.source),str(self.remote)],capture_output=True,check=True)
  self.manifest=self.base/'manifest.json';self.entry={'id':'example/project','url':self.remote.as_uri(),'canonical':'projects/example/project','candidates':{'test':[]}}
  self.write()
 def tearDown(self):self.tmp.cleanup()
 def git(self,p,*a):return subprocess.run(['git','-C',str(p),*a],capture_output=True,text=True,check=True).stdout.strip()
 def write(self):self.manifest.write_text(json.dumps({'version':1,'repositories':[self.entry]}))
 def run_sync(self,apply=False):
  cmd=['python3',str(Path(__file__).with_name('build_sync.py')),'--manifest',str(self.manifest),'--root',str(self.root),'--host','test']+(['--apply'] if apply else [])
  return subprocess.run(cmd,capture_output=True,text=True)
 def test_default_is_read_only_and_apply_clones(self):
  r=self.run_sync();self.assertEqual(r.returncode,0,r.stderr);self.assertFalse((self.root/'projects').exists())
  r=self.run_sync(True);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((self.root/self.entry['canonical']/'file.txt').read_text(),'one\n')
 def test_dirty_checkout_is_preserved(self):
  self.assertEqual(self.run_sync(True).returncode,0);p=self.root/self.entry['canonical'];(p/'file.txt').write_text('uncommitted\n');(p/'untracked.txt').write_text('keep\n')
  (self.source/'file.txt').write_text('two\n');self.git(self.source,'commit','-am','second');self.git(self.source,'push',str(self.remote),'main')
  r=self.run_sync(True);self.assertIn('blocked-dirty',r.stdout);self.assertEqual((p/'file.txt').read_text(),'uncommitted\n');self.assertTrue((p/'untracked.txt').exists())
 def test_clean_checkout_fast_forwards(self):
  self.assertEqual(self.run_sync(True).returncode,0);(self.source/'file.txt').write_text('two\n');self.git(self.source,'commit','-am','second');self.git(self.source,'push',str(self.remote),'main')
  r=self.run_sync(True);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((self.root/self.entry['canonical']/'file.txt').read_text(),'two\n')
 def test_matching_existing_checkout_gets_alias(self):
  candidate=self.root/'old';subprocess.run(['git','clone',str(self.remote),str(candidate)],capture_output=True,check=True);self.entry['candidates']['test']=['old'];self.write()
  r=self.run_sync(True);self.assertEqual(r.returncode,0,r.stderr);self.assertTrue((self.root/self.entry['canonical']).is_symlink());self.assertEqual((self.root/self.entry['canonical']).resolve(),candidate.resolve())
 def test_path_traversal_is_rejected(self):
  self.entry['canonical']='../escaped';self.write();r=self.run_sync(True);self.assertNotEqual(r.returncode,0);self.assertFalse((self.base/'escaped').exists())
 def test_existing_nonrepository_is_not_overwritten(self):
  p=self.root/self.entry['canonical'];p.mkdir(parents=True);(p/'keep').write_text('keep');r=self.run_sync(True);self.assertIn('blocked-existing',r.stdout);self.assertEqual((p/'keep').read_text(),'keep')
 def test_divergence_is_not_reset(self):
  self.assertEqual(self.run_sync(True).returncode,0);p=self.root/self.entry['canonical'];self.git(p,'config','user.name','Test');self.git(p,'config','user.email','test@example.invalid');(p/'local').write_text('local');self.git(p,'add','.');self.git(p,'commit','-m','local');before=self.git(p,'rev-parse','HEAD')
  (self.source/'remote').write_text('remote');self.git(self.source,'add','.');self.git(self.source,'commit','-m','remote');self.git(self.source,'push',str(self.remote),'main')
  r=self.run_sync(True);self.assertIn('blocked-diverged',r.stdout);self.assertEqual(self.git(p,'rev-parse','HEAD'),before)

 def test_symlinked_parent_cannot_escape_build_root(self):
  outside=self.base/'outside';outside.mkdir();(self.root/'projects').symlink_to(outside)
  r=self.run_sync(True);self.assertIn('blocked-outside-root',r.stdout);self.assertFalse((outside/'example/project').exists())

 def test_ignored_local_file_is_not_overwritten_by_upstream(self):
  (self.source/'.gitignore').write_text('local.txt\n');self.git(self.source,'add','.gitignore');self.git(self.source,'commit','-m','ignore local');self.git(self.source,'push',str(self.remote),'main')
  self.assertEqual(self.run_sync(True).returncode,0);p=self.root/self.entry['canonical'];(p/'local.txt').write_text('private local\n')
  (self.source/'local.txt').write_text('upstream\n');self.git(self.source,'add','-f','local.txt');self.git(self.source,'commit','-m','track upstream');self.git(self.source,'push',str(self.remote),'main')
  self.run_sync(True);self.assertEqual((p/'local.txt').read_text(),'private local\n')
 def snapshot(self,source,dest):
  return subprocess.run(['python3',str(Path(__file__).with_name('snapshot_sources.py')),'--source',str(source),'--destination',str(dest),'--apply'],capture_output=True,text=True)
 def test_snapshot_preserves_authored_public_assets_and_excludes_git(self):
  src=self.base/'snapshot-src';src.mkdir();(src/'public').mkdir();(src/'public/logo.svg').write_text('<svg/>');(src/'.git').write_text('gitdir: elsewhere');dst=self.base/'snapshot-dst'
  r=self.snapshot(src,dst);self.assertEqual(r.returncode,0,r.stderr);self.assertTrue((dst/'public/logo.svg').exists());self.assertFalse((dst/'.git').exists())
 def test_snapshot_retains_replaced_versions(self):
  src=self.base/'snapshot-src';src.mkdir();(src/'note').write_text('original');dst=self.base/'snapshot-dst';self.assertEqual(self.snapshot(src,dst).returncode,0)
  (src/'note').write_text('updated!');self.assertEqual(self.snapshot(src,dst).returncode,0);self.assertEqual((dst/'note').read_text(),'updated!');old=list((dst/'.snapshot-versions').rglob('note'));self.assertTrue(old);self.assertEqual(old[0].read_text(),'original')

if __name__=='__main__':unittest.main()
