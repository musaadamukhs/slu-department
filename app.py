from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
import hashlib
from functools import wraps

app = Flask(__name__)
app.secret_key = 'slu_agric_dept_secret_2025'

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

# ============================================
# MySQL Configuration
# ============================================
import os

app.config['MYSQL_HOST'] = os.environ.get('MYSQL_HOST', 'localhost')
app.config['MYSQL_PORT'] = int(os.environ.get('MYSQL_PORT', 3306))
app.config['MYSQL_USER'] = os.environ.get('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.environ.get('MYSQL_PASSWORD', '')
app.config['MYSQL_DB'] = os.environ.get('MYSQL_DB', 'slu_agric')
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
app.config['MYSQL_SSL_CA'] = os.environ.get('MYSQL_SSL_CA', None)

mysql = MySQL(app)

# ============================================
# LOGIN REQUIRED DECORATOR
# This protects any page that needs login
# If user is not logged in, sends them to login page
# ============================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            flash('Please login to access the admin panel', 'warning')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


# ============================================
# PUBLIC ROUTES
# ============================================

@app.route('/')
def home():
    cur = mysql.connection.cursor()

    # Get latest announcements for homepage
    cur.execute("""
        SELECT * FROM announcements
        WHERE expires_at IS NULL OR expires_at >= CURDATE()
        ORDER BY is_pinned DESC, created_at DESC
        LIMIT 3
    """)
    announcements = cur.fetchall()

    # Get stats for homepage
    cur.execute("SELECT COUNT(*) as count FROM staff WHERE is_active = TRUE")
    staff_count = cur.fetchone()['count']

    cur.execute("SELECT COUNT(*) as count FROM courses WHERE is_active = TRUE")
    course_count = cur.fetchone()['count']

    cur.execute("SELECT COUNT(*) as count FROM materials")
    material_count = cur.fetchone()['count']

    cur.close()

    return render_template('home.html',
        announcements=announcements,
        staff_count=staff_count,
        course_count=course_count,
        material_count=material_count
    )

@app.route('/staff')
def staff_directory():
    cur = mysql.connection.cursor()

    cur.execute("""
        SELECT * FROM staff
        WHERE is_hod = TRUE AND is_active = TRUE
    """)
    hod = cur.fetchone()

    cur.execute("""
        SELECT * FROM staff
        WHERE is_hod = FALSE AND is_active = TRUE
        ORDER BY staff_rank, full_name
    """)
    staff_list = cur.fetchall()
    cur.close()

    return render_template('staff.html', hod=hod, staff_list=staff_list)


@app.route('/courseware')
def courseware():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT c.*, s.full_name as lecturer_name,
        COUNT(m.id) as material_count
        FROM courses c
        LEFT JOIN staff s ON c.staff_id = s.id
        LEFT JOIN materials m ON m.course_id = c.id
        WHERE c.is_active = TRUE
        GROUP BY c.id
        ORDER BY c.level, c.semester
    """)
    courses = cur.fetchall()
    cur.close()
    return render_template('courseware.html', courses=courses)


# ============================================
# ADMIN ROUTES
# ============================================

@app.route('/admin')
def admin_redirect():
    return redirect(url_for('admin_login'))


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    # If already logged in, go straight to dashboard
    if 'admin_logged_in' in session:
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()

        # Hash the entered password to compare with database
        password_hashed = hashlib.sha256(password.encode()).hexdigest()

        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT * FROM admin_users 
            WHERE username = %s AND password_hash = %s
        """, (username, password_hashed))
        admin = cur.fetchone()
        cur.close()

        if admin:
            # Login successful — save to session
            session['admin_logged_in'] = True
            session['admin_username'] = admin['username']
            session['admin_name'] = admin['full_name']
            session['admin_role'] = admin['role']
            flash('Welcome back, ' + admin['full_name'] + '!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid username or password. Please try again.', 'danger')

    return render_template('admin/login.html')


