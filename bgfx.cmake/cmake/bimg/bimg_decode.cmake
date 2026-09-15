# bgfx.cmake - bgfx building in cmake
# Written in 2017 by Joshua Brookover <joshua.al.brookover@gmail.com>
#
# To the extent possible under law, the author(s) have dedicated all copyright
# and related and neighboring rights to this software to the public domain
# worldwide. This software is distributed without any warranty.
#
# You should have received a copy of the CC0 Public Domain Dedication along with
# this software. If not, see <http://creativecommons.org/publicdomain/zero/1.0/>.

# Ensure the directory exists
if(NOT IS_DIRECTORY ${BIMG_DIR})
	message(SEND_ERROR "Could not load bimg_decode, directory does not exist. ${BIMG_DIR}")
	return()
endif()

# 注意：不要再单独编译 ${MINIZ_SOURCES}。
# 新版 bimg 的 src/image_decode.cpp 已在 BIMG_CONFIG_PARSE_EXR 块内直接
# #include <miniz/miniz.c>（与上游 genie 脚本 bimg_decode.lua 对齐），
# 再编译独立 miniz.c 会在归档内产生两份 mz_* 定义，MinGW ld.lld 链接
# 下游 .dll 时报 duplicate symbol（MSVC link.exe 对相同 COMDAT 容忍故不暴露）。
file(
	GLOB_RECURSE
	BIMG_DECODE_SOURCES #
	${BIMG_DIR}/include/* #
	${BIMG_DIR}/src/image_decode*.* #
	#
	${LOADPNG_SOURCES} #
)

# AVIF decoding (libavif + dav1d), enabled by default in bimg
set(BIMG_DECODE_AVIF_SOURCES
	${BIMG_DIR}/3rdparty/dav1d/dav1d-amalgamated.c #
	${BIMG_DIR}/3rdparty/dav1d/dav1d-bitdepth-8.c #
	${BIMG_DIR}/3rdparty/dav1d/dav1d-bitdepth-16.c #
	${BIMG_DIR}/3rdparty/libavif/libavif-amalgamated.c #
)

# Old-version xmake parity: honor BGFX_LIBRARY_TYPE (static / shared).
if(BGFX_LIBRARY_TYPE STREQUAL SHARED)
	add_library(bimg_decode SHARED ${BIMG_DECODE_SOURCES} ${BIMG_DECODE_AVIF_SOURCES})
	if(WIN32)
		set_target_properties(bimg_decode PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS ON)
	endif()
else()
	add_library(bimg_decode STATIC ${BIMG_DECODE_SOURCES} ${BIMG_DECODE_AVIF_SOURCES})
endif()

# Put in a "bgfx" folder in Visual Studio
set_target_properties(bimg_decode PROPERTIES FOLDER "bgfx")

# dav1d amalgamated sources require C11
set_source_files_properties(${BIMG_DECODE_AVIF_SOURCES} PROPERTIES C_STANDARD 11)

target_compile_definitions(bimg_decode PRIVATE AVIF_CODEC_DAV1D)

target_include_directories(
	bimg_decode
	PUBLIC $<BUILD_INTERFACE:${BIMG_DIR}/include> $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
	PRIVATE ${LOADPNG_INCLUDE_DIR} #
			${MINIZ_INCLUDE_DIR} #
			${TINYEXR_INCLUDE_DIR} #
			${BIMG_DIR}/3rdparty/libavif #
			${BIMG_DIR}/3rdparty/libavif/include #
			${BIMG_DIR}/3rdparty/libavif/third_party/libyuv/include #
			${BIMG_DIR}/3rdparty/dav1d #
			${BIMG_DIR}/3rdparty/dav1d/include #
			$<$<C_COMPILER_ID:MSVC>:${BIMG_DIR}/3rdparty/dav1d/include/compat/msvc> #
)

target_link_libraries(
	bimg_decode
	PUBLIC bx #
		   bimg # shared 下为导入库（image_decode 引用 bimg::imageParse 等），static 下保持归档顺序
		   ${LOADPNG_LIBRARIES} #
		   ${MINIZ_LIBRARIES} #
		   ${TINYEXR_LIBRARIES} #
)

if(BGFX_INSTALL AND NOT BGFX_LIBRARY_TYPE MATCHES "SHARED")
	install(
		TARGETS bimg_decode
		EXPORT "${TARGETS_EXPORT_NAME}"
		LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
		ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
		RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
		INCLUDES
		DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
	)
endif()
