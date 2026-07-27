include_guard(GLOBAL)

function(nvat_configure_apple_system_link_closure)
  if(NOT APPLE)
    message(FATAL_ERROR
      "Darwin/arm64 system-link closure failed: helper reached while APPLE is "
      "false; call it only from the post-project Apple-guarded SDK path, then "
      "retry")
  endif()

  if(NOT DEFINED NVAT_APPLE_SDKROOT OR
     NOT IS_ABSOLUTE "${NVAT_APPLE_SDKROOT}" OR
     NOT IS_DIRECTORY "${NVAT_APPLE_SDKROOT}")
    message(FATAL_ERROR
      "Darwin/arm64 system-link closure failed: NVAT_APPLE_SDKROOT is not an "
      "absolute existing directory: '${NVAT_APPLE_SDKROOT}'; select a valid "
      "macOS SDK with xcrun and remove the build directory, then retry")
  endif()
  get_filename_component(
    _nvat_apple_sdkroot_real
    "${NVAT_APPLE_SDKROOT}"
    REALPATH
  )

  set(
    _nvat_apple_corrosion_sdk_link_directory
    "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib"
  )
  set(
    _nvat_apple_rust_owner_targets
    regorus_ffi
    regorus_ffi-static
  )
  foreach(_nvat_apple_rust_owner_target IN LISTS
          _nvat_apple_rust_owner_targets)
    if(NOT TARGET "${_nvat_apple_rust_owner_target}")
      message(FATAL_ERROR
        "Darwin/arm64 Rust link-directory closure failed: required owner-chain "
        "target '${_nvat_apple_rust_owner_target}' does not exist; recreate "
        "the pinned Corrosion regorus_ffi staticlib targets in a clean build "
        "directory, then retry")
    endif()
  endforeach()
  if(NOT TARGET LibXml2::LibXml2)
    message(FATAL_ERROR
      "Darwin/arm64 iconv closure failed: static owner target "
      "LibXml2::LibXml2 does not exist; create the selected LibXml2::LibXml2 "
      "target before the Apple closure call, then retry")
  endif()
  if(TARGET Iconv::Iconv)
    message(FATAL_ERROR
      "Darwin/arm64 iconv discovery failed: target Iconv::Iconv already exists "
      "without selected-SDK validation; remove the pre-existing Iconv target "
      "and configure from a clean build directory, then retry")
  endif()

  foreach(_nvat_apple_rust_owner_target IN LISTS
          _nvat_apple_rust_owner_targets)
    get_target_property(
      _nvat_apple_rust_link_directories
      "${_nvat_apple_rust_owner_target}"
      INTERFACE_LINK_DIRECTORIES
    )
    if(_nvat_apple_rust_link_directories)
      foreach(_nvat_apple_rust_link_directory IN LISTS
              _nvat_apple_rust_link_directories)
        if(NOT _nvat_apple_rust_link_directory STREQUAL
           _nvat_apple_corrosion_sdk_link_directory)
          message(FATAL_ERROR
            "Darwin/arm64 Rust link-directory closure failed: target "
            "'${_nvat_apple_rust_owner_target}' has unsupported "
            "INTERFACE_LINK_DIRECTORIES entry "
            "'${_nvat_apple_rust_link_directory}'; remove the unexpected "
            "link-directory entry and configure from a clean build directory, "
            "then retry")
        endif()
      endforeach()
    endif()
  endforeach()

  unset(NVAT_APPLE_ICONV_LIBRARY CACHE)
  set(NVAT_APPLE_ICONV_LIBRARY "NVAT_APPLE_ICONV_LIBRARY-NOTFOUND")
  find_library(
    NVAT_APPLE_ICONV_LIBRARY
    NAMES libiconv.tbd
    NO_DEFAULT_PATH
    PATHS "${NVAT_APPLE_SDKROOT}/usr/lib"
  )
  if(NOT NVAT_APPLE_ICONV_LIBRARY)
    message(FATAL_ERROR
      "Darwin/arm64 iconv discovery failed: libiconv.tbd was not found in "
      "selected SDK '${NVAT_APPLE_SDKROOT}/usr/lib'; select a macOS SDK "
      "containing usr/lib/libiconv.tbd and remove the build directory, then "
      "retry")
  endif()
  get_filename_component(
    _nvat_apple_iconv_real
    "${NVAT_APPLE_ICONV_LIBRARY}"
    REALPATH
  )
  string(
    FIND
    "${_nvat_apple_iconv_real}/"
    "${_nvat_apple_sdkroot_real}/"
    _nvat_apple_iconv_inside_sdk
  )
  if(NOT _nvat_apple_iconv_inside_sdk EQUAL 0)
    message(FATAL_ERROR
      "Darwin/arm64 iconv discovery failed: resolved path "
      "'${_nvat_apple_iconv_real}' is outside selected SDK "
      "'${_nvat_apple_sdkroot_real}'; remove host or Homebrew cache inputs and "
      "select the macOS SDK, then retry")
  endif()

  unset(NVAT_APPLE_COREFOUNDATION_FRAMEWORK CACHE)
  set(
    NVAT_APPLE_COREFOUNDATION_FRAMEWORK
    "NVAT_APPLE_COREFOUNDATION_FRAMEWORK-NOTFOUND"
  )
  find_library(
    NVAT_APPLE_COREFOUNDATION_FRAMEWORK
    NAMES CoreFoundation
    NO_DEFAULT_PATH
    PATHS "${NVAT_APPLE_SDKROOT}/System/Library/Frameworks"
  )
  if(NOT NVAT_APPLE_COREFOUNDATION_FRAMEWORK)
    message(FATAL_ERROR
      "Darwin/arm64 CoreFoundation discovery failed: CoreFoundation.framework "
      "was not found in selected SDK "
      "'${NVAT_APPLE_SDKROOT}/System/Library/Frameworks'; select a macOS SDK "
      "containing System/Library/Frameworks/CoreFoundation.framework and "
      "remove the build directory, then retry")
  endif()
  get_filename_component(
    _nvat_apple_corefoundation_real
    "${NVAT_APPLE_COREFOUNDATION_FRAMEWORK}"
    REALPATH
  )
  string(
    FIND
    "${_nvat_apple_corefoundation_real}/"
    "${_nvat_apple_sdkroot_real}/"
    _nvat_apple_corefoundation_inside_sdk
  )
  if(NOT _nvat_apple_corefoundation_inside_sdk EQUAL 0)
    message(FATAL_ERROR
      "Darwin/arm64 CoreFoundation discovery failed: resolved path "
      "'${_nvat_apple_corefoundation_real}' is outside selected SDK "
      "'${_nvat_apple_sdkroot_real}'; remove host or Homebrew cache inputs and "
      "select the macOS SDK, then retry")
  endif()

  foreach(_nvat_apple_rust_owner_target IN LISTS
          _nvat_apple_rust_owner_targets)
    set_property(
      TARGET "${_nvat_apple_rust_owner_target}"
      PROPERTY INTERFACE_LINK_DIRECTORIES ""
    )
  endforeach()
  add_library(Iconv::Iconv UNKNOWN IMPORTED)
  set_target_properties(Iconv::Iconv PROPERTIES
    IMPORTED_LOCATION "${_nvat_apple_iconv_real}"
  )
  set_property(TARGET regorus_ffi APPEND PROPERTY
    INTERFACE_LINK_LIBRARIES "${_nvat_apple_corefoundation_real}")
  set_property(TARGET LibXml2::LibXml2 APPEND PROPERTY
    INTERFACE_LINK_LIBRARIES Iconv::Iconv)

  unset(NVAT_APPLE_ICONV_LIBRARY CACHE)
  unset(NVAT_APPLE_COREFOUNDATION_FRAMEWORK CACHE)
endfunction()
