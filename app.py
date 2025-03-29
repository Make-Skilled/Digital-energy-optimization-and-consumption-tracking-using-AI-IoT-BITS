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
SMTP_USERNAME = "kr4785543@gmail.com"  # Replace with your email address (https://support.google.com/accounts/answer/185833?hl=en)
SMTP_PASSWORD = "qhuzwfrdagfyqemk"     # Replace with your app password (https://support.google.com/accounts/answer/185833?hl=en)
ALERT_EMAIL = "sudheerthadikonda0605@gmail.com"  # Replace with owner's email address

# Constants
COST_PER_KWH = 7  # Rs. 7 per kWh
INITIAL_BALANCE = 100000  # Initial balance for new users

def send_bill_alert(bill_details):
    """Send email alert for unpaid bill"""
    try:
        print("Preparing to send bill alert email...")  # Debug print
        
        subject = "⚠️ Electricity Bill Payment Due"
        
        body = f"""
        Dear Customer,

        This is a reminder about your electricity bill for {bill_details['month']}.

        Bill Details:
        - Total Consumption: {bill_details['total_kwh']:.2f} kWh
        - Amount Due: Rs. {bill_details['total_cost']:.2f}

        Please make the payment at your earliest convenience.

        Best regards,
        Smart Meter System
        """

        msg = MIMEMultipart()
        msg['From'] = SMTP_USERNAME
        msg['To'] = ALERT_EMAIL
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        print(f"Connecting to SMTP server: {SMTP_SERVER}:{SMTP_PORT}")  # Debug print
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        
        print("Starting TLS...")  # Debug print
        server.starttls()
        
        print(f"Logging in with username: {SMTP_USERNAME}")  # Debug print
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        
        print("Sending email...")  # Debug print
        server.send_message(msg)
        
        print("Closing SMTP connection...")  # Debug print
        server.quit()
        
        print(f"Bill alert email sent successfully to {ALERT_EMAIL}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        print(f"SMTP Authentication failed: {str(e)}")
        print("Please check your email and app password")
        return False
    except smtplib.SMTPException as e:
        print(f"SMTP error occurred: {str(e)}")
        return False
    except Exception as e:
        print(f"Unexpected error while sending email: {str(e)}")
        return False

def check_unpaid_bills():
    """Check for unpaid bills and send alerts"""
    try:
        current_date = datetime.now()
        start_date = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Get current month's consumption
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
        
        print("Checking for unpaid bills...")  # Debug print
        
        result = list(power_logs.aggregate(pipeline))
        if result:
            total_cost = result[0]['total_cost']
            total_kwh = result[0]['total_kwh']
            
            print(f"Found consumption - Total kWh: {total_kwh}, Cost: Rs. {total_cost}")  # Debug print
            
            # Check if there's a paid bill record for current month
            current_month_paid = bills.find_one({
                'month': start_date.strftime('%B %Y'),
                'paid_at': {'$exists': True}
            })
            
            if current_month_paid:
                print(f"Bill for {start_date.strftime('%B %Y')} already paid")  # Debug print
                return False
            
            if total_cost > 0:
                bill_details = {
                    'month': start_date.strftime('%B %Y'),
                    'total_kwh': total_kwh,
                    'total_cost': total_cost
                }
                
                print(f"Unpaid bill found - Month: {bill_details['month']}, Amount: Rs. {bill_details['total_cost']:.2f}")
                
                email_sent = send_bill_alert(bill_details)
                if email_sent:
                    print("Bill alert email sent successfully")
                    return True
                else:
                    print("Failed to send bill alert email")
                    return False
            else:
                print(f"Bill amount is zero. Total cost: Rs. {total_cost:.2f}")
        else:
            print("No consumption data found for current month")
            
        return False
        
    except Exception as e:
        print(f"Error in check_unpaid_bills: {str(e)}")
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

def send_current_bill_email():
    """Send current month's bill details via email"""
    try:
        current_bill = get_current_bill()
        if not current_bill:
            print("No current bill available to send")
            return False
            
        print("Preparing to send current bill email...")
        
        subject = "📊 Your Current Electricity Bill Statement"
        
        body = f"""
        Dear Customer,

        Here is your electricity bill statement for {current_bill['month']}.

        Bill Details:
        - Total Consumption: {current_bill['total_kwh']:.2f} kWh
        - Current Amount: Rs. {current_bill['total_cost']:.2f}

        This is an automated bill statement for your reference.

        Best regards,
        Smart Meter System
        """

        msg = MIMEMultipart()
        msg['From'] = SMTP_USERNAME
        msg['To'] = ALERT_EMAIL
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        print(f"Connecting to SMTP server: {SMTP_SERVER}:{SMTP_PORT}")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        
        print("Sending current bill email...")
        server.send_message(msg)
        server.quit()
        
        print(f"Current bill email sent successfully to {ALERT_EMAIL}")
        return True
        
    except Exception as e:
        print(f"Error sending current bill email: {str(e)}")
        return False

@app.route('/send_current_bill')
def send_current_bill():
    """Endpoint to send current bill via email"""
    success = send_current_bill_email()
    return jsonify({
        'success': success,
        'message': 'Current bill email sent successfully' if success else 'Failed to send current bill email'
    })

@app.route('/')
def dashboard():
    # Check for unpaid bills and send alert
    alert_sent = check_unpaid_bills()
    
    # Send current bill email
    current_bill_sent = send_current_bill_email()
    
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
                         alert_sent=alert_sent,
                         current_bill_sent=current_bill_sent,
                         config={'ALERT_EMAIL': ALERT_EMAIL})

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

@app.route('/check_bill_status')
def check_bill_status():
    """Debug endpoint to check current bill status"""
    try:
        current_date = datetime.now()
        start_date = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Get current consumption
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
        
        # Check if bill is paid
        current_month_paid = bills.find_one({
            'month': start_date.strftime('%B %Y'),
            'paid_at': {'$exists': True}
        })
        
        status = {
            'current_month': start_date.strftime('%B %Y'),
            'has_consumption_data': bool(result),
            'total_kwh': result[0]['total_kwh'] if result else 0,
            'total_cost': result[0]['total_cost'] if result else 0,
            'is_paid': bool(current_month_paid),
            'last_payment_date': current_month_paid['paid_at'].strftime('%Y-%m-%d %H:%M:%S') if current_month_paid else None
        }
        
        return jsonify(status)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/force_bill_alert')
def force_bill_alert():
    """Debug endpoint to force send a bill alert"""
    current_bill = get_current_bill()
    if current_bill:
        email_sent = send_bill_alert(current_bill)
        return jsonify({
            'success': email_sent,
            'bill_details': current_bill
        })
    return jsonify({
        'success': False,
        'error': 'No current bill found'
    })

if __name__ == '__main__':
    app.run(debug=True)