@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    cur = mysql.connection.cursor()

    # Get counts for dashboard stats
    cur.execute("SELECT COUNT(*) as count FROM staff WHERE is_active = TRUE")
    staff_count = cur.fetchone()['count']

    cur.execute("SELECT COUNT(*) as count FROM courses WHERE is_active = TRUE")
    course_count = cur.fetchone()['count']

    cur.execute("SELECT COUNT(*) as count FROM materials")
    material_count = cur.fetchone()['count']

    cur.execute("SELECT COUNT(*) as count FROM announcements")
    announcement_count = cur.fetchone()['count']

    # Get recent staff
    cur.execute("""
        SELECT * FROM staff 
        ORDER BY created_at DESC 
        LIMIT 5
    """)
    recent_staff = cur.fetchall()

    cur.close()

    return render_template('admin/dashboard.html',
        staff_count=staff_count,
        course_count=course_count,
        material_count=material_count,
        announcement_count=announcement_count,
        recent_staff=recent_staff
    )


@app.route('/admin/logout')
def admin_logout():
    session.clear()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('admin_login'))
# ============================================
# MANAGE STAFF ROUTES
# ============================================

@app.route('/admin/staff')
@login_required
def admin_staff():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM staff ORDER BY staff_rank, full_name")
    staff_list = cur.fetchall()
    cur.close()
    return render_template('admin/staff.html', staff_list=staff_list)


@app.route('/admin/staff/add', methods=['GET', 'POST'])
@login_required
def admin_add_staff():
    if request.method == 'POST':
        full_name    = request.form['full_name'].strip()
        title        = request.form['title'].strip()
        staff_rank   = request.form['staff_rank'].strip()
        specialization = request.form['specialization'].strip()
        email        = request.form['email'].strip()
        phone        = request.form['phone'].strip()
        bio          = request.form['bio'].strip()
        is_hod       = 1 if 'is_hod' in request.form else 0

        cur = mysql.connection.cursor()

        # If this person is HOD, remove HOD from anyone else first
        if is_hod:
            cur.execute("UPDATE staff SET is_hod = FALSE")

        cur.execute("""
            INSERT INTO staff 
            (full_name, title, staff_rank, specialization, email, phone, bio, is_hod)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (full_name, title, staff_rank, specialization, email, phone, bio, is_hod))

        mysql.connection.commit()
        cur.close()

        flash(full_name + ' has been added successfully!', 'success')
        return redirect(url_for('admin_staff'))

    return render_template('admin/add_staff.html')


@app.route('/admin/staff/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def admin_edit_staff(id):
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        full_name      = request.form['full_name'].strip()
        title          = request.form['title'].strip()
        staff_rank     = request.form['staff_rank'].strip()
        specialization = request.form['specialization'].strip()
        email          = request.form['email'].strip()
        phone          = request.form['phone'].strip()
        bio            = request.form['bio'].strip()
        is_hod         = 1 if 'is_hod' in request.form else 0

        # If this person is HOD, remove HOD from anyone else first
        if is_hod:
            cur.execute("UPDATE staff SET is_hod = FALSE")

        cur.execute("""
            UPDATE staff SET
                full_name      = %s,
                title          = %s,
                staff_rank     = %s,
                specialization = %s,
                email          = %s,
                phone          = %s,
                bio            = %s,
                is_hod         = %s
            WHERE id = %s
        """, (full_name, title, staff_rank, specialization,
              email, phone, bio, is_hod, id))

        mysql.connection.commit()
        cur.close()

        flash('Staff member updated successfully!', 'success')
        return redirect(url_for('admin_staff'))

    # GET — load existing data
    cur.execute("SELECT * FROM staff WHERE id = %s", (id,))
    member = cur.fetchone()
    cur.close()

    return render_template('admin/edit_staff.html', member=member)


@app.route('/admin/staff/delete/<int:id>')
@login_required
def admin_delete_staff(id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT full_name FROM staff WHERE id = %s", (id,))
    member = cur.fetchone()
    cur.execute("DELETE FROM staff WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    flash(member['full_name'] + ' has been removed.', 'info')
    return redirect(url_for('admin_staff'))


# ============================================
# ANNOUNCEMENTS ROUTES
# ============================================

@app.route('/admin/announcements')
@login_required
def admin_announcements():
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM announcements ORDER BY created_at DESC")
    announcements = cur.fetchall()
    cur.close()
    return render_template('admin/announcements.html', announcements=announcements)


@app.route('/admin/announcements/add', methods=['GET', 'POST'])
@login_required
def admin_add_announcement():
    if request.method == 'POST':
        title     = request.form['title'].strip()
        content   = request.form['content'].strip()
        is_pinned = 1 if 'is_pinned' in request.form else 0
        expires_at = request.form['expires_at'] or None

        cur = mysql.connection.cursor()
        cur.execute("""
            INSERT INTO announcements (title, content, is_pinned, expires_at)
            VALUES (%s, %s, %s, %s)
        """, (title, content, is_pinned, expires_at))
        mysql.connection.commit()
        cur.close()

        flash('Announcement posted successfully!', 'success')
        return redirect(url_for('admin_announcements'))

    return render_template('admin/add_announcement.html')


@app.route('/admin/announcements/delete/<int:id>')
@login_required
def admin_delete_announcement(id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM announcements WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    flash('Announcement deleted.', 'info')
    return redirect(url_for('admin_announcements'))
# ============================================
# MANAGE COURSES ROUTES
# ============================================

@app.route('/admin/courses')
@login_required
def admin_courses():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT c.*, s.full_name as lecturer_name 
        FROM courses c
        LEFT JOIN staff s ON c.staff_id = s.id
        ORDER BY c.level, c.semester
    """)
    courses = cur.fetchall()
    cur.close()
    return render_template('admin/courses.html', courses=courses)


