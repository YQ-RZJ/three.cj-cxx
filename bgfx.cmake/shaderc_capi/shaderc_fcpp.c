/*
 * fcpp unified compilation wrapper.
 * The fcpp preprocessor source files are designed to be compiled together
 * as a single translation unit. Compiling them separately causes static
 * functions to be invisible across translation units, leading to linker errors.
 */
#include "../bgfx/3rdparty/fcpp/cpp1.c"
#include "../bgfx/3rdparty/fcpp/cpp2.c"
#include "../bgfx/3rdparty/fcpp/cpp3.c"
#include "../bgfx/3rdparty/fcpp/cpp4.c"
#include "../bgfx/3rdparty/fcpp/cpp5.c"
#include "../bgfx/3rdparty/fcpp/cpp6.c"