/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * This source file is part of the Cangjie project, licensed under Apache-2.0
 * with Runtime Library Exception.
 *
 * See https://cangjie-lang.cn/pages/LICENSE for license information.
 */

#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <limits.h>
#include <string.h>
#include <openssl/ssl.h>
#include <openssl/x509.h>
#include <openssl/x509_vfy.h>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/crypto.h>
#include <openssl/objects.h>
#include "api.h"

#define MAX_CERT_COUNT 256

static int CjPemPasswordCb(char* buf, int size, int rwflag, void* userdata)
{
    if (size <= 0) { // invalid size
        return 0;
    }

    // userdata = password zero terminated string
    if (!userdata) {
        return 0;
    }

    size_t len = strlen((const char*)userdata) + 1;
    if ((size_t)size < len) {
        return 0;
    }

    memcpy(buf, userdata, len);
    return (int)len;
}

BIO* InitBioWithPem(const void* pem, size_t length, ExceptionData* exception)
{
    NOT_NULL_OR_RETURN(exception, pem, NULL);
    CHECK_OR_RETURN(exception, length < (size_t)INT_MAX, NULL);
    CHECK_OR_RETURN(exception, length > 0, NULL);

    BIO* mem = (BIO*)BIO_new(BIO_s_mem());
    if (!mem) {
        HandleError(exception, "Failed to create BIO for PEM");
        return NULL;
    }

    int writeSize = (int)length;
    if (BIO_write(mem, pem, writeSize) != writeSize) {
        HandleError(exception, "Failed to write PEM to BIO");
        BIO_vfree(mem);
        return NULL;
    }

    return mem;
}

static X509* LoadCert(const void* pem, size_t length, const char* password, ExceptionData* exception)
{
    NOT_NULL_OR_RETURN(exception, pem, NULL);

    BIO* mem = InitBioWithPem(pem, length, exception);
    if (mem == NULL) {
        return NULL;
    }

    X509* cert = PEM_read_bio_X509(mem, NULL, CjPemPasswordCb, (void*)password);
    if (cert == NULL) {
        HandleError(exception, "Failed to create X509 certificate: PEM_read_bio_X509() failed");
    }

    BIO_vfree(mem);

    return cert;
}

static EVP_PKEY* DecodePrivateKey(const void* keyBody, long keySize, ExceptionData* exception)
{
    const unsigned char* dataptr = (const unsigned char*)keyBody;

    EVP_PKEY* pkey = (EVP_PKEY*)d2i_AutoPrivateKey(NULL, &dataptr, keySize);
    if (pkey == NULL) {
        HandleError(exception,
                    "Failed to load private key, it's either corrupted, password is wrong or the format is unsupported");
    }

    return pkey;
}

// returns true if the key is for sure a PKCS8 encrypted key
// or false when uncertain
static bool IsEncryptedPkcs8(X509_SIG* p8)
{
    const X509_ALGOR* algorithm = NULL;
    const ASN1_OCTET_STRING* str = NULL;
    X509_SIG_get0(p8, &algorithm, &str);
    if (algorithm != NULL) {
        const ASN1_OBJECT* algOid;
        int paramtype;
        const void* param;
        X509_ALGOR_get0(&algOid, &paramtype, &param, algorithm);
        (void)paramtype;
        (void)param;

        int algNid = OBJ_obj2nid(algOid);
        if (algNid == NID_pbes2 || algNid == NID_id_scrypt) {
            return true;
        }
    }

    return false;
}

// returns true if the key is for sure a PKCS8 encrypted key
// or false when uncertain
static bool IsEncryptedPkcs8Key(const void* keyBody, size_t length, ExceptionData* exception)
{
    bool encrypted = false;
    BIO* mem = InitBioWithPem(keyBody, length, exception);
    if (mem == NULL) {
        return false;
    }

    X509_SIG* p8 = (X509_SIG*)d2i_PKCS8_bio(mem, NULL);
    if (p8 != NULL) {
        encrypted = IsEncryptedPkcs8(p8);
        X509_SIG_free(p8);
    }
    BIO_vfree(mem);
    return encrypted;
}

