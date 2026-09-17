# bgfx.cmake - C FFI API libraries for bgfx4cj (Cangjie FFI interop)
#
# Three libraries ported from the old xmake-based repo (cxx/bgfx):
#   geometryc_capi : geometryc executable converted to a library (GEOMETRYC_CAPI=1)
#   shaderc_capi   : shaderc executable converted to a library (SHADERC_CAPI=1)
#   bimg_capi      : bimg functions exported as extern "C"
#
# All three honor BGFX_LIBRARY_TYPE: static archives for cjpm static linking,
# or standalone DLLs in -DBGFX_LIBRARY_TYPE=SHARED builds (parity with the old
# xmake --libtype=shared option). Header guards live in
# <repo>/geometryc_capi/*.h, <repo>/shaderc_capi/*.h, <repo>/bimg_capi/*.h.

option(BGFX_BUILD_CAPI "Build the C FFI API libraries (geometryc_capi / shaderc_capi / bimg_capi)." ON)

if(NOT BGFX_BUILD_CAPI)
	return()
endif()

# ---------------------------------------------------------------------------
# meshoptimizer sources (compiled into geometryc_capi, mirroring the upstream
# geometryc tool target which folds them in directly)
# ---------------------------------------------------------------------------
if(NOT MESHOPTIMIZER_LIBRARIES)
	file(
		GLOB #
		MESHOPTIMIZER_CAPI_SOURCES #
		${BGFX_DIR}/3rdparty/meshoptimizer/src/*.cpp #
		${BGFX_DIR}/3rdparty/meshoptimizer/src/*.h #
	)
	set(MESHOPTIMIZER_CAPI_INCLUDE_DIR ${BGFX_DIR}/3rdparty)
else()
	set(MESHOPTIMIZER_CAPI_SOURCES "")
	set(MESHOPTIMIZER_CAPI_INCLUDE_DIR ${MESHOPTIMIZER_INCLUDE_DIR})
	set(MESHOPTIMIZER_CAPI_LIBRARIES ${MESHOPTIMIZER_LIBRARIES})
endif()

# ---------------------------------------------------------------------------
# geometryc_capi
# ---------------------------------------------------------------------------
if(BGFX_LIBRARY_TYPE STREQUAL SHARED)
	add_library(geometryc_capi SHARED
		${CMAKE_SOURCE_DIR}/geometryc_capi/geometryc_capi.cpp # includes ../bgfx/tools/geometryc/geometryc.cpp with GEOMETRYC_CAPI=1
		${MESHOPTIMIZER_CAPI_SOURCES}
	)
	if(WIN32)
		set_target_properties(geometryc_capi PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS ON)
	endif()
else()
	add_library(geometryc_capi STATIC
		${CMAKE_SOURCE_DIR}/geometryc_capi/geometryc_capi.cpp # includes ../bgfx/tools/geometryc/geometryc.cpp with GEOMETRYC_CAPI=1
		${MESHOPTIMIZER_CAPI_SOURCES}
	)
endif()

target_compile_definitions(geometryc_capi PRIVATE
	GEOMETRYC_CAPI=1 #
	"-D_CRT_SECURE_NO_WARNINGS" #
)

target_include_directories(
	geometryc_capi
	PUBLIC ${CMAKE_SOURCE_DIR}/geometryc_capi #
	PRIVATE ${MESHOPTIMIZER_CAPI_INCLUDE_DIR} #
)

if(BGFX_LIBRARY_TYPE STREQUAL SHARED)
	# shared: VertexLayout/vertexPack symbols resolve via libbgfx import library
	target_link_libraries(
		geometryc_capi
		PUBLIC bx
				bgfx #
		PRIVATE ${MESHOPTIMIZER_CAPI_LIBRARIES} #
	)
else()
	target_link_libraries(
		geometryc_capi
		PUBLIC bx
				bgfx-vertexlayout #
		PRIVATE ${MESHOPTIMIZER_CAPI_LIBRARIES} #
	)
endif()

set_target_properties(geometryc_capi PROPERTIES FOLDER "bgfx/capi")

# ---------------------------------------------------------------------------
# shaderc_capi
# ---------------------------------------------------------------------------
file(
	GLOB #
	SHADERC_CAPI_BACKEND_SOURCES #
	${BGFX_DIR}/tools/shaderc/shaderc_*.cpp #
	${BGFX_DIR}/tools/shaderc/pp.cpp #
)

if(BGFX_LIBRARY_TYPE STREQUAL SHARED)
	add_library(shaderc_capi SHARED
		${CMAKE_SOURCE_DIR}/shaderc_capi/shaderc_capi.cpp # includes ../bgfx/tools/shaderc/shaderc.cpp with SHADERC_CAPI=1
		${SHADERC_CAPI_BACKEND_SOURCES}
	)
	if(WIN32)
		set_target_properties(shaderc_capi PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS ON)
	endif()
else()
	add_library(shaderc_capi STATIC
		${CMAKE_SOURCE_DIR}/shaderc_capi/shaderc_capi.cpp # includes ../bgfx/tools/shaderc/shaderc.cpp with SHADERC_CAPI=1
		${SHADERC_CAPI_BACKEND_SOURCES}
	)
endif()
# 注：旧版 shaderc_backend_stubs.cpp 不再参与编译——新版 bgfx 的每个后端文件
# （hlsl/dxil/glsl/spirv/metal/wgsl）都已内置 #if/#else 桩，pssl 文件本身即桩。
# 旧桩不仅冗余（静态归档靠按需抽取侥幸不报重定义），且其 GLSL 守卫引用的
# SHADERC_CONFIG_HAS_GLSL_OPTIMIZER 在新版已不存在，SHARED 全量链接必然
# multiple definition。文件保留在磁盘上以兼容旧 xmake 构建。

target_compile_definitions(shaderc_capi PRIVATE SHADERC_CAPI=1)

# Backend availability, mirroring the old xmake configuration:
#  - HLSL via D3DCompiler only on Windows
#  - DXC (dxcompiler) disabled everywhere
#  - GLSL/SPIR-V backends via glslang: enabled only on non-Windows platforms
#  - TINT (WGSL) disabled everywhere (matches old SHADERC_CONFIG_HAS_TINT=0)
#
# Windows/MinGW 必须关闭 glslang：
#  1. shaderc_spirv.cpp / shaderc_metal.cpp 在 GLSLANG=1 时会各自定义
#     bgfx::g_allocator 与 bgfx::TinyStlAllocator（独立工具用的私有副本），
#     与 libbgfx.a(bgfx.cpp.obj) 的同名强符号在下游 dll 内 duplicate symbol；
#  2. MinGW 下 glslang 的 sprintf_s 是 UCRT 符号，与 msvcrt 冲突。
# 关闭后 SPIR-V 走 shaderc_spirv.cpp 的 #else 桩，HLSL 仍是 Windows 主后端。
if(WIN32)
	set(SHADERC_CAPI_D3DCOMPILER 1)
	set(SHADERC_CAPI_GLSLANG 0)
else()
	set(SHADERC_CAPI_D3DCOMPILER 0)
	# CI-PATCH: glslang/spirv-cross targets 只在 BGFX_BUILD_TOOLS_SHADER=ON
	# 时才被定义（bgfx4cj 统一 BGFX_BUILD_TOOLS=OFF）——GLSLANG=1 会让
	# shaderc_spirv.cpp/shaderc_metal.cpp 引用 spirv_cross:: 符号，shared
	# 链接 libshaderc_capi.dylib 时无库可解析，报 Undefined symbols
	# （macos x86_64 job 实测；Windows 靠 GLSLANG=0 桩躲过）。无 target
	# 时降级走 #else 桩，与 Windows 同策略。
	if(TARGET spirv-cross AND TARGET glslang)
		set(SHADERC_CAPI_GLSLANG 1)
	else()
		set(SHADERC_CAPI_GLSLANG 0)
	endif()
endif()

target_compile_definitions(shaderc_capi PRIVATE
	SHADERC_CONFIG_HAS_D3DCOMPILER=${SHADERC_CAPI_D3DCOMPILER} #
	SHADERC_CONFIG_HAS_DXC=0 #
	SHADERC_CONFIG_HAS_GLSLANG=${SHADERC_CAPI_GLSLANG} #
	SHADERC_CONFIG_HAS_TINT=0 #
)

target_include_directories(
	shaderc_capi
	PUBLIC ${CMAKE_SOURCE_DIR}/shaderc_capi #
	PRIVATE ${BGFX_DIR}/3rdparty/dawn #
			${BGFX_DIR}/3rdparty/dawn/src #
			${BGFX_DIR}/3rdparty/spirv-cross #
			${BGFX_DIR}/3rdparty/glslang #
			${BGFX_DIR}/3rdparty/glslang/glslang/Public #
			${BGFX_DIR}/3rdparty/glslang/glslang/Include #
			${BGFX_DIR}/3rdparty/spirv-tools/include #
)

# glslang/spirv-opt/spirv-cross/webgpu targets only exist when
# BGFX_BUILD_TOOLS_SHADER is ON (the bgfx4cj build sets BGFX_BUILD_TOOLS=OFF;
# on Windows SHADERC_CONFIG_HAS_GLSLANG=0, so the #else stubs remove all
# references anyway). As plain names they would become dangling -l flags —
# harmless for STATIC archives (no link step) but fatal when linking a DLL,
# therefore only link the targets that actually exist.
set(SHADERC_CAPI_SHADER_DEPS)
foreach(_dep glslang spirv-opt spirv-cross webgpu)
	if(TARGET ${_dep})
		list(APPEND SHADERC_CAPI_SHADER_DEPS ${_dep})
	endif()
endforeach()

if(BGFX_LIBRARY_TYPE STREQUAL SHARED)
	# shared: bgfx shader compile entry points (compileHLSLShader 等) 经导入库解析
	target_link_libraries(
		shaderc_capi
		PUBLIC bx
				bimg #
				bgfx #
				${SHADERC_CAPI_SHADER_DEPS} #
	)
else()
	target_link_libraries(
		shaderc_capi
		PUBLIC bx
				bimg #
				bgfx-vertexlayout #
				${SHADERC_CAPI_SHADER_DEPS} #
	)
endif()

set_target_properties(shaderc_capi PROPERTIES FOLDER "bgfx/capi")

# ---------------------------------------------------------------------------
# bimg_capi
# ---------------------------------------------------------------------------
if(BGFX_LIBRARY_TYPE STREQUAL SHARED)
	add_library(bimg_capi SHARED ${CMAKE_SOURCE_DIR}/bimg_capi/bimg_capi.cpp)
	if(WIN32)
		set_target_properties(bimg_capi PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS ON)
	endif()
else()
	add_library(bimg_capi STATIC ${CMAKE_SOURCE_DIR}/bimg_capi/bimg_capi.cpp)
endif()

target_include_directories(bimg_capi PUBLIC ${CMAKE_SOURCE_DIR}/bimg_capi)

target_link_libraries(
	bimg_capi
	PUBLIC bx
			bimg #
			bimg_decode #
			bimg_encode #
)

set_target_properties(bimg_capi PROPERTIES FOLDER "bgfx/capi")
