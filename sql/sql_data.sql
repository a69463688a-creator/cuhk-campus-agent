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
-- 自习室信息表
-- ============================================================
DROP TABLE IF EXISTS study_rooms;
CREATE TABLE study_rooms (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    building VARCHAR(80) NOT NULL COMMENT '教学楼名称',
    room_number VARCHAR(20) NOT NULL COMMENT '教室编号',
    room_date DATE NOT NULL COMMENT '开放日期',
    start_time TIME NOT NULL COMMENT '开放开始时间',
    end_time TIME NOT NULL COMMENT '开放结束时间',
    capacity INT NOT NULL COMMENT '总座位数',
    available_seats INT NOT NULL COMMENT '剩余可用座位',
    has_projector TINYINT DEFAULT 0 COMMENT '是否有投影仪（0/1）',
    has_ac TINYINT DEFAULT 1 COMMENT '是否有空调（0/1）',
    status VARCHAR(20) DEFAULT 'available' COMMENT '状态：available / full / closed',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_room (building, room_number, room_date, start_time)
) COMMENT='自习室信息表';

-- ============================================================
-- 图书馆座位表
-- ============================================================
DROP TABLE IF EXISTS library_seats;
CREATE TABLE library_seats (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    library_name VARCHAR(80) NOT NULL COMMENT '图书馆名称',
    floor INT NOT NULL COMMENT '楼层',
    zone VARCHAR(40) NOT NULL COMMENT '区域（如 Quiet Zone / Group Study）',
    seat_date DATE NOT NULL COMMENT '日期',
    time_slot VARCHAR(20) NOT NULL COMMENT '时间段（如 09:00-12:00）',
    total_seats INT NOT NULL COMMENT '该区域总座位数',
    available_seats INT NOT NULL COMMENT '剩余可用座位',
    has_power TINYINT DEFAULT 1 COMMENT '是否有电源插座（0/1）',
    is_quiet_zone TINYINT DEFAULT 0 COMMENT '是否静音区（0/1）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_seat (library_name, floor, zone, seat_date, time_slot)
) COMMENT='图书馆座位信息表';

-- ============================================================
-- 校园活动表
-- ============================================================
DROP TABLE IF EXISTS campus_events;
CREATE TABLE campus_events (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
    event_name VARCHAR(100) NOT NULL COMMENT '活动名称',
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
