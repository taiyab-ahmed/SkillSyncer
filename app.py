import os, re, json, sqlite3, datetime, secrets, hmac, time
from functools import wraps
from io import BytesIO
from flask import Flask, request, jsonify, render_template, g, session, redirect, url_for, flash, send_file
from werkzeug.utils import secure_filename

try:
    import pypdf
except ImportError:
    pypdf = None
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
except ImportError:
    canvas = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# On Vercel only /tmp is writable (and it is temporary), so data files go there.
DATA_DIR = "/tmp" if os.environ.get("VERCEL") else BASE_DIR
UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "resume_analyzer.db")
RULES_PATH = os.path.join(DATA_DIR, "job_rules.json")
BUNDLED_RULES_PATH = os.path.join(BASE_DIR, "job_rules.json")  # shipped with the code
MAX_UPLOAD_MB = 4  # Vercel rejects request bodies above 4.5 MB
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def load_env_file():
    """Local development only: read KEY=VALUE lines from a .env file (which is git-ignored)."""
    try:
        with open(os.path.join(BASE_DIR, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass

load_env_file()

app = Flask(__name__)
# No secret or password is stored in the code. They come from environment variables (Vercel settings or .env).
# Without SECRET_KEY a random key is used, so nobody can forge a login cookie (but sessions reset on restart).
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("VERCEL"))
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

SKILL_LIST = sorted({
    "python", "flask", "django", "sql", "git", "api", "java", "spring", "hibernate",
    "rest api", "html", "css", "javascript", "react", "responsive design", "excel",
    "power bi", "tableau", "statistics", "machine learning", "pandas", "numpy",
    "scikit-learn", "tensorflow", "opencv", "computer vision", "pytorch", "yolo",
    "deep learning", "c++", "mongodb", "mysql", "postgresql", "aws", "azure",
    "docker", "kubernetes", "communication", "leadership", "problem solving",
    "spacy", "nlp", "transformers", "streamlit", "linux",
})

def _rule(exp, skills, deg_years, locations=()):
    return {"min_years_experience": exp, "required_skills": list(skills), "require_bachelor_degree": True,
            "min_degree_years": deg_years, "allowed_locations": list(locations)}

DEFAULT_RULES = {
    "Python Developer": _rule(4, ["python"], 4, ["bangalore", "bengaluru"]),
    "Java Developer": _rule(2, ["java"], 3),
    "Web Developer": _rule(2, ["html", "css", "javascript"], 3),
    "Data Analyst": _rule(2, ["sql", "excel"], 3),
    "Machine Learning Engineer": _rule(2, ["python", "machine learning"], 3),
}

def load_rules():
    for path in (RULES_PATH, BUNDLED_RULES_PATH):
        try:
            with open(path, encoding="utf-8") as f:
                rules = json.load(f)
            if isinstance(rules, dict) and rules:
                return rules
        except (OSError, ValueError):
            pass
    return DEFAULT_RULES

def split_list(value):
    return list(dict.fromkeys(x.strip().lower() for x in value.split(",") if x.strip()))

def parse_rules_form(form):
    rules = {}
    for i in range(int(form.get("count", "0")) + 1):  # the last block is the empty "new role" block
        name = form.get(f"name_{i}", "").strip()
        if not name or form.get(f"del_{i}"):
            continue
        try:
            exp = float(form.get(f"exp_{i}") or 0)
            yrs = int(form.get(f"degyears_{i}") or 0)
        except ValueError:
            raise ValueError(f"{name}: experience and degree years must be numbers.")
        if not (0 <= exp <= 60 and 0 <= yrs <= 6):
            raise ValueError(f"{name}: experience must be 0-60 and degree years 0-6.")
        rules[name] = {"min_years_experience": exp, "required_skills": split_list(form.get(f"skills_{i}", "")),
                       "require_bachelor_degree": bool(form.get(f"degree_{i}")), "min_degree_years": yrs,
                       "allowed_locations": split_list(form.get(f"loc_{i}", ""))}
    if not rules:
        raise ValueError("Keep at least one job role.")
    return rules

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()

NEW_SCHEMA = """CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT, resume_filename TEXT, location TEXT,
    years_experience REAL, has_bachelor_degree INTEGER, degree_years INTEGER,
    is_python_developer INTEGER, result TEXT, reasons TEXT, created_at TEXT,
    salary TEXT DEFAULT '', notice TEXT DEFAULT '', skills TEXT DEFAULT '', role TEXT DEFAULT '')"""
KEEP_COLUMNS = ["resume_filename", "location", "years_experience", "has_bachelor_degree", "degree_years",
                "is_python_developer", "result", "reasons", "created_at", "salary", "notice", "skills", "role"]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(candidates)")}
    if "email" in cols:  # older version stored name/email/mobile; rebuild the table without them
        conn.execute("ALTER TABLE candidates RENAME TO candidates_old")
        conn.execute(NEW_SCHEMA)
        keep = ",".join(c for c in KEEP_COLUMNS if c in cols)
        conn.execute(f"INSERT INTO candidates ({keep}) SELECT {keep} FROM candidates_old")
        conn.execute("DROP TABLE candidates_old")
    else:
        conn.execute(NEW_SCHEMA)
    if "role" not in {r[1] for r in conn.execute("PRAGMA table_info(candidates)")}:
        conn.execute("ALTER TABLE candidates ADD COLUMN role TEXT DEFAULT ''")
    conn.commit()
    conn.close()

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() == "pdf"

def extract_text_from_pdf(filepath):
    if pypdf is None:
        raise RuntimeError("pypdf is missing. Run: pip install -r requirements.txt")
    text = ""
    with open(filepath, "rb") as f:
        reader = pypdf.PdfReader(f)
        for page in reader.pages:
            text += (page.extract_text() or "") + "\n"
    return text.strip()

def extract_years_experience(text):
    patterns = [
        r"(\d+(?:\.\d+)?)\s*\+?\s*years?\s+of\s+experience",
        r"(\d+(?:\.\d+)?)\s*\+?\s*years?\s+experience",
        r"experience\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*\+?\s*years?"
    ]
    found = []
    for pattern in patterns:
        found.extend(float(m) for m in re.findall(pattern, text, re.IGNORECASE))
    return max(found) if found else 0.0

def extract_python_skill(text):
    return bool(re.search(r"\bpython\b", text, re.IGNORECASE))

def extract_bachelor_degree(text):
    has_bachelor = bool(re.search(
        r"\bbachelor\b|\bb\.?\s*tech\b|\bb\.?\s*e\.?\b|\bb\.?\s*sc\b|\bb\.?\s*ca\b",
        text, re.IGNORECASE))
    years_match = re.search(r"(\d)\s*[- ]?year[s]?\s+(?:bachelor|degree|program|course)", text, re.IGNORECASE)
    degree_years = int(years_match.group(1)) if years_match else (4 if has_bachelor else 0)
    return has_bachelor, degree_years

def extract_resume_data(filepath):
    text = extract_text_from_pdf(filepath)
    has_bachelor, degree_years = extract_bachelor_degree(text)
    low = text.lower()
    skills = [skill for skill in SKILL_LIST if re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", low)]
    return {"raw_text": text, "years_experience": extract_years_experience(text),
            "is_python_developer": extract_python_skill(text),
            "has_bachelor_degree": has_bachelor, "degree_years": degree_years,
            "skills": skills}

SECTION_GROUPS = {
    "education": r"education|qualifications?|academics?",
    "experience": r"experience|employment|internships?|work history",
    "skills": r"skills|technical skills|core competencies",
    "projects": r"projects?",
    "summary": r"summary|objective|profile|about me",
    "certifications": r"certifications?|achievements|awards",
}
OTHER_DOCUMENT_HINTS = [  # phrases that show up in job posts, invoices, papers, books etc., not in resumes
    "job description", "we are looking for", "about the company", "about us", "how to apply", "apply now",
    "invoice", "bill to", "purchase order", "terms and conditions", "table of contents", "abstract",
    "this certificate is awarded", "certificate of completion", "dear sir", "glossary",
]
PHONE_PATTERNS = [r"(?<!\d)\d{10}(?!\d)", r"(?<!\d)\d{5}[\s-]\d{5}(?!\d)", r"\+\d{1,3}[\s-]?\d{4,5}[\s-]?\d{4,6}",
                  r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}"]

def resume_check(text):
    """Returns (is_resume, reason). Every rule must pass, so non-resume PDFs are rejected."""
    words = len(text.split())
    if words < 40:
        return False, "it has almost no text"
    if words > 4000:
        return False, "it is too long to be a resume"
    lower = text.lower()
    for hint in OTHER_DOCUMENT_HINTS:
        if hint in lower:
            return False, f'it looks like a different kind of document (contains "{hint}")'
    has_email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    has_phone = any(re.search(p, text) for p in PHONE_PATTERNS)
    if not (has_email or has_phone):
        return False, "no email address or phone number was found"
    sections = [k for k, pat in SECTION_GROUPS.items() if re.search(r"(?<![A-Za-z])(?:" + pat + r")(?![A-Za-z])", text, re.IGNORECASE)]
    if len(sections) < 2:
        return False, "no resume sections such as Education, Experience or Skills were found"
    if not re.search(r"(?<!\d)(19|20)\d{2}(?!\d)", text):
        return False, "no years or dates were found"
    return True, ""

def not_resume_message(reason):
    return f"This PDF is not a resume: {reason}. Please upload only a resume PDF."

def has_skill(text, skill):
    return re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", text, re.IGNORECASE) is not None

def match_criteria(profile, resume_text, rules):
    """profile: years_experience, has_bachelor_degree, degree_years, location. rules: one role's rules."""
    checks, reasons = [], []
    def check(label, detail, ok, reason):
        checks.append({"label": label, "detail": detail, "ok": bool(ok)})
        if not ok:
            reasons.append(reason)
    exp, need = profile["years_experience"], float(rules.get("min_years_experience", 0))
    check("Experience", f"{exp:g} years (needs {need:g}+)", exp >= need,
          f"Needs {need:g}+ years experience (found {exp:g}).")
    skills = rules.get("required_skills", [])
    if skills:
        missing = [k for k in skills if not has_skill(resume_text, k)]
        check("Required skills", "All found in resume" if not missing else "Missing: " + ", ".join(missing),
              not missing, "Required skill(s) not found in resume: " + ", ".join(missing) + ".")
    if rules.get("require_bachelor_degree"):
        yrs, need_yrs = profile["degree_years"], int(rules.get("min_degree_years", 0))
        if not profile["has_bachelor_degree"]:
            check("Bachelor's degree", "No bachelor's degree", False, "Bachelor's degree is required.")
        else:
            check("Bachelor's degree", f"{yrs}-year degree (needs {need_yrs} years)", yrs >= need_yrs,
                  f"Degree duration must be {need_yrs} years (found {yrs}).")
    allowed = [x.lower() for x in rules.get("allowed_locations", [])]
    loc = profile.get("location", "").strip()
    if allowed and loc:  # bulk upload has no location
        check("Location", loc, loc.lower() in allowed,
              f"Location '{loc}' is not in required location(s): {', '.join(rules['allowed_locations'])}.")
    passed = not reasons
    if passed:
        reasons.append("All rules for this job role were satisfied.")
    return passed, reasons, checks

def build_output(fields, resume_name, saved_name, profile, extracted, passed, reasons, checks):
    result = "MATCHING" if passed else "NOT MATCHING"
    db = get_db()
    db.execute("""INSERT INTO candidates
        (resume_filename,location,years_experience,has_bachelor_degree,degree_years,
         is_python_developer,result,reasons,created_at,salary,notice,skills,role)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (saved_name, profile["location"], profile["years_experience"], int(profile["has_bachelor_degree"]),
         profile["degree_years"], int(extracted["is_python_developer"]), result, json.dumps(reasons),
         datetime.datetime.now().isoformat(timespec="minutes"), fields["salary"], fields["notice"],
         ", ".join(extracted["skills"]), fields["role"]))
    db.commit()
    return {"result": result, "role": fields["role"], "resume": resume_name, "location": profile["location"],
            "checks": checks, "skills": extracted["skills"], "reasons": reasons}

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapped

@app.route("/")
def index():
    return render_template("index.html", roles=list(load_rules()))

@app.route("/analyze", methods=["POST"])
def analyze():
    f = {k: request.form.get(k, "").strip() for k in ["role", "experience", "degree", "location", "salary", "notice"]}
    errors = []
    years = 0.0
    rules = load_rules()
    if f["role"] not in rules:
        errors.append("Select a job role.")
    try:
        years = float(f["experience"])
        if not 0 <= years <= 60:
            raise ValueError
    except ValueError:
        errors.append("Enter experience as a number of years (0 to 60).")
    if f["degree"] not in ("0", "3", "4"):
        errors.append("Select the bachelor's degree option.")
    if not f["location"]:
        errors.append("Location is required.")
    upload = request.files.get("resume")
    if not upload or not upload.filename:
        errors.append("Resume PDF is required.")
    elif not allowed_file(upload.filename):
        errors.append("Resume must be a PDF file.")
    if errors:
        return jsonify({"error": True, "messages": errors}), 400

    filename = secure_filename(upload.filename)
    unique_name = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(3)}_{filename}"
    filepath = os.path.join(UPLOAD_FOLDER, unique_name)
    upload.save(filepath)
    try:
        extracted = extract_resume_data(filepath)
        if not extracted["raw_text"]:
            os.remove(filepath)
            return jsonify({"error": True, "messages": ["No selectable text was found. Scanned or image-only PDFs are not supported. Please upload a text-based resume PDF."]}), 400
        is_resume, reason = resume_check(extracted["raw_text"])
        if not is_resume:
            os.remove(filepath)
            return jsonify({"error": True, "messages": [not_resume_message(reason)]}), 400
        degree_years = int(f["degree"])
        profile = {"years_experience": years, "has_bachelor_degree": degree_years > 0,
                   "degree_years": degree_years, "location": f["location"]}
        passed, reasons, checks = match_criteria(profile, extracted["raw_text"], rules[f["role"]])
        output = build_output(f, filename, unique_name, profile, extracted, passed, reasons, checks)
        session["last_report"] = output
        return jsonify(output)
    except Exception as exc:
        return jsonify({"error": True, "messages": [f"Could not read PDF: {exc}"]}), 400

@app.route("/report")
def report():
    data = session.get("last_report")
    if not data:
        flash("Analyze a resume first to create a report.", "error")
        return redirect(url_for("index"))
    if canvas is None:
        return "PDF report dependency missing. Run pip install -r requirements.txt", 500
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 55
    pdf.setTitle("Resume Analyzer Report")
    pdf.setFont("Helvetica-Bold", 18); pdf.drawString(48, y, "Resume Analyzer Report"); y -= 35
    pdf.setFont("Helvetica", 11)
    lines = [f"Resume: {data['resume']}", f"Job role: {data['role']}", f"Screening result: {data['result']}", "", "Checks:"]
    lines += [f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['label']}: {c['detail']}" for c in data["checks"]]
    lines += ["", "Skills found: " + (", ".join(data["skills"]) or "None"), "", "Screening notes:"]
    lines += ["- " + item for item in data["reasons"]]
    lines += ["", "Note: This is an automated screening aid, not a hiring decision."]
    for line in lines:
        if y < 55:
            pdf.showPage(); y = height - 55; pdf.setFont("Helvetica", 11)
        pdf.drawString(48, y, line[:115]); y -= 20
    pdf.save(); buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="resume_analysis_report.pdf", mimetype="application/pdf")

@app.route("/candidates")
@admin_required
def list_candidates():
    rows = get_db().execute("SELECT id,role,resume_filename,location,years_experience,degree_years,result,skills,created_at FROM candidates ORDER BY id DESC").fetchall()
    return jsonify([dict(row) for row in rows])

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        expected_user = os.environ.get("ADMIN_USER", "")
        expected_password = os.environ.get("ADMIN_PASSWORD", "")
        if not expected_user or not expected_password:
            flash("Admin login is not set up. The site owner must set ADMIN_USER and ADMIN_PASSWORD.", "error")
            return render_template("login.html")
        user = request.form.get("username", "").encode()
        password = request.form.get("password", "").encode()
        user_ok = hmac.compare_digest(user, expected_user.encode())
        password_ok = hmac.compare_digest(password, expected_password.encode())
        if user_ok and password_ok:
            session.clear()
            session["admin_logged_in"] = True
            return redirect(url_for("dashboard"))
        time.sleep(1)  # slows down password guessing
        flash("Login details are incorrect.", "error")
    return render_template("login.html")

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/admin")
@admin_required
def dashboard():
    q = request.args.get("q", "").strip().lower()
    role = request.args.get("role", "")
    rows = []
    for r in get_db().execute("SELECT * FROM candidates ORDER BY id DESC").fetchall():
        r = dict(r)
        r["file"] = re.sub(r"^\d{14}_[0-9a-f]{6}_", "", r["resume_filename"] or "")
        if (not q or q in r["file"].lower() or q in (r["location"] or "").lower()) and (not role or r["role"] == role):
            rows.append(r)
    matched = sum(1 for r in rows if r["result"] == "MATCHING")
    return render_template("dashboard.html", rows=rows, roles=list(load_rules()), total=len(rows),
                           matched=matched, not_matched=len(rows) - matched)

@app.route("/admin/rules", methods=["GET", "POST"])
@admin_required
def edit_rules():
    if request.method == "POST":
        try:
            rules = parse_rules_form(request.form)
            with open(RULES_PATH, "w", encoding="utf-8") as f:
                json.dump(rules, f, indent=2)
            flash("Job rules saved.", "success")
            return redirect(url_for("edit_rules"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("rules.html", rules=load_rules())

@app.route("/admin/bulk", methods=["GET", "POST"])
@admin_required
def bulk_screen():
    rules, results = load_rules(), None
    if request.method == "POST":
        results = []
        role = request.form.get("role", "")
        if role not in rules:
            results.append({"file": "Job role", "error": "select a valid job role"})
        else:
            for upload in request.files.getlist("resumes")[:30]:
                if not upload.filename:
                    continue
                if not allowed_file(upload.filename):
                    results.append({"file": upload.filename, "error": "not a PDF"})
                    continue
                path = os.path.join(UPLOAD_FOLDER, secrets.token_hex(4) + "_" + secure_filename(upload.filename))
                upload.save(path)
                try:
                    extracted = extract_resume_data(path)
                    if not extracted["raw_text"]:
                        raise ValueError("No selectable text (scanned PDF/OCR not enabled)")
                    is_resume, reason = resume_check(extracted["raw_text"])
                    if not is_resume:
                        raise ValueError("not a resume: " + reason)
                    profile = {"years_experience": extracted["years_experience"], "has_bachelor_degree": extracted["has_bachelor_degree"],
                               "degree_years": extracted["degree_years"], "location": ""}
                    passed, reasons, _ = match_criteria(profile, extracted["raw_text"], rules[role])
                    results.append({"file": upload.filename, "passed": passed, "reasons": reasons})
                except Exception as exc:
                    results.append({"file": upload.filename, "error": str(exc)})
                finally:
                    if os.path.exists(path):
                        os.remove(path)
    return render_template("bulk.html", roles=list(rules), results=results)

@app.errorhandler(413)
def too_large(error):
    return jsonify({"error": True, "messages": [f"Upload exceeds the {MAX_UPLOAD_MB} MB limit."]}), 413

init_db()  # also runs on Vercel, where the app is imported instead of started

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)