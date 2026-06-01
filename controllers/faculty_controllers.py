import datetime
import csv
import io
from flask import current_app as app, render_template, request, jsonify, session, redirect, url_for, Response
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

    # 1. Gather all assigned subjects structure contexts
    assigned_subjects = []
    unique_semesters = set()
    for s in faculty.subjects:
        unique_semesters.add(s.semester)
        students_count = Student.query.filter_by(branch=s.branch).count()
        entered_count = Mark.query.filter_by(subject_id=s.subject_id, semester=s.semester).count()
        is_complete = entered_count >= students_count if students_count > 0 else False
        
        assigned_subjects.append({
            "id": s.subject_id,
            "code": s.subject_code,
            "name": s.subject_name,
            "semester": s.semester,
            "branch": s.branch,
            "status": "Complete" if is_complete else "Incomplete"
        })

    # 2. Derive global pending entries calculations matrix metrics
    total_pending_entries = 0
    for subj in faculty.subjects:
        students = Student.query.filter_by(branch=subj.branch).all()
        for s in students:
            existing = Mark.query.filter_by(
                student_id=s.student_id,
                subject_id=subj.subject_id,
                semester=subj.semester
            ).first()
            if not existing:
                total_pending_entries += 1

    evaluations_logged = Mark.query.filter_by(faculty_id=faculty.faculty_id).count()
    assigned_sub_ids = [s.subject_id for s in faculty.subjects]
    active_backlogs = Backlog.query.filter(
        Backlog.subject_id.in_(assigned_sub_ids) if assigned_sub_ids else False,
        Backlog.status == "ACTIVE"
    ).count()

    metrics = {
        "total_subjects": len(faculty.subjects),
        "evaluations_logged": evaluations_logged,
        "active_backlogs": active_backlogs,
        "pending_marks_count": total_pending_entries
    }

    # 3. Server-side render direct into Jinja Context Space
    return render_template(
        "faculty.html",
        faculty=faculty,
        assigned_subjects=assigned_subjects,
        unique_semesters=sorted(list(unique_semesters)),
        metrics=metrics
    )


# ─────────────────────────────────────────────────────────
#  API: LIVE TELEMETRY & METRICS (WITH PENDING ESTIMATES)
# ─────────────────────────────────────────────────────────
@app.route("/api/faculty/metrics", methods=["GET"])
def get_faculty_metrics():
    faculty = get_logged_faculty()
    if not faculty:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    total_subjects = len(faculty.subjects)
    evaluations_logged = Mark.query.filter_by(faculty_id=faculty.faculty_id).count()

    assigned_sub_ids = [s.subject_id for s in faculty.subjects]
    active_backlogs = Backlog.query.filter(
        Backlog.subject_id.in_(assigned_sub_ids) if assigned_sub_ids else False,
        Backlog.status == "ACTIVE"
    ).count()

    # Calculate global pending count across all assigned mapped subjects
    total_pending_entries = 0
    for subj in faculty.subjects:
        students = Student.query.filter_by(branch=subj.branch).all()
        for s in students:
            existing = Mark.query.filter_by(
                student_id=s.student_id,
                subject_id=subj.subject_id,
                semester=subj.semester
            ).first()
            if not existing:
                total_pending_entries += 1

    return jsonify({
        "faculty_name": faculty.faculty_name,
        "faculty_email": faculty.faculty_email,
        "total_subjects": total_subjects,
        "evaluations_logged": evaluations_logged,
        "active_backlogs": active_backlogs,
        "pending_marks_count": total_pending_entries
    })


# ─────────────────────────────────────────────────────────
#  API: 3-STEP GRADING ENGINE (ENTER / UPDATE MARKS)
# ─────────────────────────────────────────────────────────

@app.route("/api/faculty/subjects/fetch", methods=["GET"])
def faculty_fetch_assigned_subjects():
    faculty = get_logged_faculty()
    if not faculty:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    payload = []
    for s in faculty.subjects:
        students_count = Student.query.filter_by(branch=s.branch).count()
        entered_count = Mark.query.filter_by(subject_id=s.subject_id, semester=s.semester).count()
        is_complete = entered_count >= students_count if students_count > 0 else False
        
        payload.append({
            "id": s.subject_id,
            "code": s.subject_code,
            "name": s.subject_name,
            "semester": s.semester,
            "branch": s.branch,
            "status": "Complete" if is_complete else "Incomplete"
        })
    return jsonify(payload)


