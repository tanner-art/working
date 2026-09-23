#!/usr/bin/env python3
"""Use the existing Git credential only for gh; never print or persist it."""
import os, subprocess, sys
r=subprocess.run(['/usr/bin/git','credential','fill'],input='protocol=https\nhost=github.com\n\n',capture_output=True,text=True,check=True)
values=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
env=os.environ.copy();env['GH_TOKEN']=values['password']
os.execve('/opt/homebrew/bin/gh',['gh',*sys.argv[1:]],env)
