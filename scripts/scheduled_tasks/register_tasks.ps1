# ============================================================
# SmartCampus - Windows 任务计划程序 注册脚本
# 以管理员身份运行此脚本：
#   PowerShell (Admin) > .\scripts\scheduled_tasks\register_tasks.ps1
# ============================================================
$ErrorActionPreference = "Stop"

$PYTHON = "E:\Software\Anaconda\python.exe"
$BASE   = "E:\Workspace\agent_project\SmartCampus"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " SmartCampus 数据更新计划任务注册" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 辅助函数：创建任务
function New-SpiderTask {
    param(
        [string]$Name,         # 任务名称（如 "NewsSpider"）
        [string]$Script,       # 脚本路径（相对 $BASE）
        [string]$Schedule,     # daily / weekly
        [string]$StartTime,    # HH:MM
        [string]$Days = "",    # weekly 时的星期（SUN/MON/TUE/...）
        [bool]$Force = $true   # 是否加 --force
    )

    $taskPath = "SmartCampus\$Name"
    $scriptFull = "$BASE\utils\$Script"
    $forceFlag = if ($Force) { "--force" } else { "" }

    # 先删除旧任务（如果存在）
    schtasks /delete /tn $taskPath /f 2>$null | Out-Null

    if ($Schedule -eq "daily") {
        $cmd = "schtasks /create /tn `"$taskPath`" /tr `"$PYTHON $scriptFull $forceFlag`" /sc daily /st $StartTime /rl HIGHEST"
    } else {
        $cmd = "schtasks /create /tn `"$taskPath`" /tr `"$PYTHON $scriptFull $forceFlag`" /sc weekly /d $Days /st $StartTime /rl HIGHEST"
    }

    Write-Host "  [创建] $taskPath" -NoNewline
    Invoke-Expression $cmd 2>&1 | Out-Null

    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ $Schedule $StartTime" -ForegroundColor Green
    } else {
        Write-Host "  ✗ 失败（请以管理员身份运行）" -ForegroundColor Red
    }
}

# ============================================================
# 注册 5 个定时任务
# ============================================================

New-SpiderTask -Name "CampusEventsSpider"  -Script "spider_campus.py"        -Schedule "daily"  -StartTime "01:00"
New-SpiderTask -Name "CampusNewsSpider"    -Script "spider_news.py"          -Schedule "daily"  -StartTime "06:00"
New-SpiderTask -Name "CourseSpider"        -Script "spider_course.py"        -Schedule "weekly" -StartTime "02:00" -Days "SUN"
New-SpiderTask -Name "CanteenSpider"       -Script "spider_canteen.py"       -Schedule "weekly" -StartTime "03:00" -Days "MON"
New-SpiderTask -Name "LibraryHoursSpider"  -Script "spider_library_hours.py" -Schedule "weekly" -StartTime "04:00" -Days "MON"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " 注册完成！运行以下命令查看任务：" -ForegroundColor Green
Write-Host "   schtasks /query /tn SmartCampus\ " -ForegroundColor White
Write-Host "   taskschd.msc  (图形界面)" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan
