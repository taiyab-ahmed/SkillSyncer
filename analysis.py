"""Rule-based resume analysis: ATS score, skill gap, suggestions and interview questions.
No AI model is used here; everything is keyword and pattern based."""
import re

EMAIL_RE = r"[\w.+-]+@[\w-]+\.[\w.]+"
PHONE_PATTERNS = [r"(?<!\d)\d{10}(?!\d)", r"(?<!\d)\d{5}[\s-]\d{5}(?!\d)", r"\+\d{1,3}[\s-]?\d{4,5}[\s-]?\d{4,6}",
                  r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}"]
SECTION_GROUPS = {
    "education": r"education|qualifications?|academics?",
    "experience": r"experience|employment|internships?|work history",
    "skills": r"skills|technical skills|core competencies",
    "projects": r"projects?",
    "summary": r"summary|objective|profile|about me",
    "certifications": r"certifications?|achievements|awards",
}
STRONG_VERBS = ["built", "developed", "designed", "led", "implemented", "created", "optimized", "optimised", "automated",
                "delivered", "improved", "launched", "managed", "reduced", "increased", "architected", "deployed", "migrated"]
WEAK_PHRASES = {"responsible for": "Led or Owned", "worked on": "Built or Developed", "helped": "Supported or Enabled",
                "duties included": "Delivered", "involved in": "Contributed to", "assisted with": "Supported",
                "tasked with": "Executed"}
ALIASES = {  # related terms: if only these appear, the skill counts as "partial"
    "python": ["django", "flask", "pandas", "numpy"], "machine learning": ["scikit-learn", "tensorflow", "pytorch", "deep learning", "ml"],
    "javascript": ["js", "react", "node", "typescript"], "api": ["rest", "restful", "fastapi", "flask", "django"],
    "rest api": ["rest", "restful", "api", "fastapi"], "sql": ["mysql", "postgresql", "postgres", "sqlite", "database"],
    "html": ["html5"], "css": ["css3", "tailwind", "bootstrap"], "java": ["spring", "hibernate"],
    "excel": ["spreadsheet", "spreadsheets", "pivot"], "docker": ["kubernetes", "containers"],
    "aws": ["azure", "gcp", "cloud"], "nlp": ["spacy", "transformers", "natural language"],
    "computer vision": ["opencv", "yolo", "image processing"], "git": ["github", "gitlab"],
}
QUESTION_BANK = {
    "python": "Explain the difference between a list, tuple and dictionary in Python, and when you would use each.",
    "flask": "How does a request travel through a Flask app from the URL to your view and back to the browser?",
    "django": "What are Django models, views and templates, and how do they work together?",
    "sql": "How would you find the second highest salary in a table, and what is the difference between INNER and LEFT JOIN?",
    "java": "What is the difference between an interface and an abstract class in Java?",
    "javascript": "Explain closures in JavaScript and how the value of 'this' is decided.",
    "react": "When does a React component re-render, and how do you avoid unnecessary renders?",
    "html": "What is semantic HTML and why does it matter for accessibility and SEO?",
    "css": "Explain the CSS box model and when you would pick flexbox over grid.",
    "docker": "What is the difference between a Docker image and a container?",
    "aws": "Which AWS services have you used, and how did you secure them?",
    "git": "How do you resolve a merge conflict, and when would you rebase instead of merge?",
    "machine learning": "How do you detect and handle overfitting in a model?",
    "nlp": "How would you turn raw text into features for a classifier?",
    "excel": "How would you use lookups and pivot tables to summarise a large dataset?",
    "statistics": "Explain a p-value and a confidence interval in plain words.",
    "api": "What makes an API RESTful, and how do you version and secure one?",
    "rest api": "What makes an API RESTful, and how do you version and secure one?",
}

def has_term(text, term):
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE) is not None

def find_sections(text):
    return [k for k, pat in SECTION_GROUPS.items()
            if re.search(r"(?<![A-Za-z])(?:" + pat + r")(?![A-Za-z])", text, re.IGNORECASE)]

def target_skills(jd_text, required, skill_list):
    in_jd = [s for s in skill_list if jd_text and has_term(jd_text, s)]
    return list(dict.fromkeys(list(required) + in_jd))[:15]

def skill_gap(text, skills):
    gap = []
    for skill in skills:
        if has_term(text, skill):
            status = "found"
        elif any(has_term(text, a) for a in ALIASES.get(skill, [])):
            status = "partial"
        else:
            status = "missing"
        gap.append({"skill": skill, "status": status})
    return gap

def match_score(gap):
    if not gap:
        return None
    points = sum(1 if g["status"] == "found" else 0.5 if g["status"] == "partial" else 0 for g in gap)
    return round(100 * points / len(gap))

