"""JFPainter security regressions against real binaries, using disposable files only.

python tests/security_check.py [--target win|linux|both] [--out build/JFPainter-security/after] [--label L] [--no-build]
The original vulnerable build is expected to fail; --label distinguishes its evidence.
From Windows the Linux program runs this script inside WSL (--linux-case), with its files in
Linux's /tmp: Linux permissions and symlinks need a Linux filesystem, not a Windows mount.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import jfp

SENTINEL = b'JFPainter SECURITY REVIEW: UNRELATED FILE MUST SURVIVE\n'


def native_cases(platform, exe, base):
    results = []
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='case-', dir=base) as directory:
        work = Path(directory)
        # No reference points outside the newly created test directory.
        assert work.resolve().is_relative_to(base.resolve())
        sentinel = work / 'unrelated.txt'
        sentinel.write_bytes(SENTINEL)
        target = work / 'screenshot.png'
        link = work / 'screenshot.png.tmp~'
        if os.name == 'nt':
            os.link(sentinel, link)
        else:
            link.symlink_to(sentinel)
        env = {'JFPainter_CONFIG_DIR': str(work / 'config')}
        run = jfp.run_exe(platform, exe, ['--no-plugins', '--shot', str(target), '--size', '1000x600'],
                          timeout=45, cwd=work, env=env)
        results.append({'test':'atomic-write-preexisting-link', 'ok': sentinel.read_bytes() == SENTINEL,
                        'exit':run.returncode,'sentinel_bytes':sentinel.stat().st_size})
        results.append({'test':'atomic-write-valid-output', 'ok':run.returncode==0 and target.is_file() and target.read_bytes().startswith(b'\x89PNG')})
        # A private existing image must not become readable by other users on save.
        if os.name != 'nt':
            private = work / 'private.png'
            private.write_bytes(SENTINEL)
            private.chmod(0o600)
            run = jfp.run_exe(platform, exe, ['--no-plugins', '--shot', str(private), '--size', '1000x600'],
                              timeout=45, cwd=work, env=env)
            mode = stat.S_IMODE(private.stat().st_mode)
            results.append({'test':'atomic-write-private-permissions','ok':run.returncode==0 and mode & 0o077 == 0,'mode':oct(mode)})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--target',default='both',choices=['win','linux','both'])
    parser.add_argument('--out',default='build/JFPainter-security/after')
    parser.add_argument('--label',default='regression')
    parser.add_argument('--no-build',action='store_true')
    parser.add_argument('--linux-case',metavar='EXE',help=argparse.SUPPRESS)
    args=parser.parse_args()
    output=(ROOT/args.out).resolve()
    if args.linux_case:
        with tempfile.TemporaryDirectory(prefix='JFPainter-security-') as directory:
            result=native_cases('linux',Path(args.linux_case),Path(directory))
        print(json.dumps(result))
        return 0
    targets=jfp.targets(args.target)
    if not args.no_build: jfp.build(targets)
    result=[]
    for target in targets:
        if target==jfp.HOST:
            rows=native_cases(target,jfp.exe(target),output/('security-cases-'+target))
        else:
            command=jfp.linux_command(['python3','tests/security_check.py','--out',jfp.wsl_path(output),
                                       '--linux-case',jfp.wsl_path(jfp.exe('linux'))])
            run=subprocess.run(command,capture_output=True,text=True,timeout=150)
            if run.returncode: raise RuntimeError(run.stdout+run.stderr)
            rows=json.loads(run.stdout)
        for row in rows: row['platform']=target
        result+=rows
    output.mkdir(parents=True,exist_ok=True)
    target=output/(args.label+'-security.json')
    target.write_bytes((json.dumps(result,indent=2)+'\n').encode())
    for row in result: print(('PASS' if row['ok'] else 'FAIL'),row)
    return int(any(not row['ok'] for row in result))


if __name__=='__main__': sys.exit(main())
