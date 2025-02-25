from flask import Flask, request, render_template, jsonify, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from io import BytesIO
from PIL import Image
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
# SECRET_KEY = os.getenv("MY_SECRET")
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "./env.json"
app.secret_key = '89c25124aeaafe4fdcf01a2724187847'  # Change this to a secure secret key

# Initialize Google Cloud clients
storage_client = storage.Client()
datastore_client = datastore.Client()
print(datastore_client.project)  # Should match your GCP project ID

# Google Gemini API key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # Better to store this as environment variable

bucket_name = "chefbuckets"

# Authentication middleware
def login_required(f):
    def wrapper(*args, **kwargs):
        if 'user_email' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def get_blob_name_from_url(url):
    """Extract blob name from a GCS URL"""
    if f"{bucket_name}/" in url:
        return url.split(f"{bucket_name}/")[1]
    return url  # Return the original if we can't parse it

def generate_signed_url(blob_name, expiration=3600):
    """Generate a signed URL for a blob."""
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    
    url = blob.generate_signed_url(
        version="v4",
        # This URL is valid for 1 hour
        expiration=datetime.timedelta(seconds=expiration),
        # Allow GET requests using this URL
        method="GET"
    )
    
    return url

def get_image_metadata(image_data):
    # Encode the image
    encoded_image = base64.b64encode(image_data).decode('utf-8')
    
    # Prepare the API request
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    
    headers = {
        'Content-Type': 'application/json'
    }
    
    payload = {
        "contents": [{
            "parts": [
                {"text": "Please provide a short title (5-10 words) and a brief description (1-2 sentences) for this image. Format your response as: Title: [title] Description: [description]"},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": encoded_image
                    }
                }
            ]
        }]
    }
    
    # Make the API request
    params = {'key': GEMINI_API_KEY}
    response = requests.post(url, headers=headers, json=payload, params=params)
    result = response.json()
    
    try:
        text_response = result['candidates'][0]['content']['parts'][0]['text']
        
        # Extract title and description from the response
        title = ""
        description = ""
        
        if "Title:" in text_response and "Description:" in text_response:
            title_part = text_response.split("Title:")[1].split("Description:")[0].strip()
            description_part = text_response.split("Description:")[1].strip()
            title = title_part
            description = description_part
        else:
            # Fallback handling if the AI doesn't format as requested
            lines = text_response.strip().split('\n')
            title = lines[0] if lines else "Untitled Image"
            description = ' '.join(lines[1:]) if len(lines) > 1 else "No description available"
        
        return {
            "title": title,
            "description": description
        }
    except (KeyError, IndexError) as e:
        print(f"Error extracting metadata: {e}")
        return {
            "title": "Untitled Image",
            "description": "No description available"
        }

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Check if email already exists
        query = datastore_client.query(kind='users')
        query.add_filter('email', '=', email)
        existing_user = list(query.fetch(limit=1))
        
        if existing_user:
            flash('Email already exists')
            return redirect(url_for('signup'))
        
        # Create new user
        entity = datastore.Entity(key=datastore_client.key('users'))
        entity.update({
            'email': email,
            'password': password  # In production, hash this password!
        })
        datastore_client.put(entity)
        
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Check user credentials
        query = datastore_client.query(kind='users')
        query.add_filter('email', '=', email)
        query.add_filter('password', '=', password)  # In production, compare hashed passwords!
        user = list(query.fetch(limit=1))
        
        if user:
            session['user_email'] = email
            return redirect(url_for('gallery'))
        else:
            flash('Invalid credentials')
            return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_email', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def gallery():
    # Fetch images for the current user
    query = datastore_client.query(kind='images')
    query.add_filter('useremail', '=', session['user_email'])
    images = list(query.fetch())
    
    bucket = storage_client.bucket(bucket_name)
    
    # Generate signed URLs for each image and fetch metadata
    for image in images:
        # Handle both new records (with blob_name) and legacy records (with imagelink)
        if 'blob_name' in image:
            blob_name = image['blob_name']
        elif 'imagelink' in image:
            # Extract blob name from the URL for legacy data
            blob_name = get_blob_name_from_url(image['imagelink'])
            
            # Update this entry to use blob_name for future requests
            entity_key = image.key
            image_entity = datastore_client.get(entity_key)
            if image_entity:
                image_entity['blob_name'] = blob_name
                # Optionally, you can remove the imagelink field
                # if 'imagelink' in image_entity:
                #     del image_entity['imagelink']
                datastore_client.put(image_entity)
        else:
            # Skip if we can't determine the blob name
            continue
            
        # Generate a signed URL for the blob
        image['signed_url'] = generate_signed_url(blob_name)
        
        # Check if metadata JSON file exists and fetch it
        json_blob_name = os.path.splitext(blob_name)[0] + ".json"
        json_blob = bucket.blob(json_blob_name)
        
        if json_blob.exists():
            # Download and parse JSON metadata
            json_content = json_blob.download_as_string()
            try:
                metadata = json.loads(json_content)
                image['title'] = metadata.get('title', 'Untitled Image')
                image['description'] = metadata.get('description', 'No description available')
            except json.JSONDecodeError:
                image['title'] = 'Untitled Image'
                image['description'] = 'No description available'
        else:
            image['title'] = 'Untitled Image'
            image['description'] = 'No description available'
    
    return render_template('gallery.html', images=images)

@app.route('/upload', methods=['GET'])
@login_required
def upload_page():
    return render_template('upload_image.html')

@app.route('/upload-image', methods=['POST'])
@login_required
def upload_image():
    if 'image' not in request.files:
        return jsonify({"error": "No image part in the request"}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        # Generate unique filename
        unique_filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
        base_filename = os.path.splitext(unique_filename)[0]
        
        # Read image data
        image_data = file.read()
        
        # Get image metadata using Gemini
        metadata = get_image_metadata(image_data)
        
        # Create the metadata JSON content
        json_content = json.dumps({
            "title": metadata["title"],
            "description": metadata["description"]
        })
        
        bucket = storage_client.bucket(bucket_name)
        
        # Upload the image to Cloud Storage
        image_blob = bucket.blob(unique_filename)
        image_blob.upload_from_file(
            BytesIO(image_data),
            content_type=file.content_type
        )
        
        # Upload the JSON metadata file with the same base name
        json_blob_name = f"{base_filename}.json"
        json_blob = bucket.blob(json_blob_name)
        json_blob.upload_from_string(
            json_content,
            content_type="application/json"
        )
        
        # Store image metadata in Datastore - only store blob name, not full URL
        entity = datastore.Entity(key=datastore_client.key('images'))
        entity.update({
            'useremail': session['user_email'],
            'blob_name': unique_filename,  # Store only the blob name, not the full URL
            'title': metadata["title"],
            'description': metadata["description"],
            'upload_date': datetime.datetime.now()  # Optional: track upload date
        })
        datastore_client.put(entity)
        
        return redirect(url_for('gallery'))
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)