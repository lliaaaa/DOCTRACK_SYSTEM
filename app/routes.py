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


@bp.route('/documents/<int:record_id>')
@login_required
def document_detail(record_id):
    # ensure the current user can see this document
    record = visible_documents(current_user.department).filter_by(id=record_id).first()
    if not record:
        return render_template('404.html'), 404

    return render_template('document_detail.html', record=record)


@bp.route('/documents/edit/<int:record_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_document(record_id):
    record = Record.query.get_or_404(record_id)
    if request.method == 'POST':
        record.title = request.form.get('title', record.title)
        record.doc_type = request.form.get('doc_type', record.doc_type)
        record.department = request.form.get('department', record.department)
        record.implementing_office = request.form.get('implementing_office', record.implementing_office)
        amount = request.form.get('amount')
        record.amount = float(amount) if amount else None
        record.received_by = request.form.get('received_by', record.received_by)
        record.status = request.form.get('status', record.status)
        record.updated_at = datetime.now(timezone.utc)

        # record an edit action in history
        history = RecordHistory(
            record_id=record.id,
            action_type='edit',
            from_department=current_user.department,
            to_department=record.department,
            action_by=current_user.full_name,
            status=record.status,
            timestamp=datetime.now(timezone.utc)
        )
        db.session.add(history)
        db.session.commit()

        flash('Document updated successfully.', 'success')
        return redirect(url_for('main.document_detail', record_id=record.id))

    # GET: render edit form
    departments = Department.query.all()
    document_types = DocumentType.query.all()
    document_statuses = DocumentStatus.query.all()
    return render_template('document_edit.html', record=record, departments=departments, document_types=document_types, document_statuses=document_statuses)


@bp.route('/documents/delete/<int:record_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_document(record_id):
    record = Record.query.get_or_404(record_id)
    db.session.delete(record)
    db.session.commit()
    flash('Document deleted.', 'info')
    return redirect(url_for('main.documents'))


@bp.route('/documents/close/<int:record_id>', methods=['POST'])
@login_required
@role_required('admin')
def close_document(record_id):
    record = Record.query.get_or_404(record_id)
    record.status = 'Closed'
    record.updated_at = datetime.now(timezone.utc)

    history = RecordHistory(
        record_id=record.id,
        action_type='close',
        from_department=current_user.department,
        to_department=record.department,
        action_by=current_user.full_name,
        status=record.status,
        timestamp=datetime.now(timezone.utc)
    )
    db.session.add(history)
    db.session.commit()
    return jsonify(success=True)


# =========================================================
# USERS (ADMIN ONLY — SAME DEPARTMENT)
# =========================================================
@bp.route("/users")
@login_required
@role_required("admin")
def users():
    users = User.query.filter_by(department=current_user.department).all()
    return render_template("users.html", users=users)


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
        return redirect(url_for("main.incoming_documents"))

    return render_template(
        "admin/new_doc.html",
        users=users,
        document_type=document_type,
        document_status=document_status,
        departments=departments
    )


# =========================================================
# TRANSFER & RECEIVE
# =========================================================
@bp.route("/incoming")
@login_required
def incoming_documents():
    records = visible_documents(current_user.department)
    return render_template("incoming_doc.html", records=records)


@bp.route("/outgoing")
@login_required
def outgoing_documents():
    records = visible_documents(current_user.department)
    return render_template("outgoing_doc.html", records=records)


@bp.route("/processing")
@login_required
def processing_documents():
    records = visible_documents(current_user.department)
    return render_template("processing_doc.html", records=records)


@bp.route("/archived")
@login_required
def archived_documents():
    records = visible_documents(current_user.department).filter(Record.status == 'Closed')
    return render_template("archived.html", records=records)


@bp.route("/analytics")
@login_required
def analytics():
    # Bottleneck analytics: compute average time spent per department
    from collections import defaultdict
    import statistics

    dept_durations = defaultdict(list)

    records = Record.query.options().all()
    for record in records:
        hist = sorted(record.history, key=lambda h: h.timestamp) if record.history else []
        for i in range(len(hist) - 1):
            cur = hist[i]
            nxt = hist[i + 1]
            if cur.to_department and cur.timestamp and nxt.timestamp:
                delta = (nxt.timestamp - cur.timestamp).total_seconds()
                if delta > 0:
                    dept_durations[cur.to_department].append(delta)

    # compute averages in hours
    avg_hours = {}
    for dept, secs in dept_durations.items():
        avg_hours[dept] = (sum(secs) / len(secs)) / 3600.0

    # overall stats
    avg_values = list(avg_hours.values())
    overall_mean = statistics.mean(avg_values) if avg_values else 0
    overall_stdev = statistics.stdev(avg_values) if len(avg_values) > 1 else 0

    # bottlenecks: depts with avg > mean + stdev
    bottlenecks = [
        {"department": d, "avg_hours": round(h, 2), "count": len(dept_durations[d])}
        for d, h in avg_hours.items() if h > overall_mean + overall_stdev
    ]

    # Prepare chart data
    labels = list(avg_hours.keys())
    values = [round(v, 2) for v in avg_hours.values()]

    # Simple ML: try to train a regressor to predict duration (hours) per department
    ml_summary = None
    ml_available = False
    try:
        import pandas as pd
        from sklearn.model_selection import train_test_split
        from sklearn.ensemble import RandomForestRegressor
    except Exception:
        ml_summary = "Install pandas and scikit-learn to enable ML analytics"
    else:
        # Build dataset from history durations (same as above but per transition)
        rows = []
        for record in records:
            hist = sorted(record.history, key=lambda h: h.timestamp) if record.history else []
            for i in range(len(hist) - 1):
                cur = hist[i]
                nxt = hist[i + 1]
                if cur.to_department and cur.timestamp and nxt.timestamp:
                    delta_hours = (nxt.timestamp - cur.timestamp).total_seconds() / 3600.0
                    rows.append({
                        "doc_type": record.doc_type,
                        "department": cur.to_department,
                        "amount": record.amount or 0.0,
                        "duration": delta_hours
                    })

        if len(rows) >= 30:
            df = pd.DataFrame(rows)
            # one-hot encode categorical features
            X = pd.get_dummies(df[["doc_type", "department"]].astype(str))
            X["amount"] = df["amount"]
            y = df["duration"]

            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
            model = RandomForestRegressor(n_estimators=50, random_state=42)
            model.fit(X_train, y_train)
            score = model.score(X_test, y_test)

            # feature importances (map back)
            importances = dict(zip(X.columns, model.feature_importances_))
            top_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:10]

            ml_summary = {
                "r2": round(float(score), 3),
                "top_features": [(k, round(float(v), 4)) for k, v in top_features]
            }
            ml_available = True
        else:
            ml_summary = "Not enough history rows (need >=30) to train ML model"

    return render_template(
        "analytics.html",
        labels=labels,
        values=values,
        bottlenecks=bottlenecks,
        overall_mean=round(overall_mean, 2),
        overall_stdev=round(overall_stdev, 2),
        ml_summary=ml_summary,
        ml_available=ml_available
    )


@bp.route("/reports")
@login_required
def reports():
    return render_template("reports.html")


@bp.route("/office_settings")
@login_required
@role_required("admin")
def office_settings():
    return render_template("office_settings.html")


@bp.route("/activity_logs")
@login_required
@role_required("admin")
def activity_logs():
    records = RecordHistory.query.order_by(RecordHistory.timestamp.desc()).all()
    return render_template("logs.html", records=records)

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
        "trace.html",
        documents=documents,
        tracked_doc=tracked_doc
    )
