[CmdletBinding()]
param(
    [ValidateSet('InitializeSigning', 'Check', 'VerifyGuards', 'Build')]
    [string]$Action = 'Check',
    [ValidateSet('customer', 'delivery', 'both')]
    [string]$App = 'both',
    [string]$VerifiedApiOrigin
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
$workspace = Split-Path -Parent $PSScriptRoot
$privateRoot = Join-Path $workspace '.private\review-signing'
$runtimeRoot = Join-Path $workspace '.runtime\android-review'
$purpose = 'SupplyOS dedicated Android review signing v1'
$entropy = [Text.Encoding]::UTF8.GetBytes($purpose)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
$allowedSids = @($identity.Value, 'S-1-5-18', 'S-1-5-32-544')
$environmentNames = @(
    'SUPPLYOS_REVIEW_KEYSTORE', 'SUPPLYOS_REVIEW_KEY_ALIAS', 'SUPPLYOS_REVIEW_STORE_PASSWORD',
    'SUPPLYOS_REVIEW_KEY_PASSWORD', 'SUPPLYOS_REVIEW_CERT_SHA256', 'SUPPLYOS_REVIEW_API_ORIGIN',
    'SUPPLYOS_REVIEW_NDK_PATH', 'GRADLE_USER_HOME', 'TEMP', 'TMP', 'ANDROID_HOME', 'ANDROID_SDK_ROOT',
    'FLUTTER_SUPPRESS_ANALYTICS', 'CI'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$redactions = [Collections.Generic.List[string]]::new()
$phase = 'validating the explicit action and verified-origin gate'

function New-PrivateAcl([bool]$Directory) {
    if ($Directory) {
        $acl = [Security.AccessControl.DirectorySecurity]::new()
        $inheritance = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    } else {
        $acl = [Security.AccessControl.FileSecurity]::new()
        $inheritance = [Security.AccessControl.InheritanceFlags]::None
    }
    $acl.SetOwner($identity)
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in $allowedSids) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            [Security.Principal.SecurityIdentifier]::new($sid),
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow
        )
        $acl.AddAccessRule($rule)
    }
    return $acl
}

function Assert-PrivateItem([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Review signing refuses reparse points.'
    }
    $acl = Get-Acl -LiteralPath $Path
    if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $identity.Value -or
        -not $acl.AreAccessRulesProtected) {
        throw 'Existing review signing must have its original owner and protected ACL; it is not repaired.'
    }
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -notin $allowedSids) {
            throw 'Existing review signing grants access outside its owner, SYSTEM and Administrators.'
        }
    }
}

function New-PrivateDirectory([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        Assert-PrivateItem $Path
        if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
            throw 'A review signing directory path is occupied by a file.'
        }
        return
    }
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw 'Review signing directory parent is absent.'
    }
    [void][IO.Directory]::CreateDirectory($Path, (New-PrivateAcl $true))
    Assert-PrivateItem $Path
}

function Write-NewPrivateFile([string]$Path, [byte[]]$Bytes) {
    Assert-PrivateItem (Split-Path -Parent $Path)
    $stream = [IO.FileStream]::new($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $stream.Write($Bytes, 0, $Bytes.Length)
    } finally {
        $stream.Dispose()
    }
    [IO.File]::SetAccessControl($Path, (New-PrivateAcl $false))
    Assert-PrivateItem $Path
}

function Quote-NativeArgument([string]$Value) {
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Resolve-Keytool {
    $installed = Get-Command keytool.exe -ErrorAction SilentlyContinue
    if ($installed) { return $installed.Source }
    # Oracle's PATH shim exposes java but not the rest of the already-installed JDK.
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = (Get-Command java.exe -ErrorAction Stop).Source
    $start.Arguments = '-XshowSettings:properties -version'
    $start.UseShellExecute = $false
    $start.RedirectStandardError = $true
    $start.RedirectStandardOutput = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        $details = $process.StandardError.ReadToEnd()
        [void]$process.StandardOutput.ReadToEnd()
        $process.WaitForExit()
        $javaHome = [regex]::Match($details, '(?m)^\s*java\.home = (.+)$').Groups[1].Value.Trim()
        if ($process.ExitCode -ne 0 -or -not $javaHome) { throw 'Installed JDK discovery failed.' }
        $keytool = Join-Path $javaHome 'bin\keytool.exe'
        if (-not (Test-Path -LiteralPath $keytool -PathType Leaf)) { throw 'Installed JDK keytool is absent.' }
        return $keytool
    } finally {
        $process.Dispose()
    }
}

