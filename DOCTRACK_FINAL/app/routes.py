from collections import defaultdict

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from sqlalchemy import func, or_
from sqlalchemy.orm import aliased
from datetime import datetime, date, timezone

from . import db
from .models import (Document, Department, Transaction, User, Account,
                     DocumentType, DocumentStatus, generate_document_code)
from .decorators import role_required

bp = Blueprint("main", __name__)

COMPLETED_STATUSES = {"Closed", "With Checked and Closed"}

# ---------------------------------------------------------------------------
# SVP Automated Routing
# ---------------------------------------------------------------------------
# Document type name that uses automated routing
SVP_TYPE_NAME = "SVP"

# Ordered workflow: (status_name, destination_department_name | None)
# None means the doc stays at the current department (just advances status).
SVP_WORKFLOW = [
    ("Request for PR/PO",                        None),
    ("Request for OBR",                          "Budget Office"),
    ("For Accounting Staff Validation",          "Accounting Office"),
    ("For Signature BAC Members - BAC Office",   "BAC Office"),
    ("For Signature of Mayor",                   "Office of the Mayor"),
    ("For Processing",                           "Accounting Office"),
    ("With Checked",                             None),
    ("Closed",                                   None),
]

SVP_STATUS_ORDER = [s for s, _ in SVP_WORKFLOW]


def get_svp_next_step(current_status: str):
    """Return (next_status, next_dept_name) for an SVP document, or None if at end."""
    try:
        idx = SVP_STATUS_ORDER.index(current_status)
    except ValueError:
        return None
    if idx + 1 >= len(SVP_WORKFLOW):
        return None
    return SVP_WORKFLOW[idx + 1]  # (next_status, next_dept_or_None)


def is_svp_doc(record) -> bool:
    return record.doc_type_rel and record.doc_type_rel.type_name == SVP_TYPE_NAME


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_dept_id(dept_name: str):
    """Return department_id for a given department name, or None."""
    if not dept_name:
        return None
    dept = Department.query.filter_by(department_name=dept_name).first()
    return dept.department_id if dept else None


def get_dept_users(dept_name: str, active_only: bool = False):
    """Return Account objects belonging to the given department."""
    dept = Department.query.filter_by(department_name=dept_name).first()
    if not dept:
        return []
    q = Account.query.join(User).filter(User.department_id == dept.department_id)
    if active_only:
        q = q.filter(Account.status == 'active')
    return q.all()


def get_next_status(current_status_name: str) -> str:
    current = DocumentStatus.query.filter_by(name=current_status_name).first()
    if current:
        nxt = (DocumentStatus.query
               .filter(DocumentStatus.id > current.id)
               .order_by(DocumentStatus.id.asc())
               .first())
        if nxt:
            return nxt.name
    return "With Checked and Closed"


def make_transaction(document_id, transaction_type, origin, destination,
                     status, remarks=None, handled_by_user_id=None, action_by_name=None):
    """Helper to build a Transaction with the correct department_id."""
    dept_id = get_dept_id(destination or origin)
    return Transaction(
        document_id=document_id,
        department_id=dept_id,
        transaction_type=transaction_type,
        origin=origin,
        destination=destination,
        handled_by=handled_by_user_id,
        action_by_name=action_by_name,
        status=status,
        remarks=remarks,
        datetime=datetime.now(timezone.utc),
    )


def visible_documents(department: str):
    """Return a Document query visible to the given department."""
    dept_id = get_dept_id(department)

    processed_doc_ids = (
        db.session.query(Transaction.document_id).filter(
            (Transaction.origin == department) | (Transaction.destination == department)
        ).subquery()
    )

    pending_transfer_ids = (
        db.session.query(Transaction.document_id).filter(
            Transaction.transaction_type == "transfer",
            Transaction.destination == department,
            ~Transaction.document_id.in_(
                db.session.query(Transaction.document_id).filter(
                    Transaction.transaction_type == "received",
                    Transaction.destination == department
                )
            )
        ).subquery()
    )

    return Document.query.filter(
        or_(
            Document.current_department_id == dept_id,
            Document.document_id.in_(processed_doc_ids),
            Document.document_id.in_(pending_transfer_ids),
        )
    )


# ---------------------------------------------------------------------------
# Core routes
# ---------------------------------------------------------------------------

@bp.route("/")
def home():
    return render_template("portal.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    records_q = visible_documents(current_user.department)
    stats = {
        "total_documents": records_q.count(),
        "closed":     records_q.filter(Document.status == "Closed").count(),
        "completed":  records_q.filter(Document.status == "With Checked and Closed").count(),
        "in_process": records_q.filter(Document.status.notin_(list(COMPLETED_STATUSES))).count(),
    }
    status_data = (records_q
                   .with_entities(Document.status, func.count(Document.document_id))
                   .group_by(Document.status).all())
    records = records_q.order_by(Document.datetime.desc()).limit(5).all()
    return render_template("dashboard.html", stats=stats, charts_combined=status_data, records=records)


@bp.route("/documents")
@login_required
def documents():
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    records_q = visible_documents(current_user.department)
    if q:
        records_q = records_q.filter(
            or_(Document.document_code.ilike(f"%{q}%"), Document.title.ilike(f"%{q}%"))
        )
    if status_filter == "closed":
        records_q = records_q.filter(Document.status == "Closed")
    elif status_filter == "completed":
        records_q = records_q.filter(Document.status == "With Checked and Closed")
    elif status_filter == "inprocess":
        records_q = records_q.filter(Document.status.notin_(list(COMPLETED_STATUSES)))
    records = records_q.order_by(Document.datetime.desc()).all()
    return render_template("documents.html", records=records, q=q, status_filter=status_filter)


@bp.route("/documents/<int:record_id>")
@login_required
def document_detail(record_id):
    record = visible_documents(current_user.department).filter(
        Document.document_id == record_id).first()
    if not record:
        abort(404)
    departments = Department.query.all()
    document_statuses = DocumentStatus.query.all()
    return render_template("document_detail.html", record=record,
                           departments=departments, document_statuses=document_statuses)


@bp.route("/documents/edit/<int:record_id>", methods=["GET", "POST"])
@login_required
@role_required("admin")
def edit_document(record_id):
    record = db.session.get(Document, record_id) or abort(404)
    if request.method == "POST":
        record.title = request.form.get("title", record.title)
        # Update doc type by name
        new_type_name = request.form.get("doc_type", "")
        if new_type_name:
            dt = DocumentType.query.filter_by(type_name=new_type_name).first()
            if dt:
                record.document_type_id = dt.document_type_id
        new_dept_name = request.form.get("implementing_office", "")
        if new_dept_name:
            record.implementing_office = new_dept_name
        amount = request.form.get("amount")
        record.amount = float(amount) if amount else None
        record.received_by = request.form.get("received_by", record.received_by)
        record.status = request.form.get("status", record.status)
        record.remarks = request.form.get("remarks", record.remarks)
        date_str = request.form.get("date_received", "").strip()
        if date_str:
            try:
                record.datetime = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                pass
        record.updated_at = datetime.now(timezone.utc)
        db.session.add(make_transaction(
            document_id=record.document_id,
            transaction_type="edit",
            origin=current_user.department,
            destination=record.department,
            action_by_name=current_user.full_name,
            handled_by_user_id=current_user.user.user_id,
            status=record.status,
        ))
        db.session.commit()
        flash("Document updated successfully.", "success")
        return redirect(url_for("main.document_detail", record_id=record.document_id))
    departments = Department.query.all()
    document_types = DocumentType.query.all()
    document_statuses = DocumentStatus.query.all()
    return render_template("document_edit.html", record=record, departments=departments,
                           document_types=document_types, document_statuses=document_statuses)


@bp.route("/documents/delete/<int:record_id>", methods=["POST"])
@login_required
@role_required("admin")
def delete_document(record_id):
    record = db.session.get(Document, record_id) or abort(404)
    db.session.delete(record)
    db.session.commit()
    flash("Document deleted.", "info")
    return redirect(url_for("main.documents"))


@bp.route("/documents/close/<int:record_id>", methods=["POST"])
@login_required
@role_required("admin")
def close_document(record_id):
    record = db.session.get(Document, record_id) or abort(404)
    record.status = "Closed"
    record.updated_at = datetime.now(timezone.utc)
    db.session.add(make_transaction(
        document_id=record.document_id,
        transaction_type="close",
        origin=current_user.department,
        destination=record.department,
        action_by_name=current_user.full_name,
        handled_by_user_id=current_user.user.user_id,
        status="Closed",
    ))
    db.session.commit()
    return jsonify(success=True)


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

@bp.route("/users")
@login_required
@role_required("admin")
def users():
    dept_accounts = get_dept_users(current_user.department)
    return render_template("users.html", users=dept_accounts)


@bp.route("/users/add", methods=["POST"])
@login_required
@role_required("admin")
def add_user():
    email = request.form.get("email", "").strip().lower()
    if User.query.filter_by(email=email).first():
        flash("User already exists.", "warning")
        return redirect(url_for("main.users"))
    full_name = request.form.get("full_name", "").strip()
    parts = full_name.split(" ", 1)
    first = parts[0]
    last  = parts[1] if len(parts) > 1 else "-"
    dept = Department.query.filter_by(department_name=current_user.department).first()
    new_user = User(
        first_name=first,
        last_name=last,
        email=email,
        department_id=dept.department_id if dept else None,
    )
    db.session.add(new_user)
    db.session.flush()
    account = Account(
        user_id=new_user.user_id,
        username=email,
        role=request.form.get("role", "user"),
        status="active",
    )
    account.set_password(request.form["password"])
    db.session.add(account)
    db.session.commit()
    flash("User added successfully.", "success")
    return redirect(url_for("main.users"))


@bp.route("/admin/users/edit/<int:id>", methods=["POST"])
@login_required
@role_required("admin")
def edit_user(id):
    account = db.session.get(Account, id) or abort(404)
    user = account.user
    if account.role == "admin" and account.account_id != current_user.account_id and not account.is_temp_admin:
        flash("Cannot edit other admin accounts.", "danger")
        return redirect(url_for("main.users"))
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    if not full_name:
        flash("Full name is required.", "danger")
        return redirect(url_for("main.users"))
    parts = full_name.split(" ", 1)
    user.first_name = parts[0]
    user.last_name  = parts[1] if len(parts) > 1 else "-"
    if email and email != user.email:
        if not User.query.filter_by(email=email).first():
            user.email = email
            account.username = email
        else:
            flash("Email already in use.", "warning")
            return redirect(url_for("main.users"))
    new_password = request.form.get("new_password", "").strip()
    if new_password:
        if len(new_password) < 6:
            flash("Password must be at least 6 characters.", "warning")
            return redirect(url_for("main.users"))
        account.set_password(new_password)
    give_admin = request.form.get("give_admin_access") == "on"
    if give_admin:
        account.role = "admin"
        account.is_temp_admin = True
    else:
        account.role = "user"
        account.is_temp_admin = False
    db.session.commit()
    flash(f"User {full_name} updated successfully.", "success")
    return redirect(url_for("main.users"))


@bp.route("/admin/users/toggle/<int:id>", methods=["POST"])
@login_required
@role_required("admin")
def toggle_user(id):
    account = db.session.get(Account, id) or abort(404)
    if account.role == "admin":
        flash("Cannot deactivate admin accounts.", "warning")
        return redirect(url_for("main.users"))
    account.is_deactivated = not account.is_deactivated
    db.session.commit()
    return redirect(url_for("main.users"))


@bp.route("/admin/users/delete/<int:id>", methods=["POST"])
@login_required
@role_required("admin")
def delete_user(id):
    account = db.session.get(Account, id) or abort(404)
    if account.role == "admin":
        flash("Cannot delete admin accounts.", "danger")
        return redirect(url_for("main.users"))
    user = account.user
    db.session.delete(account)
    db.session.delete(user)
    db.session.commit()
    flash(f"User {user.full_name} deleted.", "success")
    return redirect(url_for("main.users"))


# ---------------------------------------------------------------------------
# Document CRUD
# ---------------------------------------------------------------------------

@bp.route("/add_document", methods=["GET", "POST"])
@login_required
def add_document():
    dept_accounts  = get_dept_users(current_user.department)
    document_type  = DocumentType.query.all()
    document_status = DocumentStatus.query.all()
    departments    = Department.query.all()

    if request.method == "POST":
        type_name = request.form["doc_type"]
        dt = DocumentType.query.filter_by(type_name=type_name).first()
        first_status = DocumentStatus.query.order_by(DocumentStatus.id.asc()).first()
        auto_status = first_status.name if first_status else "Pending"
        dept_id = get_dept_id(current_user.department)

        doc_code = generate_document_code()
        record = Document(
            document_code=doc_code,
            title=request.form["title"],
            document_type_id=dt.document_type_id if dt else 1,
            created_by=current_user.user.user_id,
            datetime=datetime.now(timezone.utc),
            status=auto_status,
            priority=request.form.get("priority", "Normal"),
            action_taken=request.form.get("action_taken", ""),
            current_department_id=dept_id,
            implementing_office=current_user.department,
            received_by="",
            remarks=request.form.get("remarks", ""),
            updated_at=datetime.now(timezone.utc),
        )
        db.session.add(record)
        db.session.flush()
        db.session.add(make_transaction(
            document_id=record.document_id,
            transaction_type="create",
            origin=current_user.department,
            destination=current_user.department,
            action_by_name=current_user.full_name,
            handled_by_user_id=current_user.user.user_id,
            status=auto_status,
        ))
        db.session.commit()
        flash(f"Document {record.document_code} added successfully.", "success")
        return redirect(url_for("main.document_detail", record_id=record.document_id))

    return render_template("admin/new_doc.html", users=dept_accounts,
                           document_type=document_type, document_status=document_status,
                           departments=departments)


# ---------------------------------------------------------------------------
# Incoming / Outgoing / Processing / Archived / Assigned
# ---------------------------------------------------------------------------

@bp.route("/incoming")
@login_required
def incoming_documents():
    q = request.args.get("q", "").strip()
    dept = current_user.department

    records = (visible_documents(dept)
               .filter(Document.current_department_id == get_dept_id(dept))
               .filter(Document.status.notin_(list(COMPLETED_STATUSES)))
               .order_by(Document.updated_at.desc()).all())

    already_received_ids = (
        db.session.query(Transaction.document_id)
        .filter_by(transaction_type="received", destination=dept)
        .subquery()
    )
    RejH = aliased(Transaction)
    pending_q = (
        Transaction.query
        .filter_by(transaction_type="transfer", destination=dept)
        .filter(~Transaction.document_id.in_(already_received_ids))
        .filter(
            ~db.session.query(RejH).filter(
                RejH.document_id == Transaction.document_id,
                RejH.transaction_type == "rejected_transfer",
                RejH.destination == dept,
                RejH.datetime > Transaction.datetime
            ).exists()
        )
        .order_by(Transaction.datetime.desc())
    )

    history_q = (
        Transaction.query
        .filter(Transaction.destination == dept)
        .filter(Transaction.transaction_type.in_(["received", "rejected_transfer"]))
        .filter(Transaction.document_id.in_(
            db.session.query(Transaction.document_id)
            .filter_by(transaction_type="transfer", destination=dept)
        ))
        .order_by(Transaction.datetime.desc())
    )

    pending_transfers = pending_q.all()
    transfer_history  = history_q.all()

    if q:
        ql = q.lower()
        pending_transfers = [
            h for h in pending_transfers
            if ql in (h.document.document_code or "").lower()
            or ql in (h.document.title or "").lower()
            or ql in (h.origin or "").lower()
            or ql in (h.action_by_name or "").lower()
        ]
        transfer_history = [
            h for h in transfer_history
            if ql in (h.document.document_code or "").lower()
            or ql in (h.document.title or "").lower()
            or ql in (h.origin or "").lower()
        ]

    return render_template("incoming_doc.html", records=records,
                           pending_transfers=pending_transfers,
                           transfer_history=transfer_history, q=q)


@bp.route("/outgoing")
@login_required
def outgoing_documents():
    dept = current_user.department
    outgoing = (Transaction.query
                .filter_by(transaction_type="transfer", origin=dept)
                .order_by(Transaction.datetime.desc()).all())

    my_records = (Document.query
                  .filter(Document.current_department_id == get_dept_id(dept))
                  .filter(Document.received_by == current_user.full_name)
                  .filter(Document.status == "Assigned")
                  .all())

    pending_transfer_ids  = set()
    received_transfer_ids = set()
    rejected_transfer_ids = set()

    for record in my_records:
        last_transfer = (
            Transaction.query
            .filter_by(document_id=record.document_id, transaction_type="transfer")
            .order_by(Transaction.datetime.desc())
            .first()
        )
        if last_transfer:
            was_received = (
                Transaction.query
                .filter_by(document_id=record.document_id, transaction_type="received",
                           destination=last_transfer.destination)
                .filter(Transaction.datetime > last_transfer.datetime)
                .first()
            )
            was_rejected = (
                Transaction.query
                .filter_by(document_id=record.document_id, transaction_type="rejected_transfer",
                           destination=last_transfer.destination)
                .filter(Transaction.datetime > last_transfer.datetime)
                .first()
            )
            if was_received:
                received_transfer_ids.add(record.document_id)
            elif was_rejected:
                rejected_transfer_ids.add(record.document_id)
            else:
                pending_transfer_ids.add(record.document_id)

    transfer_status = {}
    for h in outgoing:
        was_received = (
            Transaction.query
            .filter_by(document_id=h.document_id, transaction_type="received",
                       destination=h.destination)
            .filter(Transaction.datetime > h.datetime)
            .first()
        )
        was_rejected = (
            Transaction.query
            .filter_by(document_id=h.document_id, transaction_type="rejected_transfer",
                       destination=h.destination)
            .filter(Transaction.datetime > h.datetime)
            .first()
        )
        if was_received:
            transfer_status[h.transaction_id] = "received"
        elif was_rejected:
            transfer_status[h.transaction_id] = "rejected"
        else:
            transfer_status[h.transaction_id] = "pending"

    departments = Department.query.filter(Department.department_name != dept).all()

    # Compute SVP auto-destinations for assigned records
    svp_auto_dests = {}  # {doc_id: (next_status, next_dept)}
    for r in my_records:
        if is_svp_doc(r):
            step = get_svp_next_step(r.status)
            if step:
                svp_auto_dests[r.document_id] = step

    return render_template("outgoing_doc.html", outgoing=outgoing, records=my_records,
                           departments=departments,
                           pending_transfer_ids=pending_transfer_ids,
                           received_transfer_ids=received_transfer_ids,
                           transfer_status=transfer_status,
                           svp_auto_dests=svp_auto_dests)


@bp.route("/processing")
@login_required
def processing_documents():
    dept_id = get_dept_id(current_user.department)
    records = (visible_documents(current_user.department)
               .filter(Document.current_department_id == dept_id)
               .filter(Document.status.notin_(list(COMPLETED_STATUSES)))
               .filter(Document.status != "Assigned")
               .filter(or_(Document.received_by == None, Document.received_by == ""))
               .order_by(Document.updated_at.desc()).all())
    dept_accounts = get_dept_users(current_user.department, active_only=True)
    return render_template("processing_doc.html", records=records, dept_users=dept_accounts)


@bp.route("/archived")
@login_required
def archived_documents():
    records = (visible_documents(current_user.department)
               .filter(Document.status.in_(list(COMPLETED_STATUSES)))
               .order_by(Document.updated_at.desc()).all())
    return render_template("closed.html", records=records)


@bp.route("/assigned")
@login_required
def assigned_documents():
    dept_id = get_dept_id(current_user.department)
    records = (visible_documents(current_user.department)
               .filter(Document.current_department_id == dept_id)
               .filter(Document.status == "Assigned")
               .order_by(Document.updated_at.desc()).all())
    dept_accounts = get_dept_users(current_user.department, active_only=True)
    return render_template("assigned.html", records=records, dept_users=dept_accounts)


# ---------------------------------------------------------------------------
# Transfer / Receive / Reject / Cancel / Assign
# ---------------------------------------------------------------------------

@bp.route("/documents/transfer/<int:record_id>", methods=["POST"])
@login_required
def transfer_document(record_id):
    record = db.session.get(Document, record_id) or abort(404)

    if record.status in COMPLETED_STATUSES:
        return jsonify(success=False, message="This document is already completed.")

    if record.received_by != current_user.full_name:
        return jsonify(success=False, message="Only the assigned staff can release this document.")

    if record.status != "Assigned":
        return jsonify(success=False, message="Document must be in Assigned status before release.")

    data    = request.get_json() or {}
    to_dept = data.get("to_department", "").strip()
    remarks = data.get("remarks", "").strip()

    # ---- SVP automated routing ----
    if is_svp_doc(record):
        step = get_svp_next_step(record.status)
        if step is None:
            return jsonify(success=False, message="This SVP document has reached the end of its workflow.")
        next_status, auto_dest = step
        # Admin may override destination, otherwise use auto
        if not to_dept or to_dept == "auto":
            to_dept = auto_dest or current_user.department

        # Update status and route
        record.received_by = ""
        record.status      = next_status
        record.updated_at  = datetime.now(timezone.utc)
        if to_dept and to_dept != current_user.department:
            record.current_department_id = get_dept_id(to_dept) or record.current_department_id
        db.session.add(make_transaction(
            document_id=record.document_id,
            transaction_type="transfer",
            origin=current_user.department,
            destination=to_dept,
            action_by_name=current_user.full_name,
            handled_by_user_id=current_user.user.user_id,
            status=next_status,
            remarks=remarks,
        ))
        db.session.commit()
        return jsonify(success=True,
                       message=f"SVP document advanced to '{next_status}' → routed to {to_dept}.",
                       record_id=record.document_id, status=next_status)
    # ---- end SVP ----

    if not to_dept:
        return jsonify(success=False, message="Please select a target department.")
    if to_dept == current_user.department:
        return jsonify(success=False, message="Cannot transfer to your own department.")

    last_transfer = (
        Transaction.query
        .filter_by(document_id=record.document_id, transaction_type="transfer")
        .order_by(Transaction.datetime.desc())
        .first()
    )
    if last_transfer:
        was_received = (
            Transaction.query
            .filter_by(document_id=record.document_id, transaction_type="received",
                       destination=last_transfer.destination)
            .filter(Transaction.datetime > last_transfer.datetime)
            .first()
        )
        was_rejected = (
            Transaction.query
            .filter_by(document_id=record.document_id, transaction_type="rejected_transfer",
                       destination=last_transfer.destination)
            .filter(Transaction.datetime > last_transfer.datetime)
            .first()
        )
        if not was_received and not was_rejected:
            return jsonify(
                success=False,
                message=f"Document is still pending with {last_transfer.destination}. "
                        f"Wait for them to receive or reject it."
            )

    new_status = get_next_status(record.status)
    record.received_by = ""
    record.status      = new_status
    record.updated_at  = datetime.now(timezone.utc)
    db.session.add(make_transaction(
        document_id=record.document_id,
        transaction_type="transfer",
        origin=current_user.department,
        destination=to_dept,
        action_by_name=current_user.full_name,
        handled_by_user_id=current_user.user.user_id,
        status=new_status,
        remarks=remarks,
    ))
    db.session.commit()
    return jsonify(success=True, message=f"Document released to {to_dept}.",
                   record_id=record.document_id, status=new_status)


@bp.route("/documents/cancel-transfer/<int:transfer_history_id>", methods=["POST"])
@login_required
def cancel_transfer(transfer_history_id):
    transfer = db.session.get(Transaction, transfer_history_id) or abort(404)
    if transfer.origin != current_user.department:
        return jsonify(success=False, message="You can only cancel transfers from your department.")
    was_received = (
        Transaction.query
        .filter_by(document_id=transfer.document_id, transaction_type="received",
                   destination=transfer.destination)
        .first()
    )
    if was_received:
        return jsonify(success=False, message="Cannot cancel a transfer that has already been received.")
    db.session.delete(transfer)
    db.session.commit()
    return jsonify(success=True, message="Transfer cancelled successfully.")


@bp.route("/documents/receive/<int:record_id>", methods=["POST"])
@login_required
def receive_document(record_id):
    record = db.session.get(Document, record_id) or abort(404)

    already_received_ids = (
        db.session.query(Transaction.document_id)
        .filter_by(transaction_type="received", destination=current_user.department)
        .subquery()
    )
    pending = (
        Transaction.query
        .filter_by(transaction_type="transfer", destination=current_user.department,
                   document_id=record_id)
        .filter(~Transaction.document_id.in_(already_received_ids))
        .order_by(Transaction.datetime.desc())
        .first()
    )

    if pending:
        record.current_department_id = get_dept_id(current_user.department)

    record.received_by = current_user.full_name
    record.status      = "Assigned"
    record.updated_at  = datetime.now(timezone.utc)

    db.session.add(make_transaction(
        document_id=record.document_id,
        transaction_type="received",
        origin=pending.origin if pending else record.department,
        destination=current_user.department,
        action_by_name=current_user.full_name,
        handled_by_user_id=current_user.user.user_id,
        status="Assigned",
    ))
    db.session.commit()
    return jsonify(success=True, message="Document received and assigned to you.",
                   record_id=record.document_id, new_department=current_user.department,
                   status="Assigned", received_by=current_user.full_name)


@bp.route("/documents/reject/<int:record_id>", methods=["POST"])
@login_required
def reject_document(record_id):
    record = db.session.get(Document, record_id) or abort(404)
    already_received_ids = (
        db.session.query(Transaction.document_id)
        .filter_by(transaction_type="received", destination=current_user.department)
        .subquery()
    )
    pending = (
        Transaction.query
        .filter_by(transaction_type="transfer", destination=current_user.department,
                   document_id=record_id)
        .filter(~Transaction.document_id.in_(already_received_ids))
        .order_by(Transaction.datetime.desc())
        .first()
    )
    if not pending:
        return jsonify(success=False, message="No pending transfer found to reject.")

    previous_history = (
        Transaction.query
        .filter_by(document_id=record.document_id)
        .filter(Transaction.datetime < pending.datetime)
        .order_by(Transaction.datetime.desc())
        .first()
    )
    if previous_history:
        record.status     = previous_history.status
        record.updated_at = datetime.now(timezone.utc)

    db.session.add(make_transaction(
        document_id=record.document_id,
        transaction_type="rejected_transfer",
        origin=pending.origin,
        destination=current_user.department,
        action_by_name=current_user.full_name,
        handled_by_user_id=current_user.user.user_id,
        status=record.status,
    ))
    db.session.commit()
    return jsonify(success=True,
                   message=f"Transfer rejected. Document returned to {pending.origin}.",
                   record_id=record.document_id)


@bp.route("/documents/assign/<int:record_id>", methods=["POST"])
@login_required
@role_required("admin")
def assign_document(record_id):
    record = db.session.get(Document, record_id) or abort(404)
    data        = request.get_json() or {}
    assigned_to = data.get("assigned_to", "").strip()
    remarks     = data.get("remarks", "").strip()
    if not assigned_to:
        return jsonify(success=False, message="Please select a staff to assign.")
    record.received_by = assigned_to
    record.status      = "Assigned"
    record.updated_at  = datetime.now(timezone.utc)
    db.session.add(make_transaction(
        document_id=record.document_id,
        transaction_type="assigned",
        origin=current_user.department,
        destination=current_user.department,
        action_by_name=current_user.full_name,
        handled_by_user_id=current_user.user.user_id,
        status="Assigned",
        remarks=f"Assigned to {assigned_to}" + (f" \u2014 {remarks}" if remarks else ""),
    ))
    db.session.commit()
    return jsonify(success=True, message=f"Document assigned to {assigned_to}.")


@bp.route("/documents/pullout/<int:record_id>", methods=["POST"])
@login_required
@role_required("admin")
def pullout_document(record_id):
    """Pull out a document from wherever it is and move it to a specified department."""
    record = db.session.get(Document, record_id) or abort(404)
    data = request.get_json() or {}
    target_dept = data.get("to_department", current_user.department).strip()
    remarks     = data.get("remarks", "").strip()

    if not target_dept:
        target_dept = current_user.department

    prev_dept = record.department or current_user.department
    new_dept_id = get_dept_id(target_dept) or get_dept_id(current_user.department)

    record.current_department_id = new_dept_id
    record.received_by            = ""
    record.status                 = "Pulled Out"
    record.updated_at             = datetime.now(timezone.utc)

    db.session.add(make_transaction(
        document_id=record.document_id,
        transaction_type="pullout",
        origin=prev_dept,
        destination=target_dept,
        action_by_name=current_user.full_name,
        handled_by_user_id=current_user.user.user_id,
        status="Pulled Out",
        remarks=f"Pulled out by {current_user.full_name}" + (f" — {remarks}" if remarks else ""),
    ))
    db.session.commit()
    return jsonify(success=True,
                   message=f"Document pulled out and moved to {target_dept}.",
                   record_id=record.document_id)
# ---------------------------------------------------------------------------

@bp.route("/trace")
@login_required
def trace():
    q = request.args.get("q", "").strip()
    results = []
    if q:
        results = (visible_documents(current_user.department)
                   .filter(or_(Document.document_code.ilike(f"%{q}%"),
                               Document.title.ilike(f"%{q}%")))
                   .all())
    return render_template("trace.html", q=q, results=results)


# ---------------------------------------------------------------------------
# Reports (Summarized only — no export, no bottlenecks)
# ---------------------------------------------------------------------------

@bp.route("/reports")
@login_required
@role_required("admin")
def reports():
    date_from = request.args.get("from", "").strip()
    date_to   = request.args.get("to",   "").strip()

    records_q = visible_documents(current_user.department)
    if date_from:
        try:
            records_q = records_q.filter(
                Document.datetime >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            records_q = records_q.filter(
                Document.datetime <= datetime.strptime(date_to, "%Y-%m-%d"))
        except ValueError:
            pass

    all_records  = records_q.order_by(Document.datetime.desc()).all()
    total_docs   = len(all_records)
    closed_docs  = sum(1 for r in all_records if r.status in COMPLETED_STATUSES)
    in_process   = total_docs - closed_docs
    total_amount = sum(r.amount or 0 for r in all_records)

    dept_dict    = defaultdict(int)
    status_dict  = defaultdict(int)
    type_dict    = defaultdict(int)
    fin_dict     = defaultdict(float)
    monthly_dict = defaultdict(int)

    for r in all_records:
        dept_dict[r.department or "—"] += 1
        status_dict[r.status] += 1
        type_dict[r.doc_type] += 1
        if r.amount:
            fin_dict[r.doc_type] += r.amount
        if r.datetime:
            monthly_dict[r.datetime.strftime("%Y-%m")] += 1

    return render_template("reports.html",
                           total_docs=total_docs, in_process=in_process,
                           closed_docs=closed_docs, total_amount=total_amount,
                           date_from=date_from, date_to=date_to,
                           dept_summary=sorted(dept_dict.items(),     key=lambda x: x[1], reverse=True),
                           status_summary=sorted(status_dict.items(), key=lambda x: x[1], reverse=True),
                           type_summary=sorted(type_dict.items(),     key=lambda x: x[1], reverse=True),
                           financial=sorted(fin_dict.items(),         key=lambda x: x[1], reverse=True),
                           monthly=sorted(monthly_dict.items()))


# ---------------------------------------------------------------------------
# Office Settings
# ---------------------------------------------------------------------------

@bp.route("/office_settings", methods=["GET", "POST"])
@login_required
@role_required("admin")
def office_settings():
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "add_doc_type":
            name = request.form.get("name", "").strip()
            if name and not DocumentType.query.filter_by(type_name=name).first():
                db.session.add(DocumentType(type_name=name))
                db.session.commit()
                flash(f'Document type "{name}" added.', "success")
            elif name:
                flash("Document type already exists.", "warning")
        elif action == "delete_doc_type":
            dt = db.session.get(DocumentType, request.form.get("id"))
            if dt:
                db.session.delete(dt)
                db.session.commit()
                flash(f'"{dt.type_name}" deleted.', "info")
        elif action == "add_status":
            name = request.form.get("name", "").strip()
            if name and not DocumentStatus.query.filter_by(name=name).first():
                db.session.add(DocumentStatus(name=name))
                db.session.commit()
                flash(f'Status "{name}" added.', "success")
            elif name:
                flash("Status already exists.", "warning")
        elif action == "delete_status":
            ds = db.session.get(DocumentStatus, request.form.get("id"))
            if ds:
                db.session.delete(ds)
                db.session.commit()
                flash(f'"{ds.name}" deleted.', "info")
        return redirect(url_for("main.office_settings"))
    doc_types    = DocumentType.query.order_by(DocumentType.type_name).all()
    doc_statuses = DocumentStatus.query.order_by(DocumentStatus.name).all()
    staff_count  = Account.query.join(User).filter(
        User.department_id == get_dept_id(current_user.department)).count()
    return render_template("office_settings.html", doc_types=doc_types,
                           doc_statuses=doc_statuses, staff_count=staff_count)


# ---------------------------------------------------------------------------
# Activity Logs
# ---------------------------------------------------------------------------

@bp.route("/activity_logs")
@login_required
@role_required("admin")
def activity_logs():
    dept = current_user.department
    action_filter = request.args.get("action", "").strip()
    records_q = (Transaction.query
                 .join(Document, Transaction.document_id == Document.document_id)
                 .filter(
                     (Transaction.origin == dept) | (Transaction.destination == dept)
                 )
                 .order_by(Transaction.datetime.desc()))
    if action_filter:
        records_q = records_q.filter(Transaction.transaction_type == action_filter)
    records = records_q.all()
    return render_template("logs.html", records=records, action_filter=action_filter)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@bp.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403


@bp.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404
