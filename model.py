from flask_sqlalchemy import SQLAlchemy
from datetime import datetime,date
from flask_login import UserMixin

db = SQLAlchemy()

# ---------------------- Manager ----------------------
class Manager(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='manager')
    def get_id(self):
     return f"{self.role}:{self.id}"


# ---------------------- Driver ----------------------
class Driver(UserMixin, db.Model):
    __tablename__ = 'drivers'  

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    badge_renewal_date = db.Column(db.Date)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='driver')
    base_postcode = db.Column(db.String(20))
    shift = db.Column(db.String(10), default='Both') 

    locations = db.relationship(
    'DriverLocation',
    backref='driver',
    cascade='all, delete-orphan'
)


    def get_id(self):
        return f"{self.role}:{self.id}"

# ---------------------- Escort ----------------------
class Escort(UserMixin, db.Model):
    __tablename__ = 'escorts'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    address = db.Column(db.String(200))
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='escort')
    base_postcode = db.Column(db.String(20))

    def get_id(self):
     return f"{self.role}:{self.id}"

# ---------------------- Contract ----------------------
class Contract(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contract_number = db.Column(db.String(100), unique=True, nullable=False)
    school_name = db.Column(db.String(100), nullable=False)
    school_start_time = db.Column(db.Time, nullable=False)
    school_finish_time = db.Column(db.Time, nullable=False)
    children = db.relationship('Child', backref='contract', cascade="all, delete-orphan")
    route_start_time = db.Column(db.Time)
    route_finish_time = db.Column(db.Time)
    required_vehicle_size = db.Column(db.String(50))
    commute_time = db.Column(db.Integer)
    school_postcode = db.Column(db.String(20), nullable=True) 
    escort_required = db.Column(db.Boolean, default=False)


# ---------------------- Child ----------------------
class Child(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    contract_id = db.Column(db.Integer, db.ForeignKey('contract.id'), nullable=False)
    child_postcode = db.Column(db.String(20))

# ---------------------- Vehicle ----------------------
class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    registration = db.Column(db.String(50), nullable=False)
    make_model = db.Column(db.String(100))
    plate_number = db.Column(db.String(50))
    mot_renewal_date = db.Column(db.Date)
    mot_6_monthly_date = db.Column(db.Date, nullable=True)
    plate_expiry_date = db.Column(db.Date)
    tax_expiry_date = db.Column(db.Date)
    insured = db.Column(db.Boolean, default=False)
    vehicle_size = db.Column(db.String(50)) 
    is_available = db.Column(db.Boolean, default=True)

# ---------------------- Driver Allocation ----------------------
class DriverAllocation(db.Model):
    __tablename__ = 'driver_allocation' 
    id = db.Column(db.Integer, primary_key=True)
    contract_number = db.Column(db.String(100), nullable=False)
    contract_id = db.Column(db.Integer, db.ForeignKey('contract.id'))
    driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'))
    escort_id = db.Column(db.Integer, db.ForeignKey('escorts.id'), nullable=True)
    driver_shift = db.Column(db.String(20))
    escort_shift = db.Column(db.String(20), nullable=True)
    contract_days = db.Column(db.String(100), nullable=True)
    repeat_all_week = db.Column(db.Boolean, default=False)
    contract_date = db.Column(db.Date, nullable=True)

    driver = db.relationship('Driver', backref='allocations')
    escort = db.relationship('Escort', backref='allocations')
    contract = db.relationship('Contract', backref='allocations')

# ---------------------- Clock In / Out ----------------------
class ClockIn(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_type = db.Column(db.String(20), nullable=False)  # 'driver' or 'escort'
    staff_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, default=datetime.utcnow)
    clock_in_time = db.Column(db.DateTime, nullable=True)
    clock_out_time = db.Column(db.DateTime, nullable=True)
    comment = db.Column(db.Text, nullable=True)

# ---------------------- Leave ----------------------
class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    person_type = db.Column(db.String(20), nullable=False)  # 'driver' or 'escort'
    person_id = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text)
    approved = db.Column(db.Boolean, nullable=True)  # None = pending

# ---------------------- Feedback ----------------------
class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_type = db.Column(db.String(20))  # 'driver' or 'escort'
    staff_id = db.Column(db.Integer)
    message = db.Column(db.Text, nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------------- Missed Clock In ----------------------
class MissedClockInRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_type = db.Column(db.String(20))
    staff_id = db.Column(db.Integer)
    requested_date = db.Column(db.Date)
    requested_time = db.Column(db.Time)
    comment = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='Pending')

# ---------------------- Missed Clock Out ----------------------
class MissedClockOutRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_type = db.Column(db.String(20))
    staff_id = db.Column(db.Integer)
    requested_date = db.Column(db.Date)
    requested_time = db.Column(db.Time)
    comment = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='Pending')

