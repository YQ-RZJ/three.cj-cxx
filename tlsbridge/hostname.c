/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * This source file is part of the Cangjie project, licensed under Apache-2.0
 * with Runtime Library Exception.
 *
 * See https://cangjie-lang.cn/pages/LICENSE for license information.
 */

#include <openssl/ssl.h>
#include <openssl/x509_vfy.h>
#include "api.h"

extern const char* CJ_TLS_DYN_GetHostName(SSL* ssl)
{
    if (ssl == NULL) {
        return NULL;
    }

    return SSL_get_servername(ssl, TLSEXT_NAMETYPE_host_name);
}

static int CJ_TLS_SetHostName_Callback(void* s, int* al, void* arg)
{
    (void)s;
    (void)al;
    (void)arg;
    // If we ever want to do SNI filtering on server,
    // this is the place to do it
    return SSL_TLSEXT_ERR_OK;
}

extern int CJ_TLS_DYN_ServerEnableSNI(SSL_CTX* context)
{
    if (context == NULL) {
        return 0;
    }

    (void)SSL_CTX_set_tlsext_servername_callback(context, CJ_TLS_SetHostName_Callback);
    return 1;
}

extern int CJ_TLS_DYN_SetHostName(SSL* stream, const char* name, ExceptionData* exception)
{
    if (stream == NULL || name == NULL) {
        return 0;
    }

    return (int)SSL_set_tlsext_host_name(stream, name);
}

extern int CJ_TLS_DYN_SetHostNameForVerify(SSL* stream, const char* name)
{
    if (stream == NULL || name == NULL) {
        return 0;
    }

    X509_VERIFY_PARAM* param = SSL_get0_param(stream);
    if (param == NULL) {
        return 0;
    }

    return X509_VERIFY_PARAM_set1_host(param, name, 0);
}
