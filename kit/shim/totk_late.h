/* TOTK-ipa late binding: the values build_ipa.py compiles into the app from the player's own game files (module tables,
   RomFS and shared-font identities, embedded-code hashes) are read at launch from GameData/totk-late.bin instead, which
   the import tool (kit/tools/totk_import.py) writes on the player's computer. The app shell is then built without any
   game file. */
#pragma once
#include <setjmp.h>   /* runtime.h names sigjmp_buf */
#include "runtime.h"

#define TOTK_LATE_MODULES 3
extern Module totk_late_modules[TOTK_LATE_MODULES];
typedef struct { const char *name, *x0, *w, *x1; } IosEmbed;
extern IosEmbed totk_late_embed[TOTK_LATE_MODULES];
extern uint64_t totk_late_probe_plt, totk_late_probe_slot;

void totk_late_load(void);   /* idempotent; stops the start with a message when the file is missing or malformed */
uint64_t totk_late_romfs_size(void);
const char *totk_late_romfs_sha(void);
const char *totk_late_romfs_index_sha(void);
/* Fills shared_font.c's rows: {const char *path; uint64_t file_bytes, font_bytes; const char *sha256;} x count. */
void totk_late_fill_fonts(void *rows, size_t row_size, unsigned count);
