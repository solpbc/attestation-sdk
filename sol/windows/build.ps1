# Copyright (c) 2026 sol pbc
# SPDX-License-Identifier: Apache-2.0
#
# Builds the native Windows x64 verification-only nvattest from this checkout.
#
# Run from a PowerShell prompt on Windows with Visual Studio 2022 C++ build
# tools, CMake, Git and the Rust MSVC toolchain installed. The script fetches
# the pinned sources in inputs.json, verifies each SHA-256, builds the static
# dependencies, builds the verifier, runs the UTC self-test and stages:
#
#   <Root>\dist\nvattest\bin\nvattest.exe
#   <Root>\dist\nvattest\bin\{msvcp140,vcruntime140,vcruntime140_1}.dll
#   <Root>\dist\nvattest\share\ca\ca-bundle.pem
#   <Root>\dist\nvattest\LICENSE
#
# and <Root>\build-report.json with the tool versions, input digests, output
# digests and the executable's imported DLLs. Nothing is signed here.
#
# OpenSSL is configured with -DOSSL_WINCTX, so its configuration, engine and
# provider-module directories come only from an administrator-owned registry
# key that sol pbc never creates. Without that key OpenSSL loads no
# configuration file and no module from any path a standard user can create.

param(
    [string]$Root = 'C:\nvb',
    [switch]$ReuseDependencies
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$inputs = Get-Content -Raw (Join-Path $PSScriptRoot 'inputs.json') | ConvertFrom-Json
$downloads = Join-Path $Root 'downloads'
$src = Join-Path $Root 'src'
$deps = Join-Path $Root 'deps'
$build = Join-Path $Root 'build'
$dist = Join-Path $Root 'dist\nvattest'
New-Item -ItemType Directory -Force $downloads, $src | Out-Null

# Native tools report progress on stderr. Windows PowerShell turns redirected
# native stderr into error records, so judge them by exit code alone.
function Invoke-Checked([string]$what, [scriptblock]$block) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $block } finally { $ErrorActionPreference = $saved }
    if ($LASTEXITCODE -ne 0) { throw "$what failed with exit code $LASTEXITCODE" }
}

function Get-Sha256([string]$path) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
}

function Get-Pinned($item, [string]$destination) {
    $file = Join-Path $downloads $item.name
    if (-not (Test-Path -LiteralPath $file) -or (Get-Sha256 $file) -ne $item.sha256) {
        Invoke-WebRequest -UseBasicParsing -Uri $item.url -OutFile $file
    }
    $actual = Get-Sha256 $file
    if ($actual -ne $item.sha256) { throw "digest mismatch for $($item.name): $actual" }
    if (-not (Test-Path -LiteralPath (Join-Path $destination $item.dir))) {
        Invoke-Checked "extract $($item.name)" { tar.exe -xf $file -C $destination }
    }
    [ordered]@{ name = $item.name; url = $item.url; sha256 = $actual }
}

