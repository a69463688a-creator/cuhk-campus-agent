-- ============================================================
-- CUHK 自习室 种子数据
-- ============================================================
INSERT INTO study_rooms (building, room_number, room_date, start_time, end_time, capacity, available_seats, has_projector, has_ac, status) VALUES
('Yasumoto International Academic Park', 'YIA301', '2026-08-10', '08:00:00', '22:00:00', 40, 12, 1, 1, 'available'),
('Yasumoto International Academic Park', 'YIA301', '2026-08-11', '08:00:00', '22:00:00', 40, 25, 1, 1, 'available'),
('Yasumoto International Academic Park', 'YIA301', '2026-08-12', '08:00:00', '22:00:00', 40, 8, 1, 1, 'available'),
('Yasumoto International Academic Park', 'YIA402', '2026-08-10', '08:00:00', '22:00:00', 30, 5, 0, 1, 'available'),
('Yasumoto International Academic Park', 'YIA402', '2026-08-11', '08:00:00', '22:00:00', 30, 15, 0, 1, 'available'),
('Yasumoto International Academic Park', 'YIA402', '2026-08-12', '08:00:00', '22:00:00', 30, 0, 0, 1, 'full'),
('Lee Shau Kee Building', 'LSK201', '2026-08-10', '09:00:00', '21:00:00', 60, 30, 1, 1, 'available'),
('Lee Shau Kee Building', 'LSK201', '2026-08-11', '09:00:00', '21:00:00', 60, 42, 1, 1, 'available'),
('Lee Shau Kee Building', 'LSK201', '2026-08-12', '09:00:00', '21:00:00', 60, 18, 1, 1, 'available'),
('Lee Shau Kee Building', 'LSK304', '2026-08-10', '09:00:00', '21:00:00', 25, 3, 0, 1, 'available'),
('Science Centre', 'SC101', '2026-08-10', '10:00:00', '20:00:00', 50, 20, 1, 1, 'available'),
('Science Centre', 'SC101', '2026-08-11', '10:00:00', '20:00:00', 50, 35, 1, 1, 'available'),
('Science Centre', 'SC101', '2026-08-12', '10:00:00', '20:00:00', 50, 10, 1, 1, 'available'),
('Mong Man Wai Building', 'MMW202', '2026-08-10', '08:30:00', '22:30:00', 35, 15, 1, 1, 'available'),
('Mong Man Wai Building', 'MMW202', '2026-08-11', '08:30:00', '22:30:00', 35, 22, 1, 1, 'available'),
('Mong Man Wai Building', 'MMW202', '2026-08-12', '08:30:00', '22:30:00', 35, 7, 1, 1, 'available'),
('Ho Sin Hang Building', 'HSH101', '2026-08-10', '08:00:00', '23:00:00', 45, 28, 1, 1, 'available'),
('Ho Sin Hang Building', 'HSH101', '2026-08-11', '08:00:00', '23:00:00', 45, 33, 1, 1, 'available');

-- ============================================================
-- CUHK 图书馆座位 种子数据
-- ============================================================
INSERT INTO library_seats (library_name, floor, zone, seat_date, time_slot, total_seats, available_seats, has_power, is_quiet_zone) VALUES
('University Library', 1, 'Learning Commons', '2026-08-10', '09:00-12:00', 80, 25, 1, 0),
('University Library', 1, 'Learning Commons', '2026-08-10', '14:00-17:00', 80, 18, 1, 0),
('University Library', 2, 'Quiet Study Zone', '2026-08-10', '09:00-12:00', 120, 45, 1, 1),
('University Library', 2, 'Quiet Study Zone', '2026-08-10', '14:00-17:00', 120, 32, 1, 1),
('University Library', 3, 'Research Zone', '2026-08-10', '09:00-12:00', 50, 15, 1, 1),
('University Library', 3, 'Research Zone', '2026-08-10', '14:00-17:00', 50, 10, 1, 1),
('Chung Chi Library', 1, 'Reading Area', '2026-08-10', '09:00-12:00', 60, 30, 1, 0),
('Chung Chi Library', 1, 'Reading Area', '2026-08-10', '14:00-17:00', 60, 22, 1, 0),
('Chung Chi Library', 2, 'Silent Zone', '2026-08-10', '09:00-12:00', 40, 18, 1, 1),
('New Asia Library', 1, 'Group Study', '2026-08-10', '09:00-12:00', 30, 12, 1, 0),
('New Asia Library', 1, 'Group Study', '2026-08-10', '14:00-17:00', 30, 8, 1, 0),
('United College Library', 1, 'Main Reading', '2026-08-10', '09:00-12:00', 45, 20, 1, 0),
('Lee Quo Wei Law Library', 2, 'Quiet Study', '2026-08-10', '09:00-12:00', 35, 15, 1, 1);

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
