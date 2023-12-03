import os
import mysql.connector
import uuid
import io
import zipfile
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
    password="_123root",
    database="EasyShare"
)

# # Commit the changes and cl
# cursor = db.cursor()

# # SQL command to create the 'file_data' table
# create_table_query = '''
# CREATE TABLE file_data (
#     id INT AUTO_INCREMENT PRIMARY KEY,
#     file_name VARCHAR(255) NOT NULL,
#     file_link VARCHAR(255) NOT NULL,
#     user_id INT NOT NULL,
#     upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
#     last_modified_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
#     download_count INT DEFAULT 0
# );
# '''

# # Execute the SQL command
# cursor.execute(create_table_query)

# db.commit()
# exit(0)

storage_client = storage.Client()

@app.route('/')
def hello():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    files = request.files.getlist('files')

    if not files:
        return jsonify(message="No file part"), 400

    filelink = str(uuid.uuid4())  # Generate one link for all files

    for file in files:
        filename = secure_filename(file.filename)

        # Upload the file to DB
        cursor = db.cursor()
        cursor.execute(f"INSERT INTO {TABLE_NAME} (file_name, file_link, user_id) VALUES (%s, %s, %s)", (filename, filelink, -1))
        db.commit()
        cursor.close()

        # Upload the file to GCS
        blob = storage_client.bucket(BUCKET_NAME).blob(f'{filelink}/{filename}')
        blob.upload_from_string(
            file.read(), content_type=file.content_type)

    return jsonify(message=f'Files uploaded successfully. Access them at: /d/{filelink}'), 201   


@app.route('/d/<link>')
def display_file(link):
    cursor = db.cursor(dictionary=True)
    
    # Fetch details of the file matching the provided link
    cursor.execute(f"SELECT file_name, upload_time, download_count, file_link FROM {TABLE_NAME} WHERE file_link = %s", (link,))
    file_data = cursor.fetchone()
    cursor.close()

    if not file_data:
        return "File not found", 404  # Or any other appropriate response

    return render_template('file_detail.html', file=file_data)

@app.route('/download/<link>')
def download_file(link):
    cursor = db.cursor(dictionary=True)
    cursor.execute(f"SELECT file_name FROM {TABLE_NAME} WHERE file_link = %s", (link,))
    file_data = cursor.fetchone()

    if not file_data:
        return jsonify(message='File not found'), 404

    # Increment the download count
    cursor.execute(f"UPDATE {TABLE_NAME} SET download_count = download_count + 1 WHERE file_link = %s", (link,))
    db.commit()

    # Download logic
    blob = storage_client.bucket(BUCKET_NAME).blob(f'{link}/{file_data["file_name"]}')
    file = blob.download_as_bytes()
    in_memory_file = io.BytesIO(file)
    return send_file(
        in_memory_file,
        as_attachment=True,
        download_name=file_data["file_name"],
        mimetype='application/octet-stream'
    )

@app.route('/download_all/<link>')
def download_all_files(link):
    cursor = db.cursor(dictionary=True)
    cursor.execute(f"SELECT file_name FROM {TABLE_NAME} WHERE file_link = %s", (link,))
    files = cursor.fetchall()

    if not files:
        return jsonify(message='Files not found'), 404

    # Create a temporary ZIP file
    zip_filename = f'tmp_{link}.zip'
    with zipfile.ZipFile(zip_filename, 'w') as zipf:
        for file_data in files:
            # Download the file from Google Cloud Storage
            blob = storage_client.bucket(BUCKET_NAME).blob(f'{link}/{file_data["file_name"]}')
            file_content = blob.download_as_bytes()

            # Write the file to the ZIP archive
            zipf.writestr(file_data["file_name"], file_content)

    # Send the ZIP file
    return_data = io.BytesIO()
    with open(zip_filename, 'rb') as f:
        return_data.write(f.read())
    return_data.seek(0)
    os.remove(zip_filename)  # Clean up the temporary file

    return send_file(
        return_data,
        as_attachment=True,
        download_name=f'{link}_files.zip',
        mimetype='application/zip'
    )


if __name__ == "__main__":
    app.run(host=SERVER_IP, port=SERVER_PORT)