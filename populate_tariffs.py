# populate_tariffs.py
from app import app, db
from model import TariffRate


with app.app_context():
    rates = [
        ('Saloon', 'low', 2.50), ('Saloon', 'mid', 3.00), ('Saloon', 'premium', 3.50),
        ('People Carrier', 'low', 3.00), ('People Carrier', 'mid', 3.50), ('People Carrier', 'premium', 4.00),
        ('Minibus', 'low', 3.50), ('Minibus', 'mid', 4.00), ('Minibus', 'premium', 4.50),
        ('Mini Coach', 'low', 4.00), ('Mini Coach', 'mid', 4.50), ('Mini Coach', 'premium', 5.00),
        ('Midi Coach', 'low', 4.50), ('Midi Coach', 'mid', 5.00), ('Midi Coach', 'premium', 5.50),
        ('Full Coach', 'low', 5.00), ('Full Coach', 'mid', 5.50), ('Full Coach', 'premium', 6.00),
    ]

    for vt, tariff, rate in rates:
        db.session.add(TariffRate(vehicle_type=vt, tariff=tariff, rate_per_mile=rate))
    db.session.commit()
    print("✅ Tariff rates successfully added.")
