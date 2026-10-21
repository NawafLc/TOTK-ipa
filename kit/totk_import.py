#!/usr/bin/env python3
"""TOTK-ipa import: turn your own Tears of the Kingdom dump and prod.keys into an iPhone/iPad IPA, on Linux (also WSL on
Windows) or a Mac, with the app shell built by GitHub (no game files ever leave your computer).

    python3.14 totk_import.py <base 1.0.0 .xci|.nsp> --update <1.4.3 .nsp|.nsz> -k <prod.keys> [-o TOTK.ipa]
                              [--firmware <dir> | --shared-fonts <dir>]   (an NSP base game has no system fonts)

It runs MacNativeGames' own build steps for your files (steps 1-3 of build_app.py: extract and verify, rewrite the code
for Apple chips, prepare the startup shaders), then puts the result into the shell instead of compiling it in:
  - main's text with the game patches (kit/tools/export_v143.py; build_ipa.py runs the Mac host for this),
  - the module parts into the executable's placeholder sections, signed again ad hoc (kit/tools/macho.py),
  - the tables the shell reads at launch (kit/tools/late_config.py -> GameData/totk-late.bin),
  - GameData as build_ipa.py lays it out (RomFS, overlays, shared fonts, shader seed).
The shaders are left as Metal source: the phone compiles each one the first time it is used (a Mac would precompile
them, which needs Apple's Metal compiler).

The IPA is unsigned for distribution: sign and install it with your sideloading tool (xtool, Sideloadly, AltStore...),
keeping its entitlements. It contains the game made from your files: it is for your own use only; do not share it.
"""
import argparse, hashlib, json, os, platform, shutil, subprocess, sys, time, zipfile
from pathlib import Path

KIT = Path(__file__).resolve().parent
MNG = KIT / 'MacNativeGames'
sys.path.insert(0, str(KIT / 'tools'))
import export_v143, late_config, macho

VERSION = 'v143'
NAMES = late_config.NAMES


def say(msg):
    print(f'[totk-ipa] {msg}', flush=True)


