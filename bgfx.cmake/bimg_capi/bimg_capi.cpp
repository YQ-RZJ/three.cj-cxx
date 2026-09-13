/*
 * C wrapper implementation for bimg C++ API.
 * Exposes bimg functions as extern "C" for FFI interop with Cangjie.
 *
 * Design: bimg::ImageContainer is treated as an opaque pointer.
 * Field access is through getter functions. This avoids C/C++ struct
 * layout mismatch issues.
 */

#include "bimg_capi.h"

#include <bimg/bimg.h>
#include <bimg/encode.h>
#include <bimg/decode.h>
#include <bx/allocator.h>
#include <bx/error.h>

// =============================================================================
// Helper casts
// =============================================================================

static inline bx::AllocatorI* castAlloc(bimg_allocator_t* a) {
    return reinterpret_cast<bx::AllocatorI*>(a);
}

// =============================================================================
// Helper: cast opaque error pointer
// =============================================================================
static inline bx::Error* castErr(bimg_error_t* e) {
    return reinterpret_cast<bx::Error*>(e);
}

// =============================================================================
// Helper: cast opaque writer pointer
// =============================================================================
static inline bx::WriterI* castWriter(bimg_writer_t* w) {
    return reinterpret_cast<bx::WriterI*>(w);
}

// =============================================================================
// Helper: cast opaque reader seeker pointer
// =============================================================================
static inline bx::ReaderSeekerI* castReader(bimg_reader_seeker_t* r) {
    return reinterpret_cast<bx::ReaderSeekerI*>(r);
}

static inline bimg::ImageContainer* castIC(bimg_image_container_t* ic) {
    return reinterpret_cast<bimg::ImageContainer*>(ic);
}

static inline const bimg::ImageContainer* castICConst(const bimg_image_container_t* ic) {
    return reinterpret_cast<const bimg::ImageContainer*>(ic);
}

// =============================================================================
// ImageContainer field accessors
// =============================================================================

bimg_allocator_t* bimg_ic_get_allocator(const bimg_image_container_t* _ic) {
    return reinterpret_cast<bimg_allocator_t*>(castICConst(_ic)->m_allocator);
}

void* bimg_ic_get_data(const bimg_image_container_t* _ic) {
    return castICConst(_ic)->m_data;
}

uint32_t bimg_ic_get_format(const bimg_image_container_t* _ic) {
    return static_cast<uint32_t>(castICConst(_ic)->m_format);
}

uint32_t bimg_ic_get_orientation(const bimg_image_container_t* _ic) {
    return static_cast<uint32_t>(castICConst(_ic)->m_orientation);
}

uint32_t bimg_ic_get_size(const bimg_image_container_t* _ic) {
    return castICConst(_ic)->m_size;
}

uint32_t bimg_ic_get_offset(const bimg_image_container_t* _ic) {
    return castICConst(_ic)->m_offset;
}

uint32_t bimg_ic_get_width(const bimg_image_container_t* _ic) {
    return castICConst(_ic)->m_width;
}

uint32_t bimg_ic_get_height(const bimg_image_container_t* _ic) {
    return castICConst(_ic)->m_height;
}

uint32_t bimg_ic_get_depth(const bimg_image_container_t* _ic) {
    return castICConst(_ic)->m_depth;
}

uint16_t bimg_ic_get_num_layers(const bimg_image_container_t* _ic) {
    return castICConst(_ic)->m_numLayers;
}

uint8_t bimg_ic_get_num_mips(const bimg_image_container_t* _ic) {
    return castICConst(_ic)->m_numMips;
}

bool bimg_ic_get_has_alpha(const bimg_image_container_t* _ic) {
    return castICConst(_ic)->m_hasAlpha;
}

bool bimg_ic_get_cube_map(const bimg_image_container_t* _ic) {
    return castICConst(_ic)->m_cubeMap;
}

bool bimg_ic_get_ktx(const bimg_image_container_t* _ic) {
    return castICConst(_ic)->m_ktx;
}

bool bimg_ic_get_pvr3(const bimg_image_container_t* _ic) {
    return castICConst(_ic)->m_pvr3;
}

