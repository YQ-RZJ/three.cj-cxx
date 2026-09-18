# bgfx.cmake - bgfx building in cmake
# Written in 2017 by Joshua Brookover <joshua.al.brookover@gmail.com>
#
# To the extent possible under law, the author(s) have dedicated all copyright
# and related and neighboring rights to this software to the public domain
# worldwide. This software is distributed without any warranty.
#
# You should have received a copy of the CC0 Public Domain Dedication along with
# this software. If not, see <http://creativecommons.org/publicdomain/zero/1.0/>.

include(bgfx.cmake)
include(3rdparty/meshoptimizer.cmake)
include(3rdparty/dear-imgui.cmake)

if(BGFX_BUILD_TOOLS_TEXTURE)
	include(3rdparty/l-smash.cmake)
	include(texturev.cmake)
endif()
if(BGFX_BUILD_TOOLS_GEOMETRY)
	include(geometryc.cmake)
	include(geometryv.cmake)
endif()
if(BGFX_BUILD_TOOLS_SHADER)
	include(3rdparty/spirv-opt.cmake)
	include(3rdparty/spirv-cross.cmake)
	include(3rdparty/glslang.cmake)
	# CI-PATCH: webgpu/tint 仅 WGSL 后端需要（shaderc_wgsl.cpp +
	# SHADERC_CONFIG_HAS_TINT）。tint(dawn) 源码与部分 NDK clang 不兼容
	#（missing 'typename'，OHOS arm64 实测），且 shaderc_capi 硬编码
	# HAS_TINT=0 根本不消费它——本地开关默认 OFF，WGSL 需求方自行置 ON。
	option(BGFX_BUILD_TOOLS_SHADER_WGSL "Build WGSL (tint/webgpu) shader backend" OFF)
	if(BGFX_BUILD_TOOLS_SHADER_WGSL)
		include(3rdparty/webgpu.cmake)
		include(3rdparty/tint.cmake)
	endif()
	include(shaderc.cmake)
endif()

include(shared.cmake)
include(examples.cmake)
