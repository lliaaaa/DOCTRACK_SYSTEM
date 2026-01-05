import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from . import db
from .models import Record, Department, RecordHistory, User, DocumentType, DocumentStatus
from datetime import datetime
from sqlalchemy import func

# Import Flask-Login's login_required (rename to avoid collision if you had a custom one)
from flask_login import login_required
from .decorators import role_required  # keep your custom role checks

bp = Blueprint("main", __name__)


# --------------------------------
# HOME
# --------------------------------
@bp.route("/")
def home():
    return render_template("portal.html")

# --------------------------------
# SUPERADMIN AREA (ADMIN ONLY)
# --------------------------------
@bp.route("/admin")
@login_required
@role_required("admin")
def admin_home():
    return redirect(url_for("main.admin_dashboard"))

@bp.route("/admin/dashboard")
@login_required
@role_required("admin")
def admin_dashboard():
    # --- STATUS LOGIC (based on your rules) ---
    pending_status = "For Signature Mayor"
    completed_status = "With Checked"

    total_documents = Record.query.count()

    pending = Record.query.filter(
        Record.status == pending_status
    ).count()

    completed = Record.query.filter(
        Record.status == completed_status
    ).count()

    in_process = Record.query.filter(
        Record.status.notin_([pending_status, completed_status])
    ).count()

    stats = {
        "total_documents": total_documents,
        "pending": pending,
        "completed": completed,
        "in_process": in_process
    }

    # --- STATUS BREAKDOWN ---
    status_data = (
        db.session.query(
            Record.status,
            func.count(Record.id)
        )
        .group_by(Record.status)
        .all()
    )

    charts_combined = status_data

    # --- RECENT DOCUMENTS (FIXED) ---
    records = (
        Record.query
        .order_by(Record.created_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        charts_combined=charts_combined,
        records=records
    )

@bp.route("/admin/documents")
@login_required
@role_required("admin")
def admin_documents():
    records = Record.query.order_by(Record.date_received.desc()).all()
    departments = Department.query.order_by(Department.name).all()  # ✅ add this
    return render_template(
        "admin/documents.html",
        records=records,
        departments=departments
    )

# -------------------------------
# DEPARTMENTS PAGE & AJAX ENDPOINTS
# -------------------------------
@bp.route("/admin/departments")
@login_required
@role_required("admin")
def admin_departments():
    departments = (
        db.session.query(
            Department,
            func.count(Record.id)
        )
        .outerjoin(Record, Record.department == Department.name)
        .group_by(Department.id)
        .order_by(Department.name)
        .all()
    )

    return render_template(
        "admin/departments.html",
        departments=departments
    )

# ✅ AJAX ENDPOINTS FOR MODAL (MATCHES YOUR FRONTEND)
@bp.route("/admin/departments", methods=["POST"])
@login_required
@role_required("admin")
def ajax_add_department():
    try:
        data = request.get_json()
        if not data or not data.get('name'):
            return jsonify({'error': 'Department name is required'}), 400
        
        dept = Department(
            name=data['name'],
            head=data.get('head', ''),
            employees=int(data.get('employees', 0)),
            contact=data.get('contact', ''),
            email=data.get('email', '')
        )
        
        db.session.add(dept)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Department added successfully!',
            'department': {
                'id': dept.id,
                'name': dept.name,
                'head': dept.head,
                'employees': dept.employees,
                'contact': dept.contact or '',
                'email': dept.email or ''
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@bp.route("/admin/departments/<int:id>", methods=["PUT"])
@login_required
@role_required("admin")
def ajax_edit_department(id):
    try:
        dept = Department.query.get_or_404(id)
        data = request.get_json()
        
        dept.name = data['name']
        dept.head = data.get('head', '')
        dept.employees = int(data.get('employees', 0))
        dept.contact = data.get('contact', '')
        dept.email = data.get('email', '')
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Department updated successfully!',
            'department': {
                'id': dept.id,
                'name': dept.name,
                'head': dept.head,
                'employees': dept.employees,
                'contact': dept.contact or '',
                'email': dept.email or ''
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@bp.route("/admin/departments/<int:id>", methods=["DELETE"])
@login_required
@role_required("admin")
def ajax_delete_department(id):
    try:
        dept = Department.query.get_or_404(id)
        name = dept.name
        
        db.session.delete(dept)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Department "{name}" deleted successfully!'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# -------------------------------
# OLD FORM ROUTES (BACKWARD COMPATIBLE)
# -------------------------------
@bp.route("/admin/departments/add", methods=["POST"])
@login_required
@role_required("admin")
def add_department():
    dept = Department(
        name=request.form["name"],
        head=request.form["head"],
        employees=request.form.get("employees", 0),
        contact=request.form.get("contact"),
        email=request.form.get("email")
    )

    db.session.add(dept)
    db.session.commit()

    flash("Department added successfully!", "success")
    return redirect(url_for("main.admin_departments"))

@bp.route("/admin/departments/edit/<int:id>", methods=["POST"])
@login_required
@role_required("admin")
def edit_department(id):
    dept = Department.query.get_or_404(id)

    dept.name = request.form["name"]
    dept.head = request.form["head"]
    dept.employees = request.form.get("employees", 0)
    dept.contact = request.form.get("contact")
    dept.email = request.form.get("email")

    db.session.commit()

    flash("Department updated successfully!", "success")
    return redirect(url_for("main.admin_departments"))

@bp.route("/admin/departments/delete/<int:id>")
@login_required
@role_required("admin")
def delete_department(id):
    dept = Department.query.get_or_404(id)

    db.session.delete(dept)
    db.session.commit()

    flash("Department deleted successfully!", "success")
    return redirect(url_for("main.admin_departments"))

@bp.route("/admin/users")
@login_required
@role_required("admin")
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    departments = Department.query.order_by(Department.name).all()
    return render_template("admin/users.html", users=users, departments=departments)


# Add new user
@bp.route("/admin/users/add", methods=["POST"])
@login_required
@role_required("admin")
def add_user():
    full_name = request.form.get("full_name")
    email = request.form.get("email")
    password = request.form.get("password")
    role = request.form.get("role") or "user"
    department = request.form.get("department")

    # Validate required fields
    if not full_name or not email or not password:
        flash("Full name, email, and password are required.", "danger")
        return redirect(url_for("main.admin_users"))

    # Check for duplicate email
    if User.query.filter_by(email=email).first():
        flash("User with this email already exists.", "warning")
        return redirect(url_for("main.admin_users"))

    # Create new user
    user = User(
        full_name=full_name,
        email=email,
        role=role,
        department=department
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    flash(f"User {full_name} added successfully!", "success")
    return redirect(url_for("main.admin_users"))


# Edit existing user
@bp.route("/admin/users/edit/<int:id>", methods=["POST"])
@login_required
@role_required("admin")
def edit_user(id):
    user = User.query.get_or_404(id)

    full_name = request.form.get("full_name")
    email = request.form.get("email")
    password = request.form.get("password")
    role = request.form.get("role") or "user"
    department = request.form.get("department")

    # Validate required fields
    if not full_name or not email:
        flash("Full name and email are required.", "danger")
        return redirect(url_for("main.admin_users"))

    # Update user info
    user.full_name = full_name
    user.email = email
    user.role = role
    user.department = department

    # Update password only if provided
    if password:
        user.set_password(password)

    db.session.commit()
    flash(f"User {full_name} updated successfully!", "success")
    return redirect(url_for("main.admin_users"))


# Delete user
@bp.route("/admin/users/delete/<int:id>", methods=["POST"])
@login_required
@role_required("admin")
def delete_user(id):
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()

    flash(f"User {user.full_name} deleted successfully!", "success")
    return redirect(url_for("main.admin_users"))
# --------------------------------
# ADD / EDIT / DELETE RECORDS (ADMIN)
# --------------------------------
@bp.route('/admin/add_document', methods=['GET', 'POST'])
@login_required
def add_document():
    # Get users with role 'User' only
    users = User.query.filter_by(role='user').order_by(User.full_name).all()

    # Get document types, statuses, and departments
    document_types = DocumentType.query.order_by(DocumentType.name).all()
    statuses = DocumentStatus.query.order_by(DocumentStatus.name).all()
    departments = Department.query.order_by(Department.name).all()

    if request.method == 'POST':
        # Get form data
        title = request.form.get('title')
        doc_type_name = request.form.get('doc_type')
        implementing_office_name = request.form.get('implementing_office')
        date_received_str = request.form.get('date_received')
        amount = request.form.get('amount') or 0
        released_by_name = request.form.get('released_by')
        received_by_name = request.form.get('received_by')
        status_name = request.form.get('status')

        # Convert names to objects
        doc_type = DocumentType.query.filter_by(name=doc_type_name).first()
        implementing_office = Department.query.filter_by(name=implementing_office_name).first()
        released_by = User.query.filter_by(full_name=released_by_name).first()
        received_by = User.query.filter_by(full_name=received_by_name).first()
        status = DocumentStatus.query.filter_by(name=status_name).first()

        # Validate selections
        if not all([doc_type, implementing_office, released_by, received_by, status]):
            flash("Invalid selection. Please try again.", "danger")
            return redirect(url_for('admin.add_document'))

        # Convert date string to date object
        try:
            date_received = datetime.strptime(date_received_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", "danger")
            return redirect(url_for('admin.add_document'))

        # Create new Record
        new_doc = Record(
            document_id=f"DOC-{uuid.uuid4().hex[:8].upper()}",
            title=title,
            doc_type=doc_type.name,
            department=implementing_office.name,
            implementing_office=implementing_office.name,
            date_received=date_received,
            amount=float(amount),
            released_by=released_by.full_name,
            received_by=received_by.full_name,
            status=status.name,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
            
        )

        db.session.add(new_doc)
        db.session.flush()  # ensures new_doc.id is available

        # Create initial RecordHistory entry
        history_entry = RecordHistory(
            record_id=new_doc.id,
            action_type='release',  # first action is releasing
            status=status.name,
            from_department=released_by.department,
            to_department=received_by.department,
            action_by=released_by.full_name,
            timestamp=datetime.utcnow()
        )

        db.session.add(history_entry)
        db.session.commit()

        flash("Document added successfully and initial history recorded!", "success")
        return redirect(url_for('main.admin_documents'))

    return render_template(
        'admin/add_document.html',
        users=users,
        document_type=document_types,
        status=statuses,
        departments=departments
    )
@bp.route('/admin/documents/<int:id>', methods=['POST'])
@login_required
@role_required("admin")
def ajax_edit_document(id):
    try:
        record = Record.query.get_or_404(id)
        data = request.form
        
        # ✅ UPDATE ALL FIELDS
        record.title = data['title']
        record.doc_type = data['doc_type']
        record.department = data['implementing_office']
        record.date_received = datetime.strptime(data['date_received'], "%Y-%m-%d").date()
        record.amount = float(data['amount']) if data.get('amount') else None
        record.released_by = data['released_by']
        record.received_by = data['received_by']
        record.status = data['status']
        
        # ✅ ADD HISTORY IF STATUS CHANGED
        old_status = record.status  # Save old status before update
        # ... update above ...
        
        if old_status != record.status:
            history = RecordHistory(
                record_id=record.id,
                status=record.status,
                department=record.department,
                action_by=record.received_by,
                timestamp=datetime.now()
            )
            db.session.add(history)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Document updated successfully!'
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
@bp.route('/admin/delete/<int:id>', methods=['POST'])
@login_required
@role_required("admin")
def delete_document(id):
    record = Record.query.get_or_404(id)

    # Delete related history first
    RecordHistory.query.filter_by(record_id=record.id).delete()

    db.session.delete(record)
    db.session.commit()

    flash('Record deleted successfully!', 'success')
    return redirect(url_for('main.admin_documents'))

@bp.route('/admin/trace', methods=['GET'])
@login_required
@role_required("admin")
def admin_trace():
    q = request.args.get('q')
    documents = []
    tracked_doc = None

    if q:
        documents = Record.query.filter(
            Record.document_id.ilike(f'%{q}%') | Record.title.ilike(f'%{q}%')
        ).all()

        tracked_doc = Record.query.filter_by(document_id=q).first()

    return render_template('admin/tracking.html', documents=documents, tracked_doc=tracked_doc)

# DEPARTMENT USER AREA
# --------------------------------
@bp.route("/department")
@login_required
@role_required("user")
def department_home():
    return redirect(url_for('main.department_dashboard'))

@bp.route("/department/dashboard")
@login_required
@role_required("user")
def department_dashboard():
    user_dept = current_user.department

    stats = {
        "total_documents": Record.query.filter_by(department=user_dept).count(),
        "pending": Record.query.filter_by(department=user_dept, status="Pending").count(),
        "completed": Record.query.filter_by(department=user_dept, status="Completed").count(),
        "in_process": Record.query.filter(Record.department == user_dept,
                                          Record.status.notin_(["Pending", "Completed"])).count()
    }

    # Recent documents (latest 5)
    records = Record.query.filter_by(department=user_dept).order_by(Record.date_received.desc()).limit(5).all()

    return render_template("department/dashboard.html", stats=stats, records=records)

@bp.route("/department/documents")
@login_required
@role_required("user")
def department_documents():
    records = Record.query.filter_by(department=current_user.department).order_by(Record.date_received.desc()).all()

    # Optional: prepare stats for dashboard cards
    stats = {
        "total_documents": len(records),
        "pending": sum(1 for r in records if "for signature mayor" in r.status.lower()),
        "completed": sum(1 for r in records if "with checked" in r.status.lower()),
        "in_process": sum(1 for r in records if r.status.lower() not in ["with checked", "for signature mayor"])
    }

    return render_template(
        "department/documents.html",
        records=records,
        stats=stats
    )

@bp.route("/department/transfer_receive")
@login_required
@role_required("user")
def department_transfer_receive():
    # All documents in your department
    records = Record.query.filter_by(department=current_user.department).all()
    
    incoming_transfers = RecordHistory.query.filter_by(
    to_department=current_user.department,
    action_type='transfer').filter(RecordHistory.status.notin_(['Completed'])).all()


    
    # All departments (for transfer dropdown)
    departments = Department.query.all()

    return render_template(
        'department/transfer_receive.html',
        records=records,
        incoming_transfers=incoming_transfers,
        departments=departments
    )

from flask_login import current_user, login_required
@bp.route('/documents/transfer/<int:record_id>', methods=['POST'])
@login_required
def transfer_document(record_id):
    record = Record.query.get_or_404(record_id)
    data = request.get_json()
    to_department = data.get('to_department')
    new_status = data.get('status')

    if not to_department or not new_status:
        return jsonify(success=False, error="Department and status required")

    try:
        from_department = record.department

        # Update main record status only (department remains current until received)
        record.status = new_status
        record.updated_at = datetime.utcnow()

        # Add history for the transfer
        history = RecordHistory(
            record_id=record.id,
            action_type='transfer',
            from_department=from_department,
            to_department=to_department,
            action_by=current_user.full_name,  # ✅ use full_name
            status=new_status,
            timestamp=datetime.utcnow()
        )
        db.session.add(history)
        db.session.commit()

        return jsonify(success=True, message=f"Document transfer to {to_department} recorded!")
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, error=str(e))

@bp.route('/documents/receive/<int:history_id>', methods=['POST'])
@login_required
def receive_document(history_id):
    history = RecordHistory.query.get_or_404(history_id)

    if history.to_department != current_user.department:
        return jsonify({"success": False, "error": "No pending transfer for your department."})

    record = history.record
    record.department = current_user.department
    record.status = history.status
    record.updated_at = datetime.utcnow()

    history.action_type = 'received'
    history.action_by = current_user.full_name
    history.timestamp = datetime.utcnow()

    db.session.commit()


    return jsonify({
        "success": True,
        "message": f"Document {record.document_id} received successfully!",
        "new_department": record.department,
        "status": record.status
    })
@bp.route('/documents/close/<int:record_id>', methods=['POST'])
@login_required
@role_required("admin")  # or allow department users if needed
def close_document(record_id):
    try:
        record = Record.query.get_or_404(record_id)

        if record.status == "Closed":
            return jsonify({"success": False, "error": "Document is already closed."})

        record.status = "Closed"
        db.session.commit()

        # Add history entry
        history = RecordHistory(
            record_id=record.id,
            action_type="close_ticket",
            status="Closed",
            action_by=current_user.full_name,
            timestamp=datetime.utcnow()
        )
        db.session.add(history)
        db.session.commit()

        return jsonify({"success": True, "message": f"Document {record.document_id} closed successfully!"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})
