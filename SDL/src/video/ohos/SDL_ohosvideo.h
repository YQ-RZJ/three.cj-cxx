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

#ifndef SDL_OHOSVIDEO_H
#define SDL_OHOSVIDEO_H

#include <EGL/eglplatform.h>
#include "../../core/ohos/SDL_ohos.h"
#include "SDL3/SDL_Mutex.h"
#include "SDL3/SDL_rect.h"
#include "../SDL_sysvideo.h"
#include "../SDL_egl_c.h"
#include "../../core/ohos/SDL_ohos_xcomponent.h"
#include "SDL_ohoswindow.h"

#ifdef __cplusplus
/* *INDENT-OFF* */
extern "C" {
/* *INDENT-ON* */
#endif

/* Called by the JNI layer when the screen changes size or format */
extern void OHOS_SetScreenResolution(int deviceWidth, int deviceHeight, Uint32 format,
                                     float rate, double screenDensity);
extern void OHOS_SendResize(SDL_Window *window);
extern void OHOS_SetScreenSize(int surfaceWidth, int surfaceHeight);

/* Private display data */

typedef struct SDL_VideoData {
    SDL_Rect textRect;
    int      isPaused;
    int      isPausing;
} SDL_VideoData;


extern int g_ohosSurfaceWidth;
extern int g_ohosSurfaceHeight;
extern int g_ohosDeviceWidth;
extern int g_ohosDeviceHeight;
extern SDL_Semaphore *g_ohosPauseSem, *g_ohosResumeSem;
extern SDL_Mutex *g_ohosPageMutex;
extern double g_ohosScreenDensity;

/* 获取屏幕逻辑像素密度（缩放系数，如 2.0/3.0）。
 * 优先用 OHOS NDK DisplayManager API，回退到 g_ohosScreenDensity，兜底 1.0。 */
extern float OHOS_GetDensityPixels(void);

/* 将 XComponent 回调获得的新物理像素尺寸同步到 window->internal，
 * 使 OHOS_SendResize / OHOS_GetWindowSizeInPixels 能读到最新值。
 * 同时更新 native_window——surface 重建后须替换为新指针，
 * OnSurfaceDestroyedCB 会置 NULL 防止野指针。 */
extern void OHOS_SyncWindowSize(SDL_Window *window, uint64_t width, uint64_t height,
                                double offsetX, double offsetY, void *native_window);

/* Ends C function definitions when using C++ */
#ifdef __cplusplus
/* *INDENT-OFF* */
}
/* *INDENT-ON* */
#endif

#endif /* SDL_OHOSVIDEO_H */

/* vi: set ts=4 sw=4 expandtab: */
