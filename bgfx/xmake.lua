set_project("bgfx")
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

target("bgfx")
	set_kind(is_config("libtype", "shared") and "shared" or "static")
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

	-- 通用编译参数（对应 -Wall -Wextra -ffast-math -fomit-frame-pointer 等）
	add_cxflags("-Wall", "-Wextra", "-ffast-math", "-fomit-frame-pointer",
				"-Wshadow", "-Wunused-value", "-Wundef")
	add_cflags("-MMD", "-MP")   -- 生成依赖文件，等价 -MMD -MP
	add_cxxflags("-fno-rtti", "-fno-exceptions")
	-- 非 MSVC 工具链：shared 目标必须 -fPIC；xmake 的 flag 检查会忽略普通写法的 -fPIC，需 force
	if not is_config("toolchain", "msvc") then
		add_cxxflags("-fPIC", {force = true})
	end

	-- 根据平台和工具链选择渲染器和 compat 目录
	if is_config("bx_platform", "WINDOWS") then
		add_defines("BGFX_CONFIG_RENDERER_DIRECT3D11=1")
		if is_config("toolchain", "msvc") then
			add_includedirs(
				"../bx/include/compat/msvc",
				"3rdparty",
				"../bimg/include",
				"../bx/include",
				"3rdparty/khronos",
				"include"
			)
		else
			add_includedirs(
				"../bx/include/compat/mingw",
				"3rdparty",
				"../bimg/include",
				"../bx/include",
				"3rdparty/khronos",
				"include"
			)
		end
	elseif is_config("bx_platform", "ANDROID") then
		add_defines("BGFX_CONFIG_RENDERER_OPENGLES=30")
		add_defines("BGFX_CONFIG_RENDERER_OPENGLES_MIN_VERSION=30")
		add_includedirs(
			"../bx/include/compat/linux",
			"3rdparty",
			"../bimg/include",
			"../bx/include",
			"3rdparty/khronos",
			"include"
		)
	elseif is_config("bx_platform", "BSD") then
		add_defines("BGFX_CONFIG_RENDERER_OPENGLES=30")
		add_defines("BGFX_CONFIG_RENDERER_OPENGLES_MIN_VERSION=30")
		add_includedirs(
			"../bx/include/compat/freebsd",
			"3rdparty",
			"../bimg/include",
			"../bx/include",
			"3rdparty/khronos",
			"include"
		)
	elseif is_config("bx_platform", "IOS") then
		-- 仓颉侧 macOS/iOS → Metal（config.h 中显式定义任一渲染器后默认块被跳过，必须显式开启）
		add_defines("BGFX_CONFIG_RENDERER_METAL=1")
		add_includedirs(
			"../bx/include/compat/ios",
			"3rdparty",
			"../bimg/include",
			"../bx/include",
			"3rdparty/khronos",
			"include"
		)
		add_files("src/renderer_mtl.mm")
	elseif is_config("bx_platform", "OSX") then
		-- 仓颉侧 macOS/iOS → Metal
		add_defines("BGFX_CONFIG_RENDERER_METAL=1")
		add_includedirs(
			"../bx/include/compat/osx",
			"3rdparty",
			"../bimg/include",
			"../bx/include",
			"3rdparty/khronos",
			"include"
		)
		add_files("src/renderer_mtl.mm")
	elseif is_config("bx_platform", "LINUX") then
		-- 仓颉侧 Linux (gnu) → Vulkan（SPIR-V shader 后端）
		add_defines("BGFX_CONFIG_RENDERER_VULKAN=1")
		add_includedirs(
			"../bx/include/compat/linux",
			"3rdparty",
			"../bimg/include",
			"../bx/include",
			"3rdparty/khronos",
			"include"
		)
	else
		-- EMSCRIPTEN, OPHM 默认 OpenGL（OPHM 用 GLES30，与仓颉侧 OHOS → OpenGLES 一致）
		add_defines("BGFX_CONFIG_RENDERER_OPENGLES=30")
		add_defines("BGFX_CONFIG_RENDERER_OPENGLES_MIN_VERSION=30")
		add_includedirs(
			"../bx/include/compat/linux",
			"3rdparty",
			"../bimg/include",
			"../bx/include",
			"3rdparty/khronos",
			"include"
		)
	end

	-- Debug / Release 宏与优化
	if is_mode("debug") then
		add_defines("__STDC_LIMIT_MACROS", "__STDC_FORMAT_MACROS", "__STDC_CONSTANT_MACROS",
					"_DEBUG", "BX_CONFIG_DEBUG=1")
		add_cxflags("-g")

	else
		add_defines("__STDC_LIMIT_MACROS", "__STDC_FORMAT_MACROS", "__STDC_CONSTANT_MACROS",
					"NDEBUG", "BX_CONFIG_DEBUG=0")
		add_cxflags("-g", "-O3")
	end

	if is_arch("x86_64") then
		set_targetdir("../output/bgfx/Lib/x86_64")
	elseif is_arch("arm64-v8a") then
		set_targetdir("../output/bgfx/Lib/arm64-v8a")
	end

	-- 源文件（与 OBJECTS 列表一致）
	add_files(
		"src/bgfx.cpp",
		"src/debug_renderdoc.cpp",
		"src/dxgi.cpp",
		"src/glcontext_egl.cpp",
		"src/glcontext_html5.cpp",
		"src/glcontext_wgl.cpp",
		"src/nvapi.cpp",
		"src/renderer_agc.cpp",
		"src/renderer_d3d11.cpp",
		"src/renderer_d3d12.cpp",
		"src/renderer_gl.cpp",
		"src/renderer_gnm.cpp",
		"src/renderer_noop.cpp",
		"src/renderer_nvn.cpp",
		"src/renderer_vk.cpp",
		"src/shader.cpp",
		"src/shader_dxbc.cpp",
		"src/shader_spirv.cpp",
		"src/topology.cpp",
		"src/vertexlayout.cpp"
	)
