// ============================================================================
// RequireCJLibNAPI.cpp — requireCJLib 的 OHOS NAPI 实现
//
// 将 requireCJLib 的仓颉运行时 C API 封装为 NAPI 方法，供 ArkTS 调用。
// 遵循 OHOS NAPI 规范（node_api.h），参考 SDL_ohos.cpp 的注册模式。
//
// 编译为 .a 后链接到仓颉 .so 产物中，ArkTS 侧通过
//   import requireCJLib from 'requireCJLib';
// 即可调用所有注册方法。
//
// 所有导出函数均标记 __attribute__((used))，确保链接后不被剔除。
//
// 参数传递链路：ArkTS → NAPI(C/C++) → 仓颉运行时
//   1. ArkTS 通过 allocBuffer 分配原生内存
//   2. 通过 write* 系列方法按仓颉 CType 内存布局写入参数
//   3. 将 buffer 指针（bigint）传给 runTask/runTaskAndAwait
//   4. 仓颉函数通过 void* 接收参数，按 @C struct 布局读取
//   5. 返回值同理，通过 read* 系列方法从返回地址读取
// ============================================================================
#include "requireCJLib/RequireCJLibNAPI.h"
#include "requireCJLib/RequireCJLib.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <string>

// 跨编译器兼容的"强制保留符号"宏
#if defined(__GNUC__) || defined(__clang__)
  #define CJ_FFI_USED __attribute__((used))
#else
  #define CJ_FFI_USED
#endif

// ============================================================================
// 辅助函数：NAPI 参数解析与创建
// ============================================================================

namespace {

// ---- 参数解析 ----

// 从 argv[index] 提取 string
std::string getStringArg(napi_env env, napi_value* argv, size_t index) {
    napi_valuetype type;
    napi_typeof(env, argv[index], &type);
    if (type != napi_string) return "";

    size_t len = 0;
    napi_get_value_string_utf8(env, argv[index], nullptr, 0, &len);
    std::string result(len, '\0');
    napi_get_value_string_utf8(env, argv[index], result.data(), len + 1, &len);
    return result;
}

// 从 argv[index] 提取 int32
int32_t getInt32Arg(napi_env env, napi_value* argv, size_t index) {
    int32_t result = 0;
    napi_get_value_int32(env, argv[index], &result);
    return result;
}

// 从 argv[index] 提取 int64
int64_t getInt64Arg(napi_env env, napi_value* argv, size_t index) {
    int64_t result = 0;
    napi_get_value_int64(env, argv[index], &result);
    return result;
}

// 从 argv[index] 提取 double
double getDoubleArg(napi_env env, napi_value* argv, size_t index) {
    double result = 0.0;
    napi_get_value_double(env, argv[index], &result);
    return result;
}

// 从 argv[index] 提取 bool
bool getBoolArg(napi_env env, napi_value* argv, size_t index) {
    bool result = false;
    napi_get_value_bool(env, argv[index], &result);
    return result;
}

// 从 argv[index] 提取 bigint（int64，用于指针地址）
int64_t getBigIntArg(napi_env env, napi_value* argv, size_t index) {
    int64_t result = 0;
    napi_valuetype type;
    napi_typeof(env, argv[index], &type);
    if (type == napi_bigint) {
        bool lossless = false;
        napi_get_value_bigint_int64(env, argv[index], &result, &lossless);
    }
    return result;
}

// 从 argv[index] 提取 uint64 bigint
uint64_t getBigUint64Arg(napi_env env, napi_value* argv, size_t index) {
    uint64_t result = 0;
    napi_valuetype type;
    napi_typeof(env, argv[index], &type);
    if (type == napi_bigint) {
        bool lossless = false;
        napi_get_value_bigint_uint64(env, argv[index], &result, &lossless);
    }
    return result;
}

// ---- 值创建 ----

napi_value createInt32(napi_env env, int32_t value) {
    napi_value result;
    napi_create_int32(env, value, &result);
    return result;
}

napi_value createBigInt(napi_env env, int64_t value) {
    napi_value result;
    napi_create_bigint_int64(env, value, &result);
    return result;
}

napi_value createBigUint64(napi_env env, uint64_t value) {
    napi_value result;
    napi_create_bigint_uint64(env, value, &result);
    return result;
}

napi_value createDouble(napi_env env, double value) {
    napi_value result;
    napi_create_double(env, value, &result);
    return result;
}

napi_value createBool(napi_env env, bool value) {
    napi_value result;
    napi_get_boolean(env, value, &result);
    return result;
}

napi_value createUndefined(napi_env env) {
    napi_value result;
    napi_get_undefined(env, &result);
    return result;
}

napi_value createNull(napi_env env) {
    napi_value result;
    napi_get_null(env, &result);
    return result;
}

// 从 argv[index] 提取指针地址（支持 bigint 或 number）
void* getPointerArg(napi_env env, napi_value* argv, size_t index) {
    napi_valuetype type;
    napi_typeof(env, argv[index], &type);
    if (type == napi_bigint) {
        int64_t val = 0;
        bool lossless = false;
        napi_get_value_bigint_int64(env, argv[index], &val, &lossless);
        return reinterpret_cast<void*>(val);
    }
    if (type == napi_number) {
        double val = 0;
        napi_get_value_double(env, argv[index], &val);
        return reinterpret_cast<void*>(static_cast<int64_t>(val));
    }
    return nullptr;
}

}  // namespace

