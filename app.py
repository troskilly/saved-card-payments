from flask import Flask, request, render_template, redirect, flash, jsonify
import securetrading
import json
import logging
from datetime import datetime
import os
import re
from math import ceil

app = Flask(__name__)

# Use environment variable for secret key, with fallback
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-change-this')

# SecureTrading (TRUST) configuration from environment variables
ST_USERNAME = os.getenv('ST_USERNAME')
ST_PASSWORD = os.getenv('ST_PASSWORD')

# Validate that required environment variables are set
if not ST_USERNAME or not ST_PASSWORD:
    raise ValueError("ST_USERNAME and ST_PASSWORD environment variables must be set in .env")

def get_securetrading_client():
    """Initialize and return Trust client"""
    stconfig = securetrading.Config()
    stconfig.username = ST_USERNAME
    stconfig.password = ST_PASSWORD
    return securetrading.Api(stconfig)

# Configure logging
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Create a custom formatter with milliseconds
class CustomFormatter(logging.Formatter):
    def format(self, record):
        # Include milliseconds in timestamp
        record.timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # Remove last 3 digits to get milliseconds
        return super().format(record)

# Setup file handler
file_handler = logging.FileHandler(f'{log_dir}/payment_app.log')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(CustomFormatter(
    '%(timestamp)s - %(levelname)s - %(message)s'
))

# Setup console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(CustomFormatter(
    '%(timestamp)s - %(levelname)s - %(message)s'
))

# Configure app logger
app.logger.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.addHandler(console_handler)

# Remove default Flask handler to avoid duplicate logs
app.logger.handlers = [file_handler, console_handler]

# Log startup information (without exposing sensitive data)
app.logger.info(f"Application starting with ST_USERNAME: {ST_USERNAME[:5]}***")
app.logger.info(f"Flask environment: {os.getenv('FLASK_ENV', 'development')}")

@app.template_filter('add_commas')
def add_commas(value):
    """Add comma separators to numbers with 2 decimal places"""
    try:
        # Handle both string and numeric inputs
        if isinstance(value, str):
            clean_value = value.replace(',', '')
            float_value = float(clean_value)
            formatted_value = "{:,.2f}".format(float_value)
            
            # Debug logging
            app.logger.info(f"add_commas filter - Input: '{value}', Clean: '{clean_value}', Float: {float_value}, Formatted: '{formatted_value}'")
            
            return formatted_value
        else:
            float_value = float(value)
            formatted_value = "{:,.2f}".format(float_value)
            
            # Debug logging
            app.logger.info(f"add_commas filter - Input: {value}, Float: {float_value}, Formatted: '{formatted_value}'")
            
            return formatted_value
    except (ValueError, TypeError) as e:
        # If conversion fails, return original value
        app.logger.error(f"add_commas filter error - Input: {value}, Error: {e}")
        return value

@app.before_request
def log_request_info():
    """Log all incoming requests (except logs page to avoid recursive logging)"""
    # Skip logging for the logs page to prevent recursive logging
    if request.endpoint in ['logs', 'logs_api']:
        return
        
    client_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    user_agent = request.headers.get('User-Agent', 'Unknown')
    
    log_data = {
        'event': 'REQUEST',
        'timestamp': datetime.now().isoformat(),
        'client_ip': client_ip,
        'method': request.method,
        'url': request.url,
        'endpoint': request.endpoint,
        'user_agent': user_agent,
        'query_params': dict(request.args),
        'form_data': dict(request.form) if request.form else None,
        'content_length': request.content_length
    }
    
    app.logger.info(f"INCOMING_REQUEST: {json.dumps(log_data, indent=2)}")

@app.after_request
def log_response_info(response):
    """Log all outgoing responses (except logs page to avoid recursive logging)"""
    # Skip logging for the logs page to prevent recursive logging
    if request.endpoint in ['logs', 'logs_api']:
        return response
        
    log_data = {
        'event': 'RESPONSE',
        'timestamp': datetime.now().isoformat(),
        'status_code': response.status_code,
        'content_length': response.content_length,
        'mimetype': response.mimetype
    }
    
    app.logger.info(f"OUTGOING_RESPONSE: {json.dumps(log_data, indent=2)}")
    return response

@app.route('/')
def index():
    return redirect('/logs')

@app.route('/payment')
def payment():
    # Get all query parameters
    query_params = request.args.to_dict()
    
    if not query_params:
        return "No payment data provided", 400
    
    return render_template('payment.html', data=query_params, debug=app.debug)

