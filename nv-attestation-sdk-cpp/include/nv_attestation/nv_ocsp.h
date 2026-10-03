/*
 * SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
#pragma once

#include <vector>
#include <string>
#include <memory>
#include <time.h>
#include <openssl/bio.h>
#include <openssl/conf.h>

#include "nv_types.h"
#include "nv_attestation/error.h"
#include "nv_attestation/verify.h"
#include "nv_attestation/nv_http.h"
#include "nv_attestation/nv_cache.h"

namespace nvattestation {


struct NvOcspResponse {
    time_t thisupd;
    time_t nextupd;
    int reason;
    int status;
    bool nonce_matches;
    bool response_valid;
    // sol: set only by RawProofOcspClient. The status was judged by its
    // signed times against an owner-supplied verification time instead of a
    // request nonce, and stays acceptable until status_deadline.
    bool signed_age = false;
    time_t verification_time = 0;
    time_t status_deadline = 0;
};

/**
 * @brief sol: strict verification shared by every OCSP response path.
 *
 * A response is accepted only if it is one complete, successful DER
 * OCSPResponse whose signature verifies under OCSP_basic_verify with
 * flags 0 (issuer or directly delegated responder carrying
 * id-kp-OCSPSigning, plain trust anchors), and it carries exactly one
 * SingleResponse for the requested CertID. Any failure is an error and
 * yields no status.
 */
class OcspResponseVerifier {
public:
    static Error parse_basic_response(
        const unsigned char* der,
        size_t der_len,
        nv_unique_ptr<OCSP_BASICRESP>& out_basic_response
    );

    static Error verify_signature(
        OCSP_BASICRESP* basic_response,
        const nv_unique_ptr<stack_st_X509>& intermediates,
        const nv_unique_ptr<X509_STORE>& trust_store
    );

    static size_t count_single_responses(OCSP_BASICRESP* basic_response, OCSP_CERTID* id);

    /**
     * @brief Extracts the one SingleResponse for id. thisUpdate is required;
     * out_has_next_update reports whether nextUpdate was present.
     */
    static Error get_single_status(
        OCSP_BASICRESP* basic_response,
        OCSP_CERTID* id,
        int& out_status,
        int& out_reason,
        time_t& out_this_update,
        bool& out_has_next_update,
        time_t& out_next_update
    );
};

/**
 * @brief Interface for an OCSP HTTP client.
 * This allows for mocking the HTTP transfer part of OCSP requests during testing.
 */
class IOcspHttpClient {
protected:
    IOcspHttpClient() = default;
public:
    virtual ~IOcspHttpClient() = default;


    /**
     * @brief Performs the HTTP transfer for an OCSP request with retry logic and response processing.
     *
     * @param req_bio The BIO containing the serialized OCSP request.
     * @param out_ocsp_resp Output parameter for the successfully parsed OCSP response.
     * @return Error code indicating the result of the operation.
     */
    virtual Error get_ocsp_response(
        const nv_unique_ptr<X509>& subject_cert,
        const nv_unique_ptr<X509>& issuer_cert,
        const nv_unique_ptr<stack_st_X509>& intermediates,
        const nv_unique_ptr<X509_STORE>& trust_store,
        NvOcspResponse& out_ocsp_response
    ) = 0;


};

/**
 * @brief NvHttpClient-based implementation of IOcspHttpClient.
 * This implementation uses NvHttpClient for OCSP requests with direct request/response parsing.
 */
class NvHttpOcspClient : public IOcspHttpClient {
public:
    NvHttpOcspClient() = default;
    static constexpr const char* DEFAULT_BASE_URL = "https://ocsp.ndis.nvidia.com";
    static constexpr time_t DEFAULT_NEXT_UPDATE_TTL_SECONDS = 3600;

    Error get_ocsp_response(
        const nv_unique_ptr<X509>& subject_cert,
        const nv_unique_ptr<X509>& issuer_cert,
        const nv_unique_ptr<stack_st_X509>& intermediates,
        const nv_unique_ptr<X509_STORE>& trust_store,
        NvOcspResponse& out_ocsp_response
    ) override;

    static Error create(
        NvHttpOcspClient& out_client,
        const std::string& base_url,
        const std::string& service_key,
        const HttpOptions& http_options
    );

