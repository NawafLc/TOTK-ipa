#!/usr/bin/env python3
"""GameData/totk-late.bin (read by kit/shim/totk_late.c) and the embedded module parts (ios/tools/gen_embed.py's split).

totk-late.bin holds what build_ipa.py would compile into the app from the player's files: the module tables of
scripts/prepare_runtime.py (analysis/<version>-port/runtime-layout.json), the RomFS identity of
scripts/prepare_romfs_backend.py, the shared fonts of scripts/prepare_shared_fonts.py and gen_embed.py's hashes.
All integers little-endian; text fields are 80 bytes, NUL-terminated.
"""
import hashlib, json, struct
from pathlib import Path

PG = 0x4000
HEX = 80
MASK = (1 << 64) - 1
NAMES = ('main', 'subsdk0', 'sdk')


def up(n):
    return (n + PG - 1) & ~(PG - 1)


def fixups(path):
    return dict(line[2:].split() for line in Path(path).read_text().splitlines())


def embed_parts(rewritten, name, text):
    """gen_embed.py for one module: the bytes of its sections x0 (__TOTKX), w (__TOTK<name>W) and x1 (__TOTKX) and
    their SHA-256. `text` is the exported x0 (main with the game patches)."""
    data = (Path(rewritten) / f'{name}.patched.bin').read_bytes()
    hdr = fixups(Path(rewritten) / f'{name}.fixups.tsv')
    text_end, patch = int(hdr['TEXT_END'], 16), int(hdr['PATCH_OFF'], 16)
    key = int(hdr['KEY_PAGE_OFF'], 16)
    x0, x1 = up(text_end), up(len(data))
    if len(text) != x0:
        raise ValueError(f'{name}: exported x0 must be exactly {x0:#x} bytes, got {len(text):#x}')
    if patch < 0:
        file_end = int(hdr['FILE_IMAGE_LEN'], 16)
        if file_end % PG or x0 > file_end or key % PG:
            raise ValueError(f'{name}: invalid far patch layout')
        ranges = [(0, x0), (x0, file_end), (file_end, x1)]
    else:
        if patch % PG or x0 > key or key + PG > patch:
            raise ValueError(f'{name}: invalid patch layout')
        ranges = [(0, x0), (x0, patch), (patch, x1)]
    parts = []
    for i, (lo, hi) in enumerate(ranges):
        source = text if i == 0 else data
        chunk = source[lo:min(hi, len(source))] if lo < len(source) else b''
        chunk += bytes(hi - lo - len(chunk))
        parts.append(chunk)
    return parts, [hashlib.sha256(p).hexdigest() for p in parts]


def text(s):
    b = s.encode()
    if len(b) >= HEX:
        raise ValueError(f'text field too long: {s}')
    return b + bytes(HEX - len(b))


def write(out, layout, romfs_folder, fonts_folder, embed_hashes):
    """layout: runtime-layout.json; romfs_folder: extracted/<version>/romfs (index.json, runtime-index.bin);
    fonts_folder: extracted/firmware/shared-fonts (manifest.json); embed_hashes: {name: [x0, w, x1]}."""
    modules = json.loads(Path(layout).read_text())
    if [m['name'] for m in modules] != list(NAMES):
        raise ValueError('module order')
    romfs = json.loads((Path(romfs_folder) / 'index.json').read_text())
    index_sha = hashlib.sha256((Path(romfs_folder) / 'runtime-index.bin').read_bytes()).hexdigest()
    fonts = json.loads((Path(fonts_folder) / 'manifest.json').read_text())
    if fonts.get('status') != 'pass' or [f['type'] for f in fonts['fonts']] != list(range(6)):
        raise ValueError('shared font manifest')
    main = modules[0]
    b = bytearray(b'TOTKLAT1' + struct.pack('<II', 1, len(modules)))
    b += struct.pack('<QQQ', main['probe_plt'], main['probe_slot'], romfs['romfs_size'])
    b += text(romfs['romfs_sha256']) + text(index_sha)
    b += struct.pack('<II', len(fonts['fonts']), 0)
    for f in fonts['fonts']:
        name = f"{f['type']}-{f['name']}.bfttf"
        if (Path(fonts_folder) / name).stat().st_size != f['bfttf_bytes']:
            raise ValueError(f'shared font {name} size')
        b += text(name) + struct.pack('<QQ', f['bfttf_bytes'], f['font_bytes']) + text(f['sha256'])
    for m in modules:
        l, tags = m['layout'], {int(k): v for k, v in m['tags'].items()}
        pool = bytearray()
        offsets = []
        for s in m['symbols']:
            offsets.append(len(pool))
            pool += s['name'].encode() + b'\0'
        b += text(m['name']) + text(m['sha256'])
        b += struct.pack('<10Q', *[v & MASK for v in (m['size'], l['TEXT_END'], l['RO_OFF'], l['DATA_OFF'], l['PATCH_OFF'],
                                                      l['KEY_PAGE_OFF'], tags.get(12, 0), m['ctor_flag'], tags.get(25, 0),
                                                      tags.get(27, 0))])
        b += struct.pack('<IIII', len(m['symbols']), len(m['relocs']), len(m['gates']), len(pool))
        b += b''.join(text(h) for h in embed_hashes[m['name']])
        for r in m['relocs']:
            b += struct.pack('<QIIq', r['where'], r['kind'], r['symbol'], r['addend'])
        for s, at in zip(m['symbols'], offsets):
            b += struct.pack('<IIIIQQ', at, int(s['defined']), s['binding'], s['type'], s['value'] & MASK, s['size'] & MASK)
        for g in m['gates']:
            b += struct.pack('<QQII', g['ret'], g['original'], int(g['timer']), g['arg'])
        b += pool
    Path(out).write_bytes(bytes(b))
    return len(b)
