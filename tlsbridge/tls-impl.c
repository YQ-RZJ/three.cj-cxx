/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * This source file is part of the Cangjie project, licensed under Apache-2.0
 * with Runtime Library Exception.
 *
 * See https://cangjie-lang.cn/pages/LICENSE for license information.
 */

#include <string.h>
#include <openssl/ssl.h>
#include <openssl/bio.h>
#include <openssl/err.h>
#include <openssl/crypto.h>
#include "api.h"

static const char* TLS_HANDSHAKE_FAILED_SERVER = "TLS handshake failed (server)";
static const char* TLS_HANDSHAKE_FAILED_CLIENT = "TLS handshake failed (client)";

static int g_exceptionDataIndex = -1; // initialized int SslInit

static BIO* CreateBio(ExceptionData* exception)
{
    BIO_METHOD* method = CJ_TLS_BIO_GetMethod(exception);
    if (method == NULL) {
        return NULL;
    }

    BIO* mem = BIO_new(method);
    if (!mem) {
        return NULL;
    }

    return mem;
}

static void PutExceptionData(SSL* ssl, const ExceptionData* exception)
{
    if (ssl != NULL && g_exceptionDataIndex != -1) {
        (void)SSL_set_ex_data(ssl, g_exceptionDataIndex, (void*)exception);
    }
}

static void RemoveExceptionData(SSL* ssl)
{
    if (ssl != NULL && g_exceptionDataIndex != -1) {
        (void)SSL_set_ex_data(ssl, g_exceptionDataIndex, NULL);
    }
}

static void InfoCallback(const SSL* ssl, int type, int val)
{
    if ((type & SSL_CB_READ_ALERT) && g_exceptionDataIndex != -1) {
        ExceptionData* exception = (ExceptionData*)SSL_get_ex_data(ssl, g_exceptionDataIndex);
        if (exception != NULL) {
            HandleAlertError(exception, SSL_alert_desc_string_long(val), SSL_alert_type_string(val));
        }
    }
}

static int CheckParams(const SSL* ssl, const char* buffer, int size, ExceptionData* exception)
{
    if (!exception) {
        return -1;
    }
    if (!buffer) {
        HandleError(exception, "buffer shouldn't be NULL");
        return -1;
    }
    if (!ssl) {
        HandleError(exception, "SSL shouldn't be NULL");
        return -1;
    }
    if (size <= 0) {
        HandleError(exception, "buffer size should be positive");
        return -1;
    }
    return 0;
}

static BIO* MapInputBio(SSL* ssl, void* rawInput, size_t rawInputSize, int rawInputLast, ExceptionData* exception)
{
    BIO* inputBio = SSL_get_rbio(ssl);
    if (inputBio == NULL) {
        HandleError(exception, "SSL instance has no read BIO");
        return NULL;
    }

    if (CJ_TLS_BIO_Map(inputBio, rawInput, rawInputSize, rawInputLast, exception) == CJTLS_FAIL) {
        return NULL;
    }

    return inputBio;
}

static BIO* MapOutputBio(SSL* ssl, void* rawOutput, size_t rawOutputSize, ExceptionData* exception)
{
    BIO* outputBio = SSL_get_wbio(ssl);
    if (outputBio == NULL) {
        HandleError(exception, "SSL instance has no write BIO");
        return NULL;
    }

    if (CJ_TLS_BIO_Map(outputBio, rawOutput, rawOutputSize, 0, exception) == CJTLS_FAIL) {
        return NULL;
    }

    return outputBio;
}

static int SslReadFailed(SSL* ssl, int rc, ExceptionData* exception)
{
    if ((SSL_get_shutdown(ssl) & SSL_SENT_SHUTDOWN) != 0) {
        return CJTLS_EOF;
    }
    if (rc == 0) {
        // it is returned in all unknown cases
        BIO* bio = SSL_get_rbio(ssl);
        if (bio != NULL && BIO_eof(bio) != 0) {
            return CJTLS_EOF;
        }
    }

    HandleError(exception, "TLS failed to read data");
    return CJTLS_FAIL;
}

