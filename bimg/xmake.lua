set_project("bimg")
set_languages("c11", "cxx17")
add_rules("mode.debug", "mode.release")

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

-- 公共宏（Makefile 里各 config 都有）
add_defines("__STDC_LIMIT_MACROS", "__STDC_FORMAT_MACROS", "__STDC_CONSTANT_MACROS")

-- 根据平台和工具链选择 compat 目录
if is_config("bx_platform", "WINDOWS") then
    if is_config("toolchain", "msvc") then
        add_includedirs(
            "../bx/include/compat/msvc",
            "include",
            "3rdparty",
            "3rdparty/astc-encoder/include",
            "3rdparty/tinyexr/deps/miniz",
            "../bx/include"
        )
    else
        add_includedirs(
            "../bx/include/compat/mingw",
            "include",
            "3rdparty",
            "3rdparty/astc-encoder/include",
            "3rdparty/tinyexr/deps/miniz",
            "../bx/include"
        )
    end
elseif is_config("bx_platform", "BSD") then
    add_includedirs(
        "../bx/include/compat/freebsd",
        "include",
        "3rdparty",
        "3rdparty/astc-encoder/include",
        "3rdparty/tinyexr/deps/miniz",
        "../bx/include"
    )
elseif is_config("bx_platform", "IOS") then
    add_includedirs(
        "../bx/include/compat/ios",
        "include",
        "3rdparty",
        "3rdparty/astc-encoder/include",
        "3rdparty/tinyexr/deps/miniz",
        "../bx/include"
    )
elseif is_config("bx_platform", "OSX") then
    add_includedirs(
        "../bx/include/compat/osx",
        "include",
        "3rdparty",
        "3rdparty/astc-encoder/include",
        "3rdparty/tinyexr/deps/miniz",
        "../bx/include"
    )
else
    -- LINUX, ANDROID, EMSCRIPTEN
    add_includedirs(
        "../bx/include/compat/linux",
        "include",
        "3rdparty",
        "3rdparty/astc-encoder/include",
        "3rdparty/tinyexr/deps/miniz",
        "../bx/include"
    )
end

-- 公共编译标志（等价于 -Wall -Wextra -Wshadow -Wunused-value -Wundef -fPIC 等）
add_cxflags("-Wall", "-Wextra", "-Wshadow", "-Wunused-value", "-Wundef")
-- 非 MSVC 工具链：shared 目标必须 -fPIC；xmake 的 flag 检查会忽略普通写法的 -fPIC，需 force
if not is_config("toolchain", "msvc") then
    add_cxflags("-fPIC", {force = true})
end
add_cxxflags("-fno-rtti", "-fno-exceptions")

-- Debug/Release 专属宏与优化级别
if is_mode("debug") then
    add_defines("_DEBUG", "BX_CONFIG_DEBUG=1")
    -- 与原 Makefile 一致：debug 也带 -g
    add_cxflags("-g")
else
    add_defines("NDEBUG", "BX_CONFIG_DEBUG=0")
    add_cxflags("-O3", "-g")  -- 原脚本 release 也包含 -g
end

if is_arch("x86_64") then
	set_targetdir("../output/bgfx/Lib/x86_64")
elseif is_arch("arm64-v8a") then
	set_targetdir("../output/bgfx/Lib/arm64-v8a")
end

-- 目标：静态库（对应 libbimg.a）
target("bimg")
    set_kind(is_config("libtype", "shared") and "shared" or "static")
    add_links("bx")
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

    -- 源文件：等价于列出的 astcenc_* 与 bimg/src/image*.cpp
    add_files(
        "3rdparty/astc-encoder/source/*.cpp",
        "src/image.cpp",
        "src/image_gnf.cpp"
    )

-- 目标：静态库（对应 libbimg_decode.a）
target("bimg_decode")
    set_kind(is_config("libtype", "shared") and "shared" or "static")
    -- shared 下链接 -lbimg 依赖 libbimg 的导入库/so，必须先构建 bimg，否则并行链接时竞争失败
    add_deps("bimg")
    add_links("bimg", "bx")
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
		  "3rdparty/tinyexr/deps/miniz/miniz.c",
        "src/image_decode.cpp"
    )

-- 目标：静态库（对应 libbimg_encode.a）
target("bimg_encode")
    set_kind(is_config("libtype", "shared") and "shared" or "static")
    -- shared 下链接 -lbimg 依赖 libbimg 的导入库/so，必须先构建 bimg，否则并行链接时竞争失败
    add_deps("bimg")
    add_links("bimg", "bx")
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

    add_includedirs(
        "3rdparty/nvtt",
        "3rdparty/iqa/include"
    )

    add_files(
        "3rdparty/edtaa3/edtaa3func.cpp",
        "3rdparty/etc1/etc1.cpp",
        "3rdparty/etc2/ProcessRGB.cpp",
        "3rdparty/etc2/Tables.cpp",
        "3rdparty/libsquish/alpha.cpp",
        "3rdparty/libsquish/clusterfit.cpp",
        "3rdparty/libsquish/colourblock.cpp",
        "3rdparty/libsquish/colourfit.cpp",
        "3rdparty/libsquish/colourset.cpp",
        "3rdparty/libsquish/maths.cpp",
        "3rdparty/libsquish/rangefit.cpp",
        "3rdparty/libsquish/singlecolourfit.cpp",
        "3rdparty/libsquish/squish.cpp",
        "3rdparty/nvtt/bc6h/zoh.cpp",
        "3rdparty/nvtt/bc6h/zohone.cpp",
        "3rdparty/nvtt/bc6h/zohtwo.cpp",
        "3rdparty/nvtt/bc6h/zoh_utils.cpp",
        "3rdparty/nvtt/bc7/avpcl.cpp",
        "3rdparty/nvtt/bc7/avpcl_mode0.cpp",
        "3rdparty/nvtt/bc7/avpcl_mode1.cpp",
        "3rdparty/nvtt/bc7/avpcl_mode2.cpp",
        "3rdparty/nvtt/bc7/avpcl_mode3.cpp",
        "3rdparty/nvtt/bc7/avpcl_mode4.cpp",
        "3rdparty/nvtt/bc7/avpcl_mode5.cpp",
        "3rdparty/nvtt/bc7/avpcl_mode6.cpp",
        "3rdparty/nvtt/bc7/avpcl_mode7.cpp",
        "3rdparty/nvtt/bc7/avpcl_utils.cpp",
        "3rdparty/nvtt/nvmath/fitting.cpp",
        "3rdparty/nvtt/nvtt.cpp",
        "3rdparty/pvrtc/BitScale.cpp",
        "3rdparty/pvrtc/MortonTable.cpp",
        "3rdparty/pvrtc/PvrTcDecoder.cpp",
        "3rdparty/pvrtc/PvrTcEncoder.cpp",
        "3rdparty/pvrtc/PvrTcPacket.cpp",
        "3rdparty/iqa/source/convolve.c",
        "3rdparty/iqa/source/decimate.c",
        "3rdparty/iqa/source/math_utils.c",
        "3rdparty/iqa/source/ms_ssim.c",
        "3rdparty/iqa/source/mse.c",
        "3rdparty/iqa/source/psnr.c",
        "3rdparty/iqa/source/ssim.c",
        "src/image_encode.cpp",
        "src/image_cubemap_filter.cpp"
    )
