/*
 * SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 * Modified by sol pbc.
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
#include <memory>
#include <string>
#include <vector>
#include <cstdint>

#include <nlohmann/json.hpp>
#include "nv_attestation/error.h"
#include "nv_attestation/log.h"
#include "nv_attestation/utils.h"
#include "nvat.h"

namespace nvattestation {


/**
 * @brief Represents certificate chain claims for attestation
 * 
 */
/**
 * @brief sol: signed-age status result for one certificate chain.
 *
 * Present only when the chain's revocation status came from raw signed OCSP
 * proofs judged against an owner-supplied verification time. It is
 * serialized as "x-sol-cert-ocsp-signed-age" beside a nonce-matches claim
 * that is always false.
 */
class SerializableSignedAgeStatus {
    public:
    static constexpr int VERSION = 1;
    int m_version;
    int64_t m_verification_time_unix;
    int64_t m_status_deadline_unix;
    int64_t m_oldest_this_update_unix;
    uint64_t m_covered_certificates;

    SerializableSignedAgeStatus()
        : m_version(VERSION)
        , m_verification_time_unix(0)
        , m_status_deadline_unix(0)
        , m_oldest_this_update_unix(0)
        , m_covered_certificates(0) {}
};

inline void to_json(nlohmann::json& j, const SerializableSignedAgeStatus& status) {
    j["version"] = status.m_version;
    j["mode"] = "signed-age";
    j["verification_time_unix"] = status.m_verification_time_unix;
    j["status_deadline_unix"] = status.m_status_deadline_unix;
    j["oldest_this_update_unix"] = status.m_oldest_this_update_unix;
    j["covered_certificates"] = status.m_covered_certificates;
}

inline void from_json(const nlohmann::json& j, SerializableSignedAgeStatus& out_status) {
    out_status.m_version = j.at("version").get<int>();
    out_status.m_verification_time_unix = j.at("verification_time_unix").get<int64_t>();
    out_status.m_status_deadline_unix = j.at("status_deadline_unix").get<int64_t>();
    out_status.m_oldest_this_update_unix = j.at("oldest_this_update_unix").get<int64_t>();
    out_status.m_covered_certificates = j.at("covered_certificates").get<uint64_t>();
}

inline std::shared_ptr<SerializableSignedAgeStatus> make_signed_age_status(
    bool signed_age,
    int64_t verification_time,
    int64_t status_deadline,
    int64_t oldest_this_update,
    uint64_t covered_certificates) {
    if (!signed_age) {
        return nullptr;
    }
    auto status = std::make_shared<SerializableSignedAgeStatus>();
    status->m_verification_time_unix = verification_time;
    status->m_status_deadline_unix = status_deadline;
    status->m_oldest_this_update_unix = oldest_this_update;
    status->m_covered_certificates = covered_certificates;
    return status;
}

class SerializableCertChainClaims {
    public:
    std::string m_cert_expiration_date;
    std::string m_cert_status;
    std::string m_cert_ocsp_status;
    std::shared_ptr<std::string> m_cert_revocation_reason;
    bool m_ocsp_nonce_matches;
    bool m_ocsp_response_valid;
    std::shared_ptr<SerializableSignedAgeStatus> m_ocsp_signed_age;

    SerializableCertChainClaims() 
        : m_cert_expiration_date("")
        , m_cert_status("")
        , m_cert_ocsp_status("")
        , m_cert_revocation_reason(nullptr)
        , m_ocsp_nonce_matches(false)
        , m_ocsp_response_valid(false)
        , m_ocsp_signed_age(nullptr) {}
};

/**
 * @brief Serializes SerializableCertChainClaims to JSON using nlohmann json ADL
 * @param j JSON object to populate
 * @param claims SerializableCertChainClaims object to serialize
 */
inline void to_json(nlohmann::json& j, const SerializableCertChainClaims& claims) {
    j["x-nvidia-cert-expiration-date"] = claims.m_cert_expiration_date;
    j["x-nvidia-cert-status"] = claims.m_cert_status;
    j["x-nvidia-cert-ocsp-status"] = claims.m_cert_ocsp_status;
    j["x-nvidia-cert-revocation-reason"] = serialize_optional_shared_ptr(claims.m_cert_revocation_reason.get());
    j["x-nvidia-cert-ocsp-nonce-matches"] = claims.m_ocsp_nonce_matches;
    j["x-nvidia-cert-ocsp-response-valid"] = claims.m_ocsp_response_valid;
    if (claims.m_ocsp_signed_age) {
        j["x-sol-cert-ocsp-signed-age"] = *claims.m_ocsp_signed_age;
    }
}

