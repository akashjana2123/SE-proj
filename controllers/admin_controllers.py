import datetime
from flask import current_app as app, render_template, request, jsonify, session, redirect, url_for
from models import db, Admin, Faculty, Student, Subject, Mark, Result, ResultDetail, AuditLog, faculty_subject_association
from sqlalchemy import func

# ─────────────────────────────────────────────────────────
#  AUTHENTICATION GUARD
# ─────────────────────────────────────────────────────────
def get_logged_admin():
    """Retrieves authenticated admin context from DB or falls back gracefully."""
    if "role" in session and session["role"] == "admin":
        admin_obj = Admin.query.filter_by(admin_email=session.get("email")).first()
        if admin_obj:
            return admin_obj


# ─────────────────────────────────────────────────────────
#  BASE ENTRY POINT
# ─────────────────────────────────────────────────────────
# In controllers/admin_controllers.py
@app.route("/admin_dashboard", methods=["GET"])
def admin_dashboard():
    admin = get_logged_admin()
    if not admin:
        return redirect(url_for("login"))
    return render_template("admin.html")


# ─────────────────────────────────────────────────────────
#  API: LIVE METRICS & RECENT TIMELINE ACTIVITY
# ─────────────────────────────────────────────────────────
@app.route("/api/admin/metrics", methods=["GET"])
def get_dashboard_metrics():
    admin = get_logged_admin()
    
    total_students = Student.query.count()
    total_faculty = Faculty.query.count()
    total_subjects = Subject.query.count()
    published_count = Result.query.filter_by(status="PUBLISHED").count()
    pending_count = Result.query.filter_by(status="PENDING_APPROVAL").count()
    draft_count = Result.query.filter_by(status="DRAFT").count()

    semesters = [1, 2, 3, 4, 5, 6, 7, 8]
    sem_matrix = []
    
    for sem in semesters:
        pub = Result.query.filter_by(semester=sem, status="PUBLISHED").count()
        pnd = Result.query.filter_by(semester=sem, status="PENDING_APPROVAL").count()
        drf = Result.query.filter_by(semester=sem, status="DRAFT").count()
        
        sub_count = Subject.query.filter_by(semester=sem).count()
        inc = 0
        
        if sub_count > 0:
            # FIXED: Optimized to calculate missing counts using a single grouped aggregate query
            incomplete_query = db.session.query(Mark.student_id).\
                join(Student, Mark.student_id == Student.student_id).\
                filter(Student.current_sem == sem, Mark.semester == sem).\
                group_by(Mark.student_id).\
                having(func.count(Mark.mark_id) < sub_count).all()
            
            # Count students with completely zero marks entries logged as well
            total_sem_students = Student.query.filter_by(current_sem=sem).count()
            students_with_some_marks = db.session.query(func.count(func.distinct(Mark.student_id))).\
                join(Student, Mark.student_id == Student.student_id).\
                filter(Student.current_sem == sem, Mark.semester == sem).scalar() or 0
                
            inc = len(incomplete_query) + (total_sem_students - students_with_some_marks)
        
        if pub > 0 or pnd > 0 or drf > 0 or inc > 0:
            sem_matrix.append({"sem": sem, "published": pub, "pending": pnd, "draft": drf, "incomplete": inc})

    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(7).all()
    recent_activities = []
    for log in logs:
        time_str = log.created_at.strftime("%I:%M %p") if log.created_at.date() == datetime.date.today() else log.created_at.strftime("%b %d")
        icon = "🟢" if "SAVE" in log.action or "CREATE" in log.action else "⚙️" if "RESULT" in log.action else "🔑" if "PASSWORD" in log.action else "👤"
        recent_activities.append({"desc": log.action.replace("_", " ").title(), "meta": log.meta or log.entity or "System", "time": time_str, "icon": icon})

    if not recent_activities:
        recent_activities = [
            {"desc": "System Pipeline Dynamic Check", "meta": "Admin Engine Connected", "time": "Just Now", "icon": "🟢"},
            {"desc": "Database Sync Validated", "meta": "SQLAlchemy Registry Live", "time": "1 Hour Ago", "icon": "⚙️"}
        ]

    return jsonify({
        "admin_name": admin.admin_name,
        "admin_email": admin.admin_email,
        "total_students": total_students,
        "total_faculty": total_faculty,
        "total_subjects": total_subjects,
        "published_count": published_count,
        "pending_count": pending_count,
        "draft_count": draft_count,
        "sem_matrix": sem_matrix,
        "recent_activities": recent_activities
    })