@app.route('/process_payment', methods=['POST'])
def process_payment():
    try:
        # Get the form data (which should match the original query params)
        form_data = request.form.to_dict()
        
        # Initialize Trust client
        st_client = get_securetrading_client()
        
        # Prepare the request payload - map form fields to Trust expected fields
        request_data = {
            "requesttypedescriptions": request.form.getlist('requesttype'),
            "baseamount": str(int(float(form_data.get('baseamount', 0)) * 100)),
            "customerfirstname": form_data.get('darwinpaymentid')
        }
        
        # Add any additional form fields that weren't explicitly mapped
        for field_name, field_value in form_data.items():
            if field_name not in request_data and field_value:
                # Handle multi-value fields (like checkboxes or multiple selects)
                if field_name in request.form and len(request.form.getlist(field_name)) > 1:
                    request_data[field_name] = request.form.getlist(field_name)
                else:
                    request_data[field_name] = field_value
                
                app.logger.debug(f"Including additional field: {field_name} = {field_value}")
        
        # Remove any None values to clean up the payload
        request_data = {k: v for k, v in request_data.items() if v is not None and v != ''}
        
        # Create Trust request
        strequest = securetrading.Request()
        strequest.update(request_data)
        
        app.logger.debug(f"Preparing Payment Request with data: {json.dumps(request_data, indent=2)}")
        
        # Process the payment
        stresponse = st_client.process(strequest)
        
        app.logger.info(f"Payment Request Response: {json.dumps(stresponse, indent=2)}")
        
        # Convert response to dictionary for easier handling
        response_dict = dict(stresponse)
        
        # Log the API response details
        api_response_log = {
            'event': 'TRUST_PAYMENT_RESPONSE',
            'timestamp': datetime.now().isoformat(),
            'request_data': request_data,
            'response_data': response_dict
        }
        
        app.logger.info(f"TRUST_PAYMENT_RESPONSE: {json.dumps(api_response_log, indent=2)}")
        
        # Check if the payment was successful
        # Trust typically returns errorcode "0" for success
        responses = response_dict.get('responses', [])
        error_code = responses[0].get('errorcode', '1')
        error_message = responses[0].get('errormessage', 'Unknown error')

        if error_code == '0' or error_code == 0:
            flash('Payment processed successfully!', 'success')
            app.logger.info("Payment processed successfully")
            return render_template('payment_result.html', 
                                 success=True, 
                                 response_data=response_dict,
                                 debug=app.debug)
        else:
            error_msg = f'Payment failed: {error_message}'
            flash(error_msg, 'error')
            app.logger.error(f"Payment failed with error code {error_code}: {error_message}")
            return render_template('payment_result.html', 
                                 success=False, 
                                 error=error_msg,
                                 response_data=response_dict,
                                 debug=app.debug)
            
    except Exception as e:
        error_msg = f'Payment processing error: {str(e)}'
        flash(error_msg, 'error')
        app.logger.error(f"PAYMENT_PROCESSING_ERROR: {error_msg}")
        app.logger.error(f"Exception details: {type(e).__name__}: {str(e)}")
        return render_template('payment_result.html', 
                             success=False, 
                             error=str(e))

def parse_log_file():
    """Parse the log file and return structured log entries"""
    log_file_path = os.path.join('logs', 'payment_app.log')
    
    if not os.path.exists(log_file_path):
        return []
    
    logs = []
    try:
        with open(log_file_path, 'r') as f:
            content = f.read()
            
        # Updated pattern to include milliseconds
        log_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) - (\w+) - (.*?)(?=\n\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}|$)'
        matches = re.findall(log_pattern, content, re.DOTALL)
        
        # Also handle old format logs without milliseconds for backward compatibility
        old_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - (\w+) - (.*?)(?=\n\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}|$)'
        old_matches = re.findall(old_pattern, content, re.DOTALL)
        
        # Process new format logs
        for match in matches:
            timestamp_str, level, message = match
            
            # Try to parse JSON content
            json_content = None
            if message.startswith(('INCOMING_REQUEST:', 'OUTGOING_RESPONSE:', 'SECURETRADING_RESPONSE:')):
                try:
                    json_part = message.split(':', 1)[1].strip()
                    json_content = json.loads(json_part)
                except (json.JSONDecodeError, IndexError):
                    pass
            
            log_entry = {
                'timestamp': timestamp_str,
                'level': level,
                'message': message.strip(),
                'json_content': json_content,
                'event_type': message.split(':')[0] if ':' in message else 'GENERAL',
                'sort_key': datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
            }
            logs.append(log_entry)
        
        # Process old format logs (for backward compatibility)
        for match in old_matches:
            timestamp_str, level, message = match
            
            # Skip if this timestamp already exists in new format
            if any(log['timestamp'].startswith(timestamp_str) for log in logs):
                continue
            
            # Try to parse JSON content
            json_content = None
            if message.startswith(('INCOMING_REQUEST:', 'OUTGOING_RESPONSE:', 'SECURETRADING_RESPONSE:')):
                try:
                    json_part = message.split(':', 1)[1].strip()
                    json_content = json.loads(json_part)
                except (json.JSONDecodeError, IndexError):
                    pass
            
            log_entry = {
                'timestamp': timestamp_str,
                'level': level,
                'message': message.strip(),
                'json_content': json_content,
                'event_type': message.split(':')[0] if ':' in message else 'GENERAL',
                'sort_key': datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            }
            logs.append(log_entry)
            
    except Exception as e:
        app.logger.error(f"Error parsing log file: {str(e)}")
    
    # Return logs sorted by timestamp (newest first) using the sort_key
    return sorted(logs, key=lambda x: x['sort_key'], reverse=True)

