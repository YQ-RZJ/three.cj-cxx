/*
 * C wrapper for bimg C++ API.
 * Exposes bimg functions as extern "C" for FFI interop with Cangjie.
 *
 * Design: bimg::ImageContainer and other C++ structs are exposed as
 * opaque pointers. Field access is through getter/setter functions.
 * This avoids any C/C++ struct layout mismatch issues.
 */

#ifndef BIMG_CAPI_H_HEADER_GUARD
#define BIMG_CAPI_H_HEADER_GUARD

#include <stdint.h>
#include <stdbool.h>

#if defined(__cplusplus)
extern "C" {
#endif // defined(__cplusplus)

// =============================================================================
// Opaque types
// =============================================================================

/// Opaque bimg::ImageContainer
typedef struct bimg_image_container_t_ bimg_image_container_t;

/// Opaque bx::AllocatorI
typedef struct bimg_allocator_t_ bimg_allocator_t;

/// Opaque bx::Error
typedef struct bimg_error_t_ bimg_error_t;

/// Opaque bx::WriterI
typedef struct bimg_writer_t_ bimg_writer_t;

/// Opaque bx::ReaderSeekerI
typedef struct bimg_reader_seeker_t_ bimg_reader_seeker_t;

// =============================================================================
// Value structs (returned by value from C API)
// =============================================================================

/// Mirror of bimg::TextureInfo (layout-safe: no C++ types)
typedef struct bimg_texture_info_t {
    uint32_t format;       //!< TextureFormat::Enum
    uint32_t storageSize;
    uint16_t width;
    uint16_t height;
    uint16_t depth;
    uint16_t numLayers;
    uint8_t  numMips;
    uint8_t  bitsPerPixel;
    bool     cubeMap;
} bimg_texture_info_t;

/// Mirror of bimg::ImageBlockInfo (all uint8_t fields, no padding issues)
typedef struct bimg_image_block_info_t {
    uint8_t bitsPerPixel;
    uint8_t blockWidth;
    uint8_t blockHeight;
    uint8_t blockSize;
    uint8_t minBlockX;
    uint8_t minBlockY;
    uint8_t depthBits;
    uint8_t stencilBits;
    uint8_t rBits;
    uint8_t gBits;
    uint8_t bBits;
    uint8_t aBits;
    uint8_t encoding;
} bimg_image_block_info_t;

/// Mirror of bimg::ImageMip (returned by value from bimg_image_get_raw_data)
typedef struct bimg_image_mip_t {
    uint32_t    m_format;     //!< TextureFormat::Enum
    uint32_t    m_width;
    uint32_t    m_height;
    uint32_t    m_depth;
    uint32_t    m_blockSize;
    uint32_t    m_size;
    uint8_t     m_bpp;
    bool        m_hasAlpha;
    const uint8_t* m_data;
} bimg_image_mip_t;

// =============================================================================
// ImageContainer field accessors
// =============================================================================

bimg_allocator_t*     bimg_ic_get_allocator(const bimg_image_container_t* _ic);
void*                 bimg_ic_get_data(const bimg_image_container_t* _ic);
uint32_t              bimg_ic_get_format(const bimg_image_container_t* _ic);
uint32_t              bimg_ic_get_orientation(const bimg_image_container_t* _ic);
uint32_t              bimg_ic_get_size(const bimg_image_container_t* _ic);
uint32_t              bimg_ic_get_offset(const bimg_image_container_t* _ic);
uint32_t              bimg_ic_get_width(const bimg_image_container_t* _ic);
uint32_t              bimg_ic_get_height(const bimg_image_container_t* _ic);
uint32_t              bimg_ic_get_depth(const bimg_image_container_t* _ic);
uint16_t              bimg_ic_get_num_layers(const bimg_image_container_t* _ic);
uint8_t               bimg_ic_get_num_mips(const bimg_image_container_t* _ic);
bool                  bimg_ic_get_has_alpha(const bimg_image_container_t* _ic);
bool                  bimg_ic_get_cube_map(const bimg_image_container_t* _ic);
bool                  bimg_ic_get_ktx(const bimg_image_container_t* _ic);
bool                  bimg_ic_get_pvr3(const bimg_image_container_t* _ic);
bool                  bimg_ic_get_srgb(const bimg_image_container_t* _ic);

// =============================================================================
// bimg functions — bimg.h (libbimg.a)
// =============================================================================

bool bimg_is_compressed(uint32_t _format);
bool bimg_is_color(uint32_t _format);
bool bimg_is_depth(uint32_t _format);
bool bimg_is_valid(uint32_t _format);
bool bimg_is_float(uint32_t _format);
uint8_t bimg_get_bits_per_pixel(uint32_t _format);
bimg_image_block_info_t bimg_get_block_info(uint32_t _format);
const char* bimg_get_name(uint32_t _format);
uint32_t bimg_get_format(const char* _name);
uint8_t bimg_image_get_num_mips(uint32_t _format, uint16_t _width, uint16_t _height, uint16_t _depth);
uint32_t bimg_image_get_size(bimg_texture_info_t* _info, uint16_t _width, uint16_t _height, uint16_t _depth, bool _cubeMap, bool _hasMips, uint16_t _numLayers, uint32_t _format);
void bimg_image_solid(void* _dst, uint32_t _width, uint32_t _height, uint32_t _solid);
void bimg_image_checkerboard(void* _dst, uint32_t _width, uint32_t _height, uint32_t _step, uint32_t _0, uint32_t _1);
void bimg_image_rgba8_downsample2x2(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _srcPitch, uint32_t _dstPitch, const void* _src);
void bimg_image_rgba32f_to_linear(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _srcPitch, const void* _src);
void bimg_image_rgba32f_to_linear_ic(bimg_image_container_t* _imageContainer);
void bimg_image_rgba32f_to_gamma(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _srcPitch, const void* _src);
void bimg_image_rgba32f_to_gamma_ic(bimg_image_container_t* _imageContainer);
void bimg_image_rgba32f_linear_downsample2x2(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _srcPitch, const void* _src);
void bimg_image_rgba32f_downsample2x2(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _srcPitch, const void* _src);
void bimg_image_rgba32f_downsample2x2_normal_map(void* _dst, uint32_t _width, uint32_t _height, uint32_t _srcPitch, uint32_t _dstPitch, const void* _src);
void bimg_image_swizzle_bgra8(void* _dst, uint32_t _dstPitch, uint32_t _width, uint32_t _height, const void* _src, uint32_t _srcPitch);
void bimg_image_copy(void* _dst, uint32_t _height, uint32_t _srcPitch, uint32_t _depth, const void* _src, uint32_t _dstPitch);
void bimg_image_copy_bpp(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _bpp, uint32_t _srcPitch, const void* _src);
bool bimg_image_convert(uint32_t _dstFormat, uint32_t _srcFormat);
void bimg_image_convert_raw(void* _dst, uint32_t _bpp, void* _packFn, const void* _src, void* _unpackFn, uint32_t _size);
void bimg_image_convert_dims(void* _dst, uint32_t _dstBpp, void* _packFn, const void* _src, uint32_t _srcBpp, void* _unpackFn, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _srcPitch, uint32_t _dstPitch);
bool bimg_image_convert_alloc(bimg_allocator_t* _allocator, void* _dst, uint32_t _dstFormat, const void* _src, uint32_t _srcFormat, uint32_t _width, uint32_t _height, uint32_t _depth);
bimg_image_container_t* bimg_image_alloc(bimg_allocator_t* _allocator, uint32_t _format, uint16_t _width, uint16_t _height, uint16_t _depth, uint16_t _numLayers, bool _cubeMap, bool _hasMips, const void* _data);
void bimg_image_free(bimg_image_container_t* _imageContainer);
int32_t bimg_image_write_tga(bimg_writer_t* _writer, uint32_t _width, uint32_t _height, uint32_t _srcPitch, const void* _src, bool _grayscale, bool _yflip, bimg_error_t* _err);
int32_t bimg_image_write_png(bimg_writer_t* _writer, uint32_t _width, uint32_t _height, uint32_t _srcPitch, const void* _src, uint32_t _format, bool _yflip, bimg_error_t* _err);
int32_t bimg_image_write_exr(bimg_writer_t* _writer, uint32_t _width, uint32_t _height, uint32_t _srcPitch, const void* _src, uint32_t _format, bool _yflip, bimg_error_t* _err);
int32_t bimg_image_write_dds(bimg_writer_t* _writer, bimg_image_container_t* _imageContainer, const void* _data, uint32_t _size, bimg_error_t* _err);
int32_t bimg_image_write_ktx(bimg_writer_t* _writer, uint32_t _format, bool _cubeMap, uint32_t _width, uint32_t _height, uint32_t _depth, uint8_t _numMips, uint32_t _numLayers, bool _srgb, const void* _src, bimg_error_t* _err);
int32_t bimg_image_write_ktx_ic(bimg_writer_t* _writer, bimg_image_container_t* _imageContainer, const void* _data, uint32_t _size, bimg_error_t* _err);
bool bimg_image_parse_reader(bimg_image_container_t* _imageContainer, bimg_reader_seeker_t* _reader, bimg_error_t* _err);
bool bimg_image_parse_mem(bimg_image_container_t* _imageContainer, const void* _data, uint32_t _size, bimg_error_t* _err);
bimg_image_container_t* bimg_image_parse_dds(bimg_allocator_t* _allocator, const void* _src, uint32_t _size, bimg_error_t* _err);
bimg_image_container_t* bimg_image_parse_ktx(bimg_allocator_t* _allocator, const void* _src, uint32_t _size, bimg_error_t* _err);
bimg_image_container_t* bimg_image_parse_pvr3(bimg_allocator_t* _allocator, const void* _src, uint32_t _size, bimg_error_t* _err);
void bimg_image_decode_to_r8(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _dstPitch, uint32_t _srcFormat);
void bimg_image_decode_to_bgra8(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _width, uint32_t _height, uint32_t _dstPitch, uint32_t _format);
void bimg_image_decode_to_rgba8(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _width, uint32_t _height, uint32_t _dstPitch, uint32_t _format);
void bimg_image_decode_to_rgba32f(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _dstPitch, uint32_t _format);
bool bimg_image_get_raw_data(const bimg_image_container_t* _imageContainer, uint16_t _side, uint8_t _lod, const void* _data, uint32_t _size, bimg_image_mip_t* _mip);

// =============================================================================
// bimg functions — encode.h (libbimg_encode.a)
// =============================================================================

void bimg_image_encode_from_rgba8(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _format, uint32_t _quality, bimg_error_t* _err);
void bimg_image_encode_from_rgba32f(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _format, uint32_t _quality, bimg_error_t* _err);
void bimg_image_encode(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _srcFormat, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _dstFormat, uint32_t _quality, bimg_error_t* _err);
bimg_image_container_t* bimg_image_encode_ic(bimg_allocator_t* _allocator, uint32_t _dstFormat, uint32_t _quality, const bimg_image_container_t* _input);
void bimg_image_rgba32f_11to01(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _pitch, const void* _src);
void bimg_image_make_dist(bimg_allocator_t* _allocator, void* _dst, uint32_t _width, uint32_t _height, uint32_t _srcPitch, const void* _src);
float bimg_image_quality_rgba8(const void* _reference, const void* _data, uint16_t _width, uint16_t _height);
bool bimg_image_resize_rgba32f_linear(bimg_image_container_t* _dst, const bimg_image_container_t* _src);
float bimg_image_alpha_test_coverage(uint32_t _format, uint32_t _width, uint32_t _height, uint32_t _srcPitch, const void* _src, float _alphaRef, float _scale, uint32_t _upscale);
void bimg_image_scale_alpha_to_coverage(uint32_t _format, uint32_t _width, uint32_t _height, uint32_t _srcPitch, void* _src, float _coverage, float _alphaRef, uint32_t _upscale);
bimg_image_container_t* bimg_image_cubemap_from_latlong_rgba32f(bimg_allocator_t* _allocator, const bimg_image_container_t* _input, bool _useBilinearInterpolation, bimg_error_t* _err);
bimg_image_container_t* bimg_image_cubemap_from_strip_rgba32f(bimg_allocator_t* _allocator, const bimg_image_container_t* _input, bimg_error_t* _err);
bimg_image_container_t* bimg_image_generate_mips(bimg_allocator_t* _allocator, const bimg_image_container_t* _image);
bimg_image_container_t* bimg_image_cubemap_radiance_filter(bimg_allocator_t* _allocator, const bimg_image_container_t* _image, uint32_t _lightingModel, bimg_error_t* _err);

// =============================================================================
// bimg functions — decode.h (libbimg_decode.a)
// =============================================================================

bimg_image_container_t* bimg_image_parse_decode(bimg_allocator_t* _allocator, const void* _data, uint32_t _size, uint32_t _dstFormat, bimg_error_t* _err);

/// Get the default bx::AllocatorI (static DefaultAllocator)
bimg_allocator_t* bimg_get_default_allocator(void);

#if defined(__cplusplus)
} // extern "C"
#endif // defined(__cplusplus)

#endif // BIMG_CAPI_H_HEADER_GUARD
