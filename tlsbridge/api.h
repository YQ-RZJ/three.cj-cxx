/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * This source file is part of the Cangjie project, licensed under Apache-2.0
 * with Runtime Library Exception.
 *
 * See https://cangjie-lang.cn/pages/LICENSE for license information.
 */

#ifndef CJTLS_API_H
#define CJTLS_API_H

#include <stdbool.h>
#include <openssl/ssl.h>
#include <openssl/bio.h>

#define CJTLS_EOF 0
#define CJTLS_FAIL (-1)
#define CJTLS_NEED_READ (-2)
#define CJTLS_NEED_WRITE (-3)
#define CJTLS_OK 1

#define EXCEPTION_OR_RETURN(exception, ret)                                                                    \
    do {                                                                                                       \
        if ((exception) == NULL) {                                                                             \
            return (ret);                                                                                      \
        };                                                                                                     \
        ExceptionClear(exception);                                                                             \
    } while (0)

#define EXCEPTION_OR_FAIL(exception) EXCEPTION_OR_RETURN((exception), CJTLS_FAIL)

#define NOT_NULL_OR_RETURN(exception, var, ret)                                                                \
    do {                                                                                                       \
        if (!CheckNotNull(exception, (void*)(var), #var))                                                      \
            return (ret);                                                                                      \
    } while (0)

#define NOT_NULL_OR_FAIL(exception, var) NOT_NULL_OR_RETURN((exception), (var), CJTLS_FAIL)

#define CHECK_OR_RETURN(exception, cond, ret)                                                                  \
    do {                                                                                                       \
        if (!CheckOrFillException(exception, (bool)(cond), #cond))                                             \
            return (ret);                                                                                      \
    } while (0)

#define CHECK_OR_FAIL(exception, cond) CHECK_OR_RETURN((exception), (cond), CJTLS_FAIL)

typedef struct ExceptionDataS ExceptionData;

typedef struct TlsCipherSuite {
    const char* name;
} TlsCipherSuite;

void ExceptionClear(ExceptionData* exception);

bool CheckOrFillException(ExceptionData* exception, bool condition, const char* description);

bool CheckNotNull(ExceptionData* exception, const void* candidate, const char* name);

void HandleAlertError(ExceptionData* exception, const char* description, const char* type);

void HandleError(ExceptionData* exception, const char* fallback);

BIO_METHOD* CJ_TLS_BIO_GetMethod(ExceptionData* exception);

int CJ_TLS_BIO_Map(BIO* bio, void* pointer, size_t length, int eof, ExceptionData* exception);

int CJ_TLS_BIO_Unmap(BIO* bio, int eof, ExceptionData* exception);

int NewSessionCallback(SSL* ssl, SSL_SESSION* session);

void SessionReusedCallback(SSL* ssl, SSL_SESSION* session);

BIO* InitBioWithPem(const void* pem, size_t length, ExceptionData* exception);
#endif
