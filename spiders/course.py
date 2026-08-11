#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: spider_course.py
项目: SmartCampus — CUHK校园生活助手
描述: CUHK课程数据采集器
      从 another-cuhk-course-planner 项目的预抓取 JSON 数据中拉取 2026-27 学年
      课程信息，解析并写入 course_info 表。
      数据源: GitHub — EagleZhen/another-cuhk-course-planner

数据源说明:
      课程数据来自 CUHK RES（学生信息系统）的公开课程目录。
      社区项目 another-cuhk-course-planner 使用 requests + BeautifulSoup
      对 RES 进行了完整抓取，输出为按学科分类的 JSON 文件。
      本脚本直接使用其预抓取的 JSON 文件，通过 GitHub Raw 访问。
"""
import re
import time
import sys
from datetime import datetime, timedelta
from typing import Optional

import mysql.connector
import pytz
import requests

from spiders.base import BaseSpider

TZ = pytz.timezone('Asia/Shanghai')

# 课程数据源 — GitHub Raw
REPO_BASE = (
    "https://raw.githubusercontent.com/"
    "EagleZhen/another-cuhk-course-planner/main/data/2026-27"
)

# 要抓取的学科列表（CUHK 主要院系）
SUBJECTS = [
    # 工程学院
    "CSCI", "ENGG", "ELEG", "SEEM", "MAEG", "BMEG", "DSPS",
    # 理学院
    "MATH", "STAT", "PHYS", "CHEM", "BIOL", "BCHE", "CMBI", "LSCI",
    # 商学院
    "ACCT", "FINA", "MGNT", "COMM", "DSME", "ECON",
    # 社科学院
    "PSYC", "SOCI", "TRAN", "GLSD",
    # 法学院
    "LAWS",
    # 文学院
    "CHES", "ENGE", "HIST", "PHIL",
    # 医学院
    "MEDU", "NURS", "PHAR", "SBMS",
]

REQUEST_TIMEOUT = 20

# ============ 时间解析 ============

DAY_MAP = {
    'mo': 'Mon', 'tu': 'Tue', 'we': 'Wed', 'th': 'Thu',
    'fr': 'Fri', 'sa': 'Sat', 'su': 'Sun',
}


def parse_meeting_time(time_str):
    """
    解析 "Mo 1:30PM - 3:15PM" 格式的时间字符串。
    返回 (day, start_time, end_time) 或 (None, None, None)。
    """
    if not time_str or time_str == 'TBA':
        return None, None, None

    m = re.match(
        r'(\w{2})\s+'
        r'(\d{1,2}):(\d{2})\s*(AM|PM)\s*[-–]\s*'
        r'(\d{1,2}):(\d{2})\s*(AM|PM)',
        time_str, re.IGNORECASE
    )
    if not m:
        return None, None, None

    day_abbr = m.group(1).lower()
    h1, m1, ap1 = int(m.group(2)), int(m.group(3)), m.group(4).upper()
    h2, m2, ap2 = int(m.group(5)), int(m.group(6)), m.group(7).upper()

    def to_24h(h, m, ap):
        if ap == 'PM' and h != 12:
            h += 12
        if ap == 'AM' and h == 12:
            h = 0
        return f"{h:02d}:{m:02d}:00"

    day = DAY_MAP.get(day_abbr, day_abbr.capitalize())
    start = to_24h(h1, m1, ap1)
    end = to_24h(h2, m2, ap2)
    return day, start, end


def split_location(location_str):
    """
    将 "William M W Mong Eng Bldg 404" 拆分为 (building, room_number)。
    """
    if not location_str or location_str == 'TBA':
        return 'TBA', 'TBA'

    patterns = [
        r'^(.+?\bBldg\b)\s*(.+)$',
        r'^(.+?\bBuilding\b)\s*(.+)$',
        r'^(.+?\bBld\b)\s*(.+)$',
        r'^(.+?\bHall\b)\s*(.+)$',
        r'^(.+?\bCentre\b)\s*(.+)$',
        r'^(.+?\bCenter\b)\s*(.+)$',
        r'^(.+?\bCollege\b)\s*(.+)$',
        r'^(.+?\bLT\d+)\s*(.*)$',
    ]
    for pat in patterns:
        m = re.match(pat, location_str, re.IGNORECASE)
        if m:
            return m.group(1).strip(), m.group(2).strip()

    return location_str, ''


def parse_credits(credits_str):
    """解析 credits 字符串，如 '3.00' → 3"""
    try:
        return int(float(credits_str))
    except (ValueError, TypeError):
        return 0


# ============ 数据获取 ============

def fetch_subject_data(subject):
    """从 GitHub Raw 获取单个学科的课程 JSON。"""
    url = f"{REPO_BASE}/{subject}.json"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and 'courses' in data:
            return data['courses']
    except Exception as e:
        print(f"[WARN] 获取 {subject} 失败: {e}")
    return []


# ============ 数据转换与写入 ============

def transform_courses(subject_data):
    """
    将课程 JSON 转换为 course_info 表的行格式。
    每个 unique (course_code, schedule_day, start_time) 生成一行。
    """
    rows = []
    now_str = datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')

    department_map = {
        'CSCI': 'CSCI', 'ENGG': 'ENGG', 'ELEG': 'ELEG', 'SEEM': 'SEEM',
        'MAEG': 'MAEG', 'BMEG': 'BMEG', 'DSPS': 'DSPS',
        'MATH': 'MATH', 'STAT': 'STAT', 'PHYS': 'PHYS', 'CHEM': 'CHEM',
        'BIOL': 'BIOL', 'BCHE': 'BCHE', 'CMBI': 'CMBI', 'LSCI': 'LSCI',
        'ACCT': 'ACCT', 'FINA': 'FINA', 'MGNT': 'MGNT', 'COMM': 'COMM',
        'DSME': 'DSME', 'ECON': 'ECON',
        'PSYC': 'PSYC', 'SOCI': 'SOCI', 'TRAN': 'TRAN', 'GLSD': 'GLSD',
        'LAWS': 'LAWS',
        'CHES': 'CHES', 'ENGE': 'ENGE', 'HIST': 'HIST', 'PHIL': 'PHIL',
        'MEDU': 'MEDU', 'NURS': 'NURS', 'PHAR': 'PHAR', 'SBMS': 'SBMS',
    }

    for course in subject_data:
        subject = course.get('subject', '')
        code = course.get('course_code', '')
        full_code = f"{subject}{code}"
        title = (course.get('title') or 'Unknown')[:100]
        credits_val = parse_credits(course.get('credits', '0'))
        description = (course.get('description') or '')[:5000]
        dept = (course.get('academic_group') or subject)[:50]
        category = department_map.get(subject, 'Others')

        seen_meetings = {}

        for term_info in course.get('terms', []):
            for section in term_info.get('schedule', []):
                availability = section.get('availability', {})
                capacity = 0
                enrolled = 0
                try:
                    capacity = int(availability.get('capacity', 0))
                except (ValueError, TypeError):
                    pass
                try:
                    enrolled = int(availability.get('enrolled', 0))
                except (ValueError, TypeError):
                    pass

                for meeting in section.get('meetings', []):
                    time_str = meeting.get('time', '')
                    location = meeting.get('location', 'TBA')
                    instructor = (meeting.get('instructor') or 'TBA')[:50]

                    day, start_t, end_t = parse_meeting_time(time_str)
                    if not day:
                        continue

                    building, classroom = split_location(location)
                    classroom = classroom[:50] if classroom else building[:50]
                    building = building[:80]

                    meeting_key = (day, start_t)
                    if meeting_key in seen_meetings:
                        prev = seen_meetings[meeting_key]
                        if capacity > prev['capacity']:
                            prev.update({
                                'capacity': capacity, 'end_t': end_t,
                                'instructor': instructor, 'classroom': classroom,
                                'building': building,
                            })
                        if enrolled > prev['enrolled']:
                            prev['enrolled'] = enrolled
                    else:
                        seen_meetings[meeting_key] = {
                            'end_t': end_t, 'instructor': instructor,
                            'classroom': classroom, 'building': building,
                            'capacity': capacity, 'enrolled': enrolled,
                        }

        if seen_meetings:
            for (day, start_t), info in seen_meetings.items():
                rows.append((
                    full_code, title, dept, info['instructor'],
                    day, start_t, info['end_t'],
                    info['classroom'], info['building'],
                    credits_val, info['capacity'], info['enrolled'],
                    category,
                    f"{description} | course_spider @ {now_str}",
                    now_str,
                ))
        else:
            rows.append((
                full_code, title, dept, 'TBA',
                '', '', '',
                'TBA', 'TBA',
                credits_val, 0, 0,
                category,
                f"{description} | course_spider @ {now_str}",
                now_str,
            ))

    return rows


def store_courses(conn, cursor, rows):
    """
    写入 course_info 表。
    按 subject 清除旧数据后插入新数据，确保课程安排最新。
    """
    if not rows:
        return 0

    # 收集受影响的 subject 并清除旧数据
    affected_codes = set(r[0] for r in rows)
    affected_subjects = set()
    for code in affected_codes:
        subj = re.match(r'^([A-Z]+)', code)
        if subj:
            affected_subjects.add(subj.group(1))

    for subj in affected_subjects:
        cursor.execute(
            "DELETE FROM course_info WHERE course_code LIKE %s",
            (f"{subj}%",)
        )

    insert_sql = """
    INSERT INTO course_info (
        course_code, course_name, department, instructor,
        schedule_day, start_time, end_time,
        classroom, building,
        credits, capacity, enrolled,
        category, description, update_time
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    count = 0
    for row in rows:
        try:
            cursor.execute(insert_sql, row)
            count += 1
        except mysql.connector.Error as e:
            print(f"[WARN] 写入失败 ({row[0]}): {e}")
            continue

    conn.commit()
    return count


class CourseSpider(BaseSpider):
    """CUHK 课程数据爬虫

    由于课程数据按学科分文件存储，需要逐学科拉取并写入，
    因此覆盖 update_data() 实现分科迭代逻辑。
    """

    name = "Course Data Spider"
    data_source = REPO_BASE
    stale_hours = 168
    table_name = "course_info"
    schedule_time = "02:00"
    schedule_rule = "sunday"
    timestamp_column = "update_time"
    update_filter = "description LIKE '%course_spider%'"

    def fetch(self):
        """课程数据通过 update_data() 的分科迭代直接处理，此方法不使用。"""
        return SUBJECTS  # 返回学科列表作为信号

    def store(self, conn, cursor, items):
        """课程数据通过 update_data() 的分科迭代直接处理，此方法不使用。"""
        return 0

    def update_data(self, force: bool = False) -> Optional[int]:
        """
        覆盖基类的 update_data()，实现逐学科拉取→转换→写入。
        每个学科独立处理，避免单个学科失败影响全部。
        """
        conn = self.connect_db()
        cursor = conn.cursor()

        try:
            latest = self.get_latest_fetch_time(cursor)
            if not self.should_update(latest, force):
                print(f"[INFO] 课程数据已是最新（上次更新: {latest}），跳过。")
                return None

            total_courses = 0
            total_rows = 0

            for subject in SUBJECTS:
                print(f"[FETCH] {subject} ...", end=' ', flush=True)
                courses = fetch_subject_data(subject)
                if not courses:
                    print("0 courses (skip)")
                    continue

                rows = transform_courses(courses)
                written = store_courses(conn, cursor, rows)
                print(f"{len(courses)} courses → {written} rows")
                total_courses += len(courses)
                total_rows += written

                time.sleep(0.5)  # 避免 GitHub 限流

            print("=" * 50)
            print(f"[DONE] {len(SUBJECTS)} subjects, "
                  f"{total_courses} courses, {total_rows} rows")
            return total_rows
        finally:
            cursor.close()
            conn.close()

    def print_banner(self, force: bool, once: bool):
        """覆盖基类横幅，额外显示学科数量。"""
        super().print_banner(force, once)
        print(f"  学科数: {len(SUBJECTS)}")


if __name__ == "__main__":
    CourseSpider.main()
