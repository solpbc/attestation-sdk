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

#include "nv_attestation/nv_ocsp.h"
#include "nv_attestation/nv_cache.h"
#include "nv_attestation/utils.h"
#include "nv_attestation/log.h"
#include "nv_attestation/error.h"
#include "internal/debug.hpp"

#include <algorithm>
#include <cstring>
#include <limits>


namespace nvattestation {

namespace {

Error asn1_time_to_unix(const ASN1_GENERALIZEDTIME* value, time_t& out_time) {
    struct tm value_tm{};
    if (value == nullptr || ASN1_TIME_to_tm(reinterpret_cast<const ASN1_TIME*>(value), &value_tm) != 1) {
        LOG_ERROR("Unable to convert ASN1_TIME to tm: " << get_openssl_error());
        return Error::OcspInvalidResponse;
    }
    // note: timegm is available on Linux and macOS, the supported targets.
    out_time = timegm(&value_tm);
    return Error::Ok;
}

}  // namespace

Error OcspResponseVerifier::parse_basic_response(
    const unsigned char* der,
    size_t der_len,
    nv_unique_ptr<OCSP_BASICRESP>& out_basic_response
) {
    if (der == nullptr || der_len == 0 || der_len > static_cast<size_t>(std::numeric_limits<long>::max())) {
        LOG_ERROR("OCSP response is empty or too large");
        return Error::OcspInvalidResponse;
    }
    const unsigned char* cursor = der;
    nv_unique_ptr<OCSP_RESPONSE> ocsp_resp(d2i_OCSP_RESPONSE(nullptr, &cursor, static_cast<long>(der_len)));
    if (!ocsp_resp) {
        LOG_ERROR("Failed to parse OCSP response: " << get_openssl_error());
        return Error::OcspInvalidResponse;
    }
    // sol: one complete DER value, nothing after it, and re-encoding gives
    // back the same bytes.
    if (cursor != der + der_len) {
        LOG_ERROR("OCSP response has trailing bytes");
        return Error::OcspInvalidResponse;
    }
    unsigned char* reencoded = nullptr;
    int reencoded_len = i2d_OCSP_RESPONSE(ocsp_resp.get(), &reencoded);
    bool canonical = reencoded_len > 0 && static_cast<size_t>(reencoded_len) == der_len
        && std::memcmp(reencoded, der, der_len) == 0;
    OPENSSL_free(reencoded);
    if (!canonical) {
        LOG_ERROR("OCSP response is not canonical DER");
        return Error::OcspInvalidResponse;
    }

    int response_status_val = OCSP_response_status(ocsp_resp.get());
    switch (response_status_val) {
        case OCSP_RESPONSE_STATUS_SUCCESSFUL:
        {
            nv_unique_ptr<OCSP_BASICRESP> basic_resp(OCSP_response_get1_basic(ocsp_resp.get()));
            if (!basic_resp) {
                LOG_ERROR("Could not extract basic response from OCSP response: " << get_openssl_error());
                return Error::OcspInvalidResponse;
            }
            // sol: the outer check above cannot see inside the responseBytes
            // OCTET STRING. Re-encode the whole response from the parsed
            // basic response so a non-canonical or padded inner value is
            // refused too.
            nv_unique_ptr<OCSP_RESPONSE> rebuilt(OCSP_response_create(OCSP_RESPONSE_STATUS_SUCCESSFUL, basic_resp.get()));
            unsigned char* rebuilt_der = nullptr;
            int rebuilt_len = rebuilt ? i2d_OCSP_RESPONSE(rebuilt.get(), &rebuilt_der) : -1;
            bool inner_canonical = rebuilt_len > 0 && static_cast<size_t>(rebuilt_len) == der_len
                && std::memcmp(rebuilt_der, der, der_len) == 0;
            OPENSSL_free(rebuilt_der);
            if (!inner_canonical) {
                LOG_ERROR("OCSP basic response is not canonical DER");
                return Error::OcspInvalidResponse;
            }
            out_basic_response = std::move(basic_resp);
            return Error::Ok;
        }
        case OCSP_RESPONSE_STATUS_INTERNALERROR:
        case OCSP_RESPONSE_STATUS_TRYLATER:
            LOG_ERROR("OCSP responder returned server error (status: " << response_status_val
                      << " - " << OCSP_response_status_str(response_status_val) << ").");
            return Error::OcspServerError;
        case OCSP_RESPONSE_STATUS_MALFORMEDREQUEST:
        case OCSP_RESPONSE_STATUS_SIGREQUIRED:
        case OCSP_RESPONSE_STATUS_UNAUTHORIZED:
        {
            std::string status_str = OCSP_response_status_str(response_status_val);
            LOG_ERROR("OCSP request failed due to client-side issue. Status: "
                      << response_status_val << " (" << status_str << ")");
            return Error::OcspInvalidRequest;
        }
        default:
        {
            std::string status_str = OCSP_response_status_str(response_status_val);
            LOG_ERROR("OCSP responder indicated a non-retryable error. Status: "
                      << response_status_val << " (" << status_str << ")");
            return Error::OcspInvalidResponse;
        }
    }
}

Error OcspResponseVerifier::verify_signature(
    OCSP_BASICRESP* basic_response,
    const nv_unique_ptr<stack_st_X509>& intermediates,
    const nv_unique_ptr<X509_STORE>& trust_store
) {
    if (basic_response == nullptr || !trust_store) {
        LOG_ERROR("OCSP signature verification is missing its response or trust store");
        return Error::InternalError;
    }

    if (get_logger()->should_log(LogLevel::DEBUG, __FILE__, __FUNCTION__, __LINE__)) {
        X509* signer_cert = nullptr;
        if (OCSP_resp_get0_signer(basic_response, &signer_cert, nullptr) != 0 && signer_cert != nullptr) {
            LOG_TRACE("Responder Cert Info: " << get_cert_subject_issuer_str(signer_cert));
        } else {
            LOG_TRACE("Could not retrieve responder certificate from OCSP response.");
        }
        LOG_TRACE("Intermediate Certs Provided for OCSP_basic_verify (" << sk_X509_num(intermediates.get()) << "):");
        for (int i = 0; i < sk_X509_num(intermediates.get()); ++i) {
            X509 *inter_cert = sk_X509_value(intermediates.get(), i);
            if (inter_cert != nullptr) {
                LOG_DEBUG("  Intermediate Cert [" << i << "]: " << get_cert_subject_issuer_str(inter_cert));
            }
        }
    }

    // Flags 0: the signer must be the CertID's issuer or be issued directly
    // by it with id-kp-OCSPSigning; the trust store holds plain anchors with
    // no auxiliary OCSP trust.
    int verification_status = OCSP_basic_verify(basic_response, intermediates.get(), trust_store.get(), 0);
    if (verification_status == 1) {
        LOG_DEBUG("OCSP basic verification successful");
        return Error::Ok;
    }
    if (verification_status == 0) {
        LOG_ERROR("OCSP response verification failed. OpenSSL errors: " << get_openssl_error());
        return Error::OcspInvalidResponse;
    }
    LOG_ERROR("OCSP basic verification encountered an internal error with status: "
            << verification_status << ". OpenSSL errors: " << get_openssl_error());
    return Error::InternalError;
}

size_t OcspResponseVerifier::count_single_responses(OCSP_BASICRESP* basic_response, OCSP_CERTID* id) {
    if (basic_response == nullptr || id == nullptr) {
        return 0;
    }
    size_t matches = 0;
    int count = OCSP_resp_count(basic_response);
    for (int i = 0; i < count; ++i) {
        OCSP_SINGLERESP* single = OCSP_resp_get0(basic_response, i);
        if (single == nullptr) {
            continue;
        }
        const OCSP_CERTID* single_id = OCSP_SINGLERESP_get0_id(single);
        if (single_id != nullptr && OCSP_id_cmp(single_id, id) == 0) {
            matches++;
        }
    }
    return matches;
}

Error OcspResponseVerifier::get_single_status(
    OCSP_BASICRESP* basic_response,
    OCSP_CERTID* id,
    int& out_status,
    int& out_reason,
    time_t& out_this_update,
    bool& out_has_next_update,
    time_t& out_next_update
) {
    size_t matches = count_single_responses(basic_response, id);
    if (matches != 1) {
        LOG_ERROR("OCSP response must carry exactly one status for the certificate, found " << matches);
        return Error::OcspInvalidResponse;
    }
    int index = OCSP_resp_find(basic_response, id, -1);
    OCSP_SINGLERESP* single = index < 0 ? nullptr : OCSP_resp_get0(basic_response, index);
    if (single == nullptr) {
        LOG_ERROR("OCSP status for the certificate could not be located");
        return Error::OcspInvalidResponse;
    }
    // Internal pointers of the response; freed with it.
    int reason = -1;
    ASN1_GENERALIZEDTIME* revtime = nullptr;
    ASN1_GENERALIZEDTIME* thisupd = nullptr;
    ASN1_GENERALIZEDTIME* nextupd = nullptr;
    int status = OCSP_single_get0_status(single, &reason, &revtime, &thisupd, &nextupd);
    if (status < 0) {
        LOG_ERROR("OCSP single response status could not be read: " << get_openssl_error());
        return Error::OcspInvalidResponse;
    }
    Error error = asn1_time_to_unix(thisupd, out_this_update);
    if (error != Error::Ok) {
        return error;
    }
    out_has_next_update = nextupd != nullptr;
    out_next_update = 0;
    if (out_has_next_update) {
        error = asn1_time_to_unix(nextupd, out_next_update);
        if (error != Error::Ok) {
            return error;
        }
    }
    out_status = status;
    out_reason = reason;
    return Error::Ok;
}

Error NvHttpOcspClient::get_ocsp_response(
    const nv_unique_ptr<X509>& subject_cert,
    const nv_unique_ptr<X509>& issuer_cert,
    const nv_unique_ptr<stack_st_X509>& intermediates,
    const nv_unique_ptr<X509_STORE>& trust_store,
    NvOcspResponse& out_ocsp_response
) {
    nv_unique_ptr<OCSP_REQUEST> ocsp_req(OCSP_REQUEST_new());
    if (OCSP_request_add1_nonce(ocsp_req.get(), nullptr, -1) != 1) {
        LOG_ERROR("Unable to add nonce to ocsp request");
        return Error::InternalError;
    }
    // Create the original Cert ID
    nv_unique_ptr<OCSP_CERTID> id_orig (OCSP_cert_to_id(EVP_sha1(), subject_cert.get(), issuer_cert.get()));
    if (!id_orig) {
            LOG_ERROR("Unable to create OCSP_CERTID: " << get_openssl_error());
            return Error::InternalError;
    }
    // Duplicate the Cert ID for the request
    // We duplicate the ID because OCSP_request_add0_id takes ownership of the ID
    // The original ID is used by the caller to get ocsp status of the cert
    // from the ocsp response
    OCSP_CERTID *id_for_req = OCSP_CERTID_dup(id_orig.get());
    if (id_for_req == nullptr) {
        LOG_ERROR("Unable to duplicate OCSP_CERTID: " << get_openssl_error());
        return Error::InternalError;
    }

    // Add the duplicated ID to the request (OCSP_request_add0_id takes ownership of id_for_req)
    if (OCSP_request_add0_id(ocsp_req.get(), id_for_req) == nullptr) {
            // If adding fails, we need to free the duplicated ID manually
            OCSP_CERTID_free(id_for_req);
            LOG_ERROR("Unable to add subject to ocsp request");
            return Error::InternalError;
    }

    // Serialize the OCSP request to a memory BIO
    nv_unique_ptr<BIO> req_bio(BIO_new(BIO_s_mem()));
    if (!req_bio) {
        LOG_ERROR("Unable to create memory BIO for OCSP request: " << get_openssl_error());
        return Error::InternalError;
    }
    if (!i2d_OCSP_REQUEST_bio(req_bio.get(), ocsp_req.get())) {
        LOG_ERROR("Unable to serialize OCSP request to BIO: " << get_openssl_error());
        return Error::InternalError;
    }
    // Get serialized OCSP request data from the BIO
    const unsigned char *req_data_ptr = nullptr;
    long req_data_len_l = BIO_get_mem_data(req_bio.get(), &req_data_ptr);
    if (req_data_len_l <= 0 || req_data_ptr == nullptr) {
        LOG_ERROR("Unable to get serialized OCSP request data from BIO (length=" << req_data_len_l << "): " << get_openssl_error());
        return Error::InternalError;
    }
    int req_data_len = static_cast<int>(req_data_len_l);
    if (req_data_len < 0) { // Downcast and check for overflow
        LOG_ERROR("Serialized OCSP request length is too large: encountered integer overflow " << req_data_len_l);
        return Error::InternalError;
    }

    // Create the request payload as a string
    std::string request_payload(reinterpret_cast<const char*>(req_data_ptr), req_data_len);

    // Create HTTP request
    NvRequest request(
        m_ocsp_url,
        NvHttpMethod::HTTP_METHOD_POST,
        {{"Content-Type", "application/ocsp-request"},
        {"Accept", "application/ocsp-response"},
        {"User-Agent", "nv-attestation-sdk/" NVAT_VERSION_STRING}},
        request_payload
    );

    // Perform HTTP request
    long http_status = 0;
    std::string response_body;
    Error error = m_http_client.do_request_as_string(request, http_status, response_body);
    if (error != Error::Ok) {
        LOG_ERROR("Failed to perform OCSP check with url: " << m_ocsp_url);
        return error;
    }

    // Check HTTP status
    if (http_status != HTTP_STATUS_OK) {
        LOG_ERROR("OCSP server returned HTTP status: " << http_status);
        if (http_status == HTTP_STATUS_FORBIDDEN || http_status == HTTP_STATUS_UNAUTHORIZED) {
            return Error::OcspForbidden;
        }
        return Error::OcspServerError;
    }

    // Parse the response into OCSP_RESPONSE
    if (response_body.empty()) {
        LOG_ERROR("Empty OCSP response received");
        return Error::OcspInvalidResponse;
    }

    nv_unique_ptr<OCSP_BASICRESP> openssl_ocsp_resp;
    error = OcspResponseVerifier::parse_basic_response(
        reinterpret_cast<const unsigned char*>(response_body.data()), response_body.size(), openssl_ocsp_resp);
    if (error != Error::Ok) {
        return error;
    }

    // sol: an invalid signature is an error and yields no status.
    error = OcspResponseVerifier::verify_signature(openssl_ocsp_resp.get(), intermediates, trust_store);
    if (error != Error::Ok) {
        return error;
    }
    out_ocsp_response.response_valid = true;

    // see here for information about return values of the check nonce function:  https://docs.openssl.org/1.1.1/man3/OCSP_check_nonce.html
    int result = OCSP_check_nonce(ocsp_req.get(), openssl_ocsp_resp.get());
    LOG_DEBUG("OCSP_check_nonce returned: " << result);
    out_ocsp_response.nonce_matches = result == 1;

    int status = -1;
    int reason = -1;
    time_t this_update_time = 0;
    bool has_next_update = false;
    time_t next_update_time = 0;
    error = OcspResponseVerifier::get_single_status(
        openssl_ocsp_resp.get(), id_orig.get(), status, reason, this_update_time, has_next_update, next_update_time);
    if (error != Error::Ok) {
        return error;
    }
    out_ocsp_response.thisupd = this_update_time;
    if (has_next_update) {
        out_ocsp_response.nextupd = next_update_time;
    } else {
        LOG_DEBUG("nextUpdate is absent in OCSP response, using default TTL");
        out_ocsp_response.nextupd = this_update_time + NvHttpOcspClient::DEFAULT_NEXT_UPDATE_TTL_SECONDS;
    }
    out_ocsp_response.status = status;
    out_ocsp_response.reason = reason;
    out_ocsp_response.signed_age = false;
    return Error::Ok;
}

Error NvHttpOcspClient::create(
    NvHttpOcspClient& out_client,
    const std::string& base_url,
    const std::string& service_key,
    const HttpOptions& http_options) {
    out_client.m_http_options = http_options;
    out_client.m_ocsp_url = base_url;
    Error error = NvHttpClient::create(out_client.m_http_client, service_key, http_options);
    if (error != Error::Ok) {
        LOG_ERROR("Failed to create HTTP client for OCSP request");
        return error;
    }
    return Error::Ok;
}

Error NvHttpOcspClient::init_from_env(
    NvHttpOcspClient& out_client,
    const char* base_url,
    const std::string& service_key,
    const HttpOptions& http_options) {
    std::string base_uri_str;
    if (base_url == nullptr || *base_url == '\0') {
        base_uri_str = get_env_or_default("NVAT_OCSP_BASE_URL", DEFAULT_BASE_URL);
    } else {
        base_uri_str = std::string(base_url);
    }

    return create(out_client, base_uri_str, service_key, http_options);
}

namespace {

// Strict DER length: definite, minimal, at most two length octets (the
// bundle limit fits in two).
bool read_der_length(const std::string& data, size_t& offset, size_t& out_length) {
    if (offset >= data.size()) {
        return false;
    }
    unsigned char first = static_cast<unsigned char>(data[offset++]);
    if (first < 0x80) {
        out_length = first;
        return true;
    }
    size_t count = first & 0x7f;
    if (count == 0 || count > 2 || offset + count > data.size()) {
        return false;
    }
    size_t value = 0;
    for (size_t i = 0; i < count; ++i) {
        value = (value << 8) | static_cast<unsigned char>(data[offset + i]);
    }
    if (static_cast<unsigned char>(data[offset]) == 0 || value < 0x80) {
        return false;
    }
    offset += count;
    out_length = value;
    return true;
}

bool read_der_tlv(const std::string& data, size_t& offset, size_t limit, unsigned char tag, size_t& out_start, size_t& out_length) {
    if (offset >= limit || static_cast<unsigned char>(data[offset]) != tag) {
        return false;
    }
    offset++;
    size_t length = 0;
    if (!read_der_length(data, offset, length) || offset > limit || length > limit - offset) {
        return false;
    }
    out_start = offset;
    out_length = length;
    offset += length;
    return true;
}

}  // namespace

Error RawProofOcspClient::decode_bundle(const std::string& bundle_der, std::vector<std::string>& out_responses) {
    out_responses.clear();
    if (bundle_der.empty() || bundle_der.size() > MAX_BUNDLE_BYTES) {
        LOG_ERROR("Status proof bundle is empty or larger than " << MAX_BUNDLE_BYTES << " bytes");
        return Error::OcspInvalidResponse;
    }
    size_t offset = 0;
    size_t body_start = 0;
    size_t body_length = 0;
    if (!read_der_tlv(bundle_der, offset, bundle_der.size(), 0x30, body_start, body_length)
        || offset != bundle_der.size()) {
        LOG_ERROR("Status proof bundle is not one DER SEQUENCE");
        return Error::OcspInvalidResponse;
    }
    size_t body_end = body_start + body_length;
    size_t cursor = body_start;
    size_t version_start = 0;
    size_t version_length = 0;
    if (!read_der_tlv(bundle_der, cursor, body_end, 0x02, version_start, version_length)
        || version_length != 1
        || static_cast<unsigned char>(bundle_der[version_start]) != BUNDLE_VERSION) {
        LOG_ERROR("Status proof bundle version is not 1");
        return Error::OcspInvalidResponse;
    }
    size_t list_start = 0;
    size_t list_length = 0;
    if (!read_der_tlv(bundle_der, cursor, body_end, 0x30, list_start, list_length) || cursor != body_end) {
        LOG_ERROR("Status proof bundle responses are not one DER SEQUENCE");
        return Error::OcspInvalidResponse;
    }
    size_t list_end = list_start + list_length;
    size_t item = list_start;
    std::vector<std::string> responses;
    while (item < list_end) {
        if (responses.size() >= MAX_RESPONSES) {
            LOG_ERROR("Status proof bundle carries more than " << MAX_RESPONSES << " responses");
            return Error::OcspInvalidResponse;
        }
        size_t response_start = 0;
        size_t response_length = 0;
        if (!read_der_tlv(bundle_der, item, list_end, 0x04, response_start, response_length)
            || response_length == 0 || response_length > MAX_RESPONSE_BYTES) {
            LOG_ERROR("Status proof bundle response is not a bounded OCTET STRING");
            return Error::OcspInvalidResponse;
        }
        responses.emplace_back(bundle_der.substr(response_start, response_length));
    }
    if (responses.empty()) {
        LOG_ERROR("Status proof bundle is empty");
        return Error::OcspInvalidResponse;
    }
    out_responses = std::move(responses);
    return Error::Ok;
}

Error RawProofOcspClient::create(
    const std::vector<std::string>& responses,
    time_t verification_time,
    std::shared_ptr<RawProofOcspClient>& out_client
) {
    if (responses.empty() || responses.size() > MAX_RESPONSES) {
        LOG_ERROR("Raw status proofs must contain between 1 and " << MAX_RESPONSES << " responses");
        return Error::OcspInvalidResponse;
    }
    if (verification_time <= 0 || verification_time > MAX_VERIFICATION_TIME) {
        LOG_ERROR("Raw status proofs need a verification time between 1970 and 9999");
        return Error::BadArgument;
    }
    auto client = std::make_shared<RawProofOcspClient>();
    client->m_verification_time = verification_time;
    for (const auto& response : responses) {
        if (response.empty() || response.size() > MAX_RESPONSE_BYTES) {
            LOG_ERROR("Raw status proof is empty or larger than " << MAX_RESPONSE_BYTES << " bytes");
            return Error::OcspInvalidResponse;
        }
        nv_unique_ptr<OCSP_BASICRESP> basic_response;
        Error error = OcspResponseVerifier::parse_basic_response(
            reinterpret_cast<const unsigned char*>(response.data()), response.size(), basic_response);
        if (error != Error::Ok) {
            // A refused or malformed proof is never a reason to ask anyone else.
            return Error::OcspInvalidResponse;
        }
        client->m_responses.push_back(std::move(basic_response));
    }
    out_client = std::move(client);
    return Error::Ok;
}

Error RawProofOcspClient::create_from_bundle(
    const std::string& bundle_der,
    time_t verification_time,
    std::shared_ptr<RawProofOcspClient>& out_client
) {
    std::vector<std::string> responses;
    Error error = decode_bundle(bundle_der, responses);
    if (error != Error::Ok) {
        return error;
    }
    return create(responses, verification_time, out_client);
}

Error RawProofOcspClient::get_ocsp_response(
    const nv_unique_ptr<X509>& subject_cert,
    const nv_unique_ptr<X509>& issuer_cert,
    const nv_unique_ptr<stack_st_X509>& intermediates,
    const nv_unique_ptr<X509_STORE>& trust_store,
    NvOcspResponse& out_ocsp_response
) {
    if (!subject_cert || !issuer_cert) {
        LOG_ERROR("Raw status proof lookup needs a subject and issuer certificate");
        return Error::InternalError;
    }
    nv_unique_ptr<OCSP_CERTID> id(OCSP_cert_to_id(EVP_sha1(), subject_cert.get(), issuer_cert.get()));
    if (!id) {
        LOG_ERROR("Unable to create OCSP_CERTID: " << get_openssl_error());
        return Error::InternalError;
    }

    size_t coverage = 0;
    OCSP_BASICRESP* covering = nullptr;
    for (const auto& response : m_responses) {
        size_t matches = OcspResponseVerifier::count_single_responses(response.get(), id.get());
        coverage += matches;
        if (matches > 0 && covering == nullptr) {
            covering = response.get();
        }
    }
    if (coverage != 1) {
        LOG_ERROR("Raw status proofs must cover the certificate exactly once, found " << coverage
                << " for " << get_cert_subject_issuer_str(subject_cert.get()));
        return Error::OcspInvalidResponse;
    }

    Error error = OcspResponseVerifier::verify_signature(covering, intermediates, trust_store);
    if (error != Error::Ok) {
        return error;
    }

    int status = -1;
    int reason = -1;
    time_t this_update = 0;
    bool has_next_update = false;
    time_t next_update = 0;
    error = OcspResponseVerifier::get_single_status(
        covering, id.get(), status, reason, this_update, has_next_update, next_update);
    if (error != Error::Ok) {
        return error;
    }
    if (!has_next_update) {
        LOG_ERROR("Raw status proof has no nextUpdate");
        return Error::OcspInvalidResponse;
    }
    if (next_update <= this_update) {
        LOG_ERROR("Raw status proof nextUpdate is not after thisUpdate");
        return Error::OcspInvalidResponse;
    }
    if (this_update - FUTURE_TOLERANCE_SECONDS > m_verification_time) {
        LOG_ERROR("Raw status proof thisUpdate is more than " << FUTURE_TOLERANCE_SECONDS
                << " seconds after the verification time");
        return Error::OcspInvalidResponse;
    }
    time_t deadline = std::min(next_update, this_update + MAX_SIGNED_AGE_SECONDS);
    if (m_verification_time >= deadline) {
        LOG_ERROR("Raw status proof expired before the verification time");
        return Error::OcspInvalidResponse;
    }

    out_ocsp_response.thisupd = this_update;
    out_ocsp_response.nextupd = next_update;
    out_ocsp_response.status = status;
    out_ocsp_response.reason = reason;
    out_ocsp_response.nonce_matches = false;
    out_ocsp_response.response_valid = true;
    out_ocsp_response.signed_age = true;
    out_ocsp_response.verification_time = m_verification_time;
    out_ocsp_response.status_deadline = deadline;
    return Error::Ok;
}

Error NvHttpOcspCacheClient::create(
    std::shared_ptr<IOcspHttpClient>& inner_client,
    uint64_t max_size_bytes,
    time_t ttl_seconds,
    std::shared_ptr<IOcspHttpClient>& out_client
) {
    std::shared_ptr<NvHttpOcspCacheClient> cache_client = std::make_shared<NvHttpOcspCacheClient>();
    cache_client->m_inner_client = std::move(inner_client);
    cache_client->m_cache = std::make_shared<NvCache>(std::make_shared<NvCacheOptions>(max_size_bytes, ttl_seconds));
    out_client = std::move(cache_client);
    return Error::Ok;
}

Error NvHttpOcspCacheClient::get_ocsp_response(
    const nv_unique_ptr<X509>& subject_cert,
    const nv_unique_ptr<X509>& issuer_cert,
    const nv_unique_ptr<stack_st_X509>& intermediates,
    const nv_unique_ptr<X509_STORE>& trust_store,
    NvOcspResponse& out_ocsp_response
) {
    std::string key;
    Error error = get_cache_key(subject_cert, issuer_cert, key);
    if (error != Error::Ok) {
        return error;
    }
    LOG_TRACE("Getting cached OCSP response for key: " << key);
    std::shared_ptr<void> ocsp_resp_cache_ptr;
    std::shared_ptr<NvOcspResponse> ocsp_resp_cache;
    error = m_cache->get(key, ocsp_resp_cache_ptr);
    if (error != Error::Ok && error != Error::CacheObjectNotFound) {
        return error;
    }
    bool should_refresh = false;
    if (error == Error::CacheObjectNotFound) {
        LOG_TRACE("OCSP response not found in cache, refreshing");
        should_refresh = true;
    } else {
        ocsp_resp_cache = std::static_pointer_cast<NvOcspResponse>(ocsp_resp_cache_ptr);
        if (ocsp_resp_cache->nextupd < time(nullptr)) {
            LOG_TRACE("OCSP next update time is in the past, refreshing");
            should_refresh = true;
        }
    }

    if (should_refresh) {
        LOG_TRACE("Refreshing OCSP response");
        error = m_inner_client->get_ocsp_response(subject_cert, issuer_cert, intermediates, trust_store, out_ocsp_response);
        if (error != Error::Ok) {
            return error;
        }
        error = m_cache->put(key, std::make_shared<NvOcspResponse>(out_ocsp_response), NvHttpOcspCacheClient::NV_OCSP_RESPONSE_SIZE_BYTES+key.size());
        if (error != Error::Ok) {
            return error;
        }
        return Error::Ok;
    }
    LOG_TRACE("OCSP response found in cache, returning");
    out_ocsp_response = *ocsp_resp_cache;
    return Error::Ok;
}

Error NvHttpOcspCacheClient::get_cache_key(
    const nv_unique_ptr<X509>& subject_cert,
    const nv_unique_ptr<X509>& issuer_cert,
    std::string& out_cache_key
) {
    nv_unique_ptr<OCSP_CERTID> id(OCSP_cert_to_id(EVP_sha1(), subject_cert.get(), issuer_cert.get()));
    if (!id) {
        LOG_ERROR("Unable to create OCSP_CERTID: " << get_openssl_error());
        return Error::InternalError;
    }
    unsigned char *cert_id_data = nullptr;
    int der_len = i2d_OCSP_CERTID(id.get(), &cert_id_data);
    if (der_len <= 0) {
        LOG_ERROR("Unable to serialize OCSP_CERTID to DER: " << get_openssl_error());
        return Error::InternalError;
    }
    out_cache_key = std::string(reinterpret_cast<const char*>(cert_id_data), der_len);
    OPENSSL_free(cert_id_data);
    return Error::Ok;
}
}
