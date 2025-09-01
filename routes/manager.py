from flask import Blueprint
manager_bp = Blueprint('manager', __name__)
from flask_login import current_user
from flask import abort
from model import MechanicJob  # Add MechanicJob if you're reviewing mechanic jobs here
from flask import render_template, request, flash, redirect, url_for, flash,jsonify
from model import TariffRate, db, Contract, Child, NonSchoolDay,SchoolTerm,Vehicle, DriverAllocation,SchoolTerm, InsetDay
from datetime import datetime
from utils.utils import manager_required
from utils.utils import get_distance_between_postcodes
from flask import render_template, request, flash, redirect, url_for, jsonify, current_app, abort
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError, DataError
from datetime import datetime, time
from model import db, Contract, Child, TariffRate, Vehicle, MechanicJob, SchoolTerm, InsetDay
from utils.utils import manager_required, get_distance_between_postcodes

@manager_bp.route('/manage-tariffs', methods=['GET', 'POST'])
def manage_tariffs():
    if request.method == 'POST':
        for rate_id, new_price in request.form.items():
            rate = TariffRate.query.get(int(rate_id))
            if rate:
                rate.rate_per_mile = float(new_price)
        db.session.commit()
        flash("Tariff rates updated successfully!", "success")

    rates = TariffRate.query.order_by(TariffRate.vehicle_type, TariffRate.tariff).all()
    return render_template('manage_tariffs.html', rates=rates)
from flask import request, jsonify
from sqlalchemy import or_, func
from datetime import time
from model import db, Contract, Child

def _try_parse_time(token: str):
    t = token.strip().replace(".", ":")
    if t.isdigit():
        if len(t) <= 2:
            return time(int(t), 0)
        if len(t) == 4:
            return time(int(t[:2]), int(t[2:]))
    if ":" in t:
        try:
            h, m = t.split(":", 1)
            return time(int(h), int(m))
        except Exception:
            return None
    return None

@manager_bp.route("/api/contracts/search")
def api_contracts_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        rows = (db.session.query(Contract)
                .order_by(Contract.contract_number)
                .limit(25).all())
    else:
        tt = _try_parse_time(q)
        like = f"%{q.lower()}%"

        query = (db.session.query(Contract)
                 .outerjoin(Child)
                 .filter(or_(
                     func.lower(Contract.contract_number).like(like),
                     func.lower(Contract.school_name).like(like),
                     func.lower(Child.name).like(like),
                     *( [Contract.school_start_time == tt] if tt else [] ),
                     *( [Contract.route_start_time == tt]  if tt else [] ),
                     *( [Contract.route_finish_time == tt] if tt else [] ),
                 ))
                 .distinct()
                 .order_by(Contract.contract_number))

        rows = query.limit(100).all()

    def _timefmt(t): return t.strftime("%H:%M") if t else None

    payload = []
    for c in rows:
        payload.append({
            "id": c.id,
            "contract_number": c.contract_number,
            "school_name": c.school_name,
            "school_postcode": c.school_postcode,
            "school_start_time": _timefmt(c.school_start_time),
            "school_finish_time": _timefmt(c.school_finish_time),
            "route_start_time": _timefmt(c.route_start_time),
            "route_finish_time": _timefmt(c.route_finish_time),
            "required_vehicle_size": c.required_vehicle_size,
            "commute_time": c.commute_time,
            "escort_required": bool(c.escort_required),
            "children": [{"id": ch.id, "name": ch.name, "address": ch.address} for ch in c.children],
        })
    return jsonify({"results": payload})


# ---------- helpers ----------
def _parse_time(val: str):
    """Accept '9', '09', '9:00', '09:00', '0900', '9.00' -> time(9,0). Empty -> None."""
    if not val:
        return None
    v = val.strip().replace('.', ':')
    if v.isdigit():
        if len(v) <= 2:     return time(int(v), 0)
        if len(v) == 4:     return time(int(v[:2]), int(v[2:]))
    if ':' in v:
        try:
            h, m = v.split(':', 1)
            return time(int(h), int(m))
        except Exception:
            return None
    try:
        return datetime.strptime(v, "%H:%M").time()
    except Exception:
        return None

