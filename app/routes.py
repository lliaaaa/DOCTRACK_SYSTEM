from flask import Blueprint, request, render_template, flash, redirect, url_for
from datetime import datetime
from .decorators import login_required, role_required
from .models import Record
from . import db
from sqlalchemy import func


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
def superadmin_home():
    return render_template("superadmin/index.html")


@bp.route("/admin/dashboard")
@login_required
@role_required("admin")
def superadmin_dashboard():
    stats = {
        "total_documents": Record.query.count(),
        "pending": Record.query.filter_by(status="Pending").count(),
        "completed": Record.query.filter_by(status="Completed").count(),
        "in_process": Record.query.filter_by(status="In Process").count()  # <- updated
    }

    dept_data = db.session.query(Record.department, func.count()).group_by(Record.department).all()
    status_data = db.session.query(Record.status, func.count()).group_by(Record.status).all()

    charts_combined = zip([s[0] for s in status_data], [s[1] for s in status_data])

    latest = Record.query.order_by(Record.date_in.desc()).limit(5).all()

    return render_template(
        "superadmin/dashboard.html",
        stats=stats,
        charts_combined=charts_combined,
        latest=latest
    )


@bp.route("/admin/documents")
@login_required
@role_required("admin")
def superadmin_documents():
    records = Record.query.order_by(Record.date_in.desc()).all()
    return render_template(
        "superadmin/documents.html",
        records=records
    )

@bp.route("/admin/analytics")
@login_required
@role_required("admin")
def superadmin_analytics():
    return render_template("superadmin/analytics.html")


@bp.route("/admin/departments")
@login_required
@role_required("admin")
def superadmin_departments():
    return render_template("superadmin/departments.html")


@bp.route("/admin/users")
@login_required
@role_required("admin")
def superadmin_users():
    return render_template("superadmin/users.html")

# --------------------------------
# ADD / EDIT / DELETE RECORDS (ADMIN)
# --------------------------------
@bp.route('/superadmin/add', methods=['GET', 'POST'])
@login_required
@role_required("admin")
def add_record():
    if request.method == 'POST':
        title = request.form['title']
        doc_type = request.form['doc_type']
        implementing_office = request.form['implementing_office']

        # ✅ Convert string → date (PostgreSQL safe)
        date_received = datetime.strptime(
            request.form['date_received'],
            "%Y-%m-%d"
        ).date()

        amount = request.form.get('amount')
        released_by = request.form['released_by']
        received_by = request.form['received_by']
        status = request.form['status']

        new_record = Record(
            title=title,
            doc_type=doc_type,
            department=implementing_office,
            date_in=date_received,
            amount=float(amount) if amount else None,
            released_by=released_by,
            received_by=received_by,
            status=status
        )

        db.session.add(new_record)
        db.session.commit()

        flash(
            f"Record added successfully! Document ID: {new_record.document_id}",
            "success"
        )

        return redirect(url_for('main.superadmin_documents'))

    return render_template("superadmin/add_document.html")
@bp.route('/superadmin/view/<int:id>')
@login_required
@role_required("admin")
def view_document(id):
    record = Record.query.get_or_404(id)
    return render_template("superadmin/view_document.html", record=record)
@bp.route('/superadmin/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required("admin")
def edit_document(id):
    record = Record.query.get_or_404(id)

    if request.method == 'POST':
        record.title = request.form['title']
        record.doc_type = request.form['doc_type']
        record.department = request.form['implementing_office']
        record.date_in = datetime.strptime(request.form['date_received'], "%Y-%m-%d").date()
        record.amount = float(request.form['amount']) if request.form.get('amount') else None
        record.released_by = request.form['released_by']
        record.received_by = request.form['received_by']
        record.status = request.form['status']

        db.session.commit()
        flash("Record updated successfully!", "success")
        return redirect(url_for('main.superadmin_documents'))

    return render_template("superadmin/edit_document.html", record=record)
@bp.route('/superadmin/delete/<int:id>')
@login_required
@role_required("admin")
def delete_document(id):
    record = Record.query.get_or_404(id)
    db.session.delete_document(record)
    db.session.commit()

    flash('Record deleted successfully!', 'success')
    return redirect(url_for('main.superadmin_documents'))
# Trace / Tracking
@bp.route("/superadmin/trace/", defaults={'id': None})
@bp.route("/superadmin/trace/<id>")  # remove <int:>
@login_required
@role_required("admin")
def superadmin_trace(id):
    # Get all documents
    documents = Record.query.order_by(Record.date_in.desc()).all()

    # Get specific document if ID is provided
    tracked_doc = Record.query.get(id) if id else None

    return render_template(
        "superadmin/tracking.html",
        documents=documents,
        tracked_doc=tracked_doc
    )


# DEPARTMENT USER AREA
# --------------------------------
@bp.route('/')
def portal():
    return render_template('portal.html')

@bp.route("/department")
@login_required
@role_required("user")
def department_home():
    return render_template("department/index.html")


@bp.route("/department/dashboard")
@login_required
@role_required("user")
def department_dashboard():
    stats = {
        "total_documents": Record.query.count(),
        "pending": Record.query.filter_by(status="Pending").count(),
        "completed": Record.query.filter_by(status="Completed").count(),
        "overdue": Record.query.filter(Record.date_returned == None).count()
    }
    return render_template("department/dashboard.html", stats=stats)


@bp.route("/department/documents")
@login_required
@role_required("user")
def department_documents():
    return render_template("department/documents.html")


