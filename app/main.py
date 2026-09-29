"""API مزاج‌شناسی - اجرا:  uvicorn app.main:app --reload   (از ریشه پروژه)"""
import csv, io, json, os, re, secrets, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator

from .mizaj_engine import QUESTIONS, evaluate
from .setteh import generate

DB_PATH = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parent.parent / "data") / "mizaj.db"
ADMIN_KEY = os.environ.get("ADMIN_KEY", "change-me")
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

app = FastAPI(title="Mizaj API")

@contextmanager
def db():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()

with db() as c:
    c.execute("""CREATE TABLE IF NOT EXISTS people(
        id INTEGER PRIMARY KEY, code TEXT UNIQUE, created_at TEXT, first_name TEXT, last_name TEXT,
        mobile TEXT, city TEXT, gender TEXT, age INTEGER, season TEXT, hc REAL, wd REAL,
        mizaj TEXT, degree TEXT, setteh TEXT, answers TEXT)""")

def admin(key):
    if not key or not secrets.compare_digest(key, ADMIN_KEY):
        raise HTTPException(401, "کلید ادمین نامعتبر است")

class Submission(BaseModel):
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    mobile: str
    city: str = Field(min_length=1, max_length=60)
    gender: str
    age: int = Field(ge=5, le=110)
    answers: list[int]

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v):
        v = re.sub(r"[\s\-]", "", v)
        if not re.fullmatch(r"\+?\d{10,15}", v):
            raise ValueError("شماره موبایل نامعتبر است")
        return v

    @field_validator("gender")
    @classmethod
    def _gender(cls, v):
        if v not in ("زن", "مرد"):
            raise ValueError("جنسیت باید «زن» یا «مرد» باشد")
        return v

    @field_validator("answers")
    @classmethod
    def _answers(cls, v):
        if len(v) != len(QUESTIONS) or any(a not in (0, 1, 2) for a in v):
            raise ValueError("۲۴ پاسخ با مقدار ۰ تا ۲ لازم است")
        return v

@app.get("/", include_in_schema=False)
def home():
    return FileResponse(Path(__file__).resolve().parent / "static" / "index.html")

@app.get("/questions")
def questions():
    return [{"id": i, "text": t, "options": [o for o, _ in opts]} for i, (_, t, opts) in enumerate(QUESTIONS)]

@app.post("/submit")
def submit(s: Submission):
    r = evaluate(s.answers, s.age, s.gender)
    text = generate(r["hc_sign"], r["wd_sign"])
    with db() as c:
        for _ in range(10):
            code = "MZ-" + "".join(secrets.choice(ALPHABET) for _ in range(6))
            try:
                c.execute("INSERT INTO people(code,created_at,first_name,last_name,mobile,city,gender,age,season,hc,wd,mizaj,degree,setteh,answers)"
                          " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (code, datetime.now(timezone.utc).isoformat(), s.first_name, s.last_name, s.mobile, s.city,
                           s.gender, s.age, r["season"], r["hc"], r["wd"], r["mizaj"], r["degree"], text, json.dumps(s.answers)))
                break
            except sqlite3.IntegrityError:
                continue
        else:
            raise HTTPException(500, "ساخت کد پیگیری ناموفق بود")
    return {"tracking_code": code, "message": "اطلاعات شما ثبت شد. نتیجه به‌زودی از طریق مشاور ارسال می‌شود."}

@app.get("/admin/lookup/{code}")
def lookup(code: str, x_admin_key: Optional[str] = Header(None)):
    admin(x_admin_key)
    with db() as c:
        row = c.execute("SELECT * FROM people WHERE code=?", (code.upper(),)).fetchone()
    if not row:
        raise HTTPException(404, "کد یافت نشد")
    d = dict(row); d["answers"] = json.loads(d["answers"])
    return d

@app.get("/admin/contacts")
def contacts(city: Optional[str] = None, gender: Optional[str] = None, min_age: int = 0, max_age: int = 200,
             x_admin_key: Optional[str] = Header(None)):
    admin(x_admin_key)
    q, p = "SELECT code,first_name,last_name,mobile,city,gender,age,mizaj,degree,created_at FROM people WHERE age BETWEEN ? AND ?", [min_age, max_age]
    if city: q += " AND city=?"; p.append(city)
    if gender: q += " AND gender=?"; p.append(gender)
    with db() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY id DESC", p)]

@app.get("/admin/export.csv")
def export(x_admin_key: Optional[str] = Header(None)):
    admin(x_admin_key)
    with db() as c:
        rows = c.execute("SELECT code,first_name,last_name,mobile,city,gender,age,mizaj,degree,created_at FROM people ORDER BY id").fetchall()
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["code", "first_name", "last_name", "mobile", "city", "gender", "age", "mizaj", "degree", "created_at"])
    w.writerows([list(r) for r in rows])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=contacts.csv"})