/* @brief Deserializes SerializableCertChainClaims from JSON
* @param j JSON object to read from
* @param out_claims SerializableCertChainClaims object to populate
* @return Error code
*/
inline void from_json(const nlohmann::json& j, SerializableCertChainClaims& out_claims) {
    out_claims.m_cert_expiration_date = j.at("x-nvidia-cert-expiration-date").get<std::string>();
    out_claims.m_cert_status = j.at("x-nvidia-cert-status").get<std::string>();
    out_claims.m_cert_ocsp_status = j.at("x-nvidia-cert-ocsp-status").get<std::string>();
    out_claims.m_cert_revocation_reason = deserialize_optional_shared_ptr<std::string>(j, "x-nvidia-cert-revocation-reason");
    // todo (p0): we are conditionally checking these fields because nras does implement 
    // them yet. in the remote verifier implementation, we try to deserialize the nras 
    // detached eat and if we do not conditionally check here, it will fail there.
    // once nras implements these fields, we should always expect these fields to be present.
    if (j.contains("x-nvidia-cert-ocsp-nonce-matches")) {
        out_claims.m_ocsp_nonce_matches = j.at("x-nvidia-cert-ocsp-nonce-matches").get<bool>();
    } else {
        out_claims.m_ocsp_nonce_matches = true;
    }
    if (j.contains("x-nvidia-cert-ocsp-response-valid")) {
        out_claims.m_ocsp_response_valid = j.at("x-nvidia-cert-ocsp-response-valid").get<bool>();
    } else {
        out_claims.m_ocsp_response_valid = true;
    }
    if (j.contains("x-sol-cert-ocsp-signed-age")) {
        out_claims.m_ocsp_signed_age = std::make_shared<SerializableSignedAgeStatus>(
            j.at("x-sol-cert-ocsp-signed-age").get<SerializableSignedAgeStatus>());
    } else {
        out_claims.m_ocsp_signed_age = nullptr;
    }
}

enum class SerializableMeasresClaim {
    Success,
    Failure,
    NotRun,
    Absent
};

NLOHMANN_JSON_SERIALIZE_ENUM(SerializableMeasresClaim, {
    {SerializableMeasresClaim::Success, "success"},
    {SerializableMeasresClaim::Failure, "fail"},
    {SerializableMeasresClaim::NotRun, "not-run"},
    {SerializableMeasresClaim::Absent, "absent"}
});

class SerializableMismatchedMeasurements {
    public: 
        enum class MeasurementSource {
            VBIOS,
            DRIVER
        };

        uint32_t m_index;
        uint32_t m_golden_size;
        std::string m_golden_value;
        uint32_t m_runtime_size;
        std::string m_runtime_value;
        MeasurementSource m_source;

        SerializableMismatchedMeasurements()
            : m_index(0)
            , m_golden_size(0)
            , m_golden_value("")
            , m_runtime_size(0)
            , m_runtime_value("")
            , m_source(MeasurementSource::VBIOS) // need to give a default value to satisfy the linter
        {}

        SerializableMismatchedMeasurements(uint32_t index, uint32_t golden_size, std::string golden_value, uint32_t runtime_size, std::string runtime_value, MeasurementSource source)
            : m_index(index)
            , m_golden_size(golden_size)
            , m_golden_value(golden_value)
            , m_runtime_size(runtime_size)
            , m_runtime_value(runtime_value)
            , m_source(source) {}

};

NLOHMANN_JSON_SERIALIZE_ENUM(SerializableMismatchedMeasurements::MeasurementSource, {
    {SerializableMismatchedMeasurements::MeasurementSource::VBIOS, "Firmware"},
    {SerializableMismatchedMeasurements::MeasurementSource::DRIVER, "Driver"}
})

inline void to_json(nlohmann::json& j, const SerializableMismatchedMeasurements& mismatched_measurements) {
    j["index"] = mismatched_measurements.m_index;
    j["goldenSize"] = mismatched_measurements.m_golden_size;
    j["goldenValue"] = mismatched_measurements.m_golden_value;
    j["runtimeSize"] = mismatched_measurements.m_runtime_size;
    j["runtimeValue"] = mismatched_measurements.m_runtime_value;
    j["measurementSource"] = mismatched_measurements.m_source;
}

inline void from_json(const nlohmann::json& j, SerializableMismatchedMeasurements& out_mismatched_measurements) {
    out_mismatched_measurements.m_index = j.at("index").get<uint32_t>();
    out_mismatched_measurements.m_golden_size = j.at("goldenSize").get<uint32_t>();
    out_mismatched_measurements.m_golden_value = j.at("goldenValue").get<std::string>();
    out_mismatched_measurements.m_runtime_size = j.at("runtimeSize").get<uint32_t>();
    out_mismatched_measurements.m_runtime_value = j.at("runtimeValue").get<std::string>();
    out_mismatched_measurements.m_source = j.at("measurementSource").get<SerializableMismatchedMeasurements::MeasurementSource>();
}

// Operator== for SerializableMismatchedMeasurements
inline bool operator==(const SerializableMismatchedMeasurements& lhs, const SerializableMismatchedMeasurements& rhs) {
    return lhs.m_index == rhs.m_index &&
           lhs.m_golden_size == rhs.m_golden_size &&
           lhs.m_golden_value == rhs.m_golden_value &&
           lhs.m_runtime_size == rhs.m_runtime_size &&
           lhs.m_runtime_value == rhs.m_runtime_value &&
           lhs.m_source == rhs.m_source;
}