static EVP_PKEY* LoadPrivateKey(const void* keyBody, size_t keySize, ExceptionData* exception)
{
    NOT_NULL_OR_RETURN(exception, keyBody, NULL);
    CHECK_OR_RETURN(exception, keySize > 0, NULL);

    bool isEncryptedPkcs8Key = IsEncryptedPkcs8Key(keyBody, keySize, exception);
    if (isEncryptedPkcs8Key) {
        HandleError(exception, "Failed to load private key, no password specified for encrypted PKCS8 key");
        return NULL;
    }

    CHECK_OR_RETURN(exception, keySize < (size_t)LONG_MAX, NULL);
    return DecodePrivateKey(keyBody, (long)keySize, exception);
}

extern int CJ_TLS_DYN_Add_CA(SSL_CTX* ctx, const void* ca, size_t length, ExceptionData* exception)
{
    EXCEPTION_OR_RETURN(exception, 0);
    NOT_NULL_OR_RETURN(exception, ctx, 0);
    NOT_NULL_OR_RETURN(exception, ca, 0);
    CHECK_OR_RETURN(exception, length, 0);

    X509* cert = LoadCert(ca, length, 0, exception);
    if (!cert) {
        return 0;
    }

    X509_STORE* store = SSL_CTX_get_cert_store(ctx);
    if (!store) {
        HandleError(exception, "Failed to add CA: SSL_CTX_get_cert_store() failed");
        X509_free(cert);
        return 0;
    }

    if (X509_STORE_add_cert(store, cert) == 0) {
        HandleError(exception, "Failed to add CA: X509_STORE_add_cert() failed");
        X509_free(cert);
        return 0;
    }

    X509_free(cert); // decrement refcount

    return 1;
}

static bool TryGetCtxAndCert(SSL_CTX* ctx, const void* pem, size_t length, X509** outCert, ExceptionData* exception)
{
    NOT_NULL_OR_RETURN(exception, ctx, false);
    NOT_NULL_OR_RETURN(exception, pem, false);
    CHECK_OR_RETURN(exception, length > 0, false);
    NOT_NULL_OR_RETURN(exception, outCert, false);

    *outCert = LoadCert(pem, length, 0, exception);
    if (*outCert == NULL) {
        return false;
    }

    return true;
}

/**
 * Configure the specified certificate to be used (sent) (should be a single cert)
 */
extern int CJ_TLS_DYN_Use_Cert(SSL_CTX* ctx, const void* pem, size_t length, ExceptionData* exception)
{
    EXCEPTION_OR_RETURN(exception, 0);
    NOT_NULL_OR_RETURN(exception, ctx, 0);
    NOT_NULL_OR_RETURN(exception, pem, 0);
    CHECK_OR_RETURN(exception, length > 0, 0);

    X509* cert = NULL;
    if (!TryGetCtxAndCert(ctx, pem, length, &cert, exception)) {
        return 0;
    }

    if (SSL_CTX_use_certificate(ctx, cert) == 0) {
        X509_free(cert); // free certificate if failed
        HandleError(exception, "Failed to apply certificate: SSL_CTX_use_certificate() failed");
        return 0;
    }
    X509_free(cert); // decrease count because reference count was increaced internally
    return 1;
}

/**
 * Add a single certificate from the chain (to be sent). Should be invoked after CJ_TLS_DYN_Add_Cert.
 */
extern int CJ_TLS_DYN_Add_Cert(SSL_CTX* ctx, const void* pem, size_t length, ExceptionData* exception)
{
    EXCEPTION_OR_RETURN(exception, 0);
    NOT_NULL_OR_RETURN(exception, ctx, 0);
    NOT_NULL_OR_RETURN(exception, pem, 0);
    CHECK_OR_RETURN(exception, length > 0, 0);

    X509* cert = NULL;
    if (!TryGetCtxAndCert(ctx, pem, length, &cert, exception)) {
        return 0;
    }

    if (SSL_CTX_add0_chain_cert(ctx, cert) == 0) {
        HandleError(exception, "Failed to add certificate: SSL_CTX_add0_chain_cert() failed");
        X509_free(cert);
        return 0;
    }

    return 1;
}

