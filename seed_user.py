from app import app
from model import db, Manager, Driver, Escort, Mechanic
from werkzeug.security import generate_password_hash

with app.app_context():
    # Manager
    if not Manager.query.filter_by(username='manager1').first():
        manager = Manager(
            username='manager1',
            password=generate_password_hash('managerpass')
        )
        db.session.add(manager)

    # Driver
    if not Driver.query.filter_by(username='driver1').first():
        driver = Driver(
            name='Driver One',
            username='driver1',
            password=generate_password_hash('driverpass')
        )
        db.session.add(driver)

    # Escort
    if not Escort.query.filter_by(username='escort1').first():
        escort = Escort(
            name='Escort One',
            username='escort1',
            password=generate_password_hash('escortpass')
        )
        db.session.add(escort)

    # Mechanic
    if not Mechanic.query.filter_by(username='mechanic1').first():
        mechanic = Mechanic(
            username='mechanic1',
            password=generate_password_hash('mechanicpass'),
            role='mechanic'
        )
        db.session.add(mechanic)

    db.session.commit()
    print("✅ All test users seeded successfully!")
