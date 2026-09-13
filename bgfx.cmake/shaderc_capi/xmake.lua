set_project("shaderc_capi")
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

-- Platform-dependent compat include dirs + all 3rdparty paths needed by shaderc
if is_config("bx_platform", "WINDOWS") then
    add_defines("BX_PLATFORM_WINDOWS=1")
    if is_config("toolchain", "msvc") then
        add_includedirs(
            "../bx/include/compat/msvc",
            "../bx/include",
            "../bgfx/include",
            "../bgfx/src",
            "../bgfx/3rdparty",
            "../bgfx/3rdparty/fcpp",
            "../bgfx/3rdparty/glslang",
            "../bgfx/3rdparty/spirv-cross",
            "../bgfx/3rdparty/spirv-headers/include",
            "../bgfx/3rdparty/spirv-tools/include",
            "../bgfx/3rdparty/glsl-optimizer/include",
            "../bgfx/3rdparty/directx-headers/include",
            "../bgfx/3rdparty/directx-headers/include/directx",
            "../shaderc"  -- for shaderc.h
        )
    else
        add_includedirs(
            "../bx/include/compat/mingw",
            "../bx/include",
            "../bgfx/include",
            "../bgfx/src",
            "../bgfx/3rdparty",
            "../bgfx/3rdparty/fcpp",
            "../bgfx/3rdparty/glslang",
            "../bgfx/3rdparty/spirv-cross",
            "../bgfx/3rdparty/spirv-headers/include",
            "../bgfx/3rdparty/spirv-tools/include",
            "../bgfx/3rdparty/glsl-optimizer/include",
            "../bgfx/3rdparty/directx-headers/include",
            "../bgfx/3rdparty/directx-headers/include/directx",
            "../shaderc"  -- for shaderc.h
        )
    end
elseif is_config("bx_platform", "BSD") then
    add_includedirs(
        "../bx/include/compat/freebsd",
        "../bx/include",
        "../bgfx/include",
        "../bgfx/src",
        "../bgfx/3rdparty",
        "../bgfx/3rdparty/fcpp",
        "../bgfx/3rdparty/glslang",
        "../bgfx/3rdparty/spirv-cross",
        "../bgfx/3rdparty/spirv-headers/include",
        "../bgfx/3rdparty/spirv-tools/include",
        "../bgfx/3rdparty/glsl-optimizer/include",
        "../bgfx/3rdparty/directx-headers/include",
        "../bgfx/3rdparty/directx-headers/include/directx",
        "../shaderc"
    )
elseif is_config("bx_platform", "IOS") then
    add_includedirs(
        "../bx/include/compat/ios",
        "../bx/include",
        "../bgfx/include",
        "../bgfx/src",
        "../bgfx/3rdparty",
        "../bgfx/3rdparty/fcpp",
        "../bgfx/3rdparty/glslang",
        "../bgfx/3rdparty/spirv-cross",
        "../bgfx/3rdparty/spirv-headers/include",
        "../bgfx/3rdparty/spirv-tools/include",
        "../bgfx/3rdparty/glsl-optimizer/include",
        "../bgfx/3rdparty/directx-headers/include",
        "../bgfx/3rdparty/directx-headers/include/directx",
        "../shaderc"
    )
elseif is_config("bx_platform", "OSX") then
    add_includedirs(
        "../bx/include/compat/osx",
        "../bx/include",
        "../bgfx/include",
        "../bgfx/src",
        "../bgfx/3rdparty",
        "../bgfx/3rdparty/fcpp",
        "../bgfx/3rdparty/glslang",
        "../bgfx/3rdparty/spirv-cross",
        "../bgfx/3rdparty/spirv-headers/include",
        "../bgfx/3rdparty/spirv-tools/include",
        "../bgfx/3rdparty/glsl-optimizer/include",
        "../bgfx/3rdparty/directx-headers/include",
        "../bgfx/3rdparty/directx-headers/include/directx",
        "../shaderc"
    )
