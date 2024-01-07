import os
import mysql.connector
import uuid
import io
import zipfile
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from google.cloud import storage
from config import *

app = Flask(__name__)
app.static_folder = "templates"
db = mysql.connector.connect(**DB_CONFIG)
storage_client = storage.Client()


@app.route("/")
def hello():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    files = request.files.getlist("files")

    if not files:
        return jsonify(message="No file part"), 400

    filelink = str(uuid.uuid4())

    for file in files:
        filename = secure_filename(file.filename)
        file_content = file.read()  # Read the file content
        file_size = len(file_content)  # Calculate the file size in bytes

        # Database operations
        cursor = db.cursor()
        cursor.execute(
            f"INSERT INTO {TABLE_NAME} (file_name, file_link, user_id, file_size) VALUES (%s, %s, %s, %s)",
            (filename, filelink, -1, file_size),
        )
        db.commit()
        cursor.close()

        # Upload file to Google Cloud Storage
        blob = storage_client.bucket(BUCKET_NAME).blob(f"{filelink}/{filename}")
        blob.upload_from_string(file_content, content_type=file.content_type)

    return (
        jsonify(
            message="Files uploaded successfully. Access them at: ", link=filelink
        ),
        201,
    )


@app.route("/api/upload", methods=["POST"])
def api_upload_file():
    files = request.files.getlist("files")
    existing_link = request.form.get('link', None)  # Get the link if provided

    if not files:
        return jsonify(message="No file part"), 400

    filelink = existing_link if existing_link else str(uuid.uuid4())

    for file in files:
        filename = secure_filename(file.filename)
        file_content = file.read()  # Read the file content
        file_size = len(file_content)  # Calculate the file size in bytes

        # Database operations
        cursor = db.cursor()
        cursor.execute(
            f"INSERT INTO {TABLE_NAME} (file_name, file_link, user_id, file_size) VALUES (%s, %s, %s, %s)",
            (filename, filelink, -1, file_size),
        )
        db.commit()
        cursor.close()

        # File upload to Google Cloud Storage
        blob = storage_client.bucket(BUCKET_NAME).blob(f"{filelink}/{filename}")
        blob.upload_from_string(file_content, content_type=file.content_type)

    return jsonify(message="Files uploaded successfully", link=filelink), 201




@app.route("/d/<link>")
def display_file(link):
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        f"SELECT file_name, upload_time, download_count, file_size, file_link FROM {TABLE_NAME} WHERE file_link = %s",
        (link,),
    )
    files_data = cursor.fetchall()
    cursor.close()

    if not files_data:
        return "Files not found", 404

    # Optional: Convert file sizes to a more readable format (e.g., KB, MB, etc.)
    for file in files_data:
        file['file_size'] = human_readable_size(file['file_size'])

    return render_template("file_detail.html", files=files_data, link=link)

def human_readable_size(size, decimal_places=2):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0 or unit == 'TB':
            break
        size /= 1024.0
    return f"{size:.{decimal_places}f} {unit}"



@app.route("/download/<link>/<filename>")
def download_file(link, filename):
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        f"SELECT file_name FROM {TABLE_NAME} WHERE file_link = %s AND file_name = %s",
        (link, filename),
    )
    file_data = cursor.fetchone()

    cursor.execute(f"UPDATE {TABLE_NAME} SET download_count = download_count + 1 WHERE file_link = %s AND file_name = %s", (link, filename))
    db.commit()
    cursor.close()

    if not file_data:
        return "File not found", 404

    blob = storage_client.bucket(BUCKET_NAME).blob(f"{link}/{filename}")
    file = blob.download_as_bytes()
    in_memory_file = io.BytesIO(file)
    
    return send_file(
        in_memory_file,
        as_attachment=True,
        download_name=filename,
        mimetype="application/octet-stream",
    )


@app.route("/download_all/<link>")
def download_all_files(link):
    cursor = db.cursor(dictionary=True)

    cursor.execute(f"SELECT file_name FROM {TABLE_NAME} WHERE file_link = %s", (link,))
    files_data = cursor.fetchall()
    cursor.execute(f"UPDATE {TABLE_NAME} SET download_count = download_count + 1 WHERE file_link = %s", (link,))
    db.commit()
    cursor.close()

    if not files_data:
        return "Files not found", 404

    zip_filename = f"tmp_{link}.zip"
    with zipfile.ZipFile(zip_filename, "w") as zipf:
        for file_data in files_data:
            filename = file_data["file_name"]
            blob = storage_client.bucket(BUCKET_NAME).blob(f"{link}/{filename}")
            file_content = blob.download_as_bytes()

            zipf.writestr(filename, file_content)

    return_data = io.BytesIO()
    with open(zip_filename, "rb") as f:
        return_data.write(f.read())
    return_data.seek(0)
    os.remove(zip_filename)

    return send_file(
        return_data,
        as_attachment=True,
        download_name=f"{link}_files.zip",
        mimetype="application/zip",
    )

@app.route("/api/download/<link>", methods=["GET"])
def api_download_all_files(link):
    cursor = db.cursor(dictionary=True)
    cursor.execute(f"SELECT file_name FROM {TABLE_NAME} WHERE file_link = %s", (link,))
    files_data = cursor.fetchall()
    db.commit()
    cursor.close()

    if not files_data:
        return jsonify(message="Files not found"), 404

    zip_filename = f"tmp_{link}.zip"
    with zipfile.ZipFile(zip_filename, "w") as zipf:
        for file_data in files_data:
            filename = file_data["file_name"]
            blob = storage_client.bucket(BUCKET_NAME).blob(f"{link}/{filename}")
            file_content = blob.download_as_bytes()
            zipf.writestr(filename, file_content)

    return_data = io.BytesIO()
    with open(zip_filename, "rb") as f:
        return_data.write(f.read())
    os.remove(zip_filename)
    return_data.seek(0)

    return send_file(
        return_data,
        as_attachment=True,
        download_name=f"{link}_files.zip",
        mimetype="application/zip",
    )



if __name__ == "__main__":
    app.run(host=SERVER_IP, port=SERVER_PORT)
