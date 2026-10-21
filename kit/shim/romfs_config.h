/* TOTK-ipa: the RomFS identity comes from GameData/totk-late.bin at launch (totk_late.c). */
#include "totk_late.h"
#define ROMFS_IMAGE_SIZE (totk_late_romfs_size())
#define ROMFS_IMAGE_SHA256 (totk_late_romfs_sha())
#define ROMFS_INDEX_SHA256 (totk_late_romfs_index_sha())