# ─────────────────────────────────────────────────────────
#  API: CRUDS MANAGEMENT ENGINE (FACULTY)
# ─────────────────────────────────────────────────────────
@app.route("/api/admin/faculty", methods=["GET", "POST"])
def api_faculty_root():
    if request.method == "POST":
        data = request.get_json() or {}
        # In controllers/admin_controllers.py inside api_faculty_root()
        new_f = Faculty(
            faculty_name=data.get("name"), 
            faculty_email=data.get("email"),
            faculty_password=data.get("password", "demo123"), # Match your login testing credentials
            department=data.get("department"), 
            designation=data.get("designation", "Assistant Professor"),
            is_active=bool(data.get("is_active", True))
        )
        db.session.add(new_f)
        db.session.flush() # FIXED: Generates ID prior to association mappings
        
        sub_ids = data.get("subjects", [])
        if sub_ids:
            subs = Subject.query.filter(Subject.subject_id.in_(sub_ids)).all()
            new_f.subjects.extend(subs)

        db.session.commit()
        return jsonify({"success": True, "message": "Faculty registered successfully."})

    faculties = Faculty.query.all()
    return jsonify([{
        "id": f.faculty_id,
        "name": f.faculty_name,
        "email": f.faculty_email,
        "department": f.department,
        "designation": f.designation,
        "is_active": f.is_active,
        "subjects": [{"id": s.subject_id, "name": s.subject_name} for s in f.subjects]
    } for f in faculties])


@app.route("/api/admin/faculty/<int:fid>", methods=["PUT", "DELETE"])
def api_faculty_mutation(fid):
    faculty_obj = Faculty.query.get_or_404(fid) # FIXED: changed from get_or_400
    if request.method == "DELETE":
        faculty_obj.subjects.clear() # Clear out association tables link safely
        db.session.delete(faculty_obj)
        db.session.commit()
        return jsonify({"success": True, "message": "Faculty record cleanly purged."})
    
    data = request.get_json() or {}
    faculty_obj.faculty_name = data.get("name", faculty_obj.faculty_name)
    faculty_obj.faculty_email = data.get("email", faculty_obj.faculty_email)
    faculty_obj.department = data.get("department", faculty_obj.department)
    faculty_obj.designation = data.get("designation", faculty_obj.designation)
    faculty_obj.is_active = bool(data.get("is_active", True))

    if "subjects" in data:
        faculty_obj.subjects.clear()
        subs = Subject.query.filter(Subject.subject_id.in_(data.get("subjects", []))).all()
        faculty_obj.subjects.extend(subs)

    db.session.commit()
    return jsonify({"success": True, "message": "Faculty data updated."})


# ─────────────────────────────────────────────────────────
#  API: CRUDS MANAGEMENT ENGINE (STUDENTS)
# ─────────────────────────────────────────────────────────
@app.route("/api/admin/students", methods=["GET", "POST"])
def api_students_root():
    if request.method == "POST":
        data = request.get_json() or {}
        new_s = Student(
            student_name=data.get("name"), student_email=data.get("email"),
            student_password="student_secure_hashed_pass", roll_no=data.get("roll_no"),
            branch=data.get("branch"), current_sem=int(data.get("current_sem", 5)),
            academic_year=data.get("academic_year", "2024-25"), is_active=bool(data.get("is_active", True))
        )
        db.session.add(new_s)
        db.session.commit()
        return jsonify({"success": True, "message": "Student successfully enrolled."})

    students = Student.query.all()
    return jsonify([{
        "id": s.student_id, "name": s.student_name, "email": s.student_email,
        "roll_no": s.roll_no, "branch": s.branch, "current_sem": s.current_sem,
        "academic_year": s.academic_year, "is_active": s.is_active
    } for s in students])


@app.route("/api/admin/students/<int:sid>", methods=["PUT", "DELETE"])
def api_student_mutation(sid):
    student_obj = Student.query.get_or_404(sid) # FIXED: changed from get_or_400
    if request.method == "DELETE":
        db.session.delete(student_obj)
        db.session.commit()
        return jsonify({"success": True, "message": "Student identity dropped from ledger."})
    
    data = request.get_json() or {}
    student_obj.student_name = data.get("name", student_obj.student_name)
    student_obj.student_email = data.get("email", student_obj.student_email)
    student_obj.roll_no = data.get("roll_no", student_obj.roll_no)
    student_obj.branch = data.get("branch", student_obj.branch)
    student_obj.current_sem = int(data.get("current_sem", student_obj.current_sem))
    student_obj.academic_year = data.get("academic_year", student_obj.academic_year)
    student_obj.is_active = bool(data.get("is_active", True))
    
    db.session.commit()
    return jsonify({"success": True, "message": "Student profile synchronized."})


