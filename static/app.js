// State variables
let clips = [];
let currentPage = 0;
let totalPages = 0;
let totalClips = 0;

// DOM elements
const prevButton = document.getElementById('prevButton');
const nextButton = document.getElementById('nextButton');
const goToPageButton = document.getElementById('goToPageButton');
const saveButton = document.getElementById('saveButton');
const pageInfo = document.getElementById('pageInfo');
const progressBar = document.getElementById('progressBar');
const clipGrid = document.getElementById('clipGrid');

// Functions
function fetchClips() {
	axios.get(`/get_clips?page=${currentPage}`)
		.then(response => {
			clips = response.data.clips;
			totalPages = response.data.total_pages;
			totalClips = response.data.total_clips;
			clipsPerPage = response.data.clips_per_page;
			updateUI();
		});
}

function prevPage() {
	if (currentPage > 0) {
		saveComments();
		currentPage--;
		fetchClips();
	}
}

function nextPage() {
	if (currentPage < totalPages - 1) {
		saveComments();
		currentPage++;
		fetchClips();
	}
}

function goToPage(page) {
	if (page >= 0 && page <= (totalPages - 1)) {
		saveComments();
		currentPage = page;
		fetchClips();
	} else {
		alert("Page number is not in range");
	}
}

function promptForPage() {
	var newPageNumber = prompt("Go to page:");
	if (newPageNumber !== null && newPageNumber !== "") {
		newPageNumber = parseInt(newPageNumber);
		if (!isNaN(newPageNumber) && newPageNumber > 0) {
			goToPage(newPageNumber - 1);
		} else {
			alert("Invalid page number.");
		}
	}
}

function saveComments() {
	const comments = clips.map(clip => ({
		filename: clip.filename,
		comment: document.getElementById(`comment-${clip.filename}`).value
	}));
	axios.post('/save_comments', comments)
		.then(response => {
			showAlert(`Comments saved to ${response.data.file}`);
		})
		.catch(error => {
			showAlert('Error saving comments', 'danger');
		});
}

function showAlert(message, type = 'success') {
	const alertHtml = `
		<div class="alert alert-${type} alert-dismissible fade show" role="alert">
		${message}
		<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
		</div>
	`;
	document.getElementById('alertContainer').insertAdjacentHTML('beforeend', alertHtml);

	setTimeout(() => {
		const alerts = document.querySelectorAll('.alert');
		alerts.forEach(alert => {
			alert.style.opacity = '0';
			setTimeout(() => alert.remove(), 500);
		});
	}, 3000);
}

function updateUI() {
	pageInfo.textContent = `Page ${currentPage + 1} of ${totalPages} (Clips ${Math.min((currentPage + 1) * clipsPerPage, totalClips)} of ${totalClips})`;
	const progress = ((currentPage + 1) / totalPages) * 100;
	progressBar.style.width = `${progress}%`;
	prevButton.disabled = currentPage === 0;
	nextButton.disabled = currentPage === totalPages - 1;

	clipGrid.innerHTML = '';
	clips.forEach(clip => {
		const clipHtml = `
		<div class="col">
			<div class="card h-100">
			<div class="video-container">
				<video src="/video${clip.video_path}" autoplay loop muted></video>
			</div>
			<div class="card-body ${clip.clip_reviewed}">
				<p class="card-text">${clip.metadata}</p>
				<textarea id="comment-${clip.filename}" class="form-control">${clip.comment}</textarea>
			</div>
			</div>
		</div>
		`;
		clipGrid.insertAdjacentHTML('beforeend', clipHtml);
	});
}

function handleKeydown(event) {
	if (event.key === 'ArrowLeft') {
		prevPage();
	} else if (event.key === 'ArrowRight') {
		nextPage();
	}
}

// Event listeners
prevButton.addEventListener('click', prevPage);
nextButton.addEventListener('click', nextPage);
goToPageButton.addEventListener('click', promptForPage);
saveButton.addEventListener('click', saveComments);
document.addEventListener('keydown', handleKeydown);

// Initial fetch
fetchClips();