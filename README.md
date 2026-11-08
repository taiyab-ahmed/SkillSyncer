# Enhanced Resume Analyzer (Flask)

This is an enhanced version of your uploaded project. The original screening rules and screenshot-inspired design are retained, with more options added.

## Features added
- Extracted skills list.
- PDF report download.
- Form fields: experience (years), bachelor's degree, location, and optional salary / notice period. No name, email, phone, LinkedIn or GitHub is collected.
- PDF drag-and-drop selection, PDF-only validation, and 8 MB upload limit.
- Dark-mode toggle.
- HR/admin login, candidate dashboard, search/filter, simple matching chart.
- Bulk PDF screening (up to 30 files per batch).
- Job roles with their own rules (`job_rules.json`): minimum experience, required skills (found in the resume PDF), bachelor degree and duration, and allowed locations. Experience and degree are entered in the form.
- HR can add, edit and delete job roles and rules on the **Job rules** page (`/admin/rules`). There is no job-role selection.

## Run on Windows / VS Code
1. Extract the ZIP.
2. Open the `resume_analyzer` folder in VS Code.
3. In the terminal run:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

If PowerShell blocks activation, run:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`

Then open `http://127.0.0.1:5000`.

## Admin demo login
- Username: `admin`
- Password: `change-me`

These demo credentials are not safe for public deployment. Before sharing, set environment variables `ADMIN_USER`, `ADMIN_PASSWORD`, and `SECRET_KEY`. Do not expose Flask debug mode publicly.

## Pages
- `/` — candidate screening form
- `/admin/login` — admin sign in
- `/admin` — candidate dashboard
- `/admin/rules` — edit job roles and their rules
- `/admin/bulk` — batch screening
- `/report` — download the latest individual report
- `/candidates` — JSON endpoint for candidate records

## Important limitations
- Screening is rule/keyword based, not a hiring decision. Review applications with human judgment and fair criteria.
- Bulk uploads show a result per file but are not saved. Experience and degree are read from each resume, and location is not checked.
- Scanned image-only PDFs need OCR. OCR is not enabled in this project; the app displays a helpful message if a PDF contains no selectable text.
- Email notifications are not enabled because they require mail-server credentials.
- Candidate personal data is stored locally in `resume_analyzer.db` and uploaded PDFs in `uploads/`. Handle and delete personal data responsibly.
- The admin login is a simple classroom-demo login. Add stronger authentication, CSRF protection, and rate limiting before any real deployment.
