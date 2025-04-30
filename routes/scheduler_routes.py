from flask import Blueprint, jsonify, request
from model import Driver, Contract,Vehicle, Escort
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import time
from flask import jsonify, request
from geopy.distance import geodesic


from flask import render_template

scheduler_bp = Blueprint('scheduler', __name__)

@scheduler_bp.route('/scheduler')
def scheduler_view():
    return render_template('scheduler.html')

@scheduler_bp.route('/api/contracts')
def get_contracts():
    contracts = Contract.query.all()  # Optional: filter only unassigned ones
    contract_data = [
        {
            'id': c.id,
            'contract_number': c.contract_number,
            'school_name': c.school_name,
            'pickup_time': c.school_start_time.strftime('%H:%M'),
            'school_time': c.school_finish_time.strftime('%H:%M'),
            'required_vehicle_size': c.required_vehicle_size
        } for c in contracts
    ]
    return jsonify(contract_data)

from geopy.geocoders import Nominatim
import time

# Initialize the geolocator (place this at the top of your file)
geolocator = Nominatim(user_agent="evans-taxi-app")

def geocode_postcode(postcode):
    try:
        # Geocode the postcode
        location = geolocator.geocode(postcode)
        time.sleep(1)  # to avoid rate limiting
        if location:
            return (location.latitude, location.longitude)
        else:
            return None
    except Exception as e:
        print(f"Geolocation error for {postcode}: {e}")
        return None

@scheduler_bp.route('/api/suggestions')
def suggest_driver():
    # Get parameters from the request
    contract_id = request.args.get('contract_id')
    shift = request.args.get('shift')
    date = request.args.get('date')

    # Check if all required parameters are provided
    if not contract_id or not shift or not date:
        return jsonify({"error": "Missing required parameters: contract_id, shift, and date"}), 400

    print(f"Received data: contract_id={contract_id}, shift={shift}, date={date}")

    # Fetch the contract
    contract = Contract.query.get(contract_id)
    if not contract or not contract.children or not contract.children[0].child_postcode:
        print(f"Contract not found or no child postcode available.")
        return jsonify([])

    suggested = []  # Initialize the list to store driver suggestions

    # Fetch drivers based on the shift
    for driver in Driver.query.filter_by(shift=shift).all():
        print(f"Checking driver: {driver.name} with base postcode: {driver.base_postcode}")

        if not driver.base_postcode:
            continue

        # Geocode the postcodes
        driver_coords = geocode_postcode(driver.base_postcode)
        contract_coords = geocode_postcode(contract.children[0].child_postcode)

        if driver_coords and contract_coords:
            # Calculate the distance between the driver and contract
            distance_km = geodesic(driver_coords, contract_coords).km
            time_min = round((distance_km / 40) * 60)  # 40 km/h avg speed
            fuel_cost = round((distance_km / 12.75) * 1.50, 2)  # Fuel cost calculation

            # Add the driver suggestion
            suggested.append({
                'id': driver.id,
                'name': driver.name,
                'distance_km': round(distance_km, 2),
                'est_time_minutes': time_min,
                'fuel_cost': fuel_cost
            })

    # Sort by distance and return suggestions
    suggested.sort(key=lambda x: x['distance_km'])
    print(f"Suggested drivers: {suggested}")

    return jsonify(suggested)

# Geocode Postcode Function
def geocode_postcode(postcode):
    try:
        # Geocode the postcode
        location = geolocator.geocode(postcode)
        time.sleep(1)  # to avoid rate limiting
        if location:
            return (location.latitude, location.longitude)
        else:
            return None
    except Exception as e:
        print(f"Geolocation error for {postcode}: {e}")
        return None



@scheduler_bp.route('/api/drivers')
def get_drivers():
    drivers = Driver.query.all()
    driver_data = [
        {
            'id': d.id,
            'name': d.name,
            'shift_start': '07:00',  
            'shift_end': '16:00'
        } for d in drivers
    ]
    return jsonify(driver_data)
@scheduler_bp.route('/api/vehicles')
def get_vehicles():
    # Assuming you have a Vehicle model
    vehicles = Vehicle.query.all()
    return jsonify([
        {
            'id': v.id,
            'make_model': v.make_model,
            'vehicle_size': v.vehicle_size
        } for v in vehicles
    ])
@scheduler_bp.route('/api/escorts')
def get_escorts():
    escorts = Escort.query.all()
    return jsonify([
        {
            'id': e.id,
            'name': e.name,
            'phone': e.phone
        } for e in escorts
    ])