// ============================================================================
// NAPI 方法实现
// ============================================================================

namespace requirecj_napi {

// ---- 运行时生命周期 ----

// initRuntime(): 初始化仓颉运行时（使用默认配置）
// 返回：number（错误码，0=成功）
CJ_FFI_USED
napi_value NAPI_InitRuntime(napi_env env, napi_callback_info info) {
    size_t argc = 0;
    napi_get_cb_info(env, info, &argc, nullptr, nullptr, nullptr);

    CJRuntimeParam param{};
    int rc = InitCJRuntime(&param);
    return createInt32(env, rc);
}

// finiRuntime(): 结束仓颉运行时
// 返回：number（错误码，0=成功）
CJ_FFI_USED
napi_value NAPI_FiniRuntime(napi_env env, napi_callback_info info) {
    int rc = FiniCJRuntime();
    return createInt32(env, rc);
}

// isRuntimeInitialized(): 查询运行时是否已初始化
// 返回：boolean
CJ_FFI_USED
napi_value NAPI_IsRuntimeInitialized(napi_env env, napi_callback_info info) {
    int rc = InitCJRuntime(nullptr);
    return createBool(env, rc == CJ_E_OK);
}

// ---- 动态库管理 ----

// loadLibrary(libName: string): 仅加载动态库
CJ_FFI_USED
napi_value NAPI_LoadLibrary(napi_env env, napi_callback_info info) {
    size_t argc = 1;
    napi_value argv[1] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    std::string libName = getStringArg(env, argv, 0);
    int rc = LoadCJLibrary(libName.c_str());
    return createInt32(env, rc);
}

// initLibrary(libName: string): 仅初始化动态库
CJ_FFI_USED
napi_value NAPI_InitLibrary(napi_env env, napi_callback_info info) {
    size_t argc = 1;
    napi_value argv[1] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    std::string libName = getStringArg(env, argv, 0);
    int rc = InitCJLibrary(libName.c_str());
    return createInt32(env, rc);
}

// loadLibraryWithInit(libName: string): 加载 + 初始化
CJ_FFI_USED
napi_value NAPI_LoadLibraryWithInit(napi_env env, napi_callback_info info) {
    size_t argc = 1;
    napi_value argv[1] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    std::string libName = getStringArg(env, argv, 0);
    int rc = LoadCJLibraryWithInit(libName.c_str());
    return createInt32(env, rc);
}

// unloadLibrary(libName: string): 卸载动态库
CJ_FFI_USED
napi_value NAPI_UnloadLibrary(napi_env env, napi_callback_info info) {
    size_t argc = 1;
    napi_value argv[1] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    std::string libName = getStringArg(env, argv, 0);
    int rc = UnloadCJLibrary(libName.c_str());
    return createInt32(env, rc);
}

// findSymbol(libName: string, symbolName: string): 查找导出符号
// 返回：bigint（函数指针地址，0=未找到）
CJ_FFI_USED
napi_value NAPI_FindSymbol(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    std::string libName = getStringArg(env, argv, 0);
    std::string symbolName = getStringArg(env, argv, 1);
    void* addr = FindCJSymbol(libName.c_str(), symbolName.c_str());
    return createBigInt(env, reinterpret_cast<int64_t>(addr));
}

// ---- 任务执行 ----

// runTask(funcPtr: bigint, argsPtr: bigint): 异步执行仓颉函数
// 返回：bigint（任务句柄，0=失败）
CJ_FFI_USED
napi_value NAPI_RunTask(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    int64_t funcPtr = getBigIntArg(env, argv, 0);
    int64_t argsPtr = getBigIntArg(env, argv, 1);

    auto func = reinterpret_cast<CJTaskFunc>(funcPtr);
    void* args = reinterpret_cast<void*>(argsPtr);

    CJThreadHandle handle = RunCJTask(func, args);
    return createBigInt(env, reinterpret_cast<int64_t>(handle));
}

// getTaskRet(handle: bigint): 阻塞获取任务结果
// 返回：bigint（函数返回值/指针地址）
CJ_FFI_USED
napi_value NAPI_GetTaskRet(napi_env env, napi_callback_info info) {
    size_t argc = 1;
    napi_value argv[1] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    int64_t handlePtr = getBigIntArg(env, argv, 0);
    auto handle = reinterpret_cast<CJThreadHandle>(handlePtr);

    void* ret = nullptr;
    int rc = GetTaskRet(handle, &ret);
    if (rc != CJ_E_OK) {
        return createBigInt(env, 0);
    }
    return createBigInt(env, reinterpret_cast<int64_t>(ret));
}

// getTaskRetWithTimeout(handle: bigint, timeoutMs: number): 带超时获取结果
CJ_FFI_USED
napi_value NAPI_GetTaskRetWithTimeout(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    int64_t handlePtr = getBigIntArg(env, argv, 0);
    int64_t timeoutMs = getInt64Arg(env, argv, 1);
    auto handle = reinterpret_cast<CJThreadHandle>(handlePtr);

    void* ret = nullptr;
    int rc = GetTaskRetWithTimeout(handle, &ret, timeoutMs);
    if (rc != CJ_E_OK) {
        return createBigInt(env, 0);
    }
    return createBigInt(env, reinterpret_cast<int64_t>(ret));
}

// releaseHandle(handle: bigint): 释放任务句柄
CJ_FFI_USED
napi_value NAPI_ReleaseHandle(napi_env env, napi_callback_info info) {
    size_t argc = 1;
    napi_value argv[1] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    int64_t handlePtr = getBigIntArg(env, argv, 0);
    auto handle = reinterpret_cast<CJThreadHandle>(handlePtr);
    ReleaseHandle(handle);
    return createUndefined(env);
}

// runTaskAndAwait(funcPtr: bigint, argsPtr: bigint, timeoutMs?: number):
//   同步执行仓颉函数并获取结果
// 返回：bigint（函数返回值/指针地址）
CJ_FFI_USED
napi_value NAPI_RunTaskAndAwait(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    int64_t funcPtr = getBigIntArg(env, argv, 0);
    int64_t argsPtr = getBigIntArg(env, argv, 1);
    int64_t timeoutMs = (argc >= 3) ? getInt64Arg(env, argv, 2) : 0;

    auto func = reinterpret_cast<CJTaskFunc>(funcPtr);
    void* args = reinterpret_cast<void*>(argsPtr);

    if (func == nullptr) {
        std::fprintf(stderr, "[requireCJLib NAPI] runTaskAndAwait: null function pointer\n");
        return createBigInt(env, 0);
    }

    CJThreadHandle handle = RunCJTask(func, args);
    if (handle == nullptr) {
        std::fprintf(stderr, "[requireCJLib NAPI] runTaskAndAwait: RunCJTask failed\n");
        return createBigInt(env, 0);
    }

    void* ret = nullptr;
    int rc = (timeoutMs > 0)
                 ? GetTaskRetWithTimeout(handle, &ret, timeoutMs)
                 : GetTaskRet(handle, &ret);
    ReleaseHandle(handle);

    if (rc != CJ_E_OK) {
        return createBigInt(env, 0);
    }
    return createBigInt(env, reinterpret_cast<int64_t>(ret));
}

// ============================================================================
// Buffer 管理 — 打通 ArkTS → C/C++ → 仓颉 参数传递链路
//
// 原理：
//   ArkTS 无法直接获取原生内存地址，因此提供 allocBuffer/freeBuffer 让
//   ArkTS 在 C/C++ 堆上分配内存，再通过 write*/read* 系列方法按仓颉
//   CType 的内存布局读写各类型数据。最终将 buffer 指针（bigint）传给
//   runTask/runTaskAndAwait，仓颉函数通过 void* 接收并按 @C struct
//   布局解读参数。
// ============================================================================

// ---- Buffer 分配/释放 ----

// allocBuffer(size: number): 分配原生内存
// 返回：bigint（内存地址）
CJ_FFI_USED
napi_value NAPI_AllocBuffer(napi_env env, napi_callback_info info) {
    size_t argc = 1;
    napi_value argv[1] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    int64_t size = getInt64Arg(env, argv, 0);
    if (size <= 0) {
        return createBigInt(env, 0);
    }
    void* ptr = std::calloc(1, static_cast<size_t>(size));
    return createBigInt(env, reinterpret_cast<int64_t>(ptr));
}

// freeBuffer(ptr: bigint): 释放原生内存
CJ_FFI_USED
napi_value NAPI_FreeBuffer(napi_env env, napi_callback_info info) {
    size_t argc = 1;
    napi_value argv[1] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    void* ptr = getPointerArg(env, argv, 0);
    if (ptr) {
        std::free(ptr);
    }
    return createUndefined(env);
}

// memsetBuffer(ptr: bigint, value: number, size: number): 填充内存
CJ_FFI_USED
napi_value NAPI_MemsetBuffer(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    void* ptr = getPointerArg(env, argv, 0);
    int32_t value = getInt32Arg(env, argv, 1);
    int64_t size = getInt64Arg(env, argv, 2);
    if (ptr && size > 0) {
        std::memset(ptr, value, static_cast<size_t>(size));
    }
    return createUndefined(env);
}

// ---- Buffer 写入 ----
// 所有写入方法签名：write*(ptr: bigint, offset: number, value: T)

// writeBool(ptr, offset, value: boolean)
CJ_FFI_USED
napi_value NAPI_WriteBool(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    bool value = getBoolArg(env, argv, 2);
    if (base) {
        base[offset] = value ? 1 : 0;
    }
    return createUndefined(env);
}

// writeInt8(ptr, offset, value: number)
CJ_FFI_USED
napi_value NAPI_WriteInt8(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    int32_t value = getInt32Arg(env, argv, 2);
    if (base) {
        *reinterpret_cast<int8_t*>(base + offset) = static_cast<int8_t>(value);
    }
    return createUndefined(env);
}

// writeUInt8(ptr, offset, value: number)
CJ_FFI_USED
napi_value NAPI_WriteUInt8(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    int32_t value = getInt32Arg(env, argv, 2);
    if (base) {
        base[offset] = static_cast<uint8_t>(value);
    }
    return createUndefined(env);
}

// writeInt16(ptr, offset, value: number)
CJ_FFI_USED
napi_value NAPI_WriteInt16(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    int32_t value = getInt32Arg(env, argv, 2);
    if (base) {
        int16_t v = static_cast<int16_t>(value);
        std::memcpy(base + offset, &v, sizeof(v));
    }
    return createUndefined(env);
}

// writeUInt16(ptr, offset, value: number)
CJ_FFI_USED
napi_value NAPI_WriteUInt16(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    int32_t value = getInt32Arg(env, argv, 2);
    if (base) {
        uint16_t v = static_cast<uint16_t>(value);
        std::memcpy(base + offset, &v, sizeof(v));
    }
    return createUndefined(env);
}

// writeInt32(ptr, offset, value: number)
CJ_FFI_USED
napi_value NAPI_WriteInt32(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    int32_t value = getInt32Arg(env, argv, 2);
    if (base) {
        std::memcpy(base + offset, &value, sizeof(value));
    }
    return createUndefined(env);
}

// writeUInt32(ptr, offset, value: number)
CJ_FFI_USED
napi_value NAPI_WriteUInt32(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    double value = getDoubleArg(env, argv, 2);
    if (base) {
        uint32_t v = static_cast<uint32_t>(value);
        std::memcpy(base + offset, &v, sizeof(v));
    }
    return createUndefined(env);
}

// writeInt64(ptr, offset, value: bigint)
CJ_FFI_USED
napi_value NAPI_WriteInt64(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    int64_t value = getBigIntArg(env, argv, 2);
    if (base) {
        std::memcpy(base + offset, &value, sizeof(value));
    }
    return createUndefined(env);
}

// writeUInt64(ptr, offset, value: bigint)
CJ_FFI_USED
napi_value NAPI_WriteUInt64(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    uint64_t value = getBigUint64Arg(env, argv, 2);
    if (base) {
        std::memcpy(base + offset, &value, sizeof(value));
    }
    return createUndefined(env);
}

// writeFloat32(ptr, offset, value: number)
CJ_FFI_USED
napi_value NAPI_WriteFloat32(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    double value = getDoubleArg(env, argv, 2);
    if (base) {
        float v = static_cast<float>(value);
        std::memcpy(base + offset, &v, sizeof(v));
    }
    return createUndefined(env);
}

// writeFloat64(ptr, offset, value: number)
CJ_FFI_USED
napi_value NAPI_WriteFloat64(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    double value = getDoubleArg(env, argv, 2);
    if (base) {
        std::memcpy(base + offset, &value, sizeof(value));
    }
    return createUndefined(env);
}

// writePointer(ptr, offset, value: bigint) — 写入指针地址
CJ_FFI_USED
napi_value NAPI_WritePointer(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    int64_t value = getBigIntArg(env, argv, 2);
    if (base) {
        void* ptr = reinterpret_cast<void*>(value);
        std::memcpy(base + offset, &ptr, sizeof(ptr));
    }
    return createUndefined(env);
}

// writeString(ptr, offset, value: string) — 写入 UTF-8 字符串（含 null 终止符）
CJ_FFI_USED
napi_value NAPI_WriteString(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    std::string value = getStringArg(env, argv, 2);
    if (base) {
        std::memcpy(base + offset, value.c_str(), value.size() + 1);  // 含 '\0'
    }
    return createUndefined(env);
}

// writeBytes(ptr, offset, value: ArrayBuffer) — 写入原始字节
CJ_FFI_USED
napi_value NAPI_WriteBytes(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);

