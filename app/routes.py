import csv
import io
import uuid
from collections import defaultdict

from flask import Blueprint, Response, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from sqlalchemy import func, or_
from sqlalchemy.orm import aliased
from datetime import datetime, date, timezone

from . import db
from .models import Record, Department, RecordHistory, User, DocumentType, DocumentStatus
from .decorators import role_required

bp = Blueprint("main", __name__)


def visible_documents(department):
    # Get records that have been received by or transferred to this department
    processed_record_ids = (
        db.session.query(RecordHistory.record_id).filter(
            (RecordHistory.from_department == department)
            | (RecordHistory.to_department == department)
        ).subquery()
    )
    
    # Get records with pending transfers TO this department (not yet received)
    pending_transfer_ids = (
        db.session.query(RecordHistory.record_id).filter(
            RecordHistory.action_type == "transfer",
            RecordHistory.to_department == department,
            ~RecordHistory.record_id.in_(
                db.session.query(RecordHistory.record_id).filter(
                    RecordHistory.action_type == "received",
                    RecordHistory.to_department == department
                )
            )
        ).subquery()
    )
    
    return Record.query.filter(
        or_(
            Record.department == department,
            Record.id.in_(processed_record_ids),
            Record.id.in_(pending_transfer_ids),
        )
    )


@bp.route("/")
def home():
    return render_template("portal.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    records_q = visible_documents(current_user.department)
    stats = {
        "total_documents": records_q.count(),
        "closed": records_q.filter(Record.status == "Closed").count(),
        "completed": records_q.filter(Record.status == "With Checked").count(),
        "in_process": records_q.filter(Record.status.notin_(["Closed", "With Checked"])).count(),
    }
    status_data = records_q.with_entities(Record.status, func.count(Record.id)).group_by(Record.status).all()
    records = records_q.order_by(Record.created_at.desc()).limit(5).all()
    return render_template("dashboard.html", stats=stats, charts_combined=status_data, records=records)


@bp.route("/documents")
@login_required
def documents():
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    records_q = visible_documents(current_user.department)
    if q:
        records_q = records_q.filter(
            or_(Record.document_id.ilike(f"%{q}%"), Record.title.ilike(f"%{q}%"))
        )
    if status_filter == "closed":
        records_q = records_q.filter(Record.status == "Closed")
    elif status_filter == "completed":
        records_q = records_q.filter(Record.status == "With Checked")
    elif status_filter == "inprocess":
        records_q = records_q.filter(Record.status.notin_(["Closed", "With Checked"]))
    records = records_q.order_by(Record.date_received.desc()).all()
    return render_template("documents.html", records=records, q=q, status_filter=status_filter)


@bp.route("/documents/<int:record_id>")
@login_required
def document_detail(record_id):
    record = visible_documents(current_user.department).filter_by(id=record_id).first()
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
    record = db.session.get(Record, record_id) or abort(404)
    if request.method == "POST":
        record.title = request.form.get("title", record.title)
        record.doc_type = request.form.get("doc_type", record.doc_type)
        record.implementing_office = request.form.get("implementing_office", record.implementing_office)
        amount = request.form.get("amount")
        record.amount = float(amount) if amount else None
        record.received_by = request.form.get("received_by", record.received_by)
        record.status = request.form.get("status", record.status)
        record.remarks = request.form.get("remarks", record.remarks)
        date_str = request.form.get("date_received", "").strip()
        if date_str:
            try:
                record.date_received = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                pass
        record.updated_at = datetime.now(timezone.utc)
        db.session.add(RecordHistory(
            record_id=record.id, action_type="edit",
            from_department=current_user.department, to_department=record.department,
            action_by=current_user.full_name, status=record.status,
            timestamp=datetime.now(timezone.utc),
        ))
        db.session.commit()
        flash("Document updated successfully.", "success")
        return redirect(url_for("main.document_detail", record_id=record.id))
    departments = Department.query.all()
    document_types = DocumentType.query.all()
    document_statuses = DocumentStatus.query.all()
    return render_template("document_edit.html", record=record, departments=departments,
                           document_types=document_types, document_statuses=document_statuses)


@bp.route("/documents/delete/<int:record_id>", methods=["POST"])
@login_required
@role_required("admin")
def delete_document(record_id):
    record = db.session.get(Record, record_id) or abort(404)
    db.session.delete(record)
    db.session.commit()
    flash("Document deleted.", "info")
    return redirect(url_for("main.documents"))


@bp.route("/documents/close/<int:record_id>", methods=["POST"])
@login_required
@role_required("admin")
def close_document(record_id):
    record = db.session.get(Record, record_id) or abort(404)
    record.status = "Closed"
    record.updated_at = datetime.now(timezone.utc)
    db.session.add(RecordHistory(
        record_id=record.id, action_type="close",
        from_department=current_user.department, to_department=record.department,
        action_by=current_user.full_name, status="Closed",
        timestamp=datetime.now(timezone.utc),
    ))
    db.session.commit()
    return jsonify(success=True)


@bp.route("/users")
@login_required
@role_required("admin")
def users():
    dept_users = User.query.filter_by(department=current_user.department).all()
    return render_template("users.html", users=dept_users)


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
        department=current_user.department,
    )
    user.set_password(request.form["password"])
    db.session.add(user)
    db.session.commit()
    flash("User added successfully.", "success")
    return redirect(url_for("main.users"))


