function handleFileUpload() {
	var fileInput = document.getElementById('fileInput');
	if (fileInput.files.length === 0) {
		alert('No file selected!');
		return;
	}

	var formData = new FormData();

	for (let i = 0; i < fileInput.files.length; i++) {
		formData.append('files', fileInput.files[i]);
	}

	fetch('/upload', {
			method: 'POST',
			body: formData
		})
		.then(response => response.json())
		.then(data => {
			document.getElementById('upload-status').innerText = data.message;
			var anchorElement = document.createElement('a');
			anchorElement.href = '/d/' + data.link
			anchorElement.classList.add('tagline')
			anchorElement.innerText = 'Download link'
			document.getElementById('upload-status').appendChild(anchorElement);
		})
		.catch(error => {
			document.getElementById('upload-status').innerText = 'Upload Failed.';
		});

}

function triggerFileInput() {
	document.getElementById('fileInput').value = '';
	document.getElementById('fileInput').click();
}

// This function could be triggered after a successful login
function onLoginSuccess() {
    // Redirect to a user dashboard or a specific page
    window.location.href = '/user-dashboard'; 
    // or you can display a success message
    // alert('Successfully logged in with Google!');
}
