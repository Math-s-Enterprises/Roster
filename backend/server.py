from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Cookie, Header
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os, logging, uuid, jwt, bcrypt, httpx, stripe
from pathlib import Path
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from emergentintegrations.llm.chat import LlmChat, UserMessage

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
mclient = AsyncIOMotorClient(mongo_url)
db = mclient[os.environ['DB_NAME']]

JWT_SECRET = os.environ['JWT_SECRET']
EMERGENT_LLM_KEY = os.environ['EMERGENT_LLM_KEY']
EMERGENT_EMAIL_KEY = os.environ['EMERGENT_EMAIL_KEY']
EMAIL_FROM_NAME = os.environ['EMAIL_FROM_NAME']
OWNER_EMAIL = os.environ['OWNER_EMAIL']
EMAIL_BASE_URL = "https://integrations.emergentagent.com"

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY") or "sk_test_emergent"
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

app = FastAPI()
api = APIRouter(prefix="/api")
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("roster")


class SignupReq(BaseModel):
    email: EmailStr
    password: str
    name: str
    shop_name: Optional[str] = None

class LoginReq(BaseModel):
    email: EmailStr
    password: str

class ShopHours(BaseModel):
    day: str
    open: str
    close: str
    closed: bool = False

class ShopUpdate(BaseModel):
    name: Optional[str] = None
    hours: Optional[List[ShopHours]] = None
    min_shift_hours: Optional[float] = None
    max_shift_hours: Optional[float] = None
    roles: Optional[List[str]] = None
    departments: Optional[List[str]] = None
    multi_department: Optional[bool] = None
    onboarded: Optional[bool] = None

class EmployeeIn(BaseModel):
    name: str
    email: EmailStr
    role: str
    age: int
    hourly_rate: float
    max_weekly_hours: float = 40
    avatar: Optional[str] = None
    preferred_days_off: List[str] = []
    departments: List[str] = ["Shop Floor"]

class HolidayIn(BaseModel):
    date: str
    end_date: Optional[str] = None
    label: str
    scope: str = "shop"  # "shop" | "employee" | "sick"
    employee_id: Optional[str] = None

class FixedShiftIn(BaseModel):
    employee_id: str
    days: List[str]
    start: str
    end: str

class AIRuleIn(BaseModel):
    title: str
    description: str
    enabled: bool = True
    category: str = "custom"

class RosterGenReq(BaseModel):
    week_start: str
    department: Optional[str] = None

class ShiftIn(BaseModel):
    employee_id: str
    day: str
    start: str
    end: str
    paid_holiday: bool = False
    unpaid_holiday: bool = False
    sick: bool = False
    temp_override: bool = False

class RosterUpdate(BaseModel):
    shifts: List[ShiftIn]


def hash_pw(pw): return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
def check_pw(pw, h):
    try: return bcrypt.checkpw(pw.encode(), h.encode())
    except Exception: return False
def make_jwt(uid): return jwt.encode({"user_id": uid, "exp": datetime.now(timezone.utc) + timedelta(days=7)}, JWT_SECRET, algorithm="HS256")


async def get_current_user(authorization: Optional[str] = Header(None), session_token: Optional[str] = Cookie(None)):
    if authorization and authorization.startswith("Bearer "):
        try:
            payload = jwt.decode(authorization.replace("Bearer ", ""), JWT_SECRET, algorithms=["HS256"])
            u = await db.users.find_one({"user_id": payload.get("user_id")}, {"_id": 0})
            if u: return u
        except Exception: pass
    if session_token:
        s = await db.user_sessions.find_one({"session_token": session_token}, {"_id": 0})
        if s:
            exp = s["expires_at"]
            if isinstance(exp, str): exp = datetime.fromisoformat(exp)
            if exp.tzinfo is None: exp = exp.replace(tzinfo=timezone.utc)
            if exp >= datetime.now(timezone.utc):
                u = await db.users.find_one({"user_id": s["user_id"]}, {"_id": 0})
                if u: return u
    raise HTTPException(401, "Not authenticated")


DEFAULT_HOURS = [{"day": d, "open": "09:00", "close": "21:00", "closed": False} for d in ["mon","tue","wed","thu","fri","sat"]] + [{"day": "sun", "open": "10:00", "close": "18:00", "closed": False}]
DEFAULT_ROLES = ["Manager", "Supervisor", "Cashier", "Floor Assistant", "Stocker"]
DEFAULT_DEPARTMENTS = ["Shop Floor", "Deli"]
DEFAULT_AI_RULES = [
    {"title": "Under-16 curfew", "description": "Employees under 16 cannot work past 19:00 or before 08:00.", "enabled": True, "category": "legal"},
    {"title": "Weekly hour cap", "description": "No employee may exceed their max_weekly_hours setting.", "enabled": True, "category": "legal"},
    {"title": "Rest between shifts", "description": "At least 11 hours between shifts for the same employee.", "enabled": True, "category": "safety"},
    {"title": "Manager coverage", "description": "At least one Manager or Supervisor scheduled during opening hours.", "enabled": True, "category": "safety"},
]