@app.route('/logs')
def logs():
    """Display logs page"""
    debug_enabled = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes', 'on')
    if debug_enabled:
        return render_template('logs.html')
    else:
        return "Logs are not accessible except in debug mode", 403

@app.route('/api/logs')
def logs_api():
    """API endpoint for fetching filtered logs"""
    debug_enabled = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes', 'on')
    if debug_enabled:
        # Get filter parameters
        search_term = request.args.get('search', '').strip()
        log_level = request.args.get('level', 'all')
        event_type = request.args.get('event_type', 'all')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        
        # Parse all logs
        all_logs = parse_log_file()
        
        # Apply filters
        filtered_logs = []
        for log in all_logs:
            # Level filter
            if log_level != 'all' and log['level'].lower() != log_level.lower():
                continue
                
            # Event type filter
            if event_type != 'all' and log['event_type'] != event_type:
                continue
                
            # Search filter
            if search_term:
                search_in = f"{log['message']} {log['timestamp']}".lower()
                if log['json_content']:
                    search_in += f" {json.dumps(log['json_content']).lower()}"
                if search_term.lower() not in search_in:
                    continue
            
            # Remove sort_key before sending to frontend
            log_copy = {k: v for k, v in log.items() if k != 'sort_key'}
            filtered_logs.append(log_copy)
        
        # Pagination
        total_logs = len(filtered_logs)
        total_pages = ceil(total_logs / per_page)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_logs = filtered_logs[start_idx:end_idx]
        
        return jsonify({
            'logs': paginated_logs,
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'total_logs': total_logs,
                'per_page': per_page,
                'has_prev': page > 1,
                'has_next': page < total_pages
            }
        })
        
    else:
        return "Logs are not accessible except in debug mode"
        
@app.route('/test_success')
def test_success():
    """Render the success result page with mock data — debug mode only"""
    debug_enabled = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes', 'on')
    if not debug_enabled:
        return "Test routes are not accessible except in debug mode", 403

    mock_response = {
        "requestreference": "A1B2C3",
        "version": "1.00",
        "responses": [{
            "accounttypedescription": "ECOM",
            "acquirerresponsecode": "00",
            "acquirerresponsemessage": "Approved or completed Successfully",
            "authcode": "12345Z",
            "authmethod": "PRE",
            "baseamount": "12345",
            "chargedescription": "Red Savannah",
            "currencyiso3a": "USD",
            "errorcode": "0",
            "errormessage": "Ok",
            "livestatus": "1",
            "maskedpan": "123456######1234",
            "merchantname": "Red Savannah",
            "merchantcity": "Reading",
            "merchantcountryiso2a": "GB",
            "operatorname": "wsapi_redsavanna_12345",
            "orderreference": "123a456b-12c-4f5g6-8hgs-649b99a3696f",
            "paymenttypedescription": "MASTERCARD",
            "requesttypedescription": "AUTH",
            "settleduedate": "2026-03-12",
            "settlestatus": "2",
            "transactionreference": "55-70-123456789",
            "transactionstartedtimestamp": "2026-03-12 17:39:42"
        }]
    }
    return render_template('payment_result.html',
                           success=True,
                           response_data=mock_response,
                           debug=debug_enabled)

if __name__ == '__main__':
    DEBUG_MODE = os.getenv('FLASK_DEBUG', 'False').lower() in ('true', '1', 'yes', 'on')
    app.run(host='0.0.0.0', port=5000, debug=DEBUG_MODE)
