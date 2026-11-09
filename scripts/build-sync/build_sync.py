#!/usr/bin/env python3
"""Maintain a canonical Git workspace. Inspection is the default; writes require --apply."""
import argparse,concurrent.futures,json,os,re,subprocess,sys
from pathlib import Path

def git(path,*args,timeout=180):
 return subprocess.run(['git','-C',str(path),*args],capture_output=True,text=True,timeout=timeout,env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GIT_OPTIONAL_LOCKS':'0'})

def relative(value):
 p=Path(value)
 if p.is_absolute() or not p.parts or '..' in p.parts or str(p)=='.':raise ValueError('Unsafe relative path: '+value)
 return p

def normalized(url):
 if url.startswith('file://'):
  from urllib.parse import urlparse,unquote
  return str(Path(unquote(urlparse(url).path)).resolve()).removesuffix('.git')
 if url.startswith('/') :return str(Path(url).resolve()).removesuffix('.git')
 return url.removesuffix('.git').rstrip('/').replace('git@github.com:','https://github.com/').lower()

def matches(path,url):
 r=git(path,'config','--get-regexp',r'^remote\..*\.url$')
 return any(normalized(x.split(' ',1)[1])==normalized(url) for x in r.stdout.splitlines() if ' ' in x)

def inspect_remote(url):
 if url.startswith('-') or not (url.startswith(('https://','ssh://','git@','file://'))):raise ValueError('Unsupported remote URL')
 r=subprocess.run(['git','ls-remote','--symref',url,'HEAD'],capture_output=True,text=True,timeout=90,env={**os.environ,'GIT_TERMINAL_PROMPT':'0'})
 if r.returncode:raise RuntimeError('Cannot inspect remote: '+r.stderr[-200:])
 branch=None;sha=None
 for line in r.stdout.splitlines():
  if line.startswith('ref: refs/heads/'):branch=line.split('\t')[0][len('ref: refs/heads/'):]
  elif line.endswith('\tHEAD'):sha=line.split()[0]
 if not branch or not sha:raise RuntimeError('Remote has no default branch')
 return branch,sha

def sync(entry,root,host,apply):
 result={'id':entry['id'],'canonical':entry['canonical']}
 try:
  dest=root/relative(entry['canonical']);url=entry['url']
  if not dest.parent.resolve().is_relative_to(root.resolve()):result['action']='blocked-outside-root';return result
  branch,wanted=inspect_remote(url)
  if dest.exists() or dest.is_symlink():
   if not dest.exists() or not (dest/'.git').exists() or not matches(dest,url):result['action']='blocked-existing';return result
   if not dest.resolve().is_relative_to(root.resolve()):result['action']='blocked-outside-root';return result
   if git(dest,'status','--porcelain').stdout.strip():result['action']='blocked-dirty';return result
   current=git(dest,'rev-parse','HEAD').stdout.strip()
   if current==wanted:result.update(action='current',head=current);return result
   if git(dest,'branch','--show-current').stdout.strip()!=branch:result['action']='blocked-branch';return result
   result['action']='would-fast-forward'
   if apply:
    fetched=git(dest,'fetch','--no-tags',url,'refs/heads/'+branch)
    if fetched.returncode:raise RuntimeError(fetched.stderr[-200:])
    target=git(dest,'rev-parse','FETCH_HEAD').stdout.strip()
    if git(dest,'merge-base','--is-ancestor','HEAD',target).returncode:result['action']='blocked-diverged';return result
    merged=git(dest,'merge','--ff-only','--no-overwrite-ignore','FETCH_HEAD')
    if merged.returncode:raise RuntimeError(merged.stderr[-200:])
    result.update(action='fast-forwarded',head=git(dest,'rev-parse','HEAD').stdout.strip())
   return result
  # Only alias an existing clean checkout whose exact commit and remote identity match.
  for name in entry.get('candidates',{}).get(host,[]):
   p=root/relative(name)
   if not p.exists() or not p.resolve().is_relative_to(root.resolve()) or not (p/'.git').exists():continue
   if git(p,'rev-parse','HEAD').stdout.strip()==wanted and not git(p,'status','--porcelain').stdout.strip() and matches(p,url):
    result.update(action='would-alias',source=name,head=wanted)
    if apply:
     dest.parent.mkdir(parents=True,exist_ok=True);dest.symlink_to(os.path.relpath(p,dest.parent));result['action']='aliased'
    return result
  result['action']='would-clone'
  if apply:
   dest.parent.mkdir(parents=True,exist_ok=True)
   args=['git','clone','--filter=blob:none','--depth=1','--branch',branch]
   args+=['--no-single-branch'] if entry['canonical'].startswith('projects/') else ['--single-branch']
   r=subprocess.run(args+[url,str(dest)],capture_output=True,text=True,timeout=900,env={**os.environ,'GIT_TERMINAL_PROMPT':'0'})
   if r.returncode:raise RuntimeError('Clone failed; partial destination retained for inspection: '+r.stderr[-300:])
   result.update(action='cloned',head=git(dest,'rev-parse','HEAD').stdout.strip())
 except Exception as e:result.update(action='error',error=str(e))
 return result

def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--manifest',type=Path,required=True);a.add_argument('--root',type=Path,default=Path.home()/'build');a.add_argument('--host',required=True);a.add_argument('--apply',action='store_true');a.add_argument('--jobs',type=int,default=4);a.add_argument('--output',type=Path);args=a.parse_args()
 manifest=json.loads(args.manifest.read_text());entries=manifest['repositories'];paths=set()
 # Validate the entire plan before any mutation.
 for e in entries:
  p=str(relative(e['canonical']))
  if p in paths:raise ValueError('Duplicate canonical path: '+p)
  paths.add(p)
  for names in e.get('candidates',{}).values():
   for n in names:relative(n)
 results=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,min(args.jobs,8))) as pool:
  for r in pool.map(lambda e:sync(e,args.root,args.host,args.apply),entries):
   results.append(r);print(json.dumps(r),flush=True)
   if args.output:args.output.write_text(json.dumps(results,indent=2))
 return 1 if any(r['action']=='error' for r in results) else 0
if __name__=='__main__':sys.exit(main())
