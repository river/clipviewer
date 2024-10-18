document.addEventListener('DOMContentLoaded', function() {

	// State variables
	let currentClips = [];
	let nextClips = [];
	let nextClipElements = [];
	let currentPage = 0;
	let totalPages = 0;
	let totalClips = 0;

	// ------------------------
	// csv and metadata loading
	// ------------------------

	const loadForm = document.getElementById('loadForm');
	const csvPathInput = document.getElementById('csvPathInput');
	const metadataInput = document.getElementById('metadataInput');

	loadForm.addEventListener('submit', handleFormSubmit);

	function handleFormSubmit(event) {
		event.preventDefault();
		loadCSV();
	}

    function loadCSV() {
		const csvPath = csvPathInput.value;
		const metadataFields = metadataInput.value;

		if (!csvPath) {
			showAlert('Please enter CSV path', 'danger');
			return;
		}

		// Show loading spinner
		showLoadingSpinner();
		document.getElementById('clip-viewer').style.opacity = '10%';

		axios.post('/load_csv', { csv_path: csvPath, metadata_fields: metadataFields })
			.then(response => {
				showAlert(response.data.message);
				fetchClips();
			})
			.catch(error => {
				showAlert(error.response.data.message, 'danger');
			})
			.finally(() => {
				// Hide loading spinner
				hideLoadingSpinner();
				document.getElementById('clip-viewer').style.opacity = '100%';
			});
	}

	function showLoadingSpinner() {
		// Create and show the loading spinner
		const spinner = document.createElement('div');
		spinner.id = 'loading-spinner';
		spinner.className = 'spinner-border text-primary';
		spinner.setAttribute('role', 'status');
		spinner.innerHTML = '<span class="sr-only">Loading...</span>';
		document.body.appendChild(spinner);
	}

	function hideLoadingSpinner() {
		// Remove the loading spinner
		const spinner = document.getElementById('loading-spinner');
		if (spinner) {
			spinner.remove();
		}
	}

	// ------------------------
	// navigation
	// ------------------------

	const prevButton = document.getElementById('prevButton');
	const nextButton = document.getElementById('nextButton');
	const goToPageButton = document.getElementById('goToPageButton');
	const saveButton = document.getElementById('saveButton');
	const pageInfo = document.getElementById('pageInfo');
	const progressBar = document.getElementById('progressBar');
	const clipGrid = document.getElementById('clipGrid');

	prevButton.addEventListener('click', prevPage);
	nextButton.addEventListener('click', nextPage);
	goToPageButton.addEventListener('click', promptForPage);
	saveButton.addEventListener('click', saveComments);
	document.addEventListener('keydown', handleKeydown);

	function fetchClips() {
		// console.log("fetchClips()")

		axios.get(`/get_clips?page=${currentPage}`)
			.then(response => {
				currentClips = response.data.clips;
				totalPages = response.data.total_pages;
				totalClips = response.data.total_clips;
				clipsPerPage = response.data.clips_per_page;
				updateUI();
				preloadNextPage();
			});
	}

	function preloadNextPage() {
		// console.log("preloadNextPage()")

		if (currentPage < totalPages - 1) {
			axios.get(`/get_clips?page=${currentPage + 1}`)
				.then(response => {
					nextClips = response.data.clips;
					createHiddenElements(nextClips);
				});
		}
	}

	function createHiddenElements(clips) {
		// console.log("createHiddenElements()")

		nextClipElements = [];
		clips.forEach(clip => {
			const clipElement = document.createElement('div');
			clipElement.className = 'col';
			clipElement.style.display = 'none';
			clipElement.innerHTML = `
				<div class="card h-100">
					<div class="video-container">
						<video src="/video${clip.video_path}" autoplay loop muted></video>
					</div>
					<div class="card-body ${clip.clip_reviewed}">
						<p class="card-text">${clip.metadata}</p>
						<textarea id="comment-${clip.filename}" class="form-control">${clip.comment}</textarea>
					</div>
				</div>
			`;
			nextClipElements.push(clipElement);
			clipGrid.appendChild(clipElement);
		});
	}

	function nextPage() {
		// console.log("nextPage()")

		if (currentPage < totalPages - 1) {
			saveComments();
			currentPage++;
			if (nextClips.length > 0 && nextClipElements.length > 0) {
				swapInNextPage();
			} else {
				fetchClips();
			}
		}
	}

	function swapInNextPage() {
		// console.log("swapInNextPage()")

		// Remove current clips from DOM and clear from memory
		Array.from(clipGrid.children).forEach(child => {
			if (!nextClipElements.includes(child)) {
				child.remove();
			}
		});

		// Show next clips
		nextClipElements.forEach(element => {
			element.style.display = '';
		});

		currentClips = nextClips;
		nextClips = [];
		nextClipElements = [];
		updatePageInfo();
		preloadNextPage();
	}

	function prevPage() {
		// console.log("prevPage()")

		if (currentPage > 0) {
			saveComments();
			currentPage--;
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
		// console.log("saveComments()")

		const comments = currentClips.map(clip => ({
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
		const alertElement = document.createElement('div');
		alertElement.innerHTML = alertHtml;
		const alert = alertElement.firstElementChild;
		const alertContainer = document.getElementById('alertContainer');
		alertContainer.appendChild(alert);

		// Force a reflow to ensure the 'show' class takes effect
		alertContainer.offsetHeight;

		// Set up fade-out and removal for this specific alert
		setTimeout(() => {
			alert.classList.remove('show');
			alert.addEventListener('transitionend', () => {
				alert.remove();
			});
		}, 3000);
	}
	
	function updatePageInfo() {
		// console.log("updatePageInfo()")

		pageInfo.textContent = `Page ${currentPage + 1} of ${totalPages} (clips ${currentPage * clipsPerPage + 1}–${Math.min((currentPage + 1) * clipsPerPage, totalClips)} of ${totalClips})`;
		const progress = ((currentPage + 1) / totalPages) * 100;
		progressBar.style.width = `${progress}%`;
		prevButton.disabled = currentPage === 0;
		nextButton.disabled = currentPage === totalPages - 1;
	}

	function updateUI() {
		// console.log("updateUI()")

		updatePageInfo();

		clipGrid.innerHTML = '';
		currentClips.forEach(clip => {
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
		if (event.key === 'Escape') {
			// esc deselects any input
			if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') {
				document.activeElement.blur();
			}
		} else if (document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
			// left and right arrow (only if input is not selected)
			if (event.key === 'ArrowLeft') {
				prevPage();
			} else if (event.key === 'ArrowRight') {
				nextPage();
			}
		}
	}
});