    // 从 ArrayBuffer 获取数据
    bool isBuffer = false;
    napi_is_buffer(env, argv[2], &isBuffer);
    if (isBuffer && base) {
        void* data = nullptr;
        size_t len = 0;
        napi_get_buffer_info(env, argv[2], &data, &len);
        if (data && len > 0) {
            std::memcpy(base + offset, data, len);
        }
    }
    return createUndefined(env);
}

// ---- Buffer 读取 ----
// 所有读取方法签名：read*(ptr: bigint, offset: number)

// readBool(ptr, offset) → boolean
CJ_FFI_USED
napi_value NAPI_ReadBool(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    bool value = base ? (base[offset] != 0) : false;
    return createBool(env, value);
}

// readInt8(ptr, offset) → number
CJ_FFI_USED
napi_value NAPI_ReadInt8(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    int8_t value = 0;
    if (base) {
        std::memcpy(&value, base + offset, sizeof(value));
    }
    return createInt32(env, value);
}

// readUInt8(ptr, offset) → number
CJ_FFI_USED
napi_value NAPI_ReadUInt8(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    uint8_t value = base ? base[offset] : 0;
    return createInt32(env, value);
}

// readInt16(ptr, offset) → number
CJ_FFI_USED
napi_value NAPI_ReadInt16(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    int16_t value = 0;
    if (base) {
        std::memcpy(&value, base + offset, sizeof(value));
    }
    return createInt32(env, value);
}

// readUInt16(ptr, offset) → number
CJ_FFI_USED
napi_value NAPI_ReadUInt16(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    uint16_t value = 0;
    if (base) {
        std::memcpy(&value, base + offset, sizeof(value));
    }
    return createInt32(env, value);
}

// readInt32(ptr, offset) → number
CJ_FFI_USED
napi_value NAPI_ReadInt32(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    int32_t value = 0;
    if (base) {
        std::memcpy(&value, base + offset, sizeof(value));
    }
    return createInt32(env, value);
}

// readUInt32(ptr, offset) → number
CJ_FFI_USED
napi_value NAPI_ReadUInt32(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    uint32_t value = 0;
    if (base) {
        std::memcpy(&value, base + offset, sizeof(value));
    }
    return createDouble(env, static_cast<double>(value));
}

// readInt64(ptr, offset) → bigint
CJ_FFI_USED
napi_value NAPI_ReadInt64(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    int64_t value = 0;
    if (base) {
        std::memcpy(&value, base + offset, sizeof(value));
    }
    return createBigInt(env, value);
}

// readUInt64(ptr, offset) → bigint
CJ_FFI_USED
napi_value NAPI_ReadUInt64(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    uint64_t value = 0;
    if (base) {
        std::memcpy(&value, base + offset, sizeof(value));
    }
    return createBigUint64(env, value);
}

