from flask import Blueprint, request, render_template, flash, redirect, url_for
from .decorators import login_required, role_required
from .models import Record, User
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
    return render_template("dashboard.html")


# -----------------------------
# ADD RECORD
# -----------------------------
@bp.route('/add', methods=['GET', 'POST'])
@login_required
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

    return render_template("admin/add.html")

# -----------------------------
# EDIT RECORD
# -----------------------------
@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
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

    return render_template('admin/edit.html', record=record)


# -----------------------------
# DELETE RECORD
# -----------------------------
@bp.route('/delete/<int:id>')
@login_required
@role_required("admin")
def delete_record(id):
    record = Record.query.get_or_404(id)
    db.session.delete(record)
    db.session.commit()

    flash('Record deleted successfully!', 'success')
    return redirect(url_for('main.view_records'))
