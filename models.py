import datetime
from database import db
from sqlalchemy import Enum, Table
from sqlalchemy.sql import func


# ─────────────────────────────────────────────────────────
# ASSOCIATION TABLES  (Many-to-Many)
# ─────────────────────────────────────────────────────────

# Faculty ↔ Subject  (a faculty can teach many subjects,
#                     a subject can be taught by many faculty)
faculty_subject_association = Table(
    'faculty_subject_association',
    db.Model.metadata,
    db.Column('faculty_id',   db.Integer, db.ForeignKey('faculty.faculty_id'),   primary_key=True),
    db.Column('subject_id',   db.Integer, db.ForeignKey('subject.subject_id'),   primary_key=True)
)


# ─────────────────────────────────────────────────────────
# USER CREDENTIALS
# ─────────────────────────────────────────────────────────

class Admin(db.Model):
    __tablename__ = "admin"

    admin_id       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    admin_name     = db.Column(db.String,  nullable=False)
    admin_email    = db.Column(db.String,  nullable=False, unique=True)
    admin_password = db.Column(db.String,  nullable=False)   # bcrypt hash
    is_active      = db.Column(db.Boolean, nullable=False, default=True)
    date_created   = db.Column(db.Date,    nullable=False, default=func.current_date())

    # Relationships
    audit_logs = db.relationship('AuditLog', backref='admin', lazy=True,
                                  foreign_keys='AuditLog.admin_id')

    def __repr__(self):
        return f"<Admin {self.admin_name}>"


class Faculty(db.Model):
    __tablename__ = "faculty"

    faculty_id       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    faculty_name     = db.Column(db.String,  nullable=False)
    faculty_email    = db.Column(db.String,  nullable=False, unique=True)
    faculty_password = db.Column(db.String,  nullable=False)   # bcrypt hash
    department       = db.Column(db.String,  nullable=False)
    designation      = db.Column(db.String,  nullable=True)
    is_active        = db.Column(db.Boolean, nullable=False, default=True)
    date_created     = db.Column(db.Date,    nullable=False, default=func.current_date())

    # Relationships
    subjects = db.relationship('Subject', secondary=faculty_subject_association,
                                backref='faculty_members', lazy=True)
    marks    = db.relationship('Mark',    backref='faculty', lazy=True)
    backlogs = db.relationship('Backlog', backref='faculty', lazy=True)

    # Method to get all subjects assigned to this faculty
    def get_subjects(self):
        return self.subjects

    # Method to get all marks entered by this faculty
    def get_marks(self):
        return Mark.query.filter_by(faculty_id=self.faculty_id).all()

    # Method to get pending (incomplete) mark entries for a subject/semester
    def get_pending_marks(self, subject_id, semester, academic_year):
        entered = Mark.query.filter_by(
            subject_id=subject_id,
            semester=semester,
            academic_year=academic_year,
            faculty_id=self.faculty_id
        ).all()
        entered_ids = [m.student_id for m in entered]
        pending = Student.query.filter(
            Student.current_sem == semester,
            Student.student_id.notin_(entered_ids)
        ).all()
        return pending

    def __repr__(self):
        return f"<Faculty {self.faculty_name} – {self.department}>"


class Student(db.Model):
    __tablename__ = "student"

    student_id    = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_name  = db.Column(db.String,  nullable=False)
    student_email = db.Column(db.String,  nullable=False, unique=True)
    student_password = db.Column(db.String, nullable=False)  # bcrypt hash
    roll_no       = db.Column(db.String,  nullable=False, unique=True)
    branch        = db.Column(db.String,  nullable=False)
    current_sem   = db.Column(db.Integer, nullable=False)
    section       = db.Column(db.String(1), nullable=True)
    academic_year = db.Column(db.String,  nullable=False)    # e.g. "2024-25"
    is_active     = db.Column(db.Boolean, nullable=False, default=True)
    date_created  = db.Column(db.Date,    nullable=False, default=func.current_date())

    # Relationships
    marks    = db.relationship('Mark',    backref='student', lazy=True)
    backlogs = db.relationship('Backlog', backref='student', lazy=True)
    results  = db.relationship('Result',  backref='student', lazy=True)

    # Method to get published result for a semester
    def get_published_result(self, semester, academic_year):
        return Result.query.filter_by(
            student_id=self.student_id,
            semester=semester,
            academic_year=academic_year,
            status='PUBLISHED'
        ).first()

    # Method to get all active backlogs
    def get_active_backlogs(self):
        return Backlog.query.filter_by(
            student_id=self.student_id,
            status='ACTIVE'
        ).all()

    # Method to check if result is published
    def has_published_result(self, semester, academic_year):
        result = self.get_published_result(semester, academic_year)
        return result is not None

    def __repr__(self):
        return f"<Student {self.student_name} – {self.roll_no}>"


