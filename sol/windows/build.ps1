# Copyright (c) 2026 sol pbc
# SPDX-License-Identifier: Apache-2.0
#
# Builds the Windows verification-only nvattest from this checkout.
#
# Run from a PowerShell prompt on Windows with Visual Studio 2022 C++ build
# tools, CMake, Git and the Rust MSVC toolchain installed. The script fetches
# the pinned sources in inputs.json, verifies each SHA-256, builds the static
# dependencies, builds the verifier and stages:
#
#   <Root>\dist\nvattest\bin\nvattest.exe
#   <Root>\dist\nvattest\bin\{msvcp140,vcruntime140,vcruntime140_1}.dll
#   <Root>\dist\nvattest\share\ca\ca-bundle.pem
#   <Root>\dist\nvattest\LICENSE
#
# and <Root>\build-report.json with the tool versions, input digests, output
# digests and the executable's imported DLLs. Nothing is signed here.
# x64 runs the UTC self-test here. ARM64 retains it and its bound vectors under
# <Root>\validation for execution on native ARM64; the report remains pending.
#
# OpenSSL is configured with -DOSSL_WINCTX, so its configuration, engine and
# provider-module directories come only from an administrator-owned registry
# key that this build never creates. Callers must also clear OPENSSL_CONF and
# OPENSSL_MODULES to prevent environment-selected configuration or modules.

param(
    [string]$Root = 'C:\nvb',
    [ValidateSet('x64','arm64')]
    [string]$TargetArchitecture = 'x64',
    [switch]$ReuseDependencies,
    [string]$OfflineBundle,
    [ValidatePattern('^$|^[0-9a-f]{64}$')]
    [string]$OfflineManifestSha256
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
$rustTarget = if ($TargetArchitecture -eq 'arm64') { 'aarch64-pc-windows-msvc' } else { 'x86_64-pc-windows-msvc' }
$targetCmakeArguments = if ($TargetArchitecture -eq 'arm64') { @('-DCMAKE_SYSTEM_NAME=Windows','-DCMAKE_SYSTEM_PROCESSOR=ARM64') } else { @() }
if ($OfflineBundle) {
    if ($ReuseDependencies) { throw 'offline builds cannot reuse dependencies' }
    if (Test-Path -LiteralPath $Root) { throw 'offline builds require a fresh root' }
    $OfflineBundle = (Resolve-Path -LiteralPath $OfflineBundle).Path
}
New-Item -ItemType Directory -Force $downloads, $src | Out-Null

# Native tools report progress on stderr. Windows PowerShell turns redirected
# native stderr into error records, so judge them by exit code alone.
function Invoke-Checked([string]$what, [scriptblock]$block) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $block } finally { $ErrorActionPreference = $saved }
    if ($LASTEXITCODE -ne 0) { throw "$what failed with exit code $LASTEXITCODE" }
}

# CMake does not fail on an option it no longer knows: it warns that a
# manually-specified variable was not used and builds with the default. The
# dependency options below are part of the verifier's security configuration,
# so an ignored one fails the build instead of passing silently.
function Invoke-DependencyConfigure([string]$what, [string[]]$arguments) {
    $log = Join-Path $Root "configure-$what.log"
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $cmake @arguments 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log | Out-Host }
    finally { $ErrorActionPreference = $saved }
    if ($LASTEXITCODE -ne 0) { throw "$what configure failed with exit code $LASTEXITCODE" }
    if (Select-String -LiteralPath $log -SimpleMatch 'Manually-specified variables were not used' -Quiet) {
        throw "$what configure ignored a manually-specified variable; see $log"
    }
}

function Get-Sha256([string]$path) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
}

