from datetime import datetime
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo
import sqlite3

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Smart Attendance API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this when deploying publicly.
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path(__file__).with_name("attendance.db")
DB_LOCK = Lock()
IST = ZoneInfo("Asia/Kolkata")


def connect_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_db():
    with connect_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                session_date TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                is_open INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                marked_at TEXT NOT NULL,

                FOREIGN KEY(session_id) REFERENCES sessions(id),
                FOREIGN KEY(student_id) REFERENCES students(id),

                UNIQUE(session_id, student_id)
            );
        """)


initialize_db()


class ScanRequest(BaseModel):
    uid: str
    session_id: int


class StudentRequest(BaseModel):
    uid: str
    name: str


class SessionRequest(BaseModel):
    subject: str


@app.get("/")
def home():
    return {"message": "Smart Attendance API is running"}


# Register a student's RFID card.
@app.post("/students")
def register_student(data: StudentRequest):
    uid = data.uid.strip().upper()
    name = data.name.strip()

    if not uid or not name:
        return {"status": "error", "message": "UID and name are required"}

    try:
        with DB_LOCK, connect_db() as conn:
            conn.execute(
                "INSERT INTO students(uid, name) VALUES (?, ?)",
                (uid, name)
            )

        return {"status": "registered", "uid": uid, "name": name}

    except sqlite3.IntegrityError:
        return {"status": "error", "message": "UID already registered"}


# Start a new attendance session.
@app.post("/sessions/start")
def start_session(data: SessionRequest):
    subject = data.subject.strip()

    if not subject:
        return {"status": "error", "message": "Subject is required"}

    now = datetime.now(IST)

    with DB_LOCK, connect_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO sessions(subject, session_date, started_at)
            VALUES (?, ?, ?)
            """,
            (
                subject,
                now.date().isoformat(),
                now.isoformat()
            )
        )

        session_id = cursor.lastrowid

    return {
        "status": "started",
        "session_id": session_id,
        "subject": subject,
        "date": now.date().isoformat(),
        "started_at": now.isoformat()
    }


# Record attendance after an RFID scan.
@app.post("/attendance/scan")
def scan_attendance(data: ScanRequest):
    uid = data.uid.strip().upper()
    now = datetime.now(IST).isoformat()

    with DB_LOCK, connect_db() as conn:
        student = conn.execute(
            "SELECT id, name FROM students WHERE uid = ?",
            (uid,)
        ).fetchone()

        if student is None:
            return {"status": "unknown_card"}

        session = conn.execute(
            "SELECT id, is_open FROM sessions WHERE id = ?",
            (data.session_id,)
        ).fetchone()

        if session is None or session["is_open"] != 1:
            return {"status": "session_closed"}

        existing = conn.execute(
            """
            SELECT id FROM attendance
            WHERE session_id = ? AND student_id = ?
            """,
            (data.session_id, student["id"])
        ).fetchone()

        if existing:
            return {
                "status": "already_marked",
                "name": student["name"]
            }

        conn.execute(
            """
            INSERT INTO attendance(session_id, student_id, marked_at)
            VALUES (?, ?, ?)
            """,
            (data.session_id, student["id"], now)
        )

    return {
        "status": "marked",
        "name": student["name"],
        "uid": uid,
        "date_time": now
    }


# Get attendance records for the teacher's dashboard.
@app.get("/attendance/{session_id}")
def get_attendance(session_id: int):
    with connect_db() as conn:
        session = conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,)
        ).fetchone()

        if session is None:
            return {"status": "error", "message": "Session not found"}

        records = conn.execute(
            """
            SELECT students.name, students.uid, attendance.marked_at
            FROM attendance
            JOIN students ON students.id = attendance.student_id
            WHERE attendance.session_id = ?
            ORDER BY attendance.marked_at
            """,
            (session_id,)
        ).fetchall()

        total_students = conn.execute(
            "SELECT COUNT(*) FROM students"
        ).fetchone()[0]

    present = len(records)

    return {
        "session_id": session_id,
        "subject": session["subject"],
        "date": session["session_date"],
        "started_at": session["started_at"],
        "completed_at": session["completed_at"],
        "is_open": bool(session["is_open"]),
        "total_students": total_students,
        "present": present,
        "absent": max(0, total_students - present),
        "attendance": [dict(row) for row in records]
    }


# Complete the session.
@app.post("/sessions/{session_id}/complete")
def complete_session(session_id: int):
    now = datetime.now(IST).isoformat()

    with DB_LOCK, connect_db() as conn:
        session = conn.execute(
            "SELECT id, is_open FROM sessions WHERE id = ?",
            (session_id,)
        ).fetchone()

        if session is None:
            return {"status": "error", "message": "Session not found"}

        if session["is_open"] == 0:
            return {"status": "completed", "message": "Already completed"}

        conn.execute(
            """
            UPDATE sessions
            SET is_open = 0, completed_at = ?
            WHERE id = ?
            """,
            (now, session_id)
        )

    return {
        "status": "completed",
        "session_id": session_id,
        "completed_at": now
    }