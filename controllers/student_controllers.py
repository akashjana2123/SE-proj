import os
import datetime
from flask import current_app as app, render_template, request, jsonify, session, redirect, url_for
from models import db, Student, Mark, Subject, Result, AuditLog, Backlog, ResultDetail
from sqlalchemy import func

# Ensure reports directory exists locally
REPORTS_DIR = os.path.join(os.getcwd(), 'reports')
if not os.path.exists(REPORTS_DIR):
    os.makedirs(REPORTS_DIR)

# ─────────────────────────────────────────────────────────
#  STUDENT AUTHENTICATION DECORATOR GUARD
# ─────────────────────────────────────────────────────────
def get_logged_student():
    if "role" in session and session["role"] == "student" and "email" in session:
        return Student.query.filter_by(student_email=session.get("email")).first()
    return None

# ─────────────────────────────────────────────────────────
#  STUDENT BASE ROUTE (LOADS DASHBOARD)
# ─────────────────────────────────────────────────────────
@app.route("/student_dashboard", methods=["GET"])
def student_dashboard():
    student = get_logged_student()
    if not student:
        return redirect(url_for("login"))
    
    # Calculate Admitted Year from Academic Year string (e.g., "2024-25" -> "2024")
    admitted_year = student.academic_year.split('-')[0] if '-' in student.academic_year else student.academic_year
    
    # Fetch latest published CGPA & SGPA
    latest_result = Result.query.filter_by(student_id=student.student_id, status='PUBLISHED')\
                                .order_by(Result.semester.desc()).first()
    
    current_sgpa = latest_result.sgpa if latest_result else 0.0
    current_cgpa = latest_result.cgpa if latest_result else 0.0
    
    # Total completed semesters based on published records
    completed_sems = Result.query.filter_by(student_id=student.student_id, status='PUBLISHED').count()
    
    # Count of active backlogs
    active_backlogs_count = Backlog.query.filter_by(student_id=student.student_id, status='ACTIVE').count()

    student_data = {
        "name": student.student_name,
        "email": student.student_email,
        "roll_no": student.roll_no,
        "current_sem": student.current_sem,
        "section": student.section or "N/A",
        "branch": student.branch,
        "academic_year": student.academic_year,
        "admitted_year": admitted_year,
        "sgpa": current_sgpa,
        "cgpa": current_cgpa,
        "completed_sems": completed_sems,
        "backlogs_count": active_backlogs_count
    }

    return render_template("student.html", student=student_data)

# ─────────────────────────────────────────────────────────
#  API: FETCH DATA FOR A SPECIFIC SEMESTER
# ─────────────────────────────────────────────────────────
@app.route("/api/student/semester_data", methods=["GET"])
def get_semester_data():
    student = get_logged_student()
    if not student:
        return jsonify({"error": "Unauthorized"}), 401
    
    sem = request.args.get('semester', type=int)
    if not sem:
        return jsonify({"error": "Semester parameter missing"}), 400

    # Fetch Result Summary
    res = Result.query.filter_by(student_id=student.student_id, semester=sem, status='PUBLISHED').first()
    
    # Fetch Subject Wise Details
    details_list = []
    if res:
        details = ResultDetail.query.filter_by(result_id=res.result_id).all()
        for d in details:
            sub = Subject.query.get(d.subject_id)
            details_list.append({
                "subject_code": sub.subject_code,
                "subject_name": sub.subject_name,
                "credits": d.credits,
                "marks": d.marks,
                "grade": d.grade,
                "grade_point": d.grade_point,
                "weighted_points": d.credits * d.grade_point
            })
        
        return jsonify({
            "has_data": True,
            "sgpa": res.sgpa,
            "cgpa": res.cgpa,
            "status": res.overall_status,
            "details": details_list
        })
    
    return jsonify({"has_data": False, "message": f"No published data found for Semester {sem}."})

# ─────────────────────────────────────────────────────────
#  API: FETCH BACKLOGS (WITH OPTIONAL SEMESTER FILTER)
# ─────────────────────────────────────────────────────────
@app.route("/api/student/backlogs", methods=["GET"])
def get_backlogs():
    student = get_logged_student()
    if not student:
        return jsonify({"error": "Unauthorized"}), 401
    
    sem = request.args.get('semester')
    
    query = db.session.query(Backlog, Subject).join(Subject, Backlog.subject_id == Subject.subject_id)\
                      .filter(Backlog.student_id == student.student_id, Backlog.status == 'ACTIVE')
    
    if sem and sem != "all":
        query = query.filter(Subject.semester == int(sem))
        
    backlog_records = query.all()
    
    output = []
    for backlog, subject in backlog_records:
        output.append({
            "subject_code": subject.subject_code,
            "subject_name": subject.subject_name,
            "semester": subject.semester,
            "academic_year": backlog.academic_year
        })
        
    return jsonify({"backlogs": output})

