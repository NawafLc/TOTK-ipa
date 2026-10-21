/* Reader for GameData/totk-late.bin (format: kit/tools/late_config.py, which writes it). */
#include "totk_late.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#define LATE_MAGIC "TOTKLAT1"
#define HEX 80   /* fixed-size, NUL-terminated text fields */

Module totk_late_modules[TOTK_LATE_MODULES];
IosEmbed totk_late_embed[TOTK_LATE_MODULES];
uint64_t totk_late_probe_plt, totk_late_probe_slot;

static uint8_t *blob;
static size_t blob_size, at;
static uint64_t romfs_size;
static const char *romfs_sha, *romfs_index_sha;
typedef struct { const char *name; uint64_t file_bytes, font_bytes; const char *sha256; } LateFont;
static LateFont fonts[8];
static unsigned font_count;
static pthread_once_t once = PTHREAD_ONCE_INIT;

static void fail(const char *what) {
    fprintf(stderr, "[totk] game data from the import tool (totk-late.bin): %s\n", what);
    runtime_fail("totk-late.bin is missing or does not match this app; run the import tool again");
}
static const void *take(size_t n) {
    if (n > blob_size || at > blob_size - n) fail("truncated");
    const void *p = blob + at; at += n; return p;
}
static uint32_t u32(void) { uint32_t v; memcpy(&v, take(4), 4); return v; }
static uint64_t u64(void) { uint64_t v; memcpy(&v, take(8), 8); return v; }
static const char *text(void) {
    const char *s = take(HEX);
    if (!memchr(s, 0, HEX)) fail("unterminated text field");
    return s;
}
static void *table(size_t count, size_t size) {
    void *p = calloc(count ? count : 1, size);
    if (!p) fail("out of memory");
    return p;
}

static void load(void) {
    char path[4096];
    const char *explicit = getenv("TOTK_LATE"), *romfs = getenv("TOTK_ROMFS");
    if (explicit && *explicit) snprintf(path, sizeof path, "%s", explicit);
    else if (romfs && *romfs) snprintf(path, sizeof path, "%s/../totk-late.bin", romfs);
    else fail("TOTK_ROMFS is not set");
    FILE *f = fopen(path, "rb");
    if (!f) fail("not found next to the RomFS");
    struct stat st;
    if (fstat(fileno(f), &st) || st.st_size < 64 || st.st_size > (512 << 20)) fail("bad size");
    blob_size = (size_t)st.st_size; blob = malloc(blob_size);
    if (!blob || fread(blob, 1, blob_size, f) != blob_size) fail("unreadable");
    fclose(f);
    if (memcmp(take(8), LATE_MAGIC, 8)) fail("not a TOTK-ipa game data file");
    if (u32() != 1) fail("format version");
    if (u32() != TOTK_LATE_MODULES) fail("module count");
    totk_late_probe_plt = u64(); totk_late_probe_slot = u64();
    romfs_size = u64(); romfs_sha = text(); romfs_index_sha = text();
    font_count = u32(); (void)u32();
    if (font_count > sizeof fonts / sizeof *fonts) fail("font count");
    for (unsigned i = 0; i < font_count; i++) {
        fonts[i].name = text(); fonts[i].file_bytes = u64(); fonts[i].font_bytes = u64(); fonts[i].sha256 = text();
    }
    for (unsigned i = 0; i < TOTK_LATE_MODULES; i++) {
        Module *m = &totk_late_modules[i]; IosEmbed *e = &totk_late_embed[i];
        m->name = e->name = text(); m->digest = text();
        m->file_size = u64(); m->text_end = u64(); m->ro_off = u64(); m->data_off = u64(); m->patch_off = u64();
        m->key_off = u64(); m->init = u64(); m->ctor_flag = u64(); m->init_array = u64(); m->init_size = u64();
        m->nsym = u32(); m->nreloc = u32(); m->ngate = u32(); uint32_t strings = u32();
        e->x0 = text(); e->w = text(); e->x1 = text();
        Reloc *r = table(m->nreloc, sizeof *r);
        for (unsigned k = 0; k < m->nreloc; k++) { r[k].where = u64(); r[k].kind = u32(); r[k].symbol = u32(); r[k].addend = (int64_t)u64(); }
        Symbol *s = table(m->nsym, sizeof *s);
        uint32_t *name_at = table(m->nsym, sizeof *name_at);
        for (unsigned k = 0; k < m->nsym; k++) {
            name_at[k] = u32(); s[k].defined = u32(); s[k].binding = u32(); s[k].type = u32(); s[k].value = u64(); s[k].size = u64();
        }
        Gate *g = table(m->ngate, sizeof *g);
        for (unsigned k = 0; k < m->ngate; k++) { g[k].ret = u64(); g[k].original = u64(); g[k].timer = u32(); g[k].arg = u32(); }
        const char *pool = take(strings);
        if (strings && pool[strings - 1]) fail("symbol names");
        for (unsigned k = 0; k < m->nsym; k++) {
            if (name_at[k] >= strings) fail("symbol name offset");
            s[k].name = pool + name_at[k];
        }
        free(name_at);
        m->relocs = r; m->symbols = s; m->gates = g;
    }
    if (at != blob_size) fail("trailing bytes");
    if (strcmp(totk_late_modules[0].name, "main") || strcmp(totk_late_modules[1].name, "subsdk0") || strcmp(totk_late_modules[2].name, "sdk"))
        fail("module order");
    fprintf(stderr, "[totk] game data tables loaded (%zu bytes)\n", blob_size);
}

void totk_late_load(void) { pthread_once(&once, load); }
uint64_t totk_late_romfs_size(void) { totk_late_load(); return romfs_size; }
const char *totk_late_romfs_sha(void) { totk_late_load(); return romfs_sha; }
const char *totk_late_romfs_index_sha(void) { totk_late_load(); return romfs_index_sha; }
void totk_late_fill_fonts(void *rows, size_t row_size, unsigned count) {
    totk_late_load();
    if (row_size != sizeof(LateFont) || count != font_count) fail("shared font table");
    memcpy(rows, fonts, sizeof(LateFont) * count);
}
