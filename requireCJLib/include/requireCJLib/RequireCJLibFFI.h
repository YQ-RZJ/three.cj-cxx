// ============================================================================
// RequireCJLibFFI.h — requireCJLib 的 C FFI 接口
//
// 用途：为 requireCJLib 工具库提供纯 C 语言调用接口，使编译后的 .a 静态库
//       链接到仓颉 .so 产物后，外部可通过 dlopen + C 符号直接调用。
//
// 典型使用流程（外部 C / Python ctypes / 其它语言）：
//   1. dlopen("libcjproduct.so")        // 加载仓颉 .so（内含 requireCJLib .a）
//   2. cj_ffi_init_runtime(NULL)         // 初始化仓颉运行时
//   3. cj_ffi_load_library("libmylib")   // 加载仓颉动态库
//   4. cj_ffi_find_symbol + cj_ffi_run_task_and_wait  // 调用仓颉函数
//   5. cj_ffi_unload_library / cj_ffi_fini_runtime   // 清理
//
// 编译为 .a 后链接到仓颉项目时，所有函数均带 __attribute__((used))，
// 确保即使无内部引用也不会被链接器作为死代码剔除（参见"仓颉SO-C化.md"方案一）。
//
// 本头文件自包含，不依赖 RequireCJLib.h 或任何 C++ 头文件，
// 可直接被 C / C++ / ctypes / cgo 等消费。
// ============================================================================
#pragma once

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// ============================================================================
// 类型定义（与 RequireCJLib.h / Cangjie.h 保持 ABI 一致，勿改动字段顺序/类型）
//
// 当 REQUIRECJLIB_CJ_TYPES_DEFINED 已定义（即 RequireCJLib.h 已被 include）时
// 跳过重复定义，避免同一翻译单元中的重定义错误。
// ============================================================================
#ifndef REQUIRECJLIB_CJ_TYPES_DEFINED

// 运行时日志级别
enum CJRTLogLevel {
    CJRTLOG_VERBOSE = 0,
    CJRTLOG_DEBUG,
    CJRTLOG_INFO,
    CJRTLOG_REPORT,
    CJRTLOG_WARNING,
    CJRTLOG_ERROR,
    CJRTLOG_FAIL,
    CJRTLOG_FATAL,
    CJRTLOG_OFF
};

// 堆配置（对应 Cangjie.h HeapParam）
struct CJHeapParam {
    size_t regionSize;
    size_t heapSize;
    double exemptionThreshold;
    double heapUtilization;
    double heapGrowth;
    double allocationRate;
    size_t allocationWaitTime;
};

// GC 配置（对应 Cangjie.h GCParam）
struct CJGCParam {
    size_t gcThreshold;
    double garbageThreshold;
    uint64_t gcInterval;
    uint64_t backupGCInterval;
    int32_t gcThreads;
};

// 日志配置
struct CJLogParam {
    enum CJRTLogLevel logLevel;
};

// 并发配置（对应 Cangjie.h ConcurrencyParam）
struct CJConcurrencyParam {
    size_t thStackSize;
    size_t coStackSize;
    uint32_t processorNum;
};

// 运行时参数（对应 Cangjie.h RuntimeParam）
struct CJRuntimeParam {
    struct CJHeapParam heapParam;
    struct CJGCParam gcParam;
    struct CJLogParam logParam;
    struct CJConcurrencyParam coParam;
};

// 仓颉函数指针类型（void* (*)(void*)，与 Cangjie.h CJTaskFunc 一致）
typedef void* (*CJTaskFunc)(void*);

// 仓颉任务句柄（不透明指针）
typedef void* CJThreadHandle;

// 错误码（与 Cangjie.h RTErrorCode 一致）
enum CJRTErrorCode {
    CJ_E_OK     =  0,
    CJ_E_ARGS   = -1,
    CJ_E_TIMEOUT = -2,
    CJ_E_STATE  = -3,
    CJ_E_FAILED = -4
};

#endif  // REQUIRECJLIB_CJ_TYPES_DEFINED

// ============================================================================
// FFI 函数声明
//
// 所有函数均以 "cj_ffi_" 为前缀，命名风格为 snake_case，
// 便于 ctypes / cgo / dlsym 等场景使用。
// ============================================================================

// ---- 运行时生命周期 ----

// 初始化仓颉运行时。param=NULL 时使用全部默认值。可重复调用（幂等）。
// 返回：CJ_E_OK 成功，其它值失败。
int cj_ffi_init_runtime(const struct CJRuntimeParam* param);

// 结束仓颉运行时。可重复调用（幂等）。
int cj_ffi_fini_runtime(void);

// 查询运行时是否已初始化。返回 1=已初始化，0=未初始化。
int cj_ffi_is_runtime_initialized(void);

// ---- 动态库管理 ----

// 加载仓颉动态库（LoadCJLibrary，仅加载不初始化）。libName 建议传短名如 "libmylib"。
int cj_ffi_load_library(const char* libName);

// 初始化已加载的仓颉动态库（InitCJLibrary，需运行时已初始化）。
int cj_ffi_init_library(const char* libName);

// 加载 + 初始化仓颉动态库（LoadCJLibraryWithInit，需运行时已初始化）。
int cj_ffi_load_library_with_init(const char* libName);

// 卸载仓颉动态库。
int cj_ffi_unload_library(const char* libName);

// 查找仓颉动态库中的导出符号，返回函数地址或 NULL。
void* cj_ffi_find_symbol(const char* libName, const char* symbolName);

// ---- 任务执行 ----

// 在 cjthread 环境执行仓颉函数，返回任务句柄（失败返回 NULL）。
CJThreadHandle cj_ffi_run_task(CJTaskFunc func, void* args);

// 阻塞获取仓颉任务结果。ret 接收函数返回值（可为 NULL 表示不关心返回值）。
int cj_ffi_get_task_ret(CJThreadHandle handle, void** ret);

// 带超时获取任务结果（毫秒；timeout<=0 等价于 cj_ffi_get_task_ret）。
int cj_ffi_get_task_ret_with_timeout(CJThreadHandle handle, void** ret, int64_t timeout);

// 释放任务句柄。
void cj_ffi_release_handle(CJThreadHandle handle);

// 同步执行仓颉函数并获取结果（run_task + get_task_ret + release_handle 一步到位）。
// func: cj_ffi_find_symbol 返回的函数指针；args: 透传参数；ret: 接收返回值（可为 NULL）。
// timeout_ms: 超时毫秒数，<=0 表示无限等待。
int cj_ffi_run_task_and_wait(CJTaskFunc func, void* args, void** ret, int64_t timeout_ms);

#ifdef __cplusplus
}  // extern "C"
#endif
