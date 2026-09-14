#!/usr/bin/env python3
"""Install an explicit config as a user LaunchAgent. Defaults to dry-run polling."""
import argparse, pathlib, plistlib, subprocess, os, sys
p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--live',action='store_true');a=p.parse_args()
root=pathlib.Path(__file__).resolve().parent
config=pathlib.Path(a.config).resolve()
import json
c=json.loads(config.read_text());state=pathlib.Path(c['state']);state.mkdir(parents=True,exist_ok=True)
args=[sys.executable,str(root/'runner.py'),'--config',str(config)]
if not a.live: args.append('--dry-run')
label='life.threadline.runner';dest=pathlib.Path.home()/'Library/LaunchAgents'/f'{label}.plist'
if dest.exists(): raise SystemExit('Existing service preserved; explicitly unload and archive its plist before replacement')
data={'Label':label,'ProgramArguments':args,'WorkingDirectory':str(root.parent.parent),'EnvironmentVariables':{'PATH':c['path'],'HOME':str(pathlib.Path.home())},'RunAtLoad':True,'StartInterval':60,'ProcessType':'Background','StandardOutPath':str(state/'launchd.log'),'StandardErrorPath':str(state/'launchd-error.log')}
dest.write_bytes(plistlib.dumps(data))
subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(dest)],check=True)
print(dest)