@app.route("/api/faculty/marks/load_roster", methods=["POST"])
def faculty_load_student_roster():
    faculty = get_logged_faculty()
    if not faculty:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    subject_id = int(data.get("subject_id"))
    semester = data.get("semester")
    semester = int(semester) if semester else None
    academic_year = data.get("academic_year", "2024-25")

    subject = Subject.query.filter_by(subject_id=subject_id).first_or_404()
    if subject not in faculty.subjects:
        return jsonify({"success": False, "message": "Access to unassigned curriculum mapping denied."}), 403

    # Fallback to subject's native semester if parameter omitted by direct clickthroughs
    target_sem = semester if semester else subject.semester

    # Query matching students by branch node definition
    students = Student.query.filter_by(branch=subject.branch).all()

    roster = []
    for s in students:
        existing_mark = Mark.query.filter_by(
            student_id=s.student_id,
            subject_id=subject_id,
            semester=target_sem,
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
        "subject_id": subject.subject_id,
        "subject_code": subject.subject_code,
        "subject_name": subject.subject_name,
        "semester": target_sem,
        "academic_year": academic_year,
        "roster": roster
    })


import datetime
from flask import current_app as app, render_template, request, jsonify, session
from models import db, Faculty, Student, Subject, Mark, Backlog, Result, ResultDetail, AuditLog

@app.route("/api/faculty/marks/save", methods=["POST"])
def faculty_save_marks_ledger():
    faculty = get_logged_faculty()
    if not faculty:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    semester = int(data.get("semester"))
    subject_id = int(data.get("subject_id"))
    academic_year = data.get("academic_year", "2024-25")
    scores_list = data.get("scores", [])

    committed_count = 0
    affected_student_ids = set()

    for entry in scores_list:
        if entry.get("marks_obtained") is None or str(entry.get("marks_obtained")).strip() == "":
            continue
            
        student_id = int(entry.get("student_id"))
        marks_obtained = float(entry.get("marks_obtained"))

        if not (0 <= marks_obtained <= 100):
            continue

        affected_student_ids.add(student_id)

        # 1. Mutate individual Marks records
        mark_obj = Mark.query.filter_by(
            student_id=student_id, subject_id=subject_id,
            semester=semester, academic_year=academic_year
        ).first()

        if mark_obj:
            mark_obj.marks_obtained = marks_obtained
            mark_obj.faculty_id = faculty.faculty_id
            mark_obj.updated_at = datetime.datetime.utcnow()
        else:
            mark_obj = Mark(
                student_id=student_id, subject_id=subject_id, faculty_id=faculty.faculty_id,
                marks_obtained=marks_obtained, max_marks=100.0, semester=semester, academic_year=academic_year
            )
            db.session.add(mark_obj)

        # 2. Synchronize Backlogs state pipelines 
        backlog_obj = Backlog.query.filter_by(
            student_id=student_id, subject_id=subject_id, academic_year=academic_year
        ).first()

        if marks_obtained < 40.0:
            if not backlog_obj:
                new_backlog = Backlog(
                    student_id=student_id, subject_id=subject_id,
                    faculty_id=faculty.faculty_id, academic_year=academic_year, status="ACTIVE"
                )
                db.session.add(new_backlog)
            else:
                backlog_obj.status = "ACTIVE"
        else:
            if backlog_obj and backlog_obj.status == "ACTIVE":
                backlog_obj.status = "CLEARED"

        committed_count += 1

    # Flush point metrics down to allow correct average summary processing calculations
    db.session.flush()

    # 3. CRITICAL ATOMIC RECALCULATION: Aggregate data into Result and ResultDetail tables
    for s_id in affected_student_ids:
        all_sem_marks = Mark.query.filter_by(student_id=s_id, semester=semester, academic_year=academic_year).all()
        
        if not all_sem_marks:
            continue

        # Look up or initialize the student's semester Result summary record
        res_summary = Result.query.filter_by(student_id=s_id, semester=semester, academic_year=academic_year).first()
        if not res_summary:
            res_summary = Result(
                student_id=s_id, semester=semester, academic_year=academic_year,
                status="PUBLISHED", generated_at=datetime.datetime.utcnow()
            )
            db.session.add(res_summary)
            db.session.flush()

        total_credits = 0
        total_weighted_points = 0
        has_failed_course = False

        for m in all_sem_marks:
            subj = Subject.query.get(m.subject_id)
            if not subj:
                continue

            total_credits += subj.credits
            grade_points = m.get_grade_point()
            total_weighted_points += (subj.credits * grade_points)

            if m.marks_obtained < 40.0:
                has_failed_course = True

            # Match or update itemized tracking details rows
            r_detail = ResultDetail.query.filter_by(result_id=res_summary.result_id, subject_id=m.subject_id).first()
            if not r_detail:
                r_detail = ResultDetail(result_id=res_summary.result_id, subject_id=m.subject_id)
                db.session.add(r_detail)

            r_detail.marks = m.marks_obtained
            r_detail.grade = m.get_grade()
            r_detail.grade_point = float(grade_points)
            r_detail.credits = subj.credits
            r_detail.is_pass = (m.marks_obtained >= 40.0)

        # Compute averages 
        calculated_sgpa = (total_weighted_points / total_credits) if total_credits > 0 else 0.0
        res_summary.sgpa = calculated_sgpa
        res_summary.total_credits = total_credits
        res_summary.overall_status = "FAIL" if has_failed_course else "PASS"

        # Calculate Cumulative GPA (CGPA) across all completed semesters
        historical_results = Result.query.filter(Result.student_id == s_id, Result.sgpa.isnot(None)).all()
        if historical_results:
            res_summary.cgpa = sum([r.sgpa for r in historical_results]) / len(historical_results)
        else:
            res_summary.cgpa = calculated_sgpa

    # Commit the transaction safely to the database
    db.session.add(AuditLog(
        faculty_id=faculty.faculty_id, action="MARKS_SAVED", entity="mark",
        meta=f"Saved {committed_count} grading profiles and recompiled summary indexes."
    ))
    db.session.commit()

    return jsonify({"success": True, "message": f"Successfully synchronized {committed_count} records and updated student summary sheets."})


