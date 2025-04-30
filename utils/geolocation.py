from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import time

geolocator = Nominatim(user_agent="evans-taxi-app")

def get_coordinates(postcode):
    try:
        location = geolocator.geocode(postcode)
        time.sleep(1)  # To avoid rate limiting
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

    estimated_time_minutes = total_distance_km / 50 * 60  # average 50 km/h
    litres_used = total_distance_km / mpg * 4.546  # convert MPG to litres
    fuel_cost = litres_used * fuel_cost_per_litre

    return round(total_distance_km, 2), round(estimated_time_minutes), round(fuel_cost, 2)
