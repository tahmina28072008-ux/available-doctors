import os
from flask import Flask, request, jsonify
from google.cloud import firestore

app = Flask(__name__)

# Initialize the Firestore client. This assumes the Cloud Run environment
# provides the necessary credentials automatically.
db = firestore.Client()
DOCTORS_COLLECTION = 'doctors'

@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Handles incoming webhook requests and queries Firestore for doctors.
    
    It extracts specialty and location from the agent's request and
    returns a list of available doctors.
    """
    try:
        req = request.get_json(silent=True)
        print(f"Received webhook request: {req}")

        # Extract the parameters from the agent's request payload.
        parameters = req.get('sessionInfo', {}).get('parameters', {})
        specialty = parameters.get('specialty')
        city = parameters.get('location') # Assuming the parameter name is 'location'

        # Build the Firestore query.
        doctors_ref = db.collection(DOCTORS_COLLECTION)
        query = doctors_ref

        # Add filters to the query based on the parameters.
        if specialty:
            # Query the 'specialty' field in the documents.
            query = query.where('specialty', '==', specialty)
        if city:
            # Query the 'city' field in the documents.
            query = query.where('city', '==', city)

        # Execute the query and get the documents.
        docs = query.stream()

        found_doctors = []
        for doc in docs:
            doc_data = doc.to_dict()
            name = doc_data.get('name')
            # For simplicity, we'll just check if the availability map is not empty.
            # A more robust solution would check specific time slots.
            is_available = bool(doc_data.get('availability')) 
            
            if name and is_available:
                found_doctors.append(name)
        
        # Prepare the response message based on the query results.
        if found_doctors:
            doctor_list = ", ".join(found_doctors)
            message = f"Okay, we found some doctors for you. They are: {doctor_list}."
        else:
            message = "I'm sorry, I couldn't find any available doctors with that criteria."

        # Construct the final response payload for the agent.
        response = {
            "fulfillmentResponse": {
                "messages": [
                    {
                        "text": {
                            "text": [message]
                        }
                    }
                ]
            }
        }
        
        return jsonify(response)

    except Exception as e:
        print(f"Error handling webhook request: {e}")
        return jsonify({
            "fulfillmentResponse": {
                "messages": [
                    {
                        "text": {
                            "text": ["An error occurred while processing your request."]
                        }
                    }
                ]
            }
        }), 500

if __name__ == '__main__':
    # Cloud Run provides the PORT environment variable.
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
