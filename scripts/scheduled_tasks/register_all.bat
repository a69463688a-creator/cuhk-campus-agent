@echo off
chcp 65001 >nul
echo ============================================================
echo  SmartCampus 注册 Windows 计划任务
echo  请以管理员身份运行此脚本（右键 - 以管理员身份运行）
echo ============================================================
echo.

set BASE=E:\Workspace\agent_project\SmartCampus\scripts\scheduled_tasks

echo [1/5] 校园活动 - 每天 01:00
schtasks /create /tn "SmartCampus\CampusEventsSpider" /tr "%BASE%\run_events.bat" /sc daily /st 01:00 /f
echo.

echo [2/5] 校园新闻 - 每天 06:00
schtasks /create /tn "SmartCampus\CampusNewsSpider" /tr "%BASE%\run_news.bat" /sc daily /st 06:00 /f
echo.

echo [3/5] 课程数据 - 每周日 02:00
schtasks /create /tn "SmartCampus\CourseSpider" /tr "%BASE%\run_course.bat" /sc weekly /d SUN /st 02:00 /f
echo.

echo [4/5] 餐厅信息 - 每周一 03:00
schtasks /create /tn "SmartCampus\CanteenSpider" /tr "%BASE%\run_canteen.bat" /sc weekly /d MON /st 03:00 /f
echo.

echo [5/5] 图书馆时间 - 每周一 04:00
schtasks /create /tn "SmartCampus\LibraryHoursSpider" /tr "%BASE%\run_library.bat" /sc weekly /d MON /st 04:00 /f
echo.

echo ============================================================
echo  注册完成！
echo  查看任务: schtasks /query /tn SmartCampus\
echo  图形管理: taskschd.msc
echo ============================================================
pause