// readFloat32(ptr, offset) → number
CJ_FFI_USED
napi_value NAPI_ReadFloat32(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    float value = 0.0f;
    if (base) {
        std::memcpy(&value, base + offset, sizeof(value));
    }
    return createDouble(env, static_cast<double>(value));
}

// readFloat64(ptr, offset) → number
CJ_FFI_USED
napi_value NAPI_ReadFloat64(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    double value = 0.0;
    if (base) {
        std::memcpy(&value, base + offset, sizeof(value));
    }
    return createDouble(env, value);
}

// readPointer(ptr, offset) → bigint（指针地址）
CJ_FFI_USED
napi_value NAPI_ReadPointer(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    void* value = nullptr;
    if (base) {
        std::memcpy(&value, base + offset, sizeof(value));
    }
    return createBigInt(env, reinterpret_cast<int64_t>(value));
}

// readString(ptr, offset) → string（读取 null 终止的 UTF-8 字符串）
CJ_FFI_USED
napi_value NAPI_ReadString(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    if (!base) {
        napi_value result;
        napi_create_string_utf8(env, "", 0, &result);
        return result;
    }
    const char* str = reinterpret_cast<const char*>(base + offset);
    napi_value result;
    napi_create_string_utf8(env, str, std::strlen(str), &result);
    return result;
}

