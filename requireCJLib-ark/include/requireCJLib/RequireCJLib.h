// ============================================================================
// RequireCJLib.h — 仓颉动态库加载工具库（C++ 封装）
//
// 用途：让其它 C++ 项目快速获得"加载仓颉动态库并执行仓颉函数"的能力。
// 底层对接仓颉运行时（libcangjie-runtime）导出的 C API：
//   InitCJRuntime / LoadCJLibraryWithInit / FindCJSymbol / RunCJTask /
//   UnloadCJLibrary / FiniCJRuntime
//
// 使用示例：
//   requirecj::RequireCJLib cj;
//   cj.initRuntime();                        // 1. 初始化仓颉运行时
//   cj.loadLibrary("libmylib");              // 2. 加载 + 初始化仓颉动态库
//   auto fn = cj.findSymbol("myFunc");       // 3. 查找仓颉导出函数
//   cj.runTask(fn, nullptr);                 // 4. 在 cjthread 环境执行
//   cj.shutdownRuntime();                    // 5. 结束运行时
//
// 链接要求（Windows/MinGW）：
//   -L <SDK>/build-tools/runtime/lib/windows_x86_64_cjnative -lcangjie-runtime
//   运行时需 libcangjie-runtime.dll 及其 std 系列 dll 在 PATH。
// ============================================================================
#pragma once

#include <cstdint>
#include <cstddef>
#include <string>
#include <functional>

// ----------------------------------------------------------------------------
// 仓颉运行时 C API 声明（与 <Cangjie.h> 保持 ABI 一致；SDK 未随附该头文件，
// 此处按官方定义自包含，勿改动字段顺序/类型）
// ----------------------------------------------------------------------------
#ifdef __cplusplus
extern "C" {
#endif

// 仓颉运行时日志级别（对应 Cangjie.h 的 enum RTLogLevel）
enum CJRTLogLevel {
    CJRTLOG_VERBOSE = 0,
    CJRTLOG_DEBUG,
    CJRTLOG_INFO,
    CJRTLOG_REPORT,  // same as INFO
    CJRTLOG_WARNING,
    CJRTLOG_ERROR,
    CJRTLOG_FAIL,
    CJRTLOG_FATAL,
    CJRTLOG_OFF
};

// 堆配置（对应 Cangjie.h 的 struct HeapParam）
struct CJHeapParam {
    size_t regionSize;          // 区域大小(KB)，默认 64，范围 [4, 64]，0=默认
    size_t heapSize;            // 堆最大值(KB)，默认 256*1024，0=默认
    double exemptionThreshold;  // 区域免晋升阈值，默认 0.8，0=默认
    double heapUtilization;     // 堆利用率，默认 0.8，0=默认
    double heapGrowth;          // 每次 GC 后堆扩容比例，默认 0.15，0=默认
    double allocationRate;      // 分配速率(MB/s)，默认 10240，0=默认
    size_t allocationWaitTime;  // 分配最大等待(ns)，默认 1000，0=默认
};

// GC 配置（对应 Cangjie.h 的 struct GCParam）
struct CJGCParam {
    size_t gcThreshold;         // GC 触发堆分配阈值(KB)，0=默认
    double garbageThreshold;    // from-space 垃圾比例阈值，默认 0.5，0=默认
    uint64_t gcInterval;        // GC 最小间隔(ns)，默认 150ms，0=默认
    uint64_t backupGCInterval;  // 备份 GC 最小间隔(ns)，默认 240s，0=默认
    int32_t gcThreads;          // GC 线程数参数，默认 8，0=默认
};

// 日志配置（对应 Cangjie.h 的 struct LogParam）
struct CJLogParam {
    enum CJRTLogLevel logLevel;  // 低于该级别的日志被忽略，默认 ERROR
};

// 并发配置（对应 Cangjie.h 的 struct ConcurrencyParam）
struct CJConcurrencyParam {
    size_t thStackSize;     // 线程栈大小(KB)，默认 1MB，0=默认
    size_t coStackSize;     // CJThread 栈大小(KB)，默认 64KB，0=默认
    uint32_t processorNum;  // 处理器数，0=默认
};

// 运行时参数（对应 Cangjie.h 的 struct RuntimeParam）
struct CJRuntimeParam {
    struct CJHeapParam heapParam;
    struct CJGCParam gcParam;
    struct CJLogParam logParam;
    struct CJConcurrencyParam coParam;
};

// 仓颉函数指针类型（对应 Cangjie.h 的 CJTaskFunc）
typedef void* (*CJTaskFunc)(void*);

// 仓颉任务句柄（对应 Cangjie.h 的 CJThreadHandle）
typedef void* CJThreadHandle;

// 错误码（对应 Cangjie.h 的 enum RTErrorCode）
enum CJRTErrorCode {
    CJ_E_OK = 0,
    CJ_E_ARGS = -1,
    CJ_E_TIMEOUT = -2,
    CJ_E_STATE = -3,
    CJ_E_FAILED = -4
};

// ---- 运行时生命周期（符号名与 libcangjie-runtime.dll 导出一致） ----
int InitCJRuntime(const struct CJRuntimeParam* param);
int FiniCJRuntime(void);

// ---- 动态库管理 ----
int LoadCJLibrary(const char* libName);              // 仅加载（不需运行时）
int InitCJLibrary(const char* libName);              // 仅初始化（需运行时）
int LoadCJLibraryWithInit(const char* libName);      // 加载 + 初始化（需运行时）
int UnloadCJLibrary(const char* libName);
void* FindCJSymbol(const char* libName, const char* symbolName);

// ---- 任务执行 ----
CJThreadHandle RunCJTask(const CJTaskFunc func, void* args);

// 阻塞获取仓颉任务结果（Cangjie.h 的 GetTaskRet），ret 为函数返回值
int GetTaskRet(const CJThreadHandle handle, void** ret);

// 带超时获取任务结果（毫秒；timeout<=0 等价于 GetTaskRet）
int GetTaskRetWithTimeout(const CJThreadHandle handle, void** ret, int64_t timeout);

// 释放任务句柄（Cangjie.h 的 ReleaseHandle）
void ReleaseHandle(const CJThreadHandle handle);

#ifdef __cplusplus
}  // extern "C"
#endif