# ─────────────────────────────────────────────────────────
#  API: BACKLOGS LABELS MANAGEMENT BY FILTERS
# ─────────────────────────────────────────────────────────
@app.route("/api/faculty/backlogs/filtered", methods=["POST"])
def faculty_view_backlogs_filtered():
    faculty = get_logged_faculty()
    if not faculty:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    semester = data.get("semester")
    subject_id = data.get("subject_id")

    query = db.session.query(Backlog, Student, Subject).\
        join(Student, Backlog.student_id == Student.student_id).\
        join(Subject, Backlog.subject_id == Subject.subject_id).\
        filter(Backlog.faculty_id == faculty.faculty_id)

    if semester:
        query = query.filter(Subject.semester == int(semester))
    if subject_id:
        query = query.filter(Backlog.subject_id == int(subject_id))

    results = query.all()
    return jsonify([{
        "backlog_id": b.Backlog.backlog_id,
        "student_name": b.Student.student_name,
        "roll_no": b.Student.roll_no,
        "subject_code": b.Subject.subject_code,
        "subject_name": b.Subject.subject_name,
        "semester": b.Subject.semester,
        "academic_year": b.Backlog.academic_year,
        "status": b.Backlog.status
    } for b in results])


# ─────────────────────────────────────────────────────────
#  API: MANAGE RESULT REPORT MATRIX WITH DATA EXPORTS
# ─────────────────────────────────────────────────────────
@app.route("/api/faculty/results/report", methods=["GET"])
def faculty_get_results_report():
    faculty = get_logged_faculty()
    if not faculty:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    assigned_sub_ids = [s.subject_id for s in faculty.subjects]
    if not assigned_sub_ids:
        return jsonify([])

    records = db.session.query(Mark, Student, Subject).\
        join(Student, Mark.student_id == Student.student_id).\
        join(Subject, Mark.subject_id == Subject.subject_id).\
        filter(Mark.subject_id.in_(assigned_sub_ids)).all()

    return jsonify([{
        "roll_no": r.Student.roll_no,
        "student_name": r.Student.student_name,
        "subject_code": r.Subject.subject_code,
        "subject_name": r.Subject.subject_name,
        "semester": r.Mark.semester,
        "marks_obtained": r.Mark.marks_obtained,
        "grade": r.Mark.get_grade()
    } for r in records])


@app.route("/api/faculty/results/download", methods=["GET"])
def faculty_download_results_csv():
    faculty = get_logged_faculty()
    if not faculty:
        return "Unauthorized", 401

    assigned_sub_ids = [s.subject_id for s in faculty.subjects]
    records = db.session.query(Mark, Student, Subject).\
        join(Student, Mark.student_id == Student.student_id).\
        join(Subject, Mark.subject_id == Subject.subject_id).\
        filter(Mark.subject_id.in_(assigned_sub_ids)).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student Roll Code", "Legal Profile Name", "Subject Code", "Subject Name", "Semester", "Marks Obtained", "Grade Generated"])
    
    for r in records:
        writer.writerow([
            r.Student.roll_no,
            r.Student.student_name,
            r.Subject.subject_code,
            r.Subject.subject_name,
            r.Mark.semester,
            r.Mark.marks_obtained,
            r.Mark.get_grade()
        ])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=faculty_evaluation_report.csv"
    return response


# ─────────────────────────────────────────────────────────
#  API: ACCOUNT CREDENTIAL OVERRIDES
# ─────────────────────────────────────────────────────────
@app.route("/api/faculty/change_password", methods=["POST"])
def faculty_change_password():
    faculty = get_logged_faculty()
    if not faculty:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    new_password = data.get("new_password")

    if not new_password or len(new_password) < 8:
        return jsonify({"success": False, "message": "Validation Failure: Password string length must be >= 8 elements."}), 400

    faculty.faculty_password = new_password
    
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