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
app.config['MYSQL_PASSWORD'] = os.environ.get('MYSQL_PASSWORD', 'NewPassWordHere')
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

    # Get faculty info
    cur.execute("SELECT * FROM faculties LIMIT 1")
    faculty = cur.fetchone()

    # Get all active departments for the department switcher
    cur.execute("SELECT * FROM departments WHERE is_active = TRUE ORDER BY name")
    departments = cur.fetchall()

    # Get latest announcements for homepage (across all departments for now)
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
        faculty=faculty,
        departments=departments,
        announcements=announcements,
        staff_count=staff_count,
        course_count=course_count,
        material_count=material_count
    )
@app.route('/announcements')
def announcements():
    dept_slug = request.args.get('dept')

    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM departments WHERE is_active = TRUE ORDER BY name")
    departments = cur.fetchall()

    current_dept = None
    if dept_slug:
        cur.execute("SELECT * FROM departments WHERE slug = %s", (dept_slug,))
        current_dept = cur.fetchone()

    if current_dept:
        cur.execute("""
            SELECT * FROM announcements
            WHERE (expires_at IS NULL OR expires_at >= CURDATE())
            AND department_id = %s
            ORDER BY is_pinned DESC, created_at DESC
        """, (current_dept['id'],))
    else:
        cur.execute("""
            SELECT * FROM announcements
            WHERE expires_at IS NULL OR expires_at >= CURDATE()
            ORDER BY is_pinned DESC, created_at DESC
        """)

    announcements_list = cur.fetchall()
    cur.close()

    return render_template('announcements.html',
        announcements=announcements_list,
        departments=departments,
        current_dept=current_dept
    )
    
@app.route('/staff')
def staff_directory():
    dept_slug = request.args.get('dept')  # e.g. ?dept=agric-economics

    cur = mysql.connection.cursor()

    # Get all departments for the filter dropdown
    cur.execute("SELECT * FROM departments WHERE is_active = TRUE ORDER BY name")
    departments = cur.fetchall()

    current_dept = None
    if dept_slug:
        cur.execute("SELECT * FROM departments WHERE slug = %s", (dept_slug,))
        current_dept = cur.fetchone()

    # Build query based on whether a department filter is applied
    if current_dept:
        cur.execute("""
            SELECT * FROM staff
            WHERE is_hod = TRUE AND is_active = TRUE AND department_id = %s
        """, (current_dept['id'],))
        hod = cur.fetchone()

        cur.execute("""
            SELECT * FROM staff
            WHERE is_hod = FALSE AND is_active = TRUE AND department_id = %s
            ORDER BY staff_rank, full_name
        """, (current_dept['id'],))
        staff_list = cur.fetchall()
    else:
        cur.execute("SELECT * FROM staff WHERE is_hod = TRUE AND is_active = TRUE")
        hod = cur.fetchone()

        cur.execute("""
            SELECT * FROM staff
            WHERE is_hod = FALSE AND is_active = TRUE
            ORDER BY staff_rank, full_name
        """)
        staff_list = cur.fetchall()

    cur.close()

    return render_template('staff.html',
        hod=hod,
        staff_list=staff_list,
        departments=departments,
        current_dept=current_dept
    )


