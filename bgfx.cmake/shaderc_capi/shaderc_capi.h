/*
 * C API for bgfx shader compiler (shaderc).
 * Compiles shader source from memory and outputs bgfx-compatible binary shaders.
 *
 * Input:  shader source code + varying.def.sc content (memory buffers)
 * Output: bgfx binary shader (FSH/VSH/CSH format) directly usable by bgfx::createShader()
 *
 * Design: all input/output via memory buffers, no file system access.
 * All output memory is allocated by the API and freed by the caller via sc_result_free().
 */

#ifndef SHADERC_CAPI_H_HEADER_GUARD
#define SHADERC_CAPI_H_HEADER_GUARD

#include <stdint.h>
#include <stdbool.h>

#if defined(__cplusplus)
extern "C" {
#endif // defined(__cplusplus)

// =============================================================================
// Version
// =============================================================================

void sc_version(int32_t* _major, int32_t* _minor);

// =============================================================================
// Shader type
// =============================================================================

typedef enum sc_type
{
	SC_VERTEX   = 'v',
	SC_FRAGMENT = 'f',
	SC_COMPUTE  = 'c',

} sc_type_t;

// =============================================================================
// Return codes
// =============================================================================

typedef enum sc_result_code
{
	SC_SUCCESS            =  0,
	SC_ERROR_UNKNOWN      = -1,
	SC_ERROR_INVALID_PARAM = -2,
	SC_ERROR_COMPILE_FAILED = -3,
	SC_ERROR_UNKNOWN_PROFILE = -4,
	SC_ERROR_INPUT_TOO_LARGE = -5,

} sc_result_code_t;

// =============================================================================
// Compile options
// =============================================================================

typedef struct sc_options
{
	sc_type_t shader_type;         // Vertex, fragment, or compute
	const char* platform;          // "windows", "linux", "android", "ios", "osx", "asm.js"
	const char* profile;           // e.g. "120", "300_es", "5_0", "spirv", "metal", "wgsl"

	bool raw;                      // Raw mode (no bgfx wrapper, pass-through)
	bool debug;                    // Include debug information
	bool optimize;                 // Enable optimization
	uint32_t optimization_level;   // 0-3 (used when optimize=true)
	bool preprocess_only;          // Only run preprocessor, output preprocessed source
	bool disasm;                   // Output disassembly instead of binary

	// Include directories (for #include directives in shader source)
	const char* const* include_dirs;
	uint32_t           num_include_dirs;

	// Preprocessor defines ("NAME=VALUE" format)
	const char* const* defines;
	uint32_t           num_defines;

} sc_options_t;

// =============================================================================
// Compile result
// =============================================================================

typedef struct sc_result
{
	int32_t   status;     // 0 = success, negative = error code
	void*     data;       // Binary shader output (NULL on failure)
	uint32_t  size;       // Size of output data in bytes
	char*     message;    // Compiler log / error message (caller must free with sc_result_free)

} sc_result_t;

// =============================================================================
// Core API
// =============================================================================

/// Compile a shader from memory.
///
/// @param _varying_def    Varying definition file content (varying.def.sc), may be NULL.
/// @param _varying_size   Size of varying definition in bytes.
/// @param _shader_source  Shader source code.
/// @param _shader_size    Size of shader source in bytes.
/// @param _options        Compile options (must not be NULL).
/// @param _out_result     Output result (caller must call sc_result_free() when done).
///
/// @return SC_SUCCESS (0) on success, negative error code on failure.
int32_t sc_compile(
	  const void* _varying_def
	, uint32_t    _varying_size
	, const void* _shader_source
	, uint32_t    _shader_size
	, const sc_options_t* _options
	, sc_result_t* _out_result
);

/// Free all memory associated with an sc_result_t.
void sc_result_free(sc_result_t* _result);

/// Get the list of supported profile names.
/// @param _count Output: number of profiles.
/// @return Array of profile name strings (do not free).
const char* const* sc_get_profiles(uint32_t* _count);

#if defined(__cplusplus)
} // extern "C"
#endif // defined(__cplusplus)

#endif // SHADERC_CAPI_H_HEADER_GUARD