# Copyright (c) 2026 sol pbc
# SPDX-License-Identifier: Apache-2.0
#
# Imports the static OpenSSL, libxml2, xmlsec, curl and zlib archives that
# sol/windows/build.ps1 builds from the same pinned sources as the POSIX
# ExternalProject builds. NVAT_WINDOWS_DEPS_DIR names their install prefix.
#
# The xmlsec definitions must match the ones the xmlsec archive was compiled
# with. xmlsec's public structures change layout with them; a mismatch makes
# the SDK read signature results at the wrong offsets.

if(NOT NVAT_WINDOWS_DEPS_DIR)
  message(FATAL_ERROR
    "NVAT_WINDOWS_DEPS_DIR is required on Windows; build the dependencies "
    "with sol/windows/build.ps1")
endif()
file(TO_CMAKE_PATH "${NVAT_WINDOWS_DEPS_DIR}" _NVAT_DEPS)

function(nvat_import_windows_static target archive include_subdir)
  set(_archive "${_NVAT_DEPS}/lib/${archive}")
  if(NOT EXISTS "${_archive}")
    message(FATAL_ERROR "missing Windows dependency archive: ${_archive}")
  endif()
  add_library(${target} STATIC IMPORTED)
  set_target_properties(${target} PROPERTIES
    IMPORTED_LOCATION "${_archive}"
    INTERFACE_INCLUDE_DIRECTORIES "${_NVAT_DEPS}/include${include_subdir}")
endfunction()

nvat_import_windows_static(OpenSSL::Crypto libcrypto.lib "")
set_property(TARGET OpenSSL::Crypto PROPERTY
  INTERFACE_LINK_LIBRARIES "crypt32;ws2_32;advapi32;user32;bcrypt")
nvat_import_windows_static(OpenSSL::SSL libssl.lib "")
set_property(TARGET OpenSSL::SSL PROPERTY INTERFACE_LINK_LIBRARIES OpenSSL::Crypto)

nvat_import_windows_static(LibXml2::LibXml2 libxml2s.lib "/libxml2")
set_property(TARGET LibXml2::LibXml2 PROPERTY
  INTERFACE_COMPILE_DEFINITIONS LIBXML_STATIC)

set(NVAT_WINDOWS_XMLSEC_DEFINITIONS
  XMLSEC_STATIC
  XMLSEC_CRYPTO_OPENSSL
  XMLSEC_NO_XSLT
  XMLSEC_NO_SIZE_T
  XMLSEC_NO_GOST
  XMLSEC_NO_GOST2012
  XMLSEC_NO_CRYPTO_DYNAMIC_LOADING
)
nvat_import_windows_static(xmlsec::xmlsec libxmlsec_a.lib "/xmlsec1")
set_property(TARGET xmlsec::xmlsec PROPERTY
  INTERFACE_COMPILE_DEFINITIONS "${NVAT_WINDOWS_XMLSEC_DEFINITIONS}")
set_property(TARGET xmlsec::xmlsec PROPERTY
  INTERFACE_LINK_LIBRARIES "LibXml2::LibXml2;OpenSSL::Crypto")
nvat_import_windows_static(xmlsec::xmlsec-openssl libxmlsec-openssl_a.lib "/xmlsec1")
set_property(TARGET xmlsec::xmlsec-openssl PROPERTY
  INTERFACE_COMPILE_DEFINITIONS "${NVAT_WINDOWS_XMLSEC_DEFINITIONS}")
set_property(TARGET xmlsec::xmlsec-openssl PROPERTY
  INTERFACE_LINK_LIBRARIES "xmlsec::xmlsec;OpenSSL::SSL;OpenSSL::Crypto")

nvat_import_windows_static(CURL::libcurl libcurl.lib "")
set_property(TARGET CURL::libcurl PROPERTY INTERFACE_COMPILE_DEFINITIONS CURL_STATICLIB)
# curl 8 resolves IPv6 scope names with if_nametoindex (iphlpapi).
set_property(TARGET CURL::libcurl PROPERTY
  INTERFACE_LINK_LIBRARIES "OpenSSL::SSL;OpenSSL::Crypto;ws2_32;iphlpapi;crypt32;wldap32;normaliz")

set(ZLIB_LIBRARY "${_NVAT_DEPS}/lib/zlibstatic.lib" CACHE FILEPATH "Windows static zlib" FORCE)
set(ZLIB_INCLUDE_DIR "${_NVAT_DEPS}/include" CACHE PATH "Windows zlib headers" FORCE)

# Targets the POSIX build defines for its ExternalProjects; nvat depends on them.
foreach(_dep openssl_external libxml2_external xmlsec_external curl_external)
  add_custom_target(${_dep})
endforeach()
