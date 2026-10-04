/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 sol pbc
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

// Native Windows support for the verification-only build.
//
// The SDK is written against POSIX. This header supplies the few POSIX
// facilities its verification path uses, with Windows semantics made explicit:
//
// * Paths arrive as UTF-8. Files are opened through their UTF-16 form so
//   non-ASCII paths work regardless of the process code page.
// * Certificate and OCSP times use proleptic Gregorian UTC arithmetic. The
//   MSVC runtime's _mkgmtime and gmtime_s stop at the year 3000, and NVIDIA's
//   signing certificates expire in the year 9999.
// * There is no hardware evidence collection on Windows. The collector
//   libraries are never loaded: dlopen always fails, and the command-line tool
//   refuses collection before reaching it.

#pragma once

#ifdef _WIN32

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
// wingdi.h defines ERROR, which collides with the SDK's log level enumerator.
#ifdef ERROR
#undef ERROR
#endif

#include <io.h>
#include <sys/stat.h>
#include <cerrno>
#include <climits>
#include <ctime>
#include <string>

#ifndef S_ISREG
#define S_ISREG(m) (((m) & _S_IFMT) == _S_IFREG)
#endif
#ifndef S_ISDIR
#define S_ISDIR(m) (((m) & _S_IFMT) == _S_IFDIR)
#endif
#ifndef R_OK
#define R_OK 4
#endif

// Converts a UTF-8 path to UTF-16. Invalid UTF-8 yields an empty string, which
// every caller then fails to open, stat or read.
inline std::wstring nvat_widen_path(const std::string& utf8) {
    if (utf8.empty()) {
        return std::wstring();
    }
    const int length = MultiByteToWideChar(
        CP_UTF8, MB_ERR_INVALID_CHARS, utf8.data(), static_cast<int>(utf8.size()), nullptr, 0);
    if (length <= 0) {
        return std::wstring();
    }
    std::wstring wide(static_cast<size_t>(length), L'\0');
    if (MultiByteToWideChar(
            CP_UTF8, MB_ERR_INVALID_CHARS, utf8.data(), static_cast<int>(utf8.size()), &wide[0], length)
        != length) {
        return std::wstring();
    }
    return wide;
}

// Proleptic Gregorian UTC, valid for every year the 64-bit time_t covers.
inline struct tm* gmtime_r(const time_t* timestamp, struct tm* out) {
    long long days = static_cast<long long>(*timestamp) / 86400;
    long long seconds = static_cast<long long>(*timestamp) % 86400;
    if (seconds < 0) {
        seconds += 86400;
        --days;
    }
    const long long z = days + 719468;
    const long long era = (z >= 0 ? z : z - 146096) / 146097;
    const long long doe = z - era * 146097;
    const long long yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    const long long doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    const long long mp = (5 * doy + 2) / 153;
    const long long day = doy - (153 * mp + 2) / 5 + 1;
    const long long month = mp < 10 ? mp + 3 : mp - 9;
    const long long year = yoe + era * 400 + (month <= 2 ? 1 : 0);
    if (year - 1900 > INT_MAX || year - 1900 < INT_MIN) {
        errno = EOVERFLOW;
        return nullptr;
    }
    static const int days_before_month[] = {0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334};
    const bool leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    *out = tm{};
    out->tm_year = static_cast<int>(year - 1900);
    out->tm_mon = static_cast<int>(month - 1);
    out->tm_mday = static_cast<int>(day);
    out->tm_hour = static_cast<int>(seconds / 3600);
    out->tm_min = static_cast<int>((seconds % 3600) / 60);
    out->tm_sec = static_cast<int>(seconds % 60);
    long long weekday = (days + 4) % 7;
    if (weekday < 0) {
        weekday += 7;
    }
    out->tm_wday = static_cast<int>(weekday);
    out->tm_yday = days_before_month[month - 1] + static_cast<int>(day) - 1 + (leap && month > 2 ? 1 : 0);
    return out;
}

// Inverse of gmtime_r for normalized fields (month 0-11, day 1-31).
inline time_t timegm(struct tm* value) {
    long long year = static_cast<long long>(value->tm_year) + 1900;
    const long long month = static_cast<long long>(value->tm_mon) + 1;
    if (month <= 2) {
        --year;
    }
    const long long era = (year >= 0 ? year : year - 399) / 400;
    const long long yoe = year - era * 400;
    const long long doy = (153 * (month > 2 ? month - 3 : month + 9) + 2) / 5 + value->tm_mday - 1;
    const long long doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    const long long days = era * 146097 + doe - 719468;
    return static_cast<time_t>(
        days * 86400 + static_cast<long long>(value->tm_hour) * 3600
        + static_cast<long long>(value->tm_min) * 60 + value->tm_sec);
}

#define RTLD_LAZY 0x1
#define RTLD_LOCAL 0x0

inline void* dlopen(const char*, int) { return nullptr; }
inline void* dlsym(void*, const char*) { return nullptr; }
inline int dlclose(void*) { return 0; }
inline const char* dlerror() { return "hardware evidence collection is not available on Windows"; }

#endif // _WIN32