bool bimg_ic_get_srgb(const bimg_image_container_t* _ic) {
    return castICConst(_ic)->m_srgb;
}

// =============================================================================
// bimg functions — bimg.h (libbimg.a)
// =============================================================================

bool bimg_is_compressed(uint32_t _format) {
    return bimg::isCompressed(static_cast<bimg::TextureFormat::Enum>(_format));
}

bool bimg_is_color(uint32_t _format) {
    return bimg::isColor(static_cast<bimg::TextureFormat::Enum>(_format));
}

bool bimg_is_depth(uint32_t _format) {
    return bimg::isDepth(static_cast<bimg::TextureFormat::Enum>(_format));
}

bool bimg_is_valid(uint32_t _format) {
    return bimg::isValid(static_cast<bimg::TextureFormat::Enum>(_format));
}

bool bimg_is_float(uint32_t _format) {
    return bimg::isFloat(static_cast<bimg::TextureFormat::Enum>(_format));
}

uint8_t bimg_get_bits_per_pixel(uint32_t _format) {
    return bimg::getBitsPerPixel(static_cast<bimg::TextureFormat::Enum>(_format));
}

bimg_image_block_info_t bimg_get_block_info(uint32_t _format) {
    const bimg::ImageBlockInfo& info = bimg::getBlockInfo(static_cast<bimg::TextureFormat::Enum>(_format));
    bimg_image_block_info_t result;
    result.bitsPerPixel = info.bitsPerPixel;
    result.blockWidth   = info.blockWidth;
    result.blockHeight  = info.blockHeight;
    result.blockSize    = info.blockSize;
    result.minBlockX    = info.minBlockX;
    result.minBlockY    = info.minBlockY;
    result.depthBits    = info.depthBits;
    result.stencilBits  = info.stencilBits;
    result.rBits        = info.rBits;
    result.gBits        = info.gBits;
    result.bBits        = info.bBits;
    result.aBits        = info.aBits;
    result.encoding     = info.encoding;
    return result;
}

const char* bimg_get_name(uint32_t _format) {
    return bimg::getName(static_cast<bimg::TextureFormat::Enum>(_format));
}

uint32_t bimg_get_format(const char* _name) {
    return static_cast<uint32_t>(bimg::getFormat(_name));
}

uint8_t bimg_image_get_num_mips(uint32_t _format, uint16_t _width, uint16_t _height, uint16_t _depth) {
    return bimg::imageGetNumMips(static_cast<bimg::TextureFormat::Enum>(_format), _width, _height, _depth);
}

uint32_t bimg_image_get_size(bimg_texture_info_t* _info, uint16_t _width, uint16_t _height, uint16_t _depth, bool _cubeMap, bool _hasMips, uint16_t _numLayers, uint32_t _format) {
    bimg::TextureInfo* ti = reinterpret_cast<bimg::TextureInfo*>(_info);
    bimg::imageGetSize(ti, _width, _height, _depth, _cubeMap, _hasMips, _numLayers, static_cast<bimg::TextureFormat::Enum>(_format));
    return ti->storageSize;
}

void bimg_image_solid(void* _dst, uint32_t _width, uint32_t _height, uint32_t _solid) {
    bimg::imageSolid(_dst, _width, _height, _solid);
}

void bimg_image_checkerboard(void* _dst, uint32_t _width, uint32_t _height, uint32_t _step, uint32_t _0, uint32_t _1) {
    bimg::imageCheckerboard(_dst, _width, _height, _step, _0, _1);
}

void bimg_image_rgba8_downsample2x2(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _srcPitch, uint32_t _dstPitch, const void* _src) {
    bimg::imageRgba8Downsample2x2(_dst, _width, _height, _depth, _srcPitch, _dstPitch, _src);
}

void bimg_image_rgba32f_to_linear(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _srcPitch, const void* _src) {
    bimg::imageRgba32fToLinear(_dst, _width, _height, _depth, _srcPitch, _src);
}

void bimg_image_rgba32f_to_linear_ic(bimg_image_container_t* _imageContainer) {
    bimg::imageRgba32fToLinear(castIC(_imageContainer));
}

