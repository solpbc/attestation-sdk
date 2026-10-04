# Copyright (c) 2026 sol pbc
# SPDX-License-Identifier: Apache-2.0
#
# Compiler options for the native Windows (MSVC) build, shared by the SDK and
# the command-line tool. The command-line tool configures the SDK as a
# subdirectory, so the options are added once per configure.

function(nvat_add_msvc_compile_options)
  get_property(_added GLOBAL PROPERTY NVAT_MSVC_COMPILE_OPTIONS_ADDED)
  if(_added)
    return()
  endif()
  set_property(GLOBAL PROPERTY NVAT_MSVC_COMPILE_OPTIONS_ADDED TRUE)
  # /utf-8: sources and execution strings are UTF-8.
  # /permissive-: standard conformance, as GCC and Clang enforce.
  # /W3 with CMAKE_COMPILE_WARNING_AS_ERROR: the same warnings-are-errors
  #   policy as the POSIX builds; compiled third-party targets keep their
  #   existing exemption.
  # /external:anglebrackets /external:W0: headers included with angle brackets
  #   are third-party (OpenSSL, curl, libxml2, xmlsec, nlohmann/json, spdlog)
  #   and are not held to this project's warning policy.
  # /guard:cf and /Qspectre are not used: the dependency archives are built
  #   without them, so they would protect only part of the image.
  add_compile_options(/utf-8 /permissive- /Zc:__cplusplus /W3
    /external:anglebrackets /external:W0)
  add_compile_definitions(
    WIN32_LEAN_AND_MEAN
    NOMINMAX
    NOGDI
    _CRT_SECURE_NO_WARNINGS
    _CRT_NONSTDC_NO_WARNINGS
  )
  add_link_options(/DYNAMICBASE /NXCOMPAT /HIGHENTROPYVA)
endfunction()
