from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta
import requests
import json
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)

# MongoDB configuration
client = MongoClient('mongodb://localhost:27017/')
db = client['smart_meter_db']
power_logs = db['power_logs']
bills = db['bills']
users = db['users']

# ThingSpeak configuration
THINGSPEAK_CHANNEL_ID = "2571433"
THINGSPEAK_READ_API_KEY = "U3XKH2HUOUUU7VA9"
THINGSPEAK_BILL_CHANNEL_ID = "2463572"
THINGSPEAK_WRITE_API_KEY = "YOUR_THINGSPEAK_WRITE_API_KEY"
BASE_URL = f"https://api.thingspeak.com/channels/{THINGSPEAK_CHANNEL_ID}"
BILL_BASE_URL = f"https://api.thingspeak.com/channels/{THINGSPEAK_BILL_CHANNEL_ID}"

# Constants
COST_PER_KWH = 7  # Rs. 7 per kWh
INITIAL_BALANCE = 100000  # Initial balance for new users

def get_card_scan_status():
    """Check if card was scanned from ThingSpeak billing channel"""
    endpoint = f"{BILL_BASE_URL}/feeds/last.json"
    params = {'api_key': THINGSPEAK_READ_API_KEY}
    
    try:
        response = requests.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()
        return bool(int(data.get('field1', 0)))
    except:
        return False

def store_power_log(sensor_values, total_kwh):
    """Store power consumption log in MongoDB"""
    log = {
        'timestamp': datetime.now(),
        'sensor_values': sensor_values,
        'total_kwh': total_kwh,
        'cost': total_kwh * COST_PER_KWH
    }
    power_logs.insert_one(log)

def get_current_bill():
    """Get current month's bill from power logs"""
    start_date = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_date = datetime.now()
    
    pipeline = [
        {
            '$match': {
                'timestamp': {
                    '$gte': start_date,
                    '$lte': end_date
                }
            }
        },
        {
            '$group': {
                '_id': None,
                'total_kwh': {'$sum': '$total_kwh'},
                'total_cost': {'$sum': '$cost'}
            }
        }
    ]
    
    result = list(power_logs.aggregate(pipeline))
    if result:
        return {
            'month': start_date.strftime('%B %Y'),
            'total_kwh': result[0]['total_kwh'],
            'total_cost': result[0]['total_cost']
        }
    return None

def initialize_user():
    """Initialize user with default balance if not exists"""
    user = users.find_one({})  # Get the single user
    if not user:
        user = {
            'balance': INITIAL_BALANCE,
            'last_payment': datetime.now()
        }
        users.insert_one(user)
    return user

def process_payment():
    """Process payment when card is scanned"""
    user = users.find_one({})
    if not user:
        user = initialize_user()
    
    current_bill = get_current_bill()
    if not current_bill:
        return False, "No bill available"
    
    if user['balance'] >= current_bill['total_cost']:
        new_balance = user['balance'] - current_bill['total_cost']
        
        # Update user balance
        users.update_one(
            {'_id': user['_id']},
            {'$set': {
                'balance': new_balance,
                'last_payment': datetime.now()
            }}
        )
        
        # Store paid bill
        bill_data = {
            **current_bill,
            'paid_at': datetime.now(),
            'previous_balance': user['balance'],
            'new_balance': new_balance
        }
        bills.insert_one(bill_data)
        
        # Clear power logs after successful payment
        power_logs.delete_many({
            'timestamp': {
                '$gte': datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                '$lte': datetime.now()
            }
        })
        
        return True, f"Payment successful! New balance: Rs. {new_balance:.2f}"
    
    return False, f"Insufficient balance. Required: Rs. {current_bill['total_cost']:.2f}, Available: Rs. {user['balance']:.2f}"

@app.route('/get_balance')
def get_balance():
    user = users.find_one({'user_id': 'default_user'})
    return jsonify({
        'balance': user['balance'] if user else INITIAL_BALANCE,
        'last_updated': user['last_payment'].strftime('%Y-%m-%d %H:%M:%S') if user else None
    })

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
        kwh1 = safe_float(data.get('field3'))  # kWh from first Arduino
        kwh2 = safe_float(data.get('field6'))  # kWh from second Arduino
        total_kwh = kwh1 + kwh2  # Total kWh consumption
        
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
        'total_kwh': []  # Changed from total_avg to total_kwh for clarity
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
                
                # Get kWh values from fields 3 and 6 and sum them
                total_kwh = sum([
                    safe_float(feed.get('field3', 0)) + safe_float(feed.get('field6', 0))
                    for feed in feeds
                ])
                
                # Calculate and store averages, avoiding division by zero
                def safe_average(values):
                    return round(sum(values) / len(values), 2) if values else 0
                
                monthly_data['sensor1_avg'].insert(0, safe_average(sensor1_values))
                monthly_data['sensor2_avg'].insert(0, safe_average(sensor2_values))
                monthly_data['sensor3_avg'].insert(0, safe_average(sensor3_values))
                monthly_data['sensor4_avg'].insert(0, safe_average(sensor4_values))
                monthly_data['total_kwh'].insert(0, round(total_kwh, 2))
            else:
                # Insert zeros if no data available
                monthly_data['sensor1_avg'].insert(0, 0)
                monthly_data['sensor2_avg'].insert(0, 0)
                monthly_data['sensor3_avg'].insert(0, 0)
                monthly_data['sensor4_avg'].insert(0, 0)
                monthly_data['total_kwh'].insert(0, 0)
                
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"Error fetching monthly data: {e}")
            # Insert zeros on error
            monthly_data['sensor1_avg'].insert(0, 0)
            monthly_data['sensor2_avg'].insert(0, 0)
            monthly_data['sensor3_avg'].insert(0, 0)
            monthly_data['sensor4_avg'].insert(0, 0)
            monthly_data['total_kwh'].insert(0, 0)
    
    return monthly_data

@app.route('/')
def dashboard():
    # Get current sensor values and total consumption
    sensor_values, total = get_thingspeak_data()
    monthly_data = get_monthly_data()
    
    # Store power log
    store_power_log(sensor_values, total)
    
    # Initialize user if not exists
    user = initialize_user()
    
    # Check for card scan and process payment
    payment_message = None
    if get_card_scan_status():
        success, message = process_payment()
        payment_message = message
    
    # Get current bill
    current_bill = get_current_bill()
    
    return render_template('dashboard.html',
                         sensor_values=sensor_values,
                         total=total,
                         monthly_data=monthly_data,
                         balance=user['balance'],
                         current_bill=current_bill,
                         payment_message=payment_message)

@app.route('/add_balance', methods=['POST'])
def add_balance():
    try:
        data = request.get_json()
        if not data or 'amount' not in data:
            return jsonify({'success': False, 'message': 'Amount is required'}), 400
            
        amount = float(data['amount'])
        if amount <= 0:
            return jsonify({'success': False, 'message': 'Amount must be positive'}), 400
        
        user = users.find_one({})
        if not user:
            user = initialize_user()
        
        new_balance = user['balance'] + amount
        users.update_one(
            {'_id': user['_id']},
            {'$set': {'balance': new_balance}}
        )
        
        return jsonify({
            'success': True,
            'message': f'Balance updated successfully',
            'new_balance': new_balance
        })
    except Exception as e:
        print(f"Error in add_balance: {str(e)}")  # Add this for debugging
        return jsonify({'success': False, 'message': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True)