/*
 * SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <cstdlib>
#include <string>
#include <unistd.h>
#include <vector>

#include "gtest/gtest.h"
#include "nv_attestation/nv_http.h"

using namespace nvattestation;

namespace {

class EnvironmentGuard {
public:
    explicit EnvironmentGuard(std::vector<std::string> names) : names_(std::move(names)) {
        for (const auto& name : names_) {
            const char* value = std::getenv(name.c_str());
            values_.push_back(value == nullptr ? std::string() : std::string(value));
            was_set_.push_back(value != nullptr);
            unsetenv(name.c_str());
        }
    }

    ~EnvironmentGuard() {
        for (std::size_t i = 0; i < names_.size(); ++i) {
            if (was_set_[i]) {
                setenv(names_[i].c_str(), values_[i].c_str(), 1);
            } else {
                unsetenv(names_[i].c_str());
            }
        }
    }

private:
    std::vector<std::string> names_;
    std::vector<std::string> values_;
    std::vector<bool> was_set_;
};

class TemporaryFile {
public:
    TemporaryFile() {
        char path[] = "/tmp/nvat-ca-bundle-XXXXXX";
        int fd = mkstemp(path);
        EXPECT_NE(fd, -1);
        if (fd != -1) {
            close(fd);
            path_ = path;
        }
    }

    ~TemporaryFile() {
        if (!path_.empty()) {
            unlink(path_.c_str());
        }
    }

    const std::string& path() const { return path_; }

private:
    std::string path_;
};

class CaBundleResolutionTest : public ::testing::Test {
protected:
    EnvironmentGuard environment_{{"NVAT_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE"}};
};

} // namespace

TEST_F(CaBundleResolutionTest, ExplicitPathBeatsEveryEnvironmentTier) {
    TemporaryFile explicit_file;
    setenv("NVAT_CA_BUNDLE", "/missing-nvat-ca", 1);
    setenv("CURL_CA_BUNDLE", "/missing-curl-ca", 1);
    setenv("SSL_CERT_FILE", "/missing-ssl-ca", 1);

    std::string path;
    std::string tier;
    EXPECT_EQ(resolve_ca_bundle_path(explicit_file.path(), path, tier), Error::Ok);
    EXPECT_EQ(path, explicit_file.path());
    EXPECT_EQ(tier, "--ca-bundle");
}

TEST_F(CaBundleResolutionTest, NvatEnvironmentBeatsLowerEnvironmentTiers) {
    TemporaryFile nvat_file;
    setenv("NVAT_CA_BUNDLE", nvat_file.path().c_str(), 1);
    setenv("CURL_CA_BUNDLE", "/missing-curl-ca", 1);
    setenv("SSL_CERT_FILE", "/missing-ssl-ca", 1);

    std::string path;
    std::string tier;
    EXPECT_EQ(resolve_ca_bundle_path("", path, tier), Error::Ok);
    EXPECT_EQ(path, nvat_file.path());
    EXPECT_EQ(tier, "NVAT_CA_BUNDLE");
}

TEST_F(CaBundleResolutionTest, CurlEnvironmentBeatsSslEnvironment) {
    TemporaryFile curl_file;
    setenv("NVAT_CA_BUNDLE", "", 1);
    setenv("CURL_CA_BUNDLE", curl_file.path().c_str(), 1);
    setenv("SSL_CERT_FILE", "/missing-ssl-ca", 1);

    std::string path;
    std::string tier;
    EXPECT_EQ(resolve_ca_bundle_path("", path, tier), Error::Ok);
    EXPECT_EQ(path, curl_file.path());
    EXPECT_EQ(tier, "CURL_CA_BUNDLE");
}

TEST_F(CaBundleResolutionTest, SslEnvironmentBeatsDefaultsAndProbes) {
    TemporaryFile ssl_file;
    setenv("NVAT_CA_BUNDLE", "", 1);
    setenv("CURL_CA_BUNDLE", "", 1);
    setenv("SSL_CERT_FILE", ssl_file.path().c_str(), 1);

    std::string path;
    std::string tier;
    EXPECT_EQ(resolve_ca_bundle_path("", path, tier), Error::Ok);
    EXPECT_EQ(path, ssl_file.path());
    EXPECT_EQ(tier, "SSL_CERT_FILE");
}

TEST_F(CaBundleResolutionTest, EmptyValuesAreSkippedAtEveryExplicitAndEnvironmentTier) {
    TemporaryFile probe_file;
    setenv("NVAT_CA_BUNDLE", "", 1);
    setenv("CURL_CA_BUNDLE", "", 1);
    setenv("SSL_CERT_FILE", "", 1);

    std::string path;
    std::string tier;
    const std::string no_compiled_default;
    const std::vector<std::string> probes = {probe_file.path()};
    EXPECT_EQ(resolve_ca_bundle_path("", path, tier, &no_compiled_default, &probes), Error::Ok);
    EXPECT_EQ(path, probe_file.path());
    EXPECT_EQ(tier, "system CA bundle probe");
}

TEST_F(CaBundleResolutionTest, SystemProbeRunsWhenNoHigherTierResolves) {
    TemporaryFile probe_file;
    std::string path;
    std::string tier;
    const std::string no_compiled_default;
    const std::vector<std::string> probes = {"/missing-probe", probe_file.path()};
    EXPECT_EQ(resolve_ca_bundle_path("", path, tier, &no_compiled_default, &probes), Error::Ok);
    EXPECT_EQ(path, probe_file.path());
    EXPECT_EQ(tier, "system CA bundle probe");
}

TEST_F(CaBundleResolutionTest, CompiledDefaultBeatsSystemProbe) {
    TemporaryFile compiled_default;
    TemporaryFile probe_file;
    std::string path;
    std::string tier;
    const std::vector<std::string> probes = {probe_file.path()};
    EXPECT_EQ(resolve_ca_bundle_path("", path, tier, &compiled_default.path(), &probes), Error::Ok);
    EXPECT_EQ(path, compiled_default.path());
    EXPECT_EQ(tier, "libcurl compiled default");
}

TEST_F(CaBundleResolutionTest, MissingAuthoritativePathsFailWithPathAndTier) {
    const std::vector<std::pair<std::string, std::string>> cases = {
        {"--ca-bundle", "/missing-explicit-ca"},
        {"NVAT_CA_BUNDLE", "/missing-nvat-ca"},
        {"CURL_CA_BUNDLE", "/missing-curl-ca"},
        {"SSL_CERT_FILE", "/missing-ssl-ca"},
    };

    for (const auto& test_case : cases) {
        unsetenv("NVAT_CA_BUNDLE");
        unsetenv("CURL_CA_BUNDLE");
        unsetenv("SSL_CERT_FILE");
        std::string explicit_path;
        if (test_case.first == "--ca-bundle") {
            explicit_path = test_case.second;
        } else {
            setenv(test_case.first.c_str(), test_case.second.c_str(), 1);
        }

        std::string path;
        std::string tier;
        EXPECT_EQ(resolve_ca_bundle_path(explicit_path, path, tier), Error::InternalError);
        EXPECT_EQ(path, test_case.second);
        EXPECT_EQ(tier, test_case.first);
    }
}

TEST_F(CaBundleResolutionTest, MissingFullChainReturnsActionableError) {
    std::string path;
    std::string tier;
    const std::string no_compiled_default;
    const std::vector<std::string> no_probes;
    EXPECT_EQ(resolve_ca_bundle_path("", path, tier, &no_compiled_default, &no_probes), Error::InternalError);

    EXPECT_TRUE(path.empty());
    EXPECT_NE(tier.find("--ca-bundle"), std::string::npos);
    EXPECT_NE(tier.find("NVAT_CA_BUNDLE"), std::string::npos);
}
