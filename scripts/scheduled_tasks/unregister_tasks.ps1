# 删除所有 SmartCampus 计划任务
$tasks = @(
    "SmartCampus\CampusEventsSpider",
    "SmartCampus\CampusNewsSpider",
    "SmartCampus\CourseSpider",
    "SmartCampus\CanteenSpider",
    "SmartCampus\LibraryHoursSpider"
)

foreach ($t in $tasks) {
    Write-Host "  删除: $t"
    schtasks /delete /tn $t /f 2>$null
}
Write-Host "完成。"
