# Copyright (c) 2026 sol pbc
# SPDX-License-Identifier: Apache-2.0
#
# Keep build-host paths out of compiled objects.
#
# C/C++ __FILE__ and Rust panic locations otherwise carry the checkout, the
# CMake binary directory and the Cargo home of whoever built the release. They
# are never opened, but they make the archive's bytes depend on the build host
# and stop the release rail's build-root gate from being a plain substring test
# (sol/notes/build-host-path-hygiene.md).
#
# The vendored autoconf projects keep their own flags: OpenSSL records its
# CFLAGS in the library, so a remap flag there would embed the very path it
# removes.

include_guard(GLOBAL)

get_filename_component(NVAT_REPOSITORY_ROOT
  "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)

# Adds -ffile-prefix-map for the repository root and the top-level binary
# directory to every C and C++ target created after the call in this directory
# and the subdirectories it adds. MSVC uses /pathmap for __FILE__.
function(nvat_add_build_path_remap)
  if(MSVC)
    add_compile_options(
      /experimental:deterministic
      "/pathmap:${NVAT_REPOSITORY_ROOT}=."
      "/pathmap:${CMAKE_BINARY_DIR}=."
    )
    return()
  endif()
  foreach(_nvat_language C CXX)
    set(_nvat_id "${CMAKE_${_nvat_language}_COMPILER_ID}")
    if(_nvat_id AND NOT _nvat_id MATCHES "^(GNU|Clang|AppleClang)$")
      message(FATAL_ERROR
        "nvat build-path remap: unsupported ${_nvat_language} compiler "
        "${_nvat_id}; expected GNU, Clang or AppleClang")
    endif()
  endforeach()
  add_compile_options(
    "-ffile-prefix-map=${NVAT_REPOSITORY_ROOT}=."
    "-ffile-prefix-map=${CMAKE_BINARY_DIR}=."
  )
  if(APPLE)
    # ld64 writes a debug map (N_OSO stabs) naming every linked object that
    # carries debug information, such as the Rust standard library objects in
    # libregorus_ffi.a, by its real absolute path. Strip the checkout from it.
    get_filename_component(_nvat_real_root "${NVAT_REPOSITORY_ROOT}" REALPATH)
    add_link_options("LINKER:-oso_prefix,${_nvat_real_root}/")
  endif()
endfunction()

# Adds --remap-path-prefix to RUSTFLAGS for a Corrosion target and every Rust
# crate it builds. rustc applies the last matching prefix, so the more specific
# roots come after the repository root.
function(nvat_add_rust_build_path_remap target)
  if(WIN32)
    return()
  endif()
  if(DEFINED ENV{CARGO_HOME} AND NOT "$ENV{CARGO_HOME}" STREQUAL "")
    set(_nvat_cargo_home "$ENV{CARGO_HOME}")
  elseif(DEFINED ENV{HOME} AND NOT "$ENV{HOME}" STREQUAL "")
    set(_nvat_cargo_home "$ENV{HOME}/.cargo")
  else()
    message(FATAL_ERROR
      "nvat build-path remap: neither CARGO_HOME nor HOME is set, so the "
      "Cargo home cannot be remapped")
  endif()
  get_filename_component(_nvat_cargo_home "${_nvat_cargo_home}" ABSOLUTE)
  foreach(_nvat_root IN ITEMS
      "${NVAT_REPOSITORY_ROOT}" "${CMAKE_BINARY_DIR}" "${_nvat_cargo_home}")
    # Corrosion joins RUSTFLAGS with spaces.
    if(_nvat_root MATCHES "[ \t]")
      message(FATAL_ERROR
        "nvat build-path remap: '${_nvat_root}' contains whitespace, which "
        "RUSTFLAGS cannot carry; build from a path without spaces")
    endif()
  endforeach()
  corrosion_add_target_rustflags(${target}
    "--remap-path-prefix=${NVAT_REPOSITORY_ROOT}=."
    "--remap-path-prefix=${CMAKE_BINARY_DIR}=."
    "--remap-path-prefix=${_nvat_cargo_home}=cargo-home"
  )
endfunction()