@bp.route("/admin/users/edit/<int:id>", methods=["POST"])
@login_required
@role_required("admin")
def edit_user(id):
    user = db.session.get(User, id) or abort(404)
    # Prevent editing other permanent admins, but allow editing temp-promoted users
    if user.role == "admin" and user.id != current_user.id and not user.is_temp_admin:
        flash("Cannot edit other admin accounts.", "danger")
        return redirect(url_for("main.users"))
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    if not full_name:
        flash("Full name is required.", "danger")
        return redirect(url_for("main.users"))
    user.full_name = full_name
    if email and email != user.email:
        if not User.query.filter_by(email=email).first():
            user.email = email
        else:
            flash("Email already in use.", "warning")
            return redirect(url_for("main.users"))
    new_password = request.form.get("new_password", "").strip()
    if new_password:
        if len(new_password) < 6:
            flash("Password must be at least 6 characters.", "warning")
            return redirect(url_for("main.users"))
        user.set_password(new_password)
    # Handle temporary admin access toggle
    give_admin = request.form.get("give_admin_access") == "on"
    if give_admin:
        user.role = "admin"
        user.is_temp_admin = True
    else:
        user.role = "user"
        user.is_temp_admin = False
    db.session.commit()
    flash(f"User {full_name} updated successfully.", "success")
    return redirect(url_for("main.users"))


@bp.route("/admin/users/toggle/<int:id>", methods=["POST"])
@login_required
@role_required("admin")
def toggle_user(id):
    user = db.session.get(User, id) or abort(404)
    if user.role == "admin":
        flash("Cannot deactivate admin accounts.", "warning")
        return redirect(url_for("main.users"))
    user.is_deactivated = not user.is_deactivated
    db.session.commit()
    return redirect(url_for("main.users"))


@bp.route("/admin/users/delete/<int:id>", methods=["POST"])
@login_required
@role_required("admin")
def delete_user(id):
    user = db.session.get(User, id) or abort(404)
    if user.role == "admin":
        flash("Cannot delete admin accounts.", "danger")
        return redirect(url_for("main.users"))
    db.session.delete(user)
    db.session.commit()
    flash(f"User {user.full_name} deleted.", "success")
    return redirect(url_for("main.users"))


