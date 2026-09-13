set_project("geometryc_capi")
set_languages("cxx17")
add_rules("mode.debug", "mode.release")

-- Custom platform option, passed via --bx_platform=WINDOWS
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

-- Platform-dependent compat include dirs
if is_config("bx_platform", "WINDOWS") then
    if is_config("toolchain", "msvc") then
        add_includedirs(
            "../bx/include/compat/msvc",
            "../bx/include",
            "../bgfx/include",
            "../bgfx/src",
            "../bgfx/3rdparty"
        )
    else
        add_includedirs(
            "../bx/include/compat/mingw",
            "../bx/include",
            "../bgfx/include",
            "../bgfx/src",
            "../bgfx/3rdparty"
        )
    end
elseif is_config("bx_platform", "BSD") then
    add_includedirs(
        "../bx/include/compat/freebsd",
        "../bx/include",
        "../bgfx/include",
        "../bgfx/src",
        "../bgfx/3rdparty"
    )
elseif is_config("bx_platform", "IOS") then
    add_includedirs(
        "../bx/include/compat/ios",
        "../bx/include",
        "../bgfx/include",
        "../bgfx/src",
        "../bgfx/3rdparty"
    )
elseif is_config("bx_platform", "OSX") then
    add_includedirs(
        "../bx/include/compat/osx",
        "../bx/include",
        "../bgfx/include",
        "../bgfx/src",
        "../bgfx/3rdparty"
    )
else
    -- LINUX, ANDROID, EMSCRIPTEN
    add_includedirs(
        "../bx/include/compat/linux",
        "../bx/include",
        "../bgfx/include",
        "../bgfx/src",
        "../bgfx/3rdparty"
    )
end

-- Common compiler flags
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

-- Determine output architecture directory
local arch_dir = ""
if is_arch("x86_64") then
    arch_dir = "x86_64"
elseif is_arch("arm64-v8a") then
    arch_dir = "arm64-v8a"
end

if arch_dir ~= "" then
    set_targetdir("../output/bgfx/Lib/" .. arch_dir)
end

-- Target: static library
target("geometryc_capi")
    set_kind(is_config("libtype", "shared") and "shared" or "static")
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
        "geometryc_capi.cpp"
        -- geometryc.cpp is included via #include in geometryc_capi.cpp
    )

    -- Add meshoptimizer source files (required by geometryc for vertex cache optimization)
    add_files(
        "../bgfx/3rdparty/meshoptimizer/src/allocator.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/clusterizer.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/indexcodec.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/indexgenerator.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/indexanalyzer.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/overdrawoptimizer.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/partition.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/quantization.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/rasterizer.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/simplifier.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/spatialorder.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/stripifier.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/vcacheoptimizer.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/vertexcodec.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/vertexfilter.cpp",
        "../bgfx/3rdparty/meshoptimizer/src/vfetchoptimizer.cpp"
    )

    -- Link against pre-built bgfx / bx libraries
    add_links("bgfx", "bx")
    if arch_dir ~= "" then
        add_linkdirs("../output/bgfx/Lib/" .. arch_dir)
    end