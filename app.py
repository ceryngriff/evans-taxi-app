from flask import Flask, render_template, request, redirect, url_for, session, flash,jsonify,make_response, g
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, date, timedelta, timedelta as td
from functools import wraps
import calendar
from flask_login import login_required, current_user, login_user, logout_user, UserMixin,LoginManager
from model import db, Driver, Escort, DriverAllocation, DriverLocation, Vehicle, Leave, Contract, Child, ClockIn, Manager, Feedback,VehicleCheck, RunStatus,SchoolTerm, NonSchoolDay,MissedClockInRequest, MissedClockOutRequest,MissedRun, TariffRate, Quote,Mechanic,MechanicJob, Mechanic,FuelCardTransaction, InsetDay
from utils.utils import get_daily_allocations, calculate_weekly_hours, role_required, get_distance_between_postcodes
#from xhtml2pdf import pisa
from io import BytesIO
from routes.manager import manager_bp
from routes.auth import auth_bp
from routes.scheduler_routes import scheduler_bp
from collections import defaultdict
from routes.mechanic import mechanic_bp
from werkzeug.security import generate_password_hash
from calendar import monthcalendar
from werkzeug.utils import secure_filename
import os
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import time
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, DataError
from utils.billing_utils import calculate_school_days_for_month

app = Flask(__name__, instance_relative_config=True)

app.jinja_env.globals.update(enumerate=enumerate)

# Read DB URL from the environment (Render’s DATABASE_URL).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///school_bus.db")
if DATABASE_URL.startswith("postgres://"):  # normalize for SQLAlchemy
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")