// ----------------------------------------------------------------------------
// C++ 封装
// ----------------------------------------------------------------------------
namespace requirecj {

// 运行时配置（全 0 = 全部走仓颉运行时默认值）
struct RuntimeConfig {
    CJHeapParam heap{};       // 堆配置（0 = 默认）
    CJGCParam gc{};           // GC 配置（0 = 默认）
    CJLogParam log{};         // 日志配置（默认 ERROR）
    CJConcurrencyParam co{};  // 并发配置（0 = 默认）
    RuntimeConfig() {
        heap = CJHeapParam{};
        gc = CJGCParam{};
        log = CJLogParam{CJRTLOG_ERROR};
        co = CJConcurrencyParam{};
    }
};

// 加载仓颉动态库的 RAII 句柄
class CjLibrary {
public:
    // libName：仓颉动态库名（如 "libmylib" 或带路径/扩展名均可，
    // 运行时按 basename 匹配，建议传 "libmylib"）
    explicit CjLibrary(std::string libName);
    ~CjLibrary();

    CjLibrary(const CjLibrary&) = delete;
    CjLibrary& operator=(const CjLibrary&) = delete;

    // 加载 + 初始化（LoadCJLibraryWithInit）。返回是否成功。
    bool load();

    // 仅加载不初始化（LoadCJLibrary）。返回是否成功。
    bool loadOnly();

    // 查找符号（FindCJSymbol），返回函数地址或 nullptr。
    void* findSymbol(const char* symbolName) const;

    // 在 cjthread 环境执行仓颉函数（RunCJTask）。
    // fn 由 findSymbol 得到；arg 透传给仓颉函数。
    // 返回任务句柄（可后续等待），失败返回 nullptr。
    CJThreadHandle runTask(CJTaskFunc fn, void* arg = nullptr) const;

    // 同步执行并获取结果：RunCJTask + GetTaskRet + ReleaseHandle 一步到位。
    // fn 由 findSymbol 得到；arg 透传；ret 接收仓颉函数返回值。
    // 返回是否成功（任务执行且取回结果）。
    bool runTaskAndWait(CJTaskFunc fn, void* arg, void** ret, int64_t timeoutMs = 0) const;

    // 卸载库（UnloadCJLibrary）。
    bool unload();

    const std::string& name() const { return libName_; }
    bool loaded() const { return loaded_; }

private:
    std::string libName_;
    bool loaded_ = false;
};

// 仓颉运行时生命周期管理
class Runtime {
public:
    Runtime() = default;
    ~Runtime() { shutdown(); }

    Runtime(const Runtime&) = delete;
    Runtime& operator=(const Runtime&) = delete;

    // 初始化仓颉运行时（InitCJRuntime）。可重复调用（幂等）。
    bool init(const RuntimeConfig& cfg = RuntimeConfig());

    // 结束仓颉运行时（FiniCJRuntime）。
    void shutdown();

    bool initialized() const { return inited_; }

private:
    bool inited_ = false;
};

}  // namespace requirecj
