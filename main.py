import os
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# Initialize Flask app
app = Flask(__name__)

# Initialize Firebase Admin SDK
# Use the GOOGLE_APPLICATION_CREDENTIALS environment variable for security
firebase_admin.initialize_app()
db = firestore.client()

@app.route('/', methods=['POST'])
def webhook():
    """
    Dialogflow CX webhook for doctor availability.
    It queries Firestore to find doctors based on specialty, date, and location.
    """
    request_data = request.get_json()
    
    session_info = request_data.get('sessionInfo', {})
    parameters = session_info.get('parameters', {})
    tag = request_data.get('fulfillmentInfo', {}).get('tag')
    
    response_text = "I'm sorry, an error occurred. Please try again."

    if tag == 'search_doctors':
        specialty = parameters.get('specialty')
        location = parameters.get('location', {}).get('city')
        date_param = parameters.get('date') # Get the full date object/string

        # Safely extract the date string from the parameter
        if isinstance(date_param, str):
            date_str = date_param
        elif isinstance(date_param, dict) and 'date_time' in date_param:
            date_str = date_param['date_time']
        else:
            # Handle cases where the date parameter is missing or in an unexpected format
            response_text = "I couldn't understand the date provided. Please try again."
            return jsonify({
                'fulfillmentResponse': {
                    'messages': [{ 'text': { 'text': [response_text] } }]
                }
            })

        if not specialty or not location or not date_str:
            response_text = "I'm missing some information. Please provide your preferred specialty, location, and date."
        else:
            try:
                # Dialogflow sends date as ISO 8601 string (e.g., '2025-09-05T12:00:00Z')
                # We extract the date part and check if it's in the future
                requested_date = datetime.strptime(date_str.split('T')[0], '%Y-%m-%d').date()
                today = datetime.now().date()
                
                # We only show upcoming availability, so check if the date is in the past
                if requested_date < today:
                    response_text = "I can only check for future appointments. Please provide a date that isn't in the past."
                    return jsonify({
                        'fulfillmentResponse': {
                            'messages': [{ 'text': { 'text': [response_text] } }]
                        }
                    })

                # Reference the 'doctors' collection
                docs_ref = db.collection('doctors')
                
                # Query Firestore for matching specialty and city
                docs = docs_ref.where('specialty', '==', specialty).where('city', '==', location).stream()
                
                available_doctors = []
                for doc in docs:
                    doctor_data = doc.to_dict()
                    
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
                
                if available_doctors:
                    doctor_list_text = " and ".join([f"{doc['name']} has availability at {doc['times']}" for doc in available_doctors])
                    response_text = f"I found the following doctors: {doctor_list_text}. Please let me know which doctor and time you would like to book."
                else:
                    response_text = f"I could not find any {specialty} doctors in {location} available on {requested_date.strftime('%B %d, %Y')}. Would you like to check a different date or location?"
            
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
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
