[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,

    [Parameter(Mandatory = $true)]
    [string]$VenvPath,

    [Parameter(Mandatory = $true)]
    [string]$RequirementsPath
)

$ErrorActionPreference = "Stop"

function Stop-Bootstrap {
    param([string]$Message)

    Write-Host "[run2 bootstrap] $Message"
    exit 1
}

function Get-FullPath {
    param([string]$Path)

    return [System.IO.Path]::GetFullPath($Path)
}

try {
    $repositoryFullPath = Get-FullPath $RepositoryRoot
    $venvFullPath = Get-FullPath $VenvPath
    $requirementsFullPath = Get-FullPath $RequirementsPath

    if (-not (Test-Path -LiteralPath $requirementsFullPath -PathType Leaf)) {
        Stop-Bootstrap "Canonical dependency file not found: $requirementsFullPath"
    }

    $repositoryPrefix = $repositoryFullPath.TrimEnd('\') + '\'
    if ($venvFullPath.StartsWith($repositoryPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        Stop-Bootstrap "The runtime path must be outside the synchronized repository: $venvFullPath"
    }

    $venvPython = Join-Path $venvFullPath 'Scripts\python.exe'
    $managedMarker = Join-Path $venvFullPath '.sgaa-managed'
    $requirementsMarker = Join-Path $venvFullPath '.sgaa-requirements.sha256'

    Write-Host "[run2 bootstrap] Ignoring synchronized repository .venv and venv; virtualenvs are machine-specific."

    function Get-RejectionReason {
        param([string]$Candidate)

        $candidateFullPath = Get-FullPath $Candidate
        $candidateLower = $candidateFullPath.ToLowerInvariant()

        if ($candidateLower.Contains('\hermes\')) {
            return 'Hermes interpreter'
        }
        if ($candidateLower.Contains('\windowsapps\')) {
            return 'Microsoft Store/WindowsApps alias'
        }
        if ($candidateFullPath.StartsWith($repositoryPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $relative = $candidateFullPath.Substring($repositoryPrefix.Length)
            if ($relative.StartsWith('.venv\', [System.StringComparison]::OrdinalIgnoreCase) -or
                $relative.StartsWith('venv\', [System.StringComparison]::OrdinalIgnoreCase)) {
                return 'synchronized repository virtualenv'
            }
        }

        $probeDirectory = Split-Path -Parent $candidateFullPath
        while ($probeDirectory) {
            if (Test-Path -LiteralPath (Join-Path $probeDirectory 'pyvenv.cfg') -PathType Leaf) {
                return 'another virtualenv'
            }
            $parent = Split-Path -Parent $probeDirectory
            if ($parent -eq $probeDirectory) {
                break
            }
            $probeDirectory = $parent
        }

        return $null
    }

    function Get-PythonInfo {
        param([string]$Candidate)

        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            return $null
        }

        $reason = Get-RejectionReason $Candidate
        if ($reason) {
            Write-Host "[run2 bootstrap] Rejected Python candidate ($reason): $Candidate"
            return $null
        }

        try {
            $probe = & $Candidate -E -s -c "import json,sys; print(json.dumps({'executable': sys.executable, 'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'major': sys.version_info.major, 'minor': sys.version_info.minor}))" 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $probe) {
                return $null
            }
            $info = $probe | ConvertFrom-Json
            if ([int]$info.major -lt 3 -or ([int]$info.major -eq 3 -and [int]$info.minor -lt 10)) {
                return $null
            }
            if ($info.prefix -ne $info.base_prefix) {
                Write-Host "[run2 bootstrap] Rejected Python candidate (virtualenv runtime): $Candidate"
                return $null
            }
            return [PSCustomObject]@{
                Path = (Get-FullPath $Candidate)
                Major = [int]$info.major
                Minor = [int]$info.minor
            }
        }
        catch {
            return $null
        }
    }

    function Add-Candidate {
        param(
            [System.Collections.Generic.List[string]]$Candidates,
            [string]$Candidate
        )

        if (-not $Candidate) {
            return
        }
        $candidateTrimmed = $Candidate.Trim().Trim('"')
        if (-not (Test-Path -LiteralPath $candidateTrimmed -PathType Leaf)) {
            return
        }
        $candidateFullPath = Get-FullPath $candidateTrimmed
        if (-not $Candidates.Contains($candidateFullPath)) {
            $Candidates.Add($candidateFullPath)
        }
    }

    function Add-RegistryCandidates {
        param([System.Collections.Generic.List[string]]$Candidates)

        $registryRoots = @(
            'HKCU:\Software\Python\PythonCore',
            'HKLM:\Software\Python\PythonCore',
            'HKLM:\Software\WOW6432Node\Python\PythonCore'
        )
        foreach ($registryRoot in $registryRoots) {
            if (-not (Test-Path -LiteralPath $registryRoot)) {
                continue
            }
            foreach ($versionKey in (Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue)) {
                $installPath = (Get-ItemProperty -LiteralPath $versionKey.PSPath -Name InstallPath -ErrorAction SilentlyContinue).InstallPath
                if ($installPath) {
                    Add-Candidate $Candidates (Join-Path $installPath 'python.exe')
                }
            }
        }
    }

    function Add-CommonInstallCandidates {
        param([System.Collections.Generic.List[string]]$Candidates)

        $roots = @()
        if ($env:LOCALAPPDATA) {
            $roots += Join-Path $env:LOCALAPPDATA 'Programs\Python'
        }
        if ($env:ProgramFiles) {
            $roots += $env:ProgramFiles
        }
        if (${env:ProgramFiles(x86)}) {
            $roots += ${env:ProgramFiles(x86)}
        }

        foreach ($root in ($roots | Select-Object -Unique)) {
            if (-not (Test-Path -LiteralPath $root -PathType Container)) {
                continue
            }
            $directories = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match '^Python3(\.\d+)?$' -or $_.Name -match '^Python-?3(\.\d+)?$' }
            foreach ($directory in $directories) {
                Add-Candidate $Candidates (Join-Path $directory.FullName 'python.exe')
            }
        }
    }

    function Add-PathCandidates {
        param([System.Collections.Generic.List[string]]$Candidates)

        if (-not $env:PATH) {
            return
        }
        foreach ($pathEntry in ($env:PATH -split ';')) {
            $pathEntry = $pathEntry.Trim().Trim('"')
            if (-not $pathEntry) {
                continue
            }
            foreach ($commandName in @('python.exe', 'python3.exe')) {
                Add-Candidate $Candidates (Join-Path $pathEntry $commandName)
            }
        }
    }

    function Add-UvCandidates {
        param([System.Collections.Generic.List[string]]$Candidates)

        $uvCommand = Get-Command 'uv.exe' -ErrorAction SilentlyContinue
        if (-not $uvCommand) {
            return
        }
        foreach ($line in (& $uvCommand.Source 'python' 'list' '--only-installed' 2>$null)) {
            if ($line -match '\s+(?<path>[A-Za-z]:\\.*python(?:3\.\d+)?\.exe)\s*$') {
                Add-Candidate $Candidates $Matches['path']
            }
        }
    }

    $candidates = [System.Collections.Generic.List[string]]::new()
    Add-PathCandidates $candidates
    Add-RegistryCandidates $candidates
    Add-CommonInstallCandidates $candidates
    Add-UvCandidates $candidates

    $compatible = @($candidates | ForEach-Object { Get-PythonInfo $_ } | Where-Object { $_ })
    $selected = $compatible |
        Sort-Object @{ Expression = { if ($_.Minor -eq 11) { 0 } else { 1 } } }, @{ Expression = { $_.Minor }; Descending = $true }, @{ Expression = { $_.Path } } |
        Select-Object -First 1

    function Test-VenvRuntime {
        param([string]$PythonPath)

        if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
            return $false
        }
        try {
            $probe = & $PythonPath -E -s -c "import json,sys; print(json.dumps({'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'major': sys.version_info.major, 'minor': sys.version_info.minor}))" 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $probe) {
                return $false
            }
            $info = $probe | ConvertFrom-Json
            $expectedPrefix = (Get-FullPath $VenvPath).TrimEnd('\')
            return ($info.prefix -eq $expectedPrefix -and $info.prefix -ne $info.base_prefix -and [int]$info.major -eq 3 -and [int]$info.minor -ge 10)
        }
        catch {
            return $false
        }
    }

    $runtimeReady = Test-VenvRuntime $venvPython
    if (-not $runtimeReady) {
        if (Test-Path -LiteralPath $venvFullPath) {
            if (-not (Test-Path -LiteralPath $managedMarker -PathType Leaf)) {
                Stop-Bootstrap "The machine-local target exists but is not marked as SGAA-managed: $venvFullPath"
            }
            Write-Host "[run2 bootstrap] Recreating the invalid machine-local SGAA environment."
        }
        if (-not $selected) {
            Stop-Bootstrap "No compatible CPython 3.10+ installation was found. Install official 64-bit Python 3.11 or newer from https://www.python.org/downloads/windows/, then double-click run2.bat again. Do not use the Hermes environment or the Microsoft Store execution alias."
        }
        Write-Host "[run2 bootstrap] Base Python: $($selected.Path) (Python $($selected.Major).$($selected.Minor))"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $venvFullPath) | Out-Null
        & $selected.Path -m venv --clear $venvFullPath
        if ($LASTEXITCODE -ne 0 -or -not (Test-VenvRuntime $venvPython)) {
            Stop-Bootstrap "Could not create a working machine-local environment at $venvFullPath"
        }
        Set-Content -LiteralPath $managedMarker -Value 'SGAA machine-local runtime; do not sync.' -Encoding ASCII
    }
    else {
        Write-Host "[run2 bootstrap] Machine-local SGAA environment: $venvFullPath"
    }

    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $requirementsHash = ([BitConverter]::ToString($sha256.ComputeHash([System.IO.File]::ReadAllBytes($requirementsFullPath))) -replace '-', '')
    }
    finally {
        $sha256.Dispose()
    }
    $storedHash = if (Test-Path -LiteralPath $requirementsMarker -PathType Leaf) { (Get-Content -LiteralPath $requirementsMarker -Raw).Trim() } else { '' }
    if ($storedHash -ne $requirementsHash) {
        Write-Host "[run2 bootstrap] Installing/verifying dependencies from requirements.txt."
        & $venvPython -m pip install --disable-pip-version-check --no-input -r $requirementsFullPath
        if ($LASTEXITCODE -ne 0) {
            Stop-Bootstrap "Dependency installation failed. Check network access and run run2.bat again."
        }
        & $venvPython -m pip check
        if ($LASTEXITCODE -ne 0) {
            Stop-Bootstrap "Dependency verification failed after installation."
        }
        Set-Content -LiteralPath $requirementsMarker -Value $requirementsHash -Encoding ASCII
    }
    else {
        & $venvPython -m pip check
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[run2 bootstrap] Dependency state changed; repairing from requirements.txt."
            & $venvPython -m pip install --disable-pip-version-check --no-input -r $requirementsFullPath
            if ($LASTEXITCODE -ne 0) {
                Stop-Bootstrap "Dependency repair failed. Check network access and run run2.bat again."
            }
            & $venvPython -m pip check
            if ($LASTEXITCODE -ne 0) {
                Stop-Bootstrap "Dependency verification failed after repair."
            }
        }
        Write-Host "[run2 bootstrap] Dependencies verified from requirements.txt."
    }
}
catch {
    Stop-Bootstrap $_.Exception.Message
}