extern int CJ_TLS_DYN_SetPrivateKey(SSL_CTX* ctx, const void* keyPem, size_t length, ExceptionData* exception)
{
    EXCEPTION_OR_RETURN(exception, 0);
    NOT_NULL_OR_RETURN(exception, ctx, 0);
    NOT_NULL_OR_RETURN(exception, keyPem, 0);
    CHECK_OR_RETURN(exception, length > 0, 0);

    EVP_PKEY* key = LoadPrivateKey(keyPem, length, exception);
    if (!key) {
        return 0;
    }

    if (SSL_CTX_use_PrivateKey(ctx, key) == 0) {
        HandleError(exception, "Failed to apply private key: SSL_CTX_use_PrivateKey() failed");
        EVP_PKEY_free(key);
        return 0;
    }

    EVP_PKEY_free(key); // decrement refcount

    return 1;
}

extern int CJ_TLS_DYN_CheckPrivateKey(SSL_CTX* ctx, const char* file)
{
    if (ctx == NULL) {
        return 0;
    }

    return SSL_CTX_check_private_key(ctx);
}

static int CertificateVerifyCallbackAlwaysAccepting(X509_STORE_CTX* certStore, void* arg)
{
    (void)arg;

    // we need this for SSL_get0_verified_chain() to work later
    // so consider peer cert and it's provided chain as verified
    // as we are trusting everything peer say
    X509* cert = X509_STORE_CTX_get0_cert(certStore);
    if (cert != NULL) {
        STACK_OF(X509)* untrusted = X509_STORE_CTX_get0_untrusted(certStore);
        STACK_OF(X509) * verifiedChain;
        if (untrusted == NULL) {
            verifiedChain = (STACK_OF(X509)*)OPENSSL_sk_new_null();
        } else {
            // duplicate and increment refcount for every cert in it
            verifiedChain = X509_chain_up_ref(untrusted);
        }

        (void)OPENSSL_sk_insert((void*)verifiedChain, cert, 0);
        (void)X509_up_ref(cert);

        X509_STORE_CTX_set0_verified_chain(certStore, verifiedChain);
    }

    X509_STORE_CTX_set_error(certStore, X509_V_OK);
    return 1; // always accept
}

extern int CJ_TLS_DYN_SetTrustAll(SSL_CTX* ctx)
{
    if (ctx == NULL) {
        return 0;
    }

    // we use always accepting callback instead of SSL_VERIFY_NONE
    // because using SSL_VERIFY_NONE on server causes client to not send certificate
    // breaking identification modes
    SSL_CTX_set_cert_verify_callback(ctx, CertificateVerifyCallbackAlwaysAccepting, NULL);

    return 1;
}

/**
 * Whether client need to identify (send certificate).
 */
extern int CJ_TLS_DYN_SetClientVerifyMode(SSL_CTX* ctx, int required, int verify)
{
    if (ctx == NULL) {
        return 0;
    }

    if (verify == 0 && required == 0) {
        // we are here because TlsClientIdentificationMode = Disabled
        // we don't ask for client certificate so the client will not send it
        // and nothing to verify
        SSL_CTX_set_verify(ctx, SSL_VERIFY_NONE, 0);
        return 1;
    }

    int flags = SSL_VERIFY_PEER;
    if (required != 0) {
        flags |= SSL_VERIFY_FAIL_IF_NO_PEER_CERT;
    }

    SSL_CTX_set_verify(ctx, flags, 0);
    return 1;
}

struct CertChainItem
{
    void* cert;
    int size;
};

extern void CJ_TLS_DYN_CertChainFree(struct CertChainItem* result, int i)
{
    if (result == NULL) {
        return;
    }

    for (int before = 0; before < i; before++) {
        void* sub = result[before].cert;
        if (sub != NULL) {
            OPENSSL_free(sub);
        }
    }
    free(result);
}

static bool EncodeCertTo(struct CertChainItem* result, X509* cert)
{
    unsigned char* ptr = NULL;
    int resultSize = i2d_X509(cert, &ptr);
    if (resultSize < 0 || ptr == NULL) {
        return false;
    }

    result->cert = ptr;
    result->size = resultSize;

    return true;
}