void bimg_image_rgba32f_to_gamma(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _srcPitch, const void* _src) {
    bimg::imageRgba32fToGamma(_dst, _width, _height, _depth, _srcPitch, _src);
}

void bimg_image_rgba32f_to_gamma_ic(bimg_image_container_t* _imageContainer) {
    bimg::imageRgba32fToGamma(castIC(_imageContainer));
}

void bimg_image_rgba32f_linear_downsample2x2(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _srcPitch, const void* _src) {
    bimg::imageRgba32fLinearDownsample2x2(_dst, _width, _height, _depth, _srcPitch, _src);
}

void bimg_image_rgba32f_downsample2x2(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _srcPitch, const void* _src) {
    bimg::imageRgba32fDownsample2x2(_dst, _width, _height, _depth, _srcPitch, _src);
}

void bimg_image_rgba32f_downsample2x2_normal_map(void* _dst, uint32_t _width, uint32_t _height, uint32_t _srcPitch, uint32_t _dstPitch, const void* _src) {
    bimg::imageRgba32fDownsample2x2NormalMap(_dst, _width, _height, _srcPitch, _dstPitch, _src);
}

void bimg_image_swizzle_bgra8(void* _dst, uint32_t _dstPitch, uint32_t _width, uint32_t _height, const void* _src, uint32_t _srcPitch) {
    bimg::imageSwizzleBgra8(_dst, _dstPitch, _width, _height, _src, _srcPitch);
}

void bimg_image_copy(void* _dst, uint32_t _height, uint32_t _srcPitch, uint32_t _depth, const void* _src, uint32_t _dstPitch) {
    bimg::imageCopy(_dst, _height, _srcPitch, _depth, _src, _dstPitch);
}

void bimg_image_copy_bpp(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _bpp, uint32_t _srcPitch, const void* _src) {
    bimg::imageCopy(_dst, _width, _height, _depth, _bpp, _srcPitch, _src);
}

bool bimg_image_convert(uint32_t _dstFormat, uint32_t _srcFormat) {
    return bimg::imageConvert(static_cast<bimg::TextureFormat::Enum>(_dstFormat), static_cast<bimg::TextureFormat::Enum>(_srcFormat));
}

void bimg_image_convert_raw(void* _dst, uint32_t _bpp, void* _packFn, const void* _src, void* _unpackFn, uint32_t _size) {
    bimg::imageConvert(_dst, _bpp, reinterpret_cast<bimg::PackFn>(_packFn), _src, reinterpret_cast<bimg::UnpackFn>(_unpackFn), _size);
}

void bimg_image_convert_dims(void* _dst, uint32_t _dstBpp, void* _packFn, const void* _src, uint32_t _srcBpp, void* _unpackFn, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _srcPitch, uint32_t _dstPitch) {
    bimg::imageConvert(_dst, _dstBpp, reinterpret_cast<bimg::PackFn>(_packFn), _src, _srcBpp, reinterpret_cast<bimg::UnpackFn>(_unpackFn), _width, _height, _depth, _srcPitch, _dstPitch);
}

bool bimg_image_convert_alloc(bimg_allocator_t* _allocator, void* _dst, uint32_t _dstFormat, const void* _src, uint32_t _srcFormat, uint32_t _width, uint32_t _height, uint32_t _depth) {
    return bimg::imageConvert(castAlloc(_allocator), _dst, static_cast<bimg::TextureFormat::Enum>(_dstFormat), _src, static_cast<bimg::TextureFormat::Enum>(_srcFormat), _width, _height, _depth);
}

bimg_image_container_t* bimg_image_alloc(bimg_allocator_t* _allocator, uint32_t _format, uint16_t _width, uint16_t _height, uint16_t _depth, uint16_t _numLayers, bool _cubeMap, bool _hasMips, const void* _data) {
    bimg::ImageContainer* ic = bimg::imageAlloc(castAlloc(_allocator), static_cast<bimg::TextureFormat::Enum>(_format), _width, _height, _depth, _numLayers, _cubeMap, _hasMips, _data);
    return reinterpret_cast<bimg_image_container_t*>(ic);
}