# Visual Studio developer environment, imported into this process.
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'Visual Studio C++ x64 build tools not found' }
$vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
cmd.exe /c "`"$vcvars`" >nul && set" | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2] }
}
if (-not $env:VCToolsRedistDir) { throw 'vcvars did not provide VCToolsRedistDir' }
$env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"

$sourceRecords = @()
foreach ($item in $inputs.sources) { $sourceRecords += Get-Pinned $item $src }
$toolRecords = @()
foreach ($item in $inputs.build_tools) { $toolRecords += Get-Pinned $item $Root }
$perlBin = Join-Path $Root 'perl\bin'
$cmake = 'cmake'

if (-not ($ReuseDependencies -and (Test-Path (Join-Path $deps 'lib\libcurl.lib')))) {
    if (Test-Path $deps) { Remove-Item -Recurse -Force $deps }
    New-Item -ItemType Directory -Force $deps | Out-Null
    $env:CMAKE_BUILD_PARALLEL_LEVEL = [Environment]::ProcessorCount

    Push-Location (Join-Path $src 'openssl-3.6.1')
    $savedPath = $env:Path
    $env:Path = "$perlBin;$env:Path"
    Invoke-Checked 'OpenSSL configure' {
        perl Configure VC-WIN64A no-asm no-shared no-tests no-apps no-docs no-legacy no-engine no-dtls `
            "--prefix=$deps" '--openssldir=C:\Windows\System32\nvat-openssl-unused' '--libdir=lib' `
            '-DOSSL_WINCTX=nvat-sol'
    }
    Invoke-Checked 'OpenSSL build' { nmake /nologo }
    Invoke-Checked 'OpenSSL install' { nmake /nologo install_dev }
    $env:Path = $savedPath
    Pop-Location

    Invoke-Checked 'zlib configure' { & $cmake -S (Join-Path $src 'zlib-1.3.1') -B (Join-Path $Root 'b-zlib') -G 'NMake Makefiles' -DCMAKE_BUILD_TYPE=Release "-DCMAKE_INSTALL_PREFIX=$deps" }
    Invoke-Checked 'zlib build' { & $cmake --build (Join-Path $Root 'b-zlib') }
    Invoke-Checked 'zlib install' { & $cmake --install (Join-Path $Root 'b-zlib') }

    Invoke-Checked 'libxml2 configure' {
        & $cmake -S (Join-Path $src 'libxml2-2.11.9') -B (Join-Path $Root 'b-libxml2') -G 'NMake Makefiles' -DCMAKE_BUILD_TYPE=Release "-DCMAKE_INSTALL_PREFIX=$deps" `
            -DBUILD_SHARED_LIBS=OFF -DLIBXML2_WITH_ICONV=OFF -DLIBXML2_WITH_LZMA=OFF -DLIBXML2_WITH_PYTHON=OFF -DLIBXML2_WITH_ZLIB=OFF `
            -DLIBXML2_WITH_HTTP=OFF -DLIBXML2_WITH_FTP=OFF -DLIBXML2_WITH_CATALOG=OFF -DLIBXML2_WITH_TESTS=OFF -DLIBXML2_WITH_PROGRAMS=OFF
    }
    Invoke-Checked 'libxml2 build' { & $cmake --build (Join-Path $Root 'b-libxml2') }
    Invoke-Checked 'libxml2 install' { & $cmake --install (Join-Path $Root 'b-libxml2') }
    # xmlsec's MSVC makefile names the static libxml2 archive libxml2_a.lib.
    Copy-Item (Join-Path $deps 'lib\libxml2s.lib') (Join-Path $deps 'lib\libxml2_a.lib') -Force

    Push-Location (Join-Path $src 'xmlsec1-1.2.39\win32')
    Invoke-Checked 'xmlsec configure' {
        cscript //NoLogo configure.js "prefix=$deps" "include=$deps\include;$deps\include\libxml2" "lib=$deps\lib" `
            crypto=openssl-300 xslt=no iconv=no static=yes with-dl=no with-openssl3-engines=no cruntime=/MD
    }
    Invoke-Checked 'xmlsec build' { nmake /nologo /f Makefile.msvc xmlseca openssla }
    New-Item -ItemType Directory -Force (Join-Path $deps 'include\xmlsec1\xmlsec') | Out-Null
    Copy-Item -Recurse -Force ..\include\xmlsec\* (Join-Path $deps 'include\xmlsec1\xmlsec')
    Copy-Item binaries\libxmlsec_a.lib, binaries\libxmlsec-openssl_a.lib (Join-Path $deps 'lib')
    Pop-Location

    Invoke-Checked 'curl configure' {
        & $cmake -S (Join-Path $src 'curl-7.88.1') -B (Join-Path $Root 'b-curl') -G 'NMake Makefiles' -DCMAKE_BUILD_TYPE=Release "-DCMAKE_INSTALL_PREFIX=$deps" `
            "-DOPENSSL_ROOT_DIR=$deps" -DOPENSSL_USE_STATIC_LIBS=ON -DBUILD_SHARED_LIBS=OFF -DBUILD_CURL_EXE=OFF -DCURL_USE_OPENSSL=ON `
            -DCURL_USE_SCHANNEL=OFF -DCURL_USE_LIBSSH2=OFF -DCURL_USE_LIBPSL=OFF -DCURL_ZLIB=OFF -DCURL_DISABLE_LDAP=ON -DCURL_DISABLE_LDAPS=ON `
            -DENABLE_UNICODE=ON -DCURL_CA_BUNDLE=none -DCURL_CA_PATH=none
    }
    Invoke-Checked 'curl build' { & $cmake --build (Join-Path $Root 'b-curl') }
    Invoke-Checked 'curl install' { & $cmake --install (Join-Path $Root 'b-curl') }
}

if (Test-Path $build) { Remove-Item -Recurse -Force $build }
Invoke-Checked 'nvattest configure' {
    & $cmake -S (Join-Path $repo 'nv-attestation-cli') -B $build -G 'NMake Makefiles' -DCMAKE_BUILD_TYPE=Release `
        -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTING=OFF -DNVAT_RELEASE_ARTIFACT=ON "-DNVAT_WINDOWS_DEPS_DIR=$deps"
}
Invoke-Checked 'nvattest build' { & $cmake --build $build }

