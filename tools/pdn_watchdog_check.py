"""A stalled original-API codec must exit when its editor heartbeat stops.
On Windows the defaults need nothing but the .NET SDK and paint.net: the host is built with
tools/pdn_host.py next to the program (--no-build: as it is), the fixture from
pdn-host/tests/Fixture.csproj. Under Wine run it inside Linux and name every path."""
import argparse
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import jfp


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--host', help='default: target/debug/pdn-host/JFPainter.PdnHost.dll')
    parser.add_argument('--fixture', help='default: built from pdn-host/tests/Fixture.csproj')
    parser.add_argument('--paintnet', help='default: PAINTDOTNET_DIR or %%ProgramFiles%%/paint.net')
    parser.add_argument('--out', default='build/checks/watchdog-check')
    parser.add_argument('--wine', help='Wine executable on Linux; requires running this test inside Linux')
    parser.add_argument('--dotnet', default='dotnet')
    parser.add_argument('--prefix')
    parser.add_argument('--no-build', action='store_true')
    a = parser.parse_args()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if a.wine:
        if os.name == 'nt' or not (a.host and a.fixture and a.paintnet):
            parser.error('--wine runs inside Linux and needs --host, --fixture and --paintnet')
    else:
        a.paintnet = a.paintnet or os.environ.get('PAINTDOTNET_DIR') or os.path.join(os.environ.get('ProgramFiles', 'C:/Program Files'), 'paint.net')
        if not a.host:
            if not a.no_build:
                subprocess.run([sys.executable, str(ROOT / 'tools/pdn_host.py')], check=True)
            a.host = jfp.exe('win').parent / 'pdn-host/JFPainter.PdnHost.dll'
        if not a.fixture:
            subprocess.run(['dotnet', 'build', str(ROOT / 'pdn-host/tests/Fixture.csproj'), '-c', 'Release', '-o', str(out / 'fixture'),
                            '--nologo', '-v:q'], check=True, stdin=subprocess.DEVNULL)
            a.fixture = out / 'fixture/Fixture.dll'
    path = out / 'editor.watch'
    def mapped(path):
        path = str(Path(path).resolve())
        return 'Z:' + path.replace('/', '\\') if a.wine else path
    env = dict(os.environ, DOTNET_ReadyToRun='0', PAINTDOTNET_DIR=mapped(a.paintnet))
    if a.prefix:
        env['WINEPREFIX'] = a.prefix
    command = ([a.wine, a.dotnet] if a.wine else [a.dotnet]) + [mapped(a.host), mapped(a.fixture), 'FixtureFactory#0', '--decode', '--watchdog', mapped(path)]
    path.write_bytes(struct.pack('<Q', time.monotonic_ns()))
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    ready = threading.Event()
    errors = []
    def read_errors():
        for line in proc.stderr:
            errors.append(line)
            if b'fixture-waiting' in line:
                ready.set()
    reader = threading.Thread(target=read_errors, daemon=True)
    reader.start()
    try:
        proc.stdin.write(b'SLOW' + struct.pack('<4I', 0x54465354, 1, 1, 0xff123456))
        proc.stdin.close()
        proc.stdin = None
        # Updating in place also verifies compatibility with the host's sharing mode.
        started = time.monotonic()
        end = started + 30
        ready_at = None
        with path.open('r+b', buffering=0) as heartbeat:
            while time.monotonic() < end:
                heartbeat.seek(0)
                heartbeat.write(struct.pack('<Q', time.monotonic_ns()))
                assert proc.poll() is None, 'Host exited while the editor was alive: ' + b''.join(errors).decode(errors='replace')
                if ready.is_set() and ready_at is None:
                    ready_at = time.monotonic()
                    end = ready_at + 7
                time.sleep(.2)
        assert ready_at is not None, 'Codec never reached its blocking operation'
        stopped = time.monotonic()
        proc.wait(timeout=12)
        elapsed = time.monotonic() - stopped
        stdout = proc.stdout.read()
        reader.join(timeout=5)
        stderr = b''.join(errors)
        (out / 'stderr.log').write_bytes(stderr)
        assert proc.returncode == 2 and not stdout, (proc.returncode, stderr.decode(errors='replace'))
        assert elapsed < 8, f'Watchdog exit took {elapsed:.2f}s'
        print(f'Heartbeat kept codec alive; stopped editor caused clean exit in {elapsed:.2f}s, without output.')
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
