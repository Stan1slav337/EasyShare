import os
import mysql.connector
import uuid
import io
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from google.cloud import storage

SERVER_IP = '0.0.0.0'
SERVER_PORT = 5000
BUCKET_NAME = 'easyshare_data_bucket'
TABLE_NAME = 'file_data'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '.credentials/ServiceKey_GoogleCloud.json'

app = Flask(__name__)
db = mysql.connector.connect(
    host="localhost",
    user="admin",
    password="root",
    database="EasyShare"
)
storage_client = storage.Client()

@app.route('/')
def hello():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():

    if 'file' not in request.files:
        return jsonify(message="No file part"), 400
        
    file = request.files['file']
    
    filename = secure_filename(file.filename)
    filelink = str(uuid.uuid4())

    # Upload the file to DB
    cursor = db.cursor()
    cursor.execute(f"INSERT INTO {TABLE_NAME} (file_name, file_link, user_id) VALUES (%s, %s, %s)", (filename, filelink, -1))
    db.commit()
    cursor.close()

    # Upload the file to GCS
    blob = storage_client.bucket(BUCKET_NAME).blob(f'{filelink}/{filename}')
    blob.upload_from_string(
        file.read(), content_type=file.content_type)
    
    return jsonify(message=f'File uploaded successfully. Access it at: /d/{filelink}'), 201
    

@app.route('/d/<link>')
def download_file(link):
    cursor = db.cursor(dictionary=True)
    cursor.execute(f"SELECT file_name FROM {TABLE_NAME} WHERE file_link = %s", (link,))
    file_name_dict = cursor.fetchone()
    cursor.close()

    if not file_name_dict:
        return jsonify(message=f'File not found'), 400
        
    file_name = file_name_dict['file_name']
        
    blob = storage_client.bucket(BUCKET_NAME).blob(f'{link}/{file_name}')
    file = blob.download_as_bytes()
    
    in_memory_file = io.BytesIO(file)

    return send_file(
        in_memory_file,
        as_attachment=True,
        download_name=file_name,
        mimetype='application/octet-stream'  # Set the appropriate MIME type
    )

if __name__ == "__main__":
    app.run(host=SERVER_IP, port=SERVER_PORT)