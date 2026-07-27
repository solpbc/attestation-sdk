include_guard(GLOBAL)

# NVAT_PINNED_HEADER_BOUNDARIES_BEGIN
set(_NVAT_PINNED_HEADER_BOUNDARIES
  "fmt_SOURCE_DIR|fmt 10.2.1|fmt/core.h|#define FMT_VERSION 100201"
  "spdlog_SOURCE_DIR|spdlog 1.14.1|spdlog/version.h|#define SPDLOG_VER_MAJOR 1"
  "spdlog_SOURCE_DIR|spdlog 1.14.1|spdlog/version.h|#define SPDLOG_VER_MINOR 14"
  "spdlog_SOURCE_DIR|spdlog 1.14.1|spdlog/version.h|#define SPDLOG_VER_PATCH 1"
  "spdlog_SOURCE_DIR|spdlog 1.14.1|spdlog/fmt/bundled/core.h|#define FMT_VERSION 100201"
)
# NVAT_PINNED_HEADER_BOUNDARIES_END

function(_nvat_ordinary_root_conflicts_with_pinned ordinary pinned result)
  if(ordinary STREQUAL pinned)
    set(${result} TRUE PARENT_SCOPE)
    return()
  endif()
  string(FIND "${ordinary}/" "${pinned}/" _ordinary_in_pinned)
  if(_ordinary_in_pinned EQUAL 0)
    set(${result} TRUE PARENT_SCOPE)
  else()
    set(${result} FALSE PARENT_SCOPE)
  endif()
endfunction()

function(nvat_target_include_pinned_logging_headers target)
  cmake_parse_arguments(NVAT_HEADER "" "" "ORDINARY" ${ARGN})
  if(NVAT_HEADER_UNPARSED_ARGUMENTS OR NOT NVAT_HEADER_ORDINARY)
    message(FATAL_ERROR
      "${target} pinned-header boundary failed: expected "
      "nvat_target_include_pinned_logging_headers(<target> ORDINARY <root>...); "
      "pass an existing first-party target and at least one ordinary root")
  endif()
  if(NOT TARGET ${target})
    message(FATAL_ERROR
      "${target} pinned-header boundary failed: expected existing first-party "
      "consumer target ${target}; create the target before applying its pinned "
      "header boundary")
  endif()

  set(_nvat_pinned_roots)
  set(_nvat_pinned_root_records)
  foreach(_nvat_record IN LISTS _NVAT_PINNED_HEADER_BOUNDARIES)
    string(REPLACE "|" ";" _nvat_fields "${_nvat_record}")
    list(LENGTH _nvat_fields _nvat_field_count)
    if(NOT _nvat_field_count EQUAL 4)
      message(FATAL_ERROR
        "${target} pinned-header boundary failed: malformed pinned boundary "
        "record '${_nvat_record}'; repair the sole boundary registry so every "
        "record has exactly four fields")
    endif()
    list(GET _nvat_fields 0 _nvat_root_variable)
    list(GET _nvat_fields 1 _nvat_pin)
    list(GET _nvat_fields 2 _nvat_relative_header)
    list(GET _nvat_fields 3 _nvat_identity)

    if(NOT DEFINED ${_nvat_root_variable} OR
       "${${_nvat_root_variable}}" STREQUAL "")
      message(FATAL_ERROR
        "${target} pinned-header boundary failed: expected populated ${_nvat_pin} "
        "source variable ${_nvat_root_variable}; verify the pinned ${_nvat_pin} "
        "acquisition")
    endif()
    set(_nvat_include_root "${${_nvat_root_variable}}/include")
    if(NOT IS_DIRECTORY "${_nvat_include_root}")
      message(FATAL_ERROR
        "${target} pinned-header boundary failed: expected ${_nvat_pin} include "
        "root '${_nvat_include_root}'; verify the pinned ${_nvat_pin} target layout")
    endif()
    set(_nvat_header "${_nvat_include_root}/${_nvat_relative_header}")
    if(NOT EXISTS "${_nvat_header}")
      message(FATAL_ERROR
        "${target} pinned-header boundary failed: expected ${_nvat_pin} public "
        "header '${_nvat_relative_header}' under '${_nvat_include_root}'; verify "
        "the pinned ${_nvat_pin} target layout")
    endif()
    file(STRINGS "${_nvat_header}" _nvat_identity_lines
      REGEX "^${_nvat_identity}$")
    if(NOT _nvat_identity_lines)
      message(FATAL_ERROR
        "${target} pinned-header boundary failed: expected "
        "'${_nvat_relative_header}' to identify ${_nvat_pin}; verify the pinned "
        "${_nvat_pin} public-header layout")
    endif()

    get_filename_component(_nvat_canonical_pinned
      "${_nvat_include_root}" REALPATH)
    list(APPEND _nvat_pinned_roots "${_nvat_canonical_pinned}")
    list(APPEND _nvat_pinned_root_records
      "${_nvat_canonical_pinned}|${_nvat_pin}")
  endforeach()
  list(REMOVE_DUPLICATES _nvat_pinned_roots)

  foreach(_nvat_ordinary IN LISTS NVAT_HEADER_ORDINARY)
    set(_nvat_ordinary_path "${_nvat_ordinary}")
    if(_nvat_ordinary MATCHES "^\\$<BUILD_INTERFACE:(.*)>$")
      set(_nvat_ordinary_path "${CMAKE_MATCH_1}")
    elseif(_nvat_ordinary MATCHES "\\$<")
      message(FATAL_ERROR
        "${target} pinned-header boundary failed: unsupported ordinary-root "
        "generator expression '${_nvat_ordinary}'; pass a plain path or one "
        "$<BUILD_INTERFACE:path> expression")
    endif()
    if(NOT IS_ABSOLUTE "${_nvat_ordinary_path}")
      set(_nvat_ordinary_path
        "${CMAKE_CURRENT_SOURCE_DIR}/${_nvat_ordinary_path}")
    endif()
    if(NOT EXISTS "${_nvat_ordinary_path}")
      message(FATAL_ERROR
        "${target} pinned-header boundary failed: expected ordinary root "
        "'${_nvat_ordinary_path}' to exist; create or populate the first-party "
        "root before applying its pinned header boundary")
    endif()
    get_filename_component(_nvat_canonical_ordinary
      "${_nvat_ordinary_path}" REALPATH)
    foreach(_nvat_pinned_record IN LISTS _nvat_pinned_root_records)
      string(REPLACE "|" ";" _nvat_pinned_fields "${_nvat_pinned_record}")
      list(GET _nvat_pinned_fields 0 _nvat_pinned_root)
      list(GET _nvat_pinned_fields 1 _nvat_pinned_pin)
      _nvat_ordinary_root_conflicts_with_pinned(
        "${_nvat_canonical_ordinary}" "${_nvat_pinned_root}" _nvat_overlap)
      if(_nvat_overlap)
        message(FATAL_ERROR
          "${target} pinned-header boundary failed: ordinary root "
          "'${_nvat_canonical_ordinary}' overlaps pinned ${_nvat_pinned_pin} "
          "root '${_nvat_pinned_root}'; only the pinned fmt/spdlog roots may be "
          "SYSTEM")
      endif()
    endforeach()
  endforeach()

  target_include_directories(${target} PRIVATE ${NVAT_HEADER_ORDINARY})
  target_include_directories(${target} SYSTEM PRIVATE ${_nvat_pinned_roots})
endfunction()
