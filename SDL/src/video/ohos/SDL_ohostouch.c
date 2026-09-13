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

#ifdef SDL_VIDEO_DRIVER_OHOS
#if SDL_VIDEO_DRIVER_OHOS
#endif

#include "SDL3/SDL_hints.h"
#include "SDL3/SDL_events.h"
#include "SDL3/SDL_log.h"
#include "SDL_ohostouch.h"
#include "../../events/SDL_mouse_c.h"
#include "../../events/SDL_touch_c.h"
#include "../../core/ohos/SDL_ohos.h"
#include "SDL_ohosvideo.h"

#define ACTION_DOWN 0
#define ACTION_UP 1
#define ACTION_MOVE 2
#define ACTION_CANCEL 3

#define FLOOR_HIGHT 10000

void OHOS_InitTouch(void)
{
}

void OHOS_QuitTouch(void)
{
}

/* Convert OHOS XComponent pixel coordinates into SDL normalized [0,1] touch coordinates.
   SDL_SendTouch / SDL_SendTouchMotion expect normalized coordinates on EVERY action
   (down/move/up/cancel). The previous code normalized only on DOWN and fed raw pixel
   coordinates on MOVE/UP, which broke the synthetic mouse events (SDL computes
   pos_x = x * window->w internally, so raw pixels overflowed and got clamped to the
   window corner -> mouse deltas were garbage/zero). Normalize all actions so the
   public mouse API outputs the same values as on other platforms (e.g. Android). */
static void NormalizeTouchPoint(SDL_Window *window, float *x, float *y)
{
    if (window->w != 0 && window->h != 0) {
        *x = floor(*x * FLOOR_HIGHT) / ((float)window->w * FLOOR_HIGHT);
        *y = floor(*y * FLOOR_HIGHT) / ((float)window->h * FLOOR_HIGHT);
    } else {
        *x = 0.0f;
        *y = 0.0f;
    }
}

void OHOS_OnTouch(SDL_Window *window, OhosTouchId *touchsize)
{
    SDL_TouchID touchDeviceId = 0;
    SDL_FingerID fingerId = 0;
    float tempX = 0.0;
    float tempY = 0.0;

    if (!window) {
        return;
    }

    touchDeviceId = (SDL_TouchID)touchsize->touchDeviceIdIn;
    if (SDL_AddTouch(touchDeviceId, SDL_TOUCH_DEVICE_DIRECT, "") < 0) {
        SDL_Log("error: can't add touch %s, %d", __FILE__, __LINE__);
    }

    fingerId = (SDL_FingerID)touchsize->pointerFingerIdIn;

    /* OHOS XComponent 触摸坐标为物理像素，需除以 density 转为逻辑像素，
       使 NormalizeTouchPoint 的 x/window->w 计算正确（window->w 为逻辑尺寸）。 */
    float density = OHOS_GetDensityPixels();
    tempX = touchsize->x / density;
    tempY = touchsize->y / density;

    switch (touchsize->action) {
        case ACTION_DOWN:
//      case ACTION_POINTER_DOWN:
            NormalizeTouchPoint(window, &tempX, &tempY);
            SDL_SendTouch(0, touchDeviceId, fingerId, window, SDL_EVENT_FINGER_DOWN, tempX, tempY, touchsize->p);
            break;

        case ACTION_MOVE:
            NormalizeTouchPoint(window, &tempX, &tempY);
            SDL_SendTouchMotion(0, touchDeviceId, fingerId, window, tempX, tempY, touchsize->p);
            break;

        case ACTION_UP:
            NormalizeTouchPoint(window, &tempX, &tempY);
            SDL_SendTouch(0, touchDeviceId, fingerId, window, SDL_EVENT_FINGER_UP, tempX, tempY, touchsize->p);
            break;

        case ACTION_CANCEL:
            /* 触摸被系统取消（如来电/下拉通知）：按抬起语义上报，避免上层鼠标按键状态卡住 */
            NormalizeTouchPoint(window, &tempX, &tempY);
            SDL_SendTouch(0, touchDeviceId, fingerId, window, SDL_EVENT_FINGER_CANCELED, tempX, tempY, touchsize->p);
            break;

        default:
            break;
    }
}

#endif /* SDL_VIDEO_DRIVER_OHOS */

/* vi: set ts=4 sw=4 expandtab: */