static int SslRead(SSL* ssl, char* buffer, int size, ExceptionData* exception)
{
    if (CheckParams(ssl, buffer, size, exception) != 0) {
        return CJTLS_FAIL;
    }

    ERR_clear_error();
    PutExceptionData(ssl, exception);
    int rc = SSL_read(ssl, buffer, size);
    RemoveExceptionData(ssl);

    if (rc <= 0) {
        int error = SSL_get_error(ssl, rc);
        switch (error) {
            case SSL_ERROR_ZERO_RETURN:
                return CJTLS_EOF;
            case SSL_ERROR_WANT_READ:
                return CJTLS_NEED_READ;
            case SSL_ERROR_WANT_WRITE:
                return CJTLS_NEED_WRITE;
            default:
                return SslReadFailed(ssl, rc, exception);
        }
    }

    return rc;
}

/**
 * Pass encrypted rawInput:rawInputSize to OpenSSL also providing rawOutput:rawOutputSize for writing
 * and get decrypted data to dataBuffer:dataBufferSize
 * updating dataBytesRead (to dataBuffer), rawBytesConsumed (from rawInput) and
 * rawBytesProduced (to rawOutput) correspondingly
 * returns: CJTLS_OK | CJTLS_EOF | CJTLS_AGAIN | CJTLS_FAIL
 */
extern int CJ_TLS_DYN_SslRead(SSL* ssl, char* dataBuffer, int dataBufferSize, void* rawInput, size_t rawInputSize, int rawInputLast, void* rawOutput, size_t rawOutputSize,
                              size_t* dataBytesRead, size_t* rawBytesConsumed, size_t* rawBytesProduced, ExceptionData* exception)
{
    EXCEPTION_OR_FAIL(exception);
    NOT_NULL_OR_FAIL(exception, dataBuffer);
    NOT_NULL_OR_FAIL(exception, rawInput);
    NOT_NULL_OR_FAIL(exception, rawOutput);
    NOT_NULL_OR_FAIL(exception, dataBytesRead);
    NOT_NULL_OR_FAIL(exception, rawBytesConsumed);
    NOT_NULL_OR_FAIL(exception, rawBytesProduced);
    CHECK_OR_FAIL(exception, dataBufferSize > 0);

    *dataBytesRead = 0;
    *rawBytesConsumed = 0;
    *rawBytesProduced = 0;

    BIO* inputBio = MapInputBio(ssl, rawInput, rawInputSize, rawInputLast, exception);
    if (inputBio == NULL) {
        return CJTLS_FAIL;
    }

    BIO* outputBio = MapOutputBio(ssl, rawOutput, rawOutputSize, exception);
    if (outputBio == NULL) {
        return CJTLS_FAIL;
    }

    int result = SslRead(ssl, dataBuffer, dataBufferSize, exception);

    // we may potentially loose exception data if failing to unmap (that is unlikely)
    int inputConsumed = CJ_TLS_BIO_Unmap(inputBio, rawInputLast, exception);
    if (inputConsumed > 0) {
        *rawBytesConsumed = (size_t)inputConsumed;
    }

    // we may potentially loose exception data if failing to unmap (that is unlikely)
    int outputProduced = CJ_TLS_BIO_Unmap(outputBio, 0, exception);
    if (outputProduced > 0) {
        *rawBytesProduced = (size_t)outputProduced;
    }

    if (result > 0) {
        *dataBytesRead = (size_t)result;
        return CJTLS_OK;
    }

    return result;
}

static int SSlWrite(SSL* ssl, char* buffer, int size, ExceptionData* exception)
{
    if (CheckParams(ssl, buffer, size, exception) != 0) {
        return CJTLS_FAIL;
    }

    ERR_clear_error();
    PutExceptionData(ssl, exception);
    int rc = SSL_write(ssl, buffer, size);
    RemoveExceptionData(ssl);

    if (rc <= 0) {
        int error = SSL_get_error(ssl, rc);
        switch (error) {
            case SSL_ERROR_WANT_READ:
                return CJTLS_NEED_READ;
            case SSL_ERROR_WANT_WRITE:
                return CJTLS_NEED_WRITE;
            default:
                HandleError(exception, "TLS failed to write data");
                return CJTLS_FAIL;
        }
    }

    return rc;
}

