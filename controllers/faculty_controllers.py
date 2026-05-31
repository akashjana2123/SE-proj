import datetime
from flask import current_app as app, render_template, request, jsonify, session, redirect, url_for
from models import db, Faculty, Student, Subject, Mark, Backlog, Result, AuditLog, faculty_subject_association
from sqlalchemy import func

# ─────────────────────────────────────────────────────────
#  FACULTY AUTHENTICATION DECORATOR GUARD
# ─────────────────────────────────────────────────────────
def get_logged_faculty():
    """Retrieves authenticated faculty context from session or returns None."""
    if "role" in session and session["role"] == "faculty" and "email" in session:
        return Faculty.query.filter_by(faculty_email=session.get("email")).first()
    return None


# ─────────────────────────────────────────────────────────
#  FACULTY BASE ROUTE
# ─────────────────────────────────────────────────────────
@app.route("/faculty_dashboard", methods=["GET"])
def faculty_dashboard():
    faculty = get_logged_faculty()
    if not faculty:
        return redirect(url_for("login"))
    return render_template("faculty.html")


# ─────────────────────────────────────────────────────────
#  API: LIVE TELEMETRY & METRICS
# ─────────────────────────────────────────────────────────
@app.route("/api/faculty/metrics", methods=["GET"])
def get_faculty_metrics():
    faculty = get_logged_faculty()
    if not faculty:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    # Total subjects assigned
    total_subjects = len(faculty.subjects)

    # Evaluations Logged (Total individual marks rows created by this teacher)
    evaluations_logged = Mark.query.filter_by(faculty_id=faculty.faculty_id).count()

    # Active Backlogs (Arrears currently outstanding in this faculty's subjects)
    assigned_sub_ids = [s.subject_id for s in faculty.subjects]
    active_backlogs = Backlog.query.filter(
        Backlog.subject_id.in_(assigned_sub_ids) if assigned_sub_ids else False,
        Backlog.status == "ACTIVE"
    ).count()

    return jsonify({
        "faculty_name": faculty.faculty_name,
        "faculty_email": faculty.faculty_email,
        "total_subjects": total_subjects,
        "evaluations_logged": evaluations_logged,
        "active_backlogs": active_backlogs
    })


# ─────────────────────────────────────────────────────────
#  API: 3-STEP GRADING ENGINE (ENTER / UPDATE MARKS)
# ─────────────────────────────────────────────────────────

@app.route("/api/faculty/subjects/fetch", methods=["GET"])
def faculty_fetch_assigned_subjects():
    """Step 1 helper: Fetches subjects mapped to this faculty."""
    faculty = get_logged_faculty()
    if not faculty:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    return jsonify([{
        "id": s.subject_id,
        "code": s.subject_code,
        "name": s.subject_name,
        "semester": s.semester,
        "branch": s.branch
    } for s in faculty.subjects])


@app.route("/api/faculty/marks/load_roster", methods=["POST"])
def faculty_load_student_roster():
    """Step 2 helper: Loads all target students for entry or modification."""
    faculty = get_logged_faculty()
    if not faculty:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    semester = int(data.get("semester"))
    subject_id = int(data.get("subject_id"))
    academic_year = data.get("academic_year", "2024-25")

    # Verify subject belongs to faculty
    subject = Subject.query.filter_by(subject_id=subject_id).first_or_404()
    if subject not in faculty.subjects:
        return jsonify({"success": False, "message": "Access to unassigned curriculum mapping denied."}), 403

    # Gather all students eligible for this subject/semester/branch map
    students = Student.query.filter_by(current_sem=semester, branch=subject.branch).all()

    roster = []
    for s in students:
        # Check if an entry already exists
        existing_mark = Mark.query.filter_by(
            student_id=s.student_id,
            subject_id=subject_id,
            semester=semester,
            academic_year=academic_year
        ).first()

        roster.append({
            "student_id": s.student_id,
            "roll_no": s.roll_no,
            "student_name": s.student_name,
            "max_marks": 100.0,
            "marks_obtained": existing_mark.marks_obtained if existing_mark else None,
            "status": "Entered" if existing_mark else "Pending"
        })

    return jsonify({
        "subject_code": subject.subject_code,
        "subject_name": subject.subject_name,
        "roster": roster
    })


