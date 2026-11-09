"""Small file-save regressions using ordinary files and real JFPainter binaries.

python tests/file_save_check.py [--target win|linux|both] [--out build/JFPainter-file-save] [--no-build]
No crash injection, fuzzing, links, or resource stress. Artifacts are retained in OUT.
From Windows the Linux program runs this script inside WSL (--linux-case), with its files in
Linux's /tmp (modes and case-sensitive names need a Linux file system); they are copied to OUT.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import jfp

SENTINEL = b'Existing temporary file from another save.\n'


def native_cases(platform, exe, base):
    base.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='files-', dir=base))
    results = []

    def run(args, label):
        p = jfp.run_exe(platform, exe, ['--no-plugins', *args], timeout=60, cwd=work,
                        env={'JFPainter_CONFIG_DIR': str(work / 'config')})
        (work / (label + '.log')).write_text(p.stdout + p.stderr, encoding='utf-8')
        return p.returncode

    target = work / 'saved.png'
    adjacent = work / 'saved.png.tmp~'
    adjacent.write_bytes(SENTINEL)
    code = run(['--shot', str(target), '--size', '400x300'], 'save')
    results.append(dict(test='save-valid-png', ok=code == 0 and target.is_file()
                        and target.read_bytes().startswith(b'\x89PNG'), exit=code))
    results.append(dict(test='preserve-existing-temp-file',
                        ok=adjacent.is_file() and adjacent.read_bytes() == SENTINEL))
    config = work / 'config'
    config.mkdir(exist_ok=True)
    settings = config / 'settings.ini'
    settings.write_text('[Review]\nkept=1\n', encoding='utf-8')
    settings_temp = config / 'settings.ini.tmp~'
    settings_temp.write_bytes(SENTINEL)
    if os.name != 'nt':
        settings.chmod(0o600)
    settings_script = work / 'settings.uis'
    settings_script.write_text('cmd 850\nexpect #5901 text "ok"\n', encoding='utf-8')
    code = run(['--script', str(settings_script), '--verify-dirty'], 'settings')
    results.append(dict(test='save-settings', ok=code == 0 and b'kept=1' in settings.read_bytes(), exit=code))
    results.append(dict(test='preserve-existing-settings-temp',
                        ok=settings_temp.is_file() and settings_temp.read_bytes() == SENTINEL))
    if os.name != 'nt':
        mode = stat.S_IMODE(settings.stat().st_mode)
        results.append(dict(test='preserve-private-settings-mode', ok=mode == 0o600, mode=oct(mode)))
    options_script = work / 'options.uis'
    options_script.write_text('expect #9901 value 1\nexpect #9918 text ""\n', encoding='utf-8')
    code = run(['--config', str(config), '--plugins', str(work / 'plugins'),
                '--settings-save-at', '0', '--crash-dir', str(work / 'reports'),
                '--script', str(options_script), '--verify-dirty'], 'options')
    results.append(dict(test='option-values-are-not-images', ok=code == 0, exit=code))
    if os.name != 'nt':
        target.chmod(0o600)
        code = run(['--shot', str(target), '--size', '400x300'], 'replace')
        mode = stat.S_IMODE(target.stat().st_mode)
        results.append(dict(test='preserve-private-mode', ok=code == 0 and mode == 0o600,
                            mode=oct(mode), exit=code))
        # Distinct valid names on a case-sensitive filesystem must open distinct images.
        fixture = ROOT / 'tests/fixtures/a1_rgba.png'
        for name in ['Case.png', 'case.png']:
            shutil.copyfile(fixture, work / name)
        script = work / 'case.uis'
        script.write_text('size 1000 700\nexpect #9901 value 1\ncmd 101\n'
                          'click #65548\nkey ctrl+a\ntype "case.png"\n'
                          'click button:"Öffnen"\nexpect #9901 value 2\n'
                          'expect #9911 text "case.png"\n', encoding='utf-8')
        code = run(['--open', str(work / 'Case.png'), '--script', str(script), '--verify-dirty'], 'case')
        results.append(dict(test='case-distinct-documents', ok=code == 0, exit=code))
    for result in results:
        result['artifacts'] = str(work)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--target', default='both', choices=['win', 'linux', 'both'])
    parser.add_argument('--out', default='build/JFPainter-file-save')
    parser.add_argument('--label', default='file-save-results')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--linux-case', metavar='EXE', help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = (ROOT / args.out).resolve()
    if args.linux_case:
        work = Path(tempfile.mkdtemp(prefix='jfgui-file-review-'))
        rows = native_cases('linux', Path(args.linux_case), work)
        saved = output / 'file-save-cases' / work.name
        shutil.copytree(work, saved)
        for row in rows:
            row['artifacts'] = str(saved / Path(row['artifacts']).name)
        print(json.dumps(rows))
        return 0
    targets = jfp.targets(args.target)
    if not args.no_build:
        jfp.build(targets)
    results = []
    for target in targets:
        if target == jfp.HOST:
            rows = native_cases(target, jfp.exe(target), output / 'file-save-cases')
        else:
            command = jfp.linux_command(['python3', 'tests/file_save_check.py', '--out', jfp.wsl_path(output),
                                         '--linux-case', jfp.wsl_path(jfp.exe('linux'))])
            proc = subprocess.run(command, capture_output=True, text=True, timeout=180)
            if proc.returncode:
                raise RuntimeError(proc.stdout + proc.stderr)
            rows = json.loads(proc.stdout)
        for row in rows:
            row['platform'] = target
        results += rows
    (output / (args.label + '.json')).write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    for row in results:
        print(('PASS' if row['ok'] else 'FAIL'), row)
    return int(any(not row['ok'] for row in results))


if __name__ == '__main__':
    sys.exit(main())
