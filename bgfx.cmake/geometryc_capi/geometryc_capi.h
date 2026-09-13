/*
 * C API for bgfx geometry compiler (geometryc).
 * Parses glTF/OBJ from memory and outputs bgfx-compatible binary geometry data.
 *
 * Input:  glTF/OBJ file content (memory buffer)
 * Output: bgfx binary geometry (vertex buffer + index buffer + primitives + bounding volumes)
 *
 * Design: opaque pointers avoided; results are returned as flat C structs.
 * All output memory is allocated by the API and freed by the caller via gc_result_free().
 */

#ifndef GEOMETRYC_CAPI_H_HEADER_GUARD
#define GEOMETRYC_CAPI_H_HEADER_GUARD

#include <stdint.h>
#include <stdbool.h>

#if defined(__cplusplus)
extern "C" {
#endif // defined(__cplusplus)

// =============================================================================
// Version
// =============================================================================

void gc_version(int32_t* _major, int32_t* _minor);

// =============================================================================
// Coordinate system
// =============================================================================

typedef enum gc_coord_system
{
	GC_COORD_LH_UP_Y = 0, // Left-handed, up=+Y, forward=+Z  (default)
	GC_COORD_LH_UP_Z,     // Left-handed, up=+Z, forward=+Y
	GC_COORD_RH_UP_Y,     // Right-handed, up=+Y, forward=+Z
	GC_COORD_RH_UP_Z,     // Right-handed, up=+Z, forward=+Y

} gc_coord_system_t;

// =============================================================================
// Configuration
// =============================================================================

typedef struct gc_config
{
	float scale;              // Vertex scale factor (default 1.0f)
	uint8_t pack_normal;      // 0 = float3, 1 = Uint8 (default 0)
	uint8_t pack_uv;          // 0 = float2, 1 = Half  (default 0)
	bool ccw;                 // Counter-clockwise winding (default false)
	bool flip_v;              // Flip V coordinate (default false)
	bool has_tangent;         // Compute tangents (default false)
	bool has_barycentric;     // Generate barycentric coordinates (default false)
	bool compress;            // Compress vertex/index buffers (default false)
	gc_coord_system_t coord_system; // Coordinate system (default GC_COORD_LH_UP_Y)

} gc_config_t;

// =============================================================================
// Primitive info (output)
// =============================================================================

typedef struct gc_primitive
{
	uint32_t start_vertex;
	uint32_t start_index;
	uint32_t num_vertices;
	uint32_t num_indices;
	const char* name; // Material/group name (pointer into result, do not free separately)

} gc_primitive_t;

// =============================================================================
// Conversion result
// =============================================================================

typedef struct gc_result
{
	void*   data;          // Full binary output (bgfx geometry format)
	uint32_t size;          // Size of output data in bytes
	uint32_t num_vertices;  // Total vertex count
	uint32_t num_indices;   // Total index count
	uint32_t num_primitives; // Number of primitives
	gc_primitive_t* primitives; // Array of primitives (size = num_primitives)

} gc_result_t;

// =============================================================================
// Core API
// =============================================================================

/// Parse glTF/OBJ from memory and convert to bgfx binary geometry.
///
/// @param _input_data   File content (glTF JSON, GLB, or OBJ text).
/// @param _input_size   Size of input data in bytes.
/// @param _input_ext    File extension: "gltf", "glb", or "obj".
/// @param _base_path    Base directory path for resolving glTF .bin buffers.
///                      Can be NULL for OBJ or self-contained glTF (no external buffers).
/// @param _config       Configuration (NULL = defaults).
/// @param _out_result   Output result (caller must call gc_result_free() when done).
///
/// @return 0 on success, negative error code on failure.
int32_t gc_convert(
	  const void* _input_data
	, uint32_t    _input_size
	, const char* _input_ext
	, const char* _base_path
	, const gc_config_t* _config
	, gc_result_t* _out_result
);

/// Free all memory associated with a gc_result_t.
void gc_result_free(gc_result_t* _result);

#if defined(__cplusplus)
} // extern "C"
#endif // defined(__cplusplus)

#endif // GEOMETRYC_CAPI_H_HEADER_GUARD