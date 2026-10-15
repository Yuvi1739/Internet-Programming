# Library Management System

A local college programming experiment built with Flask, SQLite, HTML, CSS and JavaScript.

## Requirements
- Python 3.10+
- VS Code
- A browser

## Run on Windows
Open this folder in VS Code. Open **Terminal → New Terminal**, then run:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

If PowerShell blocks environment activation, use Command Prompt terminal and run:
```bat
venv\Scripts\activate.bat
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 in your browser.

## First admin login
- Email: `admin@library.local`
- Password: `Admin@123`

Change the default admin password and Flask secret key before using this beyond a local demonstration. This project is intended for a local academic experiment, not production deployment.

## Features
- Student registration and login
- Book catalog search and details
- Admin book inventory management
- Issue and return workflow
- Due dates and overdue fine calculation (₹5/day by default)
- Student borrowing history and current fine estimate
- Study material upload and year/semester search
- Contact form
- SQLite database created automatically on first run

Uploaded study materials are saved in `uploads/`. The local database is `library.db`.
