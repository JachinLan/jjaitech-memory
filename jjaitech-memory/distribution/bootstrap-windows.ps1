param([Parameter(Mandatory=$true)][string]$PackageRoot)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
if ($env:OS -ne 'Windows_NT') { throw 'This installer requires Windows.' }
# Respect explicitly configured restrictions. Never change execution policies.
foreach ($policy in Get-ExecutionPolicy -List) {
    if ($policy.ExecutionPolicy -in @('AllSigned','Restricted')) {
        throw 'A configured execution policy restricts unsigned installation. Ask your IT administrator for a signed deployment.'
    }
}
$PackageRoot = [IO.Path]::GetFullPath($PackageRoot)
$Installer = Join-Path $PackageRoot 'jjaitech-memory\deployment\install_windows.py'
if (!(Test-Path -LiteralPath $Installer -PathType Leaf)) { throw 'The release package is incomplete.' }
$Config = Join-Path $env:USERPROFILE '.workbuddy'
if (!(Test-Path -LiteralPath $Config -PathType Container)) {
    throw 'Open WorkBuddy and sign in with your own account first, then run this command again.'
}
Write-Host 'JJ AI TECH memory - Windows pilot (not yet native-Windows certified).'
Write-Host 'Missing Python, Node.js or Git may be installed through Microsoft WinGet.'
Write-Host 'Your current WorkBuddy model processes conversation/retrieved text; files stay local.'
Write-Host 'WorkBuddy tools will be allowed to write ONLY your AI-Wiki folder in addition to existing permissions.'
Write-Host 'No extra model API. No Wiki upload. Existing account permissions are not widened.'
if ((Read-Host 'Type YES to continue') -cne 'YES') { throw 'Installation cancelled; no changes made.' }
function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path','Machine')
    $user = [Environment]::GetEnvironmentVariable('Path','User')
    $env:Path = "$machine;$user;$env:Path"
}
function Install-Dependency([string]$Id) {
    if (!(Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw "WinGet is unavailable. Install $Id using your IT-approved installer, then retry."
    }
    Write-Host "Installing missing dependency: $Id"
    # Keep publisher/source agreement and elevation prompts visible to the employee.
    & winget.exe install --id $Id --exact --source winget
    if ($LASTEXITCODE -ne 0) {
        throw "WinGet could not install $Id (exit $LASTEXITCODE). Complete its required approval/IT setup and retry."
    }
    Refresh-Path
}
function Find-Python {
    $candidates = @()
    foreach ($name in @('py.exe','python.exe','python3.exe')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += $cmd.Source }
    }
    $base = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path -LiteralPath $base) {
        $candidates += @(Get-ChildItem -LiteralPath $base -Filter 'python.exe' -Recurse -File | Select-Object -ExpandProperty FullName)
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        $launcherArgs = @()
        if ([IO.Path]::GetFileName($candidate) -eq 'py.exe') { $launcherArgs = @('-3') }
        $probe = "import sys,sqlite3; assert sys.version_info>=(3,9); c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE t USING fts5(x)'); print(sys.executable)"
        try {
            $answer = @(& $candidate @launcherArgs -X utf8 -c $probe 2>$null)
            if ($LASTEXITCODE -eq 0 -and $answer.Count -gt 0) {
                $actual = [string]$answer[-1]
                if (Test-Path -LiteralPath $actual -PathType Leaf) { return $actual }
            }
        } catch { }
    }
    return $null
}
function Find-Node {
    $candidates = @()
    $cmd = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    $bundled = Join-Path $Config 'binaries\node\versions'
    if (Test-Path -LiteralPath $bundled) {
        $candidates += @(Get-ChildItem -LiteralPath $bundled -Filter node.exe -Recurse -File | Select-Object -ExpandProperty FullName)
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        try {
            $value = (& $candidate --version 2>$null | Out-String).Trim().TrimStart('v')
            if ($LASTEXITCODE -eq 0 -and [version]$value -ge [version]'18.20.8') { return $candidate }
        } catch { }
    }
    return $null
}
function Find-Bash {
    $candidates = @($env:CODEBUDDY_CODE_GIT_BASH_PATH)
    foreach ($root in @($env:ProgramFiles,${env:ProgramFiles(x86)},$env:LOCALAPPDATA)) {
        if ($root) {
            $candidates += (Join-Path $root 'Git\bin\bash.exe')
            $candidates += (Join-Path $root 'Programs\Git\bin\bash.exe')
        }
    }
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($git) { $candidates += (Join-Path (Split-Path (Split-Path $git.Source)) 'bin\bash.exe') }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            & $candidate --version >$null 2>&1
            if ($LASTEXITCODE -eq 0) { return $candidate }
        }
    }
    return $null
}
$Python = Find-Python
if (!$Python) { Install-Dependency 'Python.Python.3.13'; $Python = Find-Python }
if (!$Python) { throw 'A working Python 3.9+ with SQLite FTS5 is still unavailable.' }
$Node = Find-Node
if (!$Node) { Install-Dependency 'OpenJS.NodeJS.LTS'; $Node = Find-Node }
if (!$Node) { throw 'A working Node.js is still unavailable.' }
$Bash = Find-Bash
if (!$Bash) { Install-Dependency 'Git.Git'; $Bash = Find-Bash }
if (!$Bash) { throw 'Git Bash is still unavailable.' }
$env:Path = "$(Split-Path $Node);$(Split-Path $Python);$env:Path"
$env:CODEBUDDY_CODE_GIT_BASH_PATH = $Bash
# Discover the real CLI while the app can still be running; preserve it across quit.
$discovery = "import importlib.util,sys; s=importlib.util.spec_from_file_location('wi',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.discover_cli())"
$found = @(& $Python -X utf8 -c $discovery $Installer)
if ($LASTEXITCODE -ne 0 -or $found.Count -eq 0) { throw 'Cannot locate the WorkBuddy CLI. Use the manual installer --cli option.' }
$Cli = [string]$found[-1]
& $Python -X utf8 $Installer --check --cli $Cli
if ($LASTEXITCODE -ne 0) { throw 'Preflight failed; plugin installation was not started.' }
while (Get-Process WorkBuddy -ErrorAction SilentlyContinue) {
    Read-Host 'Finish your tasks and quit WorkBuddy, including its tray icon. Press Enter after quitting' | Out-Null
}
Write-Host 'Also close independent CodeBuddy CLI sessions before continuing.'
& $Python -X utf8 $Installer --cli $Cli --consent
if ($LASTEXITCODE -ne 0) { throw 'Installation failed. Keep the output and installation backup receipt.' }
Write-Host 'Plugin registration complete. Reopen WorkBuddy and verify saving/recall before wider rollout.'
