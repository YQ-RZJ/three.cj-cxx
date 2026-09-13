add_rules("mode.debug", "mode.release")
set_languages("cxx17")

-- 自定义平台选项，由 build.bat 通过 --bx_platform=WINDOWS 传入
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

-- 通用编译选项（C/C++）
add_defines("__STDC_LIMIT_MACROS", "__STDC_FORMAT_MACROS", "__STDC_CONSTANT_MACROS")
add_cxxflags("-Wall", "-Wextra", "-ffast-math", "-fomit-frame-pointer", "-Wshadow", "-Wunused-value", "-Wundef", "-fno-rtti", "-fno-exceptions")
-- 非 MSVC 工具链：shared 目标必须 -fPIC；xmake 的 flag 检查会忽略普通写法的 -fPIC，需 force
if not is_config("toolchain", "msvc") then
    add_cxxflags("-fPIC", {force = true})
end

-- 根据平台和工具链选择 compat 目录
if is_config("bx_platform", "WINDOWS") then
     add_defines("BX_PLATFORM_WINDOWS=1")
     if is_config("toolchain", "msvc") then
         add_includedirs("include/compat/msvc", "include", "3rdparty")
     else
         add_includedirs("include/compat/mingw", "include", "3rdparty")
     end
elseif is_config("bx_platform", "BSD") then
    add_includedirs("include/compat/freebsd", "include", "3rdparty")
elseif is_config("bx_platform", "IOS") then
    add_includedirs("include/compat/ios", "include", "3rdparty")
elseif is_config("bx_platform", "OSX") then
    add_includedirs("include/compat/osx", "include", "3rdparty")
else
    -- LINUX, ANDROID, EMSCRIPTEN
    add_includedirs("include/compat/linux", "include", "3rdparty")
end

if is_arch("x86_64") then
	set_targetdir("../output/bgfx/Lib/x86_64")
elseif is_arch("arm64-v8a") then
	set_targetdir("../output/bgfx/Lib/arm64-v8a")
end

-- 目标：静态库 bx
target("bx")
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

    -- 源文件（等价于列出的那些 .cpp；用通配更简洁）
    add_files("src/*.cpp")

    -- Debug/Release 差异（BX_CONFIG_DEBUG 宏 / 优化等级）
    on_load(function (target)
        if is_mode("debug") then
            target:add("defines", "BX_CONFIG_DEBUG=1", "_DEBUG")
        else
            target:add("defines", "BX_CONFIG_DEBUG=0", "NDEBUG")
            -- O3 与 Makefile 对齐
            target:add("cxflags", "-O3", {force = true})
        end
    end)
