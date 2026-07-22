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

#include <algorithm>
#include <array>
#include <curl/curl.h>
#include <memory>
#include <random>
#include <thread>
#include <chrono>
#include <sys/stat.h>
#include <unistd.h>

#include "nv_attestation/nv_http.h"
#include "nv_attestation/error.h"
#include "nv_attestation/log.h"
#include "nv_attestation/nv_types.h"
#include "nv_attestation/utils.h"

namespace nvattestation {

    namespace {

        const std::array<std::string, 5> CA_BUNDLE_PROBE_PATHS = {{
            std::string("/etc/") + "ssl/certs/ca-certificates.crt",
            std::string("/etc/") + "pki/tls/certs/ca-bundle.crt",
            std::string("/etc/") + "ssl/ca-bundle.pem",
            std::string("/etc/") + "ca-certificates/extracted/tls-ca-bundle.pem",
            std::string("/etc/") + "ssl/cert.pem",
        }};

        bool is_readable_regular_file(const std::string& path) {
            struct stat path_stat;
            return !path.empty()
                && stat(path.c_str(), &path_stat) == 0
                && S_ISREG(path_stat.st_mode)
                && access(path.c_str(), R_OK) == 0;
        }

        const std::string& compiled_default_ca_bundle_path() {
            static const std::string path = []() {
#if LIBCURL_VERSION_NUM >= 0x075400
                nv_unique_ptr<CURL> curl_handle(curl_easy_init());
                if (!curl_handle) {
                    return std::string();
                }
                char* ca_info = nullptr;
                CURLcode result = curl_easy_getinfo(curl_handle.get(), CURLINFO_CAINFO, &ca_info);
                if (result == CURLE_OK && ca_info != nullptr && *ca_info != '\0') {
                    return std::string(ca_info);
                }
#endif
                return std::string();
            }();
            return path;
        }

        Error use_authoritative_ca_bundle_path(
            const std::string& path,
            const char* tier,
            std::string& out_path,
            std::string& out_tier) {
            out_path = path;
            out_tier = tier;
            if (!is_readable_regular_file(path)) {
                return Error::InternalError;
            }
            return Error::Ok;
        }

    }

    Error resolve_ca_bundle_path(
        const std::string& explicit_path,
        std::string& out_path,
        std::string& out_tier,
        const std::string* compiled_default_override,
        const std::vector<std::string>* probe_paths_override) {
        out_path.clear();
        out_tier.clear();

        if (!explicit_path.empty()) {
            return use_authoritative_ca_bundle_path(explicit_path, "--ca-bundle", out_path, out_tier);
        }

        constexpr std::array<const char*, 3> environment_tiers = {{
            "NVAT_CA_BUNDLE",
            "CURL_CA_BUNDLE",
            "SSL_CERT_FILE",
        }};
        for (const char* environment_tier : environment_tiers) {
            std::string path = get_env_or_default(environment_tier, "");
            if (!path.empty()) {
                return use_authoritative_ca_bundle_path(path, environment_tier, out_path, out_tier);
            }
        }

        const std::string& compiled_default = compiled_default_override == nullptr
            ? compiled_default_ca_bundle_path()
            : *compiled_default_override;
        if (is_readable_regular_file(compiled_default)) {
            out_path = compiled_default;
            out_tier = "libcurl compiled default";
            return Error::Ok;
        }

        std::vector<std::string> default_probe_paths;
        if (probe_paths_override == nullptr) {
            default_probe_paths.assign(CA_BUNDLE_PROBE_PATHS.begin(), CA_BUNDLE_PROBE_PATHS.end());
        }
        const std::vector<std::string>& probe_paths = probe_paths_override == nullptr
            ? default_probe_paths
            : *probe_paths_override;
        for (const std::string& probe_path : probe_paths) {
            if (is_readable_regular_file(probe_path)) {
                out_path = probe_path;
                out_tier = "system CA bundle probe";
                return Error::Ok;
            }
        }

        out_tier = "no readable CA bundle; provide one with --ca-bundle or NVAT_CA_BUNDLE";
        return Error::InternalError;
    }

    Error NvHttpClient::create(NvHttpClient& out_client, std::string service_key, HttpOptions options) {
        out_client.m_service_key = std::move(service_key);
        out_client.m_options = options;

        return Error::Ok;
    }

    size_t NvHttpClient::curl_write_callback(void *contents, size_t size, size_t nmemb, void *userp) {
        auto totalSize = size * nmemb;
        auto* str = static_cast<std::string*>(userp);
        str->append(static_cast<char*>(contents), totalSize);
        return totalSize;
    }
    
    constexpr const long MILLIS_PER_SECOND = 1000;

