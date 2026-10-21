#!/usr/bin/env python3
"""Fill the app shell's empty game-module sections and sign the executable again (ad hoc).

The shell (kit/build_shell.py) is linked with a 16 KiB placeholder per section in kit/shim/embed.S. Here each section is
given the player's bytes: the __TOTK* segments are laid out again with the new section sizes, __LINKEDIT moves behind
them, and the code signature is rebuilt with the same identifier, special slots, requirements and entitlements (only
the page hashes change). Nothing else in the executable points into the __TOTK* segments: the loader finds them with
getsectiondata(), so moving them is safe. A layout with anything but __TOTK* segments between them and __LINKEDIT, or
with fixups in them, is refused rather than guessed at.

    macho.py fill <executable> <section-spec>...   (section-spec: SEGMENT,SECTION=file)
    macho.py info <executable>
"""
import hashlib, struct, sys
from pathlib import Path

MH_MAGIC_64 = 0xfeedfacf
LC_SEGMENT_64, LC_SYMTAB, LC_DYSYMTAB, LC_CODE_SIGNATURE = 0x19, 0x2, 0xb, 0x1d
LC_DYLD_INFO, LC_DYLD_INFO_ONLY = 0x22, 0x80000022
LC_DYLD_CHAINED_FIXUPS = 0x80000034
LINKEDIT_DATA = {0x1d, 0x1e, 0x26, 0x29, 0x2b, 0x2e, 0x36, 0x80000033, 0x80000034}
SEG_PAGE = 0x4000
CSMAGIC_EMBEDDED_SIGNATURE, CSMAGIC_CODEDIRECTORY = 0xfade0cc0, 0xfade0c02


class MachOError(Exception):
    pass


def align(x, a):
    return (x + a - 1) & ~(a - 1)


def cstr(b):
    return b.split(b'\0', 1)[0].decode()


class Section:
    def __init__(self, data, off):
        (self.sectname, self.segname, self.addr, self.size, self.offset, self.align, self.reloff, self.nreloc,
         self.flags, self.r1, self.r2, self.r3) = struct.unpack_from('<16s16sQQIIIIIIII', data, off)
        self.lc_off = off
        self.name = (cstr(self.segname), cstr(self.sectname))

    def pack(self):
        return struct.pack('<16s16sQQIIIIIIII', self.sectname, self.segname, self.addr, self.size, self.offset, self.align,
                           self.reloff, self.nreloc, self.flags, self.r1, self.r2, self.r3)


class Segment:
    def __init__(self, data, off):
        (_, _, self.segname, self.vmaddr, self.vmsize, self.fileoff, self.filesize, self.maxprot, self.initprot,
         self.nsects, self.flags) = struct.unpack_from('<II16sQQQQiiII', data, off)
        self.lc_off = off
        self.name = cstr(self.segname)
        self.sections = [Section(data, off + 72 + 80 * i) for i in range(self.nsects)]

    def pack_into(self, buf):
        struct.pack_into('<QQQQ', buf, self.lc_off + 24, self.vmaddr, self.vmsize, self.fileoff, self.filesize)
        for s in self.sections:
            buf[s.lc_off:s.lc_off + 80] = s.pack()


class MachO:
    def __init__(self, data):
        self.data = bytearray(data)
        magic, _, _, _, self.ncmds, self.sizeofcmds, _, _ = struct.unpack_from('<IiiIIIII', self.data, 0)
        if magic != MH_MAGIC_64:
            raise MachOError('not a thin 64-bit Mach-O executable')
        self.segments, self.cmds = [], []
        off = 32
        for _ in range(self.ncmds):
            cmd, size = struct.unpack_from('<II', self.data, off)
            self.cmds.append((cmd, off, size))
            if cmd == LC_SEGMENT_64:
                self.segments.append(Segment(self.data, off))
            off += size

    def cmd(self, which):
        found = [c for c in self.cmds if c[0] == which]
        return found[0] if found else None

    def section_index(self):
        """1-based section numbers as nlist n_sect counts them -> Section."""
        out, n = {}, 1
        for seg in self.segments:
            for s in seg.sections:
                out[n] = s
                n += 1
        return out


def parse_signature(blob):
    magic, length, count = struct.unpack_from('>III', blob, 0)
    if magic != CSMAGIC_EMBEDDED_SIGNATURE:
        raise MachOError('the executable has no embedded code signature (the shell is signed ad hoc by kit/build_shell.py)')
    entries = []
    for i in range(count):
        typ, off = struct.unpack_from('>II', blob, 12 + 8 * i)
        _, blen = struct.unpack_from('>II', blob, off)
        entries.append((typ, bytes(blob[off:off + blen])))
    return entries


