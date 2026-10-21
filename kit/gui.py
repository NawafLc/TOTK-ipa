#!/usr/bin/env python3
"""TOTK IPA Builder: the window the Windows installer opens. It asks for everything totk_import.py needs (your base
game, the 1.4.3 update, prod.keys, the system fonts for an NSP base game, where to save the IPA), checks it, then runs
totk_import.py and shows its progress. Nothing is uploaded anywhere: the game files are read on this computer only."""
import json, os, queue, re, shutil, subprocess, sys, threading, time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

KIT = Path(__file__).resolve().parent
TITLE = 'TOTK IPA Builder'
WINDOWS = sys.platform == 'win32'
SETTINGS = Path(os.environ.get('APPDATA') or Path.home() / '.config') / 'TOTK-ipa' / 'settings.json'
STEPS = [('1/4', 'Rewriting the game code for Apple chips'), ('2/4', 'Extracting and verifying the game data (17 GB)'),
         ('3/4', 'Preparing the startup shaders'), ('4/4', 'Building the app and writing the IPA')]


def console_python():
    """python.exe next to pythonw.exe: the build runs without a window of its own, its output comes here."""
    exe = Path(sys.executable)
    if exe.name.lower() == 'pythonw.exe' and exe.with_name('python.exe').exists():
        return exe.with_name('python.exe')
    return exe


def file_kind(path):
    """'xci', 'nsp' or None, by content as build_app.input_kind decides (the name is not used)."""
    try:
        with open(path, 'rb') as f:
            if f.read(4) == b'PFS0':
                return 'nsp'
            f.seek(0x100)
            return 'xci' if f.read(4) == b'HEAD' else None
    except OSError:
        return None


def free_gb(path):
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free / 2**30
    except OSError:
        return None


