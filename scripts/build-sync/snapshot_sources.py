#!/usr/bin/env python3
"""Copy a private source snapshot with rsync. Default is a dry run; never deletes."""
import argparse,subprocess,datetime
from pathlib import Path
EXCLUDES=['.git','node_modules/','.venv/','venv/','.build/','target/','dist/','/frontend/hugo-railway/public/','.next/','.gradle/','.gocache/','.uv-cache/','.cache/','__pycache__/','.pytest_cache/','.ruff_cache/','.local/','DerivedData/','Pods/','*.app/','/projects/','/vendor/','/scratch/','/worktrees/','/build-sync-audit/','/codex-fleet-sync/','$CODE_HOME/','.desktop-build/','.dsh-build/','.astro/','.DS_Store','.env*','auth.json','credentials.json','*.key','*.pem','*.p12','*.pfx','*.mobileprovision','*.gguf','*.safetensors','*.dmg','*.iso','*.wpress','*.tar.gz','*.zip']
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',default=str(Path.home()/'build')+'/');p.add_argument('--destination',required=True);p.add_argument('--ssh-command');p.add_argument('--apply',action='store_true');a=p.parse_args()
 cmd=['rsync','-rltp','--safe-links','--checksum','--protect-args','--chmod=Du=rwx,Dgo=,Fgo=','--itemize-changes','--stats','--backup','--backup-dir=.snapshot-versions/'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')]
 if not a.apply:cmd+=['--dry-run']
 if a.ssh_command:cmd+=['-e',a.ssh_command]
 for x in EXCLUDES:cmd+=['--exclude',x]
 cmd+=[a.source.rstrip('/')+'/',a.destination.rstrip('/')+'/']
 return subprocess.run(cmd).returncode
if __name__=='__main__':raise SystemExit(main())