db.init_app(app)
migrate = Migrate(app, db)
app.register_blueprint(scheduler_bp)
app.register_blueprint(manager_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(mechanic_bp)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'staff_login' 

@login_manager.user_loader
def load_user(user_id):
    role, id = user_id.split(':')
    if role == 'driver':
        return Driver.query.get(int(id))
    elif role == 'escort':
        return Escort.query.get(int(id))
    elif role == 'manager':
        return Manager.query.get(int(id))
    elif role == 'mechanic':
        return Mechanic.query.get(int(id))
    return None

def manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not isinstance(current_user, Manager):
            flash('Manager access required.', 'danger')
            return redirect(url_for('auth.manager_login'))  
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def home():
    return render_template('welcome.html') 

@app.route('/welcome')
def welcome():
    return render_template('welcome.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('welcome'))

@app.route('/manager-dashboard')
@manager_required
def manager_dashboard():
    today = date.today()
    start_next_week = today + timedelta(days=(7 - today.weekday()))
    end_next_week = start_next_week + timedelta(days=6)

    # Missed runs today
    missed = RunStatus.query.filter_by(completed=False)\
        .filter(RunStatus.run_date == today).all()

    enriched_runs = []
    for r in missed:
        allocation = DriverAllocation.query.get(r.allocation_id)
        staff = None
        if r.staff_type == 'driver':
            staff = Driver.query.get(r.staff_id)
        elif r.staff_type == 'escort':
            staff = Escort.query.get(r.staff_id)

        enriched_runs.append({
            'staff_name': staff.name if staff else 'Unknown',
            'shift': r.shift,
            'reason': r.reason or "No reason given",
            'contract_number': allocation.contract_number if allocation else 'N/A',
            'date': r.run_date.strftime('%Y-%m-%d')
        })

    # Upcoming leave
    upcoming_leave = Leave.query.filter(
        Leave.start_date <= end_next_week,
        Leave.end_date >= start_next_week
    ).all()

    # Vehicle checks
    upcoming_vehicle_checks = []
    for v in Vehicle.query.all():
        if (
            (v.mot_renewal_date >= today and v.mot_renewal_date <= end_next_week) or
            (v.mot_6_monthly_date and v.mot_6_monthly_date >= today and v.mot_6_monthly_date <= end_next_week) or
            (v.plate_expiry_date >= today and v.plate_expiry_date <= end_next_week) or
            (v.tax_expiry_date >= today and v.tax_expiry_date <= end_next_week)
        ):
            upcoming_vehicle_checks.append(v)

    drivers = Driver.query.all()
    escorts = Escort.query.all()

    # ✅ Badge renewal alerts (within 8 weeks)
    eight_weeks_later = today + timedelta(weeks=8)
    upcoming_badge_renewals = Driver.query.filter(
        Driver.badge_renewal_date != None,
        Driver.badge_renewal_date >= today,
        Driver.badge_renewal_date <= eight_weeks_later
    ).all()

    # ✅ Mechanics and their job counts
    mechanics_with_jobs = []
    mechanics = Mechanic.query.all()
    for mechanic in mechanics:
        job_count = MechanicJob.query.filter_by(mechanic_id=mechanic.id).count()
        mechanics_with_jobs.append({
            'mechanic': mechanic,
            'job_count': job_count
        })

    return render_template(
        'index.html',
        upcoming_leave=upcoming_leave,
        upcoming_vehicle_checks=upcoming_vehicle_checks,
        drivers=drivers,
        escorts=escorts,
        current_date=today,
        today=today,
        timedelta=timedelta,
        runs=enriched_runs,
        upcoming_badge_renewals=upcoming_badge_renewals,
        mechanics_with_jobs=mechanics_with_jobs 
    )

@app.context_processor
def inject_today():
    return {'today': date.today()}

# ---------------- Staff checked in for a run ----------------

@app.route('/submit-run-status', methods=['POST'])
@login_required
def submit_run_status():
    allocation_id = request.form.get('allocation_id')
    shift = request.form.get('shift')
    completed = bool(request.form.get('completed'))
    reason = request.form.get('reason')

    today = date.today()
    allocation = DriverAllocation.query.get_or_404(allocation_id)

    # Update or create RunStatus
    existing_status = RunStatus.query.filter_by(
        allocation_id=allocation_id,
        run_date=today,
        staff_id=current_user.id,
        staff_type=current_user.role,
        shift=shift
    ).first()

    if not existing_status:
        status = RunStatus(
            allocation_id=allocation_id,
            run_date=today,
            staff_id=current_user.id,
            staff_type=current_user.role,
            shift=shift,
            completed=completed,
            reason=reason
        )
        db.session.add(status)
    else:
        existing_status.completed = completed
        existing_status.reason = reason

    # Only log a missed run if not completed
    if not completed and reason:
        missed = MissedRun(
            allocation_id=allocation.id,
            staff_name=current_user.name,
            contract_number=allocation.contract_number,
            shift=shift,
            reason=reason,
            date=today
        )
        db.session.add(missed)
        flash("🚨 Missed run recorded.", "warning")
    else:
        flash("✅ Run marked as completed!", "success")

    db.session.commit()
    return redirect(url_for('staff_dashboard'))

#  ---------------- Missed school runs ----------------

@app.route('/manager/missed-runs')
@manager_required
def missed_runs():
    today = date.today()

    staff_query = request.args.get('staff', '').lower()
    contract_query = request.args.get('contract', '').lower()

    missed = RunStatus.query.filter_by(
        completed=False
    ).filter(RunStatus.run_date == today).all()

    enriched_runs = []
    for r in missed:
        allocation = DriverAllocation.query.get(r.allocation_id)
        staff = None
        if r.staff_type == 'driver':
            staff = Driver.query.get(r.staff_id)
        elif r.staff_type == 'escort':
            staff = Escort.query.get(r.staff_id)

        enriched_runs.append({
            'staff_name': staff.name if staff else 'Unknown',
            'shift': r.shift,
            'reason': r.reason or "No reason given",
            'contract_number': allocation.contract_number if allocation else 'N/A',
            'date': r.run_date.strftime('%Y-%m-%d')
        })

    # 🔍 Apply search filters
    if staff_query:
        enriched_runs = [run for run in enriched_runs if staff_query in run['staff_name'].lower()]
    if contract_query:
        enriched_runs = [run for run in enriched_runs if contract_query in run['contract_number'].lower()]

    return render_template('missed_runs.html', runs=enriched_runs)
# ---------- Add Mechanics ----------

@app.route('/add-mechanic', methods=['GET', 'POST'])
def add_mechanic():
    if request.method == 'POST':
        name = request.form['name']
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        mechanic = Mechanic(
            name=name,
            username=username,
            password=password
        )
        db.session.add(mechanic)
        db.session.commit()
        flash('Mechanic added successfully!', 'success')
        return redirect(url_for('staff_management'))

    return render_template('add_mechanic.html')


# ---------- Drivers ----------
@app.route('/drivers')
@manager_required
def view_drivers():
    drivers = Driver.query.all()
    return render_template('drivers.html', drivers=drivers)

@app.route('/add-driver', methods=['GET', 'POST'])
def add_driver():
    if request.method == 'POST':
        driver = Driver(
            name=request.form['name'],
            phone=request.form['phone'],
            badge_renewal_date=datetime.strptime(request.form['badge_renewal_date'], '%Y-%m-%d').date(),
            username=request.form['username'],
            password=generate_password_hash(request.form['password']),
            base_postcode=request.form['postcode'],
            shift=request.form['shift']
        )
        db.session.add(driver)
        db.session.commit()
        return redirect(url_for('view_drivers'))
    return render_template('add_driver.html')

@app.route('/edit-driver/<int:driver_id>', methods=['GET', 'POST'])
def edit_driver(driver_id):
    driver = Driver.query.get_or_404(driver_id)

    if request.method == 'POST':
        driver.name = request.form['name']
        driver.phone = request.form['phone']
        driver.base_postcode = request.form['postcode']
        driver.shift = request.form['shift']
        db.session.commit()
        return redirect(url_for('view_drivers'))

    return render_template('edit_driver.html', driver=driver)
    
@app.route('/delete-driver/<int:driver_id>', methods=['POST'])
def delete_driver(driver_id):
        driver = Driver.query.get_or_404(driver_id)
        db.session.delete(driver)
        db.session.commit()
        return redirect(url_for('view_drivers'))

# ---------------- Escorts ----------------
@app.route('/escorts')
@manager_required
def view_escorts():
    escorts = Escort.query.all()
    return render_template('escorts.html', escorts=escorts)

@app.route('/add-escort', methods=['GET', 'POST'])
def add_escort():
    if request.method == 'POST':
        escort = Escort(
            name=request.form['name'],
            phone=request.form['phone'],
            address=request.form['address'],
            base_postcode=request.form['base_postcode'],
            username=request.form['username'],
            password=generate_password_hash(request.form['password'])
        )
        db.session.add(escort)
        db.session.commit()
        return redirect(url_for('view_escorts'))
    return render_template('add_escort.html')

@app.route('/edit-escort/<int:escort_id>', methods=['GET', 'POST'])
def edit_escort(escort_id):
    escort = Escort.query.get_or_404(escort_id)
    if request.method == 'POST':
        escort.name = request.form['name']
        escort.phone = request.form['phone']
        escort.address = request.form['address']
        escort.base_postcode = request.form['base_postcode']
        db.session.commit()
        return redirect(url_for('view_escorts'))
    return render_template('edit_escort.html', escort=escort)

@app.route('/delete-escort/<int:escort_id>', methods=['POST'])
def delete_escort(escort_id):
    escort = Escort.query.get_or_404(escort_id)
    db.session.delete(escort)
    db.session.commit()
    return redirect(url_for('view_escorts'))

@app.route('/driverallocation', methods=['GET', 'POST'])
@manager_required
def driverallocation():
    drivers = Driver.query.all()
    escorts = Escort.query.all()
    contracts = Contract.query.all()
    allocations = DriverAllocation.query.all()

    if request.method == 'POST':
        contract_id = int(request.form['contract_id'])
        contract = Contract.query.get(contract_id)

        driver_id = int(request.form.get('driver_id'))  # Ensure this is an integer
        escort_id = request.form.get('escort_id') or None
        driver_shift = request.form.get('driver_shift')
        escort_shift = request.form.get('escort_shift') or None
        contract_days = ','.join(request.form.getlist('contract_days'))
        repeat_all_week = bool(request.form.get('repeat_all_week'))

        contract_date_str = request.form.get('contract_date')
        print(f"Contract Date String: {contract_date_str}")
        contract_date = datetime.strptime(contract_date_str, '%Y-%m-%d').date() if contract_date_str else None

        if contract:
            allocation = DriverAllocation(
                contract_number=contract.contract_number,
                contract_id=contract.id,
                contract_days=contract_days,
                driver_id=driver_id,
                escort_id=escort_id,
                driver_shift=driver_shift,
                escort_shift=escort_shift,
                repeat_all_week=repeat_all_week,
                contract_date=contract_date
            )
            try:
                db.session.add(allocation)
                db.session.commit()
                flash("✅ Allocation successfully added!")
            except Exception as e:
                db.session.rollback()
                flash(f"❌ Error: {str(e)}", "error")
        else:
            flash("❌ Contract not found.", "error")

        source = request.form.get('source')
        contract_date_str = request.form.get('contract_date')
        driver_shift = request.form.get('driver_shift')

        if source == 'unallocated':
            return redirect(url_for('unallocated_contracts', date=contract_date_str, shift=driver_shift))
        else:
            return redirect(url_for('driverallocation'))

    allocation = None
    return render_template(
        'driverallocation.html',
        allocations=allocations,
        drivers=drivers,
        escorts=escorts,
        contracts=contracts,
        allocation=allocation
    )


# View Driver Allocations with optional filtering
@app.route('/view_driverallocation', methods=['GET', 'POST'])
@manager_required
def view_driverallocation():
    query = DriverAllocation.query.join(Contract)

    if request.method == 'POST':
        if request.form.get('school_name'):
            query = query.filter(Contract.school_name.ilike(f"%{request.form['school_name']}%"))
        if request.form.get('driver_id'):
            try:
                driver_id = int(request.form['driver_id'])
                query = query.filter(DriverAllocation.driver_id == driver_id)
            except ValueError:
                flash("Invalid driver ID", "danger")
        if request.form.get('contract_date'):
            query = query.filter(DriverAllocation.contract_date == request.form['contract_date'])
        if request.form.get('driver_shift'):
            query = query.filter(DriverAllocation.driver_shift == request.form['driver_shift'])

    contracts = query.all()
    drivers = Driver.query.all()
    return render_template('view_driverallocation.html', contracts=contracts, drivers=drivers)


# Edit an existing driver allocation
@app.route('/edit-driverallocation/<int:allocation_id>', methods=['GET', 'POST'])
@manager_required
def edit_driverallocation(allocation_id):
    allocation = DriverAllocation.query.get_or_404(allocation_id)
    drivers = Driver.query.all()
    escorts = Escort.query.all()
    contracts = Contract.query.all()

    if request.method == 'POST':
        contract_id = int(request.form['contract_id'])
        contract = Contract.query.get_or_404(contract_id)

        allocation.contract_number = contract.contract_number
        allocation.contract_id = contract.id
        allocation.driver_id = request.form.get('driver_id')
        allocation.escort_id = request.form.get('escort_id') or None
        allocation.driver_shift = request.form.get('driver_shift')
        allocation.escort_shift = request.form.get('escort_shift') or None

        # ✅ New: Handle optional specific date
        contract_date_str = request.form.get('contract_date')
        if contract_date_str:
            allocation.contract_date = datetime.strptime(contract_date_str, '%Y-%m-%d').date()
        else:
            allocation.contract_date = None

        # ✅ Recurring Days
        allocation.contract_days = ','.join(request.form.getlist('contract_days'))
        allocation.repeat_all_week = bool(request.form.get('repeat_all_week'))

        db.session.commit()
        flash("✅ Driver allocation updated!", "success")
        return redirect(url_for('driverallocation'))

    return render_template(
        'edit_driverallocation.html',
        allocation=allocation,
        drivers=drivers,
        escorts=escorts,
        contracts=contracts
    )

@app.route('/delete-driverallocation/<int:allocation_id>', methods=['GET', 'POST'])
@manager_required
def delete_driverallocation(allocation_id):
    allocation = DriverAllocation.query.get_or_404(allocation_id)

    if request.method == 'POST':
        db.session.delete(allocation)
        db.session.commit()
        flash("Allocation deleted successfully!", "success")
        return redirect(url_for('view_driverallocation'))
    
    # If GET, show a confirmation page (optional)
    return f"""
        <h3>Are you sure you want to delete allocation ID {allocation_id}?</h3>
        <form method="post">
            <button type="submit">Yes, delete</button>
        </form>
        <a href="{url_for('view_driverallocation')}">Cancel</a>
    """



# ---------- Vehicle ----------

@app.route('/vehicles')
@role_required(['manager', 'mechanic'])
def view_vehicles():
    sort_by = request.args.get('sort_by', 'registration')
    order = request.args.get('order', 'asc')
    query = Vehicle.query
    if hasattr(Vehicle, sort_by):
        col = getattr(Vehicle, sort_by)
        query = query.order_by(db.desc(col) if order == 'desc' else col)
    vehicles = query.all()
    return render_template('vehicles.html', vehicles=vehicles, sort_by=sort_by, order=order)
@app.route('/add-vehicle', methods=['GET', 'POST'])
def add_vehicle():
    if request.method == 'POST':
        vehicle = Vehicle(
            registration=request.form['registration'],
            make_model=request.form['make_model'],
            plate_number=request.form['plate_number'],
            mot_renewal_date=datetime.strptime(request.form['mot_renewal_date'], '%Y-%m-%d').date(),
            mot_6_monthly_date=datetime.strptime(request.form['mot_6_monthly_date'], '%Y-%m-%d').date() if request.form['mot_6_monthly_date'] else None,
            plate_expiry_date=datetime.strptime(request.form['plate_expiry_date'], '%Y-%m-%d').date(),
            tax_expiry_date=datetime.strptime(request.form['tax_expiry_date'], '%Y-%m-%d').date(),
            insured='insured' in request.form,
            vehicle_size=request.form['vehicle_size']  # ✅ included only once here
        )
        db.session.add(vehicle)
        db.session.commit()
        return redirect(url_for('view_vehicles'))
    return render_template('add_vehicle.html')

@app.route('/edit-vehicle/<int:vehicle_id>', methods=['GET', 'POST'])
def edit_vehicle(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    
    if request.method == 'POST':
        vehicle.registration = request.form['registration']
        vehicle.make_model = request.form['make_model']
        vehicle.plate_number = request.form['plate_number']
        vehicle.mot_renewal_date = datetime.strptime(request.form['mot_renewal_date'], '%Y-%m-%d').date()
        vehicle.mot_6_monthly_date = datetime.strptime(request.form['mot_6_monthly_date'], '%Y-%m-%d').date() if request.form['mot_6_monthly_date'] else None
        vehicle.plate_expiry_date = datetime.strptime(request.form['plate_expiry_date'], '%Y-%m-%d').date()
        vehicle.tax_expiry_date = datetime.strptime(request.form['tax_expiry_date'], '%Y-%m-%d').date()
        vehicle.insured = 'insured' in request.form
        vehicle.vehicle_size = request.form['vehicle_size']  # ✅ this line adds vehicle size!

        db.session.commit()
        return redirect(url_for('view_vehicles'))
    
    return render_template('edit_vehicle.html', vehicle=vehicle)


@app.route('/delete-vehicle/<int:vehicle_id>', methods=['POST'])
@manager_required
def delete_vehicle(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    db.session.delete(vehicle)
    db.session.commit()
    return redirect(url_for('view_vehicles'))

# ---------- Leave Management ----------
@app.route('/leave', methods=['GET', 'POST'])
@manager_required
def manage_leave():
    drivers = Driver.query.all()
    escorts = Escort.query.all()
    if request.method == 'POST':
        leave = Leave(
            person_type=request.form['person_type'],
            person_id=request.form['person_id'],
            start_date=datetime.strptime(request.form['start_date'], '%Y-%m-%d').date(),
            end_date=datetime.strptime(request.form['end_date'], '%Y-%m-%d').date(),
            reason=request.form.get('reason', '')
        )
        db.session.add(leave)
        db.session.commit()
        return redirect(url_for('manage_leave'))
    leave_records = Leave.query.order_by(Leave.start_date.desc()).all()
    return render_template('leave.html', drivers=drivers, escorts=escorts, leave_records=leave_records)

@app.route('/edit-leave/<int:leave_id>', methods=['GET', 'POST'])
@manager_required
def edit_leave(leave_id):
    leave = Leave.query.get_or_404(leave_id)
    drivers = Driver.query.all()
    escorts = Escort.query.all()
    if request.method == 'POST':
        leave.person_type = request.form['person_type']
        leave.person_id = request.form['person_id']
        leave.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        leave.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()
        leave.reason = request.form.get('reason', '')
        db.session.commit()
        return redirect(url_for('manage_leave'))
    return render_template('edit_leave.html', leave=leave, drivers=drivers, escorts=escorts)

@app.route('/delete-leave/<int:leave_id>', methods=['POST'])
@manager_required
def delete_leave(leave_id):
    leave = Leave.query.get_or_404(leave_id)
    db.session.delete(leave)
    db.session.commit()
    return redirect(url_for('manage_leave'))

@app.route('/schedule', methods=['GET', 'POST'])
@manager_required
def schedule():
    selected_date = date.today()
    if request.method == 'POST':
        selected_date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
    allocations = get_daily_allocations(selected_date)
    return render_template('schedule.html', contracts=allocations, selected_date=selected_date)

@app.route('/schedule/<date_str>')
@manager_required
def schedule_day(date_str):
    selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    weekday_name = selected_date.strftime('%A')

    # 1. Allocations with this specific contract_date
    one_time_allocations = DriverAllocation.query.filter_by(contract_date=selected_date).all()

    # 2. Repeating allocations for this weekday
    repeat_allocs_all = DriverAllocation.query.filter_by(repeat_all_week=True).all()
    repeat_allocations = []
    for alloc in repeat_allocs_all:
        if alloc.contract_days:
            days_list = [d.strip() for d in alloc.contract_days.split(',')]
            if weekday_name in days_list:
                repeat_allocations.append(alloc)

    # Combine both
    all_allocations = one_time_allocations + repeat_allocations

    return render_template(
        'schedule_day.html',
        selected_date=selected_date,
        allocations=all_allocations,
        search_query=""
    )

@app.route('/schedule/search', methods=['GET'])
@manager_required
def search_schedule_redirect():
    date_str = request.args.get('date')
    search = request.args.get('search', '')
    if date_str:
        return redirect(url_for('view_schedule_day', date_str=date_str, search=search))
    else:
        flash("Please select a date.", "warning")
        return redirect(url_for('calendar_view'))

@app.route('/calendar')
@manager_required
def calendar_view():
    # Get the current month and year
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)

    now = datetime.now()
    if not year or not month:
        year, month = now.year, now.month

    # Adjust month/year if out of range
    if month < 1:
        month = 12
        year -= 1
    elif month > 12:
        month = 1
        year += 1

    cal = monthcalendar(year, month)

    # 1) Allocations (one-off + repeating)
    allocations_by_date = {}
    allocations = DriverAllocation.query.all()

    for alloc in allocations:
        if alloc.contract_date:
            if alloc.contract_date.year == year and alloc.contract_date.month == month:
                key = alloc.contract_date.strftime('%Y-%m-%d')
                allocations_by_date.setdefault(key, []).append(alloc)
        elif alloc.repeat_all_week and alloc.contract_days:
            wanted_days = {d.strip() for d in alloc.contract_days.split(',')}
            for week in cal:
                for i, d in enumerate(week):  # i: 0..6 (Mon..Sun), d: day num or 0
                    if d == 0:
                        continue
                    if calendar.day_name[i] in wanted_days:
                        day_date = date(year, month, d)
                        key = day_date.strftime('%Y-%m-%d')
                        allocations_by_date.setdefault(key, []).append(alloc)

    # 2) School terms -> mark ONLY weekdays as school days
    terms = SchoolTerm.query.all()
    term_dates = set()
    for term in terms:
        cur = term.start_date
        while cur <= term.end_date:
            if cur.year == year and cur.month == month and cur.weekday() < 5:  # Mon–Fri
                term_dates.add(cur)
            cur += timedelta(days=1)

    # 3) Inset days for this month
    inset_entries = InsetDay.query.filter(
        db.extract('year', InsetDay.date) == year,
        db.extract('month', InsetDay.date) == month
    ).all()
    inset_dates = {e.date for e in inset_entries}

    # 4) Non-school = weekend OR (not in term) — but don’t mark inset as non-school here
    all_visible_days = [date(year, month, d) for week in cal for d in week if d != 0]
    non_school_days = {
        d for d in all_visible_days
        if d.weekday() >= 5 or (d not in term_dates and d not in inset_dates)
    }

    # 5) Approved leave mapped per day
    leave_dates = {}
    approved_leaves = Leave.query.filter_by(approved=True).all()
    for leave in approved_leaves:
        if not (leave.start_date and leave.end_date):
            continue
        cur = leave.start_date
        while cur <= leave.end_date:
            if cur.year == year and cur.month == month:
                person_name = None
                if leave.person_type == 'driver':
                    p = Driver.query.get(leave.person_id)
                    person_name = p.name if p else None
                elif leave.person_type == 'escort':
                    p = Escort.query.get(leave.person_id)
                    person_name = p.name if p else None
                if person_name:
                    leave_dates.setdefault(cur, []).append(person_name)
            cur += timedelta(days=1)

    return render_template(
        'calendar.html',
        calendar=cal,
        allocations_by_date=allocations_by_date,
        month=month,
        year=year,
        term_dates=term_dates,
        inset_dates=inset_dates,
        inset_entries=inset_entries,
        non_school_days=non_school_days,
        leave_dates=leave_dates,
        school_terms=terms,
        date=date,
        calendar_module=calendar
    )
from datetime import date
import calendar
from utils.billing_utils import calculate_school_days_for_month

@app.route("/billing-days")
def billing_days_view():
    today = date.today()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))

    data = calculate_school_days_for_month(year, month)  # dict {school_name: days}
    rows = sorted(
        [{"school_name": k, "days": v} for k, v in data.items()],
        key=lambda r: r["school_name"].lower()
    )
    total = sum(r["days"] for r in rows)
    month_label = f"{calendar.month_name[month]} {year}"

    return render_template(
        "billing_days.html",
        rows=rows,
        year=year,
        month=month,
        month_label=month_label,
        month_names=list(calendar.month_name)[1:],  # ["January", ... "December"]
    )

@app.route('/staff-dashboard')
@login_required
def staff_dashboard():
    today = date.today()
    weekday_name = today.strftime('%A')

    role = 'driver' if isinstance(current_user, Driver) else 'escort'
    staff_id = current_user.id

    # === One-time allocations for today ===
    one_time_allocs = DriverAllocation.query.filter_by(contract_date=today).all()

    # === Repeating allocations for today ===
    repeat_allocs = []
    for alloc in DriverAllocation.query.filter_by(repeat_all_week=True).all():
        if alloc.contract_days:
            days_list = [d.strip() for d in alloc.contract_days.split(',')]
            if weekday_name in days_list:
                repeat_allocs.append(alloc)

    all_allocs = one_time_allocs + repeat_allocs

    # === Filter allocations by logged-in staff ===
    allocations = []
    for alloc in all_allocs:
        if role == 'driver' and alloc.driver_id == staff_id:
            allocations.append(alloc)
        elif role == 'escort' and alloc.escort_id == staff_id:
            allocations.append(alloc)

    # === Check if staff is on approved leave today ===
    on_leave = Leave.query.filter(
        Leave.person_type == role,
        Leave.person_id == staff_id,
        Leave.approved == True,
        Leave.start_date <= today,
        Leave.end_date >= today
    ).first()

    if on_leave:
        allocations = []  # Hide all schedule if on leave

    # === Approved leave history ===
    approved_leaves = Leave.query.filter_by(
        person_type=role,
        person_id=staff_id,
        approved=True
    ).all()

    pending_leaves = Leave.query.filter_by(
        person_type=role,
        person_id=staff_id,
        approved=None
    ).all()

    declined_leaves = Leave.query.filter_by(
        person_type=role,
        person_id=staff_id,
        approved=False
    ).all()

    # === Weekly preview (Mon–Fri) ===
    start_of_week = today - timedelta(days=today.weekday())  # Monday
    week_allocations = {}

    for i in range(5):  # Mon to Fri
        day = start_of_week + timedelta(days=i)
        weekday = day.strftime('%A')

        daily_one_time = DriverAllocation.query.filter_by(contract_date=day).all()

        daily_repeat = []
        for alloc in DriverAllocation.query.filter_by(repeat_all_week=True).all():
            if alloc.contract_days and weekday in [d.strip() for d in alloc.contract_days.split(',')]:
                daily_repeat.append(alloc)

        daily_all = daily_one_time + daily_repeat
        staff_day_allocs = []
        for alloc in daily_all:
            if role == 'driver' and alloc.driver_id == staff_id:
                staff_day_allocs.append(alloc)
            elif role == 'escort' and alloc.escort_id == staff_id:
                staff_day_allocs.append(alloc)

        week_allocations[day] = staff_day_allocs

    return render_template(
        'staff_dashboard.html',
        user=current_user,
        role=role,
        today=today,
        allocations=allocations,
        approved_leaves=approved_leaves,
        pending_leaves=pending_leaves,
        declined_leaves=declined_leaves,
        week_allocations=week_allocations,
        on_leave=on_leave
    )


@app.route('/weekly-preview')
@login_required
def weekly_preview():
    role = 'driver' if isinstance(current_user, Driver) else 'escort'
    staff_id = current_user.id

    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())  # Monday
    week_dates = [start_of_week + timedelta(days=i) for i in range(5)]  # Mon–Fri

    week_allocations = {}

    for day in week_dates:
        weekday_name = day.strftime('%A')

        # One-time allocations
        one_time_allocs = DriverAllocation.query.filter_by(contract_date=day).all()

        # Repeating allocations
        repeat_allocs_all = DriverAllocation.query.filter_by(repeat_all_week=True).all()
        repeat_allocs = [
            a for a in repeat_allocs_all
            if a.contract_days and weekday_name in [d.strip() for d in a.contract_days.split(',')]
        ]

        # Filter by logged-in user
        all_allocs = one_time_allocs + repeat_allocs
        user_allocs = [
            alloc for alloc in all_allocs
            if (role == 'driver' and alloc.driver_id == staff_id) or
               (role == 'escort' and alloc.escort_id == staff_id)
        ]

        week_allocations[day] = user_allocs

    return render_template('staff_weekly_preview.html', week_allocations=week_allocations)