# ---------- LIST ----------
@manager_bp.route('/contracts', methods=['GET'])
@manager_required
def view_contracts():
    contracts = Contract.query.order_by(Contract.contract_number).all()
    return render_template('contracts.html', contracts=contracts)

# ---------- ADD ----------
@manager_bp.route('/add-contract', methods=['GET', 'POST'])
@manager_required
def add_contract():
    if request.method == 'POST':
        try:
            contract_number      = request.form['contract_number'].strip()
            school_name          = request.form['school_name'].strip()
            school_postcode      = (request.form.get('school_postcode') or '').strip() or None
            school_start_time    = _parse_time(request.form.get('school_start_time'))
            school_finish_time   = _parse_time(request.form.get('school_finish_time'))
            route_start_time     = _parse_time(request.form.get('route_start_time'))
            route_finish_time    = _parse_time(request.form.get('route_finish_time'))
            required_vehicle_size= (request.form.get('required_vehicle_size') or '').strip() or None
            commute_time         = int(request.form.get('commute_time') or 0)
            escort_required      = bool(request.form.get('escort_required'))

            if not (school_start_time and school_finish_time):
                flash('School start/finish times are required.', 'danger')
                return redirect(url_for('manager.add_contract'))

            if Contract.query.filter_by(contract_number=contract_number).first():
                flash('❌ Contract number already exists. Please choose another.', 'danger')
                return redirect(url_for('manager.add_contract'))

            c = Contract(
                contract_number=contract_number,
                school_name=school_name,
                school_postcode=school_postcode,
                school_start_time=school_start_time,
                school_finish_time=school_finish_time,
                route_start_time=route_start_time,
                route_finish_time=route_finish_time,
                required_vehicle_size=required_vehicle_size,
                commute_time=commute_time,
                escort_required=escort_required
            )
            db.session.add(c)
            db.session.flush()  # get c.id

            # children
            names     = request.form.getlist('child_name[]')
            addresses = request.form.getlist('child_address[]')
            postcodes = request.form.getlist('child_postcode[]')
            for n, a, p in zip(names, addresses, postcodes):
                n = (n or '').strip()
                a = (a or '').strip()
                p = (p or '').strip() or None
                if n:
                    db.session.add(Child(name=n, address=a, child_postcode=p, contract_id=c.id))

            db.session.commit()
            flash('✅ Contract added successfully!', 'success')
            return redirect(url_for('manager.view_contracts'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.exception("Error adding contract")
            flash(f'❌ An error occurred: {e}', 'danger')

    return render_template('add_contract.html')

# ---------- EDIT (GET) ----------
@manager_bp.route('/contracts/<int:contract_id>/edit', methods=['GET'])
@manager_required
def edit_contract(contract_id):
    c = Contract.query.get_or_404(contract_id)
    return render_template('edit_contract.html', contract=c)

# ---------- UPDATE (POST) ----------
@manager_bp.route('/contracts/<int:contract_id>/update', methods=['POST'])
@manager_required
def update_contract(contract_id):
    c = Contract.query.get_or_404(contract_id)
    current_app.logger.info("Update contract %s form keys: %s", contract_id, list(request.form.keys()))

    # Base fields
    c.contract_number       = (request.form.get('contract_number') or c.contract_number).strip()
    c.school_name           = (request.form.get('school_name') or c.school_name).strip()
    c.school_postcode       = (request.form.get('school_postcode') or '').strip() or None
    c.required_vehicle_size = (request.form.get('required_vehicle_size') or '').strip() or None

    # Times (correct fields)
    s_start  = _parse_time(request.form.get('school_start_time'))
    s_finish = _parse_time(request.form.get('school_finish_time'))
    r_start  = _parse_time(request.form.get('route_start_time'))
    r_finish = _parse_time(request.form.get('route_finish_time'))

    if s_start  is not None: c.school_start_time  = s_start
    if s_finish is not None: c.school_finish_time = s_finish
    c.route_start_time  = r_start     # can be None
    c.route_finish_time = r_finish    # can be None

    commute = request.form.get('commute_time')
    c.commute_time = int(commute) if (commute and commute.isdigit()) else None
    c.escort_required = bool(request.form.get('escort_required'))

    # Children (update/add/remove)
    ids       = request.form.getlist('child_id[]')       or request.form.getlist('child_id')
    names     = request.form.getlist('child_name[]')     or request.form.getlist('child_name')
    addresses = request.form.getlist('child_address[]')  or request.form.getlist('child_address')
    postcodes = request.form.getlist('child_postcode[]') or request.form.getlist('child_postcode')

    def _get(seq, i, default=""): return (seq[i] if i < len(seq) else default) or default

    if ids:
        current_by_id = {str(ch.id): ch for ch in c.children}
        seen = set()
        for i in range(max(len(names), len(ids))):
            name = _get(names, i).strip()
            addr = _get(addresses, i).strip()
            pc   = (_get(postcodes, i).strip() or None)
            cid  = _get(ids, i).strip()
            if not (name or addr or pc):
                continue
            ch = current_by_id.get(cid)
            if ch:
                ch.name = name or ch.name
                ch.address = addr or ch.address
                ch.child_postcode = pc
                seen.add(cid)
            else:
                db.session.add(Child(name=name, address=addr, child_postcode=pc, contract_id=c.id))
        for cid, ch in current_by_id.items():
            if cid not in seen:
                db.session.delete(ch)
    else:
        for ch in list(c.children):
            db.session.delete(ch)
        for i in range(len(names)):
            name = _get(names, i).strip()
            if not name: continue
            addr = _get(addresses, i).strip()
            pc   = (_get(postcodes, i).strip() or None)
            db.session.add(Child(name=name, address=addr, child_postcode=pc, contract_id=c.id))

    try:
        db.session.commit()
        flash("✅ Contract updated.", "success")
    except (IntegrityError, DataError):
        db.session.rollback()
        current_app.logger.exception("Contract update failed")
        flash("❌ Could not save. Check required fields or duplicates.", "danger")

    return redirect(url_for('manager.view_contracts'))

# ---------- DELETE ----------
@manager_bp.route('/contracts/<int:contract_id>/delete', methods=['POST'])
@manager_required
def delete_contract(contract_id):
    contract = Contract.query.get_or_404(contract_id)
    db.session.delete(contract)
    db.session.commit()
    flash('Contract deleted.', 'info')
    return redirect(url_for('manager.view_contracts'))

@manager_bp.route('/manage-school-calendar', methods=['GET', 'POST'])
@manager_required
def manage_school_calendar():
    
      # if you're using Blueprints/models folder

    if request.method == 'POST':
        if 'add_term' in request.form:
            term_name = request.form['term_name']
            start_date = datetime.strptime(request.form['term_start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(request.form['term_end_date'], '%Y-%m-%d').date()

            # Check for duplicate
            existing_term = SchoolTerm.query.filter_by(name=term_name, start_date=start_date, end_date=end_date).first()
            if existing_term:
                flash("Term already exists.", "warning")
            else:
                new_term = SchoolTerm(name=term_name, start_date=start_date, end_date=end_date)
                db.session.add(new_term)
                db.session.commit()
                flash("School Term added.", "success")

        elif 'add_inset' in request.form:
            school_name = request.form['school_name'].strip()
            inset_date = datetime.strptime(request.form['inset_date'], '%Y-%m-%d').date()
            reason = request.form.get('reason', '').strip()

            # Check if the same school already has an inset day on this date
            existing_inset = InsetDay.query.filter_by(date=inset_date, school_name=school_name).first()
            if existing_inset:
                flash(f"Inset day for {school_name} on {inset_date} already exists.", "warning")
            else:
                new_inset = InsetDay(date=inset_date, school_name=school_name, reason=reason)
                db.session.add(new_inset)
                db.session.commit()
                flash("Inset Day added.", "success")

    # Fetch all data for display
    terms = SchoolTerm.query.order_by(SchoolTerm.start_date).all()
    insets = InsetDay.query.order_by(InsetDay.date).all()

    return render_template('manage_school_calendar.html', terms=terms, insets=insets)


@manager_bp.route('/view-inset-days/<school_name>', methods=['GET'])
@manager_required
def view_inset_days(school_name):
    inset_days = InsetDay.query.filter_by(school_name=school_name).all()
    return render_template('view_inset_days.html', inset_days=inset_days)

@manager_bp.route('/terms/<int:term_id>/update', methods=['POST'])
@manager_required
def update_term(term_id):
    term = SchoolTerm.query.get_or_404(term_id)
    name = (request.form.get('term_name') or term.name).strip()
    s = request.form.get('term_start_date')
    e = request.form.get('term_end_date')
    s_date = datetime.strptime(s, '%Y-%m-%d').date() if s else term.start_date
    e_date = datetime.strptime(e, '%Y-%m-%d').date() if e else term.end_date
    if e_date < s_date:
        flash('End date cannot be before start date.', 'danger')
        return redirect(url_for('manager.manage_school_calendar'))

    term.name = name
    term.start_date = s_date
    term.end_date = e_date
    db.session.commit()
    flash('Term updated.', 'success')
    return redirect(url_for('manager.manage_school_calendar'))

@manager_bp.route('/insets/<int:inset_id>/update', methods=['POST'])
@manager_required
def update_inset(inset_id):
    inset = InsetDay.query.get_or_404(inset_id)
    school = (request.form.get('school_name') or inset.school_name).strip()
    d = request.form.get('inset_date')
    reason = request.form.get('reason')
    inset.school_name = school
    inset.date = datetime.strptime(d, '%Y-%m-%d').date() if d else inset.date
    inset.reason = (reason or '').strip() or None
    db.session.commit()
    flash('Inset day updated.', 'success')
    return redirect(url_for('manager.manage_school_calendar'))

# ---- DELETE ----
@manager_bp.route('/terms/<int:term_id>/delete', methods=['POST'])
@manager_required
def delete_term(term_id):
    term = SchoolTerm.query.get_or_404(term_id)
    db.session.delete(term)
    db.session.commit()
    flash('Term deleted.', 'success')
    return redirect(url_for('manager.manage_school_calendar'))

@manager_bp.route('/insets/<int:inset_id>/delete', methods=['POST'])
@manager_required
def delete_inset(inset_id):
    inset = InsetDay.query.get_or_404(inset_id)
    db.session.delete(inset)
    db.session.commit()
    flash('Inset day deleted.', 'success')
    return redirect(url_for('manager.manage_school_calendar'))

@manager_bp.route('/scheduler')
def scheduler():
    return render_template('scheduler.html')
@manager_bp.route('/api/vehicles')
@manager_required
def get_vehicles():
    vehicles = Vehicle.query.all()
    vehicle_list = []
    for vehicle in vehicles:
        vehicle_list.append({
            'id': vehicle.id,
            'registration': vehicle.registration,
            'make_model': vehicle.make_model,
            'vehicle_size': vehicle.vehicle_size,
            'is_available': vehicle.is_available
        })
    return jsonify(vehicle_list)

@manager_bp.route('/review-mechanic-jobs')
@manager_required
def review_mechanic_jobs():
    if current_user.role != 'manager':
        abort(403)

    jobs_to_review = MechanicJob.query.filter_by(status='Completed', manager_confirmed=False).all()
    return render_template('admin_mechanic_jobs.html', jobs=jobs_to_review)


@manager_bp.route('/confirm-mechanic-job/<int:job_id>', methods=['POST'])
@manager_required
def confirm_mechanic_job(job_id):
    if current_user.role != 'manager':
        abort(403)

    job = MechanicJob.query.get_or_404(job_id)
    job.manager_confirmed = True
    job.status = 'Confirmed'
    db.session.commit()
    flash("Mechanic job confirmed successfully!", "success")
    return redirect(url_for('manager.review_mechanic_jobs'))


