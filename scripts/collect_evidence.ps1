[CmdletBinding()]
param(
    [string]$OutDir = "$env:USERPROFILE\Desktop\BSOD_Evidence",
    [int]$Days = 14
)

$ErrorActionPreference = 'SilentlyContinue'

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host '需要管理员权限：请右键开始菜单，打开“终端(管理员)”后重新运行。' -ForegroundColor Red
    exit 1
}

$dumpDir = Join-Path $OutDir 'dumps'
New-Item -ItemType Directory -Path $OutDir, $dumpDir -Force | Out-Null

Copy-Item 'C:\Windows\Minidump\*.dmp' $dumpDir -Force

$cut = (Get-Date).AddDays(-$Days)
Get-WinEvent -FilterHashtable @{ LogName = 'System'; StartTime = $cut } |
    Where-Object { $_.LevelDisplayName -in '错误', '严重' -or $_.Id -in 41, 1001, 6008, 4101 } |
    Sort-Object TimeCreated |
    Format-List TimeCreated, Id, ProviderName, Message |
    Out-File (Join-Path $OutDir 'eventlog.txt') -Encoding utf8

$summary = Join-Path $OutDir 'summary.txt'
'=== 报告生成时间 ===' | Out-File $summary -Encoding utf8
(Get-Date).ToString('yyyy-MM-dd HH:mm:ss') | Out-File $summary -Append -Encoding utf8
'' | Out-File $summary -Append -Encoding utf8
'=== Minidump 文件 ===' | Out-File $summary -Append -Encoding utf8
Get-ChildItem $dumpDir -Filter *.dmp |
    Select-Object Name, LastWriteTime, Length |
    Format-Table -AutoSize |
    Out-File $summary -Append -Encoding utf8

'=== MEMORY.DMP ===' | Out-File $summary -Append -Encoding utf8
Get-Item 'C:\Windows\MEMORY.DMP' |
    Select-Object FullName, LastWriteTime, Length |
    Format-Table -AutoSize |
    Out-File $summary -Append -Encoding utf8

'=== 常见第三方驱动版本 ===' | Out-File $summary -Append -Encoding utf8
$pattern = '^(ACE.*|vgk|sysdiag|hrdevmon|nfwfp|nvlddmkm|igdkmdn64|npu_kmd|RTKVHD64|Nahimic.*)\.sys$'
Get-ChildItem 'C:\Windows\System32\drivers' |
    Where-Object { $_.Name -match $pattern } |
    Select-Object Name, LastWriteTime, @{ n = 'Version'; e = { $_.VersionInfo.FileVersion } } |
    Format-Table -AutoSize |
    Out-File $summary -Append -Encoding utf8

$zips = Get-ChildItem $dumpDir -Filter *.dmp
if ($zips) {
    Compress-Archive -Path "$dumpDir\*.dmp" -DestinationPath (Join-Path $OutDir 'dumps.zip') -Force
    Write-Host "已打包: $(Join-Path $OutDir 'dumps.zip')" -ForegroundColor Green
}
else {
    Write-Host '未找到 Minidump：确认系统已设置为“小内存转储”，或本次是未蓝屏的硬重启。' -ForegroundColor Yellow
}

Write-Host "完成: $OutDir" -ForegroundColor Green