# ─────────────────────────────────────────────────────────
#  POST ACTION: CHANGE PASSWORD
# ─────────────────────────────────────────────────────────
@app.route("/api/student/change_password", methods=["POST"])
def change_password():
    student = get_logged_student()
    if not student:
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.get_json()
    old_password = data.get("old_password")
    new_password = data.get("new_password")
    
    if not old_password or not new_password:
        return jsonify({"error": "Missing password parameters"}), 400
        
    # Standard security practice check against hashed values
    # Assuming standard application-level verification framework here:
    from werkzeug.security import check_password_hash, generate_password_hash
    
    if not check_password_hash(student.student_password, old_password):
        return jsonify({"error": "Incorrect current password"}), 400
        
    student.student_password = generate_password_hash(new_password)
    
    # Optional: Log the update event into AuditLog
    log = AuditLog(
        student_id=student.student_id,
        action=AuditLog.PASSWORD_CHANGED,
        entity='student',
        entity_id=student.student_id,
        created_at=datetime.datetime.now()
    )
    db.session.add(log)
    db.session.commit()
    
    return jsonify({"success": "Password updated successfully!"})

# ─────────────────────────────────────────────────────────
#  ROUTE: DOWNLOAD TRANSCRIPT PDF
# ─────────────────────────────────────────────────────────
@app.route("/student_dashboard/download_pdf", methods=["GET"])
def download_pdf():
    student = get_logged_student()
    if not student:
        return redirect(url_for("login"))
        
    sem = request.args.get('semester', type=int)
    if not sem:
        return "Missing Semester selection context", 400
        
    res = Result.query.filter_by(student_id=student.student_id, semester=sem, status='PUBLISHED').first()
    if not res:
        return f"No verified ledger records found to print for Semester {sem}", 404
        
    details = ResultDetail.query.filter_by(result_id=res.result_id).all()
    subject_rows = []
    for d in details:
        sub = Subject.query.get(d.subject_id)
        subject_rows.append({
            "code": sub.subject_code,
            "name": sub.subject_name,
            "credits": d.credits,
            "marks": d.marks,
            "grade": d.grade,
            "gp": d.grade_point,
            "weighted": d.credits * d.grade_point
        })
        
    # Render minimalist clean HTML layout specialized for PDF engine compiler conversion
    rendered_html = render_template("transcript_pdf_template.html", 
                                    student=student, 
                                    result=res, 
                                    subjects=subject_rows)
    
    # Naming convention configuration target format: name-rollnumber-section-sem.pdf
    safe_name = student.student_name.replace(" ", "_")
    section_label = student.section if student.section else "NA"
    filename = f"{safe_name}-{student.roll_no}-{section_label}-sem{sem}.pdf"
    file_path = os.path.join(REPORTS_DIR, filename)
    
    # PDF Compilation step using generic cross-platform pdfkit or xhtml2pdf pattern
    success = False
    try:
        import pdfkit
        pdfkit.from_string(rendered_html, file_path)
        success = True
    except Exception:
        try:
            from xhtml2pdf import pisa
            with open(file_path, "wb") as pdf_file:
                result = pisa.CreatePDF(rendered_html, dest=pdf_file)
                # pisa.CreatePDF returns an object with an 'err' attribute
                if hasattr(result, 'err') and result.err:
                    success = False
                else:
                    success = True
        except Exception:
            success = False

    if not success:
        # Fallback: save the rendered HTML so it can be converted externally
        html_fallback = f"{filename}.html"
        html_path = os.path.join(REPORTS_DIR, html_fallback)
        try:
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(rendered_html)
        except Exception:
            return jsonify({"error": "Failed to generate PDF and unable to save HTML fallback."}), 500

        return jsonify({
            "warning": "PDF engine not available; saved HTML fallback for manual conversion.",
            "html_fallback": html_fallback,
            "path": html_path
        }), 200

    from flask import send_from_directory
    return send_from_directory(REPORTS_DIR, filename, as_attachment=True)