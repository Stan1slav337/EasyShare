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