# ─────────────────────────────────────────────────────────
#  API: CRUDS MANAGEMENT ENGINE (SUBJECTS)
# ─────────────────────────────────────────────────────────
@app.route("/api/admin/subjects", methods=["GET", "POST"])
def api_subjects_root():
    if request.method == "POST":
        data = request.get_json() or {}
        new_sub = Subject(
            subject_code=data.get("subject_code"), subject_name=data.get("subject_name"),
            branch=data.get("branch"), credits=int(data.get("credits", 4)),
            semester=int(data.get("semester", 5)), is_active=True
        )
        db.session.add(new_sub)
        db.session.commit()
        return jsonify({"success": True, "message": "Syllabus course mapped successfully."})

    subjects = Subject.query.all()
    return jsonify([{
        "id": s.subject_id, "subject_code": s.subject_code, "subject_name": s.subject_name,
        "branch": s.branch, "credits": s.credits, "semester": s.semester
    } for s in subjects])


@app.route("/api/admin/subjects/<int:sub_id>", methods=["PUT", "DELETE"])
def api_subject_mutation(sub_id):
    subject_obj = Subject.query.get_or_404(sub_id) # FIXED: changed from get_or_400
    if request.method == "DELETE":
        db.session.delete(subject_obj)
        db.session.commit()
        return jsonify({"success": True, "message": "Subject removed from active curriculum maps."})
    
    data = request.get_json() or {}
    subject_obj.subject_code = data.get("subject_code", subject_obj.subject_code)
    subject_obj.subject_name = data.get("subject_name", subject_obj.subject_name)
    subject_obj.branch = data.get("branch", subject_obj.branch)
    subject_obj.credits = int(data.get("credits", subject_obj.credits))
    subject_obj.semester = int(data.get("semester", subject_obj.semester))
    
    db.session.commit()
    return jsonify({"success": True, "message": "Subject parameters compiled cleanly."})


# ─────────────────────────────────────────────────────────
#  API: RESULT CALCULATION ENGINE WITH OPTIONAL SCHEMES
# ─────────────────────────────────────────────────────────
@app.route("/api/admin/generate_result/preview", methods=["GET"])
def api_generate_preview():
    sem = request.args.get("semester", 5, type=int)
    year = request.args.get("academic_year", "2024-25")
    branch = request.args.get("branch", "ALL")
    system_type = request.args.get("grading_system", "gpa")

    s_query = Student.query.filter_by(current_sem=sem)
    if branch != "ALL":
        s_query = s_query.filter_by(branch=branch)
    students = s_query.all()

    sub_query = Subject.query.filter_by(semester=sem)
    if branch != "ALL":
        sub_query = sub_query.filter_by(branch=branch)
    subjects = sub_query.all()

    pending_logs = []
    output_rows = []
    total_credits = sum(s.credits for s in subjects)

    for st in students:
        marks_profile = {}
        is_complete = True
        weighted_gp_sum = 0.0
        obtained_marks_sum = 0.0
        max_marks_sum = 0.0

        for sub in subjects:
            m = Mark.query.filter_by(student_id=st.student_id, subject_id=sub.subject_id, semester=sem, academic_year=year).first()
            if not m:
                is_complete = False
                pending_logs.append(f"Missing Entry: {st.student_name} ({st.roll_no}) lacks marks entry in {sub.subject_name}.")
                marks_profile[sub.subject_code] = "--"
            else:
                marks_profile[sub.subject_code] = m.marks_obtained
                obtained_marks_sum += m.marks_obtained
                max_marks_sum += m.max_marks
                weighted_gp_sum += (m.get_grade_point() * sub.credits)

        if is_complete:
            if system_type == "percentage":
                final_score = round((obtained_marks_sum / max_marks_sum) * 100, 2) if max_marks_sum > 0 else 0.0
                metric_label = f"{final_score}%"
            else:
                final_score = round(weighted_gp_sum / total_credits, 2) if total_credits > 0 else 0.0
                metric_label = f"{final_score} SGPA"
            status_label = "READY"
        else:
            metric_label = "--"
            status_label = "INCOMPLETE"

        output_rows.append({
            "name": st.student_name, "roll": st.roll_no, "branch": st.branch,
            "subjects_breakdown": marks_profile, "score": metric_label, "status": status_label
        })

    return jsonify({
        "subjects_header": [s.subject_code for s in subjects],
        "pending_notifications": pending_logs,
        "generated_output": output_rows
    })