/**
 * Pass encrypted rawInput:rawInputSize to OpenSSL also providing rawOutput:rawOutputSize for writing
 * and put user data dataBuffer:dataBufferSize to be encrypted and sent
 * updating dataBytesWritten (from dataBuffer), rawBytesConsumed (from rawInput) and
 * rawBytesProduced (to rawOutput) correspondingly
 * returns: CJTLS_OK | CJTLS_EOF | CJTLS_AGAIN | CJTLS_FAIL
 */
extern int CJ_TLS_DYN_SslWrite(SSL* ssl, char* dataBuffer, int dataBufferSize, void* rawInput, size_t rawInputSize, int rawInputLast, void* rawOutput, size_t rawOutputSize,
                               size_t* dataBytesWritten, size_t* rawBytesConsumed, size_t* rawBytesProduced, ExceptionData* exception)
{
    EXCEPTION_OR_FAIL(exception);
    NOT_NULL_OR_FAIL(exception, dataBuffer);
    NOT_NULL_OR_FAIL(exception, rawInput);
    NOT_NULL_OR_FAIL(exception, rawOutput);
    NOT_NULL_OR_FAIL(exception, dataBytesWritten);
    NOT_NULL_OR_FAIL(exception, rawBytesConsumed);
    NOT_NULL_OR_FAIL(exception, rawBytesProduced);
    CHECK_OR_FAIL(exception, dataBufferSize > 0);

    *rawBytesConsumed = 0;
    *rawBytesProduced = 0;
    *dataBytesWritten = 0;

    BIO* inputBio = MapInputBio(ssl, rawInput, rawInputSize, rawInputLast, exception);
    if (inputBio == NULL) {
        return CJTLS_FAIL;
    }

    BIO* outputBio = MapOutputBio(ssl, rawOutput, rawOutputSize, exception);
    if (outputBio == NULL) {
        return CJTLS_FAIL;
    }

    int result = SSlWrite(ssl, dataBuffer, dataBufferSize, exception);

    // we may potentially loose exception data if failing to unmap (that is unlikely)
    int inputConsumed = CJ_TLS_BIO_Unmap(inputBio, rawInputLast, exception);
    if (inputConsumed > 0) {
        *rawBytesConsumed = (size_t)inputConsumed;
    }

    // we may potentially loose exception data if failing to unmap (that is unlikely)
    int outputProduced = CJ_TLS_BIO_Unmap(outputBio, 0, exception);
    if (outputProduced > 0) {
        *rawBytesProduced = (size_t)outputProduced;
    }

    if (result > 0) {
        *dataBytesWritten = (size_t)result;
        return CJTLS_OK;
    }

    return result;
}

extern void CJ_TLS_DYN_SslInit(void)
{
    OPENSSL_init_ssl(0, NULL);

    int index = CRYPTO_get_ex_new_index(CRYPTO_EX_INDEX_SSL, 0, (void*)"ExceptionData pointer", NULL, NULL, NULL);

    g_exceptionDataIndex = index;
}

static int SetServerDefaults(SSL_CTX* ctx, ExceptionData* exception)
{
    // SSL_OP_NO_TICKET is set to emulate TLS1.2 behaviour with TLS1.3 so session reuse works the same
    // see https://github.com/openssl/openssl/issues/11039
    // this is a workaround and should be replaced with the proper fix
    // it's less efficient but safe

    /* 禁用 TLS1.0, TLS1.1 以及重协商 */
    (void)SSL_CTX_set_options(ctx, SSL_OP_NO_TLSv1 | SSL_OP_NO_TLSv1_1 | SSL_OP_NO_RENEGOTIATION | SSL_OP_NO_TICKET);

    /* 设置默认的 TLS1.2 加密套 */
    int ret = SSL_CTX_set_cipher_list(ctx,
                                      "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:"
                                      "ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
                                      "DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384");
    if (ret <= 0) {
        HandleError(exception, "TLS failed to configure ciphers: SSL_CTX_set_cipher_list() failed");
        return CJTLS_FAIL;
    }

    /* 设置默认的 TLS1.3 加密套 */
    ret = SSL_CTX_set_ciphersuites(ctx, "TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256");
    if (ret <= 0) {
        HandleError(exception, "TLS failed to configure ciphers: SSL_CTX_set_ciphersuites() failed");
        return CJTLS_FAIL;
    }

    return CJTLS_OK;
}