else
    -- LINUX, ANDROID, EMSCRIPTEN
    add_includedirs(
        "../bx/include/compat/linux",
        "../bx/include",
        "../bgfx/include",
        "../bgfx/src",
        "../bgfx/3rdparty",
        "../bgfx/3rdparty/fcpp",
        "../bgfx/3rdparty/glslang",
        "../bgfx/3rdparty/spirv-cross",
        "../bgfx/3rdparty/spirv-headers/include",
        "../bgfx/3rdparty/spirv-tools/include",
        "../bgfx/3rdparty/glsl-optimizer/include",
        "../bgfx/3rdparty/directx-headers/include",
        "../bgfx/3rdparty/directx-headers/include/directx",
        "../shaderc"
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
    -- release 不带 -g：glslang/spirv-tools/spirv-cross/glsl-optimizer 四套第三方库
    -- 模板密集，-g 产生的 .debug_* 段占单个 .o 88-99%，会把 .a 撑到 300MB+。
    -- 需要调试本库时临时改回 -g。
    add_cxflags("-O3")
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

-- =============================================================================
-- Platform → Backend mapping
-- =============================================================================
-- Each platform can only produce shaders for its own rendering backends.
-- Weak stubs in shaderc_backend_stubs.cpp provide fallback implementations
-- for backends that are not compiled for the target platform.
--
--   WINDOWS:     HLSL, DXIL, SPIR-V
--   LINUX:       GLSL, SPIR-V
--   ANDROID:     ESSL, SPIR-V
--   IOS:         Metal, GLSL, SPIR-V
--   OSX:         Metal, GLSL, SPIR-V
--   EMSCRIPTEN:  ESSL, WGSL
--   BSD:         GLSL, SPIR-V
-- =============================================================================

-- Determine which backend files to compile based on target platform
local backend_files = {}

if is_config("bx_platform", "WINDOWS") then
    -- Windows: HLSL, DXIL, SPIR-V
    -- HLSL/DXIL need D3DCompiler/DXC SDKs (d3dcompiler.h, dxcapi.h).
    -- D3DCompiler is loaded dynamically at runtime via d3dcompiler_47.dll
    -- (available on Windows 8.1+). Only the header is needed at build time.
    -- glslang=0：MinGW 下 glslang 的 sprintf_s 是 UCRT 符号，与 msvcrt 冲突；
    -- SPIR-V 后端走 shaderc_spirv.cpp 的 stub（HLSL 是 Windows 主后端）。
    add_defines(
        "SHADERC_CONFIG_HAS_D3DCOMPILER=1",
        "SHADERC_CONFIG_HAS_DXC=0",
        "SHADERC_CONFIG_HAS_GLSL_OPTIMIZER=0",
        "SHADERC_CONFIG_HAS_GLSLANG=0"
    )
    backend_files = {
        "../shaderc/shaderc_hlsl.cpp",
        "../shaderc/shaderc_spirv.cpp",
    }
elseif is_config("bx_platform", "IOS") or is_config("bx_platform", "OSX") then
    -- Apple: Metal, GLSL, SPIR-V
    add_defines(
        "SHADERC_CONFIG_HAS_GLSL_OPTIMIZER=0",
        "SHADERC_CONFIG_HAS_GLSLANG=0"
    )
    backend_files = {
        "../shaderc/shaderc_metal.cpp",
        "../shaderc/shaderc_spirv.cpp",
    }
elseif is_config("bx_platform", "EMSCRIPTEN") then
    -- Web: ESSL (via GLSL path), WGSL
    add_defines(
        "SHADERC_CONFIG_HAS_GLSL_OPTIMIZER=0",
        "SHADERC_CONFIG_HAS_GLSLANG=0"
    )
    backend_files = {
        "../shaderc/shaderc_wgsl.cpp",
    }
else
    -- Linux, Android, BSD, OPHM: GLSL/ESSL, SPIR-V
    -- 启用 glsl-optimizer：GLES/GL 渲染器用 glShaderSource 加载 GLSL 文本，
    -- shaderc_glsl.cpp 的完整实现被 SHADERC_CONFIG_HAS_GLSL_OPTIMIZER 包裹，必须置 1
    -- 启用 glslang：SPIR-V 后端编译需要完整的 glslang + spirv-cross + spirv-tools
    add_defines(
        "SHADERC_CONFIG_HAS_GLSL_OPTIMIZER=1",
        "SHADERC_CONFIG_HAS_GLSLANG=1"
    )
    backend_files = {
        "../shaderc/shaderc_glsl.cpp",
        "../shaderc/shaderc_spirv.cpp",
    }
end

-- Global backend config (all platforms):
-- Tint（WGSL）全平台关闭，不在本库编译。
add_defines("SHADERC_CONFIG_HAS_TINT=0")

-- Target: static library
target("shaderc_capi")
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

    -- Main C API wrapper (includes shaderc.cpp core)
    add_files("shaderc_capi.cpp")

    -- Backend stub file (strong symbols, one per unavailable backend)
    add_files("shaderc_backend_stubs.cpp")

    -- fcpp preprocessor (required by shaderc.cpp for GLSL preprocessing)
    -- Compiled as a single translation unit to avoid static function visibility issues
    add_files("shaderc_fcpp.c")

    -- Real backend files for the target platform
    for _, file in ipairs(backend_files) do
        add_files(file)
    end

    -- =========================================================================
    -- SPIR-V 工具链（glslang + spirv-cross + spirv-tools）
    -- 仅 SHADERC_CONFIG_HAS_GLSLANG=1 的平台（Linux/Android/BSD/OHOS）启用：
    --   - Windows（MinGW）：glslang 的 sprintf_s 是 UCRT 符号，与 msvcrt 冲突
    --   - Apple：Metal 是主后端，SPIR-V 走 stub
    --   - Emscripten：WGSL 是主后端，SPIR-V 走 stub
    -- =========================================================================
    if is_config("bx_platform", "WINDOWS") == false
    and is_config("bx_platform", "IOS") == false
    and is_config("bx_platform", "OSX") == false
    and is_config("bx_platform", "EMSCRIPTEN") == false then
    add_defines(
        "ENABLE_OPT=1",          -- glslang SPIRV-Tools 优化器集成（SpvTools.cpp 需要）
        "ENABLE_HLSL=1",         -- glslang HLSL 前端（shaderc 可能用到，保持完整）
        "SPIRV_CROSS_EXCEPTIONS_TO_ASSERTIONS=1"  -- spirv-cross 异常→断言（-fno-exceptions 下必须）
    )
    -- shaderc_spirv.cpp 的额外 include 依赖（对齐 bgfx.cmake cmake/3rdparty/glslang.cmake）：
    --   <ShaderLang.h>/<ResourceLimits.h>  → glslang/glslang/Public
    --   glslang 内部头                      → glslang/glslang/Include
    --   <SPIRV/GlslangToSpv.h>             → glslang 根（已有 ../bgfx/3rdparty/glslang）
    --   spirv-tools 内部 "source/..."      → spirv-tools 根目录 + source + include/generated
    add_includedirs(
        "../bgfx/3rdparty/glslang/glslang/Public",
        "../bgfx/3rdparty/glslang/glslang/Include",
        "../bgfx/3rdparty/spirv-tools",
        "../bgfx/3rdparty/spirv-tools/source",
        "../bgfx/3rdparty/spirv-tools/include/generated",
        "../bgfx/3rdparty/spirv-cross/include"
    )

    -- glslang 库源码（对齐 bgfx.cmake glslang.cmake 的源文件集合；
    -- 排除 StandAlone 工具；OSDependent 按平台二选一）
    -- 警告抑制：bgfx.cmake 对 glslang 使用一整套 -Wno-*（-Wshadow 等在此源码里会大量刷屏）
    local glslang_cxflags = {}
    if not is_config("toolchain", "msvc") then
        glslang_cxflags = {
            "-Wno-ignored-qualifiers",
            "-Wno-implicit-fallthrough",
            "-Wno-missing-field-initializers",
            "-Wno-reorder",
            "-Wno-return-type",
            "-Wno-shadow",
            "-Wno-sign-compare",
            "-Wno-switch",
            "-Wno-undef",
            "-Wno-unknown-pragmas",
            "-Wno-unused-function",
            "-Wno-unused-parameter",
            "-Wno-unused-variable",
            "-fno-strict-aliasing",
        }
    end
    add_files("../bgfx/3rdparty/glslang/glslang/CInterface/**.cpp", {cxflags = glslang_cxflags})
    add_files("../bgfx/3rdparty/glslang/glslang/GenericCodeGen/**.cpp", {cxflags = glslang_cxflags})
    add_files("../bgfx/3rdparty/glslang/glslang/HLSL/**.cpp", {cxflags = glslang_cxflags})
    add_files("../bgfx/3rdparty/glslang/glslang/MachineIndependent/**.cpp", {cxflags = glslang_cxflags})
    add_files("../bgfx/3rdparty/glslang/glslang/ResourceLimits/**.cpp", {cxflags = glslang_cxflags})
    add_files("../bgfx/3rdparty/glslang/SPIRV/**.cpp", {cxflags = glslang_cxflags})
    add_files("../bgfx/3rdparty/glslang/glslang/stub.cpp", {cxflags = glslang_cxflags})
    if is_config("bx_platform", "WINDOWS") then
        add_files("../bgfx/3rdparty/glslang/glslang/OSDependent/Windows/ossource.cpp", {cxflags = glslang_cxflags})
    else
        add_files("../bgfx/3rdparty/glslang/glslang/OSDependent/Unix/ossource.cpp", {cxflags = glslang_cxflags})
    end

    -- spirv-cross 库源码（排除 main.cpp 工具入口；对齐 bgfx.cmake spirv-cross.cmake）
    add_files("../bgfx/3rdparty/spirv-cross/spirv_cfg.cpp")
    add_files("../bgfx/3rdparty/spirv-cross/spirv_cpp.cpp")
    add_files("../bgfx/3rdparty/spirv-cross/spirv_cross.cpp")
    add_files("../bgfx/3rdparty/spirv-cross/spirv_cross_c.cpp")
    add_files("../bgfx/3rdparty/spirv-cross/spirv_cross_parsed_ir.cpp")
    add_files("../bgfx/3rdparty/spirv-cross/spirv_cross_util.cpp")
    add_files("../bgfx/3rdparty/spirv-cross/spirv_glsl.cpp")
    add_files("../bgfx/3rdparty/spirv-cross/spirv_hlsl.cpp")
    add_files("../bgfx/3rdparty/spirv-cross/spirv_msl.cpp")
    add_files("../bgfx/3rdparty/spirv-cross/spirv_parser.cpp")
    add_files("../bgfx/3rdparty/spirv-cross/spirv_reflect.cpp")

    -- spirv-tools 库源码（source/ 全部，含 opt/reduce/util/val 子目录；对齐 bgfx.cmake spirv-tools.cmake）
    add_files("../bgfx/3rdparty/spirv-tools/source/**.cpp")
    end

    -- =========================================================================
    -- glsl-optimizer 库源码（仅 LINUX/ANDROID/BSD/OPHM 启用 GLSL 后端时编译）
    -- shaderc_glsl.cpp 的完整实现（compileGLSLShader）依赖 glsl_optimizer API，
    -- 对齐 bgfx.cmake cmake/3rdparty/glsl-optimizer.cmake 的源文件集合：
    --   glcpp:  src/glsl/glcpp/*.c + src/util/*.c
    --   mesa:   src/mesa/program/*.c + src/mesa/main/*.c
    --   glsl-optimizer: src/glsl/*.cpp + src/glsl/*.c（排除 main.cpp / builtin_stubs.cpp）
    -- =========================================================================
    if is_config("bx_platform", "WINDOWS") == false
    and is_config("bx_platform", "IOS") == false
    and is_config("bx_platform", "OSX") == false
    and is_config("bx_platform", "EMSCRIPTEN") == false then
        add_includedirs(
            "../bgfx/3rdparty/glsl-optimizer/include",
            "../bgfx/3rdparty/glsl-optimizer/src/mesa",
            "../bgfx/3rdparty/glsl-optimizer/src/glsl",
            "../bgfx/3rdparty/glsl-optimizer/src"
        )
        local glslopt_cflags = {}
        if not is_config("toolchain", "msvc") then
            glslopt_cflags = {
                "-fno-strict-aliasing",
                "-Wno-implicit-fallthrough",
                "-Wno-parentheses",
                "-Wno-sign-compare",
                "-Wno-unused-function",
                "-Wno-unused-parameter",
            }
        end
        -- glcpp（C 源）
        add_files("../bgfx/3rdparty/glsl-optimizer/src/glsl/glcpp/**.c", {cxflags = glslopt_cflags})
        add_files("../bgfx/3rdparty/glsl-optimizer/src/util/**.c", {cxflags = glslopt_cflags})
        -- mesa（C 源）
        add_files("../bgfx/3rdparty/glsl-optimizer/src/mesa/program/**.c", {cxflags = glslopt_cflags})
        add_files("../bgfx/3rdparty/glsl-optimizer/src/mesa/main/**.c", {cxflags = glslopt_cflags})
        -- glsl-optimizer（C++ 源，排除 main.cpp / builtin_stubs.cpp 工具入口）
        add_files("../bgfx/3rdparty/glsl-optimizer/src/glsl/**.cpp", {cxflags = glslopt_cflags})
        add_files("../bgfx/3rdparty/glsl-optimizer/src/glsl/**.c", {cxflags = glslopt_cflags})
        -- getopt（mesa/glcpp 的 getopt_long 依赖）
        add_files("../bgfx/3rdparty/glsl-optimizer/src/getopt/getopt_long.c", {cxflags = glslopt_cflags})
    end

    -- Link against pre-built bgfx / bx libraries
    add_links("bgfx", "bx")
    if arch_dir ~= "" then
        add_linkdirs("../output/bgfx/Lib/" .. arch_dir)
    end