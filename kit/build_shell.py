#!/usr/bin/env python3
"""Build the TOTK-ipa app shell on a Mac, without any game file: MacNativeGames' iOS app (games/totk/ios, as
ios/tools/build_ipa.py builds it) with the game-derived parts left for the import tool.

Differences from build_ipa.py, all in a copy of games/totk:
  - Gen/runtime_tables.h, romfs_config.h, shared_fonts_config.h and ios_embed.h are kit/shim's, which read those values
    from GameData/totk-late.bin at launch (kit/shim/totk_late.c, added to the app's sources);
  - Gen/embed.S holds an empty 16 KiB placeholder per module section (same names and protections as gen_embed.py's);
  - runtime/loader.c loads that file first thing, and runtime/shared_font.c fills its rows from it;
  - no GameData and no shader seed: the import tool adds both.

    build_shell.py <MacNativeGames checkout> <output folder> [--version v143]
"""
import argparse, os, shutil, subprocess, sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
FRAMEWORKS = ['UIKit', 'Metal', 'MetalFX', 'Foundation', 'QuartzCore', 'ImageIO', 'CoreGraphics', 'CoreText',
              'UniformTypeIdentifiers', 'CoreFoundation', 'AudioToolbox', 'GameController', 'AVFAudio', 'Security']


def run(args, cwd, log, env):
    log.parent.mkdir(parents=True, exist_ok=True)
    print('+', ' '.join(str(a) for a in args), flush=True)
    with log.open('w') as f:
        p = subprocess.run([str(a) for a in args], cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT)
    if p.returncode:
        print('\n'.join(log.read_text(errors='replace').splitlines()[-60:]))
        raise SystemExit(f'{args[0]} failed; see {log}')


def replace_once(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise SystemExit(f'{path.name}: expected exactly one "{old.strip()}" (MacNativeGames changed; update kit/build_shell.py)')
    path.write_text(text.replace(old, new))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mng', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--version', default='v143', choices=['v143'])
    ap.add_argument('--work', type=Path)
    a = ap.parse_args()
    mng, out = a.mng.resolve(), a.out.resolve()
    work = (a.work or out.parent / 'shell-work').resolve()
    tree = work / 'totk'
    if tree.exists():
        shutil.rmtree(tree)
    shutil.copytree(mng / 'games/totk', tree, symlinks=True)
    ios, gen, logs = tree / 'ios', tree / 'ios/Gen', work / 'logs'
    gen.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ios / 'tools'))
    from xcode_dir import developer_dir
    env = dict(os.environ, DEVELOPER_DIR=developer_dir())

    for name in ('totk_late.h', 'totk_late.c', 'runtime_tables.h', 'romfs_config.h', 'shared_fonts_config.h', 'ios_embed.h', 'embed.S'):
        shutil.copy2(KIT / 'shim' / name, gen / name)
    replace_once(tree / 'runtime/loader.c', 'int main(int argc,char **argv) {',
                 'int main(int argc,char **argv) {\n totk_late_load();   /* TOTK-ipa: the tables from GameData/totk-late.bin */')
    replace_once(tree / 'runtime/shared_font.c', 'static const FontRow rows[SHARED_FONT_COUNT]={SHARED_FONT_ROWS};',
                 'static FontRow rows[SHARED_FONT_COUNT];   /* TOTK-ipa: filled from GameData/totk-late.bin */')
    replace_once(tree / 'runtime/shared_font.c', 'static void load(void){',
                 'static void load(void){\n totk_late_fill_fonts(rows,sizeof rows[0],SHARED_FONT_COUNT);')

    # the project as build_ipa.py generates it for this version, plus the late-binding reader
    project = (ios / 'project.yml').read_text()
    if '          - loader.c' not in project or '      - path: Gen/embed.S' not in project or '-I../build\n' not in project:
        raise SystemExit('project.yml changed; update kit/build_shell.py')
    project = project.replace('          - loader.c', '          - loader.c\n          - game_patches.c')
    project = project.replace('-I../build\n', f'-I../build -DTOTK_GAME_{a.version.upper()}=1\n')
    project = project.replace('      - path: Gen/embed.S', '      - path: Gen/embed.S\n      - path: Gen/totk_late.c')
    (ios / 'project.generated.yml').write_text(project)

    deps = tree / 'build/ios-deps'
    run([sys.executable, ios / 'tools/build_deps.py', deps], tree, logs / 'ios-dependencies.log', env)
    shutil.copytree(deps / 'include', gen / 'deps/include', dirs_exist_ok=True)
    (gen / 'deps/lib').mkdir(parents=True, exist_ok=True)
    for lib in ('libopus.a', 'libvpx.a'):
        shutil.copy2(deps / 'lib' / lib, gen / 'deps/lib' / lib)

    flags = [f'-Wl,-segprot,__TOTK{n}W,rw,rw' for n in ('main', 'subsdk0', 'sdk')] + ['-Wl,-segprot,__TOTKX,r-x,r-x']
    (gen / 'totk.xcconfig').write_text('OTHER_LDFLAGS = $(inherited) ' + ' '.join('-framework ' + x for x in FRAMEWORKS) +
                                       ' Gen/deps/lib/libopus.a Gen/deps/lib/libvpx.a ' + ' '.join(flags) + '\n')
    env.update(TOTK_APP_NAME='Tears of the Kingdom', TOTK_BUNDLE_ID='org.macnativegames.totk')
    run(['xcodegen', 'generate', '--spec', 'project.generated.yml'], ios, logs / 'xcodegen.log', env)
    derived = work / 'derived'
    run(['xcodebuild', '-project', 'TOTKIOS.xcodeproj', '-scheme', 'TOTKIOS', '-configuration', 'Release',
         '-destination', 'generic/platform=iOS', '-derivedDataPath', derived, 'CODE_SIGNING_ALLOWED=NO',
         'CODE_SIGNING_REQUIRED=NO', 'CODE_SIGN_IDENTITY='], ios, logs / 'xcodebuild-ios.log', env)
    app = derived / 'Build/Products/Release-iphoneos/TOTK.app'
    if not app.is_dir():
        raise SystemExit(f'Xcode did not produce {app}')
    # as build_ipa.py: the increased-memory-limit entitlement in the executable's ad-hoc signature, which the import
    # tool keeps when it signs the filled executable again
    run(['codesign', '--force', '--sign', '-', '--entitlements', ios / 'Sources/TOTK.entitlements', app / 'TOTK'], ios,
        logs / 'ios-entitlements.log', env)
    target = out / f'{a.version}/TOTK.app'
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(app, target, symlinks=True)
    print(f'app shell ready: {target}')


if __name__ == '__main__':
    main()
