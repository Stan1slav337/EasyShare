import os
import mysql.connector
import uuid
import io
import zipfile
import requests
from config import *
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
from werkzeug.utils import secure_filename
from google.cloud import storage
from google.oauth2 import id_token
from pip._vendor import cachecontrol
from google_auth_oauthlib.flow import Flow
import google.auth.transport.requests

app = Flask(__name__)
app.static_folder = "templates"
app.secret_key = GOOGLE_SECRET_KEY
db = mysql.connector.connect(**DB_CONFIG)
storage_client = storage.Client()

flow = Flow.from_client_secrets_file(
    client_secrets_file=CLIENT_SECRETS_FILE,
    scopes=["https://www.googleapis.com/auth/userinfo.profile", "https://www.googleapis.com/auth/userinfo.email", "openid"],
    redirect_uri="http://localhost:5000/login/callback"
)

@app.route("/")
#@login_is_required
def hello():
    name = session["name"] if "name" in session else ""
    return render_template("index.html", name=name)


def login_is_required(function):
    def wrapper(*args, **kwargs):
        if "google_id" not in session:
            return jsonify(message="Not authorized"), 401
        else:
            return function()

    return wrapper


@app.route("/login")
def login():
    authorization_url, state = flow.authorization_url()
    session["state"] = state
    return redirect(authorization_url)


@app.route("/login/callback")
def callback():
    flow.fetch_token(authorization_response=request.url)

    # if not session["state"] == request.args["state"]:
    #     abort(500)  # State does not match!

    credentials = flow.credentials
    request_session = requests.session()
    cached_session = cachecontrol.CacheControl(request_session)
    token_request = google.auth.transport.requests.Request(session=cached_session)

    id_info = id_token.verify_oauth2_token(
        id_token=credentials._id_token,
        request=token_request,
        audience=GOOGLE_CLIENT_ID
    )

    session["google_id"] = id_info.get("sub")
    session["name"] = id_info.get("name")
    return redirect("/")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")
    

def protected_area():
    return f"Hello {session['name']}! <br/> <a href='/logout'><button>Logout</button></a>"


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
        user_id = session["google_id"] if "google_id" in session else -1
        cursor = db.cursor()
        cursor.execute(
            f"INSERT INTO {TABLE_NAME} (file_name, file_link, user_id, file_size) VALUES (%s, %s, %s, %s)",
            (filename, filelink, user_id, file_size),
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
        f"SELECT file_name, upload_time, download_count, file_size, user_id, file_link FROM {TABLE_NAME} WHERE file_link = %s",
        (link,),
    )
    files_data = cursor.fetchall()
    cursor.close()

    if not files_data:
        return "Files not found", 404
    
    user_id = files_data[0]["user_id"]
    if user_id != "-1":
        if "google_id" not in session:
            return jsonify(message="Not authorized"), 401
        google_id = session["google_id"]
        if google_id != user_id:
            return jsonify(message="No permission to access files, Log In"), 401

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
    user_id_param = request.args.get('user_id')

    if not user_id_param:
        return jsonify(message="User ID is required"), 400

    cursor = db.cursor(dictionary=True)

    # Get the user_id associated with the files
    cursor.execute(
        f"SELECT file_name, user_id FROM {TABLE_NAME} WHERE file_link = %s", (link,)
    )
    files_data = cursor.fetchall()

    if not files_data:
        cursor.close()
        return jsonify(message="Files not found"), 404

    user_id = files_data[0]["user_id"]
    cursor.close()

    # Check if user_id is -1 or matches the provided user_id
    if user_id != -1 and str(user_id) != user_id_param:
        return jsonify(message="No permission to access files"), 401

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



@app.route("/my_files")
def my_files():
    # Check if the user is logged in
    if "google_id" not in session:
        return redirect(url_for("login"))

    # Get the user's Google ID from the session
    user_id = session["google_id"]

    # Connect to the database
    cursor = db.cursor(dictionary=True)

    # Retrieve files associated with the user_id
    cursor.execute(
        f"SELECT * FROM {TABLE_NAME} WHERE user_id = %s", (user_id,)
    )
    files_data = cursor.fetchall()
    cursor.close()

    # Check if the user has any files
    if not files_data:
        return "No files found for the user", 404
    
        # Optional: Convert file sizes to a more readable format (e.g., KB, MB, etc.)
    for file in files_data:
        file['file_size'] = human_readable_size(file['file_size'])

    # Render a template to display the files
    # You need to create a template 'my_files.html' that will display these files
    return render_template("file_detail.html", files=files_data, name=session["name"])

@app.route("/api_usage")
def api_usage():
    user_logged_in = "google_id" in session
    user_id = session["google_id"] if user_logged_in else None

    return render_template("api_usage.html", user_logged_in=user_logged_in, user_id=user_id)




if __name__ == "__main__":
    app.run(host=SERVER_IP, port=SERVER_PORT)
