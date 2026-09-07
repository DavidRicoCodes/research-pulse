$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $projectRoot '.logs'
$logPath = Join-Path $logDirectory 'scholar-refresh.log'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Start-Transcript -LiteralPath $logPath -Append | Out-Null

try {
    Set-Location -LiteralPath $projectRoot

    $pending = git status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the Git working tree.' }
    if ($pending) {
        throw 'The project has local tracked changes; refresh skipped to avoid overwriting them.'
    }

    git fetch origin main
    if ($LASTEXITCODE -ne 0) { throw 'Could not fetch origin/main.' }
    git switch main
    if ($LASTEXITCODE -ne 0) { throw 'Could not switch to main.' }
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'Could not fast-forward main.' }

    python collector.py
    if ($LASTEXITCODE -ne 0) { throw 'The collector failed.' }

    $history = Get-Content -Raw -LiteralPath 'data\history.json' | ConvertFrom-Json
    $latest = $history.snapshots[-1]
    $today = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd')
    if ($latest.sources.google_scholar.observed_at -ne $today) {
        throw 'Google Scholar did not return a fresh observation; nothing will be published.'
    }

    git add -- 'data/history.json'
    if ($LASTEXITCODE -ne 0) { throw 'Could not stage the new snapshot.' }
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Output 'No research data changed.'
        exit 0
    }

    git commit -m "data: Google Scholar snapshot $today"
    if ($LASTEXITCODE -ne 0) { throw 'Could not commit the Scholar snapshot.' }
    git push origin main
    if ($LASTEXITCODE -ne 0) { throw 'Could not push the Scholar snapshot.' }
    Write-Output "Published fresh Google Scholar metrics for $today."
}
finally {
    Stop-Transcript | Out-Null
}