# ======== School Terms & Inset Days: CRUD ========

@app.route('/manage-calendar', methods=['GET'])
@manager_required
def manage_calendar():
    terms = SchoolTerm.query.order_by(SchoolTerm.start_date).all()
    insets = InsetDay.query.order_by(InsetDay.date).all()
    return render_template('manage_school_calendar.html', terms=terms, insets=insets)
 
@app.route('/submit-leave-request', methods=['POST'])
@login_required
def submit_leave_request():
    person_type = 'driver' if isinstance(current_user, Driver) else 'escort'
    person_id = current_user.id

    start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
    end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()
    reason = request.form.get('reason', '')

    leave = Leave(
        person_type=person_type,
        person_id=person_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason
    )

    db.session.add(leave)
    db.session.commit()

    flash('Leave request submitted successfully.', 'success')
    return redirect(url_for('staff_dashboard'))

@app.route('/submit-feedback', methods=['POST'])
@login_required
def submit_feedback():
    message = request.form['message']
    role = 'driver' if isinstance(current_user, Driver) else 'escort'

    feedback = Feedback(
        staff_type=role,
        staff_id=current_user.id,
        message=message
    )

    db.session.add(feedback)
    db.session.commit()

    flash('Thank you for your feedback!', 'success')
    return redirect(url_for('staff_dashboard'))

