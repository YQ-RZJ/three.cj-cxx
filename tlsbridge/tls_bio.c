/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * This source file is part of the Cangjie project, licensed under Apache-2.0
 * with Runtime Library Exception.
 *
 * See https://cangjie-lang.cn/pages/LICENSE for license information.
 */

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <stdatomic.h>
#include <openssl/ssl.h>
#include <openssl/bio.h>
#include <openssl/err.h>
#include "api.h"

typedef struct BioDataS {
    void* buffer;
    size_t length;
    size_t position;
    int eof;
} BioData;

static pthread_mutex_t g_mutex = PTHREAD_MUTEX_INITIALIZER;
static atomic_uintptr_t g_methodPtr = 0;

static int BioCreate(BIO* bio)
{
    if (bio == NULL) {
        return 0; // 0 - fail for BIO_METHOD.create
    }

    BioData* data = malloc(sizeof(BioData));
    if (data == NULL) {
        return 0;
    }

    data->buffer = NULL;
    data->length = 0;
    data->position = 0;
    data->eof = 0;

    BIO_set_init(bio, 1);
    BIO_set_data(bio, data);
    BIO_set_flags(bio, 0);
    return 1;
}

static int BioDestroy(BIO* bio)
{
    if (bio == NULL) {
        return 1;
    }

    BioData* data = (BioData*)BIO_get_data(bio);
    if (data != NULL) {
        BIO_set_data(bio, NULL);
        data->buffer = NULL;
        free(data);
    }

    return 0;
}

static long BioCtl(BIO* bio, int cmd, long num, void* ptr)
{
    (void)num;
    (void)ptr;

    if (cmd == BIO_CTRL_EOF) {
        BioData* data = (BioData*)BIO_get_data(bio);
        if (data != NULL) {
            return (long)(data->length == data->position && data->eof != 0);
        }
    }
    if (cmd == BIO_CTRL_FLUSH) {
        return 1;
    }
    if (cmd == BIO_CTRL_PENDING) {
        BioData* data = (BioData*)BIO_get_data(bio);
        if (data != NULL) {
            return (long)(data->length - data->position);
        }
    }

    return 0;
}

static int BioRead(BIO* bio, char* resultBuffer, int length)
{
    // we allow resultBuffer = NULL | length == 0 intentionally as it's useful for EOF polling
    if (bio == NULL || length < 0) {
        return -1;
    }

    BIO_clear_retry_flags(bio);

    BioData* data = (BioData*)BIO_get_data(bio);
    if (data == NULL) {
        BIO_set_retry_reason(bio, BIO_R_NULL_PARAMETER);
        return -1;
    }

    size_t remaining = data->length - data->position;
    if (remaining == 0 || data->buffer == NULL) {
        if (data->eof != 0) {
            return 0;
        }

        BIO_set_retry_read(bio);
        return -1;
    }

    if (resultBuffer == NULL || length <= 0) {
        BIO_set_retry_read(bio);
        return -1;
    }

    size_t resultBufferSize = (size_t)length;
    size_t batchSize = resultBufferSize;

    if (batchSize > remaining) {
        batchSize = remaining;
    }

    char* buffer = (char*)data->buffer;
    buffer += data->position;

    memcpy(resultBuffer, (const void*)buffer, batchSize);
    data->position += batchSize;

    return (int)batchSize;
}

static int BioWrite(BIO* bio, const char* sourceBuffer, int length)
{
    if (bio == NULL) {
        return -1;
    }
    if (sourceBuffer == NULL && length == 0) {
        return 0;
    }
    if (sourceBuffer == NULL || length == 0) {
        return -1;
    }

    BIO_clear_retry_flags(bio);

    BioData* data = (BioData*)BIO_get_data(bio);
    if (data == NULL) {
        BIO_set_retry_reason(bio, BIO_R_INVALID_ARGUMENT);
        return -1;
    }

    const size_t remaining = data->length - data->position;
    if (remaining == 0 && length > 0) {
        BIO_set_retry_write(bio);
        return -1;
    }
    if (remaining == 0 || data->buffer == NULL || length == 0) {
        return 0;
    }

    size_t batchSize = (size_t)length;

    if (batchSize > remaining) {
        batchSize = remaining;
    }

    char* buffer = (char*)data->buffer;
    buffer += data->position;

    memcpy((void*)buffer, (const void*)sourceBuffer, batchSize);
    data->position += batchSize;

    return (int)batchSize;
}

static int BioPuts(BIO* bio, const char* text)
{
    return BioWrite(bio, text, (int)strlen(text));
}

static BIO_METHOD* CreateMethod(ExceptionData* exception)
{
    BIO_METHOD* m;
    int index = BIO_get_new_index();
    if (index == -1) {
        HandleError(exception, "BIO_get_new_index() failed");
        return NULL;
    }

    m = BIO_meth_new(index | BIO_TYPE_SOURCE_SINK, "cj.tls.PinnedArray");
    if (m == NULL) {
        HandleError(exception, "BIO_meth_new() failed");
        return NULL;
    }

    int rc = 1;

    rc &= BIO_meth_set_read(m, BioRead);
    rc &= BIO_meth_set_write(m, BioWrite);
    rc &= BIO_meth_set_puts(m, BioPuts);
    rc &= BIO_meth_set_ctrl(m, BioCtl);

    rc &= BIO_meth_set_create(m, BioCreate);
    rc &= BIO_meth_set_destroy(m, BioDestroy);
    if (rc != 1) {
        HandleError(exception, "BIO_meth_set_XXX() failed");
        BIO_meth_free(m);
        return NULL;
    }

    return m;
}

static BIO_METHOD* GetMethodSlowpath(ExceptionData* exception)
{
    pthread_mutex_lock(&g_mutex);

    BIO_METHOD* m = (BIO_METHOD*)atomic_load(&g_methodPtr);
    if (m == NULL) {
        m = CreateMethod(exception);
        atomic_store(&g_methodPtr, (uintptr_t)m);
    }

    pthread_mutex_unlock(&g_mutex);

    return m;
}

BIO_METHOD* CJ_TLS_BIO_GetMethod(ExceptionData* exception)
{
    BIO_METHOD* m = (BIO_METHOD*)atomic_load(&g_methodPtr);
    if (m != NULL) {
        return m;
    }

    return GetMethodSlowpath(exception);
}

int CJ_TLS_BIO_Map(BIO* bio, void* pointer, size_t length, int eof, ExceptionData* exception)
{
    NOT_NULL_OR_FAIL(exception, bio);
    CHECK_OR_FAIL(exception, pointer != NULL || length == 0);

    BioData* data = (BioData*)BIO_get_data(bio);
    if (data == NULL) {
        HandleError(exception, "BIO has no data");
        return CJTLS_FAIL;
    }

    data->buffer = pointer;
    data->position = 0;
    data->length = length;
    data->eof = eof;

    return CJTLS_OK;
}

int CJ_TLS_BIO_Unmap(BIO* bio, int eof, ExceptionData* exception)
{
    NOT_NULL_OR_FAIL(exception, bio);

    BioData* data = (BioData*)BIO_get_data(bio);
    if (data == NULL) {
        HandleError(exception, "BIO has no data");
        return CJTLS_FAIL;
    }

    int position = (int)data->position;

    data->buffer = NULL;
    data->position = 0;
    data->length = 0;
    data->eof = eof;

    return position;
}
