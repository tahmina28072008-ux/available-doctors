import os
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
from firebase_admin import App
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize Flask app
app = Flask(__name__)

# --- Firestore Connection Setup ---
try:
    # On Cloud Run, credentials are automatically provided by the environment.
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)
    logging.info("Firestore connected using Cloud Run environment credentials.")
except ValueError:
    # If running locally, you'll need a service account JSON file.
    # Set the 'GOOGLE_APPLICATION_CREDENTIALS' environment variable to its file path.
    try:
        cred = credentials.Certificate(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'))
        firebase_admin.initialize_app(cred)
        logging.info("Firestore connected using GOOGLE_APPLICATION_CREDENTIALS.")
    except Exception as e:
        logging.error(f"Error initializing Firebase: {e}")
        # To prevent the app from crashing, we'll continue, but database calls will fail.

db = firestore.client()

# --- Webhook Endpoints ---
@app.route('/')
def home():
    """Returns a simple message to confirm the service is running."""
    return "Webhook is running successfully!"

@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Dialogflow CX webhook for doctor availability.
    It queries Firestore to find doctors based on specialty, date, and location.
    """
    logging.info("--- Webhook Request Received ---")
    request_data = request.get_json()
    logging.info(f"Full Request JSON: {request_data}")
    
    session_info = request_data.get('sessionInfo', {})
    parameters = session_info.get('parameters', {})
    tag = request_data.get('fulfillmentInfo', {}).get('tag')
    
    logging.info(f"Extracted parameters: specialty={parameters.get('specialty')}, location={parameters.get('location', {}).get('city')}, date={parameters.get('date')}")
    
    response_text = "I'm sorry, an error occurred. Please try again."

    if tag == 'search_doctors':
        specialty = parameters.get('specialty')
        location = parameters.get('location', {}).get('city')
        date_param = parameters.get('date') # Get the full date object/string

        # Safely extract the date string from the parameter
        if isinstance(date_param, str):
            date_str = date_param
            logging.info("Date parameter is a string.")
        elif isinstance(date_param, dict):
            try:
                year = int(date_param.get('year'))
                month = int(date_param.get('month'))
                day = int(date_param.get('day'))
                # Construct an ISO 8601 formatted date string
                date_str = datetime(year, month, day).isoformat()
                logging.info(f"Date parameter is a dict, extracted as {date_str}")
            except (KeyError, TypeError, ValueError) as e:
                # Handle cases where the required keys are missing, invalid types, or cannot be converted to int
                response_text = "I couldn't understand the date provided. Please try again."
                logging.error(f"Date parameter dict has an issue: {e}")
                return jsonify({
                    'fulfillmentResponse': {
                        'messages': [{ 'text': { 'text': [response_text] } }]
                    }
                })
        else:
            # Handle cases where the date parameter is in an unexpected format
            response_text = "I couldn't understand the date provided. Please try again."
            logging.error("Date parameter is in an unexpected format.")
            return jsonify({
                'fulfillmentResponse': {
                    'messages': [{ 'text': { 'text': [response_text] } }]
                }
            })

        if not specialty or not location or not date_str:
            response_text = "I'm missing some information. Please provide your preferred specialty, location, and date."
            logging.info("Missing required parameters.")
        else:
            try:
                # Dialogflow sends date as ISO 8601 string (e.g., '2025-09-05T12:00:00Z')
                # We extract the date part and check if it's in the future
                requested_date = datetime.strptime(date_str.split('T')[0], '%Y-%m-%d').date()
                today = datetime.now().date()
                logging.info(f"Checking for availability on {requested_date.isoformat()}")
                
                # We only show upcoming availability, so check if the date is in the past
                if requested_date < today:
                    response_text = "I can only check for future appointments. Please provide a date that isn't in the past."
                    logging.info("Requested date is in the past.")
                    return jsonify({
                        'fulfillmentResponse': {
                            'messages': [{ 'text': { 'text': [response_text] } }]
                        }
                    })

                # Reference the 'doctors' collection
                docs_ref = db.collection('doctors')
                
                # Query Firestore for matching specialty and city
                logging.info(f"Executing Firestore query for specialty='{specialty}' and city='{location}'.")
                docs = docs_ref.where('specialty', '==', specialty).where('city', '==', location).stream()
                
                available_doctors = []
                for doc in docs:
                    doctor_data = doc.to_dict()
                    logging.info(f"Found doctor: {doctor_data.get('name')}")
                    
                    # 'availability' is a map in Firestore, with dates as keys
                    availability_map = doctor_data.get('availability', {})
                    
                    # Check if the requested date exists in the availability map
                    # The date key should be in a format like '2025-09-05'
                    if requested_date.isoformat() in availability_map:
                        available_times = availability_map[requested_date.isoformat()]
                        if available_times:
                            available_doctors.append({
                                'name': doctor_data.get('name'),
                                'times': ", ".join(available_times)
                            })
                            logging.info(f"Doctor is available on {requested_date.isoformat()}.")
                
                if available_doctors:
                    doctor_list_text = " and ".join([f"{doc['name']} has availability at {doc['times']}" for doc in available_doctors])
                    response_text = f"I found the following doctors: {doctor_list_text}. Please let me know which doctor and time you would like to book."
                    logging.info(f"Found {len(available_doctors)} available doctor(s).")
                else:
                    response_text = f"I could not find any {specialty} doctors in {location} available on {requested_date.strftime('%B %d, %Y')}. Would you like to check a different date or location?"
                    logging.info("No available doctors found.")
            
            except Exception as e:
                app.logger.error(f"Firestore query error: {e}")
                response_text = "I am having trouble looking for doctors right now. Please try again later."
    
    # Construct and return the Dialogflow-formatted JSON response
    logging.info(f"Sending response to Dialogflow: {response_text}")
    return jsonify({
        'fulfillmentResponse': {
            'messages': [
                {
                    'text': {
                        'text': [response_text]
                    }
                }
            ]
        }
    })

# --- Application Entry Point ---
if __name__ == '__main__':
    logging.info("Starting application locally...")
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
