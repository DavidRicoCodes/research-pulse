$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $projectRoot '.logs'
$logPath = Join-Path $logDirectory 'scholar-refresh.log'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Start-Transcript -LiteralPath $logPath -Append | Out-Null

try {
    # This checkout belongs exclusively to the scheduled collector.
    $automationRoot = Join-Path $logDirectory 'automation'
    if (-not (Test-Path -LiteralPath (Join-Path $automationRoot '.git'))) {
        git clone 'https://github.com/DavidRicoCodes/research-pulse.git' $automationRoot
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the automation checkout.' }
    }
    Set-Location -LiteralPath $automationRoot
    # A previous failed query may have left a generated, unpublished snapshot.
    git restore -- 'data/history.json'
    if ($LASTEXITCODE -ne 0) { throw 'Could not clear the generated automation snapshot.' }

    git fetch origin main
    if ($LASTEXITCODE -ne 0) { throw 'Could not fetch origin/main.' }
    git switch main
    if ($LASTEXITCODE -ne 0) { throw 'Could not switch to main.' }
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { throw 'Could not fast-forward main.' }

    git config user.name 'research-pulse-local'
    git config user.email 'DavidRicoCodes@users.noreply.github.com'
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
catch {
    Write-Output "Refresh failed: $($_.Exception.Message)"
    throw
}
finally {
    Stop-Transcript | Out-Null
}
