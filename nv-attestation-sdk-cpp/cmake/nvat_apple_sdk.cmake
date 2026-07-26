include_guard(GLOBAL)

function(nvat_resolve_apple_toolchain)
  if(NOT CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin")
    return()
  endif()

  if(NOT CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "^(arm64|aarch64)$")
    message(FATAL_ERROR
      "Apple architecture resolution failed: native processor "
      "${CMAKE_HOST_SYSTEM_PROCESSOR} is not arm64; run the release on an "
      "Apple Silicon host, then retry")
  endif()

  if(NOT DEFINED CMAKE_OSX_DEPLOYMENT_TARGET OR
     CMAKE_OSX_DEPLOYMENT_TARGET STREQUAL "" OR
     NOT CMAKE_OSX_DEPLOYMENT_TARGET MATCHES
       "^[0-9]+\\.[0-9]+(\\.[0-9]+)?(\\.[0-9]+)?$")
    message(FATAL_ERROR
      "Apple deployment target resolution failed: expected a dotted numeric "
      "version, got '${CMAKE_OSX_DEPLOYMENT_TARGET}'; pass "
      "-DCMAKE_OSX_DEPLOYMENT_TARGET=<version>, then retry")
  endif()

  if(DEFINED CMAKE_OSX_ARCHITECTURES AND
     NOT CMAKE_OSX_ARCHITECTURES STREQUAL "" AND
     NOT CMAKE_OSX_ARCHITECTURES STREQUAL "arm64")
    message(FATAL_ERROR
      "Apple architecture resolution failed: expected exactly arm64, got "
      "'${CMAKE_OSX_ARCHITECTURES}'; configure a native arm64 build with "
      "-DCMAKE_OSX_ARCHITECTURES=arm64, then retry")
  endif()

  set(_nvat_sdk_selector "${CMAKE_OSX_SYSROOT}")
  if(IS_ABSOLUTE "${_nvat_sdk_selector}")
    set(_nvat_sdk_path "${_nvat_sdk_selector}")
  else()
    if(_nvat_sdk_selector STREQUAL "")
      set(_nvat_sdk_selector macosx)
    endif()
    if(DEFINED NVAT_APPLE_XCRUN AND NOT NVAT_APPLE_XCRUN STREQUAL "")
      set(_nvat_xcrun "${NVAT_APPLE_XCRUN}")
    else()
      find_program(_nvat_xcrun xcrun)
    endif()
    if(NOT _nvat_xcrun)
      message(FATAL_ERROR
        "Apple SDK resolution failed: cannot invoke xcrun: executable not "
        "found; install or select Xcode Command Line Tools with xcode-select, "
        "then retry")
    endif()
    if(IS_ABSOLUTE "${_nvat_xcrun}" AND NOT EXISTS "${_nvat_xcrun}")
      message(FATAL_ERROR
        "Apple SDK resolution failed: cannot invoke xcrun: executable "
        "${_nvat_xcrun} does not exist; install or select Xcode Command Line "
        "Tools with xcode-select, then retry")
    endif()
    execute_process(
      COMMAND "${_nvat_xcrun}" --sdk "${_nvat_sdk_selector}" --show-sdk-path
      OUTPUT_VARIABLE _nvat_sdk_path
      OUTPUT_STRIP_TRAILING_WHITESPACE
      ERROR_VARIABLE _nvat_xcrun_error
      ERROR_STRIP_TRAILING_WHITESPACE
      RESULT_VARIABLE _nvat_xcrun_status
    )
    if(NOT _nvat_xcrun_status EQUAL 0)
      message(FATAL_ERROR
        "Apple SDK resolution failed: xcrun --sdk ${_nvat_sdk_selector} "
        "--show-sdk-path exited ${_nvat_xcrun_status}: ${_nvat_xcrun_error}; "
        "select a valid Xcode developer directory with xcode-select, then retry")
    endif()
    if(_nvat_sdk_path STREQUAL "")
      message(FATAL_ERROR
        "Apple SDK resolution failed: xcrun returned an empty path for SDK "
        "${_nvat_sdk_selector}; verify xcrun --sdk ${_nvat_sdk_selector} "
        "--show-sdk-path, then retry")
    endif()
  endif()

  if(NOT IS_ABSOLUTE "${_nvat_sdk_path}")
    message(FATAL_ERROR
      "Apple SDK resolution failed: resolved path is not absolute: "
      "${_nvat_sdk_path}; pass -DCMAKE_OSX_SYSROOT=<absolute SDK directory> "
      "or repair xcrun, then retry")
  endif()
  if(NOT IS_DIRECTORY "${_nvat_sdk_path}")
    message(FATAL_ERROR
      "Apple SDK resolution failed: SDK directory does not exist: "
      "${_nvat_sdk_path}; install the selected macOS SDK or pass its absolute "
      "directory, then retry")
  endif()
  if(_nvat_sdk_path MATCHES "[;\\\\]")
    message(FATAL_ERROR
      "Apple SDK resolution failed: resolved path contains a semicolon or "
      "backslash: ${_nvat_sdk_path}; pass "
      "-DCMAKE_OSX_SYSROOT=<absolute SDK directory> without those characters, "
      "then retry")
  endif()

  set(CMAKE_OSX_SYSROOT "${_nvat_sdk_path}" CACHE PATH
    "Resolved macOS SDK directory" FORCE)
  set(CMAKE_OSX_ARCHITECTURES arm64 CACHE STRING
    "Native macOS architecture" FORCE)
  set(CMAKE_OSX_DEPLOYMENT_TARGET "${CMAKE_OSX_DEPLOYMENT_TARGET}" CACHE STRING
    "Minimum macOS deployment target" FORCE)
  set(NVAT_APPLE_SDKROOT "${_nvat_sdk_path}" CACHE INTERNAL
    "Resolved macOS SDK directory" FORCE)
  set(NVAT_APPLE_ARCHITECTURE arm64 CACHE INTERNAL
    "Resolved macOS architecture" FORCE)
  set(NVAT_APPLE_DEPLOYMENT_TARGET "${CMAKE_OSX_DEPLOYMENT_TARGET}"
    CACHE INTERNAL "Resolved macOS deployment target" FORCE)
  set(NVAT_EP_ENV_COMMAND
    "${CMAKE_COMMAND};-E;env;SDKROOT=${NVAT_APPLE_SDKROOT}"
    CACHE INTERNAL "Environment prefix for vendored Apple builds" FORCE)
  set_property(GLOBAL PROPERTY NVAT_APPLE_TOOLCHAIN_RESOLVED TRUE)
endfunction()
