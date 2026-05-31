from flask import current_app as app, render_template, request, redirect, url_for, session, flash
from models import *
from controllers.admin_controllers import *
from controllers.faculty_controllers import *
from controllers.student_controllers import *

@app.route('/')
def home():
    obj = Admin.query.first()
    if obj is None:
        # Handle the case when there is no admin record
        admin_name = "No Admin Found"
    else:
        admin_name = obj.admin_name
    return render_template("index.html", admin_name=admin_name)

@app.route('/login', methods=['GET', 'POST'])
def login():
    # If this is a GET request and a user is already logged in, redirect them to their dashboard.
    if request.method == 'GET' and "role" in session:
        if session["role"] == "admin":
            return redirect(url_for("admin_dashboard"))
        elif session["role"] == "faculty":
            return redirect(url_for("faculty_dashboard"))
        elif session["role"] == "student":
            return redirect(url_for("student_dashboard"))

    error = None

    if request.method == 'POST':
        # Every time they click submit, clear old session data first 
        # so lingering logins don't interfere
        session.clear()
        
        email = request.form.get('email')
        password = request.form.get('password')
        role = (request.form.get('role') or '').strip().lower()  # Expecting 'admin', 'faculty', or 'student'

        if role == 'admin':
            admin_obj = Admin.query.filter_by(admin_email=email).first()
            if admin_obj and admin_obj.admin_password == password:
                session["user_id"] = admin_obj.admin_id
                session["email"] = admin_obj.admin_email
                session["role"] = "admin"
                return redirect(url_for('admin_dashboard'))
            else:
                error = "Invalid admin credentials"

        elif role == 'faculty':
            faculty_obj = Faculty.query.filter_by(faculty_email=email).first()
            if faculty_obj and faculty_obj.faculty_password == password:
                session["user_id"] = faculty_obj.faculty_id
                session["email"] = faculty_obj.faculty_email
                session["role"] = "faculty"
                return redirect(url_for('faculty_dashboard'))
            else:
                error = "Invalid faculty credentials"

        elif role == 'student':
            student_obj = Student.query.filter_by(student_email=email).first()
            if student_obj and student_obj.student_password == password:
                session["user_id"] = student_obj.student_id
                session["email"] = student_obj.student_email
                session["role"] = "student"
                return redirect(url_for('student_dashboard'))
            else:
                error = "Invalid student credentials"
        else:
            error = "Please select a valid role"

    return render_template("index.html", error=error)


@app.route('/logout')
def logout():
    # Clear all data out of the user session container
    session.clear()
    flash("You have been successfully logged out.", "success")
    return redirect(url_for('login'))