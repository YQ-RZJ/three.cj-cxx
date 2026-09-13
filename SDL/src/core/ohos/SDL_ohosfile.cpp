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
#include "SDL_ohosfile.h"

#include <rawfile/raw_file_manager.h>

char *g_path = nullptr;

static NativeResourceManager *g_nativeResourceManager = nullptr;

const char *SDL_OHOSGetInternalStoragePath(void) { return g_path; }

NativeResourceManager *OHOS_GetResourceManager(void)
{
    return g_nativeResourceManager;
}

void OHOS_NAPI_GetResourceManager(NativeResourceManager *nativeResourceManager)
{
    g_nativeResourceManager = nativeResourceManager;
}

void OHOS_CloseResourceManager(void)
{
    if (g_nativeResourceManager) {
        OH_ResourceManager_ReleaseNativeResourceManager(g_nativeResourceManager);
        g_nativeResourceManager = nullptr;
    }
}
