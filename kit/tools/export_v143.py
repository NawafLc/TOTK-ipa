#!/usr/bin/env python3
"""The 1.4.3 iOS export without a Mac: main's text with the game patches applied, as `totk-native-v143 <dir> export-ios`
(runtime/loader.c export_ios_text) writes it, for ios/tools/gen_embed.py.

This is a line-by-line port of what runtime/game_patches_v143.c and runtime/aspect_patch.h write into main's text when
TOTK_EXPORT_IOS is set and no TOTK_* option is (the iOS build's defaults: real-time frame step, cloth/hair clock, high-FPS
bounce fix, the ultrawide stubs left off, 60 FPS; no output or render-resolution patch). Every original instruction is
checked first, exactly as there. The phone checks the same words again when it starts (the TARGET_OS_IPHONE branches of
game_patches_v143.c), and kit/selftest/export_check.c compares this port with the C code on the Mac.
Relocations never reach the text, so only these patches differ from the rewritten image.
"""
import struct

PAGE = 0x4000


class ExportError(Exception):
    pass


def page_up(x):
    return (x + 0x3fff) & ~0x3fff


def adrp(reg, pc, target):
    # the module base is page aligned, so offsets give the same page distance as addresses
    pages = (target >> 12) - (pc >> 12)
    if pages < -(1 << 20) or pages >= (1 << 20):
        raise ExportError('1.4.3 data outside ADRP range')
    imm = pages & 0x1fffff
    return 0x90000000 | ((imm & 3) << 29) | ((imm >> 2) << 5) | reg


def branch(pc, target):
    delta = target - pc
    if (delta & 3) or delta < -(1 << 27) or delta >= (1 << 27):
        raise ExportError('1.4.3 patch branch outside range')
    return 0x14000000 | ((delta >> 2) & 0x3ffffff)


class Text:
    def __init__(self, image, text_end, file_size):
        self.b = bytearray(image)
        self.text_end, self.file_size = text_end, file_size
        self.size = page_up(file_size) + PAGE   # main: one private page after the image

    def word(self, off):
        return struct.unpack_from('<I', self.b, off)[0]

    def put(self, off, *words):
        for i, w in enumerate(words):
            struct.pack_into('<I', self.b, off + 4 * i, w & 0xffffffff)

    def zero(self, off, n):
        return not any(self.b[off:off + n])


FPS60 = [(0x2db204, 0x6b08015f, 0x7100055f), (0x2db208, 0x1a89b10a, 0x1a9fa52a), (0x2db22c, 0xb940468a, 0xd503201f),
         (0x2db360, 0x6b0801bf, 0x710005bf), (0x2db36c, 0x1a88c1ac, 0x1a9fc5ac), (0x2db340, 0xb9400288, 0x52800028),
         (0x2db34c, 0x2a0a03f5, 0x1a9fa555)]


def patch_secondary_animation(m, data, stub):
    sites = [(0x246eac, 0x1e200940), (0x345904, 0x1e210801), (0x24944c, 0x94015e7d), (0x28bc98, 0x9400546a)]
    words = 19
    if stub + words * 4 > ((m.text_end + 0x3fff) & ~0x3fff) or data + 8 > m.size:
        raise ExportError('1.4.3 secondary animation patch layout')
    code = [adrp(8, stub, data), 0xbd400100, 0x1e200940, 0xbd0367e0,
            0xbd400500, 0x1e200940, branch(stub + 24, 0x246eb0),
            adrp(8, stub + 28, data), 0xbd400101, 0x1e210801, 0xbd0117e1,
            0xbd400501, 0x1e210801, branch(stub + 52, 0x345908),
            adrp(8, stub + 56, data), 0xbd400104, 0x1e240842, 0x1e240863,
            branch(stub + 72, 0x2a0e40)]
    jumps = [branch(sites[0][0], stub), branch(sites[1][0], stub + 28),
             branch(sites[2][0], stub + 56) | 0x80000000, branch(sites[3][0], stub + 56) | 0x80000000]
    for off, original in sites:
        if off + 4 > m.text_end:
            raise ExportError('1.4.3 secondary animation site outside text')
        if m.word(off) != original:
            raise ExportError('1.4.3 secondary animation instruction mismatch')
    if not m.zero(stub, words * 4):
        raise ExportError('1.4.3 secondary animation padding in use')
    m.put(stub, *code)
    for (off, _), jump in zip(sites, jumps):
        m.put(off, jump)