@app.route("/api/faculty/marks/save", methods=["POST"])
def faculty_save_marks_ledger():
    """Step 3: Commits and updates grades. Automatically tracks/updates Backlogs."""
    faculty = get_logged_faculty()
    if not faculty:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    semester = int(data.get("semester"))
    subject_id = int(data.get("subject_id"))
    academic_year = data.get("academic_year", "2024-25")
    scores_list = data.get("scores", [])  # Array of objects: {"student_id": X, "marks_obtained": Y}

    committed_count = 0
    for entry in scores_list:
        student_id = int(entry.get("student_id"))
        marks_obtained = float(entry.get("marks_obtained"))

        # Validation Guardrail
        if not (0 <= marks_obtained <= 100):
            continue

        # Look for existing ledger row
        mark_obj = Mark.query.filter_by(
            student_id=student_id,
            subject_id=subject_id,
            semester=semester,
            academic_year=academic_year
        ).first()

        if mark_obj:
            mark_obj.marks_obtained = marks_obtained
            mark_obj.faculty_id = faculty.faculty_id
            mark_obj.updated_at = datetime.datetime.utcnow()
        else:
            mark_obj = Mark(
                student_id=student_id,
                subject_id=subject_id,
                faculty_id=faculty.faculty_id,
                marks_obtained=marks_obtained,
                max_marks=100.0,
                semester=semester,
                academic_year=academic_year
            )
            db.session.add(mark_obj)

        # ─────────────────────────────────────────────────────────
        #  AUTOMATIC BACKLOG PIPELINE MANAGED HERE (Pass Limit: 40)
        # ─────────────────────────────────────────────────────────
        backlog_obj = Backlog.query.filter_by(
            student_id=student_id,
            subject_id=subject_id,
            academic_year=academic_year
        ).first()

        if marks_obtained < 40.0:
            # Student failed: Auto-generate active backlog entry if missing
            if not backlog_obj:
                new_backlog = Backlog(
                    student_id=student_id,
                    subject_id=subject_id,
                    faculty_id=faculty.faculty_id,
                    academic_year=academic_year,
                    status="ACTIVE"
                )
                db.session.add(new_backlog)
            else:
                backlog_obj.status = "ACTIVE"  # Re-flag if set to cleared previously
        else:
            # Student passed: Auto-clear active backlog records gracefully
            if backlog_obj and backlog_obj.status == "ACTIVE":
                backlog_obj.status = "CLEARED"

        committed_count += 1

    # Log operational transaction to global logs
    log = AuditLog(
        faculty_id=faculty.faculty_id,
        action="MARKS_SAVED",
        entity="mark",
        meta=f"Saved {committed_count} student grade entries for Subject ID {subject_id} (Sem {semester})"
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({"success": True, "message": f"Successfully processed and synchronized {committed_count} ledger records."})


# ─────────────────────────────────────────────────────────
#  API: AUTOMATED ARREARS & DEFICIT PORTFOLIOS
# ─────────────────────────────────────────────────────────
@app.route("/api/faculty/backlogs/view", methods=["GET"])
def faculty_view_backlogs():
    """Fetches list of students with failed grades in this instructor's subjects."""
    faculty = get_logged_faculty()
    if not faculty:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    assigned_sub_ids = [s.subject_id for s in faculty.subjects]
    if not assigned_sub_ids:
        return jsonify([])

    # Purely read-only automated pipeline tracking ACTIVE backlogs
    backlogs = db.session.query(Backlog, Student, Subject).\
        join(Student, Backlog.student_id == Student.student_id).\
        join(Subject, Backlog.subject_id == Subject.subject_id).\
        filter(Backlog.subject_id.in_(assigned_sub_ids), Backlog.status == "ACTIVE").all()

    return jsonify([{
        "backlog_id": b.Backlog.backlog_id,
        "student_name": b.Student.student_name,
        "roll_no": b.Student.roll_no,
        "subject_code": b.Subject.subject_code,
        "subject_name": b.Subject.subject_name,
        "academic_year": b.Backlog.academic_year,
        "status": b.Backlog.status
    } for b in backlogs])


# ─────────────────────────────────────────────────────────
#  API: ACCOUNT CREDENTIAL OVERRIDES
# ─────────────────────────────────────────────────────────
@app.route("/api/faculty/change_password", methods=["POST"])
def faculty_change_password():
    """Secured channel mutation allowing users to update their credentials."""
    faculty = get_logged_faculty()
    if not faculty:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    new_password = data.get("new_password")

    if not new_password or len(new_password) < 8:
        return jsonify({"success": False, "message": "Validation Failure: Password string length must be >= 8 elements."}), 400

    faculty.faculty_password = new_password  # Store hash directly or match your encryption schemes
    
    log = AuditLog(
        faculty_id=faculty.faculty_id,
        action="PASSWORD_CHANGED",
        entity="faculty",
        entity_id=faculty.faculty_id,
        meta="Faculty user successfully reset account authentication credential."
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({"success": True, "message": "Access security credentials updated successfully."})