function Invoke-ReviewProgram(
    [string]$Program, [string[]]$Arguments, [string]$Directory,
    [bool]$Quiet = $false, [string]$ExpectedFailure = ''
) {
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Program
    $start.Arguments = ($Arguments | ForEach-Object { Quote-NativeArgument $_ }) -join ' '
    if ([IO.Path]::GetExtension($Program) -in @('.bat', '.cmd')) {
        $start.FileName = $env:ComSpec
        $start.Arguments = '/d /s /c "' + (Quote-NativeArgument $Program) + ' ' + $start.Arguments + '"'
    }
    $start.WorkingDirectory = $Directory
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    $started = $false
    try {
        [void]$process.Start()
        $started = $true
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $output = $stdout.Result + $stderr.Result
        if ($ExpectedFailure) {
            if ($process.ExitCode -eq 0 -or -not $output.Contains($ExpectedFailure)) {
                throw 'A review release guard did not reject the expected unsafe configuration.'
            }
            'Guard passed: ' + $ExpectedFailure
            return
        }
        if (-not $Quiet) {
            foreach ($secret in $redactions) {
                $output = $output.Replace($secret, '[redacted]')
            }
            if ($output) { $output.TrimEnd() }
        }
        if ($process.ExitCode -ne 0) {
            throw 'The Android review tool failed; secret-bearing tool details are suppressed.'
        }
    } finally {
        if ($started -and -not $process.HasExited) { $process.Kill() }
        $process.Dispose()
    }
}

