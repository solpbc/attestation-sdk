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

#include "nvat.h"
#include <iostream>
#include <string>
#include "CLI/CLI.hpp"
#include "version.h"
#include "attest.h"
#include "collect_evidence.h"
#include "nvattest_options.h"
#include "utils.h"
#include "logging.h"

#include "spdlog/spdlog.h"
#include "spdlog/sinks/stdout_sinks.h"


#ifdef NVAT_VERIFICATION_ONLY
// sol: a verification-only build appraises evidence files and never collects
// evidence from local hardware, so it refuses any request that would.
static bool requests_hardware_collection(
    const CLI::App* attest_subcommand,
    const CLI::App* collect_evidence_subcommand,
    const nvattest::EvidenceCollectionOptions& collection,
    const nvattest::EvidenceVerificationOptions& verification) {
    if (collect_evidence_subcommand->parsed()) {
        return true;
    }
    if (!attest_subcommand->parsed()) {
        return false;
    }
    if (verification.verifier != "local") {
        return true;
    }
    if (collection.device == "gpu") {
        return collection.gpu_evidence_source != "file";
    }
    if (collection.device == "nvswitch") {
        return collection.switch_evidence_source != "file";
    }
    return true;
}
#endif

int main(int argc, char** argv) {

#ifdef _WIN32
    // sol: CLI11 converts the UTF-16 command line to UTF-8 so non-ASCII paths
    // survive regardless of the process code page.
    CLI::App utf8_arguments;
    argv = utf8_arguments.ensure_utf8(argv);
#endif

    CLI::App app{"NVIDIA attestation CLI for collecting evidence and verifying device integrity"};

    nvattest::EvidenceCollectionOptions evidence_collection_options;
    nvattest::EvidenceVerificationOptions evidence_verification_options;
    nvattest::EvidencePolicyOptions evidence_policy_options;
    nvattest::CommonOptions common_options;
    
    add_common_options(app, common_options);

    CLI::App* version_subcommand = nvattest::create_version_subcommand(app);
    CLI::App* attest_subcommand = nvattest::create_attest_subcommand(app, evidence_collection_options, evidence_verification_options, evidence_policy_options);
    CLI::App* collect_evidence_subcommand = nvattest::create_collect_evidence_subcommand(app, evidence_collection_options);

    CLI11_PARSE(app, argc, argv);

#ifdef NVAT_VERIFICATION_ONLY
    if (requests_hardware_collection(
            attest_subcommand,
            collect_evidence_subcommand,
            evidence_collection_options,
            evidence_verification_options)) {
        std::cout << "{\"result_code\":" << NVAT_RC_FEATURE_NOT_ENABLED
                  << ",\"result_message\":\"this build verifies evidence files locally; "
                     "hardware evidence collection and remote verification are not available\"}"
                  << std::endl;
        return NVAT_RC_FEATURE_NOT_ENABLED;
    }
#endif

    nvattest::CliLogger logger(common_options.get_log_level());
    logger.install();

    // Dispatch subcommands
    if (version_subcommand->parsed()) {
        return nvattest::handle_version_subcommand();
    } else if (attest_subcommand->parsed()) {
        const int result = nvattest::handle_attest_subcommand(logger, evidence_collection_options, evidence_verification_options, evidence_policy_options, common_options);
#ifdef _WIN32
        // sol: report the same eight-bit process status as POSIX builds; the
        // full result code is in the JSON output.
        return result & 0xff;
#else
        return result;
#endif
    } else if (collect_evidence_subcommand->parsed()) {
        return nvattest::handle_collect_evidence_subcommand(logger, evidence_collection_options, common_options);
    } else {
        // Default behavior is to display the help message
        std::cout << app.help() << std::endl;
    }

    return 0;
}