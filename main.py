import os
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# Initialize Flask app
app = Flask(__name__)

# Initialize Firebase Admin SDK in the global scope to be reused across requests.
# This prevents timeouts by avoiding re-initialization on every incoming request.
if not firebase_admin.apps:
    try:
        # Use the GOOGLE_APPLICATION_CREDENTIALS environment variable for security
        firebase_admin.initialize_app()
        print("INFO: Firebase Admin SDK initialized successfully.")
    except Exception as e:
        app.logger.error(f"Failed to initialize Firebase: {e}")

db = firestore.client()
print("INFO: Firestore client created and ready.")


@app.route('/', methods=['POST'])
def webhook():
    """
    Dialogflow CX webhook for doctor availability.
    It queries Firestore to find doctors based on specialty, date, and location.
    """
    request_data = request.get_json()
    print(f"INFO: Received webhook request: {request_data}")
    
    session_info = request_data.get('sessionInfo', {})
    parameters = session_info.get('parameters', {})
    tag = request_data.get('fulfillmentInfo', {}).get('tag')
    
    print(f"INFO: Extracted parameters: specialty={parameters.get('specialty')}, location={parameters.get('location', {}).get('city')}, date={parameters.get('date')}")
    
    response_text = "I'm sorry, an error occurred. Please try again."

    if tag == 'search_doctors':
        specialty = parameters.get('specialty')
        location = parameters.get('location', {}).get('city')
        date_param = parameters.get('date') # Get the full date object/string

        # Safely extract the date string from the parameter
        if isinstance(date_param, str):
            date_str = date_param
            print("INFO: Date parameter is a string.")
        elif isinstance(date_param, dict):
            # The log shows the date parameter has keys 'year', 'month', and 'day'
            try:
                year = date_param.get('year')
                month = date_param.get('month')
                day = date_param.get('day')
                # Construct an ISO 8601 formatted date string
                date_str = datetime(year, month, day).isoformat()
                print(f"INFO: Date parameter is a dict, extracted as {date_str}")
            except (KeyError, TypeError):
                # Handle cases where the required keys are missing or invalid
                response_text = "I couldn't understand the date provided. Please try again."
                print("ERROR: Date parameter dict is missing keys or has invalid types.")
                return jsonify({
                    'fulfillmentResponse': {
                        'messages': [{ 'text': { 'text': [response_text] } }]
                    }
                })
        else:
            # Handle cases where the date parameter is in an unexpected format
            response_text = "I couldn't understand the date provided. Please try again."
            print("ERROR: Date parameter is in an unexpected format.")
            return jsonify({
                'fulfillmentResponse': {
                    'messages': [{ 'text': { 'text': [response_text] } }]
                }
            })

        if not specialty or not location or not date_str:
            response_text = "I'm missing some information. Please provide your preferred specialty, location, and date."
            print("INFO: Missing required parameters.")
        else:
            try:
                # Dialogflow sends date as ISO 8601 string (e.g., '2025-09-05T12:00:00Z')
                # We extract the date part and check if it's in the future
                requested_date = datetime.strptime(date_str.split('T')[0], '%Y-%m-%d').date()
                today = datetime.now().date()
                print(f"INFO: Checking for availability on {requested_date.isoformat()}")
                
                # We only show upcoming availability, so check if the date is in the past
                if requested_date < today:
                    response_text = "I can only check for future appointments. Please provide a date that isn't in the past."
                    print("INFO: Requested date is in the past.")
                    return jsonify({
                        'fulfillmentResponse': {
                            'messages': [{ 'text': { 'text': [response_text] } }]
                        }
                    })

                # Reference the 'doctors' collection
                docs_ref = db.collection('doctors')
                
                # Query Firestore for matching specialty and city
                print(f"INFO: Executing Firestore query for specialty='{specialty}' and city='{location}'.")
                docs = docs_ref.where('specialty', '==', specialty).where('city', '==', location).stream()
                
                available_doctors = []
                for doc in docs:
                    doctor_data = doc.to_dict()
                    print(f"INFO: Found doctor: {doctor_data.get('name')}")
                    
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
                            print(f"INFO: Doctor is available on {requested_date.isoformat()}.")
                
                if available_doctors:
                    doctor_list_text = " and ".join([f"{doc['name']} has availability at {doc['times']}" for doc in available_doctors])
                    response_text = f"I found the following doctors: {doctor_list_text}. Please let me know which doctor and time you would like to book."
                    print(f"INFO: Found {len(available_doctors)} available doctor(s).")
                else:
                    response_text = f"I could not find any {specialty} doctors in {location} available on {requested_date.strftime('%B %d, %Y')}. Would you like to check a different date or location?"
                    print("INFO: No available doctors found.")
            
            except Exception as e:
                app.logger.error(f"Firestore query error: {e}")
                response_text = "I am having trouble looking for doctors right now. Please try again later."
    
    # Construct and return the Dialogflow-formatted JSON response
    print(f"INFO: Sending response to Dialogflow: {response_text}")
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
