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

#ifdef SDL_SENSOR_OHOS

// OHOS native sensor API (libohsensor.so)
#include <sensors/oh_sensor.h>
#include "SDL_ohossensor.h"
#include "../SDL_syssensor.h"
#include "../SDL_sensor_c.h"
#include "../../thread/SDL_systhread.h"

typedef struct
{
    Sensor_Info *info;
    Sensor_Type type;
    char name[64];
    SDL_SensorID instance_id;
    SDL_Sensor *sensor;
    bool opened;
} OHOS_SensorItem;

static OHOS_SensorItem *SDL_sensors_ohos = NULL;
static int SDL_sensors_ohos_count = 0;

// Map OHOS SensorType -> SDL_SensorType
static SDL_SensorType OHOS_SensorToSDLType(Sensor_Type t)
{
    switch (t) {
    case SENSOR_TYPE_ACCELEROMETER:
    case SENSOR_TYPE_LINEAR_ACCELERATION:
        return SDL_SENSOR_ACCEL;
    case SENSOR_TYPE_GYROSCOPE:
        return SDL_SENSOR_GYRO;
    default:
        return SDL_SENSOR_UNKNOWN;
    }
}

// Callback invoked by OHOS when a new sensor sample arrives.
static void OHOS_SensorDataCallback(Sensor_Event *event)
{
    Sensor_Type stype = SENSOR_TYPE_ACCELEROMETER;
    int64_t timestamp_ns = 0;
    float *data = NULL;
    uint32_t length = 0;
    Uint64 timestamp;
    int i;

    OH_SensorEvent_GetType(event, &stype);
    OH_SensorEvent_GetTimestamp(event, &timestamp_ns);
    OH_SensorEvent_GetData(event, &data, &length);

    timestamp = SDL_GetTicksNS();

    SDL_LockSensors();
    for (i = 0; i < SDL_sensors_ohos_count; ++i) {
        OHOS_SensorItem *item = &SDL_sensors_ohos[i];
        if (item->opened && item->type == stype && item->sensor) {
            SDL_SendSensorUpdate(timestamp, item->sensor, (Uint64)timestamp_ns, data, (int)length);
        }
    }
    SDL_UnlockSensors();
}

static bool OHOS_SensorInit(void)
{
    return true;
}

static int OHOS_SensorGetCount(void)
{
    return SDL_sensors_ohos_count;
}

static void OHOS_SensorDetect(void)
{
    Sensor_Info **infos = NULL;
    uint32_t count = 0;
    uint32_t i;

    if (SDL_sensors_ohos != NULL) {
        return; // already populated
    }

    if (OH_Sensor_GetInfos(&infos, &count) != 0 || count == 0) {
        return;
    }

    SDL_sensors_ohos = (OHOS_SensorItem *)SDL_calloc(count, sizeof(OHOS_SensorItem));
    if (!SDL_sensors_ohos) {
        OH_Sensor_DestroyInfos(infos, count);
        return;
    }

    for (i = 0; i < count; ++i) {
        OHOS_SensorItem *item = &SDL_sensors_ohos[i];
        Sensor_Type type = SENSOR_TYPE_ACCELEROMETER;
        uint32_t nameLen = sizeof(item->name);

        item->info = infos[i];
        item->instance_id = (SDL_SensorID)(i + 1);
        OH_SensorInfo_GetType(item->info, &type);
        item->type = type;
        if (OH_SensorInfo_GetName(item->info, item->name, &nameLen) != 0) {
            SDL_snprintf(item->name, sizeof(item->name), "OHOS Sensor %u", i);
        }
    }
    SDL_sensors_ohos_count = (int)count;
}

static const char *OHOS_SensorGetDeviceName(int device_index)
{
    if (device_index < 0 || device_index >= SDL_sensors_ohos_count) return "";
    return SDL_sensors_ohos[device_index].name;
}

static SDL_SensorType OHOS_SensorGetDeviceType(int device_index)
{
    if (device_index < 0 || device_index >= SDL_sensors_ohos_count) return SDL_SENSOR_UNKNOWN;
    return OHOS_SensorToSDLType(SDL_sensors_ohos[device_index].type);
}

static int OHOS_SensorGetDeviceNonPortableType(int device_index)
{
    if (device_index < 0 || device_index >= SDL_sensors_ohos_count) return 0;
    return (int)SDL_sensors_ohos[device_index].type;
}

static SDL_SensorID OHOS_SensorGetDeviceInstanceID(int device_index)
{
    if (device_index < 0 || device_index >= SDL_sensors_ohos_count) return 0;
    return SDL_sensors_ohos[device_index].instance_id;
}

static bool OHOS_SensorOpen(SDL_Sensor *sensor, int device_index)
{
    if (device_index < 0 || device_index >= SDL_sensors_ohos_count) {
        return false;
    }

    OHOS_SensorItem *item = &SDL_sensors_ohos[device_index];
    Sensor_SubscriptionId *id = NULL;
    Sensor_SubscriptionAttribute *attr = NULL;
    Sensor_Subscriber *sub = NULL;

    id = OH_Sensor_CreateSubscriptionId();
    attr = OH_Sensor_CreateSubscriptionAttribute();
    sub = OH_Sensor_CreateSubscriber();
    if (!id || !attr || !sub) {
        if (id) OH_Sensor_DestroySubscriptionId(id);
        if (attr) OH_Sensor_DestroySubscriptionAttribute(attr);
        if (sub) OH_Sensor_DestroySubscriber(sub);
        return false;
    }

    OH_SensorSubscriptionId_SetType(id, item->type);
    // Sampling interval in nanoseconds; use a reasonable default of 20 ms.
    OH_SensorSubscriptionAttribute_SetSamplingInterval(attr, 20000000LL);
    OH_SensorSubscriber_SetCallback(sub, OHOS_SensorDataCallback);

    if (OH_Sensor_Subscribe(id, attr, sub) != 0) {
        OH_Sensor_DestroySubscriptionId(id);
        OH_Sensor_DestroySubscriptionAttribute(attr);
        OH_Sensor_DestroySubscriber(sub);
        return false;
    }

    // Keep the handles on the item so we can unsubscribe on close.
    item->sensor = sensor;
    item->opened = true;
    return true;
}

static void OHOS_SensorUpdate(SDL_Sensor *sensor)
{
    // OHOS pushes samples asynchronously via OHOS_SensorDataCallback.
    // Nothing to poll here.
}

static void OHOS_SensorClose(SDL_Sensor *sensor)
{
    int i;

    for (i = 0; i < SDL_sensors_ohos_count; ++i) {
        OHOS_SensorItem *item = &SDL_sensors_ohos[i];
        if (item->sensor == sensor && item->opened) {
            item->opened = false;
            item->sensor = NULL;
            break;
        }
    }
}

static void OHOS_SensorQuit(void)
{
    if (SDL_sensors_ohos) {
        SDL_free(SDL_sensors_ohos);
        SDL_sensors_ohos = NULL;
        SDL_sensors_ohos_count = 0;
    }
}

SDL_SensorDriver SDL_OHOS_SensorDriver = {
    OHOS_SensorInit,
    OHOS_SensorGetCount,
    OHOS_SensorDetect,
    OHOS_SensorGetDeviceName,
    OHOS_SensorGetDeviceType,
    OHOS_SensorGetDeviceNonPortableType,
    OHOS_SensorGetDeviceInstanceID,
    OHOS_SensorOpen,
    OHOS_SensorUpdate,
    OHOS_SensorClose,
    OHOS_SensorQuit,
};

#endif // SDL_SENSOR_OHOS