@app.route('/admin-feedback')
@manager_required
def admin_feedback():
    feedbacks = Feedback.query.order_by(Feedback.id.desc()).all()

    enriched_feedbacks = []
    for fb in feedbacks:
        if fb.staff_type == 'driver':
            staff = Driver.query.get(fb.staff_id)
        elif fb.staff_type == 'escort':
            staff = Escort.query.get(fb.staff_id)
        else:
            staff = None

        enriched_feedbacks.append({
            'id': fb.id,
            'staff_name': staff.name if staff else 'Unknown',
            'message': fb.message,
            'submitted_at': fb.submitted_at.strftime('%Y-%m-%d %H:%M') if fb.submitted_at else 'N/A'
        })

    return render_template('admin_feedback.html', feedbacks=enriched_feedbacks)

@app.route('/delete-feedback/<int:feedback_id>', methods=['POST'])
@manager_required
def delete_feedback(feedback_id):
    feedback = Feedback.query.get_or_404(feedback_id)
    db.session.delete(feedback)
    db.session.commit()
    flash("Feedback deleted successfully.", "success")
    return redirect(url_for('admin_feedback'))

# ---------- Staff calendar ----------
@app.route('/staff-calendar/<date_str>')
@login_required
def view_staff_schedule_day(date_str):
    role = 'driver' if isinstance(current_user, Driver) else 'escort'
    staff_id = current_user.id

    selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    weekday_name = selected_date.strftime('%A')  # 'Monday', etc.

    # 1. Allocations for that specific date
    one_time_allocs = DriverAllocation.query.filter_by(contract_date=selected_date).all()

    # 2. Recurring allocations for this weekday
    repeat_allocs_all = DriverAllocation.query.filter_by(repeat_all_week=True).all()
    repeat_allocs = []
    for alloc in repeat_allocs_all:
        if alloc.contract_days:
            days_list = [d.strip() for d in alloc.contract_days.split(',')]
            if weekday_name in days_list:
                repeat_allocs.append(alloc)

    # Combine and filter to only this staff member
    all_allocs = one_time_allocs + repeat_allocs

    staff_allocs = []
    for alloc in all_allocs:
        if role == 'driver' and alloc.driver_id == staff_id:
            staff_allocs.append(alloc)
        elif role == 'escort' and alloc.escort_id == staff_id:
            staff_allocs.append(alloc)

    return render_template('staff_schedule_day.html', allocations=staff_allocs, date_str=date_str)

