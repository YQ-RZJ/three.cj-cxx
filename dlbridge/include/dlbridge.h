/*
 * dlbridge.h - 通用跨平台动态库加载桥（Generic Dynamic Library Loader Bridge）
 *
 * 用途：
 *   提供一套与具体库无关的、跨平台（OpenHarmony / Linux / Android / macOS / Windows）
 *   的运行时动态库加载接口。任何语言（仓颉 / ArkTS / C / C++ / Rust ...）均可通过
 *   FFI 使用它动态加载 .so / .dll / .dylib 并解析其中的函数符号。
 *
 * 典型场景：
 *   当一个原生库（如 libSDL3.so）需要由运行时框架（如 XComponent 的 mmg）首次加载，
 *   以便其 NAPI / 初始化逻辑在正确的时机执行时，调用方不再静态链接该库（避免被
 *   DT_NEEDED 预加载），而是改为：
 *     1) dlb_load("libSDL3.so")           -> 已加载则返回已有句柄，不重跑 constructor
 *     2) dlb_sym(handle, "SDL_Init")      -> 逐个解析符号地址
 *     3) 将地址转成对应签名的函数指针并调用
 *
 * 线程安全：
 *   本库自身无全局状态，句柄可在任意线程使用；错误信息为线程局部存储。
 *
 * 注意：
 *   dlsym(handle) 对“已经加载到进程中的库”始终有效（包括以 RTLD_LOCAL 方式加载的库），
 *   因此本桥接方案不依赖宿主框架的加载 flag。
 */
#ifndef DLBRIDGE_H
#define DLBRIDGE_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- 符号可见性 / 导出 ------------------------------------------------
 * Windows 上 DLL 必须用 __declspec(dllexport) 导出符号，否则仓颉等 FFI
 * 调用方无法解析 dlb_* 函数；其它平台用默认可见性。
 */
#if defined(_WIN32) || defined(__CYGWIN__)
#  if defined(DLBRIDGE_BUILD)
#    define DLBRIDGE_API __declspec(dllexport)
#  else
#    define DLBRIDGE_API __declspec(dllimport)
#  endif
#elif defined(__GNUC__) && __GNUC__ >= 4
#  define DLBRIDGE_API __attribute__((visibility("default")))
#else
#  define DLBRIDGE_API
#endif

/* ---- flags（dlb_load 的 mode 参数）------------------------------------
 * 传 0 表示“平台默认”（POSIX: LAZY | LOCAL；Windows: 默认加载方式）。
 * 仅在需要显式控制时才组合下列位。
 */
#define DLB_LAZY    0x01u /* 延迟解析（POSIX RTLD_LAZY）        */
#define DLB_NOW     0x02u /* 立即解析（POSIX RTLD_NOW）         */
#define DLB_GLOBAL  0x04u /* 符号进入全局命名空间（RTLD_GLOBAL）*/
#define DLB_LOCAL   0x08u /* 符号保持在本地命名空间（RTLD_LOCAL）*/

typedef void* dlb_handle_t; /* 动态库句柄（NULL 表示无效） */

/*
 * 加载动态库。
 *   path  库名或路径：可为 soname（如 "libSDL3.so"）、相对路径或绝对路径。
 *         平台会对已加载的库去重：多次 dlb_load 同一库会返回同一底层句柄（引用计数+1），
 *         不会重复执行其 constructor/初始化函数。
 *   flags 0 或上面定义的位组合（不跨平台保留 RTLD 原始值）。
 * 成功返回句柄；失败返回 NULL，可用 dlb_error() 获取错误描述。
 */
DLBRIDGE_API dlb_handle_t dlb_load(const char* path, int flags);

/*
 * 解析符号（函数或数据变量的地址）。
 *   handle dlb_load 返回的句柄。
 *   name   符号名（以 '\0' 结尾），如 "SDL_Init"。
 * 成功返回地址（可能为非 NULL）；失败返回 NULL，可用 dlb_error() 获取错误描述。
 */
DLBRIDGE_API void* dlb_sym(dlb_handle_t handle, const char* name);

/*
 * 返回最近一次 dlb_load / dlb_sym / dlb_close 失败的错误描述字符串。
 * 线程局部、静态存储，指向内部缓冲区（下次调用本库函数可能被覆盖）。
 * 无错误时返回 NULL。
 */
DLBRIDGE_API const char* dlb_error(void);

/*
 * 关闭句柄（POSIX 引用计数 -1，归零才真正卸载；Windows 为 FreeLibrary）。
 * 成功返回 0；失败返回非 0，可用 dlb_error() 获取错误描述。
 */
DLBRIDGE_API int dlb_close(dlb_handle_t handle);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* DLBRIDGE_H */
