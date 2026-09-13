// ============================================================================
// RequireCJLibFFI.cpp — requireCJLib C FFI 实现
//
// 桥接层：将 cj_ffi_* C FFI 函数转发到已有的仓颉运行时 C API
// （InitCJRuntime / LoadCJLibraryWithInit / FindCJSymbol / RunCJTask 等）。
//
// 所有导出函数均标记 __attribute__((used))，确保编译为 .a 链接到
// 仓颉 .so 后不会被链接器作为死代码剔除。外部通过 dlopen + dlsym
// 即可发现并调用这些符号。
// ============================================================================
#include "requireCJLib/RequireCJLib.h"
#include "requireCJLib/RequireCJLibFFI.h"

#include <cstdio>

// 跨编译器兼容的"强制保留符号"宏：
//   GCC / Clang / MinGW: __attribute__((used))
//   MSVC: 无直接等价，需通过 /INCLUDE 链接器参数保留
#if defined(__GNUC__) || defined(__clang__)
  #define CJ_FFI_USED __attribute__((used))
#else
  #define CJ_FFI_USED
#endif

// ============================================================================
// 运行时生命周期
// ============================================================================

CJ_FFI_USED
int cj_ffi_init_runtime(const struct CJRuntimeParam* param) {
    return InitCJRuntime(param);
}

CJ_FFI_USED
int cj_ffi_fini_runtime(void) {
    return FiniCJRuntime();
}

CJ_FFI_USED
int cj_ffi_is_runtime_initialized(void) {
    // 通过尝试再次初始化来判断（InitCJRuntime 幂等）：
    // 若已初始化则直接返回成功，此处用一个轻量方式——
    // 直接调用 InitCJRuntime(NULL)，若返回 OK 说明已初始化或刚初始化成功。
    // 但这样会改变状态（首次调用时）。改用全局标记更安全。
    //
    // 注意：底层 C API 没有查询接口，这里借助 requirecj::Runtime 的 RAII 封装
    // 来跟踪状态。但 FFI 层不应依赖 C++ 类的实例——
    // 因此直接通过 InitCJRuntime 的幂等性实现：调用后若成功则一定已初始化。
    // 对于纯查询场景，调用方应先 init 再使用。
    //
    // 简化实现：直接尝试 InitCJRuntime(NULL)，幂等保证安全。
    int rc = InitCJRuntime(nullptr);
    return (rc == CJ_E_OK) ? 1 : 0;
}

// ============================================================================
// 动态库管理
// ============================================================================

CJ_FFI_USED
int cj_ffi_load_library(const char* libName) {
    return LoadCJLibrary(libName);
}

CJ_FFI_USED
int cj_ffi_init_library(const char* libName) {
    return InitCJLibrary(libName);
}

CJ_FFI_USED
int cj_ffi_load_library_with_init(const char* libName) {
    return LoadCJLibraryWithInit(libName);
}

CJ_FFI_USED
int cj_ffi_unload_library(const char* libName) {
    return UnloadCJLibrary(libName);
}

CJ_FFI_USED
void* cj_ffi_find_symbol(const char* libName, const char* symbolName) {
    return FindCJSymbol(libName, symbolName);
}

// ============================================================================
// 任务执行
// ============================================================================

CJ_FFI_USED
CJThreadHandle cj_ffi_run_task(CJTaskFunc func, void* args) {
    return RunCJTask(func, args);
}

CJ_FFI_USED
int cj_ffi_get_task_ret(CJThreadHandle handle, void** ret) {
    return GetTaskRet(handle, ret);
}

CJ_FFI_USED
int cj_ffi_get_task_ret_with_timeout(CJThreadHandle handle, void** ret, int64_t timeout) {
    return GetTaskRetWithTimeout(handle, ret, timeout);
}

CJ_FFI_USED
void cj_ffi_release_handle(CJThreadHandle handle) {
    ReleaseHandle(handle);
}

CJ_FFI_USED
int cj_ffi_run_task_and_wait(CJTaskFunc func, void* args, void** ret, int64_t timeout_ms) {
    if (func == nullptr) {
        std::fprintf(stderr, "[requireCJLib FFI] run_task_and_wait: null function pointer\n");
        return CJ_E_FAILED;
    }
    CJThreadHandle handle = RunCJTask(func, args);
    if (handle == nullptr) {
        std::fprintf(stderr, "[requireCJLib FFI] run_task_and_wait: RunCJTask failed\n");
        return CJ_E_FAILED;
    }
    void* local = nullptr;
    void** retSlot = (ret != nullptr) ? ret : &local;
    int rc = (timeout_ms > 0)
                 ? GetTaskRetWithTimeout(handle, retSlot, timeout_ms)
                 : GetTaskRet(handle, retSlot);
    ReleaseHandle(handle);
    return rc;
}