static int SetClientDefaults(SSL_CTX* ctx, ExceptionData* exception)
{
    /* 默认禁用不安全的加密套 */
    int ret = SSL_CTX_set_cipher_list(ctx, "DEFAULT:!aNULL:!eNULL:!MD5:!3DES:!DES:!RC4:!IDEA:!SEED:!aDSS:!SRP:!PSK");
    if (ret <= 0) {
        HandleError(exception, "TLS failed to configure ciphers: SSL_CTX_set_cipher_list() failed");
        return CJTLS_FAIL;
    }

    /* 默认客户端需要校验服务端的证书 */
    SSL_CTX_set_verify(ctx, SSL_VERIFY_PEER, NULL);

    (void)SSL_CTX_set_session_cache_mode(ctx, SSL_SESS_CACHE_BOTH | SSL_SESS_CACHE_NO_INTERNAL);
    SSL_CTX_sess_set_new_cb(ctx, NewSessionCallback);

    return CJTLS_OK;
}

static unsigned long DefaultOptions(void)
{
    unsigned long options = SSL_OP_ALL | SSL_OP_NO_SSLv3 | SSL_OP_NO_COMPRESSION | SSL_OP_SINGLE_DH_USE | SSL_OP_SINGLE_ECDH_USE;
    options &= ~SSL_OP_DONT_INSERT_EMPTY_FRAGMENTS;
    return options;
}

extern SSL_CTX* CJ_TLS_DYN_CreateContext(int server, void (*keylogCallback)(const SSL*, const char*), ExceptionData* exception)
{
    EXCEPTION_OR_RETURN(exception, NULL);

    const SSL_METHOD* method;
    if (server != 0) {
        method = TLS_server_method();
    } else {
        method = TLS_client_method();
    }

    SSL_CTX* ctx = SSL_CTX_new(method);
    if (!ctx) {
        HandleError(exception, "TLS failed to create context");
        return NULL;
    }

    (void)SSL_CTX_set_options(ctx, DefaultOptions());

    SSL_CTX_set_info_callback(ctx, InfoCallback);

    if (keylogCallback != NULL) {
        SSL_CTX_set_keylog_callback(ctx, keylogCallback);
    }

    if (SSL_CTX_set_min_proto_version(ctx, TLS1_2_VERSION) != 1) {
        HandleError(exception, "OpenSSL SSL_CTX_set_min_proto_version() failed");
        SSL_CTX_free(ctx);
        return NULL;
    }

    if (SSL_CTX_set_max_proto_version(ctx, TLS1_3_VERSION) != 1) {
        HandleError(exception, "OpenSSL SSL_CTX_set_max_proto_version() failed");
        SSL_CTX_free(ctx);
        return NULL;
    }

    /**
     * Set default locations for trusted CA certificates, including the default path and file name.
     * The default certificate path is "certs" under the OpenSSL default path, and the default certificate name is "cert.pem".
     * The default certificate path can be changed through the environment variable "SSL_CERT_DIR".
     * The default certificate name can be changed through the environment variable "SSL_CERT_FILE".
     */
    if (SSL_CTX_set_default_verify_paths(ctx) != 1) {
        HandleError(exception, "OpenSSL SSL_CTX_set_default_verify_paths() failed");
        SSL_CTX_free(ctx);
        return NULL;
    }

    long mode = SSL_MODE_AUTO_RETRY | SSL_MODE_ACCEPT_MOVING_WRITE_BUFFER | SSL_MODE_ENABLE_PARTIAL_WRITE | SSL_MODE_RELEASE_BUFFERS;
    (void)SSL_CTX_set_mode(ctx, mode);

    int configResult;
    if (server != 0) {
        configResult = SetServerDefaults(ctx, exception);
    } else {
        configResult = SetClientDefaults(ctx, exception);
    }

    if (configResult == CJTLS_FAIL) {
        SSL_CTX_free(ctx);
        return NULL;
    }

    return ctx;
}

