import os
import re
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Flask app
app = Flask(__name__)

# Initialize Firebase Admin SDK
# Use your service account credentials file
# Recommended: set the GOOGLE_APPLICATION_CREDENTIALS environment variable
# cred = credentials.Certificate("path/to/your/serviceAccountKey.json")
# firebase_admin.initialize_app(cred)
firebase_admin.initialize_app()
db = firestore.client()

@app.route('/', methods=['POST'])
def webhook():
    """
    Dialogflow CX webhook for doctor availability.
    """
    request_data = request.get_json()
    
    # Extract parameters from the Dialogflow request
    session_info = request_data.get('sessionInfo', {})
    parameters = session_info.get('parameters', {})
    tag = request_data.get('fulfillmentInfo', {}).get('tag')
    
    response_text = "I'm sorry, an error occurred. Please try again."

    if tag == 'search_doctors':
        location = parameters.get('location')
        specialty = parameters.get('specialty')
        date_str = parameters.get('date')

        if not location or not specialty or not date_str:
            response_text = "I'm missing some information. Please provide your preferred location, specialty, and date."
        else:
            try:
                # Convert the date string from Dialogflow (e.g., '2025-09-05T12:00:00Z')
                # to a Firestore-compatible date format for filtering
                # This example uses a simple date string comparison
                date_iso = date_str.split('T')[0]
                
                # Assume specialty is an actual field in your document
                # This needs to be configured in your Firestore collection schema
                docs_ref = db.collection('PbiVgrmLxGhdcoynZKKFxrXlz373') \
                             .where('specialty', '==', specialty) \
                             .where('city', '==', location)
                
                docs = docs_ref.get()
                
                available_doctors = []
                for doc in docs:
                    doctor_data = doc.to_dict()
                    bookings = doctor_data.get('bookings', [])
                    
                    # Check for availability on the specified date
                    is_available_on_date = False
                    for booking in bookings:
                        # Assuming 'date' in booking is a string like '2025-09-05'
                        if booking.get('date') == date_iso:
                            is_available_on_date = True
                            break
                    
                    if is_available_on_date:
                        available_doctors.append(doctor_data)
                
                if available_doctors:
                    doctor_list_text = ", ".join([doc['name'] + ' ' + doc['surname'] for doc in available_doctors])
                    response_text = f"I found the following {specialty} doctors available in {location} on {date_iso}: {doctor_list_text}. Which one would you like to book with?"
                else:
                    response_text = f"I could not find any {specialty} doctors in {location} available on {date_iso}. Would you like to check a different date or location?"
            except Exception as e:
                app.logger.error(f"Firestore query error: {e}")
                response_text = "I am having trouble looking for doctors right now. Please try again later."
    
    # Construct and return the Dialogflow-formatted JSON response
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

if __name__ == '__main__':
    # For local development, use a development server
    # In production (e.g., Cloud Run), the port is set by the environment
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
