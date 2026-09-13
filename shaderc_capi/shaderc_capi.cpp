/*
 * Implementation of C API for bgfx shader compiler (shaderc).
 * Wraps shaderc core logic, replacing file I/O with memory I/O.
 *
 * Design: shaderc.cpp is included to access the core compileShader() function.
 * Backend files (shaderc_glsl.cpp, etc.) are compiled as separate translation
 * units via add_files() in xmake.lua, then linked together.
 */

#include "shaderc_capi.h"

// Prevent main() from being compiled into this translation unit.
#define SHADERC_CAPI 1

// Include the shaderc header to access Options, compileShader declarations, etc.
#include "../shaderc/shaderc.h"

// Include the shaderc implementation source to access all internal functions.
// This brings in the full compileShader() core logic, but NOT the backend files.
// Backend functions are provided by either:
//   - shaderc_backend_stubs.cpp (weak stubs, always compiled)
//   - Real backend files (e.g. shaderc_spirv.cpp, compiled per platform)
#include "../shaderc/shaderc.cpp"

// =============================================================================
// Helper: MemoryWriter for shader output
// =============================================================================

struct MemoryWriter : public bx::WriterI
{
	MemoryWriter()
		: m_data(NULL)
		, m_size(0)
		, m_capacity(0)
	{
	}

	~MemoryWriter()
	{
	}

	int32_t write(const void* _data, int32_t _size, bx::Error* _err) override
	{
		BX_UNUSED(_err);

		if (m_size + _size > m_capacity)
		{
			uint32_t newCapacity = bx::max(m_capacity * 2, m_capacity + _size + 65536);
			uint8_t* newData = new uint8_t[newCapacity];
			if (m_data != NULL)
			{
				bx::memCopy(newData, m_data, m_size);
				delete [] m_data;
			}
			m_data = newData;
			m_capacity = newCapacity;
		}

		bx::memCopy(m_data + m_size, _data, _size);
		m_size += _size;
		return _size;
	}

	uint8_t*  m_data;
	uint32_t  m_size;
	uint32_t  m_capacity;
};

// =============================================================================
// sc_compile
// =============================================================================

