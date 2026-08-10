DROP DATABASE IF EXISTS cuhk_campus;
CREATE DATABASE cuhk_campus CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE cuhk_campus;

-- ============================================================
-- 课程信息表
-- ============================================================
DROP TABLE IF EXISTS course_info;
CREATE TABLE IF NOT EXISTS course_info (
    id INT AUTO_INCREMENT PRIMARY KEY,
    course_code VARCHAR(20) NOT NULL COMMENT '课程代码（如 CSCI2100）',
    course_name VARCHAR(100) NOT NULL COMMENT '课程名称（如 Data Structures）',
    department VARCHAR(50) NOT NULL COMMENT '开课院系（如 CSCI）',
    instructor VARCHAR(50) COMMENT '授课教师',
    schedule_day VARCHAR(10) COMMENT '上课日（如 Mon/Wed/Fri）',
    start_time TIME COMMENT '开始时间',
    end_time TIME COMMENT '结束时间',
    classroom VARCHAR(50) COMMENT '教室编号',
    building VARCHAR(80) COMMENT '教学楼名称',
    credits INT DEFAULT 3 COMMENT '学分数',
    capacity INT COMMENT '课容量上限',
    enrolled INT DEFAULT 0 COMMENT '已选课人数',
    category VARCHAR(30) COMMENT '课程类别（Required/Elective/General）',
    description TEXT COMMENT '课程简介',
    update_time DATETIME COMMENT '数据更新时间',
    UNIQUE KEY unique_course_time (course_code, schedule_day, start_time)
) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='课程信息表';

-- ============================================================
-- 校园活动表
-- ============================================================
DROP TABLE IF EXISTS campus_events;
CREATE TABLE campus_events (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    event_name VARCHAR(200) NOT NULL COMMENT '活动名称',
    organizer VARCHAR(100) NOT NULL COMMENT '主办方（书院/学系/社团）',
    venue VARCHAR(100) NOT NULL COMMENT '活动场地',
    start_time DATETIME NOT NULL COMMENT '开始时间',
    end_time DATETIME NOT NULL COMMENT '结束时间',
    category VARCHAR(30) NOT NULL COMMENT '活动类别（讲座/工作坊/比赛/文化/体育）',
    total_capacity INT NOT NULL DEFAULT 100 COMMENT '总容量',
    registered INT NOT NULL DEFAULT 0 COMMENT '已报名人数',
    description TEXT COMMENT '活动简介',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_event (start_time, event_name, venue)
) COMMENT='校园活动信息表';

-- ============================================================
-- 校园新闻表
-- ============================================================
DROP TABLE IF EXISTS campus_news;
CREATE TABLE campus_news (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    title VARCHAR(200) NOT NULL COMMENT '新闻标题',
    source VARCHAR(100) NOT NULL DEFAULT 'CUHK CPR' COMMENT '来源',
    category VARCHAR(30) DEFAULT 'General' COMMENT '新闻类别',
    publish_date DATETIME NOT NULL COMMENT '发布日期',
    summary TEXT COMMENT '新闻摘要',
    url VARCHAR(500) COMMENT '原文链接',
    image_url VARCHAR(500) COMMENT '封面图URL',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_news (publish_date, title)
) COMMENT='校园新闻表';

-- ============================================================
-- 校园餐厅表
-- ============================================================
DROP TABLE IF EXISTS canteen;
CREATE TABLE canteen (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    name VARCHAR(80) NOT NULL COMMENT '餐厅名称',
    location VARCHAR(100) NOT NULL COMMENT '所在位置/地址',
    opening_hours VARCHAR(300) COMMENT '营业时间',
    phone VARCHAR(50) COMMENT '联系电话',
    category VARCHAR(30) DEFAULT 'Canteen' COMMENT '类别（Canteen/Cafe/Restaurant/Snack Bar）',
    status VARCHAR(20) DEFAULT 'Open' COMMENT '营业状态（Open/Closed）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_canteen (name, location)
) COMMENT='校园餐厅信息表';

-- ============================================================
-- 图书馆开放时间表
-- ============================================================
DROP TABLE IF EXISTS library_hours;
CREATE TABLE library_hours (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    library_name VARCHAR(100) NOT NULL COMMENT '图书馆名称',
    area VARCHAR(100) DEFAULT 'Main' COMMENT '区域（如 Main/ Learning Garden/ Staffed services）',
    day_of_week VARCHAR(10) NOT NULL COMMENT '星期几（Mon/Tue/Wed/Thu/Fri/Sat/Sun）',
    date DATE COMMENT '具体日期',
    open_time VARCHAR(10) COMMENT '开门时间（如 09:00, 24hrs）',
    close_time VARCHAR(10) COMMENT '关门时间',
    is_closed TINYINT DEFAULT 0 COMMENT '是否闭馆',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_lib_hours (library_name, area, day_of_week, date)
) COMMENT='图书馆开放时间表';
