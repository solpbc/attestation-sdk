// Copyright (c) 2026 sol pbc
// SPDX-License-Identifier: Apache-2.0
//
// Checks the Windows Gregorian UTC conversions against fixed vectors, from
// before the epoch to the year 9999 that NVIDIA's signing certificates use.
// Usage: utc_test <vectors.json>; exits non-zero on the first mismatch.

#include "nv_attestation/windows_compat.h"

#include <cstdio>
#include <fstream>
#include <iostream>

#include <nlohmann/json.hpp>

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: utc_test <vectors.json>" << std::endl;
        return 2;
    }
    std::ifstream input(nvat_widen_path(argv[1]));
    nlohmann::json vectors;
    input >> vectors;
    int checked = 0;
    for (const auto& vector : vectors) {
        tm fields{};
        fields.tm_year = vector["year"].get<int>() - 1900;
        fields.tm_mon = vector["month"].get<int>() - 1;
        fields.tm_mday = vector["day"].get<int>();
        fields.tm_hour = vector["hour"].get<int>();
        fields.tm_min = vector["minute"].get<int>();
        fields.tm_sec = vector["second"].get<int>();
        const std::string iso = vector["iso"].get<std::string>();
        const time_t seconds = timegm(&fields);
        if (static_cast<long long>(seconds) != vector["seconds"].get<long long>()) {
            std::cerr << iso << ": timegm " << static_cast<long long>(seconds) << std::endl;
            return 10;
        }
        tm back{};
        if (gmtime_r(&seconds, &back) == nullptr) {
            std::cerr << iso << ": gmtime_r failed" << std::endl;
            return 11;
        }
        char text[32];
        std::snprintf(text, sizeof(text), "%04d-%02d-%02dT%02d:%02d:%02dZ",
            back.tm_year + 1900, back.tm_mon + 1, back.tm_mday,
            back.tm_hour, back.tm_min, back.tm_sec);
        if (iso != text || back.tm_wday != vector["weekday"].get<int>()
            || back.tm_yday != vector["yearday"].get<int>()) {
            std::cerr << iso << ": gmtime_r " << text << " wday " << back.tm_wday
                      << " yday " << back.tm_yday << std::endl;
            return 12;
        }
        ++checked;
    }
    std::cout << "utc vectors passed: " << checked << std::endl;
    return checked > 0 ? 0 : 13;
}
