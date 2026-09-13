/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 * This source file is part of the Cangjie project, licensed under Apache-2.0
 * with Runtime Library Exception.
 *
 * See https://cangjie-lang.cn/pages/LICENSE for license information.
 */

#include <openssl/ssl.h>
#include "api.h"

enum TlsProtoVersion {
    CJTLS_PROTO_VERSION_1_2 = 0, /* TLS1.2 */
    CJTLS_PROTO_VERSION_1_3 = 1, /* TLS1.3 */
    CJTLS_PROTO_VERSION_BUTT,
};

extern const char* CJ_TLS_DYN_GetVersion(SSL* ssl)
{
    if (ssl == NULL) {
        return NULL;
    }

    return SSL_get_version(ssl);
}

extern int CJ_TLS_DYN_SetProtoVersions(SSL_CTX* ctx, enum TlsProtoVersion min, enum TlsProtoVersion max)
{
    int ret;
    int sslVersionMin;
    int sslVersionMax;

    if (ctx == NULL) {
        return 0;
    }

    if (max < min || max >= CJTLS_PROTO_VERSION_BUTT) {
        return -1;
    }

    if (min == CJTLS_PROTO_VERSION_1_2) {
        sslVersionMin = TLS1_2_VERSION;
    } else {
        sslVersionMin = TLS1_3_VERSION;
    }

    if (max == CJTLS_PROTO_VERSION_1_2) {
        sslVersionMax = TLS1_2_VERSION;
    } else {
        sslVersionMax = TLS1_3_VERSION;
    }

    ret = SSL_CTX_set_min_proto_version(ctx, sslVersionMin);
    if (ret <= 0) {
        return ret;
    }

    ret = SSL_CTX_set_max_proto_version(ctx, sslVersionMax);
    if (ret <= 0) {
        return ret;
    }

    return 1;
}
