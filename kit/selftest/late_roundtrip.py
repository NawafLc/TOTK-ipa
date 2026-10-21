#!/usr/bin/env python3
"""Write a synthetic totk-late.bin with kit/tools/late_config.py and read it back with kit/shim/totk_late.c (built for
this computer against MacNativeGames' runtime/runtime.h).  usage: late_roundtrip.py <MacNativeGames checkout>"""
import hashlib, json, os, random, subprocess, sys, tempfile
from pathlib import Path
KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / 'tools'))
import late_config

def main():
    runtime = Path(sys.argv[1]) / 'games/totk/runtime'
    rnd = random.Random(7)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        modules, expect = [], []
        for name in late_config.NAMES:
            syms = [dict(name=f'_ZN2nn{rnd.randrange(10**6)}{name}', value=rnd.getrandbits(40), size=rnd.getrandbits(16),
                         defined=bool(rnd.getrandbits(1)), binding=rnd.randrange(3), type=rnd.randrange(16)) for _ in range(50)]
            relocs = [dict(where=rnd.getrandbits(32), kind=rnd.choice([257, 1025, 1026, 1027]), symbol=rnd.randrange(50),
                           addend=rnd.randrange(-1000, 10**9)) for _ in range(70)]
            gates = [dict(ret=rnd.getrandbits(32), original=rnd.getrandbits(32), timer=bool(rnd.getrandbits(1)), arg=rnd.randrange(256))
                     for _ in range(5 if name == 'main' else 0)]
            layout = {k: rnd.getrandbits(32) for k in ('TEXT_END', 'RO_OFF', 'DATA_OFF', 'PATCH_OFF', 'KEY_PAGE_OFF')}
            modules.append(dict(name=name, sha256=hashlib.sha256(name.encode()).hexdigest(), size=rnd.getrandbits(30),
                                ctor_flag=rnd.getrandbits(30), layout=layout, tags={'12': 111, '25': 222, '27': 333},
                                symbols=syms, relocs=relocs, gates=gates, probe_plt=4242, probe_slot=4343))
        (tmp / 'layout.json').write_text(json.dumps(modules))
        romfs = tmp / 'romfs'; romfs.mkdir()
        (romfs / 'index.json').write_text(json.dumps(dict(romfs_size=17052625232, romfs_sha256='ab' * 32)))
        (romfs / 'runtime-index.bin').write_bytes(b'TOTKRFS1' + bytes(100))
        fonts = tmp / 'fonts'; fonts.mkdir()
        rows = []
        for t in range(6):
            body = os.urandom(1000 + t)
            (fonts / f'{t}-font{t}.bfttf').write_bytes(body)
            rows.append(dict(type=t, name=f'font{t}', bfttf_bytes=len(body), font_bytes=len(body) - 8, sha256=hashlib.sha256(body).hexdigest()))
        (fonts / 'manifest.json').write_text(json.dumps(dict(status='pass', fonts=rows)))
        hashes = {n: [hashlib.sha256(f'{n}{i}'.encode()).hexdigest() for i in range(3)] for n in late_config.NAMES}
        late = tmp / 'totk-late.bin'
        late_config.write(late, tmp / 'layout.json', romfs, fonts, hashes)
        exe = tmp / 'late_dump'
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-I', KIT / 'shim', '-I', runtime, KIT / 'shim/totk_late.c',
                        Path(__file__).with_name('late_dump.c'), '-o', exe, '-lpthread'], check=True)
        out = subprocess.run([exe], env=dict(os.environ, TOTK_LATE=str(late)), capture_output=True, text=True, check=True).stdout.splitlines()
        want = ['probe 4242 4343', f'romfs 17052625232 {"ab" * 32} {hashlib.sha256(b"TOTKRFS1" + bytes(100)).hexdigest()}']
        want += [f"font {t}-font{t}.bfttf {r['bfttf_bytes']} {r['font_bytes']} {r['sha256']}" for t, r in enumerate(rows)]
        for m in modules:
            l = m['layout']
            want.append(' '.join(str(x) for x in ['module', m['name'], m['sha256'], m['size'], l['TEXT_END'], l['RO_OFF'], l['DATA_OFF'],
                                                    l['PATCH_OFF'], l['KEY_PAGE_OFF'], 111, m['ctor_flag'], 222, 333, *hashes[m['name']]]))
            want += [f"reloc {r['where']} {r['kind']} {r['symbol']} {r['addend']}" for r in m['relocs']]
            want += [f"sym {s['name']} {s['value']} {s['size']} {int(s['defined'])} {s['binding']} {s['type']}" for s in m['symbols']]
            want += [f"gate {g['ret']} {g['original']} {int(g['timer'])} {g['arg']}" for g in m['gates']]
        if out != want:
            bad = next(i for i, (a, b) in enumerate(zip(out + [''] * len(want), want)) if a != b)
            raise SystemExit(f'line {bad}: read {out[bad] if bad < len(out) else None!r}, wrote {want[bad]!r}')
        print(f'totk-late.bin round trip: {len(out)} lines identical ({late.stat().st_size} bytes)')

if __name__ == '__main__':
    main()