@app.route("/api/admin/generate_result/commit", methods=["POST"])
def api_generate_commit():
    data = request.get_json() or {}
    sem = int(data.get("semester", 5))
    year = data.get("academic_year", "2024-25")
    branch = data.get("branch", "ALL")

    s_query = Student.query.filter_by(current_sem=sem)
    if branch != "ALL": s_query = s_query.filter_by(branch=branch)
    students = s_query.all()
    subjects = Subject.query.filter_by(semester=sem).all()
    total_credits = sum(s.credits for s in subjects)

    commit_count = 0
    for st in students:
        marks_list = Mark.query.filter_by(student_id=st.student_id, semester=sem, academic_year=year).all()
        if len(marks_list) < len(subjects):
            continue 

        weighted_gp_sum = sum(m.get_grade_point() * m.subject.credits for m in marks_list)
        computed_sgpa = round(weighted_gp_sum / total_credits, 2) if total_credits > 0 else 0.0

        has_failed_course = any(m.get_grade() == 'F' for m in marks_list)
        overall_status = 'FAIL' if has_failed_course else 'PASS'

        res_obj = Result.query.filter_by(student_id=st.student_id, semester=sem, academic_year=year).first()
        if res_obj:
            res_obj.sgpa = computed_sgpa
            res_obj.overall_status = overall_status
            res_obj.status = "DRAFT"
        else:
            res_obj = Result(
                student_id=st.student_id, semester=sem, academic_year=year,
                sgpa=computed_sgpa, cgpa=computed_sgpa, total_credits=total_credits,
                overall_status=overall_status, status="DRAFT"
            )
            db.session.add(res_obj)
        commit_count += 1

    db.session.commit()
    return jsonify({"success": True, "message": f"Processed and saved {commit_count} student results as DRAFT."})


# ─────────────────────────────────────────────────────────
#  API: MANAGED RESULTS AUDIT OPERATIONS
# ─────────────────────────────────────────────────────────
@app.route("/api/admin/results/fetch", methods=["GET"])
def api_fetch_results_board():
    sem = request.args.get("semester")
    p_status = request.args.get("pass_fail")  
    r_status = request.args.get("status")     

    query = db.session.query(Result, Student).join(Student, Result.student_id == Student.student_id)
    
    if sem and sem != "ALL":
        query = query.filter(Result.semester == int(sem))
    if p_status and p_status != "ALL":
        query = query.filter(Result.overall_status == p_status)
    if r_status and r_status != "ALL":
        query = query.filter(Result.status == r_status)

    records = query.all()
    return jsonify([{
        "id": r.Result.result_id, "name": r.Student.student_name, "roll": r.Student.roll_no,
        "semester": r.Result.semester, "sgpa": r.Result.sgpa or "--",
        "overall_status": r.Result.overall_status or "PASS", "status": r.Result.status
    } for r in records])


@app.route("/api/admin/results/publish_single/<int:rid>", methods=["POST"])
def api_publish_single(rid):
    res = Result.query.get_or_404(rid) # FIXED: changed from get_or_400
    res.status = "PUBLISHED"
    res.published_at = datetime.datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True, "message": f"Transcript safely published to student view portal."})


@app.route("/api/admin/results/publish_all", methods=["POST"])
def api_publish_all_filtered():
    records = Result.query.filter(Result.status.in_(["DRAFT", "PENDING_APPROVAL"])).all()
    for r in records:
        r.status = "PUBLISHED"
        r.published_at = datetime.datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True, "message": f"Successfully published all {len(records)} transcripts across institutional records."})


# ─────────────────────────────────────────────────────────
#  API: CREDENTIAL ACCESS RECOVERY MANAGER
# ─────────────────────────────────────────────────────────
@app.route("/api/admin/get_users_by_filter", methods=["GET"])
def api_get_users_by_filter():
    target = request.args.get("target", "student") 
    sem = request.args.get("semester", "ALL")

    if target == "faculty":
        faculties = Faculty.query.all()
        return jsonify([{"id": f.faculty_id, "name": f.faculty_name, "meta": f.department} for f in faculties])
    
    s_query = Student.query
    if sem != "ALL":
        s_query = s_query.filter_by(current_sem=int(sem))
    students = s_query.all()
    return jsonify([{"id": s.student_id, "name": s.student_name, "meta": f"Roll: {s.roll_no} (Sem {s.current_sem})"} for s in students])


@app.route("/api/admin/change_password_execute", methods=["POST"])
def api_change_password_execute():
    data = request.get_json() or {}
    target = data.get("target")
    target_id = data.get("target_id")
    new_pwd = data.get("new_password")
    
    if not new_pwd or len(new_pwd) < 8:
        return jsonify({"success": False, "message": "Password string validation failure: Must be >= 8 symbols."}), 400

    if target == "faculty":
        user = Faculty.query.get(int(target_id))
    else:
        user = Student.query.get(int(target_id))

    if not user:
        return jsonify({"success": False, "message": "Target entity locator missing in current database context."}), 404

    # Note: If your production system uses Werkzeug or bcrypt hashing check, hash `new_pwd` here before storage!
    if target == "faculty":
        user.faculty_password = new_pwd
    else:
        user.student_password = new_pwd

    db.session.commit()
    return jsonify({"success": True, "message": f"Access credentials for '{user.student_name if target=='student' else user.faculty_name}' altered successfully."})