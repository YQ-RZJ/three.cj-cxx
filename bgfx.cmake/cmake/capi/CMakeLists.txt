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

# Backend availability — CI-PATCH2b（全平台统一）：glslang/spirv-opt/
# spirv-cross 统一编入 libshaderc_capi.a 并合并为单库（老库 OHOS 形态
# 实测 4721 个 glslang 符号）。曾试过按平台 profile 差异化（Windows 只
# 要 D3DCompiler 等），后确认无必要——静态库链接按成员对象抽取，未用
# 后端不会进下游产物，差异化只增加构建行为不一致的复杂度。
# 全平台 GLSLANG=1；Windows s_5_0 主后端仍是 D3DCompiler，GLSL 为冗余
# 能力（老库 xmake 时代即全量编入）；TINT(WGSL) 全平台关闭。
if(WIN32)
	set(SHADERC_CAPI_D3DCOMPILER 1)
	set(SHADERC_CAPI_GLSLANG 1)
else()
	set(SHADERC_CAPI_D3DCOMPILER 0)
	set(SHADERC_CAPI_GLSLANG 1)
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

# CI-PATCH3: 静态库产物合并——老库（xmake 时代）仅 OHOS 的
# libshaderc_capi.a 内嵌 glslang/spirv-opt/spirv-cross（实测 4721 个
# glslang 符号；mac/ios/linux 老库均为 0，GLSLANG 桩态）；bgfx.cmake
# 默认拆开分发。故仅在 GLSLANG 真实启用时合并（Windows GLSLANG=0
# 有 duplicate symbol 风险，见上；且无 deps 可合并）。
if(NOT BGFX_LIBRARY_TYPE STREQUAL SHARED AND SHADERC_CAPI_SHADER_DEPS)
	set(_SC_MERGE_DIR "${CMAKE_CURRENT_BINARY_DIR}/merge_deps")
	# CI-PATCH3b: 每个依赖抽取到独立子目录——Windows 文件系统大小写
	# 不敏感，多个归档的同名成员（实测：glslang 的 Pp.cpp.o 与 shaderc
	# 的 pp.cpp.o）在同一目录 ar x 互相覆盖，回填归档丢失 shaderc 的
	# Preprocessor 实现，运行期 GOT 槽空引用 SIGSEGV（OHOS 实测）。
	# 构造 make_directory 命令列表（configure 期展开，须先于 POST_BUILD 定义）
	set(_SC_MKDIR_CMDS)
	foreach(_dep ${SHADERC_CAPI_SHADER_DEPS})
		list(APPEND _SC_MKDIR_CMDS COMMAND ${CMAKE_COMMAND} -E make_directory ${_SC_MERGE_DIR}/${_dep})
	endforeach()
	add_custom_command(TARGET shaderc_capi POST_BUILD
		COMMAND ${CMAKE_COMMAND} -E rm -rf ${_SC_MERGE_DIR}
		COMMAND ${CMAKE_COMMAND} -E make_directory ${_SC_MERGE_DIR}
		# 子目录须在 rm 之后、抽取段的 cd 之前重建（同段顺序执行）
		${_SC_MKDIR_CMDS}
	)
	# 2) 依赖归档整库合并——ar MRI 脚本（OPEN/ADDLIB/SAVE），不解包成员，
	# 规避 Windows 大小写不敏感文件系统的同名成员覆盖问题
	add_custom_command(TARGET shaderc_capi POST_BUILD
		COMMAND ${CMAKE_COMMAND}
			-DDEPS=glslang,spirv-opt,spirv-cross
			-DAR=${CMAKE_AR}
			-DOUTPUT=$<TARGET_FILE:shaderc_capi>
			-DCAPI=$<TARGET_FILE:shaderc_capi>
			-DLIBDIR=$<TARGET_FILE_DIR:shaderc_capi>/../bgfx
			-P ${CMAKE_CURRENT_LIST_DIR}/merge_deps.cmake
		COMMENT "shaderc_capi: merging shader deps (${SHADERC_CAPI_SHADER_DEPS}) into single archive"
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
