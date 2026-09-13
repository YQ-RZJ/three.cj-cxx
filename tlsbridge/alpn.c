/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * This source file is part of the Cangjie project, licensed under Apache-2.0
 * with Runtime Library Exception.
 *
 * See https://cangjie-lang.cn/pages/LICENSE for license information.
 */

#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <pthread.h>
#include <openssl/ssl.h>
#include <openssl/crypto.h>
#include "api.h"

/* The server saves the structure of the user setting alpn protocol*/
struct AlpnArg {
    unsigned char* protos;
    unsigned int protosLen;
};

#define CJTLS_PROTOS_LEN_MAX (INT_MAX)

extern int CJ_TLS_DYN_SetClientAlpnProtocols(SSL_CTX* ctx, const unsigned char* protos, unsigned int protosLen)
{
    if (ctx == NULL || protos == NULL || protosLen == 0) {
        return -1;
    }

    /* This interface returns 0 for success and non-zero for failure. */
    if (SSL_CTX_set_alpn_protos(ctx, protos, protosLen) != 0) {
        return -1;
    }

    return 1;
}

/* When ctx is released, the callback function will be called to release ex_data */
static void AlpnFreeCallback(void* parent, void* ptr, CRYPTO_EX_DATA* ad, int idx, long argl, void* argp)
{
    struct AlpnArg* data;
    (void)parent;
    (void)ad;
    (void)idx;
    (void)argl;
    (void)argp;

    if (ptr != NULL) {
        data = (struct AlpnArg*)ptr;
        free(data->protos);
        free(data);
    }
}

static int AlpnGetIndex(void)
{
    /* The server saves the index of alpn's exdata, which must be initialized to -1 */
    static int g_alpnIndex = -1;
    static pthread_mutex_t g_alpnIndexLock = PTHREAD_MUTEX_INITIALIZER;

    if (g_alpnIndex == -1) {
        pthread_mutex_lock(&g_alpnIndexLock);
        if (g_alpnIndex == -1) {
            g_alpnIndex = CRYPTO_get_ex_new_index(CRYPTO_EX_INDEX_SSL_CTX, 0, NULL, NULL, NULL, AlpnFreeCallback);
        }
        pthread_mutex_unlock(&g_alpnIndexLock);
    }

    return g_alpnIndex;
}

static struct AlpnArg* ServerAlpnProtosDataInit(const unsigned char* protos, unsigned int protosLen)
{
    struct AlpnArg* data;

    if (protosLen >= CJTLS_PROTOS_LEN_MAX) {
        return NULL;
    }

    data = malloc(sizeof(struct AlpnArg));
    if (data == NULL) {
        return NULL;
    }

    data->protos = malloc(protosLen);
    if (data->protos == NULL) {
        free(data);
        return NULL;
    }

    memcpy(data->protos, protos, protosLen);

    data->protosLen = protosLen;
    return data;
}

/* The server calls this callback function to select the alpn protocol according to the client request. */
static int AlpnSelectCallback(
    SSL* ssl, const unsigned char** out, unsigned char* outlen, const unsigned char* in, unsigned int inlen, void* arg)
{
    unsigned char* res = NULL;
    unsigned char reslen = 0;
    SSL_CTX* ctx = (SSL_CTX*)SSL_get_SSL_CTX(ssl);
    int ret;
    (void)arg;

    int alpnIndex = AlpnGetIndex();
    if (alpnIndex == -1) {
        return SSL_TLSEXT_ERR_NOACK;
    }

    struct AlpnArg* data = (struct AlpnArg*)SSL_CTX_get_ex_data(ctx, alpnIndex);
    if (data == NULL) {
        /* Server not set alpn, continue handshake */
        return SSL_TLSEXT_ERR_NOACK;
    }

    ret = SSL_select_next_proto(&res, &reslen, data->protos, data->protosLen, in, inlen);
    if (ret == OPENSSL_NPN_NEGOTIATED) {
        *out = res;
        *outlen = reslen;
        return SSL_TLSEXT_ERR_OK;
    } else {
        /* The server set up alpn, but did not select success, terminating the handshake */
        return SSL_TLSEXT_ERR_ALERT_FATAL;
    }
}

/* Before setting new data, call this interface to clear the old data. */
static int AlpnClear(SSL_CTX* ctx, int index)
{
    struct AlpnArg* data = SSL_CTX_get_ex_data(ctx, index);
    if (data != NULL) {
        free(data->protos);
        free(data);
    }

    return SSL_CTX_set_ex_data(ctx, index, NULL);
}

extern int CJ_TLS_DYN_SetServerAlpnProtos(SSL_CTX* ctx, const unsigned char* protos, unsigned int protosLen)
{
    struct AlpnArg* data;
    int ret;

    if (ctx == NULL || protos == NULL || protosLen == 0) {
        return -1;
    }

    /* During the existence of ctx, it is necessary to ensure that the memory pointed to by protos is always valid, so
     * copy and save the memory */
    data = ServerAlpnProtosDataInit(protos, protosLen);
    if (data == NULL) {
        return -1;
    }

    /* Save the data in exdata of ctx. When ctx is released, tls_alpn_free_callback will be called automatically to
     * release the data. */
    int alpnIndex = AlpnGetIndex();
    if (alpnIndex == -1) {
        free(data->protos);
        free(data);
        return -1;
    }

    ret = AlpnClear(ctx, alpnIndex);
    if (ret <= 0) {
        free(data->protos);
        free(data);
        return ret;
    }
    ret = SSL_CTX_set_ex_data(ctx, alpnIndex, data);
    if (ret <= 0) {
        free(data->protos);
        free(data);
        return ret;
    }

    SSL_CTX_set_alpn_select_cb(ctx, AlpnSelectCallback, NULL);
    return 1;
}

extern void CJ_TLS_DYN_GetAlpnSelected(
    const SSL* stream, const unsigned char** proto, unsigned int* len)
{
    if (stream == NULL || proto == NULL || len == NULL) {
        if (proto != NULL) {
            *proto = NULL;
        }
        if (len != NULL) {
            *len = 0;
        }
        return;
    }

    SSL_get0_alpn_selected(stream, proto, len);
}