    Error NvHttpClient::do_request_as_string(const NvRequest& request, long& out_status, std::string& out_response) const {
        out_response.clear();
        if (m_options.ca_bundle_path_error != Error::Ok || m_options.ca_bundle_path.empty()) {
            if (!m_options.ca_bundle_path.empty()) {
                LOG_ERROR("CA bundle path '" << m_options.ca_bundle_path << "' from "
                    << m_options.ca_bundle_path_tier
                    << " does not exist or is not readable; provide a readable file with --ca-bundle or NVAT_CA_BUNDLE.");
            } else {
                LOG_ERROR("No readable CA bundle was found; provide one with --ca-bundle or NVAT_CA_BUNDLE.");
            }
            return Error::InternalError;
        }
        /*
            todo (p0): optimize usage of curl handles

            use a thread local curl easy handle and then use a global curl share handle

            use curl share handle to share dns, ssl and cookies between curl easy handle

            this is the most performance we can get without using multi handle (async). 
            but exposing that to the client is pretty complex and an easier way would to 
            expose a http interface that the client can provide
        */ 
        nv_unique_ptr<CURL> curl_handle(curl_easy_init());

        curl_easy_reset(curl_handle.get());

        curl_easy_setopt(curl_handle.get(), CURLOPT_WRITEFUNCTION, curl_write_callback);
        curl_easy_setopt(curl_handle.get(), CURLOPT_WRITEDATA, &out_response);
        curl_easy_setopt(curl_handle.get(), CURLOPT_CONNECTTIMEOUT_MS, m_options.connection_timeout_ms);
        curl_easy_setopt(curl_handle.get(), CURLOPT_TIMEOUT_MS, m_options.request_timeout_ms);
        curl_easy_setopt(curl_handle.get(), CURLOPT_CAINFO, m_options.ca_bundle_path.c_str());

        curl_easy_setopt(curl_handle.get(), CURLOPT_URL, request.url.c_str());

        const char* method_str = nullptr;
        
        switch (request.method) {
            case NvHttpMethod::HTTP_METHOD_GET:
                method_str = "GET";
                break;
            case NvHttpMethod::HTTP_METHOD_POST:
                method_str = "POST";
                break;
            case NvHttpMethod::HTTP_METHOD_PUT:
                method_str = "PUT";
                break;
            case NvHttpMethod::HTTP_METHOD_DELETE:
                method_str = "DELETE";
                break;
        }
        curl_easy_setopt(curl_handle.get(), CURLOPT_CUSTOMREQUEST, method_str);

        curl_slist* headers_list_raw = nullptr;
        if(!request.headers.empty()) {
            for (const auto& header_pair : request.headers) {
                std::string header_string = header_pair.first + ": " + header_pair.second;
                headers_list_raw = curl_slist_append(headers_list_raw, header_string.c_str());
            }
            curl_easy_setopt(curl_handle.get(), CURLOPT_HTTPHEADER, headers_list_raw);
        }

        if (!m_service_key.empty()) {
            LOG_TRACE("Service key provided, adding Authorization header");
            std::string service_key_header = "Authorization: Bearer " + m_service_key;
            headers_list_raw = curl_slist_append(headers_list_raw, service_key_header.c_str());
        }

        nv_unique_ptr<curl_slist> headers_list(headers_list_raw);

        if(!request.payload.empty()) {
            curl_easy_setopt(curl_handle.get(), CURLOPT_POSTFIELDS, request.payload.c_str());
            curl_easy_setopt(curl_handle.get(), CURLOPT_POSTFIELDSIZE, request.payload.size());
        }

        // Retry up to max_retry_count times.
        // Uses full jitter to calculate backoff.
        Error last_error = Error::InternalError;
        long cur_try = 0;
        long backoff_ms = m_options.base_backoff_ms;
        // todo (p0): make this thread local
        std::mt19937_64 rng{std::random_device{}()}; // for randomized backoff
        do {
            bool is_last_attempt = cur_try == m_options.max_retry_count; // for logging only
            if (cur_try > 0) { // this is a retry
                out_response.clear();
                long full_jitter_backoff_ms = std::uniform_int_distribution<long>(0, backoff_ms)(rng);
                LOG_TRACE("Retrying with jittered backoff of " << full_jitter_backoff_ms << "ms (base: " << backoff_ms << "ms)");
                std::this_thread::sleep_for(std::chrono::milliseconds(full_jitter_backoff_ms));
                backoff_ms *= 2;
                backoff_ms = std::min(backoff_ms, m_options.max_backoff_ms);
            }
            cur_try++;
            CURLcode curl_code = curl_easy_perform(curl_handle.get());
            if (curl_code != CURLE_OK) {
                if (is_last_attempt) {
                    LOG_ERROR("Final libcurl error: " << curl_easy_strerror(curl_code) << " (" << curl_code << ")");
                }
                if (curl_code == CURLE_COULDNT_CONNECT 
                    || curl_code == CURLE_COULDNT_RESOLVE_HOST
                    || curl_code == CURLE_OPERATION_TIMEDOUT) {
                        LOG_DEBUG("Retryable libcurl error code: " << curl_easy_strerror(curl_code) << " (" << curl_code << ")");
                        continue;
                }
                LOG_ERROR("Fatal libcurl error code: " << curl_easy_strerror(curl_code) << " (" << curl_code << ")");
                return Error::InternalError;
            }

            curl_easy_getinfo(curl_handle.get(), CURLINFO_RESPONSE_CODE, &out_status);
            if (is_http_status_2xx(out_status)) {
                return Error::Ok; // true success, exit early
            }
            if (!is_http_retryable(out_status)) {
                LOG_ERROR("Non-retryable HTTP response code: " << out_status);
                return Error::Ok; // bad code, but cannot retry
            }
            // Technically OK because HTTP request succeeded.
            // Send another request to get a better response.
            last_error = Error::Ok; 
            if (is_last_attempt) {
                LOG_ERROR("Final HTTP status after retries: " << out_status);
            } else {
                LOG_DEBUG("Retryable HTTP response code from server: " << out_status);
                LOG_DEBUG("Failed HTTP response body: " << out_response);
            }
        } while (cur_try <= m_options.max_retry_count);
        LOG_ERROR("Gave up HTTP request after " << cur_try << " attempts");
        return last_error;
    }

}