@app.route('/admin/courses/add', methods=['GET', 'POST'])
@login_required
def admin_add_course():
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        course_code  = request.form['course_code'].strip()
        course_title = request.form['course_title'].strip()
        level        = request.form['level']
        semester     = request.form['semester']
        staff_id     = request.form['staff_id'] or None
        description  = request.form['description'].strip()

        cur.execute("""
            INSERT INTO courses 
            (course_code, course_title, level, semester, staff_id, description)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (course_code, course_title, level, semester, staff_id, description))

        mysql.connection.commit()
        cur.close()

        flash(course_code + ' — ' + course_title + ' added successfully!', 'success')
        return redirect(url_for('admin_courses'))

    # GET — load staff list for dropdown
    cur.execute("SELECT id, full_name, title FROM staff WHERE is_active = TRUE ORDER BY full_name")
    staff_list = cur.fetchall()
    cur.close()

    return render_template('admin/add_course.html', staff_list=staff_list)


@app.route('/admin/courses/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def admin_edit_course(id):
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        course_code  = request.form['course_code'].strip()
        course_title = request.form['course_title'].strip()
        level        = request.form['level']
        semester     = request.form['semester']
        staff_id     = request.form['staff_id'] or None
        description  = request.form['description'].strip()

        cur.execute("""
            UPDATE courses SET
                course_code  = %s,
                course_title = %s,
                level        = %s,
                semester     = %s,
                staff_id     = %s,
                description  = %s
            WHERE id = %s
        """, (course_code, course_title, level, semester, staff_id, description, id))

        mysql.connection.commit()
        cur.close()

        flash('Course updated successfully!', 'success')
        return redirect(url_for('admin_courses'))

    # GET — load existing course data
    cur.execute("SELECT * FROM courses WHERE id = %s", (id,))
    course = cur.fetchone()

    cur.execute("SELECT id, full_name, title FROM staff WHERE is_active = TRUE ORDER BY full_name")
    staff_list = cur.fetchall()
    cur.close()

    return render_template('admin/edit_course.html', course=course, staff_list=staff_list)


@app.route('/admin/courses/delete/<int:id>')
@login_required
def admin_delete_course(id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT course_code, course_title FROM courses WHERE id = %s", (id,))
    course = cur.fetchone()
    cur.execute("DELETE FROM courses WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    flash(course['course_code'] + ' has been deleted.', 'info')
    return redirect(url_for('admin_courses'))
# ============================================
# UPLOAD MATERIALS ROUTES
# ============================================

import os
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {'pdf', 'ppt', 'pptx', 'doc', 'docx', 'xls', 'xlsx'}
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/admin/materials')
@login_required
def admin_materials():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT m.*, c.course_code, c.course_title
        FROM materials m
        LEFT JOIN courses c ON m.course_id = c.id
        ORDER BY m.uploaded_at DESC
    """)
    materials = cur.fetchall()
    cur.close()
    return render_template('admin/materials.html', materials=materials)


