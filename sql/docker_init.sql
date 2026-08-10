-- Docker init: database created by MYSQL_DATABASE env var
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

-- ============================================================
-- CUHK 课程信息 种子数据
-- ============================================================
INSERT INTO course_info (course_code, course_name, department, instructor, schedule_day, start_time, end_time, classroom, building, credits, capacity, enrolled, category, description, update_time) VALUES
('CSCI2100', 'Data Structures', 'CSCI', 'Prof. Wong', 'Mon', '09:30:00', '11:15:00', 'LT1', 'Yasumoto International Academic Park', 3, 120, 98, 'Required', 'Basic data structures including arrays, linked lists, trees, and graphs.', '2026-08-01 10:00:00'),
('CSCI2100', 'Data Structures', 'CSCI', 'Prof. Wong', 'Wed', '09:30:00', '11:15:00', 'LT1', 'Yasumoto International Academic Park', 3, 120, 98, 'Required', 'Basic data structures including arrays, linked lists, trees, and graphs.', '2026-08-01 10:00:00'),
('CSCI3100', 'Software Engineering', 'CSCI', 'Prof. Lee', 'Tue', '14:30:00', '16:15:00', 'LT2', 'Lee Shau Kee Building', 3, 80, 65, 'Required', 'Software development lifecycle, Agile methodologies, and project management.', '2026-08-01 10:00:00'),
('CSCI3100', 'Software Engineering', 'CSCI', 'Prof. Lee', 'Thu', '14:30:00', '16:15:00', 'LT2', 'Lee Shau Kee Building', 3, 80, 65, 'Required', 'Software development lifecycle, Agile methodologies, and project management.', '2026-08-01 10:00:00'),
('CSCI4180', 'Machine Learning', 'CSCI', 'Prof. Chan', 'Mon', '16:30:00', '18:15:00', 'SC1', 'Science Centre', 3, 60, 55, 'Elective', 'Supervised and unsupervised learning, neural networks, and deep learning.', '2026-08-01 10:00:00'),
('CSCI4180', 'Machine Learning', 'CSCI', 'Prof. Chan', 'Wed', '16:30:00', '18:15:00', 'SC1', 'Science Centre', 3, 60, 55, 'Elective', 'Supervised and unsupervised learning, neural networks, and deep learning.', '2026-08-01 10:00:00'),
('CSCI3170', 'Database Systems', 'CSCI', 'Prof. Cheung', 'Tue', '10:30:00', '12:15:00', 'MMW1', 'Mong Man Wai Building', 3, 100, 82, 'Required', 'Relational databases, SQL, normalization, and transaction management.', '2026-08-01 10:00:00'),
('CSCI3170', 'Database Systems', 'CSCI', 'Prof. Cheung', 'Fri', '10:30:00', '12:15:00', 'MMW1', 'Mong Man Wai Building', 3, 100, 82, 'Required', 'Relational databases, SQL, normalization, and transaction management.', '2026-08-01 10:00:00'),
('CSCI4430', 'Natural Language Processing', 'CSCI', 'Prof. Liu', 'Wed', '14:30:00', '16:15:00', 'HSH1', 'Ho Sin Hang Building', 3, 50, 42, 'Elective', 'Text processing, language models, sentiment analysis, and transformer architectures.', '2026-08-01 10:00:00'),
('CSCI4430', 'Natural Language Processing', 'CSCI', 'Prof. Liu', 'Fri', '14:30:00', '16:15:00', 'HSH1', 'Ho Sin Hang Building', 3, 50, 42, 'Elective', 'Text processing, language models, sentiment analysis, and transformer architectures.', '2026-08-01 10:00:00'),
('ENGG2020', 'Digital Logic & Systems', 'ENGG', 'Prof. Kwok', 'Mon', '11:30:00', '13:15:00', 'ERB1', 'Engineering Research Building', 3, 90, 78, 'Required', 'Boolean algebra, combinational and sequential circuits, and FPGA design.', '2026-08-01 10:00:00'),
('ENGG2020', 'Digital Logic & Systems', 'ENGG', 'Prof. Kwok', 'Thu', '11:30:00', '13:15:00', 'ERB1', 'Engineering Research Building', 3, 90, 78, 'Required', 'Boolean algebra, combinational and sequential circuits, and FPGA design.', '2026-08-01 10:00:00'),
('UGEA1000', 'University Chinese', 'CHLL', 'Prof. Lam', 'Tue', '08:30:00', '10:15:00', 'CYT1', 'Cheng Yu Tung Building', 2, 150, 130, 'General', 'Chinese language and communication skills for university students.', '2026-08-01 10:00:00'),
('UGED1000', 'Understanding Society', 'SOCI', 'Dr. Ho', 'Thu', '16:30:00', '18:15:00', 'YIA1', 'Yasumoto International Academic Park', 2, 200, 175, 'General', 'Introduction to sociological perspectives and social issues.', '2026-08-01 10:00:00');

