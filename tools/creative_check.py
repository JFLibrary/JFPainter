"""Bitmap-tip and real standalone G'MIC regression checks (download runtimes separately).
Builds JFPainter with Cargo first (--no-build: the last build). --gmic needs G'MIC-Qt 4.0.5
standalone in --gmic-runtime (default <out>/gmic-runtime): win/gmic-4.0.5-qt-win64/gmic_qt.exe,
for Linux the wrapper gmic-qt-linux."""
import argparse
import json
import os
from pathlib import Path
import sys
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import jfp

def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument('--out',default='build/checks'); ap.add_argument('--target',choices=['win','linux','both'],default='both'); ap.add_argument('--gmic',action='store_true'); ap.add_argument('--gmic-runtime',type=Path); ap.add_argument('--no-build',action='store_true'); args=ap.parse_args()
    os.chdir(ROOT); targets=jfp.targets(args.target)
    out=Path(args.out).resolve(); cases=out/'creative-check'; cases.mkdir(parents=True,exist_ok=True); results=[]
    runtime=(args.gmic_runtime or out/'gmic-runtime').resolve()
    programs={'win':runtime/'win/gmic-4.0.5-qt-win64/gmic_qt.exe','linux':runtime/'gmic-qt-linux'}
    missing=[str(programs[t]) for t in targets if args.gmic and not programs[t].exists()]
    if missing: raise SystemExit('creative_check: no G\'MIC-Qt standalone at '+', '.join(missing)+' (install it separately, see --help)')
    if not args.no_build: jfp.build(targets)
    def rel(p): return p.relative_to(ROOT).as_posix()
    def chunk(kind,data): return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    raw=(b'\0'+bytes([255,0,0,255])*4+bytes(16))*8
    (cases/'tip.png').write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',8,8,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))
    def run(target,name,script,extra=(),env=None):
        test=cases/f'{name}-{target}.uis'; test.write_text('size 1280 800\ntheme light\n'+script,encoding='utf-8')
        # This test owns this config file; don't carry a saved 180-degree tip
        # rotation into a later run of the same regression.
        config=cases/f'config-{name}-{target}'
        (config/'settings.ini').unlink(missing_ok=True)
        r=jfp.run_exe(target,jfp.exe(target),['--script',rel(test),'--verify-dirty','--config',rel(config),*extra],timeout=180,env=env)
        (cases/f'{name}-{target}.log').write_text(r.stdout+r.stderr,encoding='utf-8')
        assert r.returncode==0,name+': '+r.stdout+r.stderr
        results.append(dict(target=target,case=name,passed=True))
    for target in targets:
        run(target,'tip-undo-rotation', '''cmd 930 800
click 340,248
cmd 901 6553698
expect #9900 text "FF000000"
cmd 901 6553702
expect #9900 text "FFFFFFFF"
expect #9935 value 2
key ctrl+z
cmd 901 6553698
expect #9900 text "FFFFFFFF"
key ctrl+y
cmd 901 6553698
expect #9900 text "FF000000"
key ctrl+z
click #0x90200
click #0x90203
key ctrl+a
type "180"
key tab
click #0x90209
click 340,248
cmd 901 6553698
expect #9900 text "FFFFFFFF"
cmd 901 6553702
expect #9900 text "FF000000"
''',['--brush-tip',rel(cases/'tip.png')])
        if args.gmic:
            program=str(programs[target]) if target=='win' else jfp.wsl_path(programs[target])
            # jfp forwards env, not os.environ, to the Linux program under WSL
            qt={'QT_QPA_PLATFORM':'offscreen'}
            run(target,'gmic-invert-undo', '''cmd 445
sync 120000
expect #9918 text ""
cmd 901 0
expect #9900 text "FF000000"
expect #9935 value 2
key ctrl+z
cmd 901 0
expect #9900 text "FFFFFFFF"
key ctrl+y
cmd 901 0
expect #9900 text "FF000000"
''',['--gmic-qt',program,'--gmic-command','-split c -negative[0-2] -append c'],qt)
            run(target,'gmic-cancel', '''cmd 445
click #0x90120
sync 120000
expect #9905 value 0
expect #9935 value 1
cmd 901 0
expect #9900 text "FFFFFFFF"
''',['--gmic-qt',program],qt)
            run(target,'gmic-selection', '''cmd 750
drag 250,158 350,258
cmd 445
sync 120000
cmd 901 3276850
expect #9900 text "FF000000"
cmd 901 0
expect #9900 text "FFFFFFFF"
key ctrl+z
cmd 901 3276850
expect #9900 text "FFFFFFFF"
''',['--gmic-qt',program,'--gmic-command','-split c -negative[0-2] -append c'],qt)
            run(target,'gmic-layers', '''cmd 445
sync 120000
expect #9901 value 2
expect #9903 value 2
expect #9905 value 1
''',['--gmic-qt',program,'--gmic-command','-input [0]'],qt)
            run(target,'gmic-failure', '''cmd 445
sync 120000
expect #9905 value 0
expect #9935 value 1
cmd 901 0
expect #9900 text "FFFFFFFF"
''',['--gmic-qt','missing-jfpainter-gmic-executable'],qt)
    (cases/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8'); print(f'{len(results)} creative regression cases passed')
if __name__=='__main__': main()
