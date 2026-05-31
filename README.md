# SE Project

## Overview
This project is a Flask-based student management system for admin, faculty, and student workflows.
The app includes dashboards, CRUD operations for faculty, students, and subjects, result generation, result management, and password management.

## Prerequisites
- Python 3.12 or later
- Git (optional)

## Setup
1. Create a virtual environment:
	 ```powershell
	 python3 -m venv env
	 ```
2. Activate the environment:
	 - On Linux/macOS:
		 ```bash
		 source env/bin/activate
		 ```
	 - On Windows PowerShell:
		 ```powershell
		 .\env\Scripts\Activate.ps1
		 ```
3. Install dependencies:
	 ```powershell
	 pip install -r requirements.txt
	 ```

## Run the application
```powershell
python main.py
```

## Notes
- Ensure the virtual environment is active before installing dependencies or running the app.
- If you are on Windows and PowerShell blocks script execution, run:
	```powershell
	Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
	```

## Project Structure
- `main.py` - application entry point
- `controllers/` - route handlers and API controllers
- `models.py` - database models and ORM definitions
- `database.py` - database setup and initialization
- `templates/` - frontend templates
- `static/` - CSS and static assets