# ─────────────────────────────────────────────────────────
# SUBJECT
# ─────────────────────────────────────────────────────────

class Subject(db.Model):
    __tablename__ = "subject"

    subject_id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    subject_code = db.Column(db.String,  nullable=False, unique=True)
    subject_name = db.Column(db.String,  nullable=False)
    branch       = db.Column(db.String,  nullable=False)
    semester     = db.Column(db.Integer, nullable=False)
    credits      = db.Column(db.Integer, nullable=False)
    is_active    = db.Column(db.Boolean, nullable=False, default=True)

    # Relationships
    marks    = db.relationship('Mark',          backref='subject', lazy=True)
    backlogs = db.relationship('Backlog',        backref='subject', lazy=True)
    details  = db.relationship('ResultDetail',   backref='subject', lazy=True)

    # Method to get all marks for this subject in a semester
    def get_all_marks(self, semester, academic_year):
        return Mark.query.filter_by(
            subject_id=self.subject_id,
            semester=semester,
            academic_year=academic_year
        ).all()

    # Method to check if all students have marks entered
    def is_marks_complete(self, semester, academic_year, branch):
        students = Student.query.filter_by(
            current_sem=semester,
            branch=branch
        ).all()
        entered = Mark.query.filter_by(
            subject_id=self.subject_id,
            semester=semester,
            academic_year=academic_year
        ).count()
        return entered >= len(students)

    def __repr__(self):
        return f"<Subject {self.subject_code} – {self.subject_name}>"
    
    def get_assigned_faculty_names(self):
        """Returns a comma-separated string of faculty names assigned to this subject."""
        return ", ".join([f.faculty_name for f in self.faculty_members])


# ─────────────────────────────────────────────────────────
# MARKS
# ─────────────────────────────────────────────────────────