class Builder(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(TITLE)
        self.minsize(720, 520)
        self.process = None
        self.lines = queue.Queue()
        self.vars = {k: tk.StringVar() for k in ('base', 'update', 'keys', 'fonts', 'out', 'work')}
        self.fonts_kind = tk.StringVar(value='firmware')
        self.load_settings()
        style = ttk.Style(self)
        if WINDOWS and 'vista' in style.theme_names():
            style.theme_use('vista')
        style.configure('Title.TLabel', font=('Segoe UI', 15, 'bold'))
        style.configure('Hint.TLabel', foreground='#555')
        self.pages = ttk.Frame(self, padding=16)
        self.pages.pack(fill='both', expand=True)
        nav = ttk.Frame(self, padding=(16, 0, 16, 16))
        nav.pack(fill='x')
        self.back = ttk.Button(nav, text='< Back', command=lambda: self.show(self.page - 1))
        self.next = ttk.Button(nav, text='Next >', command=self.forward)
        self.cancel = ttk.Button(nav, text='Close', command=self.close)
        self.cancel.pack(side='right')
        self.next.pack(side='right', padx=6)
        self.back.pack(side='right')
        self.frames = [self.page_welcome(), self.page_files(), self.page_output(), self.page_build()]
        self.page = 0
        self.show(0)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.pump)

    # ---- pages ----
    def header(self, frame, title, text):
        ttk.Label(frame, text=title, style='Title.TLabel').pack(anchor='w')
        ttk.Label(frame, text=text, wraplength=660, justify='left').pack(anchor='w', pady=(6, 14))

    def page_welcome(self):
        f = ttk.Frame(self.pages)
        self.header(f, 'Build Tears of the Kingdom for iPhone and iPad',
                    'This makes an IPA from your own copy of the game, using MacNativeGames (the game runs natively on '
                    'Apple chips; it is not an emulator). Everything happens on this computer: your game files and keys '
                    'are never uploaded.')
        need = ('You will need:\n'
                '  •  Base game 1.0.0, dumped from your Switch (.nsp or .xci)\n'
                '  •  The 1.4.3 update, dumped from your Switch (.nsp or .nsz)\n'
                '  •  Your prod.keys, from the same Switch\n'
                '  •  For an .nsp base game: your Switch firmware (or its six system font files)\n'
                '  •  About 80 GB of free disk space, and an hour or two\n\n'
                'Afterwards install the IPA with a sideloading tool such as Sideloadly or AltStore on an iPhone 14 or '
                'newer (or a recent iPad) with iOS/iPadOS 26.\n\n'
                'You must own the game. The IPA contains the game made from your files: it is for your own use only. '
                'Do not share it.')
        ttk.Label(f, text=need, wraplength=660, justify='left').pack(anchor='w')
        return f

    def row(self, parent, label, var, browse, hint=None):
        r = ttk.Frame(parent)
        r.pack(fill='x', pady=4)
        ttk.Label(r, text=label, width=22).pack(side='left')
        ttk.Entry(r, textvariable=var).pack(side='left', fill='x', expand=True)
        ttk.Button(r, text='Browse…', command=browse).pack(side='left', padx=(6, 0))
        if hint:
            ttk.Label(parent, text=hint, style='Hint.TLabel', wraplength=640).pack(anchor='w', padx=(160, 0))
        return r

    def page_files(self):
        f = ttk.Frame(self.pages)
        self.header(f, 'Your game files', 'Choose the files you dumped from your own Switch.')
        games = [('Switch games', '*.nsp *.xci *.nsz'), ('All files', '*.*')]
        self.row(f, 'Base game (1.0.0)', self.vars['base'],
                 lambda: self.pick('base', games), 'The game itself, version 1.0.0: .nsp or .xci')
        self.row(f, 'Update (1.4.3)', self.vars['update'],
                 lambda: self.pick('update', games), 'The 1.4.3 update: .nsp or .nsz')
        self.row(f, 'prod.keys', self.vars['keys'],
                 lambda: self.pick('keys', [('Keys', '*.keys *.txt'), ('All files', '*.*')]), 'Dumped from the same Switch')
        self.fonts_box = ttk.LabelFrame(f, text='System fonts (needed for an .nsp base game)', padding=10)
        self.fonts_box.pack(fill='x', pady=(14, 0))
        kinds = ttk.Frame(self.fonts_box)
        kinds.pack(anchor='w')
        ttk.Radiobutton(kinds, text='Firmware folder (the unpacked .nca files of your Switch firmware)',
                        variable=self.fonts_kind, value='firmware').pack(anchor='w')
        ttk.Radiobutton(kinds, text='Folder with the six shared font files (.bfttf)',
                        variable=self.fonts_kind, value='shared-fonts').pack(anchor='w')
        self.row(self.fonts_box, 'Folder', self.vars['fonts'], lambda: self.pick_dir('fonts'))
        self.fonts_note = ttk.Label(f, text='', style='Hint.TLabel', wraplength=660)
        self.fonts_note.pack(anchor='w', pady=(6, 0))
        self.vars['base'].trace_add('write', lambda *_: self.update_fonts())
        self.update_fonts()
        return f

    def page_output(self):
        f = ttk.Frame(self.pages)
        self.header(f, 'Where to save', 'The IPA is about 18 GB. The work folder keeps intermediate files (about 60 GB); '
                                        'building again reuses them, and you can delete the folder afterwards.')
        self.row(f, 'Save the IPA as', self.vars['out'], self.pick_out)
        self.row(f, 'Work folder', self.vars['work'], lambda: self.pick_dir('work'))
        self.space = ttk.Label(f, text='', style='Hint.TLabel')
        self.space.pack(anchor='w', pady=(10, 0))
        for k in ('work', 'out'):
            self.vars[k].trace_add('write', lambda *_: self.update_space())
        return f

    def page_build(self):
        f = ttk.Frame(self.pages)
        self.status = ttk.Label(f, text='Ready to build', style='Title.TLabel')
        self.status.pack(anchor='w')
        self.step = ttk.Label(f, text='')
        self.step.pack(anchor='w', pady=(4, 6))
        self.bar = ttk.Progressbar(f, mode='determinate', maximum=len(STEPS))
        self.bar.pack(fill='x')
        box = ttk.Frame(f)
        box.pack(fill='both', expand=True, pady=(10, 0))
        self.log = tk.Text(box, height=16, wrap='word', state='disabled', font=('Consolas', 9) if WINDOWS else None)
        scroll = ttk.Scrollbar(box, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.log.pack(side='left', fill='both', expand=True)
        self.after_box = ttk.Frame(f)
        ttk.Button(self.after_box, text='Open the IPA folder', command=self.open_output).pack(side='left')
        ttk.Label(self.after_box, text='Next: install it with Sideloadly or AltStore (keep its entitlements).',
                  style='Hint.TLabel').pack(side='left', padx=10)
        return f

    # ---- navigation ----
    def show(self, n):
        for fr in self.frames:
            fr.pack_forget()
        self.page = n
        self.frames[n].pack(fill='both', expand=True)
        building = n == len(self.frames) - 1
        self.back.configure(state='normal' if 0 < n and not self.process else 'disabled')
        self.next.configure(text='Build' if n == len(self.frames) - 2 else 'Next >', state='disabled' if building else 'normal')
        if n == 2:
            self.defaults()
            self.update_space()

    def forward(self):
        problem = self.check(self.page)
        if problem:
            messagebox.showwarning(TITLE, problem, parent=self)
            return
        if self.page == len(self.frames) - 2:
            self.show(self.page + 1)
            self.start()
        else:
            self.show(self.page + 1)

    def check(self, page):
        v = {k: x.get().strip().strip('"') for k, x in self.vars.items()}
        if page == 1:
            for key, name in (('base', 'base game'), ('update', '1.4.3 update'), ('keys', 'prod.keys')):
                if not v[key] or not Path(v[key]).is_file():
                    return f'Choose your {name} file.'
            kind = file_kind(v['base'])
            if kind is None:
                return 'The base game is not an .nsp or .xci file (compressed .nsz/.xcz base games are not supported).'
            if file_kind(v['update']) != 'nsp':
                return 'The update is not an .nsp or .nsz file.'
            if kind == 'nsp' and not (v['fonts'] and Path(v['fonts']).is_dir()):
                return 'An .nsp base game has no system fonts: choose your firmware folder (or the shared font files).'
        if page == 2:
            if not v['out'].lower().endswith('.ipa'):
                return 'The output must be an .ipa file.'
            if not v['work']:
                return 'Choose a work folder.'
            free = free_gb(v['work'])
            built = Path(v['work'], 'totk/extracted/v143/romfs/romfs.bin').exists()
            if free is not None and free < 80 and not built:
                if not messagebox.askyesno(TITLE, f'The work folder\'s drive has {free:.0f} GB free; about 80 GB are '
                                                  'needed. Try anyway?', parent=self):
                    return 'Choose a work folder on a drive with more free space.'
        return None

    # ---- fields ----
    def pick(self, key, types):
        start = Path(self.vars[key].get() or self.vars['base'].get() or Path.home()).expanduser()
        path = filedialog.askopenfilename(parent=self, filetypes=types, initialdir=start.parent if start.is_file() else start)
        if path:
            self.vars[key].set(str(Path(path)))

    def pick_dir(self, key):
        path = filedialog.askdirectory(parent=self, initialdir=self.vars[key].get() or str(Path.home()))
        if path:
            self.vars[key].set(str(Path(path)))

    def pick_out(self):
        current = Path(self.vars['out'].get() or Path.home() / 'Tears of the Kingdom.ipa')
        path = filedialog.asksaveasfilename(parent=self, defaultextension='.ipa', filetypes=[('iOS app', '*.ipa')],
                                            initialdir=current.parent, initialfile=current.name)
        if path:
            self.vars['out'].set(str(Path(path)))

    def update_fonts(self):
        kind = file_kind(self.vars['base'].get().strip().strip('"'))
        self.fonts_note.configure(text={'xci': 'Your base game is an .xci: it has the system fonts, nothing more needed.',
                                        'nsp': 'Your base game is an .nsp: choose a fonts source below.'}.get(kind, ''))

    def defaults(self):
        base = Path(self.vars['base'].get().strip().strip('"'))
        if not self.vars['out'].get() and base.name:
            self.vars['out'].set(str(base.parent / 'Tears of the Kingdom.ipa'))
        if not self.vars['work'].get() and base.name:
            self.vars['work'].set(str(base.parent / 'TOTK_ipa_build'))

    def update_space(self):
        free = free_gb(self.vars['work'].get() or '.')
        self.space.configure(text='' if free is None else f'Free space on the work folder\'s drive: {free:.0f} GB')

    # ---- build ----
    def start(self):
        self.save_settings()
        v = {k: x.get().strip().strip('"') for k, x in self.vars.items()}
        args = [str(console_python()), '-u', str(KIT / 'totk_import.py'), v['base'], '--update', v['update'], '-k', v['keys'],
                '-o', v['out'], '--work', v['work']]
        if file_kind(v['base']) == 'nsp' and v['fonts']:
            args += [f'--{self.fonts_kind.get()}', v['fonts']]
        env = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1')
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0
        self.write(f'Building {v["out"]}\n')
        self.t0 = time.time()
        self.status.configure(text='Building… (this takes a while; keep this window open)')
        self.cancel.configure(text='Cancel')
        self.back.configure(state='disabled')
        try:
            self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                            env=env, cwd=str(KIT), creationflags=flags, text=True, encoding='utf-8',
                                            errors='replace', bufsize=1)
        except OSError as e:
            self.finish(1, str(e))
            return
        threading.Thread(target=self.reader, daemon=True).start()

    def reader(self):
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def pump(self):
        try:
            while True:
                line = self.lines.get_nowait()
                if line is None:
                    code = self.process.wait()
                    self.finish(code)
                    break
                self.write(line)
                for i, (tag, text) in enumerate(STEPS):
                    if tag in line:
                        self.bar.configure(value=i)
                        self.step.configure(text=f'Step {i + 1} of {len(STEPS)}: {text}')
        except queue.Empty:
            pass
        self.after(150, self.pump)

    def write(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text)
        self.log.see('end')
        self.log.configure(state='disabled')

    def finish(self, code, error=None):
        self.process = None
        self.cancel.configure(text='Close')
        self.back.configure(state='normal')
        minutes = (time.time() - getattr(self, 't0', time.time())) / 60
        if error:
            self.write(f'\n{error}\n')
        if code == 0:
            self.bar.configure(value=len(STEPS))
            self.status.configure(text=f'Done in {minutes:.0f} minutes')
            self.step.configure(text=self.vars['out'].get())
            self.after_box.pack(fill='x', pady=(10, 0))
            messagebox.showinfo(TITLE, 'The IPA is ready.\n\nInstall it with Sideloadly or AltStore. It contains your game: '
                                       'it is for your own use only.', parent=self)
        else:
            text = self.log.get('1.0', 'end')
            last = [l for l in text.splitlines() if re.search(r'ERROR|error|failed|needs|no such|must', l)]
            self.status.configure(text='The build stopped')
            self.step.configure(text=(last[-1] if last else f'exit code {code}')[:160])
            messagebox.showerror(TITLE, 'The build stopped. The log shows why; the logs folder in the work folder has '
                                        'the details. Fix the problem and press Build again: finished steps are reused.',
                                 parent=self)
            self.next.configure(text='Build', state='normal', command=self.rebuild)

    def rebuild(self):
        self.next.configure(text='Build', state='disabled', command=self.forward)
        self.start()

    def stop(self):
        if not self.process:
            return
        if WINDOWS:
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(self.process.pid)], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            self.process.terminate()

    def close(self):
        if self.process:
            if not messagebox.askyesno(TITLE, 'Stop the build? Finished steps are kept for next time.', parent=self):
                return
            self.stop()
            return
        self.save_settings()
        self.destroy()

    def open_output(self):
        folder = Path(self.vars['out'].get()).parent
        if WINDOWS:
            subprocess.run(['explorer', '/select,', self.vars['out'].get()])
        elif sys.platform == 'darwin':
            subprocess.run(['open', folder])
        else:
            subprocess.run(['xdg-open', folder])

    # ---- settings ----
    def load_settings(self):
        try:
            data = json.loads(SETTINGS.read_text())
        except (OSError, ValueError):
            return
        for k, var in self.vars.items():
            if isinstance(data.get(k), str):
                var.set(data[k])
        if data.get('fonts_kind') in ('firmware', 'shared-fonts'):
            self.fonts_kind.set(data['fonts_kind'])

    def save_settings(self):
        try:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(json.dumps({**{k: v.get() for k, v in self.vars.items()}, 'fonts_kind': self.fonts_kind.get()}))
        except OSError:
            pass


def main():
    if sys.version_info < (3, 14):
        tk.Tk().withdraw()
        messagebox.showerror(TITLE, 'This needs Python 3.14 or newer.')
        return
    Builder().mainloop()


if __name__ == '__main__':
    main()