def tool_dir():
    machine = platform.machine().lower()
    arch = {'x86_64': 'x64', 'amd64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine, machine)
    system = {'linux': 'linux', 'darwin': 'macos'}.get(sys.platform)
    folder = KIT / 'bin' / f'{system}-{arch}'
    if not system or not folder.is_dir():
        have = ', '.join(p.name for p in (KIT / 'bin').iterdir()) if (KIT / 'bin').is_dir() else 'none'
        raise SystemExit(f'this kit has no tools for {sys.platform}/{machine} (it has: {have}); on Windows run it in WSL')
    return folder


def prepare_tree(work, logs):
    """build_app.prepare_work without rsync/git: a copy of games/totk with its Python environment."""
    tree = work / 'totk'
    stamp = tree / '.kit-source'
    source = (MNG / '.kit-commit').read_text().strip() if (MNG / '.kit-commit').exists() else 'unknown'
    if not (stamp.exists() and stamp.read_text().strip() == source):
        say('copying the MacNativeGames sources into the work folder')
        keep = {'extracted', 'rewritten', 'build', 'analysis', '.venv', 'tooling', 'user-data'}
        tree.mkdir(parents=True, exist_ok=True)
        for item in (MNG / 'games/totk').iterdir():
            if item.name in keep:
                continue
            target = tree / item.name
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()
            (shutil.copytree if item.is_dir() else shutil.copy2)(item, target)
        stamp.write_text(source + '\n')
    venv = work / 'venv'
    if not (venv / 'bin/python').exists():
        say('Python environment for the build tools (one time)')
        subprocess.run([sys.executable, '-m', 'venv', venv], check=True)
    marker = venv / '.requirements'
    req = (tree / 'requirements.txt').read_text()
    if not marker.exists() or marker.read_text() != req:
        with (logs / 'pip.log').open('w') as log:
            subprocess.run([venv / 'bin/python', '-m', 'pip', 'install', '-q', '-r', tree / 'requirements.txt'],
                           check=True, stdout=log, stderr=subprocess.STDOUT)
        marker.write_text(req)
    link = tree / '.venv'
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(venv, target_is_directory=True)
    for name in ('analysis', 'build'):
        (tree / name).mkdir(exist_ok=True)
    return tree


def prepare_seed(tree, bins, logs):
    """build_app.step_shaders with this computer's translator and SPIRV-Cross (built by the kit's workflow)."""
    translator, spirv = bins / 'totk_xlate', bins / 'spirv-cross'
    say('3/4 shaders: discovering and translating startup shaders from your game data (several minutes)')
    with (logs / 'prepare-shader-seed.log').open('w') as log:
        p = subprocess.run([tree / '.venv/bin/python', 'scripts/prepare_shader_seed.py',
                            '--romfs', tree / f'extracted/{VERSION}/romfs', '--output', tree / f'build/shader-seed/{VERSION}',
                            '--translator', translator, '--spirv-cross', spirv, '--version', VERSION,
                            '--modules', tree / f'rewritten/{VERSION}'], cwd=tree, stdout=log, stderr=subprocess.STDOUT)
    if p.returncode:
        raise SystemExit(f'shader preparation failed; see {logs / "prepare-shader-seed.log"}')


def seed_for_ios(tree, seed, logs):
    """build_ipa.py's shader-seed folder, without device metallibs (the phone compiles the Metal source)."""
    src = tree / f'build/shader-seed/{VERSION}'
    if seed.exists():
        shutil.rmtree(seed)
    shutil.copytree(src, seed)
    manifest = json.loads((seed / 'seed-manifest.json').read_text())
    manifest['ios_source_manifest_sha256'] = hashlib.sha256((src / 'seed-manifest.json').read_bytes()).hexdigest()
    (seed / 'shader_map.tsv').write_text('# TOTK control-code-sha256-v1\n')
    manifest['files'] = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(seed.iterdir())
                         if f.is_file() and f.name not in ('seed-manifest.json', 'shader_map.tsv')}
    (seed / 'seed-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    with (logs / 'shader-list.log').open('w') as log:
        subprocess.run([tree / '.venv/bin/python', tree / 'scripts/shader_list.py', 'export', tree / 'assets/shader_list.tsv',
                        logs / 'pso_manifest.tsv', seed / 'pso_title.tsv'], cwd=tree, check=True, stdout=log, stderr=subprocess.STDOUT)


def copy_tree(src, dst):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def link_or_copy(src, dst):
    """Hard links keep the 17 GB RomFS from being copied again inside the work folder."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def build_payload(tree, shell, payload, logs):
    tree, shell, payload, logs = tree.resolve(), shell.resolve(), payload.resolve(), logs.resolve()
    app = payload / 'Payload/TOTK.app'
    if payload.exists():
        shutil.rmtree(payload)
    shutil.copytree(shell, app, symlinks=True)
    rewritten = tree / f'rewritten/{VERSION}'
    layout = tree / f'analysis/{VERSION}-port/runtime-layout.json'
    modules = {m['name']: m for m in json.loads(layout.read_text())}
    say('4/4 app: applying the 1.4.3 game patches to main and embedding the three code modules')
    contents, hashes = {}, {}
    for name in NAMES:
        image = (rewritten / f'{name}.patched.bin').read_bytes()
        if hashlib.sha256(image).hexdigest() != modules[name]['sha256']:
            raise SystemExit(f'{name}.patched.bin is not the verified rewrite')
        text = export_v143.export_text(image, modules[name]['layout']['TEXT_END'], name)
        parts, hashes[name] = late_config.embed_parts(rewritten, name, text)
        contents[('__TOTKX', f'__{name}x0')], contents[(f'__TOTK{name}W', '__img')], contents[('__TOTKX', f'__{name}x1')] = parts
    macho.fill(app / 'TOTK', contents)
    res = app / 'GameData'
    res.mkdir(exist_ok=True)
    romfs = tree / f'extracted/{VERSION}/romfs'
    say('4/4 app: game data (the RomFS is linked, not copied, where the disk allows)')
    (res / 'romfs').mkdir()
    for f in romfs.iterdir():
        if f.is_file():
            link_or_copy(f, res / 'romfs' / f.name)
    for src, dst in [(tree / f'extracted/{VERSION}/romfs-patches', res / 'romfs-patches'),
                     (tree / f'extracted/{VERSION}/romfs-patches-out', res / 'romfs-patches-out'),
                     (tree / 'extracted/firmware/shared-fonts', res / 'shared-fonts')]:
        copy_tree(src, dst)
    seed_for_ios(tree, res / 'shader-seed', logs)
    size = late_config.write(res / 'totk-late.bin', layout, romfs, tree / 'extracted/firmware/shared-fonts', hashes)
    say(f'4/4 app: game tables written ({size} bytes)')
    return app


def write_ipa(payload, out):
    say(f'4/4 app: writing {out} (stored, not compressed: about 18 GB)')
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + '.partial')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
        for path in sorted(payload.rglob('*')):
            rel = path.relative_to(payload).as_posix()
            if path.is_symlink():
                info = zipfile.ZipInfo(rel)
                info.external_attr = (0o120777 << 16)
                z.writestr(info, os.readlink(path))
            elif path.is_dir():
                z.write(path, rel + '/')
            else:
                z.write(path, rel)
    tmp.replace(out)


def main(argv):
    ap = argparse.ArgumentParser(description='Make a Tears of the Kingdom IPA from your own dump with the TOTK-ipa kit.')
    ap.add_argument('game', type=Path, help='base game 1.0.0 (.xci or .nsp)')
    ap.add_argument('--update', type=Path, required=True, help='the 1.4.3 update (.nsp or .nsz)')
    ap.add_argument('-k', '--keys', type=Path, required=True, help='your prod.keys')
    ap.add_argument('-o', '--out', type=Path, help='the IPA to write (default: next to the game file)')
    ap.add_argument('--work', type=Path, help='work folder (default: TOTK_ipa_build next to the game file)')
    fonts = ap.add_mutually_exclusive_group()
    fonts.add_argument('--firmware', type=Path, help='unpacked firmware NCA directory (an NSP base game has no system fonts)')
    fonts.add_argument('--shared-fonts', type=Path, help='previously extracted shared-font directory')
    a = ap.parse_args(argv)
    if sys.version_info < (3, 14):
        raise SystemExit('needs Python 3.14 or newer (MacNativeGames reads zstd with its standard library)')
    sys.path.insert(0, str(MNG))
    import build_app as B
    game, keys, update = a.game.expanduser().resolve(), a.keys.expanduser().resolve(), a.update.expanduser().resolve()
    for f in (game, keys, update):
        if not f.is_file():
            raise SystemExit(f'no such file: {f}')
    out = (a.out.expanduser().resolve() if a.out else game.parent / 'Tears of the Kingdom.ipa')
    if out.suffix.lower() != '.ipa':
        raise SystemExit('the output must end in .ipa')
    work = (a.work.expanduser().resolve() if a.work else game.parent / 'TOTK_ipa_build')
    shell = KIT / f'shell/{VERSION}/TOTK.app'
    if not (shell / 'TOTK').is_file():
        raise SystemExit(f'the app shell is missing: {shell}')
    bins = tool_dir()
    firmware = a.firmware.expanduser().resolve() if a.firmware else None
    shared_fonts = a.shared_fonts.expanduser().resolve() if a.shared_fonts else None
    if B.input_kind(game) not in ('xci', 'nsp'):
        raise SystemExit('the base game must be an uncompressed XCI or NSP')
    if B.input_kind(game) == 'nsp' and not (firmware or shared_fonts or B.fonts_valid(work / 'totk/extracted/firmware/shared-fonts')):
        raise SystemExit('an NSP base game has no system fonts: add --firmware <unpacked firmware NCA directory> or '
                         '--shared-fonts <folder with the six .bfttf files>')
    work.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(work).free / 2**30
    if free < 60 and not (work / f'totk/extracted/{VERSION}/romfs/romfs.bin').exists():
        raise SystemExit(f'needs about 60 GB free in {work} (has {free:.0f} GB)')
    logs = work / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    tree = prepare_tree(work, logs)
    B.build_hactool = lambda tree, logs: bins / 'hactool'   # built by the kit's workflow for this computer
    env = dict(os.environ)
    try:
        if B.identify_game(tree, game, keys, logs) != 'totk':
            raise SystemExit('this kit makes Tears of the Kingdom only')
        version, update = B.identify_update(tree, update, keys, logs)
        if version != VERSION:
            raise SystemExit(f'the update is {B.VERSIONS[version]["display_version"]}: the iPhone/iPad build needs 1.4.3')
        B.step_code(tree, game, keys, env, logs)
        B.step_code(tree, update, keys, env, logs, version=version)
        B.step_data(tree, game, keys, logs, firmware=firmware, shared_fonts=shared_fonts)
        B.step_update_data(tree, game, update, keys, logs, version=version)
    except B.BuildError as e:
        raise SystemExit(f'ERROR: {e}')
    for script, args in [('prepare_runtime.py', ['--version', VERSION]), ('prepare_romfs_backend.py', ['--version', VERSION])]:
        with (logs / f'{script}.log').open('w') as log:
            if subprocess.run([tree / '.venv/bin/python', f'scripts/{script}', *args], cwd=tree, stdout=log,
                              stderr=subprocess.STDOUT).returncode:
                raise SystemExit(f'{script} failed; see {logs / (script + ".log")}')
    prepare_seed(tree, bins, logs)   # reuses a seed already prepared from the same files and tools
    payload = work / 'ipa-payload'
    build_payload(tree, shell, payload, logs)
    write_ipa(payload, out)
    shutil.rmtree(payload)
    say(f'done in {(time.time() - t0) / 60:.0f} min: {out} ({out.stat().st_size / 2**30:.1f} GiB)')
    say('Sign and install it with your sideloading tool, keeping its entitlements. It holds your game: do not share it.')


if __name__ == '__main__':
    main(sys.argv[1:])