function Get-ReviewCredentials([string]$Path) {
    Assert-PrivateItem $Path
    $plain = $null
    try {
        $plain = [Security.Cryptography.ProtectedData]::Unprotect(
            [IO.File]::ReadAllBytes($Path), $entropy, [Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        $credentials = [Text.Encoding]::UTF8.GetString($plain) | ConvertFrom-Json
        if ($credentials.purpose -ne $purpose -or $credentials.password -notmatch '^[A-Za-z0-9+/]{43}=$') {
            throw 'Invalid protected review credentials.'
        }
        return $credentials
    } catch {
        throw 'The original protected review credentials could not be loaded; no keys were replaced.'
    } finally {
        if ($plain) { [Array]::Clear($plain, 0, $plain.Length) }
    }
}

function Set-ReviewSigning([string]$Directory, [string]$Alias, [string]$Password, [string]$Fingerprint) {
    [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_KEYSTORE', (Join-Path $Directory 'review.p12'), 'Process')
    [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_KEY_ALIAS', $Alias, 'Process')
    [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_STORE_PASSWORD', $Password, 'Process')
    [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_KEY_PASSWORD', $Password, 'Process')
    [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_CERT_SHA256', $Fingerprint, 'Process')
    $redactions.Add($Password)
}

function Assert-ApiOrigin([string]$Origin) {
    $uri = $null
    if (-not $Origin -or $Origin -match '[\s\\%@]' -or
        -not [Uri]::TryCreate($Origin, [UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or
        $uri.AbsolutePath -ne '/' -or $uri.HostNameType -ne 'Dns' -or
        $uri.Port -lt 1 -or $uri.Port -gt 65535) {
        throw 'Build requires a parent-verified canonical public HTTPS API origin, not an API path.'
    }
    $hostName = $uri.DnsSafeHost.ToLowerInvariant()
    $forbidden = @('localhost', 'local', 'internal', 'lan', 'home', 'home.arpa', 'corp',
        'intranet', 'private', 'onion', 'localtest.me', 'lvh.me', 'localhost.direct',
        'nip.io', 'sslip.io', 'test', 'invalid', 'example', 'example.com', 'example.net',
        'example.org', 'ngrok.io', 'ngrok-free.app', 'trycloudflare.com')
    if ($hostName.Length -gt 253 -or $hostName -notmatch '^[a-z0-9-]+(?:\.[a-z0-9-]+)+$' -or
        $hostName -notmatch '\.[a-z]{2,63}$' -or
        $hostName -match '(placeholder|your-?(api|domain|host)|change-?me)' -or
        @($hostName.Split('.') | Where-Object { $_.Length -gt 63 -or $_.StartsWith('-') -or $_.EndsWith('-') }).Count -or
        @($forbidden | Where-Object { $hostName -eq $_ -or $hostName.EndsWith('.' + $_) }).Count) {
        throw 'Build refuses private, placeholder, reserved and tunnel API hosts.'
    }
    return $Origin.TrimEnd('/')
}

try {
    if ($Action -eq 'Build') {
        $VerifiedApiOrigin = Assert-ApiOrigin $VerifiedApiOrigin
    } elseif ($VerifiedApiOrigin) {
        throw 'API origins are accepted only for an explicitly requested final Build.'
    }
    if (-not (Test-Path -LiteralPath $workspace -PathType Container)) {
        throw 'The workspace parent is absent.'
    }
    if ($Action -eq 'InitializeSigning') {
        $phase = 'creating owner-protected private review directories'
        New-PrivateDirectory (Join-Path $workspace '.private')
        New-PrivateDirectory $privateRoot
        New-PrivateDirectory (Join-Path $privateRoot 'adb')
    } else {
        Assert-PrivateItem (Join-Path $workspace '.private')
        Assert-PrivateItem $privateRoot
    }
    $apps = if ($App -eq 'both') { @('customer', 'delivery') } else { @($App) }
    $phase = 'locating the installed JDK keytool without changing Java'
    $keytool = Resolve-Keytool
    foreach ($appName in $apps) {
        $phase = 'initializing or loading original dedicated ' + $appName + ' review signing'
        $directory = Join-Path $privateRoot $appName
        $alias = 'supplyos-' + $appName + '-review'
        $packageId = 'com.supplyos.' + $appName + '.review'
        $credentialPath = Join-Path $directory 'credentials.dpapi'
        $metadataPath = Join-Path $directory 'public.json'
        $keystore = Join-Path $directory 'review.p12'
        $certificatePath = Join-Path $directory 'review.cer'
        if ($Action -eq 'InitializeSigning') {
            New-PrivateDirectory $directory
            $existing = @($credentialPath, $metadataPath, $keystore, $certificatePath | Where-Object { Test-Path -LiteralPath $_ })
            if ($existing.Count -eq 0) {
                $random = [byte[]]::new(32)
                $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
                try {
                    $generator.GetBytes($random)
                    $password = [Convert]::ToBase64String($random)
                } finally {
                    $generator.Dispose()
                    [Array]::Clear($random, 0, $random.Length)
                }
                $plain = [Text.Encoding]::UTF8.GetBytes((@{ purpose = $purpose; password = $password } | ConvertTo-Json -Compress))
                try {
                    $protected = [Security.Cryptography.ProtectedData]::Protect(
                        $plain, $entropy, [Security.Cryptography.DataProtectionScope]::CurrentUser
                    )
                    Write-NewPrivateFile $credentialPath $protected
                } finally {
                    [Array]::Clear($plain, 0, $plain.Length)
                }
                Set-ReviewSigning $directory $alias $password ''
                Invoke-ReviewProgram $keytool @('-genkeypair', '-keystore', $keystore, '-storetype', 'PKCS12',
                    '-alias', $alias, '-storepass:env', 'SUPPLYOS_REVIEW_STORE_PASSWORD',
                    '-keypass:env', 'SUPPLYOS_REVIEW_KEY_PASSWORD', '-keyalg', 'RSA', '-keysize', '3072',
                    '-sigalg', 'SHA256withRSA', '-validity', '365', '-dname',
                    "CN=SupplyOS $appName Review,OU=SupplyOS Android Review,O=SupplyOS", '-noprompt') $directory $true
                [IO.File]::SetAccessControl($keystore, (New-PrivateAcl $false))
                Invoke-ReviewProgram $keytool @('-exportcert', '-keystore', $keystore, '-storetype', 'PKCS12',
                    '-alias', $alias, '-storepass:env', 'SUPPLYOS_REVIEW_STORE_PASSWORD', '-file', $certificatePath) $directory $true
                [IO.File]::SetAccessControl($certificatePath, (New-PrivateAcl $false))
                $certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new($certificatePath)
                $sha256 = [Security.Cryptography.SHA256]::Create()
                try {
                    $fingerprint = [BitConverter]::ToString($sha256.ComputeHash($certificate.RawData)).Replace('-', '').ToLowerInvariant()
                    $metadata = @{ purpose = $purpose; packageId = $packageId; alias = $alias
                        certificateSha256 = $fingerprint; certificateSha1 = $certificate.Thumbprint.ToLowerInvariant() }
                    Write-NewPrivateFile $metadataPath ([Text.Encoding]::UTF8.GetBytes(($metadata | ConvertTo-Json)))
                } finally {
                    $sha256.Dispose()
                    $certificate.Dispose()
                }
            } elseif ($existing.Count -ne 4) {
                throw 'Partial existing review signing is preserved; initialization will not replace it.'
            }
        }
        Assert-PrivateItem $directory
        foreach ($path in @($credentialPath, $metadataPath, $keystore, $certificatePath)) { Assert-PrivateItem $path }
        $metadata = [IO.File]::ReadAllText($metadataPath) | ConvertFrom-Json
        if ($metadata.purpose -ne $purpose -or $metadata.packageId -ne $packageId -or $metadata.alias -ne $alias -or
            $metadata.certificateSha256 -notmatch '^[a-f0-9]{64}$') {
            throw 'Existing public review signing references do not match this app.'
        }
        $credentials = Get-ReviewCredentials $credentialPath
        Set-ReviewSigning $directory $alias $credentials.password $metadata.certificateSha256
        if ($Action -eq 'InitializeSigning') {
            "Review signing ready: $packageId; alias=$alias; SHA256=$($metadata.certificateSha256); SHA1=$($metadata.certificateSha1)"
            continue
        }
        foreach ($path in @($runtimeRoot, (Join-Path $runtimeRoot 'gradle'), (Join-Path $runtimeRoot 'tmp'))) {
            if (-not (Test-Path -LiteralPath (Split-Path -Parent $path) -PathType Container)) {
                [void][IO.Directory]::CreateDirectory((Split-Path -Parent $path))
            }
            if (Test-Path -LiteralPath $path) {
                if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                    throw 'Review runtime directories must not be reparse points.'
                }
            } else {
                [void][IO.Directory]::CreateDirectory($path)
            }
        }
        $appRoot = Join-Path $PSScriptRoot ($appName + '_app')
        $androidRoot = Join-Path $appRoot 'android'
        $properties = @{}
        foreach ($line in [IO.File]::ReadAllLines((Join-Path $androidRoot 'local.properties'))) {
            if ($line -match '^(sdk\.dir|flutter\.sdk)=(.*)$') {
                $properties[$Matches[1]] = $Matches[2].Replace('\\', '\').Replace('\:', ':')
            }
        }
        $flutterRoot = $properties['flutter.sdk']
        $sdkRoot = $properties['sdk.dir']
        if (-not $flutterRoot -or -not $sdkRoot -or -not (Test-Path -LiteralPath $sdkRoot -PathType Container)) {
            throw 'Existing local.properties must identify the installed Flutter and original Android SDK.'
        }
        $extension = [IO.File]::ReadAllText((Join-Path $flutterRoot 'packages\flutter_tools\gradle\src\main\kotlin\FlutterExtension.kt'))
        if ($extension -notmatch 'val ndkVersion: String = "([0-9.]+)"') {
            throw 'The cached Flutter NDK requirement could not be verified.'
        }
        $externalNdk = Join-Path $runtimeRoot ('toolchain\ndk\' + $Matches[1])
        if (Test-Path -LiteralPath (Join-Path $externalNdk 'source.properties')) {
            [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_NDK_PATH', $externalNdk, 'Process')
        } else {
            [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_NDK_PATH', $null, 'Process')
        }
        [Environment]::SetEnvironmentVariable('GRADLE_USER_HOME', (Join-Path $runtimeRoot 'gradle'), 'Process')
        [Environment]::SetEnvironmentVariable('TEMP', (Join-Path $runtimeRoot 'tmp'), 'Process')
        [Environment]::SetEnvironmentVariable('TMP', (Join-Path $runtimeRoot 'tmp'), 'Process')
        [Environment]::SetEnvironmentVariable('ANDROID_HOME', $sdkRoot, 'Process')
        [Environment]::SetEnvironmentVariable('ANDROID_SDK_ROOT', $sdkRoot, 'Process')
        [Environment]::SetEnvironmentVariable('FLUTTER_SUPPRESS_ANALYTICS', 'true', 'Process')
        [Environment]::SetEnvironmentVariable('CI', 'true', 'Process')
        if ($Action -in @('Check', 'VerifyGuards')) {
            $phase = 'checking ' + $appName + ' Gradle configuration and native resources'
            [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_API_ORIGIN', $null, 'Process')
            $wrapper = Join-Path $androidRoot 'gradlew.bat'
            $gradleArguments = @('--no-daemon', '--no-configuration-cache',
                '--console=plain', '--max-workers=2', '-Dorg.gradle.jvmargs=-Xmx3G -XX:MaxMetaspaceSize=1G -XX:ReservedCodeCacheSize=256m',
                '-Dorg.gradle.java.installations.auto-download=false')
            if ($Action -eq 'Check') {
                "Checking $packageId configuration and native manifest/resources only; no client APK is built."
                Invoke-ReviewProgram $wrapper ($gradleArguments + @(':app:verifyReviewPreparation',
                    ':app:processReviewReleaseMainManifest', ':app:mergeReviewReleaseResources')) $androidRoot
            } else {
                $phase = 'verifying negative release guard regressions for ' + $appName
                "Verifying $packageId fail-closed guards; all artifact tasks use --dry-run."
                $signingHold = 'Release artifacts are held until private non-debug signing is configured externally.'
                [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_STORE_PASSWORD', $null, 'Process')
                Invoke-ReviewProgram $wrapper ($gradleArguments + @(':app:verifyReviewPreparation')) $androidRoot $false $signingHold
                [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_STORE_PASSWORD', $credentials.password, 'Process')
                [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_KEY_ALIAS', 'AndroidDebugKey', 'Process')
                Invoke-ReviewProgram $wrapper ($gradleArguments + @(':app:verifyReviewPreparation')) $androidRoot $false $signingHold
                [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_KEY_ALIAS', $alias, 'Process')
                [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_CERT_SHA256', ('0' * 64), 'Process')
                Invoke-ReviewProgram $wrapper ($gradleArguments + @(':app:verifyReviewPreparation')) $androidRoot $false `
                    'The dedicated review key and public certificate reference could not be verified.'
                [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_CERT_SHA256', $metadata.certificateSha256, 'Process')
                Invoke-ReviewProgram $wrapper ($gradleArguments + @(':app:assembleProductionRelease', '--dry-run')) $androidRoot $false $signingHold
                Invoke-ReviewProgram $wrapper ($gradleArguments + @(':app:assembleReviewRelease', '--dry-run')) $androidRoot $false `
                    'Review APKs are held until a parent-verified public HTTPS API origin and matching Dart define are supplied.'
                $unsafeFlags = Join-Path $runtimeRoot 'test-release-flags.gradle'
                if (-not (Test-Path -LiteralPath $unsafeFlags -PathType Leaf)) {
                    throw 'The owned release-flags regression init script is absent.'
                }
                Invoke-ReviewProgram $wrapper ($gradleArguments + @('--init-script', $unsafeFlags,
                    ':app:verifyReviewPreparation')) $androidRoot $false $signingHold
                Invoke-ReviewProgram $wrapper ($gradleArguments + @('--init-script', $unsafeFlags,
                    '-PreviewGuardTestJni=true', ':app:verifyReviewPreparation')) $androidRoot $false $signingHold
                "Seven negative Gradle guard regressions passed for $packageId; no APK was produced."
            }
        } else {
            $phase = 'building the explicitly verified ' + $appName + ' review release'
            [Environment]::SetEnvironmentVariable('SUPPLYOS_REVIEW_API_ORIGIN', $VerifiedApiOrigin, 'Process')
            "Building isolated non-debuggable review release: $packageId"
            $flutter = Join-Path $flutterRoot 'bin\flutter.bat'
            Invoke-ReviewProgram $flutter @('build', 'apk', '--release', '--flavor', 'review',
                '--no-pub', '--target-platform', 'android-arm,android-arm64,android-x64',
                ('--dart-define=SUPPLYOS_API_BASE=' + $VerifiedApiOrigin + '/api/v1')) $appRoot
            $apk = Join-Path $appRoot 'build\app\outputs\flutter-apk\app-review-release.apk'
            if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) { throw 'Expected review APK is absent.' }
            $tools = Join-Path $sdkRoot 'build-tools\36.0.0'
            $signerOutput = Invoke-ReviewProgram (Join-Path $tools 'apksigner.bat') @('verify', '--print-certs', $apk) $appRoot
            if (($signerOutput -join "`n") -notmatch ('certificate SHA-256 digest: ' + $metadata.certificateSha256)) {
                throw 'The APK does not match the original dedicated public review certificate.'
            }
            $badging = Invoke-ReviewProgram (Join-Path $tools 'aapt.exe') @('dump', 'badging', $apk) $appRoot
            $badgingText = $badging -join "`n"
            $label = 'SupplyOS ' + [Globalization.CultureInfo]::InvariantCulture.TextInfo.ToTitleCase($appName) + ' Review'
            if (-not $badgingText.Contains("package: name='$packageId'") -or
                $badgingText -notmatch "versionName='[^']+-review'" -or
                $badgingText -match 'application-debuggable' -or
                -not $badgingText.Contains("application-label:'$label'")) {
                throw 'The APK review identity, visible label, version or non-debuggable boundary is invalid.'
            }
            "Verified review APK: $apk; SHA256 certificate=$($metadata.certificateSha256)"
        }
    }
} catch {
    # Do not attach native/JSON/provider exceptions, which may echo private input.
    [Console]::Error.WriteLine('Android review preparation failed while ' + $phase + '. Existing private files were preserved; inspect only sanitized tool output.')
    exit 1
} finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
    $redactions.Clear()
}