@app.route('/staff-calendar')
@login_required
def staff_calendar():
    from calendar import monthcalendar, monthrange
    from datetime import datetime, timedelta, date

    staff_id = current_user.id
    staff_type = current_user.role  # 'driver' or 'escort'

    year = request.args.get('year', default=datetime.now().year, type=int)
    month = request.args.get('month', default=datetime.now().month, type=int)
    cal = monthcalendar(year, month)

    # --- School terms: weekdays only ---
    terms = SchoolTerm.query.all()
    term_dates = set()
    for term in terms:
        cur = term.start_date
        while cur <= term.end_date:
            if cur.year == year and cur.month == month and cur.weekday() < 5:
                term_dates.add(cur)
            cur += timedelta(days=1)

    # --- Inset days ---
    inset_entries = InsetDay.query.filter(
        db.extract('year', InsetDay.date) == year,
        db.extract('month', InsetDay.date) == month
    ).all()
    inset_dates = {e.date for e in inset_entries}

    # --- This staff member's approved leave only ---
    leave_entries = Leave.query.filter_by(
        person_id=staff_id, person_type=staff_type, approved=True
    ).all()
    leave_dates = set()
    for lv in leave_entries:
        cur = lv.start_date
        while cur <= lv.end_date:
            if cur.year == year and cur.month == month:
                leave_dates.add(cur)
            cur += timedelta(days=1)

    # --- Compute non-school days (weekends or out-of-term and not inset) ---
    all_visible_days = [date(year, month, d) for wk in cal for d in wk if d != 0]
    non_school_days = {
        d for d in all_visible_days
        if d.weekday() >= 5 or (d not in term_dates and d not in inset_dates)
    }

    # ===== NEW: allocations for this staff member, per day =====
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])

    # one-off allocations inside the month
    one_time = DriverAllocation.query.filter(
        DriverAllocation.contract_date >= first_day,
        DriverAllocation.contract_date <= last_day
    ).all()
    # repeating allocations (weekly)
    repeating = DriverAllocation.query.filter_by(repeat_all_week=True).all()

    def belongs(a):
        return ((staff_type == 'driver' and a.driver_id == staff_id) or
                (staff_type == 'escort' and a.escort_id == staff_id))

    one_time  = [a for a in one_time  if belongs(a)]
    repeating = [a for a in repeating if belongs(a)]

    staff_allocations_by_date = {}
    for d in all_visible_days:
        weekday = d.strftime('%A')
        day_allocs = [a for a in one_time if a.contract_date == d]
        for a in repeating:
            if a.contract_days and any(weekday == x.strip() for x in a.contract_days.split(',')):
                day_allocs.append(a)

        if day_allocs:
            staff_allocations_by_date[d] = [
                {
                    "contract_number": a.contract_number,
                    "shift": (a.driver_shift if staff_type == 'driver' else a.escort_shift),
                    "school_name": (a.contract.school_name if a.contract else "")
                }
                for a in day_allocs
            ]

    return render_template(
        'staff_calendar.html',
        calendar=cal,
        month=month,
        year=year,
        term_dates=term_dates,
        inset_dates=inset_dates,
        inset_entries=inset_entries,
        leave_dates=leave_dates,
        non_school_days=non_school_days,
        date=date,
        calendar_module=calendar,
        staff_allocations_by_date=staff_allocations_by_date,  # <-- pass to template
    )


@app.route('/admin-leave-requests')
@login_required
def admin_leave_requests():
    pending = Leave.query.filter_by(approved=None).all()
    approved = Leave.query.filter_by(approved=True).all()
    declined = Leave.query.filter_by(approved=False).all()
    return render_template('admin_leave_requests.html', pending=pending, approved=approved, declined=declined)

@app.route('/admin-leave-action/<int:leave_id>/<string:action>', methods=['POST'])
@login_required
def admin_leave_action(leave_id, action):
    leave = Leave.query.get_or_404(leave_id)
    if action == 'approve':
        leave.approved = True
    elif action == 'decline':
        leave.approved = False
    db.session.commit()
    flash('Leave request updated.', 'success')
    return redirect(url_for('admin_leave_requests'))
@app.route('/delete-leave/<int:leave_id>', methods=['POST'])
@login_required
def delete_leave_admin(leave_id):
    leave = Leave.query.get_or_404(leave_id)
    db.session.delete(leave)
    db.session.commit()
    flash('Leave request deleted.', 'info')
    return redirect(url_for('admin_leave_requests'))

@app.route('/clock-in', methods=['POST'])
@login_required
def clock_in():
    staff_type = 'driver' if isinstance(current_user, Driver) else 'escort'
    existing = ClockIn.query.filter_by(
        staff_type=staff_type,
        staff_id=current_user.id,
        date=date.today()
    ).first()

    if existing:
        flash('Already clocked in today!', 'warning')
    else:
        record = ClockIn(
            staff_type=staff_type,
            staff_id=current_user.id,
            clock_in_time=datetime.now()
        )
        db.session.add(record)
        db.session.commit()
        flash('Clocked in successfully!', 'success')

    return redirect(url_for('staff_dashboard'))

@app.route('/clock-out', methods=['POST'])
@login_required
def clock_out():
    staff_type = 'driver' if isinstance(current_user, Driver) else 'escort'
    record = ClockIn.query.filter_by(
        staff_type=staff_type,
        staff_id=current_user.id,
        date=date.today()
    ).first()

    if record and not record.clock_out_time:
        record.clock_out_time = datetime.now()
        db.session.commit()
        flash('Clocked out successfully!', 'success')
    elif record and record.clock_out_time:
        flash('Already clocked out today!', 'warning')
    else:
        flash('You need to clock in first.', 'danger')

    return redirect(url_for('staff_dashboard'))
@app.route('/submit-missed-clockout-request', methods=['POST'])
@login_required
def submit_missed_clockout_request():
    staff_type = 'driver' if isinstance(current_user, Driver) else 'escort'
    staff_id = current_user.id
    requested_date = datetime.strptime(request.form['requested_date'], '%Y-%m-%d').date()
    requested_time = datetime.strptime(request.form['requested_time'], '%H:%M').time()
    comment = request.form.get('comment')

    new_request = MissedClockOutRequest(
        staff_type=staff_type,
        staff_id=staff_id,
        requested_date=requested_date,
        requested_time=requested_time,
        comment=comment
    )

    db.session.add(new_request)
    db.session.commit()
    flash("Your missed clock-out request has been submitted!", "success")
    return redirect(url_for('staff_dashboard'))

@app.route('/submit-missed-clockin', methods=['POST'])
@login_required
def submit_missed_clockin():
    staff_type = 'driver' if isinstance(current_user, Driver) else 'escort'
    staff_id = current_user.id
    requested_date = datetime.strptime(request.form['requested_date'], '%Y-%m-%d').date()
    requested_time = datetime.strptime(request.form['requested_time'], '%H:%M').time()
    comment = request.form.get('comment')

    new_request = MissedClockInRequest(
        staff_type=staff_type,
        staff_id=staff_id,
        requested_date=requested_date,
        requested_time=requested_time,
        comment=comment
    )
    db.session.add(new_request)
    db.session.commit()
    flash("Your missed clock-in request has been submitted!", "success")
    return redirect(url_for('staff_dashboard'))

@app.route('/manager/missed-requests')
@manager_required
def view_missed_requests():
    requests = MissedClockInRequest.query.order_by(MissedClockInRequest.submitted_at.desc()).all()
    return render_template('missed_clockin_requests.html', requests=requests)