void bimg_image_free(bimg_image_container_t* _imageContainer) {
    bimg::imageFree(castIC(_imageContainer));
}

int32_t bimg_image_write_tga(bimg_writer_t* _writer, uint32_t _width, uint32_t _height, uint32_t _srcPitch, const void* _src, bool _grayscale, bool _yflip, bimg_error_t* _err) {
    return bimg::imageWriteTga(castWriter(_writer), _width, _height, _srcPitch, _src, _grayscale, _yflip, castErr(_err));
}

int32_t bimg_image_write_png(bimg_writer_t* _writer, uint32_t _width, uint32_t _height, uint32_t _srcPitch, const void* _src, uint32_t _format, bool _yflip, bimg_error_t* _err) {
    return bimg::imageWritePng(castWriter(_writer), _width, _height, _srcPitch, _src, static_cast<bimg::TextureFormat::Enum>(_format), _yflip, castErr(_err));
}

int32_t bimg_image_write_exr(bimg_writer_t* _writer, uint32_t _width, uint32_t _height, uint32_t _srcPitch, const void* _src, uint32_t _format, bool _yflip, bimg_error_t* _err) {
    return bimg::imageWriteExr(castWriter(_writer), _width, _height, _srcPitch, _src, static_cast<bimg::TextureFormat::Enum>(_format), _yflip, castErr(_err));
}

int32_t bimg_image_write_dds(bimg_writer_t* _writer, bimg_image_container_t* _imageContainer, const void* _data, uint32_t _size, bimg_error_t* _err) {
    return bimg::imageWriteDds(castWriter(_writer), *castIC(_imageContainer), _data, _size, castErr(_err));
}

int32_t bimg_image_write_ktx(bimg_writer_t* _writer, uint32_t _format, bool _cubeMap, uint32_t _width, uint32_t _height, uint32_t _depth, uint8_t _numMips, uint32_t _numLayers, bool _srgb, const void* _src, bimg_error_t* _err) {
    return bimg::imageWriteKtx(castWriter(_writer), static_cast<bimg::TextureFormat::Enum>(_format), _cubeMap, _width, _height, _depth, _numMips, _numLayers, _srgb, _src, castErr(_err));
}

int32_t bimg_image_write_ktx_ic(bimg_writer_t* _writer, bimg_image_container_t* _imageContainer, const void* _data, uint32_t _size, bimg_error_t* _err) {
    return bimg::imageWriteKtx(castWriter(_writer), *castIC(_imageContainer), _data, _size, castErr(_err));
}

bool bimg_image_parse_reader(bimg_image_container_t* _imageContainer, bimg_reader_seeker_t* _reader, bimg_error_t* _err) {
    return bimg::imageParse(*castIC(_imageContainer), castReader(_reader), castErr(_err));
}

bool bimg_image_parse_mem(bimg_image_container_t* _imageContainer, const void* _data, uint32_t _size, bimg_error_t* _err) {
    return bimg::imageParse(*castIC(_imageContainer), _data, _size, castErr(_err));
}

bimg_image_container_t* bimg_image_parse_dds(bimg_allocator_t* _allocator, const void* _src, uint32_t _size, bimg_error_t* _err) {
    bimg::ImageContainer* ic = bimg::imageParseDds(castAlloc(_allocator), _src, _size, castErr(_err));
    return reinterpret_cast<bimg_image_container_t*>(ic);
}

bimg_image_container_t* bimg_image_parse_ktx(bimg_allocator_t* _allocator, const void* _src, uint32_t _size, bimg_error_t* _err) {
    bimg::ImageContainer* ic = bimg::imageParseKtx(castAlloc(_allocator), _src, _size, castErr(_err));
    return reinterpret_cast<bimg_image_container_t*>(ic);
}

bimg_image_container_t* bimg_image_parse_pvr3(bimg_allocator_t* _allocator, const void* _src, uint32_t _size, bimg_error_t* _err) {
    bimg::ImageContainer* ic = bimg::imageParsePvr3(castAlloc(_allocator), _src, _size, castErr(_err));
    return reinterpret_cast<bimg_image_container_t*>(ic);
}

