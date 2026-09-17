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

#ifndef SDL_OHOSHEAD_H
#define SDL_OHOSHEAD_H

#include "SDL_internal.h"
#include "SDL_ohos.h"
#include "SDL_ohos_xcomponent.h"
#include "../../video/SDL_egl_c.h"

/* SDL3: each video backend defines its own SDL_WindowData; it is exposed
 * to the core through SDL_Window->internal.  The OHOS backend keeps the
 * XComponent id here (SDL2's OHOS port stored it directly in SDL_Window).
 * SDL3 forward-declares `typedef struct SDL_WindowData SDL_WindowData;` in
 * SDL_sysvideo.h, so here we only define the struct (no typedef). */
struct SDL_WindowData {
    EGLSurface egl_xcomponent;
    EGLContext egl_context; /* We use this to preserve the context when losing focus */
    bool   backup_done;
    OHNativeWindow *native_window;
    void *ohosHandle;      /* ViewNodeController (napi_ref), moved here from SDL_Window in SDL3 */
    char *xcompentId;      /* XComponent id used to match native components */
    uint64_t width;
    uint64_t height;
    double x;
    double y;
};

#endif
