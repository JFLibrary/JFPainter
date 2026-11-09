"""jfp.py -- what the check scripts in tools/ share: build JFPainter, find it, run it

    import jfp
    jfp.build(["win", "linux"])                  cargo build of the program (and --release)
    jfp.exe("win") / jfp.exe("linux")            target/debug/JFPainter.exe, target/x86_64-unknown-linux-gnu/debug/JFPainter
    jfp.run_exe("linux", jfp.exe("linux"), ["--script", "tests/files.uis"])
                                                 -> subprocess.CompletedProcess (text stdout / stderr)
    jfp.script_args(Path("tests/files.uis"))     the arguments of its "#!args" line

Targets are "win" and "linux".  The program runs in the repository's folder, as `cargo jflib test`
runs it; on Windows the Linux program runs through the WSL distribution JFLIB_WSL_DISTRO (default
Ubuntu-24.04), whose WSLg gives it a display; environment variables passed in `env` reach it
there too.  (In JFLib these were build_rs.py's run_exe and script_args, and the program was
<out>/<target>/PaintCraft[.exe].)
"""
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIPLE = {"win": "x86_64-pc-windows-msvc", "linux": "x86_64-unknown-linux-gnu"}
DISTRO = os.environ.get("JFLIB_WSL_DISTRO", "Ubuntu-24.04")
HOST = "win" if os.name == "nt" else "linux"


def targets(choice):
    """--target win|linux|both -> the list"""
    return ["win", "linux"] if choice == "both" else [choice]


def target_dir(target, release=False):
    """the folder Cargo puts the program of `target` into (the host's without --target)"""
    sub = [] if target == HOST else [TRIPLE[target]]
    return ROOT.joinpath("target", *sub, "release" if release else "debug")


def exe(target, release=False):
    return target_dir(target, release) / ("JFPainter.exe" if target == "win" else "JFPainter")


def build(targets, release=False):
    """cargo build of the program for each target; raises CalledProcessError when one fails"""
    for t in targets:
        cmd = ["cargo", "build", "--bin", "JFPainter"] + (["--release"] if release else []) + ([] if t == HOST else ["--target", TRIPLE[t]])
        subprocess.run(cmd, cwd=ROOT, check=True)


def wsl_path(p):
    """C:\\x\\y -> /mnt/c/x/y (a path inside WSL)"""
    p = str(Path(p).resolve())
    return "/mnt/" + p[0].lower() + p[2:].replace("\\", "/") if p[1:2] == ":" else p.replace("\\", "/")


def linux_command(args, env=None):
    """the command that runs `args` (a Linux program and its arguments) on Linux from this machine"""
    if HOST == "linux":
        return [str(a) for a in args]
    # every variable of env, also one Windows has with the same value: WSL takes none of them over
    extra = [f"{k}={v}" for k, v in (env or {}).items()]
    return ["wsl.exe", "-d", DISTRO, "--cd", wsl_path(ROOT), "-e", *(["env", *extra] if extra else []),
            wsl_path(args[0]) if Path(str(args[0])).is_absolute() else str(args[0]), *map(str, args[1:])]


def run_exe(target, program, args, timeout=600, env=None, cwd=None):
    """run the program of `target` with args in the repository's folder -> CompletedProcess"""
    full = dict(os.environ, **(env or {}))
    if target == "linux" and HOST != "linux":
        cmd = linux_command([program, *args], env)
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    return subprocess.run([str(program), *map(str, args)], cwd=cwd or ROOT, env=full, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def script_args(uis):
    first = Path(uis).read_text(encoding="utf-8").splitlines()[:1]
    return shlex.split(first[0][len("#!args"):]) if first and first[0].startswith("#!args") else []