-- ============================================================
-- CUHK 校园活动 种子数据
-- ============================================================
INSERT INTO campus_events (event_name, organizer, venue, start_time, end_time, category, total_capacity, registered, description) VALUES
('CUHK Career Fair 2026', 'Career Planning Office', 'Sir Run Run Shaw Hall', '2026-09-15 10:00:00', '2026-09-15 17:00:00', 'Career', 500, 320, 'Annual career fair with 100+ employers from tech, finance, and more.'),
('AI in Healthcare Seminar', 'CSCI Department', 'Yasumoto International Academic Park LT1', '2026-08-20 15:00:00', '2026-08-20 17:00:00', 'Talk', 150, 85, 'Guest lecture by Prof. Li on recent advances in medical AI.'),
('Chung Chi College Cultural Night', 'Chung Chi College', 'Chung Chi Hall', '2026-09-05 18:30:00', '2026-09-05 22:00:00', 'Culture', 200, 120, 'An evening of traditional music, dance, and cultural performances.'),
('HackCUHK 2026', 'CSCI Student Society', 'Engineering Research Building', '2026-10-10 09:00:00', '2026-10-11 18:00:00', 'Competition', 150, 95, '24-hour hackathon. Build innovative solutions for campus life!'),
('Python Workshop for Beginners', 'ITSC', 'Lee Shau Kee Building LT2', '2026-08-25 14:00:00', '2026-08-25 17:00:00', 'Workshop', 80, 60, 'Hands-on Python programming workshop. No prior experience needed.'),
('New Asia College Open Day', 'New Asia College', 'New Asia College Campus', '2026-08-30 10:00:00', '2026-08-30 16:00:00', 'Open Day', 300, 150, 'Discover New Asia College: campus tour, student sharing, and activities.'),
('Research Poster Exhibition', 'Graduate School', 'University Library Exhibition Hall', '2026-09-01 09:00:00', '2026-09-05 18:00:00', 'Exhibition', 200, 80, 'Annual research poster exhibition showcasing graduate student projects.'),
('Mental Health Awareness Week', 'University Health Service', 'Central Campus', '2026-09-20 10:00:00', '2026-09-25 18:00:00', 'Wellness', 500, 200, 'A week of workshops, talks, and activities promoting mental wellness.'),
('Shaw College Movie Night', 'Shaw College', 'Shaw College Amphitheatre', '2026-08-22 19:00:00', '2026-08-22 22:00:00', 'Entertainment', 100, 55, 'Outdoor movie screening under the stars. Free popcorn!'),
('Startup Pitch Competition', 'CUHK Entrepreneurship Centre', 'Cheng Yu Tung Building', '2026-10-20 14:00:00', '2026-10-20 18:00:00', 'Competition', 120, 70, 'Pitch your startup idea to a panel of investors and win seed funding.');

