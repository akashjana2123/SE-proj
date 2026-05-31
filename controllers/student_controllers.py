import datetime
from flask import current_app as app, render_template, request, jsonify, session, redirect, url_for
from models import db, Student, Mark, Subject, Result, AuditLog, Backlog
from sqlalchemy import func


# ─────────────────────────────────────────────────────────
#  STUDENT AUTHENTICATION DECORATOR GUARD
# ─────────────────────────────────────────────────────────
def get_logged_student():
	if "role" in session and session["role"] == "student" and "email" in session:
		return Student.query.filter_by(student_email=session.get("email")).first()
	return None


# ─────────────────────────────────────────────────────────
#  STUDENT BASE ROUTE
# ─────────────────────────────────────────────────────────
@app.route("/student_dashboard", methods=["GET"])
def student_dashboard():
	student = get_logged_student()
	if not student:
		return redirect(url_for("login"))
	return render_template("student.html")

