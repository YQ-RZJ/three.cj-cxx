/*
 * Strong symbol stubs for shader backends that are not compiled for the
 * target platform. These are wrapped in the bgfx namespace to match the
 * symbol names expected by shaderc.cpp.
 *
 * For backends that ARE compiled (e.g., SPIR-V on all platforms), the
 * real implementation provides the strong symbol. For backends that are
 * NOT compiled, this stub provides a placeholder that returns an error.
 *
 * This approach avoids the need for weak symbols, which are not supported
 * by LLD (the linker used by the Cangjie toolchain).
 *
 * When a backend IS compiled for the target platform (e.g., HLSL/DXIL on
 * Windows), its stub is guarded by #if !SHADERC_CONFIG_HAS_* to prevent
 * duplicate symbol errors at link time.
 */

#include "shaderc_capi.h"
#include "../bgfx/tools/shaderc/shaderc.h"

namespace bgfx {

// =============================================================================
// Stub: compileGLSLShader — only when GLSL backend is NOT compiled
// (LINUX/ANDROID/BSD/OPHM 启用 glsl-optimizer 后由 shaderc_glsl.cpp 提供真实实现)
// =============================================================================

#if !SHADERC_CONFIG_HAS_GLSL_OPTIMIZER
bool compileGLSLShader(const Options& _options, uint32_t _version, const std::string& _code, bx::WriterI* _shaderWriter, bx::WriterI* _messageWriter)
{
	BX_UNUSED(_options, _version, _code, _shaderWriter);
	bx::Error err;
	bx::write(_messageWriter, &err, "GLSL shader backend is not available in this build.\n");
	BX_UNUSED(_messageWriter, &err);
	return false;
}
#endif

// =============================================================================
// Stub: compileHLSLShader — only when HLSL backend is NOT compiled
// =============================================================================

#if !SHADERC_CONFIG_HAS_D3DCOMPILER
bool compileHLSLShader(const Options& _options, uint32_t _version, const std::string& _code, bx::WriterI* _shaderWriter, bx::WriterI* _messageWriter)
{
	BX_UNUSED(_options, _version, _code, _shaderWriter);
	bx::Error err;
	bx::write(_messageWriter, &err, "HLSL shader backend is not available in this build.\n");
	BX_UNUSED(_messageWriter, &err);
	return false;
}
#endif

// =============================================================================
// Stub: compileDxilShader — only when DXIL backend is NOT compiled
// =============================================================================

#if !SHADERC_CONFIG_HAS_DXC
bool compileDxilShader(const Options& _options, uint32_t _version, const std::string& _code, bx::WriterI* _shaderWriter, bx::WriterI* _messageWriter)
{
	BX_UNUSED(_options, _version, _code, _shaderWriter);
	bx::Error err;
	bx::write(_messageWriter, &err, "DXIL shader backend is not available in this build.\n");
	BX_UNUSED(_messageWriter, &err);
	return false;
}
#endif

// =============================================================================
// Stub: compileMetalShader (not compiled on non-Apple platforms)
// =============================================================================

bool compileMetalShader(const Options& _options, uint32_t _version, const std::string& _code, bx::WriterI* _shaderWriter, bx::WriterI* _messageWriter)
{
	BX_UNUSED(_options, _version, _code, _shaderWriter);
	bx::Error err;
	bx::write(_messageWriter, &err, "Metal shader backend is not available in this build.\n");
	BX_UNUSED(_messageWriter, &err);
	return false;
}

// =============================================================================
// Stub: compilePSSLShader (not compiled on non-PlayStation platforms)
// =============================================================================

bool compilePSSLShader(const Options& _options, uint32_t _version, const std::string& _code, bx::WriterI* _shaderWriter, bx::WriterI* _messageWriter)
{
	BX_UNUSED(_options, _version, _code, _shaderWriter);
	bx::Error err;
	bx::write(_messageWriter, &err, "PSSL shader backend is not available in this build.\n");
	BX_UNUSED(_messageWriter, &err);
	return false;
}

// =============================================================================
// Stub: compileWgslShader (not compiled on non-Emscripten platforms)
// =============================================================================

bool compileWgslShader(const Options& _options, uint32_t _version, const std::string& _code, bx::WriterI* _shaderWriter, bx::WriterI* _messageWriter)
{
	BX_UNUSED(_options, _version, _code, _shaderWriter);
	bx::Error err;
	bx::write(_messageWriter, &err, "WGSL shader backend is not available in this build.\n");
	BX_UNUSED(_messageWriter, &err);
	return false;
}

// =============================================================================
// Stub: getPsslPreamble (not compiled on non-PlayStation platforms)
// =============================================================================

const char* getPsslPreamble()
{
	return "";
}

} // namespace bgfx