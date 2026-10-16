param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Hourly', 'Daily', 'Logon')]
    [string]$Frequency,
    [string]$DailyTime = '09:00'
)

$ErrorActionPreference = 'Stop'
$taskName = 'SearchGoogleDrive-Reindex'
$scriptPath = Join-Path $PSScriptRoot 'reindex.ps1'
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Script introuvable : $scriptPath"
}

$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    throw "La tache $taskName existe deja. Modifiez-la dans le Planificateur Windows."
}

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $scriptPath
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
switch ($Frequency) {
    'Hourly' {
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours 1)
    }
    'Daily' {
        $trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact($DailyTime, 'HH:mm', [cultureinfo]::InvariantCulture))
    }
    'Logon' {
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
        $trigger.Delay = 'PT2M'
    }
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 65)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'Actualise l index SearchGoogleDrive ; demarre et arrete un serveur temporaire si necessaire.' | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object NextRunTime, LastTaskResult