@app.route('/manager/handle-missed-clockin/<int:request_id>/<string:action>', methods=['POST'])
@manager_required
def handle_missed_clockin(request_id, action):
    req = MissedClockInRequest.query.get_or_404(request_id)

    if action == 'approve':
        # Create ClockIn record
        new_log = ClockIn(
            staff_id=req.staff_id,
            staff_type=req.staff_type,
            date=req.requested_date,
            clock_in_time=datetime.combine(req.requested_date, req.requested_time)
        )
        db.session.add(new_log)
        req.status = 'Approved'
        flash("Request approved and clock-in logged.", "success")

    elif action == 'decline':
        req.status = 'Declined'
        flash("Request declined.", "info")

    db.session.commit()
    return redirect(url_for('view_missed_requests'))
@app.route('/manager/missed-clockout-requests')
@manager_required
def view_missed_clockout_requests():
    requests = MissedClockOutRequest.query.order_by(MissedClockOutRequest.submitted_at.desc()).all()
    return render_template('missed_clockout_requests.html', requests=requests)
@app.route('/manager/handle-missed-clockout/<int:request_id>/<string:action>', methods=['POST'])
@manager_required
def handle_missed_clockout(request_id, action):
    req = MissedClockOutRequest.query.get_or_404(request_id)

    if action == 'approve':
        # Update ClockIn record
        log = ClockIn.query.filter_by(
            staff_type=req.staff_type,
            staff_id=req.staff_id,
            date=req.requested_date
        ).first()

        if log:
            log.clock_out_time = datetime.combine(req.requested_date, req.requested_time)
            log.comment = (log.comment or '') + f"\nMissed clock-out approved: {req.comment or 'No comment'}"
            req.status = 'Approved'
            db.session.commit()
            flash("Request approved and clock-out time updated.", "success")
        else:
            flash("No clock-in record found for that day.", "danger")

    elif action == 'decline':
        req.status = 'Declined'
        db.session.commit()
        flash("Request declined.", "info")

    return redirect(url_for('view_missed_clockout_requests'))

# ---------- clock logs----------

