from flask import Flask, request, render_template, jsonify, redirect, url_for, session, flash
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

load_dotenv()

app = Flask(__name__)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "./env.json"
app.secret_key = os.getenv("FLASK_SECRET")

storage_client = storage.Client()
datastore_client = datastore.Client()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
bucket_name = "chefbuckets"

def generate_signed_url(blob_name, expiration=3600):
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    return blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(seconds=expiration),
        method="GET"
    )

def get_image_metadata(image_data):
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
    response = requests.post(url, headers=headers, json=payload, params={'key': GEMINI_API_KEY})
    result = response.json()
    
    try:
        text_response = result['candidates'][0]['content']['parts'][0]['text']
        title = "Untitled Image"
        description = "No description available"
        if "Title:" in text_response and "Description:" in text_response:
            title = text_response.split("Title:")[1].split("Description:")[0].strip()
            description = text_response.split("Description:")[1].strip()
        return {"title": title, "description": description}
    except Exception as e:
        print(f"Error extracting metadata: {e}")
        return {"title": "Untitled Image", "description": "No description available"}

@app.route('/')
def gallery():
    query = datastore_client.query(kind='images')
    images = list(query.fetch())
    bucket = storage_client.bucket(bucket_name)
    
    for image in images:
        if 'blob_name' in image:
            blob_name = image['blob_name']
            image['signed_url'] = generate_signed_url(blob_name)
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
        return jsonify({"error": "No image part in the request"}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        unique_filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
        base_filename = os.path.splitext(unique_filename)[0]
        image_data = file.read()
        metadata = get_image_metadata(image_data)
        
        bucket = storage_client.bucket(bucket_name)
        image_blob = bucket.blob(unique_filename)
        image_blob.upload_from_file(BytesIO(image_data), content_type=file.content_type)
        
        json_blob_name = f"{base_filename}.json"
        json_blob = bucket.blob(json_blob_name)
        json_blob.upload_from_string(json.dumps(metadata), content_type="application/json")
        
        entity = datastore.Entity(key=datastore_client.key('images'))
        entity.update({
            'blob_name': unique_filename,
            'title': metadata["title"],
            'description': metadata["description"],
            'upload_date': datetime.datetime.now()
        })
        datastore_client.put(entity)
        
        return redirect(url_for('gallery'))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
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
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)