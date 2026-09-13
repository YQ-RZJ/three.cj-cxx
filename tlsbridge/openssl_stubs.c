/*
 * Stub implementations for OpenSSL symbols that are referenced
 * by libcrypto.a / libssl.a but whose implementations were excluded
 * during the OpenSSL build (engine/comp features).
 *
 * These stubs return safe default values (NULL/0) so the library
 * can link and function correctly without ENGINE or COMP support.
 *
 * IMPORTANT: Do NOT include <openssl/engine.h> or <openssl/comp.h>
 * here because OPENSSL_NO_ENGINE and OPENSSL_NO_COMP are defined,
 * which causes those headers to skip all type/function declarations.
 * Instead, we use void* for all opaque OpenSSL types.
 */

#include <stddef.h>

/* ========== COMP (Compression) stubs ========== */

int COMP_get_type(const void *meth)
{
    (void)meth;
    return -1; /* no compression method */
}

const char *COMP_get_name(const void *meth)
{
    (void)meth;
    return NULL;
}

const void *COMP_CTX_get_method(const void *ctx)
{
    (void)ctx;
    return NULL;
}

void COMP_CTX_free(void *ctx)
{
    (void)ctx;
    /* no-op */
}

int COMP_compress_block(const void *meth, const void *in, int inl,
                        void *out, int outl)
{
    (void)meth;
    (void)in;
    (void)inl;
    (void)out;
    (void)outl;
    return -1; /* failure */
}

int COMP_expand_block(const void *meth, const void *in, int inl,
                      void *out, int outl)
{
    (void)meth;
    (void)in;
    (void)inl;
    (void)out;
    (void)outl;
    return -1; /* failure */
}

/* COMP_zlib is a global variable, not a function */
const void *COMP_zlib = NULL;

void ossl_comp_zlib_cleanup(void)
{
    /* no-op */
}

void ossl_comp_brotli_cleanup(void)
{
    /* no-op */
}

void ossl_comp_zstd_cleanup(void)
{
    /* no-op */
}

void ossl_err_load_COMP_strings(void)
{
    /* no-op */
}

void ossl_err_load_ENGINE_strings(void)
{
    /* no-op */
}

void *COMP_CTX_new(const void *meth)
{
    (void)meth;
    return NULL;
}

/* ========== ENGINE stubs ========== */

int ENGINE_init(void *e)
{
    (void)e;
    return 0; /* failure - no engines available */
}

int ENGINE_finish(void *e)
{
    (void)e;
    return 0; /* failure */
}

int ENGINE_free(void *e)
{
    (void)e;
    return 0; /* failure */
}

const char *ENGINE_get_id(const void *e)
{
    (void)e;
    return NULL;
}

const void *ENGINE_get_pkey_meth(void *e, int nid)
{
    (void)e;
    (void)nid;
    return NULL;
}

void *ENGINE_get_cipher_engine(int nid)
{
    (void)nid;
    return NULL;
}

const void *ENGINE_get_cipher(void *e, int nid)
{
    (void)e;
    (void)nid;
    return NULL;
}

void *ENGINE_get_digest_engine(int nid)
{
    (void)nid;
    return NULL;
}

const void *ENGINE_get_digest(void *e, int nid)
{
    (void)e;
    (void)nid;
    return NULL;
}

int ENGINE_load_ssl_client_cert(void *e, void *s,
                                void *ca_dn,
                                void **pcert, void **ppkey,
                                void **pother,
                                void *ui_method,
                                void *callback_data)
{
    (void)e;
    (void)s;
    (void)ca_dn;
    (void)pcert;
    (void)ppkey;
    (void)pother;
    (void)ui_method;
    (void)callback_data;
    return 0; /* failure */
}

void *ENGINE_get_ssl_client_cert_function(const void *e)
{
    (void)e;
    return NULL;
}

void *ENGINE_get_pkey_meth_engine(int nid)
{
    (void)nid;
    return NULL;
}

void *ENGINE_get_default_RAND(void)
{
    return NULL;
}

const void *ENGINE_get_RAND(const void *e)
{
    (void)e;
    return NULL;
}

void *ENGINE_get_default_RSA(void)
{
    return NULL;
}

const void *ENGINE_get_RSA(const void *e)
{
    (void)e;
    return NULL;
}

void *ENGINE_get_default_DSA(void)
{
    return NULL;
}

const void *ENGINE_get_DSA(const void *e)
{
    (void)e;
    return NULL;
}

void *ENGINE_get_default_DH(void)
{
    return NULL;
}

const void *ENGINE_get_DH(const void *e)
{
    (void)e;
    return NULL;
}

void *ENGINE_get_default_EC(void)
{
    return NULL;
}

const void *ENGINE_get_EC(const void *e)
{
    (void)e;
    return NULL;
}

void *ENGINE_by_id(const char *id)
{
    (void)id;
    return NULL;
}

void ENGINE_add_conf_module(void)
{
    /* no-op */
}

const void *ENGINE_get_pkey_asn1_meth_engine(int nid)
{
    (void)nid;
    return NULL;
}

const void *ENGINE_get_pkey_asn1_meth(const void *e, int nid)
{
    (void)e;
    (void)nid;
    return NULL;
}

const void *ENGINE_pkey_asn1_find_str(void **pe, const char *str, int len)
{
    (void)pe;
    (void)str;
    (void)len;
    return NULL;
}

int ENGINE_register_all_complete(void)
{
    return 0; /* failure */
}

void engine_load_dynamic_int(void)
{
    /* no-op */
}

void engine_load_rdrand_int(void)
{
    /* no-op */
}

void engine_load_openssl_int(void)
{
    /* no-op */
}

void engine_cleanup_int(void)
{
    /* no-op */
}

void ENGINE_load_builtin_engines(void)
{
    /* no-op */
}