extern struct CertChainItem* CJ_TLS_DYN_GetPeerCertificate(const SSL* ssl, uint32_t* countPtr, ExceptionData* exception)
{
    EXCEPTION_OR_RETURN(exception, NULL);
    NOT_NULL_OR_RETURN(exception, ssl, NULL);
    NOT_NULL_OR_RETURN(exception, countPtr, NULL);

    *countPtr = 0;

    // SSL_get_peer_cert_chain() doesn't return cert itself on server
    // so we use SSL_get0_verified_chain that does always return all
    // the disadvantage is that it only return verified rather than actually sent
    // that is not exactly "fair" as it's not what the peer sent us
    // but it's simpler to implement
    STACK_OF(X509)* chain = (STACK_OF(X509)*)SSL_get0_verified_chain(ssl);
    if (chain == NULL) {
        // peer certificate may be optional: no error
        return NULL;
    }

    int count = OPENSSL_sk_num((void*)chain);
    if (count <= 0) {
        return NULL;
    }
    if (count > MAX_CERT_COUNT) {
        HandleError(exception, "Too many certificate entries provided");
        return NULL;
    }

    struct CertChainItem* result = malloc(sizeof(struct CertChainItem) * (size_t)count);
    if (result == NULL) {
        HandleError(exception, "Failed to allocate memory for certificate chain");
        return NULL;
    }

    for (int i = 0; i < count; ++i) {
        X509* cert = (X509*)OPENSSL_sk_value((void*)chain, i);
        if (cert == NULL) {
            CJ_TLS_DYN_CertChainFree(result, i);
            HandleError(exception, "Failed to get certificate entry");
            return NULL;
        }

        if (!EncodeCertTo(&result[i], cert)) {
            CJ_TLS_DYN_CertChainFree(result, i);
            HandleError(exception, "Failed to decode peer certificate entry");
            return NULL;
        }
    }

    *countPtr = (uint32_t)count;

    return result;
}

extern int CJ_TLS_DYN_SetSecurityLevel(SSL_CTX* ctx, int32_t level)
{
    if (ctx == NULL) {
        return 0;
    }

    /* set the security level to be safe enough */
    SSL_CTX_set_security_level(ctx, (int)level);

    return 1;
}

typedef int (*CustomVerifyCallbackType)(SSL_CTX* context, struct CertChainItem* chain, int count);

extern int CJ_TLS_DYN_VerifyCallback(X509_STORE_CTX* storeCtx, void* arg) {
    CustomVerifyCallbackType customVerifyCallback = (CustomVerifyCallbackType)arg;
    SSL* ssl = X509_STORE_CTX_get_ex_data(storeCtx, SSL_get_ex_data_X509_STORE_CTX_idx());
    if (ssl == NULL) {
        return 0;
    }
    SSL_CTX* ctx = SSL_get_SSL_CTX(ssl);
    if (ctx == NULL) {
        return 0;
    }

    STACK_OF(X509)* chain = X509_STORE_CTX_get0_untrusted(storeCtx);
    if (chain == NULL) {
        return customVerifyCallback(ctx, NULL, 0);
    }
    int count = OPENSSL_sk_num((void*)chain);
    if (count < 0) {
        return 0;
    } else if (count == 0) {
        return customVerifyCallback(ctx, NULL, 0);
    } else if (count > MAX_CERT_COUNT) {
        return 0;
    }

    struct CertChainItem* certs = malloc(sizeof(struct CertChainItem) * (size_t)count);
    if (certs == NULL) {
        return 0;
    }

    for (int i = 0; i < count; ++i) {
        X509* cert = (X509*)OPENSSL_sk_value((void*)chain, i);
        if (cert == NULL) {
            CJ_TLS_DYN_CertChainFree(certs, i);
            return 0;
        }

        if (!EncodeCertTo(&certs[i], cert)) {
            CJ_TLS_DYN_CertChainFree(certs, i);
            return 0;
        }
    }
    return customVerifyCallback(ctx, certs, count);
}

extern int CJ_TLS_DYN_SetCustomVerifyMode(
    SSL_CTX* ctx,
    int (*verifyCallback)(SSL_CTX* context, struct CertChainItem* chain, int count))
{
    SSL_CTX_set_cert_verify_callback(ctx, CJ_TLS_DYN_VerifyCallback, verifyCallback);
    return 1;
}
