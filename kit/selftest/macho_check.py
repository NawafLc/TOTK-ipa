#!/usr/bin/env python3
"""Fill an app shell's executable with random module parts of realistic sizes (kit/tools/macho.py) and check the result
independently: every section holds its bytes at a 16 KiB-aligned address, the page hashes match the file, the symbols
did not move; on a Mac also `codesign --verify` and the entitlements.  usage: macho_check.py <TOTK executable>"""
import hashlib, os, shutil, struct, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import macho

SIZES = {('__TOTKX', '__mainx0'): 0x2604000, ('__TOTKmainW', '__img'): 0x1500000, ('__TOTKX', '__mainx1'): 0x8000,
         ('__TOTKX', '__subsdk0x0'): 0x4000, ('__TOTKsubsdk0W', '__img'): 0x8000, ('__TOTKX', '__subsdk0x1'): 0x4000,
         ('__TOTKX', '__sdkx0'): 0x2a8000, ('__TOTKsdkW', '__img'): 0x9c000, ('__TOTKX', '__sdkx1'): 0x4000}


def symbols(data, m):
    st = m.cmd(macho.LC_SYMTAB)
    symoff, nsyms, stroff, _ = struct.unpack_from('<IIII', data, st[1] + 8)
    out = {}
    for i in range(nsyms):
        sx, = struct.unpack_from('<I', data, symoff + 16 * i)
        out[data[stroff + sx:data.index(b'\0', stroff + sx)]] = struct.unpack_from('<Q', data, symoff + 16 * i + 8)[0]
    return out


def main():
    src = Path(sys.argv[1])
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / src.name
        shutil.copy2(src, exe)
        before = macho.MachO(exe.read_bytes())
        contents = {k: os.urandom(v) for k, v in SIZES.items()}
        macho.fill(exe, contents)
        data = exe.read_bytes()
        m = macho.MachO(data)
        for seg in m.segments:
            for s in seg.sections:
                if s.name in contents:
                    assert data[s.offset:s.offset + s.size] == contents[s.name], s.name
                    assert s.addr % 0x4000 == 0 and s.offset % 0x4000 == 0, s.name
        assert symbols(data, m) == symbols(bytes(before.data), before), 'symbols moved'
        sig_off, _ = struct.unpack_from('<II', data, m.cmd(macho.LC_CODE_SIGNATURE)[1] + 8)
        for typ, blob in macho.parse_signature(data[sig_off:]):
            if typ == 0 or 0x1000 <= typ < 0x2000:
                hoff, = struct.unpack_from('>I', blob, 16)
                n, limit = struct.unpack_from('>II', blob, 28)
                hs, ht, page = blob[36], blob[37], 1 << blob[39]
                algo = hashlib.sha1 if ht == 1 else hashlib.sha256
                assert limit == sig_off
                for k in range(n):
                    assert blob[hoff + hs * k:hoff + hs * (k + 1)] == algo(data[k * page:min((k + 1) * page, limit)]).digest()[:hs]
        print(f'filled {exe.stat().st_size / 2**20:.0f} MiB executable: sections, symbols and page hashes check out')
        if sys.platform == 'darwin':
            subprocess.run(['codesign', '--verify', '--strict', '--verbose=2', exe], check=True)
            ent = subprocess.run(['codesign', '-d', '--entitlements', '-', '--xml', exe], capture_output=True, text=True, check=True).stdout
            want = subprocess.run(['codesign', '-d', '--entitlements', '-', '--xml', src], capture_output=True, text=True, check=True).stdout
            assert ent == want and 'increased-memory-limit' in ent, 'entitlements changed'
            print('codesign verifies the filled executable; entitlements unchanged')


if __name__ == '__main__':
    main()
