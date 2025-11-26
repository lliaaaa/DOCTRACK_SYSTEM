from flask import Blueprint, request, render_template, flash, redirect, url_for
from .decorators import login_required, role_required
from .models import Record
from . import db

bp = Blueprint("main", __name__)

# -----------------------------
# HOME
# -----------------------------
@bp.route("/")
def home():
    return render_template("portal.html")


# -----------------------------
# DASHBOARD (requires login)
# -----------------------------
@bp.route("/dashboard")
@login_required
def dashboard():
    from sqlalchemy import func

    stats = {
        "total_documents": Record.query.count(),
        "pending": Record.query.filter_by(status="Pending").count(),
        "completed": Record.query.filter_by(status="Completed").count(),
        "overdue": Record.query.filter(Record.date_returned == None).count()
    }

    dept_data = db.session.query(Record.department, func.count()).group_by(Record.department).all()
    status_data = db.session.query(Record.status, func.count()).group_by(Record.status).all()

    charts = {
        "dept_labels": [d[0] for d in dept_data],
        "dept_counts": [d[1] for d in dept_data],
        "status_labels": [s[0] for s in status_data],
        "status_counts": [s[1] for s in status_data],
    }

    latest = Record.query.order_by(Record.date_in.desc()).limit(5).all()

    return render_template("dashboard.html", stats=stats, charts=charts, latest=latest)



# -----------------------------
# SUPERADMIN AREA
# -----------------------------
@bp.route("/superadmin")
@login_required
@role_required("admin")
def superadmin_home():
    return render_template("superadmin/index.html")
@bp.route("/superadmin/dashboard")
@login_required
@role_required("admin")
def superadmin_dashboard():
    return render_template("superadmin/dashboard.html")
@bp.route("/superadmin/documents")
@login_required
@role_required("admin")
def superadmin_documents():
    return render_template("superadmin/documents.html")
@bp.route("/superadmin/tracking")
@login_required
@role_required("admin")
def superadmin_tracking():
    return render_template("superadmin/tracking.html")
@bp.route("/superadmin/analytics")
@login_required
@role_required("admin")
def superadmin_analytics():
    return render_template("superadmin/analytics.html")
@bp.route("/superadmin/departments")
@login_required
@role_required("admin")
def superadmin_departments():
    return render_template("superadmin/departments.html")
@bp.route("/superadmin/users")
@login_required
@role_required("admin")
def superadmin_users():
    return render_template("superadmin/users.html")
@bp.route("/superadmin/logs")
@login_required
@role_required("admin")
def superadmin_logs():
    return render_template("superadmin/logs.html")
@bp.route('/superadmin/add', methods=['GET', 'POST'])
@login_required
@role_required("admin")
def add_record():
    if request.method == 'POST':
        new_record = Record(
            control=request.form['control'],
            department=request.form['department'],
            type=request.form['type'],
            amount=request.form['amount'],
            payee=request.form['payee'],
            source=request.form['source'],
            date_in=request.form['date_in'],
            clock_in=request.form['clock_in'],
            date_returned=request.form['date_returned'],
            clock_out=request.form['clock_out'],
            status=request.form['status'],
            remarks=request.form['remarks']
        )

        db.session.add(new_record)
        db.session.commit()

        flash('Record added successfully!', 'success')
        return redirect(url_for('main.view_records'))

    return render_template("superadmin/add.html")



@bp.route('/superadmin/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required("admin")
def edit_record(id):
    record = Record.query.get_or_404(id)

    if request.method == 'POST':
        record.control = request.form['control']
        record.department = request.form['department']
        record.type = request.form['type']
        record.amount = request.form['amount']
        record.payee = request.form['payee']
        record.source = request.form['source']
        record.date_in = request.form['date_in']
        record.clock_in = request.form['clock_in']
        record.date_returned = request.form['date_returned']
        record.clock_out = request.form['clock_out']
        record.status = request.form['status']
        record.remarks = request.form['remarks']

        db.session.commit()
        flash('Record updated successfully!', 'success')
        return redirect(url_for('main.view_records'))

    return render_template('superadmin/edit.html', record=record)



@bp.route('/superadmin/delete/<int:id>')
@login_required
@role_required("admin")
def delete_record(id):
    record = Record.query.get_or_404(id)
    db.session.delete(record)
    db.session.commit()

    flash('Record deleted successfully!', 'success')
    return redirect(url_for('main.view_records'))



# -----------------------------
# CO-OFFICES SECTION
# -----------------------------
@bp.route("/co-offices")
@login_required
@role_required("co_office")
def co_offices_home():
    return render_template("co-offices/index.html")



@bp.route("/co-offices/records")
@login_required
@role_required("co_office")
def co_offices_view_records():
    records = Record.query.all()
    return render_template("co-offices/view.html", records=records)