async def ensure_shop(user):
    ex = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if ex: return ex
    shop = {
        "shop_id": f"shop_{uuid.uuid4().hex[:12]}", "owner_id": user["user_id"],
        "name": user.get("shop_name") or f"{user['name'].split()[0]}'s Shop",
        "hours": DEFAULT_HOURS, "min_shift_hours": 4, "max_shift_hours": 9,
        "roles": DEFAULT_ROLES, "departments": DEFAULT_DEPARTMENTS,
        "multi_department": False, "onboarded": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.shops.insert_one(shop.copy())
    for r in DEFAULT_AI_RULES:
        await db.ai_rules.insert_one({"rule_id": f"rule_{uuid.uuid4().hex[:12]}", "shop_id": shop["shop_id"], **r})
    return await db.shops.find_one({"shop_id": shop["shop_id"]}, {"_id": 0})


@api.post("/auth/signup")
async def signup(req: SignupReq):
    if await db.users.find_one({"email": req.email.lower()}, {"_id": 0}):
        raise HTTPException(400, "Email already registered")
    uid = f"user_{uuid.uuid4().hex[:12]}"
    user = {"user_id": uid, "email": req.email.lower(), "name": req.name, "password_hash": hash_pw(req.password),
            "shop_name": req.shop_name, "created_at": datetime.now(timezone.utc).isoformat()}
    await db.users.insert_one(user.copy())
    await ensure_shop(user)
    return {"token": make_jwt(uid), "user": {"user_id": uid, "email": user["email"], "name": user["name"]}}


@api.post("/auth/login")
async def login(req: LoginReq):
    u = await db.users.find_one({"email": req.email.lower()}, {"_id": 0})
    if not u or not u.get("password_hash") or not check_pw(req.password, u["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    await ensure_shop(u)
    return {"token": make_jwt(u["user_id"]), "user": {"user_id": u["user_id"], "email": u["email"], "name": u["name"]}}


@api.post("/auth/google/session")
async def google_session(request: Request, response: Response):
    body = await request.json()
    sid = body.get("session_id")
    if not sid: raise HTTPException(400, "Missing session_id")
    async with httpx.AsyncClient(timeout=15) as h:
        r = await h.get("https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data", headers={"X-Session-ID": sid})
    if r.status_code != 200: raise HTTPException(401, "Invalid session")
    data = r.json()
    email = data["email"].lower()
    ex = await db.users.find_one({"email": email}, {"_id": 0})
    if ex:
        uid = ex["user_id"]
    else:
        uid = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({"user_id": uid, "email": email, "name": data.get("name") or email.split("@")[0],
                                    "picture": data.get("picture"), "created_at": datetime.now(timezone.utc).isoformat()})
    u = await db.users.find_one({"user_id": uid}, {"_id": 0})
    await ensure_shop(u)
    tok = data["session_token"]
    await db.user_sessions.insert_one({"user_id": uid, "session_token": tok,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()})
    response.set_cookie("session_token", tok, httponly=True, secure=True, samesite="none", path="/", max_age=7*24*3600)
    return {"user": {"user_id": uid, "email": u["email"], "name": u["name"], "picture": u.get("picture")}}


@api.get("/auth/me")
async def me(u=Depends(get_current_user)):
    # DEV MODE: unlimited access — all users are treated as Pro until production
    return {"user_id": u["user_id"], "email": u["email"], "name": u["name"], "picture": u.get("picture"), "pro": True}


@api.post("/auth/logout")
async def logout(response: Response, session_token: Optional[str] = Cookie(None)):
    if session_token: await db.user_sessions.delete_one({"session_token": session_token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


@api.get("/shop")
async def get_shop(u=Depends(get_current_user)):
    return await ensure_shop(u)


@api.put("/shop")
async def update_shop(p: ShopUpdate, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    upd = {k: v for k, v in p.model_dump(exclude_unset=True).items() if v is not None}
    if upd: await db.shops.update_one({"shop_id": s["shop_id"]}, {"$set": upd})
    return await db.shops.find_one({"shop_id": s["shop_id"]}, {"_id": 0})


AVATARS = [
    "https://images.unsplash.com/photo-1610721193651-e6aca85b45aa?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA3MDB8MHwxfHNlYXJjaHw0fHxwcm9mZXNzaW9uYWwlMjBhdmF0YXIlMjBwb3J0cmFpdCUyMGJsYWNrJTIwYmFja2dyb3VuZHxlbnwwfHx8fDE3ODUyNzM0MTB8MA&ixlib=rb-4.1.0&q=85",
    "https://images.unsplash.com/photo-1673830719944-7bf527816dae?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA3MDB8MHwxfHNlYXJjaHwxfHxwcm9mZXNzaW9uYWwlMjBhdmF0YXIlMjBwb3J0cmFpdCUyMGJsYWNrJTIwYmFja2dyb3VuZHxlbnwwfHx8fDE3ODUyNzM0MTB8MA&ixlib=rb-4.1.0&q=85",
    "https://images.unsplash.com/photo-1673830718731-39d6542835c8?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA3MDB8MHwxfHNlYXJjaHwyfHxwcm9mZXNzaW9uYWwlMjBhdmF0YXIlMjBwb3J0cmFpdCUyMGJsYWNrJTIwYmFja2dyb3VuZHxlbnwwfHx8fDE3ODUyNzM0MTB8MA&ixlib=rb-4.1.0&q=85",
    "https://images.unsplash.com/photo-1641311280728-bec9ba3f221f?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA3MDB8MHwxfHNlYXJjaHwzfHxwcm9mZXNzaW9uYWwlMjBhdmF0YXIlMjBwb3J0cmFpdCUyMGJsYWNrJTIwYmFja2dyb3VuZHxlbnwwfHx8fDE3ODUyNzM0MTB8MA&ixlib=rb-4.1.0&q=85",
]


@api.get("/employees")
async def emp_list(u=Depends(get_current_user)):
    s = await ensure_shop(u)
    return await db.employees.find({"shop_id": s["shop_id"]}, {"_id": 0}).to_list(500)

@api.post("/employees")
async def emp_new(p: EmployeeIn, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    eid = f"emp_{uuid.uuid4().hex[:12]}"
    c = await db.employees.count_documents({"shop_id": s["shop_id"]})
    doc = {"employee_id": eid, "shop_id": s["shop_id"], **p.model_dump(),
           "avatar": p.avatar or AVATARS[c % len(AVATARS)]}
    await db.employees.insert_one(doc.copy())
    return await db.employees.find_one({"employee_id": eid}, {"_id": 0})

@api.put("/employees/{eid}")
async def emp_upd(eid: str, p: EmployeeIn, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    await db.employees.update_one({"employee_id": eid, "shop_id": s["shop_id"]}, {"$set": p.model_dump()})
    return await db.employees.find_one({"employee_id": eid}, {"_id": 0})

@api.delete("/employees/{eid}")
async def emp_del(eid: str, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    await db.employees.delete_one({"employee_id": eid, "shop_id": s["shop_id"]})
    return {"ok": True}


@api.get("/holidays")
async def hol_list(u=Depends(get_current_user)):
    s = await ensure_shop(u)
    return await db.holidays.find({"shop_id": s["shop_id"]}, {"_id": 0}).to_list(500)

@api.post("/holidays")
async def hol_new(p: HolidayIn, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    hid = f"hol_{uuid.uuid4().hex[:10]}"
    await db.holidays.insert_one({"holiday_id": hid, "shop_id": s["shop_id"], **p.model_dump()})
    return await db.holidays.find_one({"holiday_id": hid}, {"_id": 0})

@api.delete("/holidays/{hid}")
async def hol_del(hid: str, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    await db.holidays.delete_one({"holiday_id": hid, "shop_id": s["shop_id"]})
    return {"ok": True}


@api.get("/fixed-shifts")
async def fs_list(u=Depends(get_current_user)):
    s = await ensure_shop(u)
    return await db.fixed_shifts.find({"shop_id": s["shop_id"]}, {"_id": 0}).to_list(500)

@api.post("/fixed-shifts")
async def fs_new(p: FixedShiftIn, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    fid = f"fs_{uuid.uuid4().hex[:10]}"
    await db.fixed_shifts.insert_one({"fixed_id": fid, "shop_id": s["shop_id"], **p.model_dump()})
    return await db.fixed_shifts.find_one({"fixed_id": fid}, {"_id": 0})

@api.delete("/fixed-shifts/{fid}")
async def fs_del(fid: str, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    await db.fixed_shifts.delete_one({"fixed_id": fid, "shop_id": s["shop_id"]})
    return {"ok": True}


@api.get("/ai-rules")
async def rules_list(u=Depends(get_current_user)):
    s = await ensure_shop(u)
    return await db.ai_rules.find({"shop_id": s["shop_id"]}, {"_id": 0}).to_list(500)

@api.post("/ai-rules")
async def rules_new(p: AIRuleIn, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    rid = f"rule_{uuid.uuid4().hex[:10]}"
    await db.ai_rules.insert_one({"rule_id": rid, "shop_id": s["shop_id"], **p.model_dump()})
    return await db.ai_rules.find_one({"rule_id": rid}, {"_id": 0})

@api.put("/ai-rules/{rid}")
async def rules_upd(rid: str, p: AIRuleIn, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    await db.ai_rules.update_one({"rule_id": rid, "shop_id": s["shop_id"]}, {"$set": p.model_dump()})
    return await db.ai_rules.find_one({"rule_id": rid}, {"_id": 0})

@api.delete("/ai-rules/{rid}")
async def rules_del(rid: str, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    await db.ai_rules.delete_one({"rule_id": rid, "shop_id": s["shop_id"]})
    return {"ok": True}


DAYS = ["mon","tue","wed","thu","fri","sat","sun"]
def hm(s): h,m = s.split(":"); return int(h)*60+int(m)
def mh(m): return f"{m//60:02d}:{m%60:02d}"
def shift_duration_min(start: str, end: str) -> int:
    """Handles overnight shifts (23:00-07:00 = 8h)."""
    s, e = hm(start), hm(end)
    return e - s if e > s else (24*60 - s) + e


async def solve_roster(shop, employees, holidays, fixed_shifts, ai_rules, week_start, weights):
    shop_hours = {h["day"]: h for h in shop["hours"]}
    min_shift = shop["min_shift_hours"] * 60
    max_shift = min(shop["max_shift_hours"], 11) * 60  # hard cap 11h
    def _range(h):
        s = datetime.strptime(h["date"], "%Y-%m-%d").date()
        e = datetime.strptime(h.get("end_date") or h["date"], "%Y-%m-%d").date()
        out = set()
        while s <= e:
            out.add(s.isoformat())
            s += timedelta(days=1)
        return out
    shop_off = set()
    emp_off = {}
    for h in holidays:
        rng = _range(h)
        if h["scope"] == "shop":
            shop_off |= rng
        elif h["scope"] in ("employee", "sick") and h.get("employee_id"):
            emp_off.setdefault(h["employee_id"], set()).update(rng)
    ws = datetime.strptime(week_start, "%Y-%m-%d").date()
    day_dates = {DAYS[i]: (ws + timedelta(days=i)).isoformat() for i in range(7)}
    fixed_map = {}
    for f in fixed_shifts:
        for d in f["days"]:
            fixed_map.setdefault(f["employee_id"], {})[d] = (f["start"], f["end"])
    shifts, issues = [], []
    emp_hours = {e["employee_id"]: 0.0 for e in employees}
    # Load compiled custom-rule constraints for hard enforcement
    constraints = [r.get("compiled") for r in ai_rules if r.get("compiled") and r.get("approved", True)]
    def _violates(emp_id, day, start_m, end_m, open_m_local, close_m_local):
        for c in constraints:
            eids = c.get("employee_ids") or []
            if eids and emp_id not in eids: continue
            days = [d.lower()[:3] for d in (c.get("days") or [])]
            if days and day not in days: continue
            t = (c.get("type") or "").lower()
            if t == "no_day": return c
            if t == "no_close" and end_m >= close_m_local - 30: return c
            if t == "no_open" and start_m <= open_m_local + 30: return c
        return None
    role_priority = {r: i for i, r in enumerate(["Manager","Supervisor","Cashier","Floor Assistant","Stocker"])}

    for d in DAYS:
        the_date = day_dates[d]
        if the_date in shop_off: continue
        sh = shop_hours.get(d, {})
        if sh.get("closed"): continue
        open_m, close_m = hm(sh["open"]), hm(sh["close"])
        if close_m - open_m <= 0: continue
        target_len = min(max(close_m - open_m, int(min_shift)), int(max_shift))
        already_ids = {s["employee_id"] for s in shifts if s["day"] == d}
        def _score(e):
            base = -weights.get("day", {}).get(e["employee_id"], {}).get(d, 0)
            cw = weights.get("coworkers", {}).get(e["employee_id"], {})
            affinity = -sum(cw.get(x, 0) for x in already_ids)
            return (role_priority.get(e["role"], 99), base + affinity * 0.5)
        candidates = sorted(employees, key=_score)
        assigned_today = set()

        for emp in candidates:
            fs = fixed_map.get(emp["employee_id"], {}).get(d)
            if fs:
                if the_date in emp_off.get(emp["employee_id"], set()):
                    issues.append(f"{emp['name']} has fixed shift on {d} but is on holiday.")
                    continue
                s_m, e_m = hm(fs[0]), hm(fs[1])
                length_h = (e_m - s_m) / 60
                if emp_hours[emp["employee_id"]] + length_h > emp["max_weekly_hours"]:
                    issues.append(f"{emp['name']} fixed shift exceeds max weekly hours.")
                    continue
                if emp["age"] < 16 and (s_m < hm("08:00") or e_m > hm("19:00")):
                    issues.append(f"{emp['name']} (under 16) fixed shift violates curfew.")
                shifts.append({"shift_id": f"sh_{uuid.uuid4().hex[:8]}", "employee_id": emp["employee_id"], "day": d, "start": fs[0], "end": fs[1], "fixed": True})
                emp_hours[emp["employee_id"]] += length_h
                assigned_today.add(emp["employee_id"])

        has_mgr = any(any(s["employee_id"] == emp["employee_id"] and s["day"] == d for s in shifts) for emp in employees if emp["role"] in ("Manager","Supervisor"))
        needed = max(2, len([e for e in employees if e["role"] in ("Cashier","Floor Assistant")]) // 3 + 1)

        for emp in candidates:
            if len([s for s in shifts if s["day"] == d]) >= needed and has_mgr: break
            if emp["employee_id"] in assigned_today: continue
            if the_date in emp_off.get(emp["employee_id"], set()): continue
            if d in (emp.get("preferred_days_off") or []): continue
            s_m, e_m = open_m, min(open_m + target_len, close_m)
            length_h = (e_m - s_m) / 60
            if length_h < shop["min_shift_hours"]: continue
            if emp_hours[emp["employee_id"]] + length_h > emp["max_weekly_hours"]:
                e_m = s_m + int(shop["min_shift_hours"] * 60)
                length_h = (e_m - s_m) / 60
                if emp_hours[emp["employee_id"]] + length_h > emp["max_weekly_hours"]: continue
            if emp["age"] < 16:
                if e_m > hm("19:00"): e_m = min(e_m, hm("19:00"))
                if s_m < hm("08:00"): s_m = hm("08:00")
                length_h = (e_m - s_m) / 60
                if length_h < shop["min_shift_hours"]: continue
            if _violates(emp["employee_id"], d, s_m, e_m, open_m, close_m):
                issues.append(f"{emp['name']} skipped on {d} due to custom rule.")
                continue
            shifts.append({"shift_id": f"sh_{uuid.uuid4().hex[:8]}", "employee_id": emp["employee_id"], "day": d, "start": mh(s_m), "end": mh(e_m), "fixed": False})
            emp_hours[emp["employee_id"]] += length_h
            assigned_today.add(emp["employee_id"])
            if emp["role"] in ("Manager","Supervisor"): has_mgr = True

        if not any(s["day"] == d for s in shifts):
            issues.append(f"No coverage assigned for {d}.")
        elif not has_mgr:
            issues.append(f"No manager/supervisor coverage on {d}.")

    score = max(0, 100 - len(issues) * 8)
    emp_rate = {e["employee_id"]: e["hourly_rate"] for e in employees}
    labor_cost = sum(((hm(s["end"]) - hm(s["start"])) / 60) * emp_rate.get(s["employee_id"], 0) for s in shifts)
    total_hours = sum(emp_hours.values())
    max_possible = sum(e["max_weekly_hours"] for e in employees) or 1
    return {"shifts": shifts, "issues": issues, "compliance_score": score,
            "labor_cost": round(labor_cost, 2), "total_hours": round(total_hours, 1),
            "utilization": round((total_hours / max_possible) * 100, 1),
            "per_employee_hours": {k: round(v, 1) for k, v in emp_hours.items()}}


async def compute_weights(sid):
    """AI learning: per-employee day preference + co-worker affinity from APPROVED rosters."""
    w = {}
    coworkers = {}
    async for r in db.rosters.find({"shop_id": sid, "approved": True}, {"_id": 0}):
        # skip anything explicitly excluded from learning
        if r.get("exclude_from_ai"): continue
        by_day = {}
        for s in r.get("shifts", []):
            if s.get("sick") or s.get("temp_override"): continue  # never learn from sick leave / temp overrides
            w.setdefault(s["employee_id"], {}).setdefault(s["day"], 0)
            w[s["employee_id"]][s["day"]] += 1
            by_day.setdefault(s["day"], []).append(s["employee_id"])
        for day, ids in by_day.items():
            for i in ids:
                for j in ids:
                    if i != j:
                        coworkers.setdefault(i, {}).setdefault(j, 0)
                        coworkers[i][j] += 1
    return {"day": w, "coworkers": coworkers}


@api.post("/roster/generate")
async def gen_roster(p: RosterGenReq, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    # Free plan gating: DISABLED in dev
    # if not u.get("pro", False):
    #     count = await db.rosters.count_documents({"shop_id": s["shop_id"]})
    #     if count >= 4:
    #         raise HTTPException(402, "Free plan limit reached (4 rosters). Upgrade to Pro to generate more.")
    emps = await db.employees.find({"shop_id": s["shop_id"]}, {"_id": 0}).to_list(500)
    if p.department:
        emps = [e for e in emps if p.department in (e.get("departments") or ["Shop Floor"])]
    if not emps: raise HTTPException(400, "Add employees first" if not p.department else f"No employees in {p.department}")
    hols = await db.holidays.find({"shop_id": s["shop_id"]}, {"_id": 0}).to_list(500)
    fx = await db.fixed_shifts.find({"shop_id": s["shop_id"]}, {"_id": 0}).to_list(500)
    emp_ids = {e["employee_id"] for e in emps}
    fx = [f for f in fx if f["employee_id"] in emp_ids]
    rules = await db.ai_rules.find({"shop_id": s["shop_id"], "enabled": True}, {"_id": 0}).to_list(500)
    weights = await compute_weights(s["shop_id"])
    result = await solve_roster(s, emps, hols, fx, rules, p.week_start, weights)

    ai_summary = None
    try:
        chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"roster-{uuid.uuid4().hex[:8]}",
                       system_message="You are an expert retail workforce planner. Reply in 2 short sentences.").with_model("anthropic", "claude-sonnet-4-5-20250929")
        prompt = f"Weekly roster: week {p.week_start}. {len(result['shifts'])} shifts. Compliance {result['compliance_score']}. Cost ${result['labor_cost']}. Issues: {result['issues'][:3]}. Give a concise assessment + one optimization tip."
        ai_summary = str(await chat.send_message(UserMessage(text=prompt)))
    except Exception as e:
        log.warning(f"AI summary skipped: {e}")

    latest = await db.rosters.find_one({"shop_id": s["shop_id"], "week_start": p.week_start}, sort=[("created_at", -1)], projection={"_id": 0})
    version = "v1.0"
    if latest:
        try:
            mj, mn = latest["version"].replace("v", "").split(".")
            version = f"v{mj}.{int(mn)+1}"
        except Exception: version = "v1.1"
    rid = f"rst_{uuid.uuid4().hex[:12]}"
    doc = {"roster_id": rid, "shop_id": s["shop_id"], "week_start": p.week_start, "version": version,
           **result, "ai_summary": ai_summary, "approved": False, "department": p.department,
           "created_at": datetime.now(timezone.utc).isoformat()}
    await db.rosters.insert_one(doc.copy())
    await db.activity_logs.insert_one({"log_id": f"log_{uuid.uuid4().hex[:10]}", "shop_id": s["shop_id"],
        "action": "roster_generated", "detail": f"Generated {version} for week {p.week_start}",
        "created_at": datetime.now(timezone.utc).isoformat()})
    return doc


@api.get("/rosters")
async def r_list(u=Depends(get_current_user)):
    s = await ensure_shop(u)
    return await db.rosters.find({"shop_id": s["shop_id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)


@api.get("/rosters/past")
async def past_rosters(u=Depends(get_current_user)):
    s = await ensure_shop(u)
    today = datetime.now(timezone.utc).date().isoformat()
    return await db.rosters.find({"shop_id": s["shop_id"], "week_start": {"$lt": today}}, {"_id": 0}).sort("week_start", -1).to_list(200)


@api.post("/rosters/upload-historical")
async def upload_hist(request: Request, u=Depends(get_current_user)):
    """Accept previously-approved historical roster JSON. Trusted training data."""
    s = await ensure_shop(u)
    payload = await request.json()
    if not payload: raise HTTPException(400, "Empty payload")
    rosters_in = payload if isinstance(payload, list) else [payload]
    created = []
    for p in rosters_in:
        shifts = p.get("shifts", [])
        week_start = p.get("week_start")
        if not week_start or not shifts: continue
        doc = {"roster_id": f"hist_{uuid.uuid4().hex[:12]}", "shop_id": s["shop_id"], "week_start": week_start,
               "version": "v1.0-hist", "shifts": shifts, "issues": [], "compliance_score": 100,
               "labor_cost": 0, "total_hours": sum((hm(x["end"])-hm(x["start"]))/60 for x in shifts if x.get("start") and x.get("end")),
               "utilization": 0, "per_employee_hours": {}, "approved": True, "historical": True,
               "created_at": datetime.now(timezone.utc).isoformat()}
        await db.rosters.insert_one(doc.copy())
        created.append(doc["roster_id"])
    # AI training stats
    total_shifts = sum(len(r.get("shifts", [])) for r in rosters_in)
    employees_learned = len({s["employee_id"] for r in rosters_in for s in r.get("shifts", []) if s.get("employee_id")})
    return {"ok": True, "imported": len(created), "weeks": len(created), "total_shifts": total_shifts,
            "employees_learned": employees_learned, "roster_ids": created}


@api.post("/rosters/ocr")
async def ocr_roster(request: Request, u=Depends(get_current_user)):
    """Extract roster data from an image URL using Claude vision."""
    body = await request.json()
    image_url = body.get("image_url")
    if not image_url: raise HTTPException(400, "image_url required")
    s = await ensure_shop(u)
    emps = await db.employees.find({"shop_id": s["shop_id"]}, {"_id": 0}).to_list(500)
    emp_names = [e["name"] for e in emps]
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
    import base64
    async with httpx.AsyncClient(timeout=30) as h:
        img_resp = await h.get(image_url)
        img_resp.raise_for_status()
    image_b64 = base64.b64encode(img_resp.content).decode()
    system = ("You extract weekly retail rosters from images. Return STRICT JSON only, no prose. "
              "Schema: {\"week_start\":\"YYYY-MM-DD (Monday)\",\"shifts\":[{\"employee_name\":\"...\",\"day\":\"mon|tue|wed|thu|fri|sat|sun\",\"start\":\"HH:MM\",\"end\":\"HH:MM\",\"role\":\"...\",\"note\":\"holiday|sick|off|\"}]}. "
              f"Known employees at this shop: {emp_names}. Use exact names when matched, else use as-shown.")
    try:
        chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"ocr-{uuid.uuid4().hex[:8]}", system_message=system).with_model("anthropic", "claude-sonnet-4-5-20250929")
        msg = UserMessage(text="Extract the roster in strict JSON per schema.", file_contents=[ImageContent(image_base64=image_b64)])
        raw = await chat.send_message(msg)
    except Exception as e:
        raise HTTPException(500, f"OCR failed: {e}")
    text = raw if isinstance(raw, str) else str(raw)
    # Try to isolate JSON
    import json as _json, re as _re
    m = _re.search(r"\{[\s\S]*\}", text)
    if not m: raise HTTPException(500, f"Could not parse JSON from OCR: {text[:200]}")
    try:
        parsed = _json.loads(m.group(0))
    except Exception as e:
        raise HTTPException(500, f"JSON parse error: {e}")
    # Map employee names to IDs
    name_to_id = {e["name"].lower(): e["employee_id"] for e in emps}
    valid = []
    for sh in parsed.get("shifts", []):
        eid = name_to_id.get((sh.get("employee_name") or "").lower())
        if not eid: continue  # skip unknown employees; UI review will offer to create
        note = (sh.get("note") or "").lower()
        if note in ("holiday", "sick", "off", "hol", "leave"): continue
        if not sh.get("start") or not sh.get("end") or not sh.get("day"): continue
        valid.append({"employee_id": eid, "employee_name": sh.get("employee_name"),
                       "day": sh["day"], "start": sh["start"], "end": sh["end"]})
    return {"week_start": parsed.get("week_start"), "shifts": valid, "raw_shifts": parsed.get("shifts", [])}


@api.get("/rosters/{rid}")
async def r_get(rid: str, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    r = await db.rosters.find_one({"roster_id": rid, "shop_id": s["shop_id"]}, {"_id": 0})
    if not r: raise HTTPException(404, "Not found")
    return r

@api.put("/rosters/{rid}")
async def r_upd(rid: str, p: RosterUpdate, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    emps = await db.employees.find({"shop_id": s["shop_id"]}, {"_id": 0}).to_list(500)
    er = {e["employee_id"]: e["hourly_rate"] for e in emps}
    shifts = [{"shift_id": f"sh_{uuid.uuid4().hex[:8]}", **sh.model_dump(), "fixed": False} for sh in p.shifts]
    for sh in shifts:
        dur = shift_duration_min(sh["start"], sh["end"]) / 60
        if dur <= 0: raise HTTPException(400, f"Invalid shift ({sh['start']}-{sh['end']})")
        if dur > 11: raise HTTPException(400, f"Shift exceeds 11h limit ({sh['start']}-{sh['end']} = {dur}h)")
    seen = set()
    for sh in shifts:
        k = (sh["employee_id"], sh["day"])
        if k in seen: raise HTTPException(400, f"Duplicate shift for employee on {sh['day']}")
        seen.add(k)
    lc = sum((shift_duration_min(sh["start"], sh["end"]) / 60) * er.get(sh["employee_id"], 0)
             for sh in shifts if not sh.get("unpaid_holiday"))
    th = sum(shift_duration_min(sh["start"], sh["end"]) / 60 for sh in shifts
             if not sh.get("unpaid_holiday") and not sh.get("sick") and not sh.get("paid_holiday"))
    await db.rosters.update_one({"roster_id": rid, "shop_id": s["shop_id"]}, {"$set": {"shifts": shifts, "labor_cost": round(lc, 2), "total_hours": round(th, 1)}})
    return await db.rosters.find_one({"roster_id": rid, "shop_id": s["shop_id"]}, {"_id": 0})

@api.post("/rosters/{rid}/approve")
async def r_approve(rid: str, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    r = await db.rosters.find_one({"roster_id": rid, "shop_id": s["shop_id"]}, {"_id": 0})
    if not r: raise HTTPException(404, "Not found")
    await db.rosters.delete_many({"shop_id": s["shop_id"], "week_start": r["week_start"],
                                    "department": r.get("department"), "roster_id": {"$ne": rid}})
    await db.rosters.update_one({"roster_id": rid, "shop_id": s["shop_id"]}, {"$set": {"approved": True, "version": "v1.0"}})
    await db.activity_logs.insert_one({"log_id": f"log_{uuid.uuid4().hex[:10]}", "shop_id": s["shop_id"],
        "action": "roster_approved", "detail": f"Approved & pruned prior versions for week {r['week_start']}",
        "created_at": datetime.now(timezone.utc).isoformat()})
    return {"ok": True}


def email_html(name, shop_name, ws, shifts, ver):
    labels = {"mon":"Mon","tue":"Tue","wed":"Wed","thu":"Thu","fri":"Fri","sat":"Sat","sun":"Sun"}
    rows = "".join(f'<tr><td style="padding:8px 12px;color:#a1a1aa;font-family:monospace;">{labels.get(s["day"], s["day"])}</td><td style="padding:8px 12px;color:#fff;font-family:monospace;">{s["start"]} – {s["end"]}</td></tr>' for s in shifts)
    if not rows: rows = '<tr><td colspan="2" style="padding:12px;color:#a1a1aa;">No shifts scheduled this week.</td></tr>'
    return f"""<div style="background:#05050A;padding:32px;font-family:Arial,sans-serif;color:#fff;"><table width="100%" style="max-width:560px;margin:auto;background:#0A0B10;border:1px solid rgba(255,255,255,0.08);border-radius:16px;overflow:hidden;"><tr><td style="padding:24px 24px 8px 24px;"><div style="color:#00E5FF;font-size:22px;font-weight:700;">{shop_name}</div><div style="color:#a1a1aa;font-size:13px;margin-top:4px;">Roster {ver} · week of {ws}</div></td></tr><tr><td style="padding:16px 24px;color:#fff;"><p>Hi {name},</p><p>Your shifts for the upcoming week are below.</p></td></tr><tr><td style="padding:0 24px 24px 24px;"><table width="100%" style="background:#05050A;border-radius:12px;border:1px solid rgba(255,255,255,0.08);">{rows}</table></td></tr><tr><td style="padding:0 24px 24px 24px;color:#71717A;font-size:12px;">Sent via Roster AI</td></tr></table></div>"""


@api.post("/roster/{rid}/dispatch")
async def dispatch(rid: str, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    r = await db.rosters.find_one({"roster_id": rid, "shop_id": s["shop_id"]}, {"_id": 0})
    if not r: raise HTTPException(404, "Not found")
    emps = await db.employees.find({"shop_id": s["shop_id"]}, {"_id": 0}).to_list(500)
    sent, failed = [], []
    for e in emps:
        emp_shifts = [sh for sh in r["shifts"] if sh["employee_id"] == e["employee_id"]]
        html = email_html(e["name"], s["name"], r["week_start"], emp_shifts, r["version"])
        payload = {"to": [e["email"]], "subject": f"Your schedule · {s['name']} · week of {r['week_start']}", "html": html, "from_name": EMAIL_FROM_NAME}
        try:
            async with httpx.AsyncClient(timeout=30) as h:
                resp = await h.post(f"{EMAIL_BASE_URL}/api/v1/email/send", headers={"X-Email-Key": EMERGENT_EMAIL_KEY}, json=payload)
                resp.raise_for_status()
                sent.append({"employee_id": e["employee_id"], "email": e["email"], "name": e["name"]})
        except Exception as ex:
            log.error(f"Email failed for {e['email']}: {ex}")
            failed.append({"employee_id": e["employee_id"], "email": e["email"], "name": e["name"], "error": str(ex)[:100]})
        await db.activity_logs.insert_one({"log_id": f"log_{uuid.uuid4().hex[:10]}", "shop_id": s["shop_id"],
            "action": "email_sent" if e["employee_id"] in [x["employee_id"] for x in sent] else "email_failed",
            "detail": f"Dispatch to {e['name']} <{e['email']}> for {r['version']}",
            "created_at": datetime.now(timezone.utc).isoformat()})
    await db.rosters.update_one({"roster_id": rid}, {"$set": {"dispatched_at": datetime.now(timezone.utc).isoformat()}})
    return {"sent": sent, "failed": failed, "total": len(sent) + len(failed)}


@api.get("/activity")
async def act_list(u=Depends(get_current_user)):
    s = await ensure_shop(u)
    return await db.activity_logs.find({"shop_id": s["shop_id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)


@api.post("/ai-rules/{rid}/compile")
async def compile_rule(rid: str, u=Depends(get_current_user)):
    """Use Claude to transform a free-text rule into a structured constraint."""
    s = await ensure_shop(u)
    rule = await db.ai_rules.find_one({"rule_id": rid, "shop_id": s["shop_id"]}, {"_id": 0})
    if not rule: raise HTTPException(404, "Rule not found")
    emps = await db.employees.find({"shop_id": s["shop_id"]}, {"_id": 0}).to_list(500)
    system = ("You convert scheduling rules into JSON constraints. Reply with STRICT JSON only. "
              "Schema: {\"type\":\"no_close|no_open|no_day|max_hours|min_rest|required_together|role_required_day|other\","
              "\"employee_ids\":[...],\"days\":[\"mon\"..\"sun\"],\"role\":\"...\",\"value\":number,\"description\":\"...\"}. "
              f"Known employees: {[{'id':e['employee_id'],'name':e['name'],'role':e['role']} for e in emps]}")
    try:
        chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"rule-{uuid.uuid4().hex[:8]}",
                       system_message=system).with_model("anthropic", "claude-sonnet-4-5-20250929")
        raw = str(await chat.send_message(UserMessage(text=f"Rule: {rule['title']} — {rule['description']}")))
    except Exception as e:
        raise HTTPException(500, f"Compilation failed: {e}")
    import json as _json, re as _re
    m = _re.search(r"\{[\s\S]*\}", raw)
    if not m: raise HTTPException(500, "Could not parse constraint JSON")
    try:
        compiled = _json.loads(m.group(0))
    except Exception as e:
        raise HTTPException(500, f"JSON parse error: {e}")
    await db.ai_rules.update_one({"rule_id": rid, "shop_id": s["shop_id"]}, {"$set": {"compiled": compiled}})
    return {"compiled": compiled}


@api.get("/reports/sick-leave")
async def sick_report(u=Depends(get_current_user)):
    """Sick leave report — for HR only, never used for AI training."""
    s = await ensure_shop(u)
    hols = await db.holidays.find({"shop_id": s["shop_id"], "scope": "sick"}, {"_id": 0}).to_list(500)
    emps = {e["employee_id"]: e for e in await db.employees.find({"shop_id": s["shop_id"]}, {"_id": 0}).to_list(500)}
    by_emp = {}
    for h in hols:
        eid = h.get("employee_id")
        if not eid: continue
        entry = by_emp.setdefault(eid, {"employee_id": eid, "name": emps.get(eid, {}).get("name", "Unknown"), "role": emps.get(eid, {}).get("role", ""), "avatar": emps.get(eid, {}).get("avatar"), "days": 0, "occurrences": []})
        s_ = datetime.strptime(h["date"], "%Y-%m-%d").date()
        e_ = datetime.strptime(h.get("end_date") or h["date"], "%Y-%m-%d").date()
        days = (e_ - s_).days + 1
        entry["days"] += days
        entry["occurrences"].append({"start": h["date"], "end": h.get("end_date") or h["date"], "days": days, "label": h.get("label")})
    return {"by_employee": list(by_emp.values()), "total_days": sum(x["days"] for x in by_emp.values()),
            "total_incidents": sum(len(x["occurrences"]) for x in by_emp.values())}


@api.get("/ai/training-stats")
async def ai_stats(u=Depends(get_current_user)):
    s = await ensure_shop(u)
    approved = await db.rosters.count_documents({"shop_id": s["shop_id"], "approved": True})
    historical = await db.rosters.count_documents({"shop_id": s["shop_id"], "historical": True})
    total_shifts = 0
    emp_set = set()
    async for r in db.rosters.find({"shop_id": s["shop_id"], "approved": True}, {"_id": 0}):
        for sh in r.get("shifts", []):
            if sh.get("sick") or sh.get("temp_override"): continue
            total_shifts += 1
            emp_set.add(sh["employee_id"])
    return {"approved_rosters": approved, "historical_rosters": historical,
            "total_shifts_learned": total_shifts, "employees_learned": len(emp_set)}


@api.post("/seed-demo")
async def seed_demo(u=Depends(get_current_user)):
    s = await ensure_shop(u)
    await db.employees.delete_many({"shop_id": s["shop_id"], "demo": True})
    demo = [
        {"name":"Aisha Rahman","email":"aisha@demo.co","role":"Manager","age":34,"hourly_rate":28.0,"max_weekly_hours":40,"preferred_days_off":["sun"],"demo":True},
        {"name":"Marcus Chen","email":"marcus@demo.co","role":"Supervisor","age":28,"hourly_rate":22.0,"max_weekly_hours":40,"preferred_days_off":["mon"],"demo":True},
        {"name":"Priya Nair","email":"priya@demo.co","role":"Cashier","age":22,"hourly_rate":16.0,"max_weekly_hours":40,"preferred_days_off":["tue"],"demo":True},
        {"name":"Jordan Lee","email":"jordan@demo.co","role":"Cashier","age":19,"hourly_rate":15.5,"max_weekly_hours":20,"preferred_days_off":["wed"],"demo":True},
        {"name":"Sofia Diaz","email":"sofia@demo.co","role":"Floor Assistant","age":17,"hourly_rate":14.0,"max_weekly_hours":20,"preferred_days_off":["thu"],"demo":True},
        {"name":"Ethan Park","email":"ethan@demo.co","role":"Stocker","age":24,"hourly_rate":15.0,"max_weekly_hours":40,"preferred_days_off":["fri"],"demo":True},
        {"name":"Lena Volkov","email":"lena@demo.co","role":"Floor Assistant","age":15,"hourly_rate":12.5,"max_weekly_hours":20,"preferred_days_off":["sat"],"demo":True},
    ]
    for i, e in enumerate(demo):
        await db.employees.insert_one({"employee_id": f"emp_{uuid.uuid4().hex[:12]}", "shop_id": s["shop_id"], "avatar": AVATARS[i % len(AVATARS)], **e})
    return {"ok": True, "count": len(demo)}


class CheckoutRequest(BaseModel):
    lookup_key: str
    quantity: int = Field(1, ge=1, le=100)
    origin_url: str


@api.post("/payments/checkout")
async def create_checkout(req: CheckoutRequest, u=Depends(get_current_user)):
    prices = stripe.Price.list(lookup_keys=[req.lookup_key], active=True, limit=1).data
    if not prices:
        raise HTTPException(500, f"Price not found: {req.lookup_key}")
    price = prices[0]
    kwargs = dict(
        line_items=[{"price": price.id, "quantity": req.quantity}],
        mode="subscription" if price.recurring else "payment",
        success_url=f"{req.origin_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{req.origin_url}/payment/cancel",
        metadata={"user_id": u["user_id"], "lookup_key": req.lookup_key},
    )
    try:
        session = stripe.checkout.Session.create(**kwargs, managed_payments={"enabled": True})
    except stripe.error.InvalidRequestError as e:
        msg = (e.user_message or "").lower()
        if "managed payments" in msg or "ineligible" in msg:
            session = stripe.checkout.Session.create(**kwargs, automatic_tax={"enabled": True}, billing_address_collection="required")
        else:
            raise
    await db.payment_transactions.insert_one({
        "session_id": session.id, "user_id": u["user_id"], "lookup_key": req.lookup_key,
        "amount": (price.unit_amount or 0) * req.quantity, "currency": price.currency,
        "status": "initiated", "payment_status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"checkout_url": session.url, "session_id": session.id}


@api.get("/payments/status/{session_id}")
async def get_status(session_id: str):
    record = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not record: raise HTTPException(404, "Not found")
    if record.get("payment_status") != "paid":
        try:
            s = stripe.checkout.Session.retrieve(session_id)
            if s.payment_status == "paid" or s.status == "complete":
                await db.payment_transactions.update_one(
                    {"session_id": session_id, "payment_status": {"$ne": "paid"}},
                    {"$set": {"status": "completed", "payment_status": "paid",
                              "stripe_subscription_id": s.subscription,
                              "stripe_payment_intent_id": s.payment_intent,
                              "updated_at": datetime.now(timezone.utc).isoformat()}},
                )
                # unlock pro on user
                if record.get("user_id"):
                    await db.users.update_one({"user_id": record["user_id"]}, {"$set": {"pro": True, "pro_since": datetime.now(timezone.utc).isoformat()}})
                record = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
        except stripe.error.StripeError:
            pass
    return {"session_id": record["session_id"], "status": record["status"], "payment_status": record["payment_status"]}


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid signature")
    obj, t = event["data"]["object"], event["type"]
    if t == "checkout.session.completed":
        res = await db.payment_transactions.update_one(
            {"session_id": obj["id"], "payment_status": {"$ne": "paid"}},
            {"$set": {"status": "completed", "payment_status": obj.get("payment_status", "paid"),
                      "stripe_subscription_id": obj.get("subscription"),
                      "stripe_payment_intent_id": obj.get("payment_intent"),
                      "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
        if res.modified_count:
            rec = await db.payment_transactions.find_one({"session_id": obj["id"]}, {"_id": 0})
            if rec and rec.get("user_id"):
                await db.users.update_one({"user_id": rec["user_id"]}, {"$set": {"pro": True, "pro_since": datetime.now(timezone.utc).isoformat()}})
    elif t == "checkout.session.async_payment_succeeded":
        await db.payment_transactions.update_one({"session_id": obj["id"]}, {"$set": {"payment_status": "paid", "updated_at": datetime.now(timezone.utc).isoformat()}})
    elif t == "checkout.session.async_payment_failed":
        await db.payment_transactions.update_one({"session_id": obj["id"]}, {"$set": {"status": "failed", "payment_status": "failed", "updated_at": datetime.now(timezone.utc).isoformat()}})
    elif t == "checkout.session.expired":
        await db.payment_transactions.update_one({"session_id": obj["id"]}, {"$set": {"status": "expired", "payment_status": "expired", "updated_at": datetime.now(timezone.utc).isoformat()}})
    return {"status": "ok"}


@api.post("/rosters/ocr-batch")
async def ocr_batch(request: Request, u=Depends(get_current_user)):
    """Batch OCR across multiple image URLs. Returns merged shifts + raw."""
    body = await request.json()
    urls = body.get("image_urls") or []
    if not urls: raise HTTPException(400, "image_urls required")
    all_valid, all_raw = [], []
    weeks = []
    for url in urls:
        try:
            body_single = {"image_url": url}
            request._body = _json_bytes(body_single)  # not portable; call function directly
        except Exception:
            pass
    # simplest: iterate and call ocr_roster inline
    for url in urls:
        try:
            async def _call():
                from fastapi import Request as R
                class _Req:
                    async def json(self): return {"image_url": url}
                resp = await ocr_roster(_Req(), u)
                return resp
            data = await _call()
            all_valid.extend(data.get("shifts", []))
            all_raw.extend([{**r, "_source_url": url} for r in data.get("raw_shifts", [])])
            if data.get("week_start"): weeks.append(data["week_start"])
        except Exception as e:
            log.warning(f"OCR failed for {url}: {e}")
    return {"weeks": weeks, "shifts": all_valid, "raw_shifts": all_raw, "processed": len(urls)}


def _json_bytes(d):
    import json as _j
    return _j.dumps(d).encode()


@api.post("/dev/reset")
async def reset_all(u=Depends(get_current_user)):
    """Wipe all data for the current user's shop — dev reset."""
    s = await ensure_shop(u)
    sid = s["shop_id"]
    await db.employees.delete_many({"shop_id": sid})
    await db.holidays.delete_many({"shop_id": sid})
    await db.fixed_shifts.delete_many({"shop_id": sid})
    await db.rosters.delete_many({"shop_id": sid})
    await db.activity_logs.delete_many({"shop_id": sid})
    await db.ai_rules.delete_many({"shop_id": sid})
    # Re-seed just the default AI rules (constraints, not data)
    for r in DEFAULT_AI_RULES:
        await db.ai_rules.insert_one({"rule_id": f"rule_{uuid.uuid4().hex[:12]}", "shop_id": sid, **r})
    # Reset onboarding
    await db.shops.update_one({"shop_id": sid}, {"$set": {"onboarded": False}})
    return {"ok": True, "message": "All data reset. Shop is now empty."}


@api.post("/ai-rules/{rid}/approve-compiled")
async def approve_rule(rid: str, u=Depends(get_current_user)):
    s = await ensure_shop(u)
    r = await db.ai_rules.find_one({"rule_id": rid, "shop_id": s["shop_id"]}, {"_id": 0})
    if not r or not r.get("compiled"): raise HTTPException(400, "Rule not compiled yet")
    await db.ai_rules.update_one({"rule_id": rid, "shop_id": s["shop_id"]}, {"$set": {"approved": True}})
    return {"ok": True}


@api.get("/employees/{eid}/holiday-balance")
async def emp_balance(eid: str, u=Depends(get_current_user)):
    """Holiday accrual: 8h per 100h worked (0.08 ratio). Only counts approved roster hours."""
    s = await ensure_shop(u)
    total_worked = 0.0
    paid_holiday_used = 0.0
    async for r in db.rosters.find({"shop_id": s["shop_id"], "approved": True}, {"_id": 0}):
        for sh in r.get("shifts", []):
            if sh.get("employee_id") != eid: continue
            if sh.get("sick") or sh.get("unpaid_holiday"): continue
            dur = shift_duration_min(sh["start"], sh["end"]) / 60
            if sh.get("paid_holiday"):
                paid_holiday_used += dur
            else:
                total_worked += dur
    accrued = round(total_worked * 0.08, 2)
    balance = round(accrued - paid_holiday_used, 2)
    return {"employee_id": eid, "hours_worked": round(total_worked, 1),
            "accrued_holiday_hours": accrued, "used_paid_holiday": round(paid_holiday_used, 1),
            "balance": balance}


@api.get("/employees/holiday-balances")
async def all_balances(u=Depends(get_current_user)):
    s = await ensure_shop(u)
    emps = await db.employees.find({"shop_id": s["shop_id"]}, {"_id": 0}).to_list(500)
    out = []
    for e in emps:
        worked = 0.0; used = 0.0
        async for r in db.rosters.find({"shop_id": s["shop_id"], "approved": True}, {"_id": 0}):
            for sh in r.get("shifts", []):
                if sh.get("employee_id") != e["employee_id"]: continue
                if sh.get("sick") or sh.get("unpaid_holiday"): continue
                dur = shift_duration_min(sh["start"], sh["end"]) / 60
                if sh.get("paid_holiday"): used += dur
                else: worked += dur
        out.append({"employee_id": e["employee_id"], "name": e["name"], "role": e.get("role"),
                    "hours_worked": round(worked, 1), "accrued": round(worked * 0.08, 2),
                    "used": round(used, 1), "balance": round(worked * 0.08 - used, 2)})
    return out


@api.get("/")
async def root(): return {"message": "Roster AI"}


app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True,
                   allow_origins=os.environ.get('CORS_ORIGINS','*').split(','),
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    ex = await db.users.find_one({"email": OWNER_EMAIL.lower()}, {"_id": 0})
    if not ex:
        uid = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({"user_id": uid, "email": OWNER_EMAIL.lower(), "name": "Aneesh",
                                    "password_hash": hash_pw("demo1234"), "shop_name": "Metro Tech Retail",
                                    "created_at": datetime.now(timezone.utc).isoformat()})
        u = await db.users.find_one({"user_id": uid}, {"_id": 0})
        await ensure_shop(u)


@app.on_event("shutdown")
async def shutdown(): mclient.close()