extern void CJ_TLS_DYN_FreeContext(SSL_CTX* ctx)
{
    if (ctx != NULL) {
        SSL_CTX_free(ctx);
    }
}

extern SSL* CJ_TLS_DYN_CreateSsl(SSL_CTX* ctx, int server, ExceptionData* exception)
{
    EXCEPTION_OR_RETURN(exception, NULL);
    NOT_NULL_OR_RETURN(exception, ctx, NULL);

    SSL* ssl = SSL_new(ctx);
    if (ssl == NULL) {
        HandleError(exception, "SSL_new() failed");
        return NULL;
    }

    BIO* read = CreateBio(exception);
    if (read == NULL) {
        SSL_free(ssl);
        return NULL;
    }

    BIO* write = CreateBio(exception);
    if (write == NULL) {
        BIO_free(read);
        SSL_free(ssl);
        return NULL;
    }

    SSL_set_bio(ssl, read, write);

    if (server != 0) {
        SSL_set_accept_state(ssl);
    } else {
        SSL_set_connect_state(ssl);
    }

    return ssl;
}

extern void CJ_TLS_DYN_FreeSsl(SSL* ssl)
{
    if (ssl != NULL) {
        SSL_free(ssl);
    }
}

static int SslHandshakeFailed(SSL* ssl, ExceptionData* exception)
{
    const char* message;
    if (SSL_is_server(ssl) != 0) {
        message = TLS_HANDSHAKE_FAILED_SERVER;
    } else {
        message = TLS_HANDSHAKE_FAILED_CLIENT;
    }

    HandleError(exception, message);
    return CJTLS_FAIL;
}

static int SslHandshake(SSL* ssl, ExceptionData* exception)
{
    PutExceptionData(ssl, exception);
    int rc = SSL_do_handshake(ssl);
    RemoveExceptionData(ssl);

    if (rc == 1) {
        if (SSL_session_reused(ssl) == 1) {
            SSL_SESSION* session = SSL_get_session(ssl);
            if (session != NULL) {
                SessionReusedCallback(ssl, session);
            }
        }

        return CJTLS_OK;
    }
    if (rc == 0) {
        return SslHandshakeFailed(ssl, exception);
    }

    int error = SSL_get_error(ssl, rc);
    switch (error) {
        case SSL_ERROR_WANT_READ:
            return CJTLS_NEED_READ;
        case SSL_ERROR_WANT_WRITE:
            return CJTLS_NEED_WRITE;
        case SSL_ERROR_SSL:
            return SslHandshakeFailed(ssl, exception);
        default:
            return SslHandshakeFailed(ssl, exception);
    }
}

/**
 * Pass encrypted rawInput:rawInputSize to OpenSSL also providing rawOutput:rawOutputSize for writing
 * and try to do handshake updating dataBytesRead (to dataBuffer), rawBytesConsumed (from rawInput) and
 * rawBytesProduced (to rawOutput) correspondingly
 * returns: CJTLS_OK | CJTLS_EOF | CJTLS_AGAIN | CJTLS_FAIL
 */
extern int CJ_TLS_DYN_SslHandshake(SSL* ssl, void* rawInput, size_t rawInputSize, int rawInputLast, void* rawOutput, size_t rawOutputSize, size_t* rawBytesConsumed,
                                   size_t* rawBytesProduced, ExceptionData* exception)
{
    EXCEPTION_OR_FAIL(exception);
    NOT_NULL_OR_FAIL(exception, ssl);
    NOT_NULL_OR_FAIL(exception, rawInput);
    NOT_NULL_OR_FAIL(exception, rawOutput);
    NOT_NULL_OR_FAIL(exception, rawBytesConsumed);
    NOT_NULL_OR_FAIL(exception, rawBytesProduced);

    *rawBytesProduced = 0;
    *rawBytesConsumed = 0;

    BIO* inputBio = MapInputBio(ssl, rawInput, rawInputSize, rawInputLast, exception);
    if (inputBio == NULL) {
        return CJTLS_FAIL;
    }

    BIO* outputBio = MapOutputBio(ssl, rawOutput, rawOutputSize, exception);
    if (outputBio == NULL) {
        return CJTLS_FAIL;
    }

    int result = SslHandshake(ssl, exception);
    // we may potentially loose exception data if failing to unmap (that is unlikely)
    int inputConsumed = CJ_TLS_BIO_Unmap(inputBio, rawInputLast, exception);
    if (inputConsumed > 0) {
        *rawBytesConsumed = (size_t)inputConsumed;
    }

    // we may potentially loose exception data if failing to unmap (that is unlikely)
    int outputProduced = CJ_TLS_BIO_Unmap(outputBio, 0, exception);
    if (outputProduced > 0) {
        *rawBytesProduced = (size_t)outputProduced;
    }

    return result;
}

