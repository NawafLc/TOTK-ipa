#!/usr/bin/env python3
"""Build the import tool's helper programs for this computer (Linux or macOS), from MacNativeGames' pinned sources:

  hactool      the update merge (build_app.build_hactool's pinned commit and patches; on Linux the bounded base-file
               view uses glibc's fopencookie instead of BSD funopen)
  spirv-cross  SPIRV-Cross at build_app.SPIRV_CROSS with its Release flags
  totk_xlate   the shader translator (games/totk/tools/totk_xlate, NativeAOT) - on macOS arm64 the repository's prebuilt

    build_tools.py <MacNativeGames checkout> <output folder> [--dotnet dotnet]
"""
import argparse, concurrent.futures, os, platform, shutil, subprocess, sys
from pathlib import Path

LINUX_SEEK = [
    ('static int mng_base_read(void *cookie, char *buffer, int count) {',
     'static ssize_t mng_base_read(void *cookie, char *buffer, size_t count) {'),
    ('    if (left < count) count = (int)left;', '    if (left < (off_t)count) count = (size_t)left;'),
    ('static fpos_t mng_base_seek(void *cookie, fpos_t offset, int whence) {',
     'static int mng_base_seek(void *cookie, off64_t *where, int whence) {\n    off64_t offset = *where;'),
    ('return (fpos_t)-1;', 'return -1;'),
    ('    return (fpos_t)(range->position = base + offset);', '    *where = range->position = base + offset;\n    return 0;'),
    ('    FILE *view = funopen(range, mng_base_read, NULL, mng_base_seek, mng_base_close);',
     '    FILE *view = fopencookie(range, "rb", (cookie_io_functions_t){ .read = mng_base_read, .write = NULL, '
     '.seek = mng_base_seek, .close = mng_base_close });'),
    ('#define _DARWIN_C_SOURCE 1\n', '#define _GNU_SOURCE 1\n#define _DARWIN_C_SOURCE 1\n'),
]


def sh(args, cwd=None):
    print('+', ' '.join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mng', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--dotnet', default='dotnet')
    a = ap.parse_args()
    mng, out = a.mng.resolve(), a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(mng))
    import build_app as B
    work = out.parent / 'tools-work'
    tree = work / 'totk'
    (tree).mkdir(parents=True, exist_ok=True)
    logs = work / 'logs'
    logs.mkdir(exist_ok=True)
    linux = sys.platform.startswith('linux')

    # hactool: build_app's own fetch and patches; the Linux file view is swapped in just before make
    real_run = B.run
    def run(cmd, log, cwd=None, env=None, quiet=True):
        if linux and cmd and cmd[0] == 'make':
            main_c = Path(cwd) / 'main.c'
            text = main_c.read_text()
            if 'fopencookie(' not in text:
                for old, new in LINUX_SEEK:
                    if text.count(old) != 1:
                        raise SystemExit(f'hactool main.c: expected one "{old}" (MacNativeGames changed its hactool patch)')
                    text = text.replace(old, new)
                main_c.write_text(text)
        try:
            return real_run(cmd, log, cwd=cwd, env=env, quiet=quiet)
        except B.BuildError:
            print(Path(log).read_text(errors='replace')[-4000:])
            raise
    B.run = run
    shutil.copy2(B.build_hactool(tree, logs), out / 'hactool')

    # SPIRV-Cross with build_app's pinned commit and Release flags
    src = work / 'src/SPIRV-Cross'
    B.git_fetch(*B.SPIRV_CROSS, src, logs / 'fetch-spirv-cross.log')
    flags = [f for f in B.SPIRV_CROSS_FLAGS if f not in ('-arch', 'arm64')]
    objs = work / 'spirv-obj'
    objs.mkdir(exist_ok=True)
    cxx = 'clang++' if shutil.which('clang++') else 'c++'
    with concurrent.futures.ThreadPoolExecutor(os.cpu_count() or 4) as pool:
        list(pool.map(lambda n: sh([cxx, *flags, '-c', src / n, '-o', objs / (n + '.o')]), B.SPIRV_CROSS_SOURCES))
    sh([cxx, *[objs / (n + '.o') for n in B.SPIRV_CROSS_SOURCES], '-o', out / 'spirv-cross'])

    # the shader translator
    prebuilt = mng / 'games/totk/prebuilt/macos-arm64/totk_xlate'
    if sys.platform == 'darwin' and platform.machine() == 'arm64':
        if B.sha256(prebuilt) != (prebuilt.parent / 'totk_xlate.sha256').read_text().strip():
            raise SystemExit('the prebuilt translator does not match its .sha256')
        shutil.copy2(prebuilt, out / 'totk_xlate')
    else:
        rid = {('linux', 'x86_64'): 'linux-x64', ('linux', 'aarch64'): 'linux-arm64'}[(sys.platform if not linux else 'linux', platform.machine())]
        here = mng / 'games/totk/tools/totk_xlate'
        x = work / 'xlate'
        if x.exists():
            shutil.rmtree(x)
        shutil.copytree(mng / 'vendor/ryujinx', x / 'ryujinx-src')
        for d in (x / 'ryujinx-src/src').glob('*/'):
            for sub in ('obj', 'bin'):
                shutil.rmtree(d / sub, ignore_errors=True)
        for p in sorted((here / 'patches').glob('*.patch')):
            with p.open() as f:
                print('+ patch', p.name, flush=True)
                subprocess.run(['patch', '-s', '-d', x / 'ryujinx-src', '-p1', '--forward'], stdin=f, check=True)
        (x / 'app').mkdir()
        for f in list(here.glob('*.cs')) + [here / 'totk_xlate.csproj']:
            shutil.copy2(f, x / 'app' / f.name)
        sh([a.dotnet, 'publish', x / 'app/totk_xlate.csproj', '-c', 'Release', '-r', rid, '-p:PublishAot=true',
            '-p:InvariantGlobalization=true', f'-p:RyuSrc={x / "ryujinx-src"}', '-o', x / 'out'])
        shutil.copy2(x / 'out/totk_xlate', out / 'totk_xlate')
    for name in ('hactool', 'spirv-cross', 'totk_xlate'):
        (out / name).chmod(0o755)
    print('tools ready:', ', '.join(sorted(p.name for p in out.iterdir())))


if __name__ == '__main__':
    main()
