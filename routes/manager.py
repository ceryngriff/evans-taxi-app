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
@manager_bp.route('/add-contract', methods=['GET', 'POST'])
@manager_required
def add_contract():
    if request.method == 'POST':
        try:
            # 🔧 Get all form fields
            contract_number = request.form['contract_number']
            school_name = request.form['school_name']
            school_postcode = request.form['school_postcode']
            school_start_time = datetime.strptime(request.form['school_start_time'], '%H:%M').time()
            school_finish_time = datetime.strptime(request.form['school_finish_time'], '%H:%M').time()
            route_start_time = datetime.strptime(request.form['route_start_time'], '%H:%M').time()
            route_finish_time = datetime.strptime(request.form['route_finish_time'], '%H:%M').time()
            required_vehicle_size = request.form.get('required_vehicle_size')
            commute_time = int(request.form.get('commute_time') or 0)
            escort_required = True if request.form.get('escort_required') == 'on' else False

            # 🔒 Check for duplicate contract number
            if Contract.query.filter_by(contract_number=contract_number).first():
                flash('❌ Contract number already exists. Please choose another.', 'danger')
                return redirect(url_for('manager.add_contract'))

            # ✅ Create and save the contract
            new_contract = Contract(
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

            db.session.add(new_contract)
            db.session.flush()  # So we can get new_contract.id for the children

            # 👶 Handle children
            child_names = request.form.getlist('child_name[]')
            child_addresses = request.form.getlist('child_address[]')
            child_postcodes = request.form.getlist('child_postcode[]')

            for name, address, postcode in zip(child_names, child_addresses, child_postcodes):
                if name.strip():
                    child = Child(
                        name=name,
                        address=address,
                        child_postcode=postcode,
                        contract_id=new_contract.id
                    )
                    db.session.add(child)

            db.session.commit()
            flash('✅ Contract added successfully!', 'success')
            return redirect(url_for('view_contracts'))

        except Exception as e:
            db.session.rollback()
            print("🚨 ERROR WHILE SAVING CONTRACT:", e)
            flash(f'❌ An error occurred: {e}', 'danger')

    return render_template('add_contract.html')


@manager_bp.route('/edit-contract/<int:contract_id>', methods=['GET', 'POST'])
@manager_required
def edit_contract(contract_id):
    contract = Contract.query.get_or_404(contract_id)
    if request.method == 'POST':
        contract.contract_number = request.form['contract_number']
        contract.school_name = request.form['school_name']
        contract.school_start_time = datetime.strptime(request.form['school_start_time'], '%H:%M').time()
        contract.school_finish_time = datetime.strptime(request.form['school_finish_time'], '%H:%M').time()
        db.session.commit()
        flash('Contract updated successfully.', 'success')
        return redirect(url_for('view_contracts'))
    return render_template('edit_contract.html', contract=contract)

@manager_bp.route('/delete-contract/<int:contract_id>', methods=['POST'])
@manager_required
def delete_contract(contract_id):
    contract = Contract.query.get_or_404(contract_id)
    db.session.delete(contract)
    db.session.commit()
    flash('Contract deleted.', 'info')
    return redirect(url_for('view_contracts'))

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