$utcTest = Join-Path $build 'nvat_windows_utc_test.exe'
Invoke-Checked 'UTC self-test' { & $utcTest (Join-Path $PSScriptRoot 'tests\utc-vectors.json') }

# Stage the payload.
if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
New-Item -ItemType Directory -Force (Join-Path $dist 'bin'), (Join-Path $dist 'share\ca') | Out-Null
Copy-Item (Join-Path $build 'nvattest.exe') (Join-Path $dist 'bin')
$crtDir = Get-ChildItem -Directory (Join-Path $env:VCToolsRedistDir 'x64') -Filter 'Microsoft.VC*.CRT' | Select-Object -First 1
if (-not $crtDir) { throw 'Visual C++ x64 runtime redistributable directory not found' }
foreach ($dll in $inputs.msvc_runtime) {
    Copy-Item (Join-Path $crtDir.FullName $dll) (Join-Path $dist 'bin')
}
$targets = Get-Content -Raw (Join-Path $repo 'sol\release\targets.toml')
$caUrl = [regex]::Match($targets, '(?m)^ca_bundle_url\s*=\s*"([^"]+)"').Groups[1].Value
$caSha = [regex]::Match($targets, '(?m)^ca_bundle_sha256\s*=\s*"([0-9a-f]{64})"').Groups[1].Value
if (-not $caUrl -or -not $caSha) { throw 'targets.toml has no CA bundle pin' }
$caFile = Join-Path $downloads 'ca-bundle.pem'
if (-not (Test-Path $caFile) -or (Get-Sha256 $caFile) -ne $caSha) {
    Invoke-WebRequest -UseBasicParsing -Uri $caUrl -OutFile $caFile
}
if ((Get-Sha256 $caFile) -ne $caSha) { throw 'CA bundle digest mismatch' }
Copy-Item $caFile (Join-Path $dist 'share\ca\ca-bundle.pem')
Copy-Item (Join-Path $repo 'LICENSE') (Join-Path $dist 'LICENSE')

# Report.
$imports = (& dumpbin /nologo /dependents (Join-Path $dist 'bin\nvattest.exe')) |
    Where-Object { $_ -match '^\s+\S+\.dll\s*$' } | ForEach-Object { $_.Trim() }
$outputs = Get-ChildItem -Recurse -File $dist | Sort-Object FullName | ForEach-Object {
    [ordered]@{
        path = $_.FullName.Substring($dist.Length + 1).Replace('\', '/')
        bytes = $_.Length
        sha256 = Get-Sha256 $_.FullName
        file_version = $_.VersionInfo.FileVersion
    }
}
$report = [ordered]@{
    schema = 1
    source_commit = $(if (Test-Path (Join-Path $repo '.git')) { (& git -C $repo rev-parse HEAD) } else { $env:NVAT_SOURCE_COMMIT })
    source_clean = $(if (Test-Path (Join-Path $repo '.git')) { [string]::IsNullOrEmpty((& git -C $repo status --porcelain)) } else { $null })
    tools = [ordered]@{
        msvc = $env:VCToolsVersion
        vs = (& $vswhere -latest -property catalog_productDisplayVersion)
        windows_sdk = $env:WindowsSDKVersion
        cmake = ((& $cmake --version) | Select-Object -First 1)
        rustc = (& rustc -V)
        cargo = (& cargo -V)
        crt_redist = $crtDir.Name
    }
    sources = $sourceRecords
    build_tools = $toolRecords
    ca_bundle = [ordered]@{ url = $caUrl; sha256 = $caSha }
    imports = @($imports)
    outputs = @($outputs)
}
$report | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $Root 'build-report.json')
Write-Output "NVATTEST_WINDOWS_BUILD_OK $(Join-Path $dist 'bin\nvattest.exe')"
