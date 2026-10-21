/* Prints what kit/shim/totk_late.c reads from a totk-late.bin, for late_roundtrip.py. */
#include "totk_late.h"
#include <stdio.h>
#include <stdlib.h>
_Noreturn void runtime_fail(const char *message) { fprintf(stderr, "FAIL: %s\n", message); exit(1); }
typedef struct { const char *path; uint64_t file_bytes, font_bytes; const char *sha256; } FontRow;
int main(void) {
    totk_late_load();
    printf("probe %llu %llu\nromfs %llu %s %s\n", (unsigned long long)totk_late_probe_plt, (unsigned long long)totk_late_probe_slot,
           (unsigned long long)totk_late_romfs_size(), totk_late_romfs_sha(), totk_late_romfs_index_sha());
    FontRow rows[6]; totk_late_fill_fonts(rows, sizeof rows[0], 6);
    for (int i = 0; i < 6; i++) printf("font %s %llu %llu %s\n", rows[i].path, (unsigned long long)rows[i].file_bytes, (unsigned long long)rows[i].font_bytes, rows[i].sha256);
    for (int i = 0; i < TOTK_LATE_MODULES; i++) {
        Module *m = &totk_late_modules[i]; IosEmbed *e = &totk_late_embed[i];
        printf("module %s %s %zu %llu %llu %llu %llu %llu %llu %llu %llu %llu %s %s %s\n", m->name, m->digest, m->file_size,
               (unsigned long long)m->text_end, (unsigned long long)m->ro_off, (unsigned long long)m->data_off, (unsigned long long)m->patch_off,
               (unsigned long long)m->key_off, (unsigned long long)m->init, (unsigned long long)m->ctor_flag, (unsigned long long)m->init_array,
               (unsigned long long)m->init_size, e->x0, e->w, e->x1);
        for (unsigned k = 0; k < m->nreloc; k++) printf("reloc %llu %u %u %lld\n", (unsigned long long)m->relocs[k].where, m->relocs[k].kind, m->relocs[k].symbol, (long long)m->relocs[k].addend);
        for (unsigned k = 0; k < m->nsym; k++) printf("sym %s %llu %llu %u %u %u\n", m->symbols[k].name, (unsigned long long)m->symbols[k].value, (unsigned long long)m->symbols[k].size, m->symbols[k].defined, m->symbols[k].binding, m->symbols[k].type);
        for (unsigned k = 0; k < m->ngate; k++) printf("gate %llu %llu %u %u\n", (unsigned long long)m->gates[k].ret, (unsigned long long)m->gates[k].original, m->gates[k].timer, m->gates[k].arg);
    }
    return 0;
}