@app.route('/admin/materials/upload', methods=['GET', 'POST'])
@login_required
def admin_upload_material():
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        course_id     = request.form['course_id']
        material_type = request.form['material_type']
        file          = request.files['file']

        if file and allowed_file(file.filename):
            # Make filename safe and unique
            filename = secure_filename(file.filename)
            unique_filename = str(course_id) + '_' + material_type + '_' + filename

            # Save file to uploads folder
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(save_path)

            # Save record to database
            cur.execute("""
                INSERT INTO materials 
                (course_id, material_type, file_name, file_path)
                VALUES (%s, %s, %s, %s)
            """, (course_id, material_type, filename, unique_filename))

            mysql.connection.commit()
            cur.close()

            flash('File uploaded successfully!', 'success')
            return redirect(url_for('admin_materials'))
        else:
            flash('Invalid file type. Only PDF, PPT, DOC, XLS allowed.', 'danger')

    # GET — load courses for dropdown
    cur.execute("""
        SELECT id, course_code, course_title, level 
        FROM courses 
        WHERE is_active = TRUE 
        ORDER BY level, course_code
    """)
    courses = cur.fetchall()
    cur.close()

    return render_template('admin/upload_material.html', courses=courses)


@app.route('/admin/materials/delete/<int:id>')
@login_required
def admin_delete_material(id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM materials WHERE id = %s", (id,))
    material = cur.fetchone()

    if material:
        # Delete file from disk
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], material['file_path'])
        if os.path.exists(file_path):
            os.remove(file_path)

        # Delete record from database
        cur.execute("DELETE FROM materials WHERE id = %s", (id,))
        mysql.connection.commit()
        flash('Material deleted successfully.', 'info')

    cur.close()
    return redirect(url_for('admin_materials'))


# Allow students to download files
@app.route('/download/<filename>')
def download_file(filename):
    from flask import send_from_directory
    # Increment download count
    cur = mysql.connection.cursor()
    cur.execute("""
        UPDATE materials SET download_count = download_count + 1 
        WHERE file_path = %s
    """, (filename,))
    mysql.connection.commit()
    cur.close()
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)
    # ============================================
# PUBLIC ANNOUNCEMENTS & CONTACT ROUTES
# ============================================

@app.route('/announcements')
def announcements():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT * FROM announcements
        WHERE expires_at IS NULL OR expires_at >= CURDATE()
        ORDER BY is_pinned DESC, created_at DESC
    """)
    announcements = cur.fetchall()
    cur.close()
    return render_template('announcements.html', announcements=announcements)


@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/courseware/<int:course_id>/materials')
def course_materials(course_id):
    cur = mysql.connection.cursor()

    # Get course details
    cur.execute("""
        SELECT c.*, s.full_name as lecturer_name
        FROM courses c
        LEFT JOIN staff s ON c.staff_id = s.id
        WHERE c.id = %s
    """, (course_id,))

    course = cur.fetchone()

    # Get all materials for this course
    cur.execute("""
        SELECT * FROM materials
        WHERE course_id = %s
        ORDER BY material_type, uploaded_at DESC
    """, (course_id,))
    materials = cur.fetchall()

    cur.close()
    return render_template('course_materials.html',
                           course=course, materials=materials)
if __name__ == '__main__':
    app.run(debug=True, port=3000)