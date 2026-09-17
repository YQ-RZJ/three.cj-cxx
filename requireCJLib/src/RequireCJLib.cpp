// ============================================================================
// RequireCJLib.cpp — 仓颉动态库加载工具库实现
//
// 底层动态链接仓颉运行时（libcangjie-runtime）导出的 C API。
// Windows/MinGW 链接：-lcangjie-runtime（导入库 libcangjie-runtime.dll.a）
// ============================================================================
#include "requireCJLib/RequireCJLib.h"

#include <cstdio>
#include <algorithm>

#if defined(_WIN32)
#define REQUIRE_CJ_SHLIB_EXT ".dll"
#elif defined(__APPLE__)
#define REQUIRE_CJ_SHLIB_EXT ".dylib"
#else
#define REQUIRE_CJ_SHLIB_EXT ".so"
#endif

namespace requirecj {

namespace {

// 规范化库名：若未带扩展名，按平台自动补 .dll/.so/.dylib。
// 运行时 LoaderManager/GetBaseFile 按 basename 精确匹配加载时注册的库名，
// 因此加载与查找必须使用一致的完整文件名（含扩展名）。
std::string normalizeLibName(const std::string& name) {
    if (name.empty()) {
        return name;
    }
    // 已带扩展名（含 "."，如 libfoo.dll / libfoo.so）则不补
    if (name.find('.') != std::string::npos) {
        return name;
    }
    return name + REQUIRE_CJ_SHLIB_EXT;
}

}  // namespace

// ============================================================================
// Runtime
// ============================================================================

bool Runtime::init(const RuntimeConfig& cfg) {
    if (inited_) {
        return true;  // 幂等：已初始化直接成功
    }
    // 运行时参数全 0 = 全部使用仓颉运行时默认值（源码中均有默认填充逻辑）
    CJRuntimeParam param{};
    param.heapParam = cfg.heap;
    param.gcParam = cfg.gc;
    param.logParam = cfg.log;
    param.coParam = cfg.co;
    int rc = InitCJRuntime(&param);
    if (rc != CJ_E_OK) {
        std::fprintf(stderr, "[requireCJLib] InitCJRuntime failed, rc=%d\n", rc);
        return false;
    }
    inited_ = true;
    return true;
}

void Runtime::shutdown() {
    if (!inited_) {
        return;
    }
    int rc = FiniCJRuntime();
    if (rc != CJ_E_OK) {
        std::fprintf(stderr, "[requireCJLib] FiniCJRuntime failed, rc=%d\n", rc);
    }
    inited_ = false;
}

// ============================================================================
// CjLibrary
// ============================================================================

CjLibrary::CjLibrary(std::string libName)
    : libName_(normalizeLibName(std::move(libName))) {}

CjLibrary::~CjLibrary() {
    if (loaded_) {
        unload();
    }
}

bool CjLibrary::load() {
    if (loaded_) {
        return true;
    }
    int rc = LoadCJLibraryWithInit(libName_.c_str());
    if (rc != CJ_E_OK) {
        std::fprintf(stderr, "[requireCJLib] LoadCJLibraryWithInit(%s) failed, rc=%d\n",
                     libName_.c_str(), rc);
        return false;
    }
    loaded_ = true;
    return true;
}

bool CjLibrary::loadOnly() {
    if (loaded_) {
        return true;
    }
    int rc = LoadCJLibrary(libName_.c_str());
    if (rc != CJ_E_OK) {
        std::fprintf(stderr, "[requireCJLib] LoadCJLibrary(%s) failed, rc=%d\n",
                     libName_.c_str(), rc);
        return false;
    }
    loaded_ = true;
    return true;
}

void* CjLibrary::findSymbol(const char* symbolName) const {
    void* addr = FindCJSymbol(libName_.c_str(), symbolName);
    if (addr == nullptr) {
        std::fprintf(stderr, "[requireCJLib] FindCJSymbol(%s, %s) not found\n",
                     libName_.c_str(), symbolName);
    }
    return addr;
}

CJThreadHandle CjLibrary::runTask(CJTaskFunc fn, void* arg) const {
    if (fn == nullptr) {
        std::fprintf(stderr, "[requireCJLib] runTask: null function pointer\n");
        return nullptr;
    }
    return RunCJTask(fn, arg);
}

bool CjLibrary::runTaskAndWait(CJTaskFunc fn, void* arg, void** ret,
                               int64_t timeoutMs) const {
    if (fn == nullptr) {
        std::fprintf(stderr, "[requireCJLib] runTaskAndWait: null function pointer\n");
        return false;
    }
    CJThreadHandle handle = RunCJTask(fn, arg);
    if (handle == nullptr) {
        std::fprintf(stderr, "[requireCJLib] runTaskAndWait: RunCJTask failed\n");
        return false;
    }
    // GetTaskRet 会向 ret 写入结果；调用方可能传 nullptr（如仅执行不关心返回值），
    // 此时用局部变量承接，避免对空指针解引用。
    void* local = nullptr;
    void** retSlot = (ret != nullptr) ? ret : &local;
    int rc = (timeoutMs > 0)
                 ? GetTaskRetWithTimeout(handle, retSlot, timeoutMs)
                 : GetTaskRet(handle, retSlot);
    ReleaseHandle(handle);
    if (rc != CJ_E_OK) {
        std::fprintf(stderr, "[requireCJLib] runTaskAndWait: GetTaskRet failed, rc=%d\n", rc);
        return false;
    }
    return true;
}

bool CjLibrary::unload() {
    if (!loaded_) {
        return true;
    }
    int rc = UnloadCJLibrary(libName_.c_str());
    loaded_ = false;
    if (rc != CJ_E_OK) {
        std::fprintf(stderr, "[requireCJLib] UnloadCJLibrary(%s) failed, rc=%d\n",
                     libName_.c_str(), rc);
        return false;
    }
    return true;
}

}  // namespace requirecj
