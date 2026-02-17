"""
API routes for analytics and real-time data endpoints.
This module is imported and registered in __init__.py.
"""
from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from collections import defaultdict
import statistics
from .models import Record, RecordHistory

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/analytics", methods=["GET"])
@login_required
def api_analytics():
    """
    JSON endpoint for real-time bottleneck analytics.
    Returns avg hours per department, bottlenecks, and ML summary.
    Frontend can poll this for live updates.
    """
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

    labels = list(avg_hours.keys())
    values = [round(v, 2) for v in avg_hours.values()]

    return jsonify({
        "labels": labels,
        "values": values,
        "bottlenecks": bottlenecks,
        "overall_mean": round(overall_mean, 2),
        "overall_stdev": round(overall_stdev, 2)
    })


@api_bp.route("/documents", methods=["GET"])
@login_required
def api_documents():
    """
    Return all visible documents as JSON for external integrations or dashboards.
    """
    from sqlalchemy import or_
    
    records = Record.query.filter(
        or_(
            Record.department == current_user.department,
            Record.id.in_(
                RecordHistory.query.with_entities(RecordHistory.record_id)
                .filter(
                    (RecordHistory.from_department == current_user.department) |
                    (RecordHistory.to_department == current_user.department)
                )
                .subquery()
            )
        )
    ).order_by(Record.created_at.desc()).all()

    return jsonify({
        "total": len(records),
        "documents": [
            {
                "id": r.id,
                "document_id": r.document_id,
                "title": r.title,
                "status": r.status,
                "department": r.department,
                "created_at": r.created_at.isoformat() if r.created_at else None
            }
            for r in records
        ]
    })
