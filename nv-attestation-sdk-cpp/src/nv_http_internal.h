/*
 * SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <string>
#include <vector>

#include "nv_attestation/error.h"

namespace nvattestation {

    Error resolve_ca_bundle_path_with_overrides(
        const std::string& explicit_path,
        std::string& out_path,
        std::string& out_tier,
        const std::string* compiled_default_override,
        const std::vector<std::string>* probe_paths_override);

    std::string ca_bundle_resolution_error_message(
        const std::string& path,
        const std::string& tier);

}
