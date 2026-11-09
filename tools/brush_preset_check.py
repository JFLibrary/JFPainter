"""Brush Factory / Dynamic Draw preset import, flow, undo and malformed-input checks.
Builds JFPainter with Cargo first (--no-build: the last build); the parser's unit tests compile
src/tools/brushes/presets.rs with the jflib sources Cargo downloaded for this build."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import jfp


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--out', default='build/checks')
    parser.add_argument('--target', choices=['win', 'linux', 'both'], default='both')
    parser.add_argument('--original-plugin', type=Path, help='Optional unmodified Dynamic Draw v4 DLL; exports fixtures with its own types using Windows .NET')
    parser.add_argument('--no-build', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    targets = jfp.targets(args.target)
    if not args.no_build:
        jfp.build(targets)
    out = Path(args.out).resolve()
    cases = out / 'brush-preset-check'
    cases.mkdir(parents=True, exist_ok=True)
    harness = cases / 'parser.rs'
    # jflib::agent_core::json and jflib::base::xml, the two modules presets.rs uses, from Cargo's sources
    meta = json.loads(subprocess.run(['cargo', 'metadata', '--format-version', '1', '--offline', '--locked'],
                                     capture_output=True, check=True).stdout)
    src = {p['name']: Path(next(t['src_path'] for t in p['targets'] if 'lib' in t['kind'])).parent
           for p in meta['packages'] if p['name'] in ('jflib-agent-core', 'jflib-base')}
    harness.write_text('extern crate alloc;\nextern crate self as jflib;\n' + ''.join(
        f'pub mod {outer} {{ #[path="{(src[crate] / file).as_posix()}"] pub mod {name}; }}\n' for outer, crate, name, file in [
            ('agent_core', 'jflib-agent-core', 'json', 'json.rs'), ('base', 'jflib-base', 'xml', 'xml.rs')])
        + f'#[path="{(ROOT / "src/tools/brushes/presets.rs").as_posix()}"] pub mod presets;\n', encoding='utf-8')
    exe = cases / ('parser-tests.exe' if os.name == 'nt' else 'parser-tests')
    subprocess.run(['rustc', '--edition=2024', '--test', str(harness), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    tip = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 8, 8, 8, 6, 0, 0, 0))
    tip += chunk(b'IDAT', zlib.compress((b'\0' + bytes([0, 0, 0, 255]) * 8) * 8)) + chunk(b'IEND', b'')
    (cases / 'tip.png').write_bytes(tip)
    preset = dict(BrushSize=8, BrushDensity=2, AutomaticBrushDensity=False,
                  BrushColor=-65536, BrushFlow=128, BrushImagePath='tip.png')
    (cases / 'presets.json').write_text(json.dumps(dict(Version='4.0', CustomBrushes={
        'Red ink': preset, 'Capped': dict(preset, BrushOpacity=77),
        'Builtin': dict(preset, BrushImagePath='Circle Hard', BrushFlow=255),
        'Blocked': dict(preset, RandMaxSize=10)})), encoding='utf-8')
    xml_fields = ''.join(f'<{k}>{str(v).lower() if isinstance(v, bool) else v}</{k}>' for k, v in preset.items())
    (cases / 'presets.xml').write_text('<DynamicDrawSettings><CustomBrushes xmlns:a="http://schemas.microsoft.com/2003/10/Serialization/Arrays"><a:KeyValueOfstringBrushSettings><a:Key>Red ink</a:Key><a:Value>' + xml_fields + '</a:Value></a:KeyValueOfstringBrushSettings></CustomBrushes></DynamicDrawSettings>', encoding='utf-8')
    variants = [('json', 'Red ink'), ('xml', 'Red ink'), ('json', 'Capped'), ('json', 'Blocked'), ('json', 'Builtin')]
    if args.original_plugin:
        exporter = cases / 'exporter'
        subprocess.run(['dotnet', 'build', 'pdn-host/tests/PresetsFixture.csproj', '-c', 'Release', '-o', str(exporter), '--nologo', '-v:q'], check=True)
        subprocess.run(['dotnet', str(exporter / 'PresetsFixture.dll'), str(args.original_plugin.resolve()), str(cases)], env=dict(os.environ, DOTNET_ReadyToRun='0'), check=True)
        variants += [('original.json', 'Original export'), ('original.xml', 'Original export')]
    results = []
    for target in targets:
        for extension, selected in variants:
            name = f'{target}-{extension}-{selected.replace(" ", "-")}'
            script = cases / f'{name}.uis'
            script_text = '''size 1280 800
theme light
expect #9918 text ""
key b
click 340,248
cmd 901 6553700
expect #9900 text "FFFF7F7F"
key ctrl+z
cmd 901 6553700
expect #9900 text "FFFFFFFF"
key ctrl+y
cmd 901 6553700
expect #9900 text "FFFF7F7F"
key ctrl+z
drag 340,248 352,248
cmd 901 6553706
expect #9900 text "FFFF3F3F"
'''
            if selected == 'Capped':
                script_text = script_text.replace('FFFF7F7F', 'FFFFB2B2').replace('FFFF3F3F', 'FFFFB2B2')
            elif selected == 'Builtin':
                # The unmodified Circle Hard PNG has alpha 254 at its center.
                script_text = script_text.replace('FFFF7F7F', 'FFFF0101').replace('FFFF3F3F', 'FFFF0000')
                script_text += '''click #0x90200
click #0x90218
expect window 24803 open
click #0x9021b
expect window 24803 closed
click #0x90209
'''
            elif selected == 'Blocked':
                script_text = '''size 1280 800
expect #9918 text "Blocked: Diese aktiven Einstellungen werden noch nicht unterstützt: RandMaxSize"
expect #9932 value 200
expect #9933 text "FF000000"
expect #9935 value 1
'''
            script.write_text(script_text, encoding='utf-8')
            config = cases / f'config-{name}'
            (config / 'settings.ini').unlink(missing_ok=True)
            relative = lambda p: p.relative_to(ROOT).as_posix()
            run = jfp.run_exe(target, jfp.exe(target), ['--config', relative(config), '--script', relative(script),
                '--verify-dirty', '--brush-presets', relative(cases / (extension if extension.startswith('original.') else f'presets.{extension}')), '--brush-preset', selected], timeout=120)
            (cases / f'{name}.log').write_text(run.stdout + run.stderr, encoding='utf-8')
            assert run.returncode == 0, run.stdout + run.stderr
            results.append(dict(target=target, format=extension, preset=selected, passed=True))
    (cases / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(f'{len(results)} preset editor checks passed')


if __name__ == '__main__':
    main()
