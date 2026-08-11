"""种子数据 — 课程、活动、餐厅 初始数据

Revision ID: 002
Revises: 001
Create Date: 2026-08-11
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """插入初始种子数据（使用 INSERT IGNORE 防止重复）"""

    # ── 课程种子数据 ──
    op.execute("""
        INSERT IGNORE INTO course_info
            (course_code, course_name, department, instructor, schedule_day,
             start_time, end_time, classroom, building, credits, capacity,
             enrolled, category, description, update_time)
        VALUES
        ('CSCI2100', 'Data Structures', 'CSCI', 'Prof. Wong', 'Mon',
         '09:30:00', '11:15:00', 'LT1', 'Yasumoto International Academic Park',
         3, 120, 98, 'Required',
         'Basic data structures including arrays, linked lists, trees, and graphs.',
         '2026-08-01 10:00:00'),
        ('CSCI2100', 'Data Structures', 'CSCI', 'Prof. Wong', 'Wed',
         '09:30:00', '11:15:00', 'LT1', 'Yasumoto International Academic Park',
         3, 120, 98, 'Required',
         'Basic data structures including arrays, linked lists, trees, and graphs.',
         '2026-08-01 10:00:00'),
        ('CSCI3100', 'Software Engineering', 'CSCI', 'Prof. Lee', 'Tue',
         '14:30:00', '16:15:00', 'LT2', 'Lee Shau Kee Building',
         3, 80, 65, 'Required',
         'Software development lifecycle, Agile methodologies, and project management.',
         '2026-08-01 10:00:00'),
        ('CSCI3100', 'Software Engineering', 'CSCI', 'Prof. Lee', 'Thu',
         '14:30:00', '16:15:00', 'LT2', 'Lee Shau Kee Building',
         3, 80, 65, 'Required',
         'Software development lifecycle, Agile methodologies, and project management.',
         '2026-08-01 10:00:00'),
        ('CSCI4180', 'Machine Learning', 'CSCI', 'Prof. Chan', 'Mon',
         '16:30:00', '18:15:00', 'SC1', 'Science Centre',
         3, 60, 55, 'Elective',
         'Supervised and unsupervised learning, neural networks, and deep learning.',
         '2026-08-01 10:00:00'),
        ('CSCI4180', 'Machine Learning', 'CSCI', 'Prof. Chan', 'Wed',
         '16:30:00', '18:15:00', 'SC1', 'Science Centre',
         3, 60, 55, 'Elective',
         'Supervised and unsupervised learning, neural networks, and deep learning.',
         '2026-08-01 10:00:00'),
        ('CSCI3170', 'Database Systems', 'CSCI', 'Prof. Cheung', 'Tue',
         '10:30:00', '12:15:00', 'MMW1', 'Mong Man Wai Building',
         3, 100, 82, 'Required',
         'Relational databases, SQL, normalization, and transaction management.',
         '2026-08-01 10:00:00'),
        ('CSCI3170', 'Database Systems', 'CSCI', 'Prof. Cheung', 'Fri',
         '10:30:00', '12:15:00', 'MMW1', 'Mong Man Wai Building',
         3, 100, 82, 'Required',
         'Relational databases, SQL, normalization, and transaction management.',
         '2026-08-01 10:00:00'),
        ('CSCI4430', 'Natural Language Processing', 'CSCI', 'Prof. Liu', 'Wed',
         '14:30:00', '16:15:00', 'HSH1', 'Ho Sin Hang Building',
         3, 50, 42, 'Elective',
         'Text processing, language models, sentiment analysis, and transformer architectures.',
         '2026-08-01 10:00:00'),
        ('CSCI4430', 'Natural Language Processing', 'CSCI', 'Prof. Liu', 'Fri',
         '14:30:00', '16:15:00', 'HSH1', 'Ho Sin Hang Building',
         3, 50, 42, 'Elective',
         'Text processing, language models, sentiment analysis, and transformer architectures.',
         '2026-08-01 10:00:00'),
        ('ENGG2020', 'Digital Logic & Systems', 'ENGG', 'Prof. Kwok', 'Mon',
         '11:30:00', '13:15:00', 'ERB1', 'Engineering Research Building',
         3, 90, 78, 'Required',
         'Boolean algebra, combinational and sequential circuits, and FPGA design.',
         '2026-08-01 10:00:00'),
        ('ENGG2020', 'Digital Logic & Systems', 'ENGG', 'Prof. Kwok', 'Thu',
         '11:30:00', '13:15:00', 'ERB1', 'Engineering Research Building',
         3, 90, 78, 'Required',
         'Boolean algebra, combinational and sequential circuits, and FPGA design.',
         '2026-08-01 10:00:00'),
        ('UGEA1000', 'University Chinese', 'CHLL', 'Prof. Lam', 'Tue',
         '08:30:00', '10:15:00', 'CYT1', 'Cheng Yu Tung Building',
         2, 150, 130, 'General',
         'Chinese language and communication skills for university students.',
         '2026-08-01 10:00:00'),
        ('UGED1000', 'Understanding Society', 'SOCI', 'Dr. Ho', 'Thu',
         '16:30:00', '18:15:00', 'YIA1', 'Yasumoto International Academic Park',
         2, 200, 175, 'General',
         'Introduction to sociological perspectives and social issues.',
         '2026-08-01 10:00:00')
    """)

    # ── 校园活动种子数据 ──
    op.execute("""
        INSERT IGNORE INTO campus_events
            (event_name, organizer, venue, start_time, end_time, category,
             total_capacity, registered, description)
        VALUES
        ('CUHK Career Fair 2026', 'Career Planning Office', 'Sir Run Run Shaw Hall',
         '2026-09-15 10:00:00', '2026-09-15 17:00:00', 'Career',
         500, 320, 'Annual career fair with 100+ employers from tech, finance, and more.'),
        ('AI in Healthcare Seminar', 'CSCI Department',
         'Yasumoto International Academic Park LT1',
         '2026-08-20 15:00:00', '2026-08-20 17:00:00', 'Talk',
         150, 85, 'Guest lecture by Prof. Li on recent advances in medical AI.'),
        ('Chung Chi College Cultural Night', 'Chung Chi College', 'Chung Chi Hall',
         '2026-09-05 18:30:00', '2026-09-05 22:00:00', 'Culture',
         200, 120, 'An evening of traditional music, dance, and cultural performances.'),
        ('HackCUHK 2026', 'CSCI Student Society', 'Engineering Research Building',
         '2026-10-10 09:00:00', '2026-10-11 18:00:00', 'Competition',
         150, 95, '24-hour hackathon. Build innovative solutions for campus life!'),
        ('Python Workshop for Beginners', 'ITSC', 'Lee Shau Kee Building LT2',
         '2026-08-25 14:00:00', '2026-08-25 17:00:00', 'Workshop',
         80, 60, 'Hands-on Python programming workshop. No prior experience needed.'),
        ('New Asia College Open Day', 'New Asia College', 'New Asia College Campus',
         '2026-08-30 10:00:00', '2026-08-30 16:00:00', 'Open Day',
         300, 150, 'Discover New Asia College: campus tour, student sharing, and activities.'),
        ('Research Poster Exhibition', 'Graduate School',
         'University Library Exhibition Hall',
         '2026-09-01 09:00:00', '2026-09-05 18:00:00', 'Exhibition',
         200, 80, 'Annual research poster exhibition showcasing graduate student projects.'),
        ('Mental Health Awareness Week', 'University Health Service', 'Central Campus',
         '2026-09-20 10:00:00', '2026-09-25 18:00:00', 'Wellness',
         500, 200, 'A week of workshops, talks, and activities promoting mental wellness.'),
        ('Shaw College Movie Night', 'Shaw College', 'Shaw College Amphitheatre',
         '2026-08-22 19:00:00', '2026-08-22 22:00:00', 'Entertainment',
         100, 55, 'Outdoor movie screening under the stars. Free popcorn!'),
        ('Startup Pitch Competition', 'CUHK Entrepreneurship Centre',
         'Cheng Yu Tung Building',
         '2026-10-20 14:00:00', '2026-10-20 18:00:00', 'Competition',
         120, 70, 'Pitch your startup idea to a panel of investors and win seed funding.')
    """)

    # ── 校园餐厅种子数据 ──
    op.execute("""
        INSERT IGNORE INTO canteen (name, location, opening_hours, phone, category, status)
        VALUES
        ('Basic Medical Sciences Building Snack Bar', 'Basic Medical Sciences Building',
         '10:00-19:00', '', 'Snack Bar', 'Open'),
        ('Benjamin Franklin Centre Coffee Corner', 'Benjamin Franklin Centre',
         'Mon-Sat 07:30-19:30, Sun/PH Closed', '', 'Cafe', 'Open'),
        ('Benjamin Franklin Centre Staff Canteen', 'Benjamin Franklin Centre',
         'Mon-Fri 11:00-15:00, PH Closed', '', 'Canteen', 'Open'),
        ('Benjamin Franklin Centre Student Canteen', 'Benjamin Franklin Centre',
         'Mon-Fri 07:30-20:00, Sun 08:30-19:30', '', 'Canteen', 'Open'),
        ('Women Cooperative Store', 'Benjamin Franklin Centre',
         'Mon-Sat 08:00-23:30', '', 'Store', 'Open'),
        ('Chung Chi College Staff Club', 'Chung Chi College',
         'Please refer to college website', '', 'Canteen', 'Open'),
        ('Chung Chi College Student Canteen', 'Chung Chi College',
         'Please refer to college website', '', 'Canteen', 'Open'),
        ('Li Wai Chun Building Cafe', 'Li Wai Chun Building',
         'Please refer to outlet', '', 'Cafe', 'Open'),
        ('Li Wai Chun Building Halal Food Outlet', 'Li Wai Chun Building',
         'Please refer to outlet', '', 'Canteen', 'Open'),
        ('Orchid Lodge', 'New Asia College',
         'Please refer to outlet', '', 'Restaurant', 'Open'),
        ('Paper & Coffee (Pommerenke Student Centre)', 'Pommerenke Student Centre',
         'Please refer to outlet', '', 'Cafe', 'Open'),
        ('New Asia College Staff Canteen', 'New Asia College',
         'Please refer to college website', '', 'Canteen', 'Open'),
        ('New Asia College Student Canteen', 'New Asia College',
         'Please refer to college website', '', 'Canteen', 'Open'),
        ('Yun Chi Hsien', 'New Asia College',
         'Please refer to college website', '', 'Restaurant', 'Open'),
        ('New Asia College Coffee Shop', 'New Asia College',
         'Please refer to college website', '', 'Cafe', 'Open'),
        ('United College Staff Canteen', 'United College',
         'Please refer to college website', '', 'Canteen', 'Open'),
        ('United College Student Canteen', 'United College',
         'Please refer to college website', '', 'Canteen', 'Open'),
        ('Si Yuan Amenities Centre', 'United College',
         'Please refer to college website', '', 'Canteen', 'Open'),
        ('Cafe Shaw', 'Shaw College',
         'Please refer to college website', '', 'Cafe', 'Open'),
        ('Morningside College Dining Hall', 'Morningside College',
         'Please refer to college website', '', 'Canteen', 'Open'),
        ('Morningside College Cafe', 'Morningside College',
         'Please refer to college website', '', 'Cafe', 'Open'),
        ('S.H. Ho College Canteen', 'S.H. Ho College',
         'Please refer to college website', '', 'Canteen', 'Open'),
        ('S.H. Ho College Connexion', 'S.H. Ho College',
         'Please refer to college website', '', 'Cafe', 'Open'),
        ('S.H. Ho College Cafe', 'S.H. Ho College',
         'Please refer to college website', '', 'Cafe', 'Open'),
        ('CW Chu College Canteen', 'CW Chu College',
         'Mon-Sat 08:30-21:30', '', 'Canteen', 'Open'),
        ('Wu Yee Sun College Student Canteen', 'Wu Yee Sun College',
         'Please refer to college website', '', 'Canteen', 'Open'),
        ('Wu Yee Sun College Staff Canteen', 'Wu Yee Sun College',
         'Please refer to college website', '', 'Canteen', 'Open'),
        ('Wu Yee Sun College Cafe', 'Wu Yee Sun College',
         'Please refer to college website', '', 'Cafe', 'Open'),
        ('Lee Woo Sing College WS Pavilion', 'Lee Woo Sing College',
         'Please refer to college website', '', 'Restaurant', 'Open'),
        ('Lee Woo Sing College The Harmony', 'Lee Woo Sing College',
         'Please refer to college website', '', 'Canteen', 'Open'),
        ('Lee Woo Sing College Cafe Tolo', 'Lee Woo Sing College',
         'Please refer to college website', '', 'Cafe', 'Open'),
        ('The Stage', 'Yasumoto International Academic Park',
         'Mon-Fri 08:15-16:30', '', 'Cafe', 'Open'),
        ('Gastronomy Club', 'Yasumoto International Academic Park',
         'Members only', '', 'Restaurant', 'Open'),
        ('Inno330', 'Cheng Yu Tung Building',
         'Please refer to outlet', '', 'Cafe', 'Open'),
        ('Tea House', 'Cheng Yu Tung Building',
         'Please refer to outlet', '', 'Restaurant', 'Open'),
        ('The Infinity Room', 'Cheng Yu Tung Building',
         'Please refer to outlet', '', 'Restaurant', 'Open'),
        ('Art Museum Cafe - Ideaology', 'Art Museum',
         'Please refer to outlet', '', 'Cafe', 'Open'),
        ('Benjamin Franklin Centre Vegetarian Food Shop', 'Benjamin Franklin Centre',
         '', '', 'Canteen', 'Closed'),
        ('Lee Shau Kee Building Snack Bar', 'Lee Shau Kee Building',
         '', '', 'Snack Bar', 'Closed'),
        ('YIA Cafe', 'Yasumoto International Academic Park',
         '', '', 'Cafe', 'Closed'),
        ('Postgraduate Hall 3 Canteen', 'Postgraduate Hall 3',
         '', '', 'Canteen', 'Closed')
    """)


def downgrade() -> None:
    """清空种子数据"""
    op.execute("DELETE FROM course_info WHERE update_time = '2026-08-01 10:00:00'")
    op.execute("DELETE FROM campus_events WHERE organizer = 'CUHK CPR' OR organizer LIKE '%College%' OR organizer IN ('CSCI Department', 'Career Planning Office', 'CSCI Student Society', 'ITSC', 'Graduate School', 'University Health Service', 'CUHK Entrepreneurship Centre')")
    op.execute("DELETE FROM canteen WHERE status IN ('Open', 'Closed')")