def ats_score(text, sections, match, n_skills):
    words = len(text.split())
    email = bool(re.search(EMAIL_RE, text))
    phone = any(re.search(p, text) for p in PHONE_PATTERNS)
    years = len(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text))
    metrics = len(re.findall(r"\d+\s*%|\b\d+x\b|\b\d[\d,]*\+?\s*(?:users|customers|clients|projects|members|apis|requests)", text, re.IGNORECASE))
    strong = sum(1 for v in STRONG_VERBS if has_term(text, v))
    items = []
    def add(label, points, mx, note):
        items.append({"label": label, "points": points, "max": mx, "note": note})
    add("Contact details", (8 if email else 0) + (7 if phone else 0), 15,
        "Email and phone found" if email and phone else "Email missing" if not email and phone else "Phone missing" if email else "Email and phone missing")
    add("Standard sections", min(25, len(sections) * 5), 25, f"{len(sections)} sections found: " + (", ".join(sections) or "none"))
    add("Length", 10 if 200 <= words <= 1200 else 6 if 100 <= words < 200 or 1200 < words <= 1800 else 2, 10, f"{words} words")
    add("Dates", 10 if years >= 2 else 5 if years == 1 else 0, 10, f"{years} year(s) mentioned")
    cover = round(match * 0.3) if match is not None else min(30, n_skills * 5)
    add("Keyword coverage", cover, 30, f"{match}% of target skills" if match is not None else f"{n_skills} skills detected")
    add("Impact", (5 if metrics >= 1 else 0) + (5 if strong >= 3 else 0), 10, f"{metrics} measurable result(s), {strong} action verb(s)")
    return {"score": sum(i["points"] for i in items), "items": items, "metrics": metrics, "strong": strong,
            "email": email, "phone": phone, "words": words}

def suggestions(text, gap, sections, ats):
    tips = [f'Replace "{p}" with a stronger verb such as {b}.' for p, b in WEAK_PHRASES.items() if has_term(text, p)]
    if ats["metrics"] == 0:
        tips.append("Add measurable results, for example 'cut report time by 40%' or 'served 2,000 users'.")
    if ats["strong"] < 3:
        tips.append("Start bullet points with action verbs such as Built, Led, Designed or Automated.")
    for g in [g for g in gap if g["status"] == "missing"][:3]:
        tips.append(f'The role needs "{g["skill"]}". If you have used it, add it to Skills and show it in a project.')
    for g in [g for g in gap if g["status"] == "partial"][:2]:
        tips.append(f'You mention tools related to "{g["skill"]}". Name "{g["skill"]}" explicitly so ATS filters can find it.')
    for name in ("summary", "skills", "experience", "education", "projects"):
        if name not in sections:
            tips.append(f"Add a clear {name.title()} section.")
    if not ats["email"] or not ats["phone"]:
        tips.append("Put a professional email address and phone number at the top.")
    if ats["words"] < 200:
        tips.append("The resume is quite short. Add detail on your projects and responsibilities.")
    elif ats["words"] > 1200:
        tips.append("The resume is long. Keep it to one or two pages.")
    return tips[:10] or ["No major problems found. Keep the resume tailored to each role."]

def interview_questions(role, gap, resume_skills):
    gap_skills = [g["skill"] for g in gap]
    ordered = [g["skill"] for g in gap if g["status"] != "missing"] + [s for s in resume_skills if s not in gap_skills]
    qs = []
    for s in ordered[:5]:
        qs.append(f"{s}: " + QUESTION_BANK.get(s, f"Describe a project where you used {s}. What problem did it solve and what would you change?"))
    for g in [g for g in gap if g["status"] == "missing"][:2]:
        qs.append(f'{g["skill"]} (gap): The {role} role needs it but it is not on your resume. Have you used it, and how fast could you become productive?')
    qs.append("Walk me through your most challenging project and exactly what you built yourself.")
    qs.append("Tell me about a disagreement with a teammate and how you resolved it.")
    return qs

def analyze_resume(text, role, rules, jd_text, skill_list, resume_skills):
    gap = skill_gap(text, target_skills(jd_text, rules.get("required_skills", []), skill_list))
    match = match_score(gap)
    sections = find_sections(text)
    ats = ats_score(text, sections, match, len(resume_skills))
    tips = suggestions(text, gap, sections, ats)
    return {"ats": {"score": ats["score"], "items": ats["items"]}, "match_score": match, "jd_used": bool(jd_text.strip()),
            "gap": gap, "suggestions": tips, "questions": interview_questions(role, gap, resume_skills)}