def rebuild_code_directory(cd, code):
    """The same CodeDirectory with page hashes of `code` (the file up to the signature)."""
    (magic, length, version, flags, hash_off, ident_off, n_special, n_code, code_limit, hash_size, hash_type, platform,
     page_log) = struct.unpack_from('>IIIIIIIIIBBBB', cd, 0)
    if magic != CSMAGIC_CODEDIRECTORY:
        raise MachOError('unexpected code directory')
    if hash_off + n_code * hash_size != length:
        raise MachOError('code directory layout: page hashes are not its last part')
    if version >= 0x20300 and struct.unpack_from('>Q', cd, 0x38)[0]:
        raise MachOError('64-bit code limit is not supported')
    algo = {1: hashlib.sha1, 2: hashlib.sha256, 3: hashlib.sha256, 4: hashlib.sha384}.get(hash_type)
    if not algo:
        raise MachOError(f'code directory hash type {hash_type}')
    page = 1 << page_log if page_log else len(code)
    hashes = b''.join(algo(code[i:i + page]).digest()[:hash_size] for i in range(0, len(code), page))
    n = len(hashes) // hash_size
    new = bytearray(cd[:hash_off]) + hashes
    struct.pack_into('>I', new, 4, len(new))
    struct.pack_into('>II', new, 28, n, len(code))
    return bytes(new)


def build_signature(entries, code):
    blobs = [(t, rebuild_code_directory(b, code) if t == 0 or 0x1000 <= t < 0x2000 else b) for t, b in entries]
    header = 12 + 8 * len(blobs)
    out = bytearray(struct.pack('>III', CSMAGIC_EMBEDDED_SIGNATURE, 0, len(blobs)))
    off = header
    for t, b in blobs:
        out += struct.pack('>II', t, off)
        off += len(b)
    for _, b in blobs:
        out += b
    struct.pack_into('>I', out, 4, len(out))
    return bytes(out)


