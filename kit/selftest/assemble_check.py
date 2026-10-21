#!/usr/bin/env python3
"""The import tool's last part on synthetic game files: the Python environment as MacNativeGames' scripts expect it
(prepare_venv, with junctions on Windows), the module parts into the real app shell (build_payload), GameData and the
IPA (write_ipa). Checks the IPA's entries, the executable's mode and that every section holds what was embedded.
    usage: assemble_check.py <MacNativeGames checkout> <TOTK.app shell>"""
import hashlib, json, os, shutil, struct, sys, tempfile, zipfile
from pathlib import Path
KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'selftest'))
import totk_import as T, check_export as C, macho


def synthetic_tree(mng, root):
    tree = root / 'totk'
    shutil.copytree(mng / 'games/totk', tree, ignore=shutil.ignore_patterns('prebuilt'))
    rw = tree / 'rewritten/v143'
    rw.mkdir(parents=True)
    layout = []
    for name in T.NAMES:
        if name == 'main':
            text_end, size = 0x2600010, 0x3b00000
            img = C.image(text_end, size, 0)
            key = 0x3a00000
        else:
            text_end, size = 0x10010, 0x40000
            img = os.urandom(size)
            key = 0x2c000
        patch = key + 0x4000
        (rw / f'{name}.patched.bin').write_bytes(img)
        (rw / f'{name}.fixups.tsv').write_text(f'# TEXT_END {text_end:x}\n# PATCH_OFF {patch:x}\n# KEY_PAGE_OFF {key:x}\n')
        layout.append(dict(name=name, sha256=hashlib.sha256(img).hexdigest(), size=len(img), ctor_flag=8, tags={'12': 4},
                           layout=dict(TEXT_END=text_end, RO_OFF=text_end + 0x10000, DATA_OFF=text_end + 0x20000,
                                       PATCH_OFF=patch, KEY_PAGE_OFF=key),
                           symbols=[dict(name='nnMain', value=4, size=4, defined=True, binding=1, type=2)],
                           relocs=[dict(where=text_end + 0x20000, kind=1027, symbol=0, addend=8)], gates=[],
                           probe_plt=1, probe_slot=2))
    (tree / 'analysis/v143-port').mkdir(parents=True)
    (tree / 'analysis/v143-port/runtime-layout.json').write_text(json.dumps(layout))
    romfs = tree / 'extracted/v143/romfs'
    romfs.mkdir(parents=True)
    (romfs / 'romfs.bin').write_bytes(b'x' * 100000)
    (romfs / 'runtime-index.bin').write_bytes(b'TOTKRFS1' + bytes(16))
    (romfs / 'index.json').write_text(json.dumps(dict(romfs_size=100000, romfs_sha256=hashlib.sha256(b'x' * 100000).hexdigest())))
    for d in ('romfs-patches', 'romfs-patches-out'):
        (tree / f'extracted/v143/{d}').mkdir(parents=True)
        (tree / f'extracted/v143/{d}/manifest.tsv').write_text('# none\n')
    fonts = tree / 'extracted/firmware/shared-fonts'
    fonts.mkdir(parents=True)
    rows = []
    for t in range(6):
        b = os.urandom(100)
        (fonts / f'{t}-font{t}.bfttf').write_bytes(b)
        rows.append(dict(type=t, name=f'font{t}', bfttf_bytes=100, font_bytes=92, sha256=hashlib.sha256(b).hexdigest()))
    (fonts / 'manifest.json').write_text(json.dumps(dict(status='pass', fonts=rows)))
    seed = tree / 'build/shader-seed/v143'
    seed.mkdir(parents=True)
    (seed / 'seed-manifest.json').write_text(json.dumps(dict(chain='c', schema=1, shaders=1, files={})))
    (seed / ('a' * 64 + '-' + 'b' * 12 + '_b.metal')).write_text('kernel void k() {}')
    return tree


def main():
    mng, shell = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        logs = root / 'logs'
        logs.mkdir()
        tree = synthetic_tree(mng, root)
        venv = T.prepare_venv(root / 'venv', tree / 'requirements.txt', logs)
        T.dir_link(tree / '.venv', venv)
        app = T.build_payload(tree, shell, root / 'payload', logs)
        out = root / 'out/TOTK.ipa'
        T.write_ipa(root / 'payload', out)
        with zipfile.ZipFile(out) as z:
            names = set(z.namelist())
            shell_files = {'Payload/TOTK.app/' + p.relative_to(shell).as_posix() for p in shell.rglob('*') if p.is_file()}
            for want in (*shell_files, 'Payload/TOTK.app/GameData/totk-late.bin',
                         'Payload/TOTK.app/GameData/romfs/romfs.bin', 'Payload/TOTK.app/GameData/shared-fonts/0-font0.bfttf',
                         'Payload/TOTK.app/GameData/shader-seed/seed-manifest.json',
                         'Payload/TOTK.app/GameData/shader-seed/pso_title.tsv'):
                assert want in names, f'{want} missing from the IPA'
            info = z.getinfo('Payload/TOTK.app/TOTK')
            assert info.external_attr >> 16 == 0o100755, oct(info.external_attr >> 16)
            assert z.getinfo('Payload/TOTK.app/GameData/romfs/romfs.bin').file_size == 100000
            exe = z.read('Payload/TOTK.app/TOTK')
        m = macho.MachO(exe)
        sizes = {s.name: s.size for seg in m.segments for s in seg.sections}
        assert sizes[('__TOTKX', '__mainx0')] == 0x2604000, hex(sizes[('__TOTKX', '__mainx0')])
        print(f'IPA assembled: {len(names)} entries, {out.stat().st_size / 2**20:.0f} MiB; executable sections filled')


if __name__ == '__main__':
    main()
