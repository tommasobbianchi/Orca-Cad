// Provides the single-header NanoSVG implementation symbols that NSVGUtils.o
// (inside libslic3r.a) references. The GUI supplies these from BitmapCache.cpp
// and the tests from their own #define; libslic3r.a does NOT contain them, so a
// minimal consumer must compile them itself.
//
// Only the parse/delete path is needed here (NSVGUtils.cpp uses nsvgParseFromFile,
// nsvgParse, nsvgDelete). NANOSVGRAST_IMPLEMENTATION (nanosvgrast.h) is NOT
// required unless a rasterizer is later used.
#define NANOSVG_IMPLEMENTATION
#include "nanosvg/nanosvg.h"