static int SslShutdown(SSL* ssl, ExceptionData* exception)
{
    NOT_NULL_OR_FAIL(exception, ssl);

    int result = SSL_shutdown(ssl);
    if (result == 1) {
        return CJTLS_OK;
    }

    if (result == 0) {
        unsigned int state = (unsigned int)SSL_get_shutdown(ssl);
        if ((state & SSL_SENT_SHUTDOWN) == 0) {
            return CJTLS_NEED_WRITE;
        }
        if ((state & SSL_RECEIVED_SHUTDOWN) == 0) {
            return CJTLS_NEED_READ;
        }
        return CJTLS_OK;
    }

    int error = SSL_get_error(ssl, result);
    switch (error) {
        case SSL_ERROR_WANT_READ:
            return CJTLS_NEED_READ;
        case SSL_ERROR_WANT_WRITE:
            return CJTLS_NEED_WRITE;
        default:
            if ((SSL_get_shutdown(ssl) & SSL_SENT_SHUTDOWN) != 0) {
                return CJTLS_OK;
            }
            HandleError(exception, "TLS shutdown failed");
            return CJTLS_FAIL;
    }
}

extern int CJ_TLS_DYN_SslShutdown(SSL* ssl, void* rawInput, size_t rawInputSize, int rawInputLast, void* rawOutput, size_t rawOutputSize, size_t* rawBytesConsumed,
                                  size_t* rawBytesProduced, ExceptionData* exception)
{
    EXCEPTION_OR_FAIL(exception);
    NOT_NULL_OR_FAIL(exception, rawInput);
    NOT_NULL_OR_FAIL(exception, rawOutput);
    NOT_NULL_OR_FAIL(exception, rawBytesConsumed);
    NOT_NULL_OR_FAIL(exception, rawBytesProduced);

    *rawBytesConsumed = 0;
    *rawBytesProduced = 0;

    BIO* inputBio = MapInputBio(ssl, rawInput, rawInputSize, rawInputLast, exception);
    if (inputBio == NULL) {
        return CJTLS_FAIL;
    }

    BIO* outputBio = MapOutputBio(ssl, rawOutput, rawOutputSize, exception);
    if (outputBio == NULL) {
        return CJTLS_FAIL;
    }

    int result = SslShutdown(ssl, exception);

    // we may potentially loose exception data if failing to unmap (that is unlikely)
    int inputConsumed = CJ_TLS_BIO_Unmap(inputBio, rawInputLast, exception);
    if (inputConsumed > 0) {
        *rawBytesConsumed = (size_t)inputConsumed;
    }

    // we may potentially loose exception data if failing to unmap (that is unlikely)
    int outputProduced = CJ_TLS_BIO_Unmap(outputBio, 0, exception);
    if (outputProduced > 0) {
        *rawBytesProduced = (size_t)outputProduced;
    }

    return result;
}

extern int CJ_TLS_DYN_SetClientSignatureAlgorithms(SSL_CTX* ctx, const unsigned char* sigalgs, ExceptionData* exception)
{
    if (ctx == NULL || sigalgs == NULL) {
        return -1;
    }

    if (SSL_CTX_set1_sigalgs_list(ctx, (const char*)sigalgs) != 1) {
        HandleError(exception, "Failed to set client signature algorithms.");
        return -1;
    }

    return 1;
}