-- ============================================================
-- CUHK 校园餐厅 种子数据（来源: CUHK accommodation page）
-- ============================================================
INSERT INTO canteen (name, location, opening_hours, phone, category, status) VALUES
('Basic Medical Sciences Building Snack Bar', 'Basic Medical Sciences Building', '10:00-19:00', '', 'Snack Bar', 'Open'),
('Benjamin Franklin Centre Coffee Corner', 'Benjamin Franklin Centre', 'Mon-Sat 07:30-19:30, Sun/PH Closed', '', 'Cafe', 'Open'),
('Benjamin Franklin Centre Staff Canteen', 'Benjamin Franklin Centre', 'Mon-Fri 11:00-15:00, PH Closed', '', 'Canteen', 'Open'),
('Benjamin Franklin Centre Student Canteen', 'Benjamin Franklin Centre', 'Mon-Fri 07:30-20:00, Sun 08:30-19:30', '', 'Canteen', 'Open'),
('Women Cooperative Store', 'Benjamin Franklin Centre', 'Mon-Sat 08:00-23:30', '', 'Store', 'Open'),
('Chung Chi College Staff Club', 'Chung Chi College', 'Please refer to college website', '', 'Canteen', 'Open'),
('Chung Chi College Student Canteen', 'Chung Chi College', 'Please refer to college website', '', 'Canteen', 'Open'),
('Li Wai Chun Building Cafe', 'Li Wai Chun Building', 'Please refer to outlet', '', 'Cafe', 'Open'),
('Li Wai Chun Building Halal Food Outlet', 'Li Wai Chun Building', 'Please refer to outlet', '', 'Canteen', 'Open'),
('Orchid Lodge', 'New Asia College', 'Please refer to outlet', '', 'Restaurant', 'Open'),
('Paper & Coffee (Pommerenke Student Centre)', 'Pommerenke Student Centre', 'Please refer to outlet', '', 'Cafe', 'Open'),
('New Asia College Staff Canteen', 'New Asia College', 'Please refer to college website', '', 'Canteen', 'Open'),
('New Asia College Student Canteen', 'New Asia College', 'Please refer to college website', '', 'Canteen', 'Open'),
('Yun Chi Hsien', 'New Asia College', 'Please refer to college website', '', 'Restaurant', 'Open'),
('New Asia College Coffee Shop', 'New Asia College', 'Please refer to college website', '', 'Cafe', 'Open'),
('United College Staff Canteen', 'United College', 'Please refer to college website', '', 'Canteen', 'Open'),
('United College Student Canteen', 'United College', 'Please refer to college website', '', 'Canteen', 'Open'),
('Si Yuan Amenities Centre', 'United College', 'Please refer to college website', '', 'Canteen', 'Open'),
('Cafe Shaw', 'Shaw College', 'Please refer to college website', '', 'Cafe', 'Open'),
('Morningside College Dining Hall', 'Morningside College', 'Please refer to college website', '', 'Canteen', 'Open'),
('Morningside College Cafe', 'Morningside College', 'Please refer to college website', '', 'Cafe', 'Open'),
('S.H. Ho College Canteen', 'S.H. Ho College', 'Please refer to college website', '', 'Canteen', 'Open'),
('S.H. Ho College Connexion', 'S.H. Ho College', 'Please refer to college website', '', 'Cafe', 'Open'),
('S.H. Ho College Cafe', 'S.H. Ho College', 'Please refer to college website', '', 'Cafe', 'Open'),
('CW Chu College Canteen', 'CW Chu College', 'Mon-Sat 08:30-21:30', '', 'Canteen', 'Open'),
('Wu Yee Sun College Student Canteen', 'Wu Yee Sun College', 'Please refer to college website', '', 'Canteen', 'Open'),
('Wu Yee Sun College Staff Canteen', 'Wu Yee Sun College', 'Please refer to college website', '', 'Canteen', 'Open'),
('Wu Yee Sun College Cafe', 'Wu Yee Sun College', 'Please refer to college website', '', 'Cafe', 'Open'),
('Lee Woo Sing College WS Pavilion', 'Lee Woo Sing College', 'Please refer to college website', '', 'Restaurant', 'Open'),
('Lee Woo Sing College The Harmony', 'Lee Woo Sing College', 'Please refer to college website', '', 'Canteen', 'Open'),
('Lee Woo Sing College Cafe Tolo', 'Lee Woo Sing College', 'Please refer to college website', '', 'Cafe', 'Open'),
('The Stage', 'Yasumoto International Academic Park', 'Mon-Fri 08:15-16:30', '', 'Cafe', 'Open'),
('Gastronomy Club', 'Yasumoto International Academic Park', 'Members only', '', 'Restaurant', 'Open'),
('Inno330', 'Cheng Yu Tung Building', 'Please refer to outlet', '', 'Cafe', 'Open'),
('Tea House', 'Cheng Yu Tung Building', 'Please refer to outlet', '', 'Restaurant', 'Open'),
('The Infinity Room', 'Cheng Yu Tung Building', 'Please refer to outlet', '', 'Restaurant', 'Open'),
('Art Museum Cafe - Ideaology', 'Art Museum', 'Please refer to outlet', '', 'Cafe', 'Open'),
('Benjamin Franklin Centre Vegetarian Food Shop', 'Benjamin Franklin Centre', '', '', 'Canteen', 'Closed'),
('Lee Shau Kee Building Snack Bar', 'Lee Shau Kee Building', '', '', 'Snack Bar', 'Closed'),
('YIA Cafe', 'Yasumoto International Academic Park', '', '', 'Cafe', 'Closed'),
('Postgraduate Hall 3 Canteen', 'Postgraduate Hall 3', '', '', 'Canteen', 'Closed');
