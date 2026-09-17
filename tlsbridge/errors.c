/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * This source file is part of the Cangjie project, licensed under Apache-2.0
 * with Runtime Library Exception.
 *
 * See https://cangjie-lang.cn/pages/LICENSE for license information.
 */

#include <stddef.h>
#include <stdbool.h>
#include <stdio.h>
#include <openssl/err.h>
#include <openssl/bio.h>
#include <openssl/crypto.h>
#include "api.h"

struct ExceptionDataS {
    const char* message;      // this is always allocated using malloc
    const char* constMessage; // this is never allocated
};

void ExceptionClear(ExceptionData* exception)
{
    ERR_clear_error();
    if (exception != NULL) {
        if (exception->message != NULL) {
            OPENSSL_free((void*)exception->message);
            exception->message = NULL;
        }

        exception->constMessage = NULL;
    }
}

static void HandleErrorPutFromStack(BIO* buffer)
{
    if (buffer == NULL) {
        return;
    }
    char codeBuffer[16];
    int maxErrors = 100;
    for (int count = 0; count < maxErrors; ++count) {
        unsigned long error = ERR_get_error();
        if (error == 0) {
            break;
        }

        const char* message = ERR_reason_error_string(error);
        if (message != NULL) {
            if (count > 0) {
                BIO_puts(buffer, ", ");
            }
            BIO_puts(buffer, message);

            // here we need this AND because we are compiling against openssl 3.x but running with openssl 1.x
            // ERR_GET_REASON from openssl3 is unable to remove the func code assuming it to be always zero
            // so we have no choice other than do it ourselves.
#define ERR_REASON_MASK_COMPAT 0xfff
            int reason = ERR_GET_REASON(error) & ERR_REASON_MASK_COMPAT;
            if (snprintf(codeBuffer, sizeof(codeBuffer), " (%d)", reason) > 0) {
                BIO_puts(buffer, codeBuffer);
            }
        }
    }
}

static const char* HandleErrorBuildString(BIO* buffer)
{
    if (buffer == NULL) {
        return NULL;
    }

    BIO_write(buffer, "\0", 1);

    BUF_MEM* ptr = NULL;
    BIO_get_mem_ptr(buffer, &ptr);
    if (ptr == NULL || ptr->data == NULL || ptr->length == 0) {
        return NULL;
    }

    return (const char*)OPENSSL_strndup(ptr->data, ptr->length);
}

static void AppendErrorMessage(ExceptionData* exception, BIO* buffer)
{
    if (exception == NULL || buffer == NULL) {
        return;
    }

    if (exception->constMessage != NULL) {
        BIO_puts(buffer, ", ");
        BIO_puts(buffer, exception->constMessage);
        exception->constMessage = NULL;
    }

    if (exception->message != NULL) {
        const char* existingMessage = exception->message;
        BIO_puts(buffer, ", ");
        BIO_puts(buffer, existingMessage);
        OPENSSL_free((void*)existingMessage);
        exception->message = NULL;
    }

    exception->message = HandleErrorBuildString(buffer);
}

void HandleError(ExceptionData* exception, const char* fallback)
{
    if (exception == NULL) {
        return;
    }

    if (ERR_peek_error() == 0) {
        exception->constMessage = fallback;
        return;
    }

    BIO* buffer = (BIO*)BIO_new(BIO_s_mem());
    if (buffer == NULL) {
        exception->constMessage = fallback;
        return;
    }

    BIO_puts(buffer, fallback);
    BIO_puts(buffer, ": ");

    HandleErrorPutFromStack(buffer);

    AppendErrorMessage(exception, buffer);

    if (exception->message == NULL) {
        exception->constMessage = fallback;
    }

    BIO_free(buffer);
}

void HandleAlertError(ExceptionData* exception, const char* description, const char* type)
{
    if (exception == NULL) {
        return;
    }

    BIO* buffer = (BIO*)BIO_new(BIO_s_mem());
    if (buffer == NULL) {
        return;
    }

    BIO_puts(buffer, "TLS alert");

    if (description != NULL) {
        BIO_puts(buffer, " ");
        BIO_puts(buffer, description);
    }
    if (type != NULL) {
        BIO_puts(buffer, "(");
        BIO_puts(buffer, type);
        BIO_puts(buffer, ")");
    }

    AppendErrorMessage(exception, buffer);

    BIO_free(buffer);
}

static void FormatFailedAssertionError(ExceptionData* exception, const char* description)
{
    BIO* buffer = BIO_new(BIO_s_mem());
    if (buffer == NULL) {
        exception->constMessage = description;
        return;
    }

    BIO_puts(buffer, "Predicate failed: ");
    BIO_puts(buffer, description);
    AppendErrorMessage(exception, buffer);

    BIO_free(buffer);
}

bool CheckOrFillException(ExceptionData* exception, bool condition, const char* description)
{
    if (condition) {
        return true;
    }

    if (exception != NULL && description != NULL) {
        FormatFailedAssertionError(exception, description);
    }

    return false;
}

static void FormatNullAssertionError(ExceptionData* exception, const char* name)
{
    BIO* buffer = BIO_new(BIO_s_mem());
    if (buffer == NULL) {
        exception->constMessage = name;
        return;
    }

    BIO_puts(buffer, name);
    BIO_puts(buffer, " shouldn't be NULL");
    AppendErrorMessage(exception, buffer);

    BIO_free(buffer);
}

bool CheckNotNull(ExceptionData* exception, const void* candidate, const char* name)
{
    if (candidate != NULL) {
        return true;
    }

    if (exception != NULL && name != NULL) {
        FormatNullAssertionError(exception, name);
    }

    return false;
}