# ---------------------- Missed school runs ----------------------
class MissedRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    allocation_id = db.Column(
        db.Integer,
        db.ForeignKey('driver_allocation.id', ondelete="CASCADE")
    )
    staff_name = db.Column(db.String(100))
    contract_number = db.Column(db.String(50))
    shift = db.Column(db.String(10))
    reason = db.Column(db.String(100))
    date = db.Column(db.Date)

    allocation = db.relationship("DriverAllocation", backref=db.backref("missed_runs", cascade="all, delete"))


# ---------------------- Drivers vehicle checks  ----------------------
class VehicleCheck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    staff_id = db.Column(db.Integer, nullable=False)
    staff_type = db.Column(db.String(20), nullable=False)  # 'driver' or 'escort' if needed
    date = db.Column(db.Date, default=date.today)
    mileage = db.Column(db.String(50))
    lights_ok = db.Column(db.Boolean, default=True)
    tires_ok = db.Column(db.Boolean, default=True)
    oil_level_ok = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)
    water_check = db.Column(db.Boolean, default=False)
    mot_date = db.Column(db.Date)

class RunStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    allocation_id = db.Column(
        db.Integer,
        db.ForeignKey('driver_allocation.id', ondelete="CASCADE")
    )
    staff_id = db.Column(db.Integer)
    staff_type = db.Column(db.String(50))
    run_date = db.Column(db.Date)
    shift = db.Column(db.String(10))  
    completed = db.Column(db.Boolean, default=False)
    reason = db.Column(db.String(200))

    allocation = db.relationship("DriverAllocation", backref=db.backref("run_statuses", cascade="all, delete"))


# ---------------------- Quotes ----------------------

class TariffRate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_type = db.Column(db.String(50), nullable=False)  
    tariff = db.Column(db.String(50), nullable=False)         
    rate_per_mile = db.Column(db.Float, nullable=False)
    
class Quote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_type = db.Column(db.String(50), nullable=False)
    tariff = db.Column(db.String(50), nullable=False)
    mileage = db.Column(db.Float, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
 
# ---------------------- School Holidays ----------------------

class SchoolTerm(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    def __repr__(self):
        return f"<SchoolTerm {self.name}: {self.start_date} to {self.end_date}>"

class NonSchoolDay(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        date = db.Column(db.Date, nullable=False, unique=True)
        school_name = db.Column(db.String(200), nullable=False)  # Added school_name
        reason = db.Column(db.String(200), nullable=True)

        def __repr__(self):
            return f"<NonSchoolDay {self.date}: {self.school_name} ({self.reason})>"

# ---------------------- Track drivers ----------------------
class DriverLocation(db.Model):
    __tablename__ = 'driver_locations'

    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False)  # ForeignKey reference to Driver's id
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    
    def __repr__(self):
        return f"<DriverLocation {self.driver_id} - {self.timestamp}>"

# ----------------------Mechanics----------------------

class Mechanic(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100)) 
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), default='mechanic')

    def get_id(self):
        return f"{self.role}:{self.id}"

from datetime import datetime

class MechanicJob(db.Model):
    __tablename__ = 'mechanic_jobs'

    id = db.Column(db.Integer, primary_key=True)
    mechanic_id = db.Column(db.Integer, db.ForeignKey('mechanic.id'), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    job_description = db.Column(db.Text, nullable=False)
    job_date = db.Column(db.Date, default=date.today, nullable=False)
    status = db.Column(db.String(50), default='Pending')  # Keep this
    completed_at = db.Column(db.DateTime, nullable=True)
    manager_confirmed = db.Column(db.Boolean, default=False)

    mechanic = db.relationship('Mechanic', backref='jobs')
    vehicle = db.relationship('Vehicle', backref='mechanic_jobs')


# ---------------------- Fuel Card Transactions ----------------------

class FuelCardTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('drivers.id'))  # assuming only drivers use fuel cards
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'))
    amount = db.Column(db.Float, nullable=False)
    litres = db.Column(db.Float, nullable=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    receipt_image = db.Column(db.String(255))

    user = db.relationship('Driver', backref='fuel_transactions')
    vehicle = db.relationship('Vehicle', backref='fuel_transactions')

class InsetDay(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    school_name = db.Column(db.String(200), nullable=False)
    reason = db.Column(db.String(200), nullable=True)

    def __repr__(self):
        return f"<InsetDay {self.date} - {self.school_name}>"





