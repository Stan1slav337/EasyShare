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

        cursor = db.cursor()
        cursor.execute(
            f"INSERT INTO {TABLE_NAME} (file_name, file_link, user_id) VALUES (%s, %s, %s)",
            (filename, filelink, -1),
        )
        db.commit()
        cursor.close()

        blob = storage_client.bucket(BUCKET_NAME).blob(f"{filelink}/{filename}")
        blob.upload_from_string(file.read(), content_type=file.content_type)

    return (
        jsonify(
            message=f"Files uploaded successfully. Access them at: ", link=filelink
        ),
        201,
    )


@app.route("/d/<link>")
def display_file(link):
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        f"SELECT file_name, upload_time, download_count, file_link FROM {TABLE_NAME} WHERE file_link = %s",
        (link,),
    )
    files_data = cursor.fetchall()
    cursor.close()

    if not files_data:
        return "Files not found", 404

    return render_template("file_detail.html", files=files_data)


@app.route("/download/<link>/<filename>")
def download_file(link, filename):
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        f"SELECT file_name FROM {TABLE_NAME} WHERE file_link = %s AND file_name = %s",
        (link, filename),
    )
    file_data = cursor.fetchone()
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


if __name__ == "__main__":
    app.run(host=SERVER_IP, port=SERVER_PORT)
