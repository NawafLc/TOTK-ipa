/* Runs MacNativeGames' own runtime/game_patches_v143.c the way `export-ios` does (TOTK_EXPORT_IOS set) on a synthetic
   main image and writes main's exported text, so kit/selftest/check_export.py can compare kit/tools/export_v143.py with it.
   usage: export_check <image> <text_end hex> <out> */
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
void runtime_game_patches(Module *m);
_Noreturn void runtime_fail(const char *message) { fprintf(stderr, "FAIL: %s\n", message); exit(1); }
void runtime_oe_push_message(uint32_t message) { (void)message; }
int mfxup_output_enabled(void) { return 0; }
void dm_gfx_set_flag(const char *name, int on) { (void)name; (void)on; }
void runtime_survey_init(Module *m) { (void)m; }
void *runtime_symbol(const char *name) { (void)name; return NULL; }   /* Vert+ only (TOTK_ASPECT_VERT), off here */
int main(int argc, char **argv) {
    if (argc != 4) return 2;
    FILE *f = fopen(argv[1], "rb"); if (!f) return 2;
    fseek(f, 0, SEEK_END); size_t n = (size_t)ftell(f); fseek(f, 0, SEEK_SET);
    Module m = {0}; m.name = "main"; m.file_size = n; m.text_end = strtoull(argv[2], NULL, 16);
    m.size = ((n + 0x3fff) & ~(size_t)0x3fff) + 0x4000;
    void *base = NULL; if (posix_memalign(&base, 0x4000, m.size)) return 2;
    memset(base, 0, m.size); m.base = base;
    if (fread(m.base, 1, n, f) != n) return 2; fclose(f);
    setenv("TOTK_EXPORT_IOS", "1", 1);
    runtime_game_patches(&m);
    size_t x0 = (m.text_end + 0x3fff) & ~(size_t)0x3fff;
    FILE *o = fopen(argv[3], "wb"); if (!o || fwrite(m.base, 1, x0, o) != x0 || fclose(o)) return 2;
    return 0;
}
