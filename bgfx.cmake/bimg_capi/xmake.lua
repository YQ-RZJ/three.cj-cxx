set_project("bimg_capi")
set_languages("c11", "cxx17")
add_rules("mode.debug", "mode.release")

-- Custom platform option
option("bx_platform")
    set_default("LINUX")
    set_showmenu(true)
    set_description("Target platform: LINUX, WINDOWS, ANDROID, BSD, EMSCRIPTEN, IOS, OSX")
option_end()

option("libtype")
    set_default("static")
    set_showmenu(true)
    set_values("static", "shared")
    set_description("Library type: static / shared")
option_end()

-- Common defines
add_defines("__STDC_LIMIT_MACROS", "__STDC_FORMAT_MACROS", "__STDC_CONSTANT_MACROS")

-- Include dirs based on platform
if is_config("bx_platform", "WINDOWS") then
    if is_config("toolchain", "msvc") then
        add_includedirs(
            "../bx/include/compat/msvc",
            "../bimg/include",
            "../bimg/3rdparty",
            "../bimg/3rdparty/astc-encoder/include",
            "../bimg/3rdparty/tinyexr/deps/miniz",
            "../bx/include"
        )
    else
        add_includedirs(
            "../bx/include/compat/mingw",
            "../bimg/include",
            "../bimg/3rdparty",
            "../bimg/3rdparty/astc-encoder/include",
            "../bimg/3rdparty/tinyexr/deps/miniz",
            "../bx/include"
        )
    end
else
    -- LINUX, ANDROID, etc.
    add_includedirs(
        "../bx/include/compat/linux",
        "../bimg/include",
        "../bimg/3rdparty",
        "../bimg/3rdparty/astc-encoder/include",
        "../bimg/3rdparty/tinyexr/deps/miniz",
        "../bx/include"
    )
end

-- Common flags
add_cxflags("-Wall", "-Wextra", "-Wshadow", "-Wunused-value", "-Wundef")
-- 非 MSVC 工具链：shared 目标必须 -fPIC；xmake 的 flag 检查会忽略普通写法的 -fPIC，需 force
if not is_config("toolchain", "msvc") then
    add_cxflags("-fPIC", {force = true})
end
add_cxxflags("-fno-rtti", "-fno-exceptions")

-- Debug/Release
if is_mode("debug") then
    add_defines("_DEBUG", "BX_CONFIG_DEBUG=1")
    add_cxflags("-g")
else
    add_defines("NDEBUG", "BX_CONFIG_DEBUG=0")
    add_cxflags("-O3", "-g")
end

if is_arch("x86_64") then
    set_targetdir("../output/bgfx/Lib/x86_64")
elseif is_arch("arm64-v8a") then
    set_targetdir("../output/bgfx/Lib/arm64-v8a")
end

-- Target: static library for bimg C API wrapper
target("bimg_capi")
    set_kind(is_config("libtype", "shared") and "shared" or "static")
    add_links("bimg", "bimg_decode", "bimg_encode", "bx")
    if is_arch("x86_64") then
        add_linkdirs("../output/bgfx/Lib/x86_64")
    elseif is_arch("arm64-v8a") then
        add_linkdirs("../output/bgfx/Lib/arm64-v8a")
    end
    -- Windows 动态库导出符号：MSVC 用 export_all 规则（等价 CMake 的 WINDOWS_EXPORT_ALL_SYMBOLS）；
    -- mingw 下源码含 __declspec(dllexport)（如 bgfx.cpp 的 GPU 变量）时 ld 会禁用自动导出，需强制全导出
    if is_config("libtype", "shared") and is_plat("windows") then
        if is_config("toolchain", "msvc") then
            add_rules("utils.symbols.export_all")
        else
            add_shflags("-Wl,--export-all-symbols")
        end
    end

    add_files(
        "bimg_capi.cpp"
    )