def patch_realtime(m):
    data = (m.file_size + 0x3fff) & ~0x3fff
    stub = (m.text_end + 15) & ~15
    if data + PAGE != m.size or stub + 16 > ((m.text_end + 0x3fff) & ~0x3fff):
        raise ExportError('1.4.3 frame-step patch layout')
    guards = [(0x3e5658, 0x1e210808), (0x2daa54, 0xbd425260), (0x2daa58, 0x52a84e08), (0x2daa6c, 0x5e21d800),
              (0x2daa70, 0x1e201820), (0x2daa74, 0x1e2c1001), (0x2daa78, 0x1e210800)]
    for off, original in guards:
        if m.word(off) != original:
            raise ExportError('1.4.3 real-time original instruction mismatch')
    if not m.zero(stub, 16):
        raise ExportError('1.4.3 frame-step veneer padding not empty')
    m.put(stub, adrp(8, stub, data), 0xbd400900, 0x1e210808, branch(stub + 12, 0x3e565c))
    words = [branch(0x3e5658, stub), adrp(9, 0x2daa54, data), 0xbd400120, 0xd503201f, 0xd503201f, 0xd503201f, 0xd503201f]
    for (off, _), w in zip(guards, words):
        m.put(off, w)
    patch_secondary_animation(m, data, stub + 176)


def patch_slowmo_bounce(m):
    stub = ((m.text_end + 15) & ~15) + 256
    if stub + 20 > ((m.text_end + 0xfff) & ~0xfff):
        raise ExportError('1.4.3 bounce veneer layout')
    veneer = [0xbd402920, 0xbd403921, 0x1e210800, 0x52a85909, branch(stub + 16, 0x562a6c)]
    word = branch(0x562a64, stub)
    for off, original in [(0x562a64, 0xbd402920), (0x562a68, 0x52a85909), (0x562a6c, 0x1e270121)]:
        if m.word(off) != original:
            raise ExportError('1.4.3 bounce check: original instruction mismatch')
    if not m.zero(stub, len(veneer) * 4):
        raise ExportError('1.4.3 bounce veneer padding not empty')
    m.put(stub, *veneer)
    m.put(0x562a64, word)


ASPECT_DATA_SLOT, ASPECT_STUB = 56, 32


def aspect_install(m, sites, stub_off, data_off):
    page_end = (m.text_end + 0x3fff) & ~0x3fff
    if stub_off < m.text_end or stub_off + ASPECT_STUB * len(sites) > page_end:
        raise ExportError("aspect patch: no room in main's text padding")
    if data_off + ASPECT_DATA_SLOT + 4 > m.size:
        raise ExportError('aspect patch: no data page after main')
    if not m.zero(stub_off, ASPECT_STUB * len(sites)):
        raise ExportError('aspect patch: text padding in use')
    for i, site in enumerate(sites):
        ins = m.word(site)
        if (ins & 0xffe0fc00) != 0x1e201800 and (ins & 0xffc00000) != 0xbd400000:
            raise ExportError('aspect patch: the camera code does not match this game version')
        s = stub_off + ASPECT_STUB * i
        pages = (data_off >> 12) - ((s + 8) >> 12)
        if pages < -(1 << 20) or pages >= (1 << 20):
            raise ExportError('aspect patch: data page out of ADRP range')
        imm = pages & 0x1fffff
        m.put(s, ins, 0xf81f0fea, 0x90000000 | ((imm & 3) << 29) | ((imm >> 2) << 5) | 10,
              0xb9400000 | ((ASPECT_DATA_SLOT // 4) << 10) | (10 << 5) | 10, 0x3400004a,
              0x1e270000 | (10 << 5) | (ins & 31), 0xf84107ea, branch(s + 28, site + 4))
        m.put(site, branch(site, s))


def game_patches(m):
    patch_realtime(m)
    patch_slowmo_bounce(m)
    aspect_install(m, [0x628c74, 0xb43460, 0x1ff04f4, 0x253fbb0], ((m.text_end + 15) & ~15) + 48,
                   (m.file_size + 0x3fff) & ~0x3fff)
    for off, original, _ in FPS60:
        if off + 4 > m.text_end:
            raise ExportError('1.4.3 FPS patch outside text')
        if m.word(off) != original:
            raise ExportError('1.4.3 FPS patch original instruction mismatch')
    for off, _, replacement in FPS60:
        m.put(off, replacement)


def export_text(image, text_end, name):
    """The bytes export_ios_text writes as <name>.x0.bin: [0, page_up(TEXT_END)) after the game patches (main only)."""
    n = page_up(text_end)
    if name != 'main':
        return bytes(image[:n])
    m = Text(image, text_end, len(image))
    game_patches(m)
    return bytes(m.b[:n])
