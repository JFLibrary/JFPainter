#!/usr/bin/env python3
"""pdn_host.py -- build JFPainter's host for original paint.net plugins (pdn-host/, Windows only)

    python tools/pdn_host.py                  into target/debug/pdn-host, where the program looks
    python tools/pdn_host.py --release        into target/release/pdn-host
    python tools/pdn_host.py --out build/pdn-host
                                              for the packages: PACKAGE's win_files takes it from
                                              there (cargo jflib package)

The host is our own .NET assembly, built against the paint.net installed on this machine
(PaintDotNetDir, else C:\\Program Files\\paint.net) with the .NET SDK (`dotnet`).  Its references
to paint.net are not copied, so nothing of paint.net is redistributed; a user needs paint.net,
not the SDK.  Without the SDK or paint.net there is no host: JFPainter then says so in its menu
Effekte > Paint.NET-Plugins, and the packages go without it.  pdn-host/README.md has the rest.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = ROOT / "pdn-host"
PROJECT = HOST / "PaintCraft.PdnHost.csproj"
# what the program needs (.dll alone on paint.net's own runtime; the other two let --pdn-dotnet
# start it on an installed .NET)
FILES = [PROJECT.stem + e for e in (".dll", ".runtimeconfig.json", ".deps.json")]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--release", action="store_true", help="into target/release/pdn-host")
    ap.add_argument("--out", help="into this folder instead")
    a = ap.parse_args()
    out = Path(a.out).resolve() if a.out else ROOT / "target" / ("release" if a.release else "debug") / "pdn-host"
    install = Path(os.environ.get("PaintDotNetDir") or Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "paint.net")
    if not shutil.which("dotnet"):
        sys.exit("pdn_host.py: no .NET SDK (dotnet) here: JFPainter goes without its plugin host")
    if not (install / "PaintDotNet.Effects.Core.dll").exists():
        sys.exit(f"pdn_host.py: no paint.net in {install} (set PaintDotNetDir): JFPainter goes without its plugin host")
    bin_dir = HOST / "bin" / "Release"
    r = subprocess.run(["dotnet", "build", str(PROJECT), "-c", "Release", "-o", str(bin_dir), f"-p:PaintDotNetDir={install}",
                        "--nologo", "-v:q"], stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        # another paint.net version may not compile: that costs the plugin host, not the app
        sys.exit(f"pdn_host.py: the host did not build against {install}:\n{r.stdout[-3000:]}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for f in FILES:
        shutil.copy2(bin_dir / f, out / f)
    print(f"pdn host against {install}: {out.relative_to(ROOT).as_posix() if out.is_relative_to(ROOT) else out}/ ({', '.join(FILES)})")


if __name__ == "__main__":
    main()