void bimg_image_decode_to_r8(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _dstPitch, uint32_t _srcFormat) {
    bimg::imageDecodeToR8(castAlloc(_allocator), _dst, _src, _width, _height, _depth, _dstPitch, static_cast<bimg::TextureFormat::Enum>(_srcFormat));
}

void bimg_image_decode_to_bgra8(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _width, uint32_t _height, uint32_t _dstPitch, uint32_t _format) {
    bimg::imageDecodeToBgra8(castAlloc(_allocator), _dst, _src, _width, _height, _dstPitch, static_cast<bimg::TextureFormat::Enum>(_format));
}

void bimg_image_decode_to_rgba8(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _width, uint32_t _height, uint32_t _dstPitch, uint32_t _format) {
    bimg::imageDecodeToRgba8(castAlloc(_allocator), _dst, _src, _width, _height, _dstPitch, static_cast<bimg::TextureFormat::Enum>(_format));
}

void bimg_image_decode_to_rgba32f(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _dstPitch, uint32_t _format) {
    bimg::imageDecodeToRgba32f(castAlloc(_allocator), _dst, _src, _width, _height, _depth, _dstPitch, static_cast<bimg::TextureFormat::Enum>(_format));
}

bool bimg_image_get_raw_data(const bimg_image_container_t* _imageContainer, uint16_t _side, uint8_t _lod, const void* _data, uint32_t _size, bimg_image_mip_t* _mip) {
    bimg::ImageMip mip;
    bool result = bimg::imageGetRawData(*castICConst(_imageContainer), _side, _lod, _data, _size, mip);
    if (result && _mip) {
        _mip->m_format    = static_cast<uint32_t>(mip.m_format);
        _mip->m_width     = mip.m_width;
        _mip->m_height    = mip.m_height;
        _mip->m_depth     = mip.m_depth;
        _mip->m_blockSize = mip.m_blockSize;
        _mip->m_size      = mip.m_size;
        _mip->m_bpp       = mip.m_bpp;
        _mip->m_hasAlpha  = mip.m_hasAlpha;
        _mip->m_data      = mip.m_data;
    }
    return result;
}

// =============================================================================
// bimg functions — encode.h (libbimg_encode.a)
// =============================================================================

void bimg_image_encode_from_rgba8(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _format, uint32_t _quality, bimg_error_t* _err) {
    bimg::imageEncodeFromRgba8(castAlloc(_allocator), _dst, _src, _width, _height, _depth, static_cast<bimg::TextureFormat::Enum>(_format), static_cast<bimg::Quality::Enum>(_quality), castErr(_err));
}

void bimg_image_encode_from_rgba32f(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _format, uint32_t _quality, bimg_error_t* _err) {
    bimg::imageEncodeFromRgba32f(castAlloc(_allocator), _dst, _src, _width, _height, _depth, static_cast<bimg::TextureFormat::Enum>(_format), static_cast<bimg::Quality::Enum>(_quality), castErr(_err));
}

void bimg_image_encode(bimg_allocator_t* _allocator, void* _dst, const void* _src, uint32_t _srcFormat, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _dstFormat, uint32_t _quality, bimg_error_t* _err) {
    bimg::imageEncode(castAlloc(_allocator), _dst, _src, static_cast<bimg::TextureFormat::Enum>(_srcFormat), _width, _height, _depth, static_cast<bimg::TextureFormat::Enum>(_dstFormat), static_cast<bimg::Quality::Enum>(_quality), castErr(_err));
}

bimg_image_container_t* bimg_image_encode_ic(bimg_allocator_t* _allocator, uint32_t _dstFormat, uint32_t _quality, const bimg_image_container_t* _input) {
    bimg::ImageContainer* result = bimg::imageEncode(castAlloc(_allocator), static_cast<bimg::TextureFormat::Enum>(_dstFormat), static_cast<bimg::Quality::Enum>(_quality), *castICConst(_input));
    return reinterpret_cast<bimg_image_container_t*>(result);
}

void bimg_image_rgba32f_11to01(void* _dst, uint32_t _width, uint32_t _height, uint32_t _depth, uint32_t _pitch, const void* _src) {
    bimg::imageRgba32f11to01(_dst, _width, _height, _depth, _pitch, _src);
}

