from flask import Flask, request, render_template, jsonify, redirect, url_for, session, flash, send_file
from werkzeug.utils import secure_filename
from io import BytesIO
from google.cloud import storage, datastore
from dotenv import load_dotenv
import uuid
import os
import base64
import requests
import datetime
import json
import logging

logging.basicConfig(level=logging.INFO)

load_dotenv()

app = Flask(__name__)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "./env.json"
app.secret_key = os.getenv("FLASK_SECRET")

storage_client = storage.Client()
datastore_client = datastore.Client()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEYSS")
bucket_name = "project3-cloud-native-dev-chef"

def generate_signed_url(blob_name, expiration=3600):
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    return blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(seconds=expiration),
        method="GET"
    )

def get_image_metadata(image_data):
    try:
        # Log API key status (masked for security)
        if GEMINI_API_KEY:
            api_key_status = f"API key present (length: {len(GEMINI_API_KEY)})"
        else:
            api_key_status = "API key missing"
        logging.info(f"Gemini API key status: {api_key_status}")
        
        encoded_image = base64.b64encode(image_data).decode('utf-8')
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
        headers = {'Content-Type': 'application/json'}
        payload = {
            "contents": [{
                "parts": [
                    {"text": "Please provide a short title (5-10 words) and a brief description (1-2 sentences) for this image. Format: Title: [title] Description: [description]"},
                    {"inline_data": {"mime_type": "image/jpeg", "data": encoded_image}}
                ]
            }]
        }
        
        logging.info(f"Sending request to Gemini API at: {url}")
        response = requests.post(url, headers=headers, json=payload, params={'key': GEMINI_API_KEY})
        
        # Log response status
        logging.info(f"Gemini API response status: {response.status_code}")
        
        # Check if the response is valid
        if response.status_code != 200:
            logging.error(f"Gemini API error: {response.status_code} - {response.text}")
            return {"title": "Untitled Image", "description": "No description available"}
        
        result = response.json()
        
        # Debug log the response structure
        logging.debug(f"Response structure: {json.dumps(result, indent=2)}")
        
        # Check if 'candidates' exists
        if 'candidates' not in result:
            logging.error(f"No 'candidates' in response: {result}")
            return {"title": "Untitled Image", "description": f"API error: {result.get('error', {}).get('message', 'Unknown error')}"}
        
        text_response = result['candidates'][0]['content']['parts'][0]['text']
        title = "Untitled Image"
        description = "No description available"
        
        if "Title:" in text_response and "Description:" in text_response:
            title = text_response.split("Title:")[1].split("Description:")[0].strip()
            description = text_response.split("Description:")[1].strip()
            
        return {"title": title, "description": description}
        
    except Exception as e:
        logging.error(f"Error extracting metadata: {e}", exc_info=True)
        return {"title": "Untitled Image", "description": "Error processing image"}

@app.route('/serve_image/<blob_name>')
def serve_image(blob_name):
    try:
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        # Download image into memory
        image_bytes = blob.download_as_bytes()
        # Send the image file directly
        return send_file(
            BytesIO(image_bytes),
            mimetype=blob.content_type,
            download_name=blob_name
        )
    except Exception as e:
        logging.error(f"Error serving image: {e}")
        return "Image not found", 404

@app.route('/')
def gallery():
    query = datastore_client.query(kind='images')
    images = list(query.fetch())
    bucket = storage_client.bucket(bucket_name)
    
    for image in images:
        if 'blob_name' in image:
            blob_name = image['blob_name']
            # Add signed URL for direct access
            image['signed_url'] = generate_signed_url(blob_name)
            # Also include the serve_image URL as a fallback
            image['serve_url'] = url_for('serve_image', blob_name=blob_name)
            
            # Load metadata from JSON blob
            json_blob_name = os.path.splitext(blob_name)[0] + ".json"
            json_blob = bucket.blob(json_blob_name)
            if json_blob.exists():
                json_content = json_blob.download_as_string()
                try:
                    metadata = json.loads(json_content)
                    image['title'] = metadata.get('title', 'Untitled Image')
                    image['description'] = metadata.get('description', 'No description available')
                except json.JSONDecodeError:
                    pass
    return render_template('gallery.html', images=images)

@app.route('/upload', methods=['GET'])
def upload_page():
    return render_template('upload_image.html')

@app.route('/upload-image', methods=['POST'])
def upload_image():
    if 'image' not in request.files:
        flash("No image part in the request", "error")
        return redirect(url_for('upload_page'))
    
    file = request.files['image']
    if file.filename == '':
        flash("No selected file", "error")
        return redirect(url_for('upload_page'))
    
    try:
        unique_filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
        base_filename = os.path.splitext(unique_filename)[0]
        image_data = file.read()
        
        # Get metadata from Gemini API (with better error handling)
        metadata = get_image_metadata(image_data)
        logging.info(f"Generated metadata: {metadata}")
        
        bucket = storage_client.bucket(bucket_name)
        image_blob = bucket.blob(unique_filename)
        image_blob.upload_from_file(BytesIO(image_data), content_type=file.content_type)
        logging.info(f"Uploaded image to blob: {unique_filename}")
        
        # Save metadata to a separate JSON blob
        json_blob_name = f"{base_filename}.json"
        json_blob = bucket.blob(json_blob_name)
        json_blob.upload_from_string(json.dumps(metadata), content_type="application/json")
        logging.info(f"Uploaded metadata to blob: {json_blob_name}")
        
        # Store in Datastore with Gemini metadata
        entity = datastore.Entity(key=datastore_client.key('images'))
        entity.update({
            'blob_name': unique_filename,
            'title': metadata["title"],
            'description': metadata["description"],
            'upload_date': datetime.datetime.now()
        })
        datastore_client.put(entity)
        logging.info("Saved to Datastore")
        
        flash("Image uploaded successfully!", "success")
        return redirect(url_for('gallery'))
    except Exception as e:
        logging.error(f"Error uploading image: {e}", exc_info=True)
        flash(f"Error uploading image: {str(e)}", "error")
        return redirect(url_for('upload_page'))
    
@app.route('/delete-image', methods=['POST'])
def delete_image():
    data = request.get_json()
    image_id = data.get('image_id')

    if not image_id:
        return jsonify({"error": "No image ID provided"}), 400

    try:
        key = datastore_client.key('images', int(image_id))
        image_entity = datastore_client.get(key)

        if not image_entity:
            return jsonify({"error": "Image not found"}), 404

        blob_name = image_entity['blob_name']
        base_filename = os.path.splitext(blob_name)[0]
        json_blob_name = f"{base_filename}.json"

        # Delete from Cloud Storage
        bucket = storage_client.bucket(bucket_name)
        image_blob = bucket.blob(blob_name)
        json_blob = bucket.blob(json_blob_name)

        if image_blob.exists():
            image_blob.delete()
        if json_blob.exists():
            json_blob.delete()

        # Delete from Datastore
        datastore_client.delete(key)

        return jsonify({"success": True}), 200

    except Exception as e:
        logging.error(f"Error deleting image: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# Add a route to verify the Gemini API key is working
@app.route('/check-gemini-api', methods=['GET'])
def check_gemini_api():
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash"
        response = requests.get(url, params={'key': GEMINI_API_KEY})
        if response.status_code == 200:
            return jsonify({"status": "API key is valid", "response": response.json()})
        else:
            return jsonify({"status": "API key may be invalid", "error": response.text}), 400
    except Exception as e:
        return jsonify({"status": "Error checking API", "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)