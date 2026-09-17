/*
 * Copyright (c) 2023 Huawei Device Co., Ltd.
 * Licensed under the Apache License,Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include "../../SDL_internal.h"
#include "../../core/ohos/SDL_ohosplugin_c.h"
#include "SDL3/SDL_log.h"
#include "SDL3/SDL_timer.h"

#include <ace/xcomponent/native_interface_xcomponent.h>
#include <locale.h>
#include <unistd.h>

#define OHOS_EGL_ALPHA_SIZE_DEFAULT 8
#define OHOS_GETWINDOW_DELAY_TIME 2
#define TIMECONSTANT 3000
#define OHOS_WAIT_COUNT 700
#define OHOS_WAIT_TIME 10

#ifdef SDL_VIDEO_DRIVER_OHOS
#if SDL_VIDEO_DRIVER_OHOS
#endif

#include "napi/native_api.h"
#include "../SDL_sysvideo.h"
#include "../../events/SDL_keyboard_c.h"
#include "../../events/SDL_mouse_c.h"
#include "../../events/SDL_windowevents_c.h"
#include "../../core/ohos/SDL_ohos.h"
#include "../../core/ohos/SDL_ohosplugin_c.h"

#include "SDL_ohosvideo.h"
#include "SDL_ohoswindow.h"
#include "SDL3/SDL_hints.h"
#include <pthread.h>

/* Currently only one window */

/* 直连建窗回退路径（无 NodeController 适配层、XComponent 直连建窗时使用） */
static bool OHOS_CreateWindowFromRegisteredXComponent(SDL_VideoDevice *thisDevice, SDL_Window *window);

bool OHOS_CreateWindow(SDL_VideoDevice *thisDevice, SDL_Window *window, SDL_PropertiesID create_props)
{
    /* 无 NodeController 适配层时（base 纯仓颉工程），走 XComponent 直连建窗路径；
     * 此时绝不能调用 OHOS_GetRootNode（g_napiCallback 为空会解引用空指针）。 */
    if (!OHOS_IsNodeControllerReady()) {
        return OHOS_CreateWindowFromRegisteredXComponent(thisDevice, window);
    }
    napi_ref parentWindowNode = NULL;
    napi_ref childWindowNode = NULL;
    WindowPosition *windowPosition = NULL;
    SDL_WindowData *windowData;
    if (window->internal == NULL || ((SDL_WindowData *)window->internal)->ohosHandle == NULL) {
        OHOS_GetRootNode(g_windowId, &parentWindowNode);
        if (parentWindowNode == NULL) {
            return false;
        }
        windowPosition = (WindowPosition*)SDL_malloc(sizeof(WindowPosition));
        windowPosition->height = window->h;
        windowPosition->width = window->w;
        windowPosition->x = window->x;
        windowPosition->y = window->y;
        OHOS_AddChildNode(parentWindowNode, &childWindowNode, windowPosition);
        SDL_free(windowPosition);
        if (childWindowNode == NULL) {
            return false;
        }
    } else {
        parentWindowNode = ((SDL_WindowData *)window->internal)->ohosHandle;
    }
    OHOS_CreateWindowFrom(thisDevice, window, childWindowNode);
    return true;
}

void OHOS_SetWindowTitle(SDL_VideoDevice *thisDevice, SDL_Window *window)
{
    OHOS_NAPI_SetTitle(window->title);
}

void OHOS_SetWindowFullscreen(SDL_VideoDevice *thisDevice, SDL_Window *window, SDL_VideoDisplay *display,
                              bool fullscreen)
{
    SDL_WindowData *data;
    SDL_LockMutex(g_ohosPageMutex);

    /* If the window is being destroyed don't change visible state */
    if (!window->is_destroying) {
        OHOS_NAPI_SetWindowStyle(fullscreen);
    }

    data = (SDL_WindowData *)window->internal;

    if (!data || !data->native_window) {
        if (data && !data->native_window) {
            SDL_SetError("Missing native window");
        }
        goto endfunction;
    }

endfunction:

    SDL_UnlockMutex(g_ohosPageMutex);
}

void OHOS_MinimizeWindow(SDL_VideoDevice *thisDevice, SDL_Window *window)
{
}

void OHOS_DestroyWindow(SDL_VideoDevice *thisDevice, SDL_Window *window)
{
    SDL_Log("Destroy window is Calling.");
    SDL_LockMutex(g_ohosPageMutex);

    if (window->internal) {
        SDL_WindowData *data = (SDL_WindowData *)window->internal;
        if (data->ohosHandle) {
            OHOS_RemoveChildNode(data->ohosHandle);
        }
        if (data->egl_xcomponent != EGL_NO_SURFACE) {
            SDL_EGL_DestroySurface(thisDevice, data->egl_xcomponent);
        }
        data->egl_xcomponent = EGL_NO_SURFACE;
        if (data->xcompentId) {
            OHOS_ClearPluginData(data->xcompentId);
            SDL_free(data->xcompentId);
        }
        SDL_free(window->internal);
        window->internal = NULL;
    }

    SDL_UnlockMutex(g_ohosPageMutex);
}