    /**
     * @brief Creates an NvHttpOcspClient instance.
     *
     * @param out_client Output parameter for the created client
     * @param ocsp_url The OCSP server URL
     * @param http_options HTTP options for the client
     * @return Error::Ok on success, error code on failure
     */
    static Error init_from_env(
        NvHttpOcspClient& out_client,
        const char * base_url,
        const std::string& service_key,
        const HttpOptions& http_options
    );

private:
    HttpOptions m_http_options;
    std::string m_ocsp_url;
    NvHttpClient m_http_client;
};

/**
 * @brief sol: offline status provider over raw NVIDIA OCSP responses.
 *
 * It has no HTTP client and never falls back to one. Each required CertID
 * must be covered by exactly one SingleResponse across the supplied
 * responses; unused responses for other CertIDs are ignored. A covering
 * response must verify exactly as on the online path, carry thisUpdate and
 * nextUpdate, have thisUpdate no more than FUTURE_TOLERANCE_SECONDS after the
 * verification time, and be judged before
 * min(nextUpdate, thisUpdate + MAX_SIGNED_AGE_SECONDS). There is no expiry
 * grace. The request nonce is never reported as matching.
 */
class RawProofOcspClient : public IOcspHttpClient {
public:
    static constexpr time_t MAX_SIGNED_AGE_SECONDS = 86400;
    static constexpr time_t FUTURE_TOLERANCE_SECONDS = 60;
    // 9999-12-31T23:59:59Z; keeps every deadline sum far from time_t overflow.
    static constexpr time_t MAX_VERIFICATION_TIME = 253402300799;
    // The bundle codec and its limits are the journal's published RA-TLS
    // status-proof extension contract, version 1.
    static constexpr long BUNDLE_VERSION = 1;
    static constexpr size_t MAX_BUNDLE_BYTES = 16384;
    static constexpr size_t MAX_RESPONSES = 16;
    static constexpr size_t MAX_RESPONSE_BYTES = 2048;

    RawProofOcspClient() = default;

    Error get_ocsp_response(
        const nv_unique_ptr<X509>& subject_cert,
        const nv_unique_ptr<X509>& issuer_cert,
        const nv_unique_ptr<stack_st_X509>& intermediates,
        const nv_unique_ptr<X509_STORE>& trust_store,
        NvOcspResponse& out_ocsp_response
    ) override;

    /**
     * @brief Creates a client from complete DER OCSPResponse values.
     */
    static Error create(
        const std::vector<std::string>& responses,
        time_t verification_time,
        std::shared_ptr<RawProofOcspClient>& out_client
    );

    /**
     * @brief Creates a client from a version 1 status-proof bundle:
     * DER SEQUENCE { version INTEGER (1), responses SEQUENCE OF OCTET STRING }.
     */
    static Error create_from_bundle(
        const std::string& bundle_der,
        time_t verification_time,
        std::shared_ptr<RawProofOcspClient>& out_client
    );

    static Error decode_bundle(const std::string& bundle_der, std::vector<std::string>& out_responses);

private:
    std::vector<nv_unique_ptr<OCSP_BASICRESP>> m_responses;
    time_t m_verification_time = 0;
};

class NvHttpOcspCacheClient: public IOcspHttpClient {
public:
    NvHttpOcspCacheClient() = default;

    Error get_ocsp_response(
        const nv_unique_ptr<X509>& subject_cert,
        const nv_unique_ptr<X509>& issuer_cert,
        const nv_unique_ptr<stack_st_X509>& intermediates,
        const nv_unique_ptr<X509_STORE>& trust_store,
        NvOcspResponse& out_ocsp_response
    ) override;

    static Error create(
        std::shared_ptr<IOcspHttpClient>& inner_client,
        uint64_t max_size_bytes,
        time_t ttl_seconds,
        std::shared_ptr<IOcspHttpClient>& out_client
    );

    private:
    std::shared_ptr<IOcspHttpClient> m_inner_client;
    std::shared_ptr<INvCache> m_cache;

    /*
        approx size of one cache entry = key length + size of NvOcspResponse
        size of NvOcspResponse = approx 20 bytes
    */
    static constexpr const uint64_t NV_OCSP_RESPONSE_SIZE_BYTES = 20;

    static Error get_cache_key(
        const nv_unique_ptr<X509>& subject_cert,
        const nv_unique_ptr<X509>& issuer_cert,
        std::string& out_cache_key
    );

};
}