int32_t sc_compile(
	  const void* _varying_def
	, uint32_t    _varying_size
	, const void* _shader_source
	, uint32_t    _shader_size
	, const sc_options_t* _options
	, sc_result_t* _out_result
)
{
	// Validate input
	if (_options == NULL || _shader_source == NULL || _shader_size == 0 || _out_result == NULL)
	{
		return SC_ERROR_INVALID_PARAM;
	}

	// Clear output first
	_out_result->data    = NULL;
	_out_result->size    = 0;
	_out_result->message = NULL;
	_out_result->status  = SC_ERROR_UNKNOWN;

	// ---- Map C API options to bgfx::Options ----
	bgfx::Options options;

	options.shaderType = (char)_options->shader_type;
	options.platform   = _options->platform != NULL ? _options->platform : "";
	options.profile    = _options->profile != NULL ? _options->profile : "";
	options.raw        = _options->raw;
	options.debugInformation = _options->debug;
	options.optimize         = _options->optimize;
	options.optimizationLevel = _options->optimization_level;
	options.preprocessOnly   = _options->preprocess_only;
	options.keepComments     = _options->keep_comments;
	options.disasm           = _options->disasm;

	// Include directories
	for (uint32_t ii = 0; ii < _options->num_include_dirs; ++ii)
	{
		if (_options->include_dirs[ii] != NULL)
		{
			options.includeDirs.push_back(_options->include_dirs[ii]);
		}
	}

	// Defines
	for (uint32_t ii = 0; ii < _options->num_defines; ++ii)
	{
		if (_options->defines[ii] != NULL)
		{
			options.defines.push_back(_options->defines[ii]);
		}
	}

	// Set input file path to a valid value (fcpp preprocessor needs it for FPPTAG_FILE_NAME)
	options.inputFilePath  = "shader.sc";
	options.outputFilePath = "";

	// ---- Prepare varying definition string ----
	const char* varying = NULL;
	std::string varyingStr;
	if (_varying_def != NULL && _varying_size > 0)
	{
		varyingStr.assign((const char*)_varying_def, _varying_size);
		varying = varyingStr.c_str();
	}

	// ---- Prepare shader source (mutable copy for the preprocessor) ----
	// The compileShader function modifies the shader buffer in place,
	// so we need a mutable copy. The function also takes ownership by
	// calling delete[] on it, so we allocate with new char[].
	const size_t padding = 16384;
	char* shaderCopy = new char[_shader_size + padding + 1];
	bx::memCopy(shaderCopy, _shader_source, _shader_size);
	bx::memSet(&shaderCopy[_shader_size], 0, padding + 1);

	// ---- Create memory writers for output ----
	MemoryWriter shaderWriter;
	MemoryWriter messageWriter;

	// Set bgfx::g_verbose to false by default
	bgfx::g_verbose = false;

	// ---- Call the core compiler ----
	bool compiled = bgfx::compileShader(
		  varying
		, ""   // command line comment (empty for API usage)
		, shaderCopy
		, _shader_size
		, options
		, &shaderWriter  // _shaderWriter
		, &messageWriter // _messageWriter
	);

	// Note: compileShader takes ownership of shaderCopy and will delete[] it internally.

	// ---- Fill output result ----
	if (compiled)
	{
		_out_result->data  = shaderWriter.m_data;
		_out_result->size  = shaderWriter.m_size;
		_out_result->status = SC_SUCCESS;

		// Transfer ownership: shaderWriter.m_data was allocated with new[],
		// and will be freed by the caller via sc_result_free().
		shaderWriter.m_data = NULL; // Prevent double-free
	}
	else
	{
		_out_result->status = SC_ERROR_COMPILE_FAILED;
		// Discard any partial shader output
		delete [] shaderWriter.m_data;
	}

	// Copy message log
	if (messageWriter.m_size > 0)
	{
		_out_result->message = new char[messageWriter.m_size + 1];
		bx::memCopy(_out_result->message, messageWriter.m_data, messageWriter.m_size);
		_out_result->message[messageWriter.m_size] = '\0';
	}

	delete [] messageWriter.m_data;

	return _out_result->status;
}

// =============================================================================
// sc_result_free
// =============================================================================

void sc_result_free(sc_result_t* _result)
{
	if (_result == NULL)
	{
		return;
	}

	delete [] (uint8_t*)_result->data;
	_result->data = NULL;
	_result->size = 0;

	delete [] _result->message;
	_result->message = NULL;

	_result->status = SC_ERROR_UNKNOWN;
}

// =============================================================================
// sc_get_profiles
// =============================================================================

const char* const* sc_get_profiles(uint32_t* _count)
{
	// The s_profiles array is defined in shaderc.cpp inside the bgfx namespace.
	// We expose the profile names as a static array of C strings.
	static const char* s_profileNames[] =
	{
		"100_es",
		"300_es",
		"120",
		"140",
		"150",
		"330",
		"400",
		"410",
		"420",
		"430",
		"440",
		"none",
		"metal",
		"pssl",
		"spirv",
		"spirv14",
		"wgsl",
		"dxil",
		"5_0",
		"4_0",
		"3_0",
		"4_1",
		"5_1",
		"6_0",
		"6_1",
		"6_2",
		"6_3",
		"6_4",
		"6_5",
		"6_6",
		"6_7",
	};

	if (_count != NULL)
	{
		*_count = BX_COUNTOF(s_profileNames);
	}

	return s_profileNames;
}

// =============================================================================
// sc_version
// =============================================================================

void sc_version(int32_t* _major, int32_t* _minor)
{
	if (_major != NULL) *_major = BGFX_SHADERC_VERSION_MAJOR;
	if (_minor != NULL) *_minor = BGFX_SHADERC_VERSION_MINOR;
}