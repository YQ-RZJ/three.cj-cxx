# bgfx.cmake - bgfx building in cmake
# Written in 2017 by Joshua Brookover <joshua.al.brookover@gmail.com>
#
# To the extent possible under law, the author(s) have dedicated all copyright
# and related and neighboring rights to this software to the public domain
# worldwide. This software is distributed without any warranty.
#
# You should have received a copy of the CC0 Public Domain Dedication along with
# this software. If not, see <http://creativecommons.org/publicdomain/zero/1.0/>.

# Grab the shaderc source files
file(
	GLOB
	SHADERC_SOURCES #
	${BGFX_DIR}/tools/shaderc/*.cpp #
	${BGFX_DIR}/tools/shaderc/*.h #
	${BGFX_DIR}/src/shader* #
)

add_executable(shaderc ${SHADERC_SOURCES})

# CI-PATCH: 显式声明 GLSL 后端可用——shaderc.h 依赖 __has_include
# (<ShaderLang.h>) 自动探测，但 include 路径在下方才注入，探测失败时
# compileSPIRVShader/compileGLSLShader 编成桩，链接报 undefined
# （OHOS arm64 实测）。glslang/spirv-* 已在链接依赖中，宏置 1 一致。
target_compile_definitions(shaderc PRIVATE SHADERC_CONFIG_HAS_GLSLANG=1)

target_link_libraries(
	shaderc
	PRIVATE bx
			bimg
			bgfx-vertexlayout
			glslang
			spirv-opt
			spirv-cross
)
# CI-PATCH: webgpu/tint 仅在 WGSL 后端开启时链接（与 cmake/bgfx/
# CMakeLists.txt 的 BGFX_BUILD_TOOLS_SHADER_WGSL 开关联动）——
# targets 不存在时硬编码链接会报 dangling target 错误
if(TARGET webgpu)
	target_link_libraries(shaderc PRIVATE webgpu)
endif()
if(TARGET tint)
	target_link_libraries(shaderc PRIVATE tint)
endif()

# CI-PATCH: dawn include 路径仅 WGSL 后端开启时注入——无条件注入会让
# shaderc.h 的 __has_include(<tint/api/tint.h>) 为真，SHADERC_CONFIG_
# HAS_TINT 默认 1，shaderc_wgsl.cpp 主体被编译却无 tint 库可链
#（OHOS arm64 实测 missing 'typename' 编译错误）。
if(TARGET tint)
	target_include_directories(
		shaderc
		PRIVATE ${BGFX_DIR}/3rdparty/dawn
				${BGFX_DIR}/3rdparty/dawn/src
	)
endif()

set(DXCOMPILER_RUNTIME)
# CI-PATCH: 排除 OHOS——OHOS 也是 UNIX（Linux 内核），但 NDK 无
# directx-headers/无 DXC 运行时。注意两点坑（均实测）：
# 1. CMake 原生没有 OHOS 变量，本项目判定用 BX_PLATFORM_OHOS
#   （bgfx.cmake 自定义 option），写 `NOT OHOS` 恒为真等于没排除；
# 2. 排除 include 路径后，shaderc.h 的 SHADERC_CONFIG_HAS_DXC 默认
#   表达式 `BX_PLATFORM_WINDOWS || BX_PLATFORM_LINUX` 在 OHOS 下仍为
#   真（BX_PLATFORM_LINUX=1），shaderc_dxil.cpp 会去 include
#   <unknwnbase.h>（Windows SDK 头，NDK 无）→ fatal error。
#   必须显式定义 SHADERC_CONFIG_HAS_DXC=0 关掉 DXC 段。
if(BX_PLATFORM_OHOS)
	target_compile_definitions(shaderc PRIVATE SHADERC_CONFIG_HAS_DXC=0)
elseif(UNIX
   AND NOT APPLE
   AND NOT EMSCRIPTEN
   AND NOT ANDROID
)
	target_include_directories(
		shaderc
		PRIVATE ${BGFX_DIR}/3rdparty/directx-headers/include/directx
				${BGFX_DIR}/3rdparty/directx-headers/include
				${BGFX_DIR}/3rdparty/directx-headers/include/wsl/stubs
	)
	set(DXCOMPILER_RUNTIME ${BGFX_DIR}/tools/bin/linux/libdxcompiler.so)
elseif(WIN32)
	target_include_directories(
		shaderc
		PRIVATE ${BGFX_DIR}/3rdparty/directx-headers/include/directx
				${BGFX_DIR}/3rdparty/directx-headers/include
	)
	set(DXCOMPILER_RUNTIME ${BGFX_DIR}/tools/bin/windows/dxcompiler.dll)
endif()

if(BGFX_AMALGAMATED)
	target_link_libraries(shaderc PRIVATE bgfx-shader)
endif()

# CI-PATCH2: shaderc 可执行工具须当场解析 bgfx::fatal——新版 bgfx 的
# bx inline 头（error.inl/readerwriter.inl）经 bgfx/src/shader*.cpp 引用
# bgfx::fatal，该符号只由 libbgfx 定义（上游有意只留一份定义：最终程序
# 同时链接 libbgfx.a 与 libshaderc*.a 时避免重复符号）。工具是独立
# 可执行文件、不随 three 产物分发，链接 libbgfx 无下游重复符号风险；
# BGFX_BUILD_TOOLS=OFF（bgfx4cj 构建）时 target 不存在，跳过。
# 注意 shaderc_capi（capi/CMakeLists.txt）不受此影响：SHARED 形态已
# 显式链 bgfx（DLL 必须自持），STATIC 形态有意不链——留给消费者收口。
if(TARGET bgfx)
	target_link_libraries(shaderc PRIVATE bgfx)
endif()

set_target_properties(
	shaderc PROPERTIES FOLDER "bgfx/tools" #
					   OUTPUT_NAME ${BGFX_TOOLS_PREFIX}shaderc #
)

if(BGFX_BUILD_TOOLS_SHADER)
	add_executable(bgfx::shaderc ALIAS shaderc)
	if(BGFX_CUSTOM_TARGETS)
		add_dependencies(bgfx-tools shaderc)
	endif()
endif()

if(ANDROID)
	target_link_libraries(shaderc PRIVATE log)
elseif(IOS)
	set_target_properties(shaderc PROPERTIES MACOSX_BUNDLE ON MACOSX_BUNDLE_GUI_IDENTIFIER shaderc)
endif()

if(BGFX_INSTALL)
	install(TARGETS shaderc EXPORT "${TARGETS_EXPORT_NAME}" DESTINATION "${CMAKE_INSTALL_BINDIR}")
endif()

# DXIL compiler will be dynamically loaded at runtime - no need
# to link, just install the needed binaries alongside shaderc.exe
# CI-PATCH: 加存在性守卫——新 upstream 已从 git 移除 tools/bin/ 预编译
# DXC 运行时（本地 submodule f14487c7 实测 tools/bin 目录不存在），
# 文件缺失时 copy_if_different 在链接后置失败，整个 shaderc 目标报错
# （linux/macos/ios/android x86 job 实测 "Error copying file ... libdxcompiler.so"）。
# DXC 后端在无该运行时时应退化为编译期不可用（SHADERC_CONFIG_HAS_DXC
# 已由探测宏控制），不再阻塞构建。
if(DXCOMPILER_RUNTIME AND EXISTS "${DXCOMPILER_RUNTIME}")
	add_custom_command(
		TARGET shaderc POST_BUILD
		COMMAND ${CMAKE_COMMAND} -E copy_if_different ${DXCOMPILER_RUNTIME} $<TARGET_FILE_DIR:shaderc>
	)
	if(BGFX_INSTALL)
		install(FILES ${DXCOMPILER_RUNTIME} DESTINATION "${CMAKE_INSTALL_BINDIR}")
	endif()
endif()
