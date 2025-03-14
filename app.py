from flask import Flask, render_template
from datetime import datetime, timedelta
import requests
import json

app = Flask(__name__)

# ThingSpeak configuration
THINGSPEAK_CHANNEL_ID = "2571433"
THINGSPEAK_READ_API_KEY = "U3XKH2HUOUUU7VA9"
BASE_URL = f"https://api.thingspeak.com/channels/{THINGSPEAK_CHANNEL_ID}"

def get_thingspeak_data():
    """Fetch latest sensor values from ThingSpeak"""
    endpoint = f"{BASE_URL}/feeds/last.json"
    params = {'api_key': THINGSPEAK_READ_API_KEY}
    
    try:
        response = requests.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()
        
        def safe_float(value):
            """Safely convert value to float, return 0 if invalid"""
            try:
                if value is None:
                    return 0.0
                return float(value)
            except (ValueError, TypeError):
                return 0.0
        
        # Get ampere values from fields 1, 2, 4, 5
        sensor_values = {
            'sensor1': safe_float(data.get('field1')),  # Amperes
            'sensor2': safe_float(data.get('field2')),  # Amperes
            'sensor3': safe_float(data.get('field4')),  # Amperes
            'sensor4': safe_float(data.get('field5'))   # Amperes
        }
        
        # Get kWh values from fields 3 and 6
        kwh1 = safe_float(data.get('field3'))
        kwh2 = safe_float(data.get('field6'))
        total_kwh = kwh1 + kwh2
        
        return sensor_values, round(total_kwh, 2)
        
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"Error fetching current data: {e}")
        return {'sensor1': 0, 'sensor2': 0, 'sensor3': 0, 'sensor4': 0}, 0

def get_monthly_data():
    """Fetch and calculate monthly averages from ThingSpeak"""
    current_date = datetime.now()
    
    monthly_data = {
        'months': [],
        'sensor1_avg': [],
        'sensor2_avg': [],
        'sensor3_avg': [],
        'sensor4_avg': [],
        'total_avg': []
    }
    
    def safe_float(value):
        """Safely convert value to float, return 0 if invalid"""
        try:
            if value is None:
                return 0.0
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    
    # Get data for last 6 months
    for i in range(6):
        end_date = current_date - timedelta(days=30 * i)
        start_date = end_date - timedelta(days=30)
        
        monthly_data['months'].insert(0, end_date.strftime('%B %Y'))
        
        endpoint = f"{BASE_URL}/feeds.json"
        params = {
            'api_key': THINGSPEAK_READ_API_KEY,
            'start': start_date.strftime('%Y-%m-%d'),
            'end': end_date.strftime('%Y-%m-%d'),
            'round': 2
        }
        
        try:
            response = requests.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()
            feeds = data.get('feeds', [])
            
            if feeds:
                # Get ampere values from fields 1, 2, 4, 5
                sensor1_values = [safe_float(feed.get('field1')) for feed in feeds]
                sensor2_values = [safe_float(feed.get('field2')) for feed in feeds]
                sensor3_values = [safe_float(feed.get('field4')) for feed in feeds]
                sensor4_values = [safe_float(feed.get('field5')) for feed in feeds]
                
                # Get kWh values from fields 3 and 6
                kwh_values = [(safe_float(feed.get('field3')) + safe_float(feed.get('field6'))) 
                            for feed in feeds]
                
                # Calculate and store averages, avoiding division by zero
                def safe_average(values):
                    return round(sum(values) / len(values), 2) if values else 0
                
                monthly_data['sensor1_avg'].insert(0, safe_average(sensor1_values))
                monthly_data['sensor2_avg'].insert(0, safe_average(sensor2_values))
                monthly_data['sensor3_avg'].insert(0, safe_average(sensor3_values))
                monthly_data['sensor4_avg'].insert(0, safe_average(sensor4_values))
                monthly_data['total_avg'].insert(0, safe_average(kwh_values))
            else:
                # Insert zeros if no data available
                monthly_data['sensor1_avg'].insert(0, 0)
                monthly_data['sensor2_avg'].insert(0, 0)
                monthly_data['sensor3_avg'].insert(0, 0)
                monthly_data['sensor4_avg'].insert(0, 0)
                monthly_data['total_avg'].insert(0, 0)
                
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"Error fetching monthly data: {e}")
            # Insert zeros on error
            monthly_data['sensor1_avg'].insert(0, 0)
            monthly_data['sensor2_avg'].insert(0, 0)
            monthly_data['sensor3_avg'].insert(0, 0)
            monthly_data['sensor4_avg'].insert(0, 0)
            monthly_data['total_avg'].insert(0, 0)
    
    return monthly_data

@app.route('/')
def dashboard():
    sensor_values, total = get_thingspeak_data()
    monthly_data = get_monthly_data()
    return render_template('dashboard.html', 
                         sensor_values=sensor_values, 
                         total=total,
                         monthly_data=monthly_data)

if __name__ == '__main__':
    app.run(debug=True)