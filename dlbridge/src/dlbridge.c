/*
 * dlbridge.c - 通用跨平台动态库加载桥实现
 *
 * 后端选择：
 *   POSIX  (OpenHarmony / Linux / Android / macOS)：dlopen / dlsym / dlerror / dlclose
 *   Windows                                    ：LoadLibraryA / GetProcAddress / GetLastError / FreeLibrary
 *
 * 设计约束：
 *   - 纯 C99，无任何第三方头文件依赖，方便任意工具链编译与任意语言 FFI。
 *   - 不依赖具体库（不含 SDL / 任何业务库头文件），天然通用。
 *   - 线程局部错误缓冲，避免跨线程串扰。
 */
#include "dlbridge.h"

#if defined(_WIN32)
#    define WIN32_LEAN_AND_MEAN
#    include <windows.h>
#else
#    include <dlfcn.h>
#endif

#include <stdio.h>
#include <string.h>

/* ------------------------------------------------------------------ */
/* 线程局部错误缓冲                                                     */
/* ------------------------------------------------------------------ */
#if defined(_MSC_VER)
#    define DLB_TLS __declspec(thread)
#elif defined(__GNUC__) || defined(__clang__)
#    define DLB_TLS __thread
#else
#    define DLB_TLS _Thread_local
#endif

static DLB_TLS char g_dlb_err[512];

static void set_error(const char* msg)
{
    if (msg) {
        (void)snprintf(g_dlb_err, sizeof(g_dlb_err), "%s", msg);
    } else {
        g_dlb_err[0] = '\0';
    }
}

const char* dlb_error(void)
{
    return g_dlb_err[0] != '\0' ? g_dlb_err : NULL;
}

/* ------------------------------------------------------------------ */
/* flags 映射                                                           */
/* ------------------------------------------------------------------ */
#if !defined(_WIN32)
static int map_flags(int flags)
{
    int f = RTLD_LAZY | RTLD_LOCAL;
    if (flags & DLB_NOW) {
        f = (f & ~RTLD_LAZY) | RTLD_NOW;
    }
    if (flags & DLB_GLOBAL) {
        f = (f & ~RTLD_LOCAL) | RTLD_GLOBAL;
    }
    if (flags & DLB_LOCAL) {
        f = (f & ~RTLD_GLOBAL) | RTLD_LOCAL;
    }
    return f;
}
#endif

#if defined(_WIN32)
static void set_win_error(void)
{
    DWORD code = GetLastError();
    LPSTR buf = NULL;
    DWORD len = FormatMessageA(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        NULL, code, MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
        (LPSTR)&buf, 0, NULL);
    if (len > 0 && buf != NULL) {
        /* 去掉末尾的 \r\n */
        while (len > 0 && (buf[len - 1] == '\r' || buf[len - 1] == '\n')) {
            buf[--len] = '\0';
        }
        (void)snprintf(g_dlb_err, sizeof(g_dlb_err), "win32 error %lu: %s",
                       (unsigned long)code, buf);
        LocalFree(buf);
    } else {
        (void)snprintf(g_dlb_err, sizeof(g_dlb_err), "win32 error %lu", (unsigned long)code);
    }
}
#endif

/* ------------------------------------------------------------------ */
/* 公共 API                                                             */
/* ------------------------------------------------------------------ */
dlb_handle_t dlb_load(const char* path, int flags)
{
    if (!path || !*path) {
        set_error("dlb_load: empty path");
        return NULL;
    }
#if defined(_WIN32)
    {
        (void)flags; /* Windows 的 LoadLibraryA 不区分 LAZY/NOW/GLOBAL/LOCAL */
        UINT prev = SetErrorMode(SEM_FAILCRITICALERRORS);
        HMODULE m = LoadLibraryA(path);
        SetErrorMode(prev);
        if (!m) {
            set_win_error();
            return NULL;
        }
        return (dlb_handle_t)m;
    }
#else
    {
        void* h = dlopen(path, map_flags(flags));
        if (!h) {
            set_error(dlerror());
            return NULL;
        }
        return (dlb_handle_t)h;
    }
#endif
}

void* dlb_sym(dlb_handle_t handle, const char* name)
{
    if (!handle) {
        set_error("dlb_sym: null handle");
        return NULL;
    }
    if (!name || !*name) {
        set_error("dlb_sym: empty symbol name");
        return NULL;
    }
#if defined(_WIN32)
    {
        FARPROC p = GetProcAddress((HMODULE)handle, name);
        if (!p) {
            set_win_error();
            return NULL;
        }
        return (void*)p;
    }
#else
    {
        /* dlerror() 必须在 dlsym 前清空，以区分“符号不存在”与“成功”。 */
        (void)dlerror();
        void* p = dlsym(handle, name);
        const char* e = dlerror();
        if (e) {
            set_error(e);
            return NULL;
        }
        return p;
    }
#endif
}

int dlb_close(dlb_handle_t handle)
{
    if (!handle) {
        set_error("dlb_close: null handle");
        return -1;
    }
#if defined(_WIN32)
    if (!FreeLibrary((HMODULE)handle)) {
        set_win_error();
        return -1;
    }
    return 0;
#else
    if (dlclose(handle) != 0) {
        set_error(dlerror());
        return -1;
    }
    return 0;
#endif
}
