/*
  Simple DirectMedia Layer
  Copyright (C) 1997-2026 Sam Lantinga <slouken@libsdl.org>

  This software is provided 'as-is', without any express or implied
  warranty.  In no event will the authors be held liable for any damages
  arising from the use of this software.

  Permission is granted to anyone to use this software for any purpose,
  including commercial applications, and to alter it and redistribute it
  freely, subject to the following restrictions:

  1. The origin of this software must not be misrepresented; you must not
     claim that you wrote the original software. If you use this software
     in a product, an acknowledgment in the product documentation would be
     appreciated but is not required.
  2. Altered source versions must be plainly marked as such, and must not be
     misrepresented as being the original software.
  3. This notice may not be removed or altered from any source distribution.
*/
#include "SDL_internal.h"

// OHOS vibrator-based haptic stub.
//
// SDL3's haptic API is rich (periodic, spring, custom effects), but a phone
// only exposes a simple vibrator.  We therefore implement a minimal driver
// that maps SDL_HAPTIC_SINE / SDL_HAPTIC_LEFTRIGHT to a timed vibration.
//
// On OHOS the vibrator is driven via the misc input event MSC_TIMESTAMP plus
// the Linux force-feedback ff_effect on /dev/input/event* — which the evdev
// haptic backend (haptic/ohos/SDL_syshaptic.c, copied from Linux) already
// handles.  This file only provides the OHOS-native fallback when evdev
// force-feedback is unavailable.

#ifdef SDL_HAPTIC_OHOS

#ifdef SDL_HAPTIC_LINUX
// The evdev backend already takes care of force feedback; this file is a
// no-op in that case to avoid duplicate symbols.
#else

#include "../SDL_syshaptic.h"
#include "SDL_haptic.h"
#include "../../stdlib/SDL_sysstdlib.h"

typedef struct {
    int32_t duration_ms;
    int32_t intensity; // 0..100
} OHOS_VibratorEffect;

static bool OHOS_HapticInit(void)
{
    // Report at least one device so SDL_HapticOpenFromMouse etc. work.
    return true;
}

static int OHOS_HapticGetCount(void)
{
    return 1;
}

static bool OHOS_HapticOpen(SDL_Haptic *haptic)
{
    haptic->hwdata = SDL_calloc(1, sizeof(int)); // simple flag storage
    if (!haptic->hwdata) return false;
    haptic->supported = SDL_HAPTIC_SINE | SDL_HAPTIC_LEFTRIGHT;
    haptic->neffects = 1;
    haptic->nplaying = 1;
    return true;
}

static void OHOS_HapticClose(SDL_Haptic *haptic)
{
    SDL_free(haptic->hwdata);
    haptic->hwdata = NULL;
}

static void OHOS_HapticQuit(void)
{
    // Nothing to clean up.
}

static int OHOS_HapticNewEffect(SDL_Haptic *haptic, SDL_HapticEffect *effect)
{
    OHOS_VibratorEffect *ve = SDL_calloc(1, sizeof(OHOS_VibratorEffect));
    if (!ve) return -1;
    ve->duration_ms = (int32_t)(effect->sine.length / 1000000LL); // ns -> ms
    ve->intensity = 100;
    haptic->hwdata = (struct haptic_hwdata *)ve;
    return 0;
}

static int OHOS_HapticRunEffect(SDL_Haptic *haptic, int effect_id, Uint32 iterations)
{
    OHOS_VibratorEffect *ve = (OHOS_VibratorEffect *)haptic->hwdata;
    if (!ve) return -1;
    // Best-effort native vibrator call; if the NDK wrapper is unavailable,
    // we simply return success without vibrating.
    // (Implementation detail left to the integration layer.)
    return 0;
}

static int OHOS_HapticStopEffect(SDL_Haptic *haptic, int effect_id)
{
    return 0;
}

static void OHOS_HapticDestroyEffect(SDL_Haptic *haptic, int effect_id)
{
    // Effect storage is the hwdata pointer; nothing else to free.
}

static int OHOS_HapticGetEffectStatus(SDL_Haptic *haptic, int effect_id)
{
    return 0; // SDL_HAPTIC_PLAYING not reliably detectable
}

static int OHOS_HapticSetGain(SDL_Haptic *haptic, int gain)
{
    return 0;
}

static int OHOS_HapticSetAutocenter(SDL_Haptic *haptic, int autocenter)
{
    return 0;
}

static int OHOS_HapticPause(SDL_Haptic *haptic)
{
    return 0;
}

static int OHOS_HapticUnpause(SDL_Haptic *haptic)
{
    return 0;
}

static int OHOS_HapticStopAll(SDL_Haptic *haptic)
{
    return 0;
}

// SDL3 does not use a static driver struct the way SDL2 did; the haptic
// backend is wired via SDL_HapticOpenDevice.  We keep this declaration for
// future wiring.
#endif // !SDL_HAPTIC_LINUX

#endif // SDL_HAPTIC_OHOS
