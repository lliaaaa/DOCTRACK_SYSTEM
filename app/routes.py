import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func, or_
from datetime import datetime, date, timezone

from . import db
from .models import (
    Record,
    Department,
    RecordHistory,
    User,
    DocumentType,
    DocumentStatus
)
from .decorators import role_required

bp = Blueprint("main", __name__)


# =========================================================
# HELPER: documents visible to current department
# =========================================================
def visible_documents(department):
    return Record.query.filter(
        or_(
            Record.department == department,
            Record.id.in_(
                db.session.query(RecordHistory.record_id)
                .filter(
                    (RecordHistory.from_department == department) |
                    (RecordHistory.to_department == department)
                )
            )
        )
    )


# =========================================================
# HOME
# =========================================================
@bp.route("/")
def home():
    return render_template("portal.html")


# =========================================================
# DASHBOARD (ADMIN + USER)
# =========================================================
@bp.route("/dashboard")
@login_required
def dashboard():
    records_q = visible_documents(current_user.department)

    stats = {
        "total_documents": records_q.count(),
        "closed": records_q.filter(Record.status == "Closed").count(),
        "completed": records_q.filter(Record.status == "With Checked").count(),
        "in_process": records_q.filter(
            Record.status.notin_(["Closed", "With Checked"])
        ).count()
    }

    status_data = (
        records_q.with_entities(Record.status, func.count(Record.id))
        .group_by(Record.status)
        .all()
    )

    records = records_q.order_by(Record.created_at.desc()).limit(5).all()

    return render_template(
        "dashboard.html",
        stats=stats,
        charts_combined=status_data,
        records=records
    )


# =========================================================
# DOCUMENTS (ADMIN + USER)
# =========================================================
@bp.route("/documents")
@login_required
def documents():
    records = visible_documents(current_user.department)\
        .order_by(Record.date_received.desc())\
        .all()

    return render_template("documents.html", records=records)


# =========================================================
# USERS (ADMIN ONLY — SAME DEPARTMENT)
# =========================================================
@bp.route("/users")
@login_required
@role_required("admin")
def users():
    users = User.query.filter_by(department=current_user.department).all()
    return render_template("admin/users.html", users=users)


@bp.route("/users/add", methods=["POST"])
@login_required
@role_required("admin")
def add_user():
    if User.query.filter_by(email=request.form["email"]).first():
        flash("User already exists.", "warning")
        return redirect(url_for("main.users"))

    user = User(
        full_name=request.form["full_name"],
        email=request.form["email"],
        role=request.form.get("role", "user"),
        department=current_user.department
    )
    user.set_password(request.form["password"])

    db.session.add(user)
    db.session.commit()

    flash("User added successfully.", "success")
    return redirect(url_for("main.users"))

# Edit existing user (no password change, admins protected)
@bp.route("/admin/users/edit/<int:id>", methods=["POST"])
@login_required
@role_required("admin")
def edit_user(id):
    user = User.query.get_or_404(id)

    # Prevent editing other admins
    if user.role == "admin":
        flash("Cannot edit other admin accounts.", "danger")
        return redirect(url_for("main.users"))

    full_name = request.form.get("full_name")
    email = request.form.get("email")
    department = request.form.get("department")

    if not full_name:
        flash("Full name is required.", "danger")
        return redirect(url_for("main.users"))

    user.full_name = full_name
    user.department = department

    db.session.commit()
    flash(f"User {full_name} updated successfully!", "success")
    return redirect(url_for("main.users"))

# Activate / Deactivate user
@bp.route("/admin/users/toggle/<int:id>", methods=["POST"])
@login_required
def toggle_user(id):
    user = User.query.get_or_404(id)
    if user.role == "admin":
        return redirect(url_for("main.users"))

    user.is_deactivated = not user.is_deactivated
    db.session.commit()
    return redirect(url_for("main.users"))

# Delete user (protect admins)
@bp.route("/admin/users/delete/<int:id>", methods=["POST"])
@login_required
@role_required("admin")
def delete_user(id):
    user = User.query.get_or_404(id)
    if user.role == "admin":
        flash("Cannot delete admin accounts.", "danger")
        return redirect(url_for("main.users"))

    db.session.delete(user)
    db.session.commit()
    flash(f"User {user.full_name} deleted successfully!", "success")
    return redirect(url_for("main.users"))