def fill(path, contents):
    """contents: {(segment, section): bytes}. Rewrites the executable in place."""
    path = Path(path)
    m = MachO(path.read_bytes())
    data = m.data
    names = [s.name for s in m.segments]
    first = next((i for i, n in enumerate(names) if n.startswith('__TOTK')), None)
    if first is None:
        raise MachOError('no __TOTK* segments: not a TOTK-ipa app shell')
    tail = names[first:]
    if tail[-1] != '__LINKEDIT' or any(not n.startswith('__TOTK') for n in tail[:-1]):
        raise MachOError(f'unsupported segment order after the game sections: {tail}')
    moved = m.segments[first:-1]
    linkedit = m.segments[-1]
    by_name = {s.name: s for seg in moved for s in seg.sections}
    unknown = set(contents) - set(by_name)
    if unknown:
        raise MachOError(f'no such placeholder section: {sorted(unknown)}')
    # fixups (chained or opcode-based) inside a moved segment would need rewriting; the shell has none
    fx = m.cmd(LC_DYLD_CHAINED_FIXUPS)
    if fx:
        dataoff, = struct.unpack_from('<I', data, fx[1] + 8)
        starts, = struct.unpack_from('<I', data, dataoff + 4)
        seg_count, = struct.unpack_from('<I', data, dataoff + starts)
        for i in range(seg_count):
            info, = struct.unpack_from('<I', data, dataoff + starts + 4 + 4 * i)
            if info and i >= first and i < len(m.segments) - 1:
                raise MachOError(f'segment {names[i]} has fixups; it cannot be moved')
    if m.cmd(LC_DYLD_INFO) or m.cmd(LC_DYLD_INFO_ONLY):
        c = m.cmd(LC_DYLD_INFO) or m.cmd(LC_DYLD_INFO_ONLY)
        if any(struct.unpack_from('<10I', data, c[1] + 8)[0:8:2]):
            raise MachOError('opcode-based rebase/bind information is not supported')
    sig_cmd = m.cmd(LC_CODE_SIGNATURE)
    if not sig_cmd:
        raise MachOError('the executable is not signed')
    sig_off, sig_size = struct.unpack_from('<II', data, sig_cmd[1] + 8)
    if sig_off + sig_size != len(data) or not linkedit.fileoff <= sig_off:
        raise MachOError('the code signature is not at the end of __LINKEDIT')
    entries = parse_signature(data[sig_off:sig_off + sig_size])

    # lay the moved segments out again, section by section, in their original order
    old_addr = {s.name: (s.addr, s.offset, s.size) for seg in moved for s in seg.sections}
    vm, fo = moved[0].vmaddr, moved[0].fileoff
    if vm % SEG_PAGE or fo % SEG_PAGE:
        raise MachOError('game segments are not page aligned')
    region = bytearray()
    for seg in moved:
        seg.vmaddr, seg.fileoff = vm, fo
        cursor = 0
        for s in seg.sections:
            body = contents.get(s.name)
            if body is None:
                a, o, z = old_addr[s.name]
                body = bytes(data[o:o + z])
            cursor = align(cursor, 1 << s.align)
            s.addr, s.offset, s.size = vm + cursor, fo + cursor, len(body)
            region += bytes(fo + cursor - (moved[0].fileoff + len(region))) + body
            cursor += len(body)
        size = align(cursor, SEG_PAGE)
        region += bytes(fo + size - (moved[0].fileoff + len(region)))
        seg.vmsize = seg.filesize = size
        vm += size
        fo += size
    delta = fo - linkedit.fileoff
    old_linkedit_off = linkedit.fileoff
    linkedit_body = bytes(data[old_linkedit_off:sig_off])
    linkedit.vmaddr, linkedit.fileoff = vm, fo

    # symbols that point into a moved section follow it
    st = m.cmd(LC_SYMTAB)
    if st:
        symoff, nsyms, stroff, strsize = struct.unpack_from('<IIII', data, st[1] + 8)
        index = m.section_index()
        body = bytearray(linkedit_body)
        for i in range(nsyms):
            at = symoff - old_linkedit_off + 16 * i
            n_type, n_sect = body[at + 4], body[at + 5]
            if n_type & 0x0e == 0x0e and n_sect in index and index[n_sect].name in old_addr:
                value, = struct.unpack_from('<Q', body, at + 8)
                struct.pack_into('<Q', body, at + 8, value - old_addr[index[n_sect].name][0] + index[n_sect].addr)
        linkedit_body = bytes(body)

    header = bytearray(data[:moved[0].fileoff])   # load commands, __TEXT and __DATA: unchanged bytes
    # every offset into __LINKEDIT moves by delta
    for cmd, off, _ in m.cmds:
        if cmd in LINKEDIT_DATA and cmd != LC_CODE_SIGNATURE:
            d, z = struct.unpack_from('<II', header, off + 8)
            if z:
                struct.pack_into('<I', header, off + 8, d + delta)
        elif cmd == LC_SYMTAB:
            vals = list(struct.unpack_from('<IIII', header, off + 8))
            vals[0] += delta if vals[1] else 0
            vals[2] += delta if vals[3] else 0
            struct.pack_into('<IIII', header, off + 8, *vals)
        elif cmd == LC_DYSYMTAB:
            vals = list(struct.unpack_from('<18I', header, off + 8))
            for k in (6, 8, 10, 12, 14, 16):
                if vals[k + 1]:
                    vals[k] += delta
            struct.pack_into('<18I', header, off + 8, *vals)
    new_sig_off = align(linkedit.fileoff + len(linkedit_body), 16)
    pad = new_sig_off - (linkedit.fileoff + len(linkedit_body))
    # the signature's size depends only on the page count, so it is known before hashing
    pages_probe = build_signature(entries, bytes(new_sig_off))
    sig_len = align(len(pages_probe), 16)
    struct.pack_into('<II', header, sig_cmd[1] + 8, new_sig_off, sig_len)
    linkedit.filesize = new_sig_off + sig_len - linkedit.fileoff
    linkedit.vmsize = align(linkedit.filesize, SEG_PAGE)
    for seg in moved + [linkedit]:
        seg.pack_into(header)
    code = bytes(header) + bytes(region) + linkedit_body + bytes(pad)
    if len(code) != new_sig_off:
        raise MachOError('internal layout error')
    sig = build_signature(entries, code)
    sig += bytes(sig_len - len(sig))
    tmp = path.with_name(path.name + '.filling')
    tmp.write_bytes(code + sig)
    tmp.chmod(path.stat().st_mode)
    tmp.replace(path)


def info(path):
    m = MachO(Path(path).read_bytes())
    for seg in m.segments:
        print(f'{seg.name:16} vm {seg.vmaddr:#014x} +{seg.vmsize:#x} file {seg.fileoff:#x} +{seg.filesize:#x}')
        for s in seg.sections:
            print(f'    {s.name[1]:16} {s.addr:#014x} +{s.size:#x} @{s.offset:#x} align 2^{s.align}')


def main(argv):
    if len(argv) >= 2 and argv[0] == 'info':
        info(argv[1])
        return
    if len(argv) < 3 or argv[0] != 'fill':
        raise SystemExit(__doc__)
    contents = {}
    for spec in argv[2:]:
        name, file = spec.split('=', 1)
        seg, sect = name.split(',')
        contents[(seg, sect)] = Path(file).read_bytes()
    fill(argv[1], contents)


if __name__ == '__main__':
    main(sys.argv[1:])