class Mark(db.Model):
    __tablename__ = "mark"

    mark_id        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id     = db.Column(db.Integer, db.ForeignKey('student.student_id'),   nullable=False)
    subject_id     = db.Column(db.Integer, db.ForeignKey('subject.subject_id'),   nullable=False)
    faculty_id     = db.Column(db.Integer, db.ForeignKey('faculty.faculty_id'),   nullable=False)
    marks_obtained = db.Column(db.Float,   nullable=False)
    max_marks      = db.Column(db.Float,   nullable=False, default=100.0)
    semester       = db.Column(db.Integer, nullable=False)
    academic_year  = db.Column(db.String,  nullable=False)   # e.g. "2024-25"
    created_at     = db.Column(db.DateTime, nullable=False, default=func.now())
    updated_at     = db.Column(db.DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Unique constraint — one mark per student per subject per semester per year
    __table_args__ = (
        db.UniqueConstraint('student_id', 'subject_id', 'semester', 'academic_year',
                            name='uq_mark_student_subject_sem_year'),
    )

    # Method to validate marks before saving
    def is_valid(self):
        return 0 <= self.marks_obtained <= self.max_marks

    # Method to get grade based on marks
    def get_grade(self):
        pct = (self.marks_obtained / self.max_marks) * 100
        if pct >= 90: return 'O'
        elif pct >= 80: return 'A+'
        elif pct >= 70: return 'A'
        elif pct >= 60: return 'B+'
        elif pct >= 50: return 'B'
        elif pct >= 40: return 'C'
        else: return 'F'

    # Method to get grade point
    def get_grade_point(self):
        grade_map = {'O': 10, 'A+': 9, 'A': 8, 'B+': 7, 'B': 6, 'C': 5, 'F': 0}
        return grade_map.get(self.get_grade(), 0)

    def __repr__(self):
        return f"<Mark student={self.student_id} subject={self.subject_id} marks={self.marks_obtained}>"


# ─────────────────────────────────────────────────────────
# BACKLOG
# ─────────────────────────────────────────────────────────

class Backlog(db.Model):
    __tablename__ = "backlog"

    backlog_id    = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id    = db.Column(db.Integer, db.ForeignKey('student.student_id'),  nullable=False)
    subject_id    = db.Column(db.Integer, db.ForeignKey('subject.subject_id'),  nullable=False)
    faculty_id    = db.Column(db.Integer, db.ForeignKey('faculty.faculty_id'),  nullable=False)
    academic_year = db.Column(db.String,  nullable=False)
    status        = db.Column(
        db.Enum('ACTIVE', 'CLEARED', name='backlog_status'),
        nullable=False, default='ACTIVE'
    )
    created_at    = db.Column(db.DateTime, nullable=False, default=func.now())

    # Unique constraint — one backlog per student per subject per year
    __table_args__ = (
        db.UniqueConstraint('student_id', 'subject_id', 'academic_year',
                            name='uq_backlog_student_subject_year'),
    )

    # Method to clear a backlog
    def clear_backlog(self):
        self.status = 'CLEARED'
        db.session.commit()

    # Method to check if backlog is active
    def is_active(self):
        return self.status == 'ACTIVE'

    def __repr__(self):
        return f"<Backlog student={self.student_id} subject={self.subject_id} status={self.status}>"


# ─────────────────────────────────────────────────────────
# RESULT  &  RESULT DETAIL
# ─────────────────────────────────────────────────────────

class Result(db.Model):
    __tablename__ = "result"

    result_id      = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id     = db.Column(db.Integer, db.ForeignKey('student.student_id'), nullable=False)
    semester       = db.Column(db.Integer, nullable=False)
    academic_year  = db.Column(db.String,  nullable=False)
    sgpa           = db.Column(db.Float,   nullable=True)
    cgpa           = db.Column(db.Float,   nullable=True)
    total_credits  = db.Column(db.Integer, nullable=True)
    earned_credits = db.Column(db.Integer, nullable=True)
    overall_status = db.Column(
        db.Enum('PASS', 'FAIL', name='result_overall_status'),
        nullable=True
    )
    status         = db.Column(
        db.Enum('DRAFT', 'PENDING_APPROVAL', 'PUBLISHED', name='result_status'),
        nullable=False, default='DRAFT'
    )
    generated_at   = db.Column(db.DateTime, nullable=False, default=func.now())
    published_at   = db.Column(db.DateTime, nullable=True)

    # Unique constraint — one result per student per semester per year
    __table_args__ = (
        db.UniqueConstraint('student_id', 'semester', 'academic_year',
                            name='uq_result_student_sem_year'),
    )

    # Relationships
    details = db.relationship('ResultDetail', backref='result',
                               lazy=True, cascade='all, delete-orphan')

    # Method to submit result for admin approval
    def submit_for_approval(self):
        if self.status == 'DRAFT':
            self.status = 'PENDING_APPROVAL'
            db.session.commit()

    # Method to publish result (admin only)
    def publish(self):
        if self.status == 'PENDING_APPROVAL':
            self.status = 'PUBLISHED'
            self.published_at = datetime.datetime.utcnow()
            db.session.commit()

    # Method to check if result is published
    def is_published(self):
        return self.status == 'PUBLISHED'

    # Method to get all subject-wise details
    def get_details(self):
        return ResultDetail.query.filter_by(result_id=self.result_id).all()

    def __repr__(self):
        return f"<Result student={self.student_id} sem={self.semester} status={self.status}>"


class ResultDetail(db.Model):
    __tablename__ = "result_detail"

    detail_id   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    result_id   = db.Column(db.Integer, db.ForeignKey('result.result_id'),   nullable=False)
    subject_id  = db.Column(db.Integer, db.ForeignKey('subject.subject_id'), nullable=False)
    marks       = db.Column(db.Float,   nullable=True)
    grade       = db.Column(db.String(3), nullable=True)    # O, A+, A, B+, B, C, F
    grade_point = db.Column(db.Float,   nullable=True)
    credits     = db.Column(db.Integer, nullable=True)
    is_pass     = db.Column(db.Boolean, nullable=True)

    def __repr__(self):
        return f"<ResultDetail result={self.result_id} subject={self.subject_id} grade={self.grade}>"


# ─────────────────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────────────────

class AuditLog(db.Model):
    __tablename__ = "audit_log"

    log_id     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    admin_id   = db.Column(db.Integer, db.ForeignKey('admin.admin_id'),     nullable=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey('faculty.faculty_id'), nullable=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.student_id'), nullable=True)
    action     = db.Column(db.String,  nullable=False)   # e.g. 'MARKS_SAVED'
    entity     = db.Column(db.String,  nullable=True)    # e.g. 'mark'
    entity_id  = db.Column(db.Integer, nullable=True)
    meta       = db.Column(db.Text,    nullable=True)    # JSON string
    ip_address = db.Column(db.String,  nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=func.now())

    # Action constants
    LOGIN_SUCCESS       = 'LOGIN_SUCCESS'
    LOGIN_FAILED        = 'LOGIN_FAILED'
    ACCOUNT_LOCKED      = 'ACCOUNT_LOCKED'
    PASSWORD_CHANGED    = 'PASSWORD_CHANGED'
    MARKS_SAVED         = 'MARKS_SAVED'
    BACKLOG_ADDED       = 'BACKLOG_ADDED'
    BACKLOG_CLEARED     = 'BACKLOG_CLEARED'
    RESULT_GENERATED    = 'RESULT_GENERATED'
    RESULT_SUBMITTED    = 'RESULT_SUBMITTED'
    RESULT_PUBLISHED    = 'RESULT_PUBLISHED'
    FACULTY_CREATED     = 'FACULTY_CREATED'
    STUDENT_DELETED     = 'STUDENT_DELETED'

    def __repr__(self):
        return f"<AuditLog action={self.action} entity={self.entity} at={self.created_at}>"