function Assert-TargetPE([string]$path) {
    $bytes = [IO.File]::ReadAllBytes($path)
    if ($bytes.Length -lt 64 -or $bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) { throw "Not a PE image: $path" }
    $offset = [BitConverter]::ToUInt32($bytes,0x3c)
    if ([long]$offset + 6 -gt $bytes.Length -or [BitConverter]::ToUInt32($bytes,$offset) -ne 0x4550) { throw "Invalid PE signature: $path" }
    $machine = [BitConverter]::ToUInt16($bytes,$offset+4)
    $expected = if ($TargetArchitecture -eq 'arm64') { 0xaa64 } else { 0x8664 }
    if ($machine -ne $expected) { throw "Wrong PE architecture for $TargetArchitecture : $path (machine=$machine)" }
    return [int]$machine
}

if ($OfflineBundle) {
    $manifestPath = Join-Path $OfflineBundle 'offline-manifest.json'
    if (-not $OfflineManifestSha256 -or (Get-Sha256 $manifestPath) -ne $OfflineManifestSha256) {
        throw 'offline manifest does not match the caller-bound digest'
    }
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or -not $manifest.files) { throw 'invalid offline manifest' }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($item in $manifest.files) {
        if ($item.path -notmatch '^[A-Za-z0-9_+.-]+(/[A-Za-z0-9_+.-]+)*$' -or
            @($item.path.Split('/') | Where-Object { $_ -eq '..' -or $_ -eq '.' }).Count -ne 0 -or
            -not $seen.Add($item.path)) { throw 'unsafe or duplicate offline input path' }
        $file = Join-Path $OfflineBundle $item.path
        $info = Get-Item -Force -LiteralPath $file
        if ($info.PSIsContainer -or $info.Length -ne $item.size -or
            (Get-Sha256 $file) -ne $item.sha256) { throw "missing or changed offline input: $($item.path)" }
    }
    foreach ($file in Get-ChildItem -Force -Recurse -LiteralPath $OfflineBundle) {
        if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'offline input contains a reparse point' }
        if (-not $file.PSIsContainer) {
            $relative = $file.FullName.Substring($OfflineBundle.Length + 1).Replace('\', '/')
            if ($relative -ne 'offline-manifest.json' -and -not $seen.Contains($relative)) {
                throw "unexpected offline input: $relative"
            }
        }
    }
} elseif ($OfflineManifestSha256) {
    throw 'offline manifest digest requires OfflineBundle'
}

function Get-Pinned($item, [string]$destination) {
    $file = Join-Path $downloads $item.name
    if ($OfflineBundle) {
        $inputFile = Join-Path $OfflineBundle $item.name
        if (-not (Test-Path -LiteralPath $inputFile -PathType Leaf) -or
            (Get-Sha256 $inputFile) -ne $item.sha256) {
            throw "missing or changed offline input: $($item.name)"
        }
        Copy-Item -LiteralPath $inputFile -Destination $file
    }
    if (-not (Test-Path -LiteralPath $file) -or (Get-Sha256 $file) -ne $item.sha256) {
        if ($OfflineBundle) { throw "offline input was changed: $($item.name)" }
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
$component = if ($TargetArchitecture -eq 'arm64') { 'Microsoft.VisualStudio.Component.VC.Tools.ARM64' } else { 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64' }
$vs = & $vswhere -latest -products '*' -requires $component -property installationPath
if ($LASTEXITCODE -ne 0 -or -not $vs) { throw "Visual Studio C++ $TargetArchitecture build tools not found" }
$vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvarsall.bat'
$vcTarget = if ($TargetArchitecture -eq 'arm64') { 'x64_arm64' } else { 'x64' }
cmd.exe /c "call `"$vcvars`" $vcTarget >nul && set" | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2] }
}
if ($LASTEXITCODE -ne 0) { throw "Visual Studio target environment failed: $LASTEXITCODE" }
if (-not $env:VCToolsRedistDir) { throw 'vcvars did not provide VCToolsRedistDir' }
$env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"

$sourceRecords = @()
foreach ($item in $inputs.sources) { $sourceRecords += Get-Pinned $item $src }
$toolRecords = @()
foreach ($item in $inputs.build_tools) { $toolRecords += Get-Pinned $item $Root }
$perlBin = Join-Path $Root 'perl\bin'
$cmake = 'cmake'
$offlineCmakeArguments = @()
if ($OfflineBundle) {
    $toolRecords += Get-Pinned $inputs.cmake_tool $Root
    $cmake = Join-Path $Root "$($inputs.cmake_tool.dir)\bin\cmake.exe"
    foreach ($item in $inputs.cmake_sources) {
        $sourceRecords += Get-Pinned $item $src
        $offlineCmakeArguments += "-DFETCHCONTENT_SOURCE_DIR_$($item.cmake_name)=$(Join-Path $src $item.dir)"
        if ($item.cmake_name -eq 'REGORUS') {
            # The pinned source archive has no .git directory. Its build script
            # otherwise launches git to embed the source revision. Bind that
            # metadata directly to the archive coordinate, without a PATH tool.
            $buildScript = Join-Path (Join-Path $src $item.dir) 'build.rs'
            if ($item.revision -notmatch '^[0-9a-f]{40}$' -or
                (Get-Sha256 $buildScript) -ne $item.build_script_sha256) {
                throw 'unexpected offline Regorus build script'
            }
            $old = @'
        let output = std::process::Command::new("git")
            .args(["rev-parse", "HEAD"])
            .output()
            .expect("`git rev-parse HEAD` failed.");
        let git_hash = String::from_utf8(output.stdout).unwrap();
'@
            $original = [IO.File]::ReadAllText($buildScript)
            if (-not $original.Contains($old)) { throw 'offline Regorus revision substitution failed' }
            $patched = $original.Replace($old, "        let git_hash = `"$($item.revision)`";")
            [IO.File]::WriteAllText($buildScript, $patched, [Text.UTF8Encoding]::new($false))
            $sourceRecords += [ordered]@{
                name = 'regorus-build-revision'; revision = $item.revision
                original_sha256 = $item.build_script_sha256; sha256 = (Get-Sha256 $buildScript)
            }
        }
    }
    $offlineCmakeArguments += '-DFETCHCONTENT_FULLY_DISCONNECTED=ON'
    $offlineCmakeArguments += '-DNVAT_OFFLINE_BUILD=ON'
    $env:CARGO_HOME = Join-Path $Root 'cargo-home'
    New-Item -ItemType Directory -Path $env:CARGO_HOME | Out-Null
    $vendorArchive = Join-Path $OfflineBundle 'cargo-vendor.tar.gz'
    $vendorPin = Get-Content -Raw (Join-Path $OfflineBundle 'cargo-vendor.json') | ConvertFrom-Json
    if ((Get-Sha256 $vendorArchive) -ne $vendorPin.sha256) { throw 'offline Cargo vendor digest mismatch' }
    if ($vendorPin.cargo_lock_sha256 -ne (Get-Sha256 (Join-Path $repo 'sol\release\regorus-Cargo.lock'))) {
        throw 'offline Cargo graph differs from the fork lock'
    }
    Invoke-Checked 'extract offline Cargo vendor' { tar.exe -xf $vendorArchive -C $Root }
    $vendorPath = (Join-Path $Root 'cargo-vendor').Replace('\', '/')
    @('[source.crates-io]', 'replace-with = "offline-vendor"', '[source.offline-vendor]', "directory = `"$vendorPath`"", '[net]', 'offline = true') |
        Set-Content -Encoding ASCII (Join-Path $env:CARGO_HOME 'config.toml')
    $env:CARGO_NET_OFFLINE = 'true'
}

if (-not ($ReuseDependencies -and (Test-Path (Join-Path $deps 'lib\libcurl.lib')))) {
    if (Test-Path $deps) { Remove-Item -Recurse -Force $deps }
    New-Item -ItemType Directory -Force $deps | Out-Null
    $env:CMAKE_BUILD_PARALLEL_LEVEL = [Environment]::ProcessorCount

    Push-Location (Join-Path $src 'openssl-3.6.5')
    $savedPath = $env:Path
    $env:Path = "$perlBin;$env:Path"
    $opensslTarget = if ($TargetArchitecture -eq 'arm64') { 'VC-WIN64-ARM' } else { 'VC-WIN64A' }
    Invoke-Checked 'OpenSSL configure' {
        perl Configure $opensslTarget no-asm no-shared no-tests no-apps no-docs no-legacy no-engine no-dtls `
            "--prefix=$deps" '--openssldir=C:\Windows\System32\nvat-openssl-unused' '--libdir=lib' `
            '-DOSSL_WINCTX=nvat-sol'
    }
    Invoke-Checked 'OpenSSL build' { nmake /nologo }
    Invoke-Checked 'OpenSSL install' { nmake /nologo install_dev }
    $env:Path = $savedPath
    Pop-Location

    Invoke-Checked 'zlib configure' { & $cmake -S (Join-Path $src 'zlib-1.3.1') -B (Join-Path $Root 'b-zlib') -G 'NMake Makefiles' -DCMAKE_BUILD_TYPE=Release "-DCMAKE_INSTALL_PREFIX=$deps" @targetCmakeArguments }
    Invoke-Checked 'zlib build' { & $cmake --build (Join-Path $Root 'b-zlib') }
    Invoke-Checked 'zlib install' { & $cmake --install (Join-Path $Root 'b-zlib') }

    Invoke-DependencyConfigure 'libxml2' (@(
        '-S', (Join-Path $src 'libxml2-2.11.9'), '-B', (Join-Path $Root 'b-libxml2'), '-G', 'NMake Makefiles', '-DCMAKE_BUILD_TYPE=Release', "-DCMAKE_INSTALL_PREFIX=$deps",
        '-DBUILD_SHARED_LIBS=OFF', '-DLIBXML2_WITH_ICONV=OFF', '-DLIBXML2_WITH_LZMA=OFF', '-DLIBXML2_WITH_PYTHON=OFF', '-DLIBXML2_WITH_ZLIB=OFF',
        '-DLIBXML2_WITH_HTTP=OFF', '-DLIBXML2_WITH_FTP=OFF', '-DLIBXML2_WITH_CATALOG=OFF', '-DLIBXML2_WITH_TESTS=OFF', '-DLIBXML2_WITH_PROGRAMS=OFF') + $targetCmakeArguments)
    Invoke-Checked 'libxml2 build' { & $cmake --build (Join-Path $Root 'b-libxml2') }
    Invoke-Checked 'libxml2 install' { & $cmake --install (Join-Path $Root 'b-libxml2') }
    # xmlsec's MSVC makefile names the static libxml2 archive libxml2_a.lib.
    Copy-Item (Join-Path $deps 'lib\libxml2s.lib') (Join-Path $deps 'lib\libxml2_a.lib') -Force

    Push-Location (Join-Path $src 'xmlsec1-1.2.43\win32')
    Invoke-Checked 'xmlsec configure' {
        cscript //NoLogo configure.js "prefix=$deps" "include=$deps\include;$deps\include\libxml2" "lib=$deps\lib" `
            crypto=openssl-300 xslt=no iconv=no static=yes with-dl=no with-openssl3-engines=no cruntime=/MD
    }
    Invoke-Checked 'xmlsec build' { nmake /nologo /f Makefile.msvc xmlseca openssla }
    New-Item -ItemType Directory -Force (Join-Path $deps 'include\xmlsec1\xmlsec') | Out-Null
    Copy-Item -Recurse -Force ..\include\xmlsec\* (Join-Path $deps 'include\xmlsec1\xmlsec')
    Copy-Item binaries\libxmlsec_a.lib, binaries\libxmlsec-openssl_a.lib (Join-Path $deps 'lib')
    Pop-Location

    # curl 8 builds documentation, tests and examples by default and probes for
    # optional libraries; the build names every one it turns off. No CA bundle,
    # CA path or OpenSSL fallback store is compiled in: the SDK hands curl the
    # pinned bundle as a blob.
    Invoke-DependencyConfigure 'curl' (@(
        '-S', (Join-Path $src 'curl-8.23.0'), '-B', (Join-Path $Root 'b-curl'), '-G', 'NMake Makefiles', '-DCMAKE_BUILD_TYPE=Release', "-DCMAKE_INSTALL_PREFIX=$deps",
        "-DOPENSSL_ROOT_DIR=$deps", '-DOPENSSL_USE_STATIC_LIBS=ON', '-DBUILD_SHARED_LIBS=OFF', '-DBUILD_STATIC_LIBS=ON', '-DBUILD_CURL_EXE=OFF', '-DCURL_USE_OPENSSL=ON',
        '-DCURL_USE_SCHANNEL=OFF', '-DCURL_USE_LIBSSH2=OFF', '-DCURL_USE_LIBPSL=OFF', '-DCURL_ZLIB=OFF', '-DCURL_BROTLI=OFF', '-DCURL_ZSTD=OFF',
        '-DUSE_NGHTTP2=OFF', '-DUSE_LIBIDN2=OFF', '-DCURL_DISABLE_LDAP=ON', '-DCURL_DISABLE_LDAPS=ON', '-DENABLE_UNICODE=ON',
        '-DCURL_CA_BUNDLE=none', '-DCURL_CA_PATH=none', '-DCURL_CA_FALLBACK=OFF',
        '-DBUILD_TESTING=OFF', '-DBUILD_EXAMPLES=OFF', '-DBUILD_LIBCURL_DOCS=OFF', '-DBUILD_MISC_DOCS=OFF', '-DENABLE_CURL_MANUAL=OFF') + $targetCmakeArguments)
    Invoke-Checked 'curl build' { & $cmake --build (Join-Path $Root 'b-curl') }
    Invoke-Checked 'curl install' { & $cmake --install (Join-Path $Root 'b-curl') }
}

if (Test-Path $build) { Remove-Item -Recurse -Force $build }
Invoke-Checked 'nvattest configure' {
    & $cmake -S (Join-Path $repo 'nv-attestation-cli') -B $build -G 'NMake Makefiles' -DCMAKE_BUILD_TYPE=Release `
        -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTING=OFF -DNVAT_RELEASE_ARTIFACT=ON "-DNVAT_WINDOWS_DEPS_DIR=$deps" "-DRust_CARGO_TARGET=$rustTarget" @targetCmakeArguments @offlineCmakeArguments
}
Invoke-Checked 'nvattest build' { & $cmake --build $build }

$utcTest = Join-Path $build 'nvat_windows_utc_test.exe'
$null = Assert-TargetPE $utcTest
$utcVectors = Join-Path $PSScriptRoot 'tests\utc-vectors.json'
$nativeValidation = if ($TargetArchitecture -eq 'arm64') { 'pending' } else { 'passed' }
if ($TargetArchitecture -eq 'arm64') {
    $validationRoot = Join-Path $Root 'validation'
    New-Item -ItemType Directory -Path $validationRoot | Out-Null
    Copy-Item $utcTest (Join-Path $validationRoot 'nvat_windows_utc_test.exe')
    Copy-Item $utcVectors (Join-Path $validationRoot 'utc-vectors.json')
} else {
    Invoke-Checked 'UTC self-test' { & $utcTest $utcVectors }
}

# Stage the payload.
if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
New-Item -ItemType Directory -Force (Join-Path $dist 'bin'), (Join-Path $dist 'share\ca') | Out-Null
Copy-Item (Join-Path $build 'nvattest.exe') (Join-Path $dist 'bin')
$crtDir = Get-ChildItem -Directory (Join-Path $env:VCToolsRedistDir $TargetArchitecture) -Filter 'Microsoft.VC*.CRT' | Select-Object -First 1
if (-not $crtDir) { throw "Visual C++ $TargetArchitecture runtime redistributable directory not found" }
$runtimeFiles = if ($TargetArchitecture -eq 'arm64') { $inputs.msvc_runtime_arm64 } else { $inputs.msvc_runtime }
foreach ($dll in $runtimeFiles) {
    Copy-Item (Join-Path $crtDir.FullName $dll) (Join-Path $dist 'bin')
}
$targets = Get-Content -Raw (Join-Path $repo 'sol\release\targets.toml')
$caUrl = [regex]::Match($targets, '(?m)^ca_bundle_url\s*=\s*"([^"]+)"').Groups[1].Value
$caSha = [regex]::Match($targets, '(?m)^ca_bundle_sha256\s*=\s*"([0-9a-f]{64})"').Groups[1].Value
if (-not $caUrl -or -not $caSha) { throw 'targets.toml has no CA bundle pin' }
$caFile = Join-Path $downloads 'ca-bundle.pem'
if ($OfflineBundle) {
    $offlineCa = Join-Path $OfflineBundle 'ca-bundle.pem'
    if ((Get-Sha256 $offlineCa) -ne $caSha) { throw 'offline CA digest mismatch' }
    Copy-Item -LiteralPath $offlineCa -Destination $caFile
}
if (-not (Test-Path $caFile) -or (Get-Sha256 $caFile) -ne $caSha) {
    if ($OfflineBundle) { throw 'offline CA was changed' }
    Invoke-WebRequest -UseBasicParsing -Uri $caUrl -OutFile $caFile
}
if ((Get-Sha256 $caFile) -ne $caSha) { throw 'CA bundle digest mismatch' }
Copy-Item $caFile (Join-Path $dist 'share\ca\ca-bundle.pem')
Copy-Item (Join-Path $repo 'LICENSE') (Join-Path $dist 'LICENSE')

# Report.
$imports = (& dumpbin /nologo /dependents (Join-Path $dist 'bin\nvattest.exe')) |
    Where-Object { $_ -match '^\s+\S+\.dll\s*$' } | ForEach-Object { $_.Trim() }
$outputs = Get-ChildItem -Recurse -File $dist | Sort-Object FullName | ForEach-Object {
    if ($_.Extension -in @('.exe','.dll')) { $null = Assert-TargetPE $_.FullName }
    [ordered]@{
        path = $_.FullName.Substring($dist.Length + 1).Replace('\', '/')
        bytes = $_.Length
        sha256 = Get-Sha256 $_.FullName
        file_version = $_.VersionInfo.FileVersion
    }
}
$report = [ordered]@{
    schema = 1
    target_architecture = $TargetArchitecture
    target_triple = $rustTarget
    native_validation = [ordered]@{ status = $nativeValidation; executable_sha256 = (Get-Sha256 $utcTest); vectors_sha256 = (Get-Sha256 $utcVectors) }
    source_commit = $(if (Test-Path (Join-Path $repo '.git')) { (& git -C $repo rev-parse HEAD) } else { $env:NVAT_SOURCE_COMMIT })
    source_clean = $(if (Test-Path (Join-Path $repo '.git')) { [string]::IsNullOrEmpty((& git -C $repo status --porcelain)) } else { $null })
    tools = [ordered]@{
        msvc = $env:VCToolsVersion
        vs = (& $vswhere -latest -products '*' -requires $component -property catalog_productDisplayVersion)
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
if ($TargetArchitecture -eq 'arm64') { Write-Output "NVATTEST_WINDOWS_CROSS_BUILD_READY_FOR_NATIVE_TEST $(Join-Path $dist 'bin\nvattest.exe')" }
else { Write-Output "NVATTEST_WINDOWS_BUILD_OK $(Join-Path $dist 'bin\nvattest.exe')" }