@app.route('/courseware')
def courseware():
    dept_slug = request.args.get('dept')

    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM departments WHERE is_active = TRUE ORDER BY name")
    departments = cur.fetchall()

    current_dept = None
    if dept_slug:
        cur.execute("SELECT * FROM departments WHERE slug = %s", (dept_slug,))
        current_dept = cur.fetchone()

    if current_dept:
        cur.execute("""
            SELECT c.*, s.full_name as lecturer_name,
            COUNT(m.id) as material_count
            FROM courses c
            LEFT JOIN staff s ON c.staff_id = s.id
            LEFT JOIN materials m ON m.course_id = c.id
            WHERE c.is_active = TRUE AND c.department_id = %s
            GROUP BY c.id
            ORDER BY c.level, c.semester
        """, (current_dept['id'],))
    else:
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

    return render_template('courseware.html',
        courses=courses,
        departments=departments,
        current_dept=current_dept
    )


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
        full_name = request.form.get('full_name', '').strip()
        title = request.form.get('title', '').strip()
        staff_rank = request.form.get('staff_rank', '').strip()
        specialization = request.form.get('specialization', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        bio = request.form.get('bio', '').strip()
        qualifications = request.form.get('qualifications', '').strip()
        research_interests = request.form.get('research_interests', '').strip()
        publications = request.form.get('publications', '').strip()
        office_location = request.form.get('office_location', '').strip()
        orcid = request.form.get('orcid', '').strip()
        is_hod = 1 if 'is_hod' in request.form else 0

        photo_filename = 'default.jpg'
        photo_file = request.files.get('photo')
        if photo_file and photo_file.filename and allowed_image(photo_file.filename):
            safe_name = secure_filename(photo_file.filename)
            photo_filename = f"staff_{full_name.replace(' ', '_')}_{safe_name}"
            photo_file.save(os.path.join(app.config['STAFF_PHOTO_FOLDER'], photo_filename))

        cur = mysql.connection.cursor()

        if is_hod:
            cur.execute("UPDATE staff SET is_hod = FALSE")

        cur.execute("""
            INSERT INTO staff 
            (full_name, title, staff_rank, specialization, email, phone, bio,
             qualifications, research_interests, publications, office_location, orcid, photo, is_hod)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (full_name, title, staff_rank, specialization, email, phone, bio,
              qualifications, research_interests, publications, office_location, orcid, photo_filename, is_hod))

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
        full_name = request.form['full_name'].strip()
        title = request.form['title'].strip()
        staff_rank = request.form['staff_rank'].strip()
        specialization = request.form['specialization'].strip()
        email = request.form['email'].strip()
        phone = request.form['phone'].strip()
        bio = request.form['bio'].strip()
        qualifications = request.form.get('qualifications', '').strip()
        research_interests = request.form.get('research_interests', '').strip()
        publications = request.form.get('publications', '').strip()
        office_location = request.form.get('office_location', '').strip()
        orcid = request.form.get('orcid', '').strip()
        is_hod = 1 if 'is_hod' in request.form else 0

        # If this person is HOD, remove HOD from anyone else first
        if is_hod:
            cur.execute("UPDATE staff SET is_hod = FALSE")

        cur.execute("""
            UPDATE staff SET
                full_name = %s,
                title = %s,
                staff_rank = %s,
                specialization = %s,
                email = %s,
                phone = %s,
                bio = %s,
                qualifications = %s,
                research_interests = %s,
                publications = %s,
                office_location = %s,
                orcid = %s,
                is_hod = %s
            WHERE id = %s
        """, (full_name, title, staff_rank, specialization,
              email, phone, bio, qualifications, research_interests,
              publications, office_location, orcid, is_hod, id))

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
LAB_UPLOAD_FOLDER = 'static/images/labs'
app.config['LAB_UPLOAD_FOLDER'] = LAB_UPLOAD_FOLDER
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
STAFF_PHOTO_FOLDER = 'static/images/staff'
app.config['STAFF_PHOTO_FOLDER'] = STAFF_PHOTO_FOLDER

def allowed_image(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

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
# ============================================
# ABOUT / MISSION & VISION ROUTE
# ============================================

@app.route('/about')
def about():
    dept_slug = request.args.get('dept')

    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM faculties LIMIT 1")
    faculty = cur.fetchone()

    cur.execute("SELECT * FROM departments WHERE is_active = TRUE ORDER BY name")
    departments = cur.fetchall()

    current_dept = None
    if dept_slug:
        cur.execute("SELECT * FROM departments WHERE slug = %s", (dept_slug,))
        current_dept = cur.fetchone()

    # Get HOD of the selected department (or overall) for the about page
    hod = None
    if current_dept:
        cur.execute("""
            SELECT * FROM staff
            WHERE is_hod = TRUE AND is_active = TRUE AND department_id = %s
        """, (current_dept['id'],))
        hod = cur.fetchone()

    cur.close()

    return render_template('about.html',
        faculty=faculty,
        departments=departments,
        current_dept=current_dept,
        hod=hod
    )
# ============================================
# STAFF PROFILE (PUBLIC VIEW + DOWNLOAD)
# ============================================

@app.route('/staff/<int:id>')
def staff_profile(id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT s.*, d.name as department_name, d.slug as department_slug
        FROM staff s
        LEFT JOIN departments d ON s.department_id = d.id
        WHERE s.id = %s AND s.is_active = TRUE
    """, (id,))
    member = cur.fetchone()

    courses_taught = []
    if member:
        cur.execute("""
            SELECT course_code, course_title, level, semester
            FROM courses WHERE staff_id = %s AND is_active = TRUE
            ORDER BY level
        """, (id,))
        courses_taught = cur.fetchall()

    cur.close()

    if not member:
        flash('Staff profile not found.', 'danger')
        return redirect(url_for('staff_directory'))

    return render_template('staff_profile.html', member=member, courses_taught=courses_taught)


@app.route('/staff/<int:id>/download')
def staff_download(id):
    from flask import Response
    from io import BytesIO
    from xhtml2pdf import pisa

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM staff WHERE id = %s", (id,))
    member = cur.fetchone()
    cur.close()

    if not member:
        flash('Staff profile not found.', 'danger')
        return redirect(url_for('staff_directory'))

    html = render_template('staff_cv_pdf.html', member=member)

    pdf_buffer = BytesIO()
    result = pisa.CreatePDF(src=html, dest=pdf_buffer)

    if result.err:
        flash('Could not generate PDF. Please try again later.', 'danger')
        return redirect(url_for('staff_profile', id=id))

    pdf_buffer.seek(0)
    filename = member['full_name'].replace(' ', '_').replace('.', '') + '_Profile.pdf'

    return Response(pdf_buffer.read(), mimetype='application/pdf', headers={
        'Content-Disposition': f'attachment; filename={filename}'
    })

    # ============================================
# PUBLIC LABORATORIES ROUTES
# ============================================

@app.route('/laboratories')
def laboratories():
    dept_slug = request.args.get('dept')

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM departments WHERE is_active = TRUE ORDER BY name")
    departments = cur.fetchall()

    current_dept = None
    if dept_slug:
        cur.execute("SELECT * FROM departments WHERE slug = %s", (dept_slug,))
        current_dept = cur.fetchone()

    if current_dept:
        cur.execute("""
            SELECT * FROM laboratories
            WHERE is_active = TRUE AND department_id = %s
            ORDER BY name
        """, (current_dept['id'],))
    else:
        cur.execute("SELECT * FROM laboratories WHERE is_active = TRUE ORDER BY name")

    labs = cur.fetchall()
    cur.close()

    return render_template('laboratories.html',
        labs=labs, departments=departments, current_dept=current_dept)


@app.route('/laboratories/<int:id>')
def laboratory_detail(id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT l.*, d.name as department_name
        FROM laboratories l
        LEFT JOIN departments d ON l.department_id = d.id
        WHERE l.id = %s
    """, (id,))
    lab = cur.fetchone()

    photos = []
    if lab:
        cur.execute("SELECT * FROM lab_photos WHERE lab_id = %s ORDER BY id", (id,))
        photos = cur.fetchall()

    cur.close()

    if not lab:
        flash('Laboratory not found.', 'danger')
        return redirect(url_for('laboratories'))

    return render_template('laboratory_detail.html', lab=lab, photos=photos)


# ============================================
# ADMIN LABORATORIES ROUTES
# ============================================

@app.route('/admin/laboratories')
@login_required
def admin_laboratories():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT l.*, d.name as department_name
        FROM laboratories l
        LEFT JOIN departments d ON l.department_id = d.id
        ORDER BY l.name
    """)
    labs = cur.fetchall()
    cur.close()
    return render_template('admin/laboratories.html', labs=labs)


@app.route('/admin/laboratories/add', methods=['GET', 'POST'])
@login_required
def admin_add_lab():
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        department_id = request.form['department_id']
        name = request.form['name'].strip()
        lab_type = request.form['lab_type'].strip()
        size_capacity = request.form['size_capacity'].strip()
        description = request.form['description'].strip()
        equipment = request.form['equipment'].strip()
        technologies = request.form['technologies'].strip()

        cur.execute("""
            INSERT INTO laboratories
            (department_id, name, lab_type, size_capacity, description, equipment, technologies)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (department_id, name, lab_type, size_capacity, description, equipment, technologies))
        mysql.connection.commit()
        new_id = cur.lastrowid
        cur.close()

        flash(name + ' added successfully! Now upload photos for it.', 'success')
        return redirect(url_for('admin_lab_photos', lab_id=new_id))

    cur.execute("SELECT id, name FROM departments WHERE is_active = TRUE ORDER BY name")
    departments = cur.fetchall()
    cur.close()

    return render_template('admin/add_lab.html', departments=departments)


@app.route('/admin/laboratories/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def admin_edit_lab(id):
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        department_id = request.form['department_id']
        name = request.form['name'].strip()
        lab_type = request.form['lab_type'].strip()
        size_capacity = request.form['size_capacity'].strip()
        description = request.form['description'].strip()
        equipment = request.form['equipment'].strip()
        technologies = request.form['technologies'].strip()

        cur.execute("""
            UPDATE laboratories SET
                department_id = %s, name = %s, lab_type = %s,
                size_capacity = %s, description = %s,
                equipment = %s, technologies = %s
            WHERE id = %s
        """, (department_id, name, lab_type, size_capacity,
              description, equipment, technologies, id))
        mysql.connection.commit()
        cur.close()

        flash('Laboratory updated successfully!', 'success')
        return redirect(url_for('admin_laboratories'))

    cur.execute("SELECT * FROM laboratories WHERE id = %s", (id,))
    lab = cur.fetchone()

    cur.execute("SELECT id, name FROM departments WHERE is_active = TRUE ORDER BY name")
    departments = cur.fetchall()
    cur.close()

    return render_template('admin/edit_lab.html', lab=lab, departments=departments)


@app.route('/admin/laboratories/delete/<int:id>')
@login_required
def admin_delete_lab(id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM lab_photos WHERE lab_id = %s", (id,))
    cur.execute("DELETE FROM laboratories WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    flash('Laboratory deleted.', 'info')
    return redirect(url_for('admin_laboratories'))


@app.route('/admin/laboratories/<int:lab_id>/photos', methods=['GET', 'POST'])
@login_required
def admin_lab_photos(lab_id):
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        file = request.files.get('photo')
        caption = request.form.get('caption', '').strip()

        if file and allowed_image(file.filename):
            filename = secure_filename(file.filename)
            unique_filename = f"lab{lab_id}_{filename}"
            save_path = os.path.join(app.config['LAB_UPLOAD_FOLDER'], unique_filename)
            file.save(save_path)

            cur.execute("""
                INSERT INTO lab_photos (lab_id, photo_path, caption)
                VALUES (%s, %s, %s)
            """, (lab_id, unique_filename, caption))
            mysql.connection.commit()

            # If this lab has no cover photo set yet, use this as cover
            cur.execute("SELECT cover_photo FROM laboratories WHERE id = %s", (lab_id,))
            current_cover = cur.fetchone()
            if current_cover and current_cover['cover_photo'] == 'default-lab.jpg':
                cur.execute("UPDATE laboratories SET cover_photo = %s WHERE id = %s",
                           (unique_filename, lab_id))
                mysql.connection.commit()

            flash('Photo uploaded successfully!', 'success')
        else:
            flash('Invalid file type. Only JPG, PNG, WEBP allowed.', 'danger')

        return redirect(url_for('admin_lab_photos', lab_id=lab_id))

    cur.execute("SELECT * FROM laboratories WHERE id = %s", (lab_id,))
    lab = cur.fetchone()

    cur.execute("SELECT * FROM lab_photos WHERE lab_id = %s ORDER BY id", (lab_id,))
    photos = cur.fetchall()
    cur.close()

    return render_template('admin/lab_photos.html', lab=lab, photos=photos)


@app.route('/admin/laboratories/photos/delete/<int:photo_id>/<int:lab_id>')
@login_required
def admin_delete_lab_photo(photo_id, lab_id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM lab_photos WHERE id = %s", (photo_id,))
    mysql.connection.commit()
    cur.close()
    flash('Photo deleted.', 'info')
    return redirect(url_for('admin_lab_photos', lab_id=lab_id))

# ============================================
# PUBLIC ROLES / OFFICERS ROUTE
# ============================================

@app.route('/officers')
def officers():
    dept_slug = request.args.get('dept')

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM departments WHERE is_active = TRUE ORDER BY name")
    departments = cur.fetchall()

    current_dept = None
    if dept_slug:
        cur.execute("SELECT * FROM departments WHERE slug = %s", (dept_slug,))
        current_dept = cur.fetchone()

    base_query = """
        SELECT sr.*, s.full_name, s.title, s.email, s.phone, s.photo,
               rt.name as role_name, d.name as department_name
        FROM staff_roles sr
        JOIN staff s ON sr.staff_id = s.id
        JOIN role_types rt ON sr.role_type_id = rt.id
        JOIN departments d ON sr.department_id = d.id
        WHERE sr.is_active = TRUE
    """

    if current_dept:
        cur.execute(base_query + " AND sr.department_id = %s ORDER BY rt.name, sr.level",
                   (current_dept['id'],))
    else:
        cur.execute(base_query + " ORDER BY d.name, rt.name, sr.level")

    roles = cur.fetchall()
    cur.close()

    return render_template('officers.html',
        roles=roles, departments=departments, current_dept=current_dept)


# ============================================
# ADMIN ROLES ROUTES
# ============================================

@app.route('/admin/roles')
@login_required
def admin_roles():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT sr.*, s.full_name, rt.name as role_name, d.name as department_name
        FROM staff_roles sr
        JOIN staff s ON sr.staff_id = s.id
        JOIN role_types rt ON sr.role_type_id = rt.id
        JOIN departments d ON sr.department_id = d.id
        ORDER BY sr.is_active DESC, d.name, rt.name
    """)
    roles = cur.fetchall()
    cur.close()
    return render_template('admin/roles.html', roles=roles)


@app.route('/admin/roles/add', methods=['GET', 'POST'])
@login_required
def admin_add_role():
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        role_type_id = request.form.get('role_type_id')
        department_id = request.form.get('department_id')
        level = request.form.get('level') or None
        academic_session = request.form.get('academic_session', '').strip()

        cur.execute("""
            INSERT INTO staff_roles (staff_id, role_type_id, department_id, level, academic_session)
            VALUES (%s, %s, %s, %s, %s)
        """, (staff_id, role_type_id, department_id, level, academic_session))
        mysql.connection.commit()
        cur.close()

        flash('Role assigned successfully!', 'success')
        return redirect(url_for('admin_roles'))

    cur.execute("SELECT id, full_name FROM staff WHERE is_active = TRUE ORDER BY full_name")
    staff_list = cur.fetchall()

    cur.execute("SELECT id, name FROM role_types ORDER BY name")
    role_types = cur.fetchall()

    cur.execute("SELECT id, name FROM departments WHERE is_active = TRUE ORDER BY name")
    departments = cur.fetchall()
    cur.close()

    return render_template('admin/add_role.html',
        staff_list=staff_list, role_types=role_types, departments=departments)


@app.route('/admin/roles/toggle/<int:id>')
@login_required
def admin_toggle_role(id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT is_active FROM staff_roles WHERE id = %s", (id,))
    current = cur.fetchone()
    new_status = not current['is_active']
    cur.execute("UPDATE staff_roles SET is_active = %s WHERE id = %s", (new_status, id))
    mysql.connection.commit()
    cur.close()
    flash('Role status updated.', 'success')
    return redirect(url_for('admin_roles'))


@app.route('/admin/roles/delete/<int:id>')
@login_required
def admin_delete_role(id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM staff_roles WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    flash('Role assignment removed.', 'info')
    return redirect(url_for('admin_roles'))
# ============================================
# PUBLIC GALLERY ROUTE
# ============================================

@app.route('/gallery')
def gallery():
    dept_slug = request.args.get('dept')

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM departments WHERE is_active = TRUE ORDER BY name")
    departments = cur.fetchall()

    current_dept = None
    if dept_slug:
        cur.execute("SELECT * FROM departments WHERE slug = %s", (dept_slug,))
        current_dept = cur.fetchone()

    if current_dept:
        cur.execute("SELECT * FROM gallery WHERE department_id = %s ORDER BY uploaded_at DESC",
                   (current_dept['id'],))
    else:
        cur.execute("SELECT * FROM gallery ORDER BY uploaded_at DESC")

    photos = cur.fetchall()
    cur.close()

    return render_template('gallery.html',
        photos=photos, departments=departments, current_dept=current_dept)


# ============================================
# ADMIN GALLERY ROUTES
# ============================================

@app.route('/admin/gallery')
@login_required
def admin_gallery():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT g.*, d.name as department_name
        FROM gallery g
        LEFT JOIN departments d ON g.department_id = d.id
        ORDER BY g.uploaded_at DESC
    """)
    photos = cur.fetchall()

    cur.execute("SELECT id, name FROM departments WHERE is_active = TRUE ORDER BY name")
    departments = cur.fetchall()
    cur.close()

    return render_template('admin/gallery.html', photos=photos, departments=departments)


@app.route('/admin/gallery/upload', methods=['POST'])
@login_required
def admin_upload_gallery_photo():
    department_id = request.form.get('department_id') or None
    title = request.form.get('title', '').strip()
    category = request.form.get('category', '').strip()
    file = request.files.get('photo')

    if file and file.filename and allowed_image(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = f"gallery_{filename}"
        cur = mysql.connection.cursor()
        # Ensure unique filename if collision
        save_path = os.path.join('static/images/gallery', unique_filename)
        counter = 1
        while os.path.exists(save_path):
            unique_filename = f"gallery_{counter}_{filename}"
            save_path = os.path.join('static/images/gallery', unique_filename)
            counter += 1
        file.save(save_path)

        cur.execute("""
            INSERT INTO gallery (department_id, title, category, photo_path)
            VALUES (%s, %s, %s, %s)
        """, (department_id, title, category, unique_filename))
        mysql.connection.commit()
        cur.close()
        flash('Photo added to gallery!', 'success')
    else:
        flash('Invalid file type. Only JPG, PNG, WEBP allowed.', 'danger')

    return redirect(url_for('admin_gallery'))


@app.route('/admin/gallery/delete/<int:id>')
@login_required
def admin_delete_gallery_photo(id):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM gallery WHERE id = %s", (id,))
    mysql.connection.commit()
    cur.close()
    flash('Photo removed from gallery.', 'info')
    return redirect(url_for('admin_gallery'))
if __name__ == '__main__':
    app.run(debug=True, port=3000)