@echo off
chcp 65001 >nul
REM ============================================================
REM SmartCampus - 一次性运行所有爬虫
REM 运行所有 spider，每个脚本自带 should_update 检查，
REM 数据新鲜自动跳过，过期自动拉取。
REM ============================================================
set PYTHON=E:\Software\Anaconda\python.exe
set BASE=E:\Workspace\agent_project\SmartCampus

echo [%date% %time%] SmartCampus 数据更新开始
echo.

echo [1/5] 校园活动 ...
%PYTHON% %BASE%\utils\spider_campus.py --force --once

echo [2/5] 校园新闻 ...
%PYTHON% %BASE%\utils\spider_news.py --force --once

echo [3/5] 餐厅信息 ...
%PYTHON% %BASE%\utils\spider_canteen.py --force --once

echo [4/5] 图书馆开放时间 ...
%PYTHON% %BASE%\utils\spider_library_hours.py --force --once

echo [5/5] 课程数据（耗时较长）...
%PYTHON% %BASE%\utils\spider_course.py --force --once

echo.
echo [%date% %time%] SmartCampus 数据更新完成
pause
