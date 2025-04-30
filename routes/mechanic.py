from datetime import date, timedelta, datetime
from model import Vehicle, VehicleCheck, MechanicJob, db
from flask import Blueprint, render_template, abort, redirect, url_for
from flask_login import login_required, current_user

mechanic_bp = Blueprint('mechanic', __name__)

@mechanic_bp.route('/mechanic-dashboard')
@login_required
def dashboard():
    if current_user.role != 'mechanic':
        abort(403)

    vehicles = Vehicle.query.order_by(Vehicle.registration).all()

    # Upcoming alerts (next 30 days)
    upcoming_threshold = date.today() + timedelta(days=30)
    alerts = []

    for v in vehicles:
        if v.mot_renewal_date and v.mot_renewal_date <= upcoming_threshold:
            alerts.append(f"MOT due soon for {v.registration} ({v.mot_renewal_date})")
        if v.plate_expiry_date and v.plate_expiry_date <= upcoming_threshold:
            alerts.append(f"Plate expiry soon for {v.registration} ({v.plate_expiry_date})")
        if v.tax_expiry_date and v.tax_expiry_date <= upcoming_threshold:
            alerts.append(f"Tax expiry soon for {v.registration} ({v.tax_expiry_date})")
        if not v.insured:
            alerts.append(f"{v.registration} is NOT insured!")

    # ✅ Show only unconfirmed jobs
    mechanic_jobs = MechanicJob.query.filter_by(
        mechanic_id=current_user.id
    ).filter(
        MechanicJob.manager_confirmed == False
    ).all()

    job_count = len(mechanic_jobs)

    return render_template(
        'mechanic_dashboard.html',
        vehicles=vehicles,
        alerts=alerts,
        mechanic_jobs=mechanic_jobs,
        job_count=job_count
    )


@mechanic_bp.route('/toggle-job-status/<int:job_id>', methods=['POST'])
@login_required
def toggle_job_status(job_id):
    if current_user.role != 'mechanic':
        abort(403)

    job = MechanicJob.query.get_or_404(job_id)
    
    if job.status != 'Completed':
        job.status = 'Completed'
        job.completed_at = datetime.utcnow()
    else:
        job.status = 'Pending'
        job.completed_at = None
        job.manager_confirmed = False  # Reset confirmation if mechanic undoes completion

    db.session.commit()
    return redirect(url_for('mechanic.dashboard'))

