#!/usr/bin/env python3
"""Open the builder window, walk its pages with synthetic files and check what it asks for, without building."""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['APPDATA'] = tempfile.mkdtemp()   # no saved settings from a previous run
import gui


def main():
    tmp = Path(tempfile.mkdtemp())
    nsp, xci, keys = tmp / 'base.nsp', tmp / 'base.xci', tmp / 'prod.keys'
    nsp.write_bytes(b'PFS0' + bytes(0x200))
    xci.write_bytes(bytes(0x100) + b'HEAD' + bytes(0x100))
    keys.write_text('header_key = 00\n')
    w = gui.Builder()
    w.withdraw()
    w.update()
    w.show(1)
    assert w.check(1) == 'Choose your base game file.'
    w.vars['base'].set(str(nsp)); w.vars['update'].set(str(nsp)); w.vars['keys'].set(str(keys))
    w.update()
    assert 'fonts' in (w.check(1) or ''), w.check(1)
    assert '.nsp' in w.fonts_note.cget('text')
    w.vars['fonts'].set(str(tmp))
    assert w.check(1) is None, w.check(1)
    w.vars['base'].set(str(xci)); w.vars['fonts'].set('')
    w.update()
    assert w.check(1) is None, w.check(1)
    assert '.xci' in w.fonts_note.cget('text')
    w.show(2)
    assert w.vars['out'].get() == str(tmp / 'Tears of the Kingdom.ipa'), w.vars['out'].get()
    assert w.vars['work'].get() == str(tmp / 'TOTK_ipa_build')
    w.vars['out'].set(str(tmp / 'x.zip'))
    assert 'ipa' in w.check(2)
    w.show(3)
    w.write('log line\n')
    w.update()
    w.save_settings()
    w.destroy()
    print('builder window: pages, file checks and defaults behave')


if __name__ == '__main__':
    main()