void OHOS_SetWindowResizable(SDL_VideoDevice *thisDevice, SDL_Window *window, bool resizable)
{
    if (resizable) {
        OHOS_NAPI_SetWindowResize(window->windowed.x, window->windowed.y, window->windowed.w, window->windowed.h);
    }
}

void OHOS_SetWindowSize(SDL_VideoDevice *thisDevice, SDL_Window *window)
{
    SDL_WindowData *data = (SDL_WindowData *)window->internal;
    if (data && data->ohosHandle) {
        OHOS_ResizeNode(data->ohosHandle, window->w, window->h);
    }
}

void OHOS_SetWindowPosition(SDL_VideoDevice *thisDevice, SDL_Window *window)
{
    SDL_WindowData *data = (SDL_WindowData *)window->internal;
    if (data && data->ohosHandle) {
        OHOS_MoveNode(data->ohosHandle, window->x, window->y);
    }
}

void OHOS_ShowWindow(SDL_VideoDevice *thisDevice, SDL_Window *window)
{
    SDL_WindowData *data = (SDL_WindowData *)window->internal;
    if (data && data->ohosHandle) {
        OHOS_SetNodeVisibility(data->ohosHandle, 0);
    }
}

void OHOS_HideWindow(SDL_VideoDevice *thisDevice, SDL_Window *window)
{
    SDL_WindowData *data = (SDL_WindowData *)window->internal;
    if (data && data->ohosHandle) {
        OHOS_SetNodeVisibility(data->ohosHandle, 1);
    }
}

static void OHOS_WaitGetNativeXcompent(const char *strID, pthread_t tid, OH_NativeXComponent **nativeXComponent)
{
    int cnt = OHOS_WAIT_COUNT;
    while (!OHOS_FindNativeXcomPoment(strID, nativeXComponent)) {
        if (cnt-- == 0) {
            break;
        }
        SDL_Delay(OHOS_WAIT_TIME);
    }
}

static void OHOS_WaitGetNativeWindow(const char *strID, pthread_t tid, SDL_WindowData **windowData,
    OH_NativeXComponent *nativeXComponent)
{
    int cnt = OHOS_WAIT_COUNT;
    while (!OHOS_FindNativeWindow(nativeXComponent, windowData)) {
        if (cnt-- == 0) {
            break;
        }
        SDL_Delay(OHOS_WAIT_TIME);
    }
}

static void OHOS_SetRealWindowPosition(SDL_Window *window, SDL_WindowData *windowData)
{
    /* OHOS XComponent surface 尺寸为物理像素，需除以 density 得逻辑尺寸。
     * SDL 以 window->w/h 为逻辑尺寸，GetWindowSizeInPixels 返回物理像素。
     * density 从 OHOS_GetDensityPixels() 获取（NDK DisplayManager API） */
    float density = OHOS_GetDensityPixels();
    window->x = windowData->x;
    window->y = windowData->y;
    window->w = (int)(windowData->width / density);
    window->h = (int)(windowData->height / density);
}

/* 无 NodeController 适配层（ArkTS 未调用 sdl.init(callback)，如纯仓颉 base 工程）时的
 * 建窗路径：直接使用 XComponent onLoad 时已注册（libraryname='SDL3' 触发 mmg 加载并调用
 * OHOS_XcomponentExport）的 OH_NativeXComponent 及其 native window 创建 SDL 窗口。
 * 这样：
 *   - 输入事件（触摸/键鼠，经 GetWindowFromXComponent 按 xcompentId 匹配）能路由进该窗口；
 *   - native window 写入 SDL_PROP_WINDOW_OHOS_WINDOW_POINTER，供渲染后端
 *     （BgfxRenderer.initBgfx 等）绑定 OpenGLES 渲染。
 * 该路径完全绕过 NodeController 树（getNodeByWindowId/addChildNode），故 base 工程
 * 无需引入任何 C++ 工程/适配层，Three.cj 对外接口保持跨平台不变。 */
