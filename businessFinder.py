import requests
import pandas as pd
import math
import argparse
import os
import glob
import time
from dotenv import load_dotenv

# Set up command-line argument parsing
def parse_arguments():
    parser = argparse.ArgumentParser(description="Find businesses with phone numbers but no websites within a ZIP code area.")
    parser.add_argument("--zip_code", type=str, default="98033", help="The ZIP code to search within. Default is 98033.")
    parser.add_argument("--n", type=int, default=10, help="The number of stores to find.")
    parser.add_argument("--minRadius", type=int, default=0, help="Minimum radius to start search from.")
    return parser.parse_args()

# Geocode to get latitude and longitude of the ZIP code area
def get_lat_lng(zip_code, api_key):
    response = requests.get(
        'https://maps.googleapis.com/maps/api/geocode/json',
        params={'address': zip_code, 'key': api_key}
    )
    location_data = response.json()
    if location_data['results']:
        location = location_data['results'][0]['geometry']['location']
        return location['lat'], location['lng']
    else:
        print("Unable to get location for the ZIP code")
        print(location_data)
        return None, None

# Generate grid points within a radius around the central point
def get_grid_points(center_lat, center_lng, radius, num_points=10):
    points = []
    offset = radius / (num_points // 2)
    for i in range(-num_points // 2, num_points // 2 + 1):
        for j in range(-num_points // 2, num_points // 2 + 1):
            lat = center_lat + (i * offset) / 111320
            lng = center_lng + (j * offset) / (111320 * math.cos(center_lat * math.pi / 180))
            points.append((lat, lng))
    return points

# Get businesses for each point in the grid
def get_businesses_grid_search(center_lat, center_lng, radius, api_key):
    businesses = []
    grid_points = get_grid_points(center_lat, center_lng, radius)
    print(f"Searching in {len(grid_points)} grid points within {radius} meters...")
    total_points = len(grid_points)

    for idx, (lat, lng) in enumerate(grid_points):
        next_page_token = None
        if(idx % 10 == 0):
            print(f"Processing point {idx + 1}/{total_points}: (lat: {lat}, lng: {lng})")        
        while True:
            params = {
                'location': f'{lat},{lng}',
                'radius': radius,
                'type': 'store',
                'key': api_key
            }
            if next_page_token:
                params['pagetoken'] = next_page_token

            response = requests.get('https://maps.googleapis.com/maps/api/place/nearbysearch/json', params=params)
            data = response.json()

            for place in data.get('results', []):
                business = {
                    'name': place.get('name'),
                    'place_id': place.get('place_id'),
                    'address': place.get('vicinity'),
                    'types': ', '.join(place.get('types'))
                }
                businesses.append(business)

            next_page_token = data.get('next_page_token')
            if not next_page_token:
                break
        if(idx % 10 == 0):
            print(f"Found {len(businesses)}")
        #time.sleep(1)  # To avoid hitting rate limits
    unique_businesses = {business['place_id']: business for business in businesses}.values()
    print(f"{len(unique_businesses)} Unique businesses")
    return list(unique_businesses)

# Get phone and website details
def get_business_details(place_id, api_key):
    details_url = 'https://maps.googleapis.com/maps/api/place/details/json'
    response = requests.get(details_url, params={'place_id': place_id, 'key': api_key})
    details = response.json().get('result', {})
    
    return {
        'phone': details.get('formatted_phone_number'),
        'website': details.get('website')
    }

# Load previously found businesses to avoid duplicates
def load_previous_results(zip_code, n):
    existing_files = glob.glob(f"{zip_code}.{n}.*.csv")
    previous_stores = set()

    for file in existing_files:
        df = pd.read_csv(file)
        previous_stores.update(df['Name'].tolist())
    
    return previous_stores

unwanted_types = ['point_of_interest', 'establishment']

# Main function to filter businesses
def filter_businesses(businesses, api_key, previous_stores, n):
    results = []
    for i, business in enumerate(businesses, start=1):
        if business['name'] not in previous_stores:
            details = get_business_details(business['place_id'], api_key)
            business_types = business['types'].split(',')  # Assuming types are comma-separated in the string
            filtered_types = [t.strip() for t in business_types if t not in unwanted_types]
            filtered_types_string = ', '.join(filtered_types)
            if details['phone'] and not details['website']:
                results.append({
                    'Name': business['name'],
                    'Address': business['address'],
                    'Phone': details['phone'],
                    'Types':filtered_types_string
                })
            print(f"Processed {i} of {len(businesses)} businesses; found {len(results)} matching criteria.")
            if len(results) >= n:  # Stop once we have at least n results
                break
    return results

# Main script entry point
def main():
    args = parse_arguments()
    
    # Access the secret variable
    load_dotenv()
    API_KEY = os.getenv('API_KEY')

    lat, lng = get_lat_lng(args.zip_code, API_KEY)
    if lat and lng:
        max_radius = args.minRadius
        found_businesses = []
        previous_stores = load_previous_results(args.zip_code, args.n)

        nPreviousStores = len(previous_stores)
        if(nPreviousStores > 0):
            print('Found ', nPreviousStores, 'previous stores')

        # Increment radius until we find the desired number of businesses
        while len(found_businesses) < args.n:
            max_radius += 500  # Increment radius by 500 meters
            print(f"\nExpanding search radius to {max_radius} meters...")

            businesses = get_businesses_grid_search(lat, lng, max_radius, API_KEY)
            print(f"Total businesses found at {max_radius} meters: {len(businesses)}")
            
            # Filter those which has phone but not website
            filtered_businesses = filter_businesses(businesses, API_KEY, previous_stores, args.n - len(found_businesses))
            print(f"Total new businesses matching criteria: {len(filtered_businesses)}")

            # Append until we reach n unique businesses
            for business in filtered_businesses:
                found_businesses.append(business)
                previous_stores.add(business['Name'])
            print(f"Current number of unique businesses collected: {len(found_businesses)}")

        # Save results to CSV
        df = pd.DataFrame(found_businesses)
        file_name = f"{args.zip_code}.{args.n}.{max_radius}.csv"
        df.to_csv(file_name, index=False)
        print(f"\nSaved {len(found_businesses)} stores to {file_name}")

if __name__ == "__main__":
    main()
