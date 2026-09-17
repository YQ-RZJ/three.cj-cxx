/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * This source file is part of the Cangjie project, licensed under Apache-2.0
 * with Runtime Library Exception.
 *
 * See https://cangjie-lang.cn/pages/LICENSE for license information.
 */

#include <stddef.h>
#include <stdlib.h>
#include <openssl/ssl.h>
#include <openssl/crypto.h>
#include "api.h"

extern int CJ_TLS_DYN_SetCipherList(SSL_CTX* ctx, const char* str)
{
    if (ctx == NULL || str == NULL) {
        return 0;
    }

    return SSL_CTX_set_cipher_list(ctx, str);
}

extern int CJ_TLS_DYN_SetCipherSuites(SSL_CTX* ctx, const char* str)
{
    if (ctx == NULL || str == NULL) {
        return 0;
    }

    return SSL_CTX_set_ciphersuites(ctx, str);
}

static const TlsCipherSuite* GetCipherSuite(const SSL_CIPHER* cipher)
{
    if (cipher == NULL) {
        return NULL;
    }

    TlsCipherSuite* cipherSuite = (TlsCipherSuite*)malloc((size_t)sizeof(TlsCipherSuite));
    if (cipherSuite == NULL) {
        return NULL;
    }

    const char* name = SSL_CIPHER_get_name(cipher);
    cipherSuite->name = OPENSSL_strdup(name);
    if (cipherSuite->name == NULL) {
        free(cipherSuite);
        return NULL;
    }

    return cipherSuite;
}

extern const TlsCipherSuite* CJ_TLS_DYN_GetCipherSuite(SSL* ssl)
{
    if (ssl == NULL) {
        return NULL;
    }

    const SSL_CIPHER* cipher = (const SSL_CIPHER*)SSL_get_current_cipher(ssl);

    return GetCipherSuite(cipher);
}

extern const TlsCipherSuite** CJ_TLS_DYN_GetAllCipherSuites(void)
{
    const SSL_METHOD* method = (const SSL_METHOD*)TLS_client_method();
    SSL_CTX* ctx = (SSL_CTX*)SSL_CTX_new(method);
    if (ctx == NULL) {
        return NULL;
    }

    STACK_OF(SSL_CIPHER)* ciphers = (STACK_OF(SSL_CIPHER)*)SSL_CTX_get_ciphers(ctx);
    if (ciphers == NULL) {
        return NULL;
    }

    int ciphersCount = OPENSSL_sk_num((void*)ciphers);
    size_t initialSize = (size_t)(ciphersCount + 1) * sizeof(TlsCipherSuite*);
    if (initialSize == 0) {
        SSL_CTX_free(ctx);
        return NULL;
    }
    const TlsCipherSuite** cipherSuites = malloc(initialSize);
    if (cipherSuites == NULL) {
        SSL_CTX_free(ctx);
        return NULL;
    }

    // parse suites
    int parsedSuites = 0;
    for (int i = 0; i < ciphersCount; i++) {
        const SSL_CIPHER* cipher = (const SSL_CIPHER*)OPENSSL_sk_value((void*)ciphers, i);
        if (cipher != NULL) {
            const TlsCipherSuite* cipherSuite = GetCipherSuite(cipher);
            if (cipherSuite != NULL) {
                cipherSuites[parsedSuites] = cipherSuite;
                parsedSuites++;
            }
        }
    }

    cipherSuites[parsedSuites] = NULL;

    SSL_CTX_free(ctx);

    return cipherSuites;
}