static bool OHOS_CreateWindowFromRegisteredXComponent(SDL_VideoDevice *thisDevice, SDL_Window *window)
{
    char *strID = NULL;
    OH_NativeXComponent *nativeXComponent = NULL;
    SDL_WindowData *windowData = NULL;
    SDL_WindowData *wdata = NULL;

    if (!OHOS_GetFirstNativeXComponent(&strID, &nativeXComponent)) {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION,
                     "OHOS: no registered XComponent for direct window creation (XComponent libraryname='SDL3' missing?)");
        return false;
    }
    /* 等待 OnSurfaceCreated 把 native window 写入注册表（最多 OHOS_WAIT_COUNT*OHOS_WAIT_TIME 毫秒） */
    OHOS_WaitGetNativeWindow(strID, pthread_self(), &windowData, nativeXComponent);
    if (windowData == NULL || windowData->native_window == NULL) {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "OHOS: XComponent native window not ready");
        SDL_free(strID);
        return false;
    }

    wdata = (SDL_WindowData *)SDL_calloc(1, sizeof(SDL_WindowData));
    if (wdata == NULL) {
        SDL_free(strID);
        return false;
    }
    /* xcompentId 用于输入事件路由匹配（GetWindowFromXComponent 按 id 找 SDL_Window） */
    wdata->xcompentId = strID;
    wdata->native_window = windowData->native_window;
    wdata->width = windowData->width;
    wdata->height = windowData->height;
    wdata->x = windowData->x;
    wdata->y = windowData->y;
    window->internal = wdata;

    SDL_LockMutex(g_ohosPageMutex);
    OHOS_SetRealWindowPosition(window, windowData);
    SDL_SetPointerProperty(SDL_GetWindowProperties(window), SDL_PROP_WINDOW_OHOS_WINDOW_POINTER,
                           wdata->native_window);
    if ((window->flags & SDL_WINDOW_OPENGL) != 0) {
        if (thisDevice->gl_config.alpha_size == 0) {
            thisDevice->gl_config.alpha_size = OHOS_EGL_ALPHA_SIZE_DEFAULT;
        }
        wdata->egl_xcomponent =
            SDL_EGL_CreateSurface(thisDevice, window, (NativeWindowType)windowData->native_window);
        windowData->egl_xcomponent = wdata->egl_xcomponent;
        if (wdata->egl_xcomponent == EGL_NO_SURFACE) {
            SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "Failed to create eglsurface");
            SDL_UnlockMutex(g_ohosPageMutex);
            return false;
        }
    }
    SDL_UnlockMutex(g_ohosPageMutex);
    return true;
}

bool OHOS_CreateWindowFrom(SDL_VideoDevice *thisDevice, SDL_Window *window, const void *data)
{
    char *strID = NULL;
    pthread_t tid;
    OH_NativeXComponent *nativeXComponent = NULL;
    SDL_WindowData *windowData = NULL;
    SDL_WindowData *sdlWindowData = NULL;
    SDL_WindowData *wdata = (SDL_WindowData *)window->internal;
    if (data == NULL && (wdata == NULL || wdata->ohosHandle == NULL))
        return false;
    if (data != NULL && (wdata == NULL || wdata->ohosHandle == NULL)) {
        if (wdata == NULL) {
            wdata = (SDL_WindowData *)SDL_calloc(1, sizeof(SDL_WindowData));
            window->internal = wdata;
        }
        wdata->ohosHandle = (void *)data;
    }
    strID = OHOS_GetXComponentId(wdata->ohosHandle);
    wdata->xcompentId = strID;

    tid = pthread_self();
    OHOS_AddXcomPomentIdForThread(strID, tid);
    OHOS_WaitGetNativeXcompent(strID, tid, &nativeXComponent);
    OHOS_WaitGetNativeWindow(strID, tid, &windowData, nativeXComponent);

    if (windowData == NULL)
        return false;

    sdlWindowData = wdata;
    SDL_LockMutex(g_ohosPageMutex);
    OHOS_SetRealWindowPosition(window, windowData);
    sdlWindowData->native_window = windowData->native_window;
    if (!sdlWindowData->native_window) {
        goto endfunction;
    }
    /* 将 OHNativeWindow * 写入窗口属性，供外部绑定 OpenGL / bgfx 等渲染后端使用（nwh） */
    SDL_SetPointerProperty(SDL_GetWindowProperties(window), SDL_PROP_WINDOW_OHOS_WINDOW_POINTER, sdlWindowData->native_window);

    if ((window->flags & SDL_WINDOW_OPENGL) != 0) {
        if (thisDevice->gl_config.alpha_size == 0) {
            thisDevice->gl_config.alpha_size = OHOS_EGL_ALPHA_SIZE_DEFAULT;
        }
        sdlWindowData->egl_xcomponent =
            SDL_EGL_CreateSurface(thisDevice, window, (NativeWindowType)windowData->native_window);
        windowData->egl_xcomponent = sdlWindowData->egl_xcomponent;
        if (sdlWindowData->egl_xcomponent == EGL_NO_SURFACE) {
            SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "Failed to create eglsurface");
            goto endfunction;
        }
    }
    window->internal = sdlWindowData;
endfunction:
     SDL_UnlockMutex(g_ohosPageMutex);
     return window->internal ? true : false;
}

char *OHOS_GetWindowTitle(SDL_VideoDevice *thisDevice, SDL_Window *window)
{
    char *title = NULL;
    title = window->title;
    SDL_Log("sdlthread OHOS_GetWindowTitle");
    if (title) {
        return title;
    } else {
        return "Title is NULL";
    }
}
#endif /* SDL_VIDEO_DRIVER_OHOS */

/* vi: set ts=4 sw=4 expandtab: */
