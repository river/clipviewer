document.addEventListener('DOMContentLoaded', function () {

	// State variables
	let currentClips = [];
	let nextClips = [];
	let nextClipElements = [];
	let currentPage = 0;
	let totalPages = 0;
	let totalClips = 0;
	let clipsPerPage = 0;
	let labelOptions = []

	// Utility: escape HTML to prevent XSS (string-based, no DOM allocation)
	function escapeHtml(str) {
		return str.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
	}

	// ------------------------
	// csv and metadata loading
	// ------------------------

	const loadForm = document.getElementById('loadForm');
	const csvPathInput = document.getElementById('csvPathInput');
	const metadataInput = document.getElementById('metadataInput');
	const labelOptionsInput = document.getElementById('labelOptionsInput');
	const freeTextToggle = document.getElementById('freeTextToggle');

	// Load values from URL query parameters and initialize inputs and currentPage
	const urlParams = new URLSearchParams(window.location.search);
	csvPathInput.value = urlParams.get('csvPath') || '';
	metadataInput.value = urlParams.get('metadata') || '';
	labelOptionsInput.value = urlParams.get('labels') || '';
	freeTextToggle.checked = urlParams.get('freeText') === 'true';
	const urlPage = urlParams.get('page');
	if (urlPage) {
		currentPage = Number(urlPage);
	}

	// Update URL with current form inputs and page number
	function updateUrlParams() {
		const params = new URLSearchParams();
		params.set('csvPath', csvPathInput.value);
		params.set('metadata', metadataInput.value);
		params.set('labels', labelOptionsInput.value);
		params.set('freeText', freeTextToggle.checked);
		params.set('page', currentPage);
		window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`);
	}

	loadForm.addEventListener('submit', handleFormSubmit);

	freeTextToggle.addEventListener('change', function () {
		updateUrlParams();
		if (currentClips.length > 0) {
			// Read current comment values from DOM before re-rendering
			currentClips.forEach((clip, index) => {
				const el = document.getElementById(`comment-${index}`);
				if (el) clip.comment = el.value;
			});
			updateUI();
			// Rebuild preloaded next page elements with new widget type
			nextClipElements.forEach(el => el.remove());
			nextClipElements.length = 0;
			if (nextClips.length > 0) {
				createHiddenElements(nextClips);
			}
		}
	});

	// If URL already has parameters, auto-submit the form
	if (csvPathInput.value) {
		handleFormSubmit(new Event('submit'));
	}

	function handleFormSubmit(event) {
		event.preventDefault();
		updateUrlParams();
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
		document.getElementById('clip-viewer').style.opacity = '0.1';

		axios.post('/load_csv', { csv_path: csvPath, metadata_fields: metadataFields })
			.then(response => {
				showAlert(response.data.message);
				fetchClips();
			})
			.catch(error => {
				const msg = error.response?.data?.message || error.message || 'An error occurred';
				showAlert(msg, 'danger');
			})
			.finally(() => {
				// Hide loading spinner
				hideLoadingSpinner();
				document.getElementById('clip-viewer').style.opacity = '1';
			});

		// load label options: filter out empty entries, then prepend a single blank option
		labelOptions = ['', ...labelOptionsInput.value.split(',').filter(s => s.trim() !== '')];
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
	document.getElementById('exportButton').addEventListener('click', () => {
		window.location.href = '/export_comments';
	});
	document.addEventListener('keydown', handleKeydown);

	function fetchClips() {
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
		if (currentPage < totalPages - 1) {
			axios.get(`/get_clips?page=${currentPage + 1}`)
				.then(response => {
					nextClips = response.data.clips;
					createHiddenElements(nextClips);
				});
		}
	}

	const videoCardTemplate = (clip, index) => {
		const commentId = `comment-${index}`;
		let commentHtml;
		if (freeTextToggle.checked) {
			commentHtml = `<input type="text" id="${commentId}" class="form-control" value="${escapeHtml(clip.comment)}">`;
		} else {
			const optionsHtml = labelOptions.map((optionText) => {
				const escaped = escapeHtml(optionText);
				return clip.comment === optionText
					? `<option value="${escaped}" selected>${escaped}</option>`
					: `<option value="${escaped}">${escaped}</option>`;
			}).join('');
			commentHtml = `<select id="${commentId}" class="form-select">${optionsHtml}</select>`;
		}

		return `
			<div class="col">
				<div class="card h-100">
					<div class="video-container">
						<video src="/video${escapeHtml(clip.avi_path)}" autoplay loop muted></video>
					</div>
					<div class="card-body ${escapeHtml(clip.clip_reviewed)}">
						<p class="card-text">${escapeHtml(clip.metadata)}</p>
						${commentHtml}
					</div>
				</div>
			</div>
		`;
	}

	function createHiddenElements(clips) {
		nextClipElements = [];
		clips.forEach((clip, index) => {
			const template = document.createElement('template');
			template.innerHTML = videoCardTemplate(clip, index).trim();
			const clipElement = template.content.firstChild;
			clipElement.style.display = 'none';
			nextClipElements.push(clipElement);
			clipGrid.appendChild(clipElement);
		});
	}

	function nextPage() {
		if (currentPage < totalPages - 1) {
			saveComments();
			currentPage++;
			updateUrlParams();
			if (nextClips.length > 0 && nextClipElements.length > 0) {
				swapInNextPage();
			} else {
				fetchClips();
			}
		}
	}

	function swapInNextPage() {
		// Remove current clips from DOM and clear from memory
		Array.from(clipGrid.children).forEach(child => {
			if (!nextClipElements.includes(child)) {
				// Remove event listeners
				child.onclick = null;
				child.onmouseover = null;
				child.onmouseout = null;

				// Clear video source and pause playback
				const video = child.querySelector('video');
				if (video) {
					video.pause();
					video.src = '';
					video.load();
				}

				// Remove child from DOM
				child.remove();

				// Clear any references in the child
				if (child.player) {
					child.player.dispose();
					child.player = null;
				}
			}
		});

		// Show next clips
		nextClipElements.forEach(element => {
			element.style.display = '';
		});

		// Clear references
		currentClips.length = 0;
		currentClips = nextClips.slice(); // Create a shallow copy
		nextClips.length = 0;
		nextClipElements.length = 0;

		updatePageInfo();
		preloadNextPage();
	}

	function prevPage() {
		if (currentPage > 0) {
			saveComments();
			currentPage--;
			updateUrlParams();
			fetchClips();
		}
	}

	function goToPage(page) {
		if (page >= 0 && page <= (totalPages - 1)) {
			saveComments();
			currentPage = page;
			updateUrlParams();
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
		if (currentClips.length === 0) return Promise.resolve();

		const comments = currentClips.map((clip, index) => {
			const el = document.getElementById(`comment-${index}`);
			return {
				avi_path: clip.avi_path,
				comment: el ? el.value : ''
			};
		});

		return axios.post('/save_comments', comments)
			.then(response => {
				const dbPath = response.data.db_path;
				showAlert(`Comments saved to ${dbPath}`);
			})
			.catch(() => {
				showAlert('Error saving comments', 'danger');
			});
	}

	function showAlert(message, type = 'success') {
		const alertHtml = `
			<div class="alert alert-${type} alert-dismissible fade show" role="alert">
				${escapeHtml(message)}
				<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
			</div>
		`;
		const alertElement = document.createElement('div');
		alertElement.innerHTML = alertHtml;
		const alert = alertElement.firstElementChild;
		const alertContainer = document.getElementById('alertContainer');
		alertContainer.appendChild(alert);

		// Reading offsetHeight forces a browser reflow, ensuring the
		// 'show' class CSS transition triggers correctly on the alert.
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
		pageInfo.textContent = `Page ${currentPage + 1} of ${totalPages} (clips ${currentPage * clipsPerPage + 1}–${Math.min((currentPage + 1) * clipsPerPage, totalClips)} of ${totalClips})`;
		const progress = totalPages > 0 ? ((currentPage + 1) / totalPages) * 100 : 0;
		progressBar.style.width = `${progress}% `;
		prevButton.disabled = currentPage === 0;
		nextButton.disabled = currentPage === totalPages - 1;
	}

	function updateUI() {
		updatePageInfo();

		clipGrid.innerHTML = '';
		currentClips.forEach((clip, index) => {
			const clipHtml = videoCardTemplate(clip, index);
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
			// left and right arrow
			// and text input is NOT selected
			if (event.key === 'ArrowLeft') {
				prevPage();
			} else if (event.key === 'ArrowRight') {
				nextPage();
			}
		}
	}
});
