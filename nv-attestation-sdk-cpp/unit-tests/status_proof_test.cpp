/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 sol pbc
 * SPDX-License-Identifier: Apache-2.0
 *
 * sol: offline signed-age status proofs. Fixtures come from sol/test-fixtures/generate_status_proofs.py,
 * an independent Python `cryptography` producer.
 */

#include "gtest/gtest.h"

#include <fstream>
#include <iterator>
#include <memory>
#include <string>
#include <vector>

#include <openssl/objects.h>
#include <openssl/ocsp.h>
#include <openssl/x509.h>

#include "nv_attestation/claims.h"
#include "nv_attestation/error.h"
#include "nv_attestation/nv_ocsp.h"
#include "nv_attestation/nv_types.h"
#include "nv_attestation/nv_x509.h"
#include "nvat.h"

using namespace nvattestation;

namespace {

const std::string kDir = "testdata/status_proofs/";
// 2026-10-01T00:00:00Z, the fixtures' thisUpdate.
constexpr time_t kT0 = 1790812800;
constexpr time_t kDay = 86400;

std::string read_file(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    EXPECT_TRUE(file.good()) << path;
    return std::string((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
}

std::string cert(const std::string& name) { return read_file(kDir + name + ".pem"); }
std::string response(const std::string& name) { return read_file(kDir + "responses/" + name + ".der"); }
std::string bundle(const std::string& name) { return read_file(kDir + "bundles/" + name + ".der"); }

X509CertChain device_chain(const std::vector<std::string>& order) {
    X509CertChain chain;
    EXPECT_EQ(X509CertChain::create(CertificateChainType::GPU_DEVICE_IDENTITY, cert("root"), chain), Error::Ok);
    for (const auto& name : order) {
        EXPECT_EQ(chain.push_back(cert(name)), Error::Ok) << name;
    }
    return chain;
}

const std::vector<std::string> kPresented = {"leaf", "l4", "l3", "l2", "root"};

std::shared_ptr<RawProofOcspClient> proofs(const std::vector<std::string>& names, time_t verification_time) {
    std::vector<std::string> responses;
    for (const auto& name : names) {
        responses.push_back(response(name));
    }
    std::shared_ptr<RawProofOcspClient> client;
    EXPECT_EQ(RawProofOcspClient::create(responses, verification_time, client), Error::Ok);
    return client;
}

Error chain_claims(const X509CertChain& chain, IOcspHttpClient& client, CertChainClaims& out) {
    return chain.generate_cert_chain_claims(OcspVerifyOptions(), client, out);
}

const std::vector<std::string> kGood = {"good_l2", "good_l3", "good_l4"};

}  // namespace

// --- R2: strict raw-response verifier and truthful signed-age claims --------

TEST(RawProofTest, GoodProofsProduceSignedAgeClaimsWithoutANonceMatch) {
    X509CertChain chain = device_chain(kPresented);
    auto client = proofs({"good_l2", "good_l3", "good_l4", "unused_unrelated"}, kT0 + 3600);
    CertChainClaims claims;
    ASSERT_EQ(chain_claims(chain, *client, claims), Error::Ok);
    EXPECT_EQ(claims.ocsp_claims.status, OCSPStatus::GOOD);
    EXPECT_TRUE(claims.ocsp_claims.ocsp_response_valid);
    EXPECT_FALSE(claims.ocsp_claims.nonce_matches);
    EXPECT_TRUE(claims.ocsp_claims.signed_age);
    EXPECT_EQ(claims.ocsp_claims.verification_time, kT0 + 3600);
    EXPECT_EQ(claims.ocsp_claims.status_deadline, kT0 + kDay);
    EXPECT_EQ(claims.ocsp_claims.oldest_this_update, kT0);
    EXPECT_EQ(claims.ocsp_claims.covered_certificates, 3u);
}

TEST(RawProofTest, IssuerSignedResponseIsAuthorized) {
    X509CertChain chain = device_chain(kPresented);
    auto client = proofs({"good_l2", "good_l3", "good_l4_issuer_signed"}, kT0 + 60);
    CertChainClaims claims;
    ASSERT_EQ(chain_claims(chain, *client, claims), Error::Ok);
    EXPECT_EQ(claims.ocsp_claims.status, OCSPStatus::GOOD);
}

TEST(RawProofTest, UnauthorizedRespondersAndBadSignaturesYieldNoStatus) {
    for (const char* l4 : {
             "l4_wrong_issuer_responder",
             "l4_responder_without_eku",
             "l4_root_signer_without_eku",
             "l4_bad_signature",
         }) {
        X509CertChain chain = device_chain(kPresented);
        auto client = proofs({"good_l2", "good_l3", l4}, kT0 + 60);
        CertChainClaims claims;
        EXPECT_EQ(chain_claims(chain, *client, claims), Error::OcspInvalidResponse) << l4;
        EXPECT_NE(claims.ocsp_claims.status, OCSPStatus::GOOD) << l4;
    }
}

TEST(RawProofTest, AuxiliaryRootTrustWouldBeTheOnlyRouteForANonDelegatedSigner) {
    // Control: give the root explicit OCSP-signing trust and the root-issued
    // signer without the EKU is accepted. The production store loads plain
    // PEM anchors, so the same response is refused.
    nv_unique_ptr<X509> root = x509_from_cert_string(cert("root"));
    nv_unique_ptr<X509> l3 = x509_from_cert_string(cert("l3"));
    nv_unique_ptr<X509> l4 = x509_from_cert_string(cert("l4"));
    nv_unique_ptr<X509> l2 = x509_from_cert_string(cert("l2"));
    nv_unique_ptr<STACK_OF(X509)> intermediates(sk_X509_new_null());
    sk_X509_push(intermediates.get(), l3.get());
    sk_X509_push(intermediates.get(), l2.get());

    auto client = proofs({"l4_root_signer_without_eku"}, kT0 + 60);
    NvOcspResponse out{};
    nv_unique_ptr<X509_STORE> plain = create_trust_store(root.get());
    EXPECT_EQ(client->get_ocsp_response(l4, l3, intermediates, plain, out), Error::OcspInvalidResponse);

    nv_unique_ptr<X509> aux_root(X509_dup(root.get()));
    ASSERT_EQ(X509_add1_trust_object(aux_root.get(), OBJ_nid2obj(NID_OCSP_sign)), 1);
    nv_unique_ptr<X509_STORE> aux = create_trust_store(aux_root.get());
    EXPECT_EQ(client->get_ocsp_response(l4, l3, intermediates, aux, out), Error::Ok)
        << "control: the shortcut exists only with auxiliary root trust";
}

TEST(RawProofTest, SignedAgeBoundariesUseTheVerificationTime) {
    struct Case { std::string l4; time_t verification_time; bool accepted; time_t deadline; };
    const std::vector<Case> cases = {
        {"good_l4", kT0 - 60, true, kT0 + kDay},       // 60 s future tolerance
        {"good_l4", kT0 - 61, false, 0},
        {"good_l4", kT0 + kDay - 1, true, kT0 + kDay},
        {"good_l4", kT0 + kDay, false, 0},              // no expiry grace
        {"l4_next_48h", kT0 + kDay - 1, true, kT0 + kDay},  // capped at thisUpdate + 24 h
        {"l4_next_48h", kT0 + kDay, false, 0},
        {"l4_next_1h", kT0 + 3599, true, kT0 + 3600},
        {"l4_next_1h", kT0 + 3600, false, 0},
        {"l4_no_next_update", kT0 + 60, false, 0},
        {"l4_next_equals_this", kT0, false, 0},
    };
    for (const auto& c : cases) {
        X509CertChain chain = device_chain(kPresented);
        auto client = proofs({"good_l2", "good_l3", c.l4}, c.verification_time);
        CertChainClaims claims;
        Error error = chain_claims(chain, *client, claims);
        if (c.accepted) {
            ASSERT_EQ(error, Error::Ok) << c.l4 << " at " << c.verification_time;
            EXPECT_EQ(claims.ocsp_claims.status_deadline, c.deadline) << c.l4;
        } else {
            EXPECT_EQ(error, Error::OcspInvalidResponse) << c.l4 << " at " << c.verification_time;
        }
    }
}

TEST(RawProofTest, CoverageMustBeExactlyOnce) {
    const std::vector<std::vector<std::string>> sets = {
        {"good_l2", "good_l3"},                                // l4 missing
        {"good_l2", "good_l3", "good_l4", "good_l4"},          // duplicate
        {"good_l2", "good_l3", "good_l4", "l4_revoked"},       // conflicting
        {"good_l2", "good_l3", "good_l4", "l4_next_48h"},      // two GOOD versions
        {"good_l2", "good_l3", "l4_two_singles"},              // two SingleResponses in one
        {"unused_unrelated"},                                  // nothing required
    };
    for (const auto& set : sets) {
        X509CertChain chain = device_chain(kPresented);
        auto client = proofs(set, kT0 + 60);
        CertChainClaims claims;
        EXPECT_EQ(chain_claims(chain, *client, claims), Error::OcspInvalidResponse) << set.size();
    }
    // The hand-encoded control with one SingleResponse is accepted.
    X509CertChain chain = device_chain(kPresented);
    auto client = proofs({"good_l2", "good_l3", "l4_manual_single"}, kT0 + 60);
    CertChainClaims claims;
    EXPECT_EQ(chain_claims(chain, *client, claims), Error::Ok);
}

TEST(RawProofTest, NonGoodStatusesAreReportedTruthfully) {
    for (const auto& [l4, expected] : std::vector<std::pair<std::string, OCSPStatus>>{
             {"l4_revoked", OCSPStatus::REVOKED}, {"l4_unknown", OCSPStatus::UNKOWN}}) {
        X509CertChain chain = device_chain(kPresented);
        auto client = proofs({"good_l2", "good_l3", l4}, kT0 + 60);
        CertChainClaims claims;
        ASSERT_EQ(chain_claims(chain, *client, claims), Error::Ok) << l4;
        EXPECT_EQ(claims.ocsp_claims.status, expected) << l4;
        EXPECT_FALSE(claims.ocsp_claims.nonce_matches);
    }
}

TEST(RawProofTest, MalformedOrUnsuccessfulResponsesAreRefusedAtCreation) {
    for (const char* name : {"l4_trailing_byte", "try_later"}) {
        std::shared_ptr<RawProofOcspClient> client;
        EXPECT_EQ(RawProofOcspClient::create({response(name)}, kT0, client), Error::OcspInvalidResponse) << name;
        EXPECT_EQ(client, nullptr);
    }
    std::shared_ptr<RawProofOcspClient> client;
    EXPECT_EQ(RawProofOcspClient::create({}, kT0, client), Error::OcspInvalidResponse);
    EXPECT_EQ(RawProofOcspClient::create({std::string("\x30\x00", 2)}, kT0, client), Error::OcspInvalidResponse);
    EXPECT_EQ(RawProofOcspClient::create({response("good_l4")}, 0, client), Error::BadArgument);
}

// --- version 1 bundle codec -------------------------------------------------

TEST(RawProofBundleTest, GoodBundleDecodesToItsResponses) {
    std::vector<std::string> responses;
    ASSERT_EQ(RawProofOcspClient::decode_bundle(bundle("good"), responses), Error::Ok);
    ASSERT_EQ(responses.size(), 4u);
    EXPECT_EQ(responses[0], response("good_l2"));
    EXPECT_EQ(responses[2], response("good_l4"));
}

TEST(RawProofBundleTest, NonCanonicalOrOutOfBoundsBundlesAreRefused) {
    for (const char* name : {
             "version_2", "empty", "seventeen", "oversized_response", "trailing_byte",
             "version_non_minimal", "length_non_minimal", "indefinite_length", "item_not_octet_string"}) {
        std::vector<std::string> responses;
        EXPECT_EQ(RawProofOcspClient::decode_bundle(bundle(name), responses), Error::OcspInvalidResponse) << name;
        EXPECT_TRUE(responses.empty()) << name;
    }
    std::vector<std::string> responses;
    EXPECT_EQ(RawProofOcspClient::decode_bundle(std::string(RawProofOcspClient::MAX_BUNDLE_BYTES + 1, '\x30'), responses),
              Error::OcspInvalidResponse);
}

TEST(RawProofBundleTest, CApiConstructsOnlyFromABoundedBundleAndOwnerTime) {
    std::string good = bundle("good");
    nvat_ocsp_client_t client = nullptr;
    ASSERT_EQ(nvat_ocsp_client_create_raw_proofs(&client, reinterpret_cast<const uint8_t*>(good.data()), good.size(), kT0), NVAT_RC_OK);
    nvat_ocsp_client_free(&client);
    EXPECT_EQ(nvat_ocsp_client_create_raw_proofs(&client, reinterpret_cast<const uint8_t*>(good.data()), good.size(), 0), NVAT_RC_BAD_ARGUMENT);
    EXPECT_EQ(nvat_ocsp_client_create_raw_proofs(&client, nullptr, 0, kT0), NVAT_RC_BAD_ARGUMENT);
    std::string bad = bundle("version_2");
    EXPECT_EQ(nvat_ocsp_client_create_raw_proofs(&client, reinterpret_cast<const uint8_t*>(bad.data()), bad.size(), kT0), NVAT_RC_OCSP_INVALID_RESPONSE);
}

// --- serialized claims ---------------------------------------------------------

TEST(SignedAgeClaimTest, OnlySignedAgeChainsSerializeTheClaim) {
    SerializableCertChainClaims online;
    online.m_ocsp_nonce_matches = true;
    nlohmann::json online_json = online;
    EXPECT_FALSE(online_json.contains("x-sol-cert-ocsp-signed-age"));

    SerializableCertChainClaims offline;
    offline.m_ocsp_signed_age = make_signed_age_status(true, kT0, kT0 + kDay, kT0 - 10, 3);
    nlohmann::json offline_json = offline;
    ASSERT_TRUE(offline_json.contains("x-sol-cert-ocsp-signed-age"));
    const auto& claim = offline_json["x-sol-cert-ocsp-signed-age"];
    EXPECT_EQ(claim["version"], 1);
    EXPECT_EQ(claim["mode"], "signed-age");
    EXPECT_EQ(claim["verification_time_unix"], kT0);
    EXPECT_EQ(claim["status_deadline_unix"], kT0 + kDay);
    EXPECT_EQ(claim["oldest_this_update_unix"], kT0 - 10);
    EXPECT_EQ(claim["covered_certificates"], 3);
    EXPECT_EQ(offline_json["x-nvidia-cert-ocsp-nonce-matches"], false);
    EXPECT_EQ(make_signed_age_status(false, kT0, kT0, kT0, 1), nullptr);
}

// --- real NVIDIA proofs through the full local verifier -----------------------

namespace {

const std::string kNvidiaDir = kDir + "nvidia/";
// The earliest and latest thisUpdate among the captured responses.
constexpr time_t kNvidiaFirstThisUpdate = 1790993048;
constexpr time_t kNvidiaLastThisUpdate = 1790993049;

struct OfflineAttestation {
    nvat_rc_t rc = NVAT_RC_OK;
    nlohmann::json claims;
};

OfflineAttestation attest_offline(const std::string& bundle_der, int64_t verification_time, const std::string& nonce_hex) {
    OfflineAttestation result;
    nvat_attestation_ctx_t ctx = nullptr;
    nvat_rim_store_t rim_store = nullptr;
    nvat_ocsp_client_t ocsp_client = nullptr;
    nvat_nonce_t nonce = nullptr;
    nvat_str_t detached_eat = nullptr;
    nvat_claims_collection_t claims = nullptr;
    nvat_str_t serialized = nullptr;

    EXPECT_EQ(nvat_attestation_ctx_create(&ctx), NVAT_RC_OK);
    EXPECT_EQ(nvat_attestation_ctx_set_device_type(ctx, NVAT_DEVICE_GPU), NVAT_RC_OK);
    EXPECT_EQ(nvat_attestation_ctx_set_gpu_evidence_source_json_file(ctx, (kNvidiaDir + "gpu-evidence.json").c_str()), NVAT_RC_OK);
    EXPECT_EQ(nvat_rim_store_create_filesystem(&rim_store, (kNvidiaDir + "rims").c_str()), NVAT_RC_OK);
    EXPECT_EQ(nvat_attestation_ctx_set_default_rim_store(ctx, rim_store), NVAT_RC_OK);
    result.rc = nvat_ocsp_client_create_raw_proofs(
        &ocsp_client, reinterpret_cast<const uint8_t*>(bundle_der.data()), bundle_der.size(), verification_time);
    if (result.rc == NVAT_RC_OK) {
        EXPECT_EQ(nvat_attestation_ctx_set_default_ocsp_client(ctx, ocsp_client), NVAT_RC_OK);
        EXPECT_EQ(nvat_attestation_ctx_set_verifier_type(ctx, NVAT_VERIFY_LOCAL), NVAT_RC_OK);
        EXPECT_EQ(nvat_nonce_from_hex(&nonce, nonce_hex.c_str()), NVAT_RC_OK);
        result.rc = nvat_attest_device(ctx, nonce, &detached_eat, &claims);
        if (claims != nullptr && nvat_claims_collection_serialize_json(claims, &serialized) == NVAT_RC_OK) {
            char* data = nullptr;
            if (nvat_str_get_data(serialized, &data) == NVAT_RC_OK && data != nullptr) {
                result.claims = nlohmann::json::parse(data);
            }
        }
    }
    nvat_str_free(&serialized);
    nvat_claims_collection_free(&claims);
    nvat_str_free(&detached_eat);
    nvat_nonce_free(&nonce);
    nvat_ocsp_client_free(&ocsp_client);
    nvat_rim_store_free(&rim_store);
    nvat_attestation_ctx_free(&ctx);
    return result;
}

std::string evidence_nonce() {
    return nlohmann::json::parse(read_file(kNvidiaDir + "gpu-evidence.json"))[0]["nonce"].get<std::string>();
}

std::string nvidia_bundle_without(size_t skipped) {
    std::vector<std::string> responses;
    EXPECT_EQ(RawProofOcspClient::decode_bundle(read_file(kNvidiaDir + "bundle.der"), responses), Error::Ok);
    std::string items;
    for (size_t i = 0; i < responses.size(); ++i) {
        if (i == skipped) {
            continue;
        }
        const std::string& response = responses[i];
        items += '\x04';
        items += static_cast<char>(0x82);
        items += static_cast<char>((response.size() >> 8) & 0xff);
        items += static_cast<char>(response.size() & 0xff);
        items += response;
    }
    std::string list = std::string("\x30\x82", 2) + static_cast<char>((items.size() >> 8) & 0xff) + static_cast<char>(items.size() & 0xff) + items;
    std::string body = std::string("\x02\x01\x01", 3) + list;
    return std::string("\x30\x82", 2) + static_cast<char>((body.size() >> 8) & 0xff) + static_cast<char>(body.size() & 0xff) + body;
}

}  // namespace

TEST(NvidiaStatusProofTest, ProductionGpuAppraisesOfflineWithEveryLegSignedAge) {
    OfflineAttestation result = attest_offline(read_file(kNvidiaDir + "bundle.der"), kNvidiaLastThisUpdate + 3600, evidence_nonce());
    ASSERT_EQ(result.rc, NVAT_RC_OK);
    ASSERT_TRUE(result.claims.is_array());
    ASSERT_EQ(result.claims.size(), 1u);
    const auto& claim = result.claims[0];
    EXPECT_EQ(claim["eat_nonce"], evidence_nonce());
    for (const char* leg : {
             "x-nvidia-gpu-attestation-report-cert-chain",
             "x-nvidia-gpu-driver-rim-cert-chain",
             "x-nvidia-gpu-vbios-rim-cert-chain"}) {
        const auto& chain = claim[leg];
        EXPECT_EQ(chain["x-nvidia-cert-ocsp-status"], "good") << leg;
        EXPECT_EQ(chain["x-nvidia-cert-ocsp-nonce-matches"], false) << leg;
        const auto& signed_age = chain["x-sol-cert-ocsp-signed-age"];
        EXPECT_EQ(signed_age["version"], 1) << leg;
        EXPECT_EQ(signed_age["verification_time_unix"], kNvidiaLastThisUpdate + 3600) << leg;
        EXPECT_EQ(signed_age["status_deadline_unix"], kNvidiaFirstThisUpdate + kDay) << leg;
        EXPECT_EQ(signed_age["covered_certificates"], 3) << leg;
    }
}

TEST(NvidiaStatusProofTest, ExpiredFutureIncompleteProofsOrAWrongNonceReject) {
    const std::string bundle_der = read_file(kNvidiaDir + "bundle.der");
    EXPECT_EQ(attest_offline(bundle_der, kNvidiaFirstThisUpdate + kDay, evidence_nonce()).rc, NVAT_RC_OCSP_INVALID_RESPONSE);
    EXPECT_EQ(attest_offline(bundle_der, kNvidiaLastThisUpdate - 61, evidence_nonce()).rc, NVAT_RC_OCSP_INVALID_RESPONSE);
    EXPECT_EQ(attest_offline(bundle_der, kNvidiaLastThisUpdate - 60, evidence_nonce()).rc, NVAT_RC_OK);
    // Each of the seven proofs this GPU needs is required; the eighth, for
    // the other VBIOS signer, is not.
    for (size_t skipped = 0; skipped < 8; ++skipped) {
        nvat_rc_t rc = attest_offline(nvidia_bundle_without(skipped), kNvidiaLastThisUpdate + 60, evidence_nonce()).rc;
        if (skipped == 7) {
            EXPECT_EQ(rc, NVAT_RC_OK) << "unused inventory entry";
        } else {
            EXPECT_EQ(rc, NVAT_RC_OCSP_INVALID_RESPONSE) << skipped;
        }
    }
    std::string wrong_nonce = evidence_nonce();
    wrong_nonce[0] = wrong_nonce[0] == 'a' ? 'b' : 'a';
    EXPECT_NE(attest_offline(bundle_der, kNvidiaLastThisUpdate + 60, wrong_nonce).rc, NVAT_RC_OK);
}
