from model import DriverAllocation, Leave,ClockIn,Contract, Driver
from datetime import datetime, timedelta, date
from flask import redirect, url_for, flash
from flask_login import current_user
from functools import wraps
from collections import defaultdict
import os
import requests
from dotenv import load_dotenv

load_dotenv()  # loads key from .env

ORS_API_KEY = os.getenv("SCHOOL_APP_ORS_KEY")



def manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or getattr(current_user, 'role', '') != 'manager':
            flash("Access denied. Managers only.", "danger")
            return redirect(url_for('auth.manager_login'))
        return f(*args, **kwargs)
    return decorated_function


def get_daily_allocations(target_date):
    weekday_name = target_date.strftime('%A')
    all_allocations = DriverAllocation.query.all()

    daily_allocations = []

    for alloc in all_allocations:
        if alloc.contract_days:
            days = [d.strip() for d in alloc.contract_days.split(',')]
        else:
            days = []

        if alloc.repeat_all_week:
         if weekday_name not in days:
          continue
        elif alloc.contract_date != target_date:
         continue


        leave = Leave.query.filter_by(
            person_id=alloc.driver_id,
            person_type='driver',
            approved=True
        ).filter(
            Leave.start_date <= target_date,
            Leave.end_date >= target_date
        ).first()

        if leave:
            continue

        daily_allocations.append(alloc)

    return daily_allocations

  #Total Hours Worked This Week
  

def calculate_weekly_hours():
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)

    weekly_logs = ClockIn.query.filter(
        ClockIn.date >= start_of_week,
        ClockIn.date <= end_of_week
    ).all()

    hours_worked = defaultdict(timedelta)
    for log in weekly_logs:
        if log.clock_in_time and log.clock_out_time:
            duration = log.clock_out_time - log.clock_in_time
            hours_worked[(log.staff_type, log.staff_id)] += duration

    formatted_hours = {
        key: f"{int(value.total_seconds() // 3600)}h {int((value.total_seconds() % 3600) // 60)}m"
        for key, value in hours_worked.items()
    }

    return formatted_hours

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                flash("You do not have access to this page.", "danger")
                return redirect(url_for('welcome'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


import os
ORS_API_KEY = os.getenv("SCHOOL_APP_ORS_KEY") 

def get_distance_between_postcodes(postcode1, postcode2, escort_postcode=None, children_postcodes=None, school_postcode=None):
    try:
        headers = {
            'Authorization': ORS_API_KEY,
            'Content-Type': 'application/json'
        }

        def get_coords(postcode):
            """Get coordinates for a postcode"""
            response = requests.get(
                f"https://api.openrouteservice.org/geocode/search?api_key={ORS_API_KEY}&text={postcode}"
            )
            response.raise_for_status()
            data = response.json()

            features = data.get('features')
            if not features:
                print(f"[ERROR] No coordinates found for postcode: {postcode}")
                return None

            coords = features[0]['geometry']['coordinates']
            print(f"[INFO] {postcode} → {coords}")
            return coords

        # Get all coordinates
        driver_coords = get_coords(postcode1)
        school_coords = get_coords(school_postcode)
        children_coords = [get_coords(pc) for pc in children_postcodes or []]
        escort_coords = get_coords(escort_postcode) if escort_postcode else None

        # Ensure all required locations resolved successfully
        if not driver_coords or not school_coords or any(c is None for c in children_coords):
            print("[ERROR] Required location(s) missing. Aborting route calculation.")
            return None

        # Build route: [Driver → Escort? → Children... → School → Escort (return)? → Driver]
        locations = [driver_coords]
        if escort_coords:
            locations.append(escort_coords)
        locations.extend(children_coords)
        locations.append(school_coords)
        if escort_coords:
            locations.append(escort_coords)  # return to escort
        locations.append(driver_coords)  # back to driver

        # Prepare the matrix request
        body = {
            "locations": locations,
            "metrics": ["distance"],
            "units": "km"
        }

        r = requests.post("https://api.openrouteservice.org/v2/matrix/driving-car", json=body, headers=headers)
        r.raise_for_status()
        dist_data = r.json()

        # Sum distances along the route (sequential pairs)
        total_distance = 0
        for i in range(len(locations) - 1):
            try:
                step_distance = dist_data["distances"][i][i + 1]
                total_distance += step_distance
            except Exception as e:
                print(f"[ERROR] Missing distance between step {i} and {i + 1}: {e}")
                return None

        print(f"[SUCCESS] Total route distance: {total_distance:.2f} km")
        return total_distance

    except requests.exceptions.RequestException as e:
        print(f"[Request Error] {e}")
    except ValueError as e:
        print(f"[Value Error] {e}")
    except Exception as e:
        print(f"[Unexpected Error] {e}")

    return None



def check_driver_availability(driver_id, shift, contract_date):
    # Check if the driver is already allocated to a contract at this time
    conflicting_allocation = DriverAllocation.query.filter_by(
        driver_id=driver_id,
        driver_shift=shift,
        contract_date=contract_date
    ).first()
    
    if conflicting_allocation:
        return False  # Driver is already assigned to another contract
    else:
        return True  # Driver is available
def suggest_best_drivers(contract_id, shift, date):
    contract = Contract.query.get(contract_id)
    if not contract:
        return []

    suggested_drivers = []
    for driver in Driver.query.all():
        if check_driver_availability(driver.id, shift, date):
            # Calculate distance between driver and contract
            driver_location = driver.location  # Assuming this is stored in the driver's model
            distance = get_distance_between_postcodes(driver_location, contract.pickup_postcode)
            
            if distance is not None and distance <= 50:  # e.g., 50 miles radius
                suggested_drivers.append({
                    'driver_id': driver.id,
                    'driver_name': driver.name,
                    'distance': distance
                })

    # Sort by distance to suggest the closest driver
    suggested_drivers.sort(key=lambda x: x['distance'])
    return suggested_drivers