# =========================================================
# ADD DOCUMENT (ADMIN)
# =========================================================
@bp.route("/add_document", methods=["GET", "POST"])
@login_required
@role_required("admin")
def add_document():
    users = User.query.filter_by(department=current_user.department).all()
    document_type = DocumentType.query.all()
    document_status = DocumentStatus.query.all()
    departments = Department.query.all()

    if request.method == "POST":
        date_received = datetime.strptime(
            request.form["date_received"], "%Y-%m-%d"
        ).date()
        amount_input = request.form.get("amount", "").strip()
        amount = float(amount_input) if amount_input else None

        record = Record(
        document_id=f"DOC-{uuid.uuid4().hex[:8].upper()}",
        title=request.form["title"],
        doc_type=request.form["doc_type"],
        department=request.form["implementing_office"],
        implementing_office=request.form["implementing_office"],
        date_received = date.today(),
        amount=amount,
        released_by=current_user.full_name,
        received_by=request.form["received_by"],
        status=request.form["status"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )

        db.session.add(record)
        db.session.flush()

        history = RecordHistory(
            record_id=record.id,
            action_type="release",
            from_department=current_user.department,
            to_department=request.form["implementing_office"],
            action_by=current_user.full_name,
            status=request.form["status"],
            timestamp=datetime.now(timezone.utc)
        )

        db.session.add(history)
        db.session.commit()

        flash("Document added successfully.", "success")
        return redirect(url_for("main.documents"))

    return render_template(
        "admin/add_document.html",
        users=users,
        document_type=document_type,
        document_status=document_status,
        departments=departments
    )


# =========================================================
# TRANSFER & RECEIVE
# =========================================================
@bp.route("/transfer_receive")
@login_required
def transfer_receive():
    dept = current_user.department

    records = Record.query.filter_by(department=dept).all()

    incoming_transfers = RecordHistory.query.filter_by(
        to_department=dept,
        action_type="transfer"
    ).all()

    departments = Department.query.all() if current_user.role == "admin" else []

    return render_template(
        "admin/transfer_receive.html",
        records=records,
        incoming_transfers=incoming_transfers,
        departments=departments
    )

@bp.route("/documents/transfer/<int:record_id>", methods=["POST"])
@login_required
def transfer_document(record_id):
    record = Record.query.get_or_404(record_id)
    data = request.get_json()

    history = RecordHistory(
        record_id=record.id,
        action_type="transfer",
        from_department=current_user.department,
        to_department=data["to_department"],
        action_by=current_user.full_name,
        status=data["status"],
        timestamp=datetime.now(timezone.utc)
    )

    record.status = data["status"]
    record.updated_at = datetime.now(timezone.utc)

    db.session.add(history)
    db.session.commit()

    return jsonify(
        success=True,
        message="Document transferred successfully.",
        record_id=record.id,
        status=record.status
    )


@bp.route("/documents/receive/<int:history_id>", methods=["POST"])
@login_required
def receive_document(history_id):
    history = RecordHistory.query.get_or_404(history_id)

    if history.to_department != current_user.department:
        return jsonify(success=False)

    record = history.record
    record.department = current_user.department
    record.status = history.status
    record.updated_at = datetime.now(timezone.utc)

    history.action_type = "received"
    history.action_by = current_user.full_name
    history.timestamp = datetime.now(timezone.utc)

    db.session.commit()

    return jsonify(success=True)


# =========================================================
# TRACE
# =========================================================
@bp.route("/trace")
@login_required
def trace():
    q = request.args.get("q")
    documents = []
    tracked_doc = None

    if q:
        documents = visible_documents(current_user.department).filter(
            (Record.document_id.ilike(f"%{q}%")) |
            (Record.title.ilike(f"%{q}%"))
        ).all()

        tracked_doc = visible_documents(current_user.department)\
            .filter_by(document_id=q)\
            .first()

    return render_template(
        "tracking.html",
        documents=documents,
        tracked_doc=tracked_doc
    )