void bimg_image_make_dist(bimg_allocator_t* _allocator, void* _dst, uint32_t _width, uint32_t _height, uint32_t _srcPitch, const void* _src) {
    bimg::imageMakeDist(castAlloc(_allocator), _dst, _width, _height, _srcPitch, _src);
}

float bimg_image_quality_rgba8(const void* _reference, const void* _data, uint16_t _width, uint16_t _height) {
    return bimg::imageQualityRgba8(_reference, _data, _width, _height);
}

bool bimg_image_resize_rgba32f_linear(bimg_image_container_t* _dst, const bimg_image_container_t* _src) {
    return bimg::imageResizeRgba32fLinear(castIC(_dst), castICConst(_src));
}

float bimg_image_alpha_test_coverage(uint32_t _format, uint32_t _width, uint32_t _height, uint32_t _srcPitch, const void* _src, float _alphaRef, float _scale, uint32_t _upscale) {
    return bimg::imageAlphaTestCoverage(static_cast<bimg::TextureFormat::Enum>(_format), _width, _height, _srcPitch, _src, _alphaRef, _scale, _upscale);
}

void bimg_image_scale_alpha_to_coverage(uint32_t _format, uint32_t _width, uint32_t _height, uint32_t _srcPitch, void* _src, float _coverage, float _alphaRef, uint32_t _upscale) {
    bimg::imageScaleAlphaToCoverage(static_cast<bimg::TextureFormat::Enum>(_format), _width, _height, _srcPitch, _src, _coverage, _alphaRef, _upscale);
}

bimg_image_container_t* bimg_image_cubemap_from_latlong_rgba32f(bimg_allocator_t* _allocator, const bimg_image_container_t* _input, bool _useBilinearInterpolation, bimg_error_t* _err) {
    bimg::ImageContainer* result = bimg::imageCubemapFromLatLongRgba32F(castAlloc(_allocator), *castICConst(_input), _useBilinearInterpolation, castErr(_err));
    return reinterpret_cast<bimg_image_container_t*>(result);
}

bimg_image_container_t* bimg_image_cubemap_from_strip_rgba32f(bimg_allocator_t* _allocator, const bimg_image_container_t* _input, bimg_error_t* _err) {
    bimg::ImageContainer* result = bimg::imageCubemapFromStripRgba32F(castAlloc(_allocator), *castICConst(_input), castErr(_err));
    return reinterpret_cast<bimg_image_container_t*>(result);
}

bimg_image_container_t* bimg_image_generate_mips(bimg_allocator_t* _allocator, const bimg_image_container_t* _image) {
    bimg::ImageContainer* result = bimg::imageGenerateMips(castAlloc(_allocator), *castICConst(_image));
    return reinterpret_cast<bimg_image_container_t*>(result);
}

bimg_image_container_t* bimg_image_cubemap_radiance_filter(bimg_allocator_t* _allocator, const bimg_image_container_t* _image, uint32_t _lightingModel, bimg_error_t* _err) {
    bimg::ImageContainer* result = bimg::imageCubemapRadianceFilter(castAlloc(_allocator), *castICConst(_image), static_cast<bimg::LightingModel::Enum>(_lightingModel), castErr(_err));
    return reinterpret_cast<bimg_image_container_t*>(result);
}

// =============================================================================
// bimg functions — decode.h (libbimg_decode.a)
// =============================================================================

bimg_image_container_t* bimg_image_parse_decode(bimg_allocator_t* _allocator, const void* _data, uint32_t _size, uint32_t _dstFormat, bimg_error_t* _err) {
    bimg::ImageContainer* ic = bimg::imageParse(castAlloc(_allocator), _data, _size, static_cast<bimg::TextureFormat::Enum>(_dstFormat), castErr(_err));
    return reinterpret_cast<bimg_image_container_t*>(ic);
}

bimg_allocator_t* bimg_get_default_allocator(void) {
    static bx::DefaultAllocator s_allocator;
    return reinterpret_cast<bimg_allocator_t*>(&s_allocator);
}
