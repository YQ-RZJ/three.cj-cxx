# bgfx.cmake - C FFI API libraries for bgfx4cj (Cangjie FFI interop)
#
# Three libraries ported from the old xmake-based repo (cxx/bgfx):
#   geometryc_capi : geometryc executable converted to a library (GEOMETRYC_CAPI=1)
#   shaderc_capi   : shaderc executable converted to a library (SHADERC_CAPI=1)
#   bimg_capi      : bimg functions exported as extern "C"
#
# All three are built as STATIC libraries (the FFI boundary for the Cangjie
# project; cjpm links static archives). Header guards live in
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
add_library(geometryc_capi STATIC
	${CMAKE_SOURCE_DIR}/geometryc_capi/geometryc_capi.cpp # includes ../bgfx/tools/geometryc/geometryc.cpp with GEOMETRYC_CAPI=1
	${MESHOPTIMIZER_CAPI_SOURCES}
)

target_compile_definitions(geometryc_capi PRIVATE
	GEOMETRYC_CAPI=1 #
	"-D_CRT_SECURE_NO_WARNINGS" #
)

target_include_directories(
	geometryc_capi
	PUBLIC ${CMAKE_SOURCE_DIR}/geometryc_capi #
	PRIVATE ${MESHOPTIMIZER_CAPI_INCLUDE_DIR} #
)

target_link_libraries(
	geometryc_capi
	PUBLIC bx
			bgfx-vertexlayout #
	PRIVATE ${MESHOPTIMIZER_CAPI_LIBRARIES} #
)

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

add_library(shaderc_capi STATIC
	${CMAKE_SOURCE_DIR}/shaderc_capi/shaderc_capi.cpp # includes ../bgfx/tools/shaderc/shaderc.cpp with SHADERC_CAPI=1
	${CMAKE_SOURCE_DIR}/shaderc_capi/shaderc_backend_stubs.cpp
	${SHADERC_CAPI_BACKEND_SOURCES}
)

target_compile_definitions(shaderc_capi PRIVATE SHADERC_CAPI=1)

# Backend availability, mirroring the old xmake configuration:
#  - HLSL via D3DCompiler only on Windows
#  - DXC (dxcompiler) disabled everywhere
#  - GLSL/SPIR-V backends via glslang enabled on all non-Windows platforms
#  - TINT (WGSL) disabled everywhere (matches old SHADERC_CONFIG_HAS_TINT=0)
if(WIN32)
	set(SHADERC_CAPI_D3DCOMPILER 1)
else()
	set(SHADERC_CAPI_D3DCOMPILER 0)
endif()

target_compile_definitions(shaderc_capi PRIVATE
	SHADERC_CONFIG_HAS_D3DCOMPILER=${SHADERC_CAPI_D3DCOMPILER} #
	SHADERC_CONFIG_HAS_DXC=0 #
	SHADERC_CONFIG_HAS_GLSLANG=1 #
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

target_link_libraries(
	shaderc_capi
	PUBLIC bx
			bimg #
			bgfx-vertexlayout #
			glslang #
			spirv-opt #
			spirv-cross #
			webgpu #
)

set_target_properties(shaderc_capi PROPERTIES FOLDER "bgfx/capi")

# ---------------------------------------------------------------------------
# bimg_capi
# ---------------------------------------------------------------------------
add_library(bimg_capi STATIC ${CMAKE_SOURCE_DIR}/bimg_capi/bimg_capi.cpp)

target_include_directories(bimg_capi PUBLIC ${CMAKE_SOURCE_DIR}/bimg_capi)

target_link_libraries(
	bimg_capi
	PUBLIC bx
			bimg #
			bimg_decode #
			bimg_encode #
)

set_target_properties(bimg_capi PROPERTIES FOLDER "bgfx/capi")