// Operator== for SerializableCertChainClaims
bool operator==(const SerializableCertChainClaims& lhs, const SerializableCertChainClaims& rhs);

// todo (p0): remove after error claims are deprecated
class NrasErrorClaim {
    public:
        int code;
        std::string http_status;
        std::string description;
        std::string message;
};

inline void from_json(const nlohmann::json& j, NrasErrorClaim& out_nras_error) {
    out_nras_error.code = j.at("code").get<int>();
    out_nras_error.http_status = j.at("httpStatus").get<std::string>();
    out_nras_error.description = j.at("description").get<std::string>();
    out_nras_error.message = j.at("message").get<std::string>();
}

inline void to_json(nlohmann::json& j, const NrasErrorClaim& nras_error_claim) {
    j["code"] = nras_error_claim.code;
    j["httpStatus"] = nras_error_claim.http_status;
    j["description"] = nras_error_claim.description;
    j["message"] = nras_error_claim.message;
}

/**
 * @brief Virtual base class for claims
 * 
 */
class Claims {
    public:
        Claims() = default;
        virtual ~Claims() = default;
        virtual Error serialize_json(std::string& out_json) const = 0;
        // these functions are used to create the detached EAT
        virtual Error get_nonce(std::string& out_nonce) const = 0;
        virtual Error get_version(std::string& out_version) const = 0;
        virtual Error get_device_type(std::string& out_device_type) const = 0;
        // this is needed because Claims is a virtual class and when working with 
        // shared_ptr<Claims> it is not straightforward to define nlohmann json's 
        // adl (to_json and from_json)
        virtual nlohmann::json to_json_object() const = 0;
};

class DetachedEATOptions {
    public: 
        std::string m_private_key_pem = "";
        std::string m_issuer = "NVAT-LOCAL-VERIFIER";
        std::string m_kid = "";

        DetachedEATOptions() = default;
        ~DetachedEATOptions() = default;
};

class ClaimsCollection {
    public:
        ClaimsCollection() = default;
        ClaimsCollection(std::vector<std::shared_ptr<Claims>> claims) : m_claims(claims) {}
        ~ClaimsCollection() = default;

        Error serialize_json(std::string& out_json) const;
        Error get_detached_eat(
            std::string& out_json,
            const DetachedEATOptions& options
        ) const;
        void extend(ClaimsCollection other);
        void append(const std::shared_ptr<Claims>& claims);
        bool empty() const;
        size_t size() const;
        std::shared_ptr<Claims> operator[](size_t index);

        // because this function needs m_claims, which is private
        friend void to_json(nlohmann::json& j, const ClaimsCollection& claims);

    private:
        std::vector<std::shared_ptr<Claims>> m_claims;
};

void to_json(nlohmann::json& j, const ClaimsCollection& claims);
// claims common to payloads inside all JWTs
class SerializableCommonEATClaims {
    public: 
        std::int64_t m_iat;
        std::int64_t m_exp;
        std::string m_iss;
        std::string m_jti;
};

// payload inside the overall JWT token
class SerializableOverallEATClaims {
    public: 
        std::string m_sub;
        SerializableCommonEATClaims m_common_claims;

        std::string m_claims_version;
        std::unordered_map<std::string, std::string, std::hash<std::string>, std::equal_to<>> m_submod_digests;

        bool m_overall_result;
        std::string m_eat_nonce;
};

// payload inside the submod JWT tokens
class SerializableEATSubmodClaims {
    public: 
        SerializableCommonEATClaims m_common_claims;
        std::shared_ptr<Claims> m_device_claims;
};

// the entire detached EAT
class SerializableDetachedEAT {
      public: 
         // can be deserialized to SerializableOverallEATClaims
         std::string m_overall_jwt_token;
         // each element can be deserialized to SerializableEATSubmodClaims
         std::unordered_map<std::string, std::string, std::hash<std::string>, std::equal_to<>> m_device_jwt_tokens;
};

void to_json(nlohmann::json& j, const SerializableDetachedEAT& detached_eat);
void to_json(nlohmann::json& j, const SerializableOverallEATClaims& overall_claims);
void to_json(nlohmann::json& j, const SerializableEATSubmodClaims& submod_claims);
void to_json(nlohmann::json& j, const SerializableCommonEATClaims& out_common_claims);

void from_json(const nlohmann::json& j, SerializableDetachedEAT& detached_eat);
void from_json(const nlohmann::json& j, SerializableOverallEATClaims& overall_claims);
void from_json(const nlohmann::json& j, SerializableEATSubmodClaims& submod_claims);
void from_json(const nlohmann::json& j, SerializableCommonEATClaims& out_common_claims);
} // namespace nvattestation
