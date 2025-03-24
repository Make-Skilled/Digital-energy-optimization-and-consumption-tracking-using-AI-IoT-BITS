from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta
import requests
import json
from pymongo import MongoClient
from bson import ObjectId
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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
THINGSPEAK_WRITE_API_KEY = "D4DB9ZE264CRSE9P"
BASE_URL = f"https://api.thingspeak.com/channels/{THINGSPEAK_CHANNEL_ID}"
BILL_BASE_URL = f"https://api.thingspeak.com/channels/{THINGSPEAK_BILL_CHANNEL_ID}"

# Email configuration
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = "kr4785543@gmail.com"  # Replace with your email
SMTP_PASSWORD = "qhuzwfrdagfyqemk"     # Replace with your app password
ALERT_EMAIL = "sudheerthadikonda0605@gmail.com"  # Replace with owner's email

# Constants
COST_PER_KWH = 7  # Rs. 7 per kWh
INITIAL_BALANCE = 100000  # Initial balance for new users

def send_bill_alert(bill_details):
    """Send email alert for unpaid bill"""
    subject = "⚠️ Electricity Bill Payment Overdue"
    
    body = f"""
    Dear Customer,

    Your electricity bill for {bill_details['month']} is overdue.

    Bill Details:
    - Total Consumption: {bill_details['total_kwh']:.2f} kWh
    - Amount Due: Rs. {bill_details['total_cost']:.2f}

    Please make the payment as soon as possible to avoid service interruption.

    Best regards,
    Smart Meter System
    """

    msg = MIMEMultipart()
    msg['From'] = SMTP_USERNAME
    msg['To'] = ALERT_EMAIL
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Bill alert email sent successfully to {ALERT_EMAIL}")
    except Exception as e:
        print(f"Failed to send email alert: {str(e)}")

def check_unpaid_bills():
    """Check for unpaid bills and send alerts with 1-minute cooldown"""
    current_date = datetime.now()
    start_date = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Check when the last alert was sent
    last_alert = bills.find_one(
        {'alert_sent_at': {'$exists': True}},
        sort=[('alert_sent_at', -1)]
    )
    
    # If an alert was sent in the last minute, don't send another
    if last_alert and (current_date - last_alert['alert_sent_at']).total_seconds() < 60:  # 60 seconds = 1 minute
        return False
    
    # Get current month's bill
    pipeline = [
        {
            '$match': {
                'timestamp': {
                    '$gte': start_date,
                    '$lt': current_date
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
        # Check if there's a paid bill record for current month
        current_month_paid = bills.find_one({
            'month': start_date.strftime('%B %Y'),
            'paid_at': {'$exists': True}
        })
        
        if not current_month_paid:
            # Bill is unpaid, send alert
            bill_details = {
                'month': start_date.strftime('%B %Y'),
                'total_kwh': result[0]['total_kwh'],
                'total_cost': result[0]['total_cost']
            }
            send_bill_alert(bill_details)
            
            # Record that an alert was sent
            bills.insert_one({
                'alert_sent_at': current_date,
                'month': start_date.strftime('%B %Y'),
                'total_kwh': result[0]['total_kwh'],
                'total_cost': result[0]['total_cost'],
                'alert_type': 'unpaid_bill'
            })
            
            print(f"Bill alert sent for {bill_details['month']}")
            return True
    return False

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
        'total_kwh': []
    }
    
    # Get data for last 6 months
    for i in range(6):
        end_date = current_date - timedelta(days=30 * i)
        start_date = end_date - timedelta(days=30)
        monthly_data['months'].insert(0, end_date.strftime('%B %Y'))
        
        # Get monthly bill data from MongoDB
        pipeline = [
            {
                '$match': {
                    'timestamp': {
                        '$gte': start_date,
                        '$lt': end_date
                    }
                }
            },
            {
                '$group': {
                    '_id': None,
                    'avg_sensor1': {'$avg': '$sensor_values.sensor1'},
                    'avg_sensor2': {'$avg': '$sensor_values.sensor2'},
                    'avg_sensor3': {'$avg': '$sensor_values.sensor3'},
                    'avg_sensor4': {'$avg': '$sensor_values.sensor4'},
                    'total_kwh': {'$sum': '$total_kwh'}
                }
            }
        ]
        
        result = list(power_logs.aggregate(pipeline))
        if result:
            monthly_data['sensor1_avg'].insert(0, round(result[0].get('avg_sensor1', 0), 2))
            monthly_data['sensor2_avg'].insert(0, round(result[0].get('avg_sensor2', 0), 2))
            monthly_data['sensor3_avg'].insert(0, round(result[0].get('avg_sensor3', 0), 2))
            monthly_data['sensor4_avg'].insert(0, round(result[0].get('avg_sensor4', 0), 2))
            monthly_data['total_kwh'].insert(0, round(result[0].get('total_kwh', 0), 2))
        else:
            monthly_data['sensor1_avg'].insert(0, 0)
            monthly_data['sensor2_avg'].insert(0, 0)
            monthly_data['sensor3_avg'].insert(0, 0)
            monthly_data['sensor4_avg'].insert(0, 0)
            monthly_data['total_kwh'].insert(0, 0)
    
    return monthly_data

@app.route('/')
def dashboard():
    # Only check for unpaid bills every minute
    alert_sent = False
    last_alert = bills.find_one(
        {'alert_type': 'unpaid_bill'},
        sort=[('alert_sent_at', -1)]
    )
    
    if not last_alert or (datetime.now() - last_alert['alert_sent_at']).total_seconds() >= 60:
        alert_sent = check_unpaid_bills()
    
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
                         payment_message=payment_message,
                         alert_sent=alert_sent)  # Add this line to pass alert_sent to the template

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
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