@bp.route("/add_document", methods=["GET", "POST"])
@login_required
@role_required("admin")
def add_document():
    dept_users = User.query.filter_by(department=current_user.department).all()
    document_type = DocumentType.query.all()
    document_status = DocumentStatus.query.all()
    departments = Department.query.all()

    if request.method == "POST":
        date_str = request.form.get("date_received", "").strip()
        try:
            date_received = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            date_received = date.today()

        amount_input = request.form.get("amount", "").strip()
        amount = float(amount_input) if amount_input else None

        # Auto-assign the first status from DocumentStatus table
        first_status = DocumentStatus.query.order_by(DocumentStatus.id.asc()).first()
        auto_status = first_status.name if first_status else "Pending"

        record = Record(
            document_id=f"DOC-{uuid.uuid4().hex[:8].upper()}",
            title=request.form["title"],
            doc_type=request.form["doc_type"],
            department=current_user.department,
            implementing_office=current_user.department,
            date_received=date_received,
            amount=amount,
            released_by=current_user.full_name,
            received_by=request.form.get("received_by", current_user.full_name),
            status=auto_status,
            priority=request.form.get("priority", "Normal"),
            remarks=request.form.get("remarks", ""),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.session.add(record)
        db.session.flush()
        db.session.add(RecordHistory(
            record_id=record.id, action_type="create",
            from_department=current_user.department, to_department=current_user.department,
            action_by=current_user.full_name, status=auto_status,
            timestamp=datetime.now(timezone.utc),
        ))
        db.session.commit()
        flash(f"Document {record.document_id} added successfully.", "success")
        return redirect(url_for("main.documents"))

    return render_template("admin/new_doc.html", users=dept_users,
                           document_type=document_type, document_status=document_status,
                           departments=departments)


@bp.route("/incoming")
@login_required
def incoming_documents():
    records = (visible_documents(current_user.department)
               .filter(Record.department == current_user.department)
               .filter(Record.status != "Closed")
               .order_by(Record.updated_at.desc()).all())
    already_received_ids = (
        db.session.query(RecordHistory.record_id)
        .filter_by(action_type="received", to_department=current_user.department)
        .subquery()
    )
    # Correlated alias: exclude a transfer if a rejection for the same record exists AFTER it.
    # This way, re-transfers after a rejection will correctly reappear.
    RejH = aliased(RecordHistory)
    pending_transfers = (
        RecordHistory.query
        .filter_by(action_type="transfer", to_department=current_user.department)
        .filter(~RecordHistory.record_id.in_(already_received_ids))
        .filter(
            ~db.session.query(RejH).filter(
                RejH.record_id == RecordHistory.record_id,
                RejH.action_type == "rejected_transfer",
                RejH.to_department == current_user.department,
                RejH.timestamp > RecordHistory.timestamp
            ).exists()
        )
        .order_by(RecordHistory.timestamp.desc()).all()
    )
    
    # Get transfer history (received and rejected)
    transfer_history = (
        RecordHistory.query
        .filter(RecordHistory.to_department == current_user.department)
        .filter(RecordHistory.action_type.in_(["received", "rejected_transfer"]))
        .filter(RecordHistory.record_id.in_(
            db.session.query(RecordHistory.record_id)
            .filter_by(action_type="transfer", to_department=current_user.department)
        ))
        .order_by(RecordHistory.timestamp.desc()).all()
    )
    
    return render_template("incoming_doc.html", records=records, pending_transfers=pending_transfers,
                          transfer_history=transfer_history)


@bp.route("/outgoing")
@login_required
def outgoing_documents():
    outgoing = (RecordHistory.query
                .filter_by(action_type="transfer", from_department=current_user.department)
                .order_by(RecordHistory.timestamp.desc()).all())
    my_records = (visible_documents(current_user.department)
                  .filter(Record.department == current_user.department)
                  .filter(Record.status != "Closed").all())
    
    # Get records with unresolved pending transfers
    pending_transfer_ids = set()
    received_transfer_ids = set()
    rejected_transfer_ids = set()
    
    for record in my_records:
        last_transfer = (
            RecordHistory.query
            .filter_by(record_id=record.id, action_type="transfer")
            .order_by(RecordHistory.timestamp.desc())
            .first()
        )
        if last_transfer:
            # Check if this transfer has been received or rejected AFTER the transfer timestamp
            was_received = (
                RecordHistory.query
                .filter_by(
                    record_id=record.id,
                    action_type="received",
                    to_department=last_transfer.to_department
                )
                .filter(RecordHistory.timestamp > last_transfer.timestamp)
                .first()
            )
            was_rejected = (
                RecordHistory.query
                .filter_by(
                    record_id=record.id,
                    action_type="rejected_transfer",
                    to_department=last_transfer.to_department
                )
                .filter(RecordHistory.timestamp > last_transfer.timestamp)
                .first()
            )
            if was_received:
                received_transfer_ids.add(record.id)
            elif was_rejected:
                rejected_transfer_ids.add(record.id)
            else:
                pending_transfer_ids.add(record.id)

    # Get transfer status for outgoing history
    transfer_status = {}
    for h in outgoing:
        was_received = (
            RecordHistory.query
            .filter_by(
                record_id=h.record_id,
                action_type="received",
                to_department=h.to_department
            )
            .filter(RecordHistory.timestamp > h.timestamp)
            .first()
        )
        was_rejected = (
            RecordHistory.query
            .filter_by(
                record_id=h.record_id,
                action_type="rejected_transfer",
                to_department=h.to_department
            )
            .filter(RecordHistory.timestamp > h.timestamp)
            .first()
        )
        if was_received:
            transfer_status[h.id] = 'received'
        elif was_rejected:
            transfer_status[h.id] = 'rejected'
        else:
            transfer_status[h.id] = 'pending'
    
    departments = Department.query.filter(Department.name != current_user.department).all()
    document_statuses = DocumentStatus.query.all()
    return render_template("outgoing_doc.html", outgoing=outgoing, records=my_records,
                           departments=departments, document_statuses=document_statuses,
                           pending_transfer_ids=pending_transfer_ids,
                           received_transfer_ids=received_transfer_ids,
                           transfer_status=transfer_status)


@bp.route("/processing")
@login_required
def processing_documents():
    records = (visible_documents(current_user.department)
               .filter(Record.status.notin_(["Closed", "With Checked"]))
               .order_by(Record.updated_at.desc()).all())
    return render_template("processing_doc.html", records=records)


@bp.route("/archived")
@login_required
def archived_documents():
    records = (visible_documents(current_user.department)
               .filter(Record.status == "Closed")
               .order_by(Record.updated_at.desc()).all())
    return render_template("closed.html", records=records)


@bp.route("/documents/transfer/<int:record_id>", methods=["POST"])
@login_required
def transfer_document(record_id):
    record = db.session.get(Record, record_id) or abort(404)
    data = request.get_json() or {}
    to_dept = data.get("to_department", "").strip()
    new_status = data.get("status", record.status).strip()
    remarks = data.get("remarks", "").strip()
    
    if not to_dept:
        return jsonify(success=False, message="Please select a target department.")
    
    # Get the most recent transfer for this document
    last_transfer = (
        RecordHistory.query
        .filter_by(record_id=record.id, action_type="transfer")
        .order_by(RecordHistory.timestamp.desc())
        .first()
    )
    
    if last_transfer:
        # Allow re-transfer only if the last transfer was received OR rejected
        was_received = (
            RecordHistory.query
            .filter_by(
                record_id=record.id,
                action_type="received",
                to_department=last_transfer.to_department
            )
            .filter(RecordHistory.timestamp > last_transfer.timestamp)
            .first()
        )
        was_rejected = (
            RecordHistory.query
            .filter_by(
                record_id=record.id,
                action_type="rejected_transfer",
                to_department=last_transfer.to_department
            )
            .filter(RecordHistory.timestamp > last_transfer.timestamp)
            .first()
        )

        if not was_received and not was_rejected:
            return jsonify(
                success=False,
                message=f"Document is still pending with {last_transfer.to_department}. Please wait for them to receive or reject it before transferring again."
            )
    
    db.session.add(RecordHistory(
        record_id=record.id, action_type="transfer",
        from_department=current_user.department, to_department=to_dept,
        action_by=current_user.full_name, status=new_status, remarks=remarks,
        timestamp=datetime.now(timezone.utc),
    ))
    record.status = new_status
    record.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(success=True, message=f"Document transferred to {to_dept}.",
                   record_id=record.id, status=record.status)


@bp.route("/documents/cancel-transfer/<int:transfer_history_id>", methods=["POST"])
@login_required
def cancel_transfer(transfer_history_id):
    transfer = db.session.get(RecordHistory, transfer_history_id) or abort(404)
    
    # Verify the user is from the sending department
    if transfer.from_department != current_user.department:
        return jsonify(success=False, message="You can only cancel transfers from your department.")
    
    # Check if transfer has been received
    was_received = (
        RecordHistory.query
        .filter_by(
            record_id=transfer.record_id,
            action_type="received",
            to_department=transfer.to_department
        )
        .first()
    )
    
    if was_received:
        return jsonify(success=False, message="Cannot cancel a transfer that has already been received.")
    
    # Delete the transfer record
    db.session.delete(transfer)
    db.session.commit()
    
    return jsonify(success=True, message="Transfer cancelled successfully.")


@bp.route("/documents/receive/<int:record_id>", methods=["POST"])
@login_required
def receive_document(record_id):
    record = db.session.get(Record, record_id) or abort(404)
    
    # For pending transfers - check if there's a pending transfer to our department
    already_received_ids = (
        db.session.query(RecordHistory.record_id)
        .filter_by(action_type="received", to_department=current_user.department)
        .subquery()
    )
    pending = (RecordHistory.query
               .filter_by(action_type="transfer", to_department=current_user.department, record_id=record_id)
               .filter(~RecordHistory.record_id.in_(already_received_ids))
               .order_by(RecordHistory.timestamp.desc()).first())
    
    # Update department if receiving from transfer
    if pending:
        record.department = current_user.department

    # Auto-advance status to the next step on receive
    current_status = DocumentStatus.query.filter_by(name=record.status).first()
    if current_status:
        next_status = (DocumentStatus.query
                       .filter(DocumentStatus.id > current_status.id)
                       .order_by(DocumentStatus.id.asc())
                       .first())
        record.status = next_status.name if next_status else "Closed"
    else:
        record.status = "Closed"

    record.updated_at = datetime.now(timezone.utc)
    db.session.add(RecordHistory(
        record_id=record.id, action_type="received",
        from_department=pending.from_department if pending else record.department,
        to_department=current_user.department,
        action_by=current_user.full_name, status=record.status,
        timestamp=datetime.now(timezone.utc),
    ))
    db.session.commit()
    return jsonify(success=True, message="Document received successfully.",
                   record_id=record.id, new_department=current_user.department,
                   status=record.status, received_by=record.received_by)


@bp.route("/documents/reject/<int:record_id>", methods=["POST"])
@login_required
def reject_document(record_id):
    record = db.session.get(Record, record_id) or abort(404)
    
    # Get the pending transfer
    already_received_ids = (
        db.session.query(RecordHistory.record_id)
        .filter_by(action_type="received", to_department=current_user.department)
        .subquery()
    )
    pending = (RecordHistory.query
               .filter_by(action_type="transfer", to_department=current_user.department, record_id=record_id)
               .filter(~RecordHistory.record_id.in_(already_received_ids))
               .order_by(RecordHistory.timestamp.desc()).first())
    
    if not pending:
        return jsonify(success=False, message="No pending transfer found to reject.")
    
    db.session.add(RecordHistory(
        record_id=record.id, action_type="rejected_transfer",
        from_department=pending.from_department,
        to_department=current_user.department,
        action_by=current_user.full_name, status=record.status,
        timestamp=datetime.now(timezone.utc),
    ))
    db.session.commit()
    return jsonify(success=True, message=f"Transfer rejected. Document returned to {pending.from_department}.",
                   record_id=record.id)
@login_required
def transfer_receive():
    my_records = (visible_documents(current_user.department)
                  .filter(Record.department == current_user.department)
                  .filter(Record.status != "Closed").all())
    already_received_subq = (
        db.session.query(RecordHistory.record_id)
        .filter_by(action_type="received", to_department=current_user.department)
        .subquery()
    )
    RejH2 = aliased(RecordHistory)
    incoming_transfers = (
        RecordHistory.query
        .filter_by(action_type="transfer", to_department=current_user.department)
        .filter(~RecordHistory.record_id.in_(already_received_subq))
        .filter(
            ~db.session.query(RejH2).filter(
                RejH2.record_id == RecordHistory.record_id,
                RejH2.action_type == "rejected_transfer",
                RejH2.to_department == current_user.department,
                RejH2.timestamp > RecordHistory.timestamp
            ).exists()
        )
        .order_by(RecordHistory.timestamp.desc()).all()
    )
    departments = Department.query.filter(Department.name != current_user.department).all()
    document_statuses = DocumentStatus.query.all()
    return render_template("admin/transfer_receive.html",
                           records=my_records, incoming_transfers=incoming_transfers,
                           departments=departments, document_statuses=document_statuses)


@bp.route("/trace")
@login_required
def trace():
    q = request.args.get("q", "").strip()
    results = []
    if q:
        results = (visible_documents(current_user.department)
                   .filter(or_(Record.document_id.ilike(f"%{q}%"), Record.title.ilike(f"%{q}%")))
                   .all())
    return render_template("trace.html", q=q, results=results)


@bp.route("/analytics")
@login_required
def analytics():
    import statistics
    dept_durations = defaultdict(list)
    records = Record.query.all()
    for record in records:
        hist = sorted(record.history, key=lambda h: h.timestamp) if record.history else []
        for i in range(len(hist) - 1):
            cur, nxt = hist[i], hist[i + 1]
            if cur.to_department and cur.timestamp and nxt.timestamp:
                delta = (nxt.timestamp - cur.timestamp).total_seconds()
                if delta > 0:
                    dept_durations[cur.to_department].append(delta)

    avg_hours = {d: (sum(s) / len(s)) / 3600.0 for d, s in dept_durations.items()}
    avg_values = list(avg_hours.values())
    overall_mean = statistics.mean(avg_values) if avg_values else 0
    overall_stdev = statistics.stdev(avg_values) if len(avg_values) > 1 else 0
    threshold = overall_mean + overall_stdev
    bottlenecks = [{"department": d, "avg_hours": round(h, 2), "count": len(dept_durations[d])}
                   for d, h in avg_hours.items() if h > threshold]
    labels = list(avg_hours.keys())
    values = [round(v, 2) for v in avg_hours.values()]
    return render_template("analytics.html", labels=labels, values=values, bottlenecks=bottlenecks,
                           overall_mean=round(overall_mean, 2), overall_stdev=round(overall_stdev, 2),
                           threshold=round(threshold, 2))


@bp.route("/reports")
@login_required
def reports():
    all_records = visible_documents(current_user.department).order_by(Record.date_received.desc()).all()
    total_docs = len(all_records)
    closed_docs = sum(1 for r in all_records if r.status == "Closed")
    in_process = sum(1 for r in all_records if r.status not in ["Closed", "With Checked"])
    total_amount = sum(r.amount or 0 for r in all_records)
    dept_dict = defaultdict(int)
    status_dict = defaultdict(int)
    type_dict = defaultdict(int)
    fin_dict = defaultdict(float)
    monthly_dict = defaultdict(int)
    for r in all_records:
        dept_dict[r.department] += 1
        status_dict[r.status] += 1
        type_dict[r.doc_type] += 1
        if r.amount:
            fin_dict[r.doc_type] += r.amount
        if r.date_received:
            monthly_dict[r.date_received.strftime("%Y-%m")] += 1
    dept_dur = defaultdict(list)
    user_act_dict = defaultdict(int)
    for record in all_records:
        hist = sorted(record.history, key=lambda h: h.timestamp) if record.history else []
        for i in range(len(hist) - 1):
            cur, nxt = hist[i], hist[i + 1]
            if cur.to_department and cur.timestamp and nxt.timestamp:
                dh = (nxt.timestamp - cur.timestamp).total_seconds() / 3600.0
                if dh > 0:
                    dept_dur[cur.to_department].append(dh)
        for h in record.history:
            if h.action_by:
                user_act_dict[h.action_by] += 1
    avg_processing = {d: round(sum(t) / len(t), 2) for d, t in dept_dur.items()}
    return render_template("reports.html",
                           total_docs=total_docs, in_process=in_process,
                           closed_docs=closed_docs, total_amount=total_amount,
                           dept_summary=sorted(dept_dict.items(), key=lambda x: x[1], reverse=True),
                           status_summary=sorted(status_dict.items(), key=lambda x: x[1], reverse=True),
                           type_summary=sorted(type_dict.items(), key=lambda x: x[1], reverse=True),
                           financial=sorted(fin_dict.items(), key=lambda x: x[1], reverse=True),
                           monthly=sorted(monthly_dict.items()),
                           avg_processing=avg_processing,
                           user_activity=sorted(user_act_dict.items(), key=lambda x: x[1], reverse=True),
                           records=all_records)


@bp.route("/reports/export")
@login_required
def export_report():
    report_type = request.args.get("type", "documents")
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    records_q = visible_documents(current_user.department)
    if date_from:
        try:
            records_q = records_q.filter(Record.date_received >= datetime.strptime(date_from, "%Y-%m-%d").date())
        except ValueError:
            pass
    if date_to:
        try:
            records_q = records_q.filter(Record.date_received <= datetime.strptime(date_to, "%Y-%m-%d").date())
        except ValueError:
            pass
    records = records_q.all()
    output = io.StringIO()
    writer = csv.writer(output)
    if report_type == "history":
        writer.writerow(["Document ID", "Action", "From", "To", "By", "Status", "Timestamp"])
        for r in records:
            for h in r.history:
                writer.writerow([r.document_id, h.action_type, h.from_department,
                                  h.to_department, h.action_by, h.status, h.timestamp])
    else:
        writer.writerow(["Document ID", "Title", "Type", "Department", "Status",
                         "Amount", "Date Received", "Released By", "Received By", "Remarks"])
        for r in records:
            writer.writerow([r.document_id, r.title, r.doc_type, r.department, r.status,
                              r.amount or 0, r.date_received, r.released_by, r.received_by, r.remarks or ""])
    output.seek(0)
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename=doctrack_{report_type}_export.csv"})


@bp.route("/office_settings", methods=["GET", "POST"])
@login_required
@role_required("admin")
def office_settings():
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "add_doc_type":
            name = request.form.get("name", "").strip()
            if name and not DocumentType.query.filter_by(name=name).first():
                db.session.add(DocumentType(name=name))
                db.session.commit()
                flash(f'Document type "{name}" added.', "success")
            elif name:
                flash("Document type already exists.", "warning")
        elif action == "delete_doc_type":
            dt = db.session.get(DocumentType, request.form.get("id"))
            if dt:
                db.session.delete(dt)
                db.session.commit()
                flash(f'"{dt.name}" deleted.', "info")
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
    doc_types = DocumentType.query.order_by(DocumentType.name).all()
    doc_statuses = DocumentStatus.query.order_by(DocumentStatus.name).all()
    staff_count = User.query.filter_by(department=current_user.department).count()
    return render_template("office_settings.html", doc_types=doc_types,
                           doc_statuses=doc_statuses, staff_count=staff_count)


@bp.route("/activity_logs")
@login_required
@role_required("admin")
def activity_logs():
    action_filter = request.args.get("action", "").strip()
    records_q = (RecordHistory.query.join(Record, RecordHistory.record_id == Record.id)
               .filter((RecordHistory.from_department == current_user.department)
                       | (RecordHistory.to_department == current_user.department))
               .order_by(RecordHistory.timestamp.desc()))
    if action_filter:
        records_q = records_q.filter(RecordHistory.action_type == action_filter)
    records = records_q.all()
    return render_template("logs.html", records=records, action_filter=action_filter)


@bp.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403


@bp.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404