@app.route('/admin/clock-logs', methods=['GET', 'POST'])
@manager_required
def admin_clock_logs():
    staff_type = request.form.get('staff_type')
    staff_id = request.form.get('staff_id')
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')

    query = ClockIn.query

    if staff_type:
        query = query.filter_by(staff_type=staff_type)
    if staff_id:
        query = query.filter_by(staff_id=staff_id)
    if start_date:
        query = query.filter(ClockIn.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
    if end_date:
        query = query.filter(ClockIn.date <= datetime.strptime(end_date, '%Y-%m-%d').date())

    logs = query.order_by(ClockIn.date.desc(), ClockIn.clock_in_time.desc()).all()
    drivers = Driver.query.all()
    escorts = Escort.query.all()

    formatted_hours = calculate_weekly_hours()

    return render_template(
        'admin_clock_logs.html',
        logs=logs,
        drivers=drivers,
        escorts=escorts,
        formatted_hours=formatted_hours
    )

# ---------- Create Manager ----------
@app.route('/create-manager', methods=['GET', 'POST'])
def create_manager():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        existing = Manager.query.filter_by(username=username).first()
        if existing:
            flash('Username already exists.', 'danger')
        else:
            manager = Manager(
                username=username,
                password=generate_password_hash(password)  # <-- hash!
            )
            db.session.add(manager)
            db.session.commit()
            flash('Manager account created successfully!', 'success')
            return redirect(url_for('auth.manager_login'))  # note blueprint prefix

    return render_template('create_manager.html')


# ---------- Unallocated contracts ----------
@app.route('/unallocated-contracts', methods=['GET'])
@manager_required
def unallocated_contracts():
    selected_date = request.args.get('date')
    selected_shift = request.args.get('shift', 'AM')

    if not selected_date:
        selected_date = date.today().isoformat()
    selected_date_obj = datetime.strptime(selected_date, "%Y-%m-%d").date()

    # Fetch all driver allocations for the given date and shift
    allocated_ids = db.session.query(DriverAllocation.contract_id).filter_by(
        contract_date=selected_date_obj,
        driver_shift=selected_shift
    ).all()
    allocated_ids = [id for (id,) in allocated_ids]

    # Get all contracts NOT in that list
    unallocated = Contract.query.filter(~Contract.id.in_(allocated_ids)).all()

    drivers = Driver.query.all()
    escorts = Escort.query.all()

    return render_template(
        'unallocated_contracts.html',
        unallocated=unallocated,
        selected_date=selected_date,
        selected_shift=selected_shift,
        drivers=drivers,
        escorts=escorts
    )


@app.route('/assign-driver', methods=['POST'])
@manager_required
def assign_driver():
    contract_id = int(request.form.get('contract_id'))
    day = request.form.get('day')
    shift = request.form.get('shift')
    driver_id = request.form.get('driver_id') or None
    escort_id = request.form.get('escort_id') or None

    contract = Contract.query.get(contract_id)
    if not contract:
        flash("❌ Contract not found.", "error")
        return redirect(url_for('unallocated_contracts'))

    contract_number = contract.contract_number
    contract_days = day  # assigning for a single day, e.g. "Tuesday"

    # Set shifts properly based on what's selected
    driver_shift = shift if driver_id else None
    escort_shift = shift if escort_id else None

    # Only create allocation if at least one of driver or escort is selected
    if not driver_id and not escort_id:
        flash("❌ Please assign at least a driver or escort.", "error")
        return redirect(url_for('unallocated_contracts'))

    # Create the allocation
    allocation = DriverAllocation(
        contract_number=contract_number,
        contract_id=contract_id,
        contract_days=contract_days,
        repeat_all_week=True,  # ✅ Ensure it repeats weekly so it shows up
        driver_id=driver_id,
        escort_id=escort_id,
        driver_shift=driver_shift,
        escort_shift=escort_shift,
        contract_date=None  # one-off assignments can use specific dates if needed
    )
    db.session.add(allocation)
    db.session.commit()

    flash("✅ Allocation successful!", "success")
    return redirect(url_for('unallocated_contracts'))


# ---------- terms and privacy ----------
@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

@app.route("/terms")
def terms():
    return render_template("terms.html")

# ---------- drivers vehicle checks  ----------
from datetime import datetime

@app.route('/vehicle-check', methods=['GET', 'POST'])
@login_required
def vehicle_check():
    vehicles = Vehicle.query.all()
    if request.method == 'POST':
        # Parse water check and safely parse mot_date
        water_check = 'water_check' in request.form
        mot_date_str = request.form.get('mot_date')
        mot_date = None
        if mot_date_str:
            try:
                mot_date = datetime.strptime(mot_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash("Invalid MOT date format. Please use YYYY-MM-DD.", "danger")
                return redirect(url_for('vehicle_check'))

        check = VehicleCheck(
            vehicle_id=request.form['vehicle_id'],
            staff_id=current_user.id,
            staff_type='driver' if isinstance(current_user, Driver) else 'escort',
            mileage=request.form['mileage'],
            lights_ok='lights_ok' in request.form,
            tires_ok='tires_ok' in request.form,
            oil_level_ok='oil_level_ok' in request.form,
            notes=request.form.get('notes'),
            water_check=water_check,
            mot_date=mot_date
        )

        db.session.add(check)
        db.session.commit()
        flash("✅ Vehicle check submitted!", "success")
        return redirect(url_for('staff_dashboard'))

    return render_template('vehicle_check.html', vehicles=vehicles)


@app.route('/manager/vehicle-checks')
@role_required(['manager', 'mechanic'])
def view_vehicle_checks():
    checks = VehicleCheck.query.order_by(VehicleCheck.date.desc()).all()

    enriched_checks = []
    for check in checks:
        vehicle = Vehicle.query.get(check.vehicle_id)
        staff_name = "Unknown"
        if check.staff_type == 'driver':
            driver = Driver.query.get(check.staff_id)
            staff_name = driver.name if driver else "Unknown"
        elif check.staff_type == 'escort':
            escort = Escort.query.get(check.staff_id)
            staff_name = escort.name if escort else "Unknown"

        enriched_checks.append({
            'date': check.date.strftime('%Y-%m-%d'),
            'vehicle': f"{vehicle.registration} - {vehicle.make_model}" if vehicle else "Unknown",
            'staff_name': staff_name,
            'mileage': check.mileage,
            'lights_ok': check.lights_ok,
            'tires_ok': check.tires_ok,
            'oil_level_ok': check.oil_level_ok,
            'notes': check.notes or '—'
        })

    return render_template('admin_vehicle_checks.html', checks=enriched_checks)

def calculate_quote(vehicle_type, tariff, mileage):
    rate_entry = TariffRate.query.filter_by(vehicle_type=vehicle_type, tariff=tariff).first()
    if not rate_entry:
        return 0.0
    base_price = max(rate_entry.rate_per_mile * mileage, 5.00)  # apply £5 minimum fare
    return round(base_price, 2)


@app.route('/generate-quote', methods=['GET', 'POST'])
def generate_quote():
    quote = None
    if request.method == 'POST':
        vehicle_type = request.form['vehicle_type']
        tariff = request.form['tariff']
        mileage = float(request.form['mileage'])

        rate = TariffRate.query.filter_by(vehicle_type=vehicle_type, tariff=tariff).first()

        print("Vehicle:", vehicle_type)
        print("Tariff:", tariff)
        print("Mileage:", mileage)
        print("Rate found:", rate)

        if rate:
            total_price = max(rate.rate_per_mile * mileage, 5.00)
            total_price = round(total_price, 2)

            quote = Quote(
                vehicle_type=vehicle_type,
                tariff=tariff,
                mileage=mileage,
                total_price=total_price
            )
            db.session.add(quote)
            db.session.commit()

    return render_template('manager_generate_quote.html', quote=quote)


@app.route('/quotes')
def view_quotes():
    quotes = Quote.query.order_by(Quote.created_at.desc()).all()
    return render_template('manager_view_quotes.html', quotes=quotes)

#@app.route('/quote/<int:quote_id>/download')
#def download_quote_pdf(quote_id):
    quote = Quote.query.get_or_404(quote_id)
    rendered = render_template('quote_pdf_template.html', quote=quote)

    pdf = BytesIO()
    pisa_status = pisa.CreatePDF(rendered, dest=pdf)

    if pisa_status.err:
        return "PDF generation failed", 500

    response = make_response(pdf.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=quote_{quote.id}.pdf'
    return response

# ---------- Drivers location ----------
@app.route('/update-location', methods=['POST'])
def update_location():
    data = request.get_json()

    # Extract location data
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    
    # Assume you have a DriverLocation model to store this data
    driver_id = current_user.id  # Or however you get the driver's ID
    
    # Save the location to the database
    new_location = DriverLocation(
        driver_id=driver_id,
        latitude=latitude,
        longitude=longitude,
        timestamp=datetime.utcnow()
    )
    db.session.add(new_location)
    db.session.commit()

    return jsonify({"message": "Location updated successfully!"}), 200

# ---------- Drivers location ----------

def get_missing_vehicle_checks():
    today = date.today()

    all_drivers = Driver.query.all()
    checks_today = VehicleCheck.query.filter_by(date=today).all()

    checked_ids = {(check.staff_id, check.staff_type) for check in checks_today}

    missing = []
    for driver in all_drivers:
        if (driver.id, 'driver') not in checked_ids:
            missing.append(driver)

    return missing

@app.route('/staff-management')
@manager_required
def staff_management():
    drivers = Driver.query.all()
    escorts = Escort.query.all()
    mechanics = Mechanic.query.all()
    return render_template('staff_management.html', drivers=drivers, escorts=escorts, mechanics=mechanics)

@app.route('/edit-mechanic/<int:mechanic_id>', methods=['GET', 'POST'])
def edit_mechanic(mechanic_id):
    mechanic = Mechanic.query.get_or_404(mechanic_id)
    if request.method == 'POST':
        mechanic.name = request.form['name']
        mechanic.username = request.form['username']
        db.session.commit()
        flash('Mechanic updated!', 'success')
        return redirect(url_for('staff_management'))
    return render_template('edit_mechanic.html', mechanic=mechanic)

@app.route('/delete-mechanic/<int:mechanic_id>')
def delete_mechanic(mechanic_id):
    mechanic = Mechanic.query.get_or_404(mechanic_id)
    db.session.delete(mechanic)
    db.session.commit()
    flash('Mechanic deleted!', 'warning')
    return redirect(url_for('staff_management'))

@app.route('/allocate-mechanic-job', methods=['GET', 'POST'])
@manager_required
def allocate_mechanic_job():
    mechanics = Mechanic.query.all()
    vehicles = Vehicle.query.all()

    if request.method == 'POST':
        job = MechanicJob(
            mechanic_id=request.form['mechanic_id'],
            job_description=request.form['job_description'],
            vehicle_id=request.form['vehicle_id']
        )
        db.session.add(job)
        db.session.commit()
        flash("🛠️ Mechanic job allocated successfully", "success")
        return redirect(url_for('manager_dashboard'))

    return render_template('allocate_mechanic_job.html', mechanics=mechanics, vehicles=vehicles)

@app.route('/view-mechanic-jobs')
@role_required('manager,mechanic')
def view_mechanic_jobs():
    jobs = MechanicJob.query.all()
    return render_template('view_mechanic_jobs.html', jobs=jobs)


@app.route('/log-fuel', methods=['GET', 'POST'])
@login_required
def log_fuel():
    if request.method == 'POST':
        amount = request.form.get('amount')
        date = request.form.get('date')
        receipt = request.files.get('receipt_photo')

        filename = None
        if receipt and receipt.filename != '':
            filename = secure_filename(receipt.filename)
            filepath = os.path.join('static', 'receipts', filename)
            receipt.save(filepath)

        transaction = FuelCardTransaction(
            user_id=current_user.id,
            amount=float(amount),
            date=datetime.strptime(date, "%Y-%m-%d"),
            receipt_filename=filename  # This will be None if no receipt uploaded
        )
        db.session.add(transaction)
        db.session.commit()

        flash("⛽ Fuel transaction logged successfully!", "success")
        return redirect(url_for('staff_dashboard'))

    return render_template('log_fuel.html')


@app.route('/admin/fuel-logs', methods=['GET'])
@manager_required
def view_fuel_logs():
    staff_type = request.args.get('staff_type')
    staff_id = request.args.get('staff_id')
    date_str = request.args.get('date')

    logs_query = FuelCardTransaction.query

    # Filter by staff type and ID
    if staff_type and staff_id:
        logs_query = logs_query.filter(
            FuelCardTransaction.staff_type == staff_type,
            FuelCardTransaction.user_id == int(staff_id)
        )

    # Filter by date
    if date_str:
        try:
            filter_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            logs_query = logs_query.filter(FuelCardTransaction.date == filter_date)
        except ValueError:
            flash("Invalid date format", "danger")

    logs = logs_query.order_by(FuelCardTransaction.date.desc()).all()

    # Get all staff names by role
    drivers = Driver.query.all()
    escorts = Escort.query.all()
    mechanics = Mechanic.query.all()

    return render_template(
        'admin_fuel_logs.html',
        logs=logs,
        drivers=drivers,
        escorts=escorts,
        mechanics=mechanics
    )

@app.route('/api/save_allocations', methods=['POST'])
def save_allocations():
    try:
        data = request.get_json()
        allocation_date = data.get('allocation_date')
        allocations = data.get('allocations', [])

        print("Allocations received:", allocations)
        print("Date received:", allocation_date)

        if not allocation_date:
            return jsonify({'error': 'Missing allocation date'}), 400

        for item in allocations:
            driver_id = item.get('driver_id')
            contract_id = item.get('contract_id')
            escort_id = item.get('escort_id')
            driver_shift = item.get('driver_shift', '')
            escort_shift = item.get('escort_shift', '')

            # Load related DB entries
            driver = Driver.query.get(driver_id)
            contract = Contract.query.get(contract_id)

            if not contract.contract_number:
                print(f"Skipping: contract has no number for contract_id={contract_id}")
                continue


            contract_number = contract.contract_number
            escort_id = int(escort_id) if escort_id else None

            new_allocation = DriverAllocation(
                contract_number=contract_number,
                contract_id=contract.id,
                driver_id=driver.id,
                escort_id=escort_id,
                driver_shift=driver_shift,
                escort_shift=escort_shift,
                contract_date=datetime.strptime(allocation_date, '%Y-%m-%d').date()
            )

            db.session.add(new_allocation)

        db.session.commit()
        return jsonify({'success': True})

    except Exception as e:
        print("Error while saving allocations:", str(e))
        return jsonify({'error': str(e)}), 500



@app.route('/api/allocated_contracts')
def get_allocated_contracts():
    date_str = request.args.get('date')
    shift = request.args.get('shift')

    if not date_str or not shift:
        return jsonify([])

    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()

    allocated = DriverAllocation.query.filter_by(contract_date=date_obj, driver_shift=shift).all()
    allocated_ids = list(set([a.contract_id for a in allocated if a.contract_id]))

    return jsonify(allocated_ids)

from geopy.distance import geodesic

FUEL_COST_PER_LITRE = 1.50
KM_PER_LITRE = 12.75  # ~30 MPG
AVERAGE_SPEED_KMPH = 40  # average travel speed


@app.route('/calculate_route', methods=['POST'])
def calculate_route():
    data = request.get_json()

    driver_postcode = data.get('driver_postcode')
    children_postcodes = data.get('children_postcodes', [])
    school_postcode = data.get('school_postcode')
    escort_postcode = data.get('escort_postcode')

    total_distance = 0
    breakdown = {}

    # Step 1: Driver → Escort
    if escort_postcode:
        distance_driver_to_escort = get_distance_between_postcodes(driver_postcode, escort_postcode)
        breakdown['driver_to_escort'] = distance_driver_to_escort
        if distance_driver_to_escort is not None:
            total_distance += distance_driver_to_escort

    # Step 2: Escort → Children
    if escort_postcode and children_postcodes:
        escort_to_children = []
        for child_postcode in children_postcodes:
            distance = get_distance_between_postcodes(escort_postcode, child_postcode)
            escort_to_children.append({child_postcode: distance})
            if distance is not None:
                total_distance += distance
        breakdown['escort_to_children'] = escort_to_children

    # Step 3: Children → School
    children_to_school = []
    if children_postcodes and school_postcode:
        for child_postcode in children_postcodes:
            distance = get_distance_between_postcodes(child_postcode, school_postcode)
            children_to_school.append({child_postcode: distance})
            if distance is not None:
                total_distance += distance
        breakdown['children_to_school'] = children_to_school

    # Step 4: School → Escort
    if escort_postcode:
        distance_school_to_escort = get_distance_between_postcodes(school_postcode, escort_postcode)
        breakdown['school_to_escort'] = distance_school_to_escort
        if distance_school_to_escort is not None:
            total_distance += distance_school_to_escort

        # Step 5: Escort → Driver
        distance_escort_to_driver = get_distance_between_postcodes(escort_postcode, driver_postcode)
        breakdown['escort_to_driver'] = distance_escort_to_driver
        if distance_escort_to_driver is not None:
            total_distance += distance_escort_to_driver

    # Step 6: School → Driver (if no escort)
    if not escort_postcode:
        distance_school_to_driver = get_distance_between_postcodes(school_postcode, driver_postcode)
        breakdown['school_to_driver'] = distance_school_to_driver
        if distance_school_to_driver is not None:
            total_distance += distance_school_to_driver

    return jsonify({
        'total_distance': total_distance,
        'breakdown': breakdown
    }), 200

@app.route('/route_calculation', methods=['GET'])
def route_calculation():
    return render_template('route_calculation.html')


geolocator = Nominatim(user_agent="evans-taxi-app")

def get_coordinates(postcode):
    try:
        location = geolocator.geocode(postcode)
        time.sleep(1)  # to avoid rate limiting
        if location:
            return (location.latitude, location.longitude)
    except Exception as e:
        print(f"Geolocation error for {postcode}: {e}")
    return None

def calculate_route_estimates(driver_postcode, child_postcode, school_postcode, fuel_cost_per_litre=1.50, mpg=35):
    coords_driver = get_coordinates(driver_postcode)
    coords_child = get_coordinates(child_postcode)
    coords_school = get_coordinates(school_postcode)

    if not coords_driver or not coords_child or not coords_school:
        return None, None, None

    total_distance_km = (
        geodesic(coords_driver, coords_child).km +
        geodesic(coords_child, coords_school).km
    )

    estimated_time_minutes = total_distance_km / 50 * 60  # assume 50km/h avg
    litres_used = total_distance_km / mpg * 4.546  # miles per gallon to litres
    fuel_cost = litres_used * fuel_cost_per_litre

    return round(total_distance_km, 2), round(estimated_time_minutes), round(fuel_cost, 2)

@app.route('/api/contracts')
@manager_required
def get_contracts():
    contracts = Contract.query.all()
    return jsonify([
        {
            "id": c.id,
            "contract_number": c.contract_number,
            "school_name": c.school_name,
            "pickup_time": c.route_start_time.strftime('%H:%M') if c.route_start_time else "",
            "school_time": c.route_finish_time.strftime('%H:%M') if c.route_finish_time else "",
            "required_vehicle_size": c.required_vehicle_size  # ✅ This line is key
        } for c in contracts
    ])

@app.route('/weekly-driver-summary')
def weekly_driver_summary():
    today = datetime.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)

    allocations = DriverAllocation.query.filter(
        DriverAllocation.contract_date >= start_of_week.date(),
        DriverAllocation.contract_date <= end_of_week.date()
    ).all()

    summary = {}

    for alloc in allocations:
        driver = alloc.driver
        contract = alloc.contract
        escort = alloc.escort

        # Skip if contract or driver is missing (avoid crashes)
        if not contract or not driver:
            continue

        driver_postcode = driver.base_postcode
        child_postcode = contract.children[0].child_postcode if contract.children else None
        school_postcode = contract.school_postcode
        escort_postcode = escort.base_postcode if escort else None

        if not driver_postcode or not child_postcode or not school_postcode:
            continue  # Missing data, skip

        distance = 0

        if escort_postcode:
            d1 = get_distance_between_postcodes(driver_postcode, escort_postcode)
            d2 = get_distance_between_postcodes(escort_postcode, child_postcode)
            d3 = get_distance_between_postcodes(child_postcode, school_postcode)
            d4 = get_distance_between_postcodes(school_postcode, escort_postcode)
            d5 = get_distance_between_postcodes(escort_postcode, driver_postcode)
            for d in [d1, d2, d3, d4, d5]:
                distance += d if d else 0
        else:
            d1 = get_distance_between_postcodes(driver_postcode, child_postcode)
            d2 = get_distance_between_postcodes(child_postcode, school_postcode)
            d3 = get_distance_between_postcodes(school_postcode, driver_postcode)
            for d in [d1, d2, d3]:
                distance += d if d else 0

        fuel_used = round((distance / 12.75) * 1.50, 2)

        driver_name = driver.name

        if driver_name not in summary:
            summary[driver_name] = {
                'distance': 0,
                'fuel': 0.0,
                'days': []
            }

        summary[driver_name]['distance'] += round(distance, 2)
        summary[driver_name]['fuel'] += fuel_used
        summary[driver_name]['days'].append(alloc.contract_date)

    return render_template(
        'weekly_driver_summary.html',
        summary=summary,
        start=start_of_week.date(),
        end=end_of_week.date()
    )

@app.before_request
def before_request_func():
    if db.engine.url.drivername == 'sqlite':
        db.session.execute(text('PRAGMA foreign_keys = ON'))



# Handle 404 errors
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

# Handle 500 errors
@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

# Optional: Catch all unhandled exceptions
@app.errorhandler(Exception)
def all_exception_handler(error):
    app.logger.error(f"Unhandled Exception: {error}")
    return render_template('error.html', error=error), 500

@app.route('/manager/change-password', methods=['GET', 'POST'])
@manager_required
def change_manager_password():
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if not current_user.check_password(current_password):
            flash("❌ Current password is incorrect.", "danger")
            return redirect(url_for('change_manager_password'))

        if new_password != confirm_password:
            flash("❌ New passwords do not match.", "danger")
            return redirect(url_for('change_manager_password'))

        current_user.password = generate_password_hash(new_password)
        db.session.commit()
        flash("✅ Your password has been updated!", "success")
        return redirect(url_for('manager_dashboard'))

    return render_template('manager_change_password.html')

from flask import render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash
from model import Driver, Escort, Mechanic  # Make sure these are imported

@app.route('/reset-password/<role>/<int:user_id>', methods=['GET', 'POST'])
def reset_user_password(role, user_id):
    if role == 'driver':
        user = Driver.query.get_or_404(user_id)
    elif role == 'escort':
        user = Escort.query.get_or_404(user_id)
    elif role == 'mechanic':
        user = Mechanic.query.get_or_404(user_id)
    else:
        flash('Invalid role type.', 'danger')
        return redirect(url_for('staff_management'))

    if request.method == 'POST':
        new_password = request.form['new_password']
        user.password = generate_password_hash(new_password)
        db.session.commit()
        flash(f'{role.capitalize()} password updated successfully!', 'success')
        return redirect(url_for('staff_management'))

    return render_template('reset_user_password.html', user=user, role=role)

if __name__ == "__main__":
    print("Registered Routes:")
    for rule in app.url_map.iter_rules():
        print(rule)
    app.run(host="0.0.0.0", port=5000, debug=True)