// readBytes(ptr, offset, length) → ArrayBuffer
CJ_FFI_USED
napi_value NAPI_ReadBytes(napi_env env, napi_callback_info info) {
    size_t argc = 3;
    napi_value argv[3] = {nullptr};
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);

    uint8_t* base = reinterpret_cast<uint8_t*>(getPointerArg(env, argv, 0));
    int64_t offset = getInt64Arg(env, argv, 1);
    int64_t length = getInt64Arg(env, argv, 2);
    if (!base || length <= 0) {
        // 返回空 ArrayBuffer
        napi_value result;
        void* data = nullptr;
        napi_create_arraybuffer(env, 0, &data, &result);
        return result;
    }

    napi_value result;
    void* data = nullptr;
    napi_create_arraybuffer(env, static_cast<size_t>(length), &data, &result);
    if (data) {
        std::memcpy(data, base + offset, static_cast<size_t>(length));
    }
    return result;
}

// ============================================================================
// NAPI 模块注册
// ============================================================================

// Init: 注册所有方法到 exports 对象
napi_value Init(napi_env env, napi_value exports) {
    napi_property_descriptor desc[] = {
        // ---- 运行时生命周期 ----
        {"initRuntime",           nullptr, NAPI_InitRuntime,           nullptr, nullptr, nullptr, napi_default, nullptr},
        {"finiRuntime",           nullptr, NAPI_FiniRuntime,           nullptr, nullptr, nullptr, napi_default, nullptr},
        {"isRuntimeInitialized",  nullptr, NAPI_IsRuntimeInitialized,  nullptr, nullptr, nullptr, napi_default, nullptr},

        // ---- 动态库管理 ----
        {"loadLibrary",           nullptr, NAPI_LoadLibrary,           nullptr, nullptr, nullptr, napi_default, nullptr},
        {"initLibrary",           nullptr, NAPI_InitLibrary,           nullptr, nullptr, nullptr, napi_default, nullptr},
        {"loadLibraryWithInit",   nullptr, NAPI_LoadLibraryWithInit,   nullptr, nullptr, nullptr, napi_default, nullptr},
        {"unloadLibrary",         nullptr, NAPI_UnloadLibrary,         nullptr, nullptr, nullptr, napi_default, nullptr},
        {"findSymbol",            nullptr, NAPI_FindSymbol,            nullptr, nullptr, nullptr, napi_default, nullptr},

        // ---- 任务执行 ----
        {"runTask",               nullptr, NAPI_RunTask,               nullptr, nullptr, nullptr, napi_default, nullptr},
        {"getTaskRet",            nullptr, NAPI_GetTaskRet,            nullptr, nullptr, nullptr, napi_default, nullptr},
        {"getTaskRetWithTimeout", nullptr, NAPI_GetTaskRetWithTimeout, nullptr, nullptr, nullptr, napi_default, nullptr},
        {"releaseHandle",         nullptr, NAPI_ReleaseHandle,         nullptr, nullptr, nullptr, napi_default, nullptr},
        {"runTaskAndAwait",       nullptr, NAPI_RunTaskAndAwait,       nullptr, nullptr, nullptr, napi_default, nullptr},

        // ---- Buffer 管理 ----
        {"allocBuffer",           nullptr, NAPI_AllocBuffer,           nullptr, nullptr, nullptr, napi_default, nullptr},
        {"freeBuffer",            nullptr, NAPI_FreeBuffer,            nullptr, nullptr, nullptr, napi_default, nullptr},
        {"memsetBuffer",          nullptr, NAPI_MemsetBuffer,          nullptr, nullptr, nullptr, napi_default, nullptr},

        // ---- Buffer 写入 ----
        {"writeBool",             nullptr, NAPI_WriteBool,             nullptr, nullptr, nullptr, napi_default, nullptr},
        {"writeInt8",             nullptr, NAPI_WriteInt8,             nullptr, nullptr, nullptr, napi_default, nullptr},
        {"writeUInt8",            nullptr, NAPI_WriteUInt8,            nullptr, nullptr, nullptr, napi_default, nullptr},
        {"writeInt16",            nullptr, NAPI_WriteInt16,            nullptr, nullptr, nullptr, napi_default, nullptr},
        {"writeUInt16",           nullptr, NAPI_WriteUInt16,           nullptr, nullptr, nullptr, napi_default, nullptr},
        {"writeInt32",            nullptr, NAPI_WriteInt32,            nullptr, nullptr, nullptr, napi_default, nullptr},
        {"writeUInt32",           nullptr, NAPI_WriteUInt32,           nullptr, nullptr, nullptr, napi_default, nullptr},
        {"writeInt64",            nullptr, NAPI_WriteInt64,            nullptr, nullptr, nullptr, napi_default, nullptr},
        {"writeUInt64",           nullptr, NAPI_WriteUInt64,           nullptr, nullptr, nullptr, napi_default, nullptr},
        {"writeFloat32",          nullptr, NAPI_WriteFloat32,          nullptr, nullptr, nullptr, napi_default, nullptr},
        {"writeFloat64",          nullptr, NAPI_WriteFloat64,          nullptr, nullptr, nullptr, napi_default, nullptr},
        {"writePointer",          nullptr, NAPI_WritePointer,          nullptr, nullptr, nullptr, napi_default, nullptr},
        {"writeString",           nullptr, NAPI_WriteString,           nullptr, nullptr, nullptr, napi_default, nullptr},
        {"writeBytes",            nullptr, NAPI_WriteBytes,            nullptr, nullptr, nullptr, napi_default, nullptr},

        // ---- Buffer 读取 ----
        {"readBool",              nullptr, NAPI_ReadBool,              nullptr, nullptr, nullptr, napi_default, nullptr},
        {"readInt8",              nullptr, NAPI_ReadInt8,              nullptr, nullptr, nullptr, napi_default, nullptr},
        {"readUInt8",             nullptr, NAPI_ReadUInt8,             nullptr, nullptr, nullptr, napi_default, nullptr},
        {"readInt16",             nullptr, NAPI_ReadInt16,             nullptr, nullptr, nullptr, napi_default, nullptr},
        {"readUInt16",            nullptr, NAPI_ReadUInt16,            nullptr, nullptr, nullptr, napi_default, nullptr},
        {"readInt32",             nullptr, NAPI_ReadInt32,             nullptr, nullptr, nullptr, napi_default, nullptr},
        {"readUInt32",            nullptr, NAPI_ReadUInt32,            nullptr, nullptr, nullptr, napi_default, nullptr},
        {"readInt64",             nullptr, NAPI_ReadInt64,             nullptr, nullptr, nullptr, napi_default, nullptr},
        {"readUInt64",            nullptr, NAPI_ReadUInt64,            nullptr, nullptr, nullptr, napi_default, nullptr},
        {"readFloat32",           nullptr, NAPI_ReadFloat32,           nullptr, nullptr, nullptr, napi_default, nullptr},
        {"readFloat64",           nullptr, NAPI_ReadFloat64,           nullptr, nullptr, nullptr, napi_default, nullptr},
        {"readPointer",           nullptr, NAPI_ReadPointer,           nullptr, nullptr, nullptr, napi_default, nullptr},
        {"readString",            nullptr, NAPI_ReadString,            nullptr, nullptr, nullptr, napi_default, nullptr},
        {"readBytes",             nullptr, NAPI_ReadBytes,             nullptr, nullptr, nullptr, napi_default, nullptr},
    };
    napi_define_properties(env, exports, sizeof(desc) / sizeof(desc[0]), desc);
    return exports;
}

}  // namespace requirecj_napi

// ============================================================================
// NAPI 模块入口（参考 SDL_ohos.cpp 的注册模式）
// ============================================================================

EXTERN_C_START
static napi_value RequireCJLibNapiInit(napi_env env, napi_value exports) {
    return requirecj_napi::Init(env, exports);
}
EXTERN_C_END

// NAPI 模块描述符
static napi_module g_requireCJLibModule = {
    .nm_version = 1,
    .nm_flags = 0,
    .nm_filename = nullptr,
    .nm_register_func = RequireCJLibNapiInit,
    .nm_modname = "requireCJLib",
    .nm_priv = ((void*)0),
    .reserved = {0},
};

// 模块自动注册（链接时自动执行）
extern "C" __attribute__((constructor)) void RegisterRequireCJLibModule(void) {
    napi_module_register(&g_requireCJLibModule);
}
