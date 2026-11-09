"""Bounded local regression checks of JFPainter's files and settings.

python tests/deeper_check.py files [--target win|linux|both] [--out build/JFPainter-deeper] [--no-build]
python tests/deeper_check.py settings [--target win|linux|both] [--out build/JFPainter-deeper] [--no-build]
files: four processes write the same PNG at once (--shot), five rounds; the result is always one
complete image, an unrelated *.tmp~ survives, no temporary file stays, a directory in the way is
kept.  From Windows the Linux program runs this script inside WSL (--linux-child) with its files
in Linux's /tmp; they are copied to OUT.  settings: tools/settings_check.py's malformed and env
checks, each in a fresh folder below OUT.  Artifacts are retained.
(In JFLib a third mode, codecs, ran the library's PDN/PNG decoder suites and mutations through
JFLib's codectest app and tools: they test the library and stay in JFLib.)
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import jfp


def save_results(out, name, rows):
    path = out / (name + '.json')
    path.write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')


def native_files(out, platform, exe):
    base = out / 'concurrent-files'
    base.mkdir(exist_ok=True)
    if platform == 'linux':
        work = Path(tempfile.mkdtemp(prefix='JFPainter-deeper-'))
        assert work.resolve().parent == Path(tempfile.gettempdir()).resolve()
    else:
        work = Path(tempfile.mkdtemp(prefix=platform + '-', dir=base))
        assert work.resolve().is_relative_to(out.resolve())
    rows = []

    def run(path, theme, tag):
        result = jfp.run_exe(platform, exe, ['--no-plugins', '--theme', theme, '--size', '400x300',
                                             '--shot', str(path)], timeout=30, cwd=work,
                             env={'JFPainter_CONFIG_DIR': str(work / ('config-' + tag))})
        (work / (tag + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
        return result.returncode

    hashes = set()
    for theme in ['light', 'dark']:
        p = work / (theme + '.png')
        code = run(p, theme, 'reference-' + theme)
        if code or not p.exists():
            raise RuntimeError('Could not generate reference PNG')
        hashes.add(hashlib.sha256(p.read_bytes()).hexdigest())
    target = work / 'shared.png'
    sentinel = work / 'shared.png.tmp~'
    sentinel.write_bytes(b'Independent file must survive.\n')
    with ThreadPoolExecutor(max_workers=4) as pool:
        for round_no in range(5):
            futures = [pool.submit(run, target, ['light', 'dark'][n % 2], f'round-{round_no}-{n}')
                       for n in range(4)]
            codes = [f.result() for f in futures]
            digest = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
            rows.append(dict(test='concurrent-complete-write', round=round_no, platform=platform,
                             ok=all(c == 0 for c in codes) and digest in hashes, exits=codes))
    rows.append(dict(test='concurrent-preserves-unrelated-temp', platform=platform,
                     ok=sentinel.read_bytes() == b'Independent file must survive.\n'))
    rows.append(dict(test='concurrent-cleans-owned-temp', platform=platform,
                     ok=not list(work.glob('shared.png.tmp-*'))))
    # A directory cannot be replaced by a PNG. No temporary file should remain.
    blocked = work / 'directory.png'
    blocked.mkdir()
    code = run(blocked, 'light', 'invalid-target')
    rows.append(dict(test='failed-replace-keeps-directory', platform=platform,
                     ok=code != 0 and blocked.is_dir() and not list(work.glob('directory.png.tmp-*')), exit=code))
    artifacts = work
    if platform == 'linux':
        artifacts = base / work.name
        shutil.copytree(work, artifacts)
    for row in rows:
        row['artifacts'] = str(artifacts)
    return rows


def files(out, targets, linux_child=None):
    if linux_child:
        print(json.dumps(native_files(out, 'linux', linux_child)))
        return 0
    rows = []
    for target in targets:
        if target == jfp.HOST:
            rows += native_files(out, target, jfp.exe(target))
            continue
        # Linux from Windows: this script inside WSL, so that its files are on a Linux file system
        command = jfp.linux_command(['python3', 'tests/deeper_check.py', 'files', '--out', jfp.wsl_path(out),
                                     '--linux-child', jfp.wsl_path(jfp.exe('linux'))])
        proc = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if proc.returncode:
            raise RuntimeError(proc.stdout + proc.stderr)
        rows += json.loads(proc.stdout)
    save_results(out, 'deeper-files', rows)
    for row in rows:
        print(('PASS' if row['ok'] else 'FAIL'), row)
    return int(any(not r['ok'] for r in rows))


def settings(out, targets):
    import settings_check as check
    os.environ.pop('JFPainter_CONFIG_DIR', None)  # (jfp.run_exe passes the environment on)
    rows = []
    for target in targets:
        for name in ['malformed', 'env']:
            runner = check.Runner(target, out)
            runner.base = Path(tempfile.mkdtemp(prefix=f'settings-{target}-{name}-', dir=out))
            assert runner.base.resolve().is_relative_to(out.resolve())
            # Both checker functions create children of this fresh directory.
            getattr(check, 't_' + name)(runner)
            rows.append(dict(target=target, test=name, failed=runner.fails,
                             artifacts=str(runner.base)))
            print(target, name, 'failures:', runner.fails, flush=True)
    save_results(out, 'deeper-settings', rows)
    return int(any(row['failed'] for row in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=['files', 'settings'])
    parser.add_argument('--target', default='both', choices=['win', 'linux', 'both'])
    parser.add_argument('--out', default='build/JFPainter-deeper')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--linux-child', metavar='EXE', help=argparse.SUPPRESS)
    args = parser.parse_args()
    out = (ROOT / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    targets = jfp.targets(args.target)
    if not (args.no_build or args.linux_child):
        jfp.build(targets)
    if args.mode == 'settings':
        return settings(out, targets)
    return files(out, targets, args.linux_child and Path(args.linux_child))


if __name__ == '__main__':
    sys.exit(main())
