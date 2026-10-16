param(
    [string]$LogPath = (Join-Path $PSScriptRoot '..\data\scheduled-reindex.log'),
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$baseUrl = "http://127.0.0.1:$Port"
$projectPath = Split-Path -Parent $PSScriptRoot
$serverProcess = $null
$exitCode = 0

function Write-ReindexLog([string]$Message) {
    $directory = Split-Path -Parent $LogPath
    if ($directory -and -not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    Write-Output $line
}

try {
    try {
        $status = Invoke-RestMethod -Uri "$baseUrl/api/status" -TimeoutSec 5
    }
    catch {
        $pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $pythonPath)) {
            throw 'Python du projet introuvable. Lancez scripts\start.bat une premiere fois.'
        }
        Write-ReindexLog 'START: demarrage temporaire du serveur local.'
        $serverProcess = Start-Process -FilePath $pythonPath -ArgumentList @(
            '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port"
        ) -WorkingDirectory $projectPath -WindowStyle Hidden -PassThru

        $deadline = (Get-Date).AddSeconds(60)
        $status = $null
        while ((Get-Date) -lt $deadline) {
            if ($serverProcess.HasExited) {
                throw "Le serveur temporaire s'est arrete au demarrage (code $($serverProcess.ExitCode)). Verifiez les dependances et le port $Port."
            }
            try {
                $status = Invoke-RestMethod -Uri "$baseUrl/api/status" -TimeoutSec 2
                break
            }
            catch {
                Start-Sleep -Milliseconds 500
            }
        }
        if ($null -eq $status) {
            throw 'Le serveur temporaire ne repond pas apres 60 secondes.'
        }
    }

    # Au premier lancement, le serveur peut construire son index automatiquement.
    # Attendre ce scan avant de fermer une instance demarree par cette tache.
    $indexDeadline = (Get-Date).AddSeconds(3600)
    if ($serverProcess -and $status.indexing) {
        Write-ReindexLog 'WAIT: attente de l indexation au demarrage.'
        while ($status.indexing) {
            if ($serverProcess.HasExited) {
                throw 'Le serveur temporaire s est arrete pendant l indexation.'
            }
            if ((Get-Date) -ge $indexDeadline) {
                throw 'L indexation au demarrage depasse une heure.'
            }
            Start-Sleep -Seconds 1
            $status = Invoke-RestMethod -Uri "$baseUrl/api/status" -TimeoutSec 15
        }
    }
    if ($status.indexing) {
        Write-ReindexLog 'SKIP: une indexation est deja en cours.'
        exit 0
    }
    if (-not $status.available) {
        throw 'Le dossier Google Drive est inaccessible. Verifiez Drive et le lecteur G:.'
    }

    $page = Invoke-WebRequest -Uri "$baseUrl/" -UseBasicParsing -TimeoutSec 15
    $tokenMatch = [regex]::Match($page.Content, '<meta\s+name="local-token"\s+content="([^"]+)"')
    if (-not $tokenMatch.Success) {
        throw 'Jeton local introuvable dans la page de recherche.'
    }

    $remainingSeconds = [int][math]::Ceiling(($indexDeadline - (Get-Date)).TotalSeconds)
    if ($remainingSeconds -le 0) {
        throw 'La duree maximale d indexation est depassee.'
    }
    $report = Invoke-RestMethod -Uri "$baseUrl/api/reindex" -Method Post `
        -Headers @{ 'X-Local-Token' = $tokenMatch.Groups[1].Value } -TimeoutSec $remainingSeconds
    if (-not $report.success) {
        throw 'La reindexation a retourne un echec.'
    }
    Write-ReindexLog ('OK: ajoutes={0}, modifies={1}, supprimes={2}, inchanges={3}, ignores={4}' -f `
        $report.added, $report.updated, $report.deleted, $report.unchanged, $report.skipped)
    foreach ($warning in $report.warnings) {
        Write-ReindexLog "WARNING: $warning"
    }
}
catch {
    # Un clic sur Reindexer peut demarrer un scan entre le statut et le POST.
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) {
        Write-ReindexLog 'SKIP: une indexation est deja en cours.'
    }
    else {
        Write-ReindexLog ('ERROR: {0} Application attendue sur {1}.' -f $_.Exception.Message, $baseUrl)
        $exitCode = 1
    }
}
finally {
    if ($serverProcess) {
        if (-not $serverProcess.HasExited) {
            # Le lanceur Python du venv peut creer un processus enfant : fermer
            # uniquement cet arbre, jamais les autres instances Python/Uvicorn.
            & "$env:SystemRoot\System32\taskkill.exe" /PID "$($serverProcess.Id)" /T /F | Out-Null
        }
        if ($serverProcess.WaitForExit(5000)) {
            Write-ReindexLog 'STOP: serveur temporaire arrete.'
        }
        else {
            Write-ReindexLog 'ERROR: impossible d arreter le serveur temporaire.'
            $exitCode = 1
        }
        $serverProcess.Dispose()
    }
}
exit $exitCode
