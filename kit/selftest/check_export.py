#!/usr/bin/env python3
"""Compare kit/tools/export_v143.py with MacNativeGames' C patches (export_check, built on the Mac) on synthetic images:
every original instruction the patches check is planted at its site, everything else is random words, and the text
padding after TEXT_END is zero as in a rewritten image.  usage: check_export.py <export_check binary>"""
import os, random, struct, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import export_v143 as ex

def image(text_end, file_size, seed):
    rnd = random.Random(seed)
    b = bytearray(rnd.getrandbits(8) for _ in range(file_size)) if file_size < 1 << 16 else bytearray(os.urandom(file_size))
    pad_end = (text_end + 0x3fff) & ~0x3fff
    b[text_end:pad_end] = bytes(pad_end - text_end)
    plant = [(0x3e5658, 0x1e210808), (0x2daa54, 0xbd425260), (0x2daa58, 0x52a84e08), (0x2daa6c, 0x5e21d800),
             (0x2daa70, 0x1e201820), (0x2daa74, 0x1e2c1001), (0x2daa78, 0x1e210800),
             (0x246eac, 0x1e200940), (0x345904, 0x1e210801), (0x24944c, 0x94015e7d), (0x28bc98, 0x9400546a),
             (0x562a64, 0xbd402920), (0x562a68, 0x52a85909), (0x562a6c, 0x1e270121),
             (0x628c74, 0xbd40a661), (0xb43460, 0x1e211803), (0x1ff04f4, 0xbd400c20), (0x253fbb0, 0x1e231842)]
    plant += [(off, orig) for off, orig, _ in ex.FPS60]
    for off, word in plant:
        struct.pack_into('<I', b, off, word)
    return bytes(b)

def main():
    harness = sys.argv[1]
    cases = [(0x2600010, 0x3b00000), (0x2600a04, 0x3b04000), (0x2603400, 0x3c00123)]
    with tempfile.TemporaryDirectory() as tmp:
        for i, (text_end, size) in enumerate(cases):
            img = image(text_end, size, i)
            src, out = Path(tmp, 'main.bin'), Path(tmp, 'x0.bin')
            src.write_bytes(img)
            subprocess.run([harness, src, f'{text_end:x}', out], check=True, env={k: v for k, v in os.environ.items() if not k.startswith('TOTK_')})
            want = out.read_bytes()
            got = ex.export_text(img, text_end, 'main')
            if got != want:
                diff = [hex(k) for k in range(0, len(want), 4) if got[k:k + 4] != want[k:k + 4]][:10]
                raise SystemExit(f'case {i}: export_v143.py differs from the C patches at {diff}')
            changed = sum(1 for k in range(0, len(want), 4) if want[k:k + 4] != img[k:k + 4])
            print(f'case {i}: identical ({changed} words patched)')
    print('export_v143.py matches runtime/game_patches_v143.c')

if __name__ == '__main__':
    main()
