document.addEventListener('DOMContentLoaded', function () {

	// State variables
	let currentClips = [];
	const pageCache = new Map();
	const MAX_CACHE_SIZE = 7;
	const domCache = new Map();
	const MAX_DOM_CACHE_SIZE = 3;
	const preloadLinks = new Map();
	let currentPage = 0;
	let totalPages = 0;
	let totalClips = 0;
	let clipsPerPage = 0;
	let labelOptions = []

	// Utility: escape HTML to prevent XSS (string-based, no DOM allocation)
	function escapeHtml(str) {
		return str.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
	}

	function releaseVideos(container) {
		container.querySelectorAll('video').forEach(v => { v.pause(); v.src = ''; });
	}

	function removePreloadLinks(page) {
		const links = preloadLinks.get(page);
		if (links) {
			links.forEach(link => link.remove());
			preloadLinks.delete(page);
		}
	}

	function clearDomCache() {
		domCache.forEach(frag => releaseVideos(frag));
		domCache.clear();
		preloadLinks.forEach(links => links.forEach(link => link.remove()));
		preloadLinks.clear();
	}

	function evictMap(map, maxSize, onEvict) {
		while (map.size > maxSize) {
			let farthest = null, maxDist = -1;
			for (const key of map.keys()) {
				const dist = Math.abs(key - currentPage);
				if (dist > maxDist) { maxDist = dist; farthest = key; }
			}
			if (onEvict) onEvict(map.get(farthest), farthest);
			map.delete(farthest);
		}
	}

	function applyPageData(data) {
		currentClips = data.clips.map(c => ({...c}));
		totalPages = data.total_pages;
		totalClips = data.total_clips;
		clipsPerPage = data.clips_per_page;
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
			// DOM cache has wrong widget type, clear it
			clearDomCache();
			updateUI();
			preloadAdjacentPages();
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
		pageCache.clear();
		clearDomCache();
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

	function getCachedOrFetch(page) {
		if (pageCache.has(page)) {
			return Promise.resolve(pageCache.get(page));
		}
		return axios.get(`/get_clips?page=${page}`).then(response => {
			pageCache.set(page, response.data);
			evictCache();
			return response.data;
		});
	}

	function evictCache() {
		evictMap(pageCache, MAX_CACHE_SIZE);
	}

	function preloadAdjacentPages() {
		const pages = [];
		if (currentPage > 0) pages.push(currentPage - 1);
		if (currentPage < totalPages - 1) pages.push(currentPage + 1);
		pages.forEach(page => {
			getCachedOrFetch(page).then(data => {
				if (!domCache.has(page)) {
					prerenderDom(page, data);
				}
			}).catch(() => {});
		});
	}

	function prerenderDom(page, data) {
		const fragment = document.createDocumentFragment();
		const links = [];
		data.clips.forEach((clip, index) => {
			const wrapper = document.createElement('template');
			wrapper.innerHTML = videoCardTemplate(clip, index).trim();
			const el = wrapper.content.firstChild;
			const video = el.querySelector('video');
			if (video) {
				video.removeAttribute('autoplay');
				// Prefetch video so it's in browser cache when swapped in
				const link = document.createElement('link');
				link.rel = 'preload';
				link.as = 'video';
				link.href = video.src;
				document.head.appendChild(link);
				links.push(link);
			}
			fragment.appendChild(el);
		});
		preloadLinks.set(page, links);
		domCache.set(page, fragment);
		evictDomCache();
	}

	function evictDomCache() {
		evictMap(domCache, MAX_DOM_CACHE_SIZE, (frag, key) => {
			releaseVideos(frag);
			removePreloadLinks(key);
		});
	}

	function saveCurrentDom() {
		if (clipGrid.children.length === 0) return;
		clipGrid.querySelectorAll('video').forEach(v => { v.pause(); });
		const fragment = document.createDocumentFragment();
		while (clipGrid.firstChild) {
			fragment.appendChild(clipGrid.firstChild);
		}
		domCache.set(currentPage, fragment);
		evictDomCache();
	}

	function fetchClips() {
		// Try DOM cache first (instant swap)
		if (domCache.has(currentPage) && pageCache.has(currentPage)) {
			clipGrid.appendChild(domCache.get(currentPage));
			domCache.delete(currentPage);
			removePreloadLinks(currentPage);
			clipGrid.querySelectorAll('video').forEach(v => { v.muted = true; v.play().catch(() => {}); });

			applyPageData(pageCache.get(currentPage));
			// Sync comment values from DOM into currentClips
			currentClips.forEach((clip, index) => {
				const el = document.getElementById(`comment-${index}`);
				if (el) clip.comment = el.value;
			});
			updatePageInfo();
			preloadAdjacentPages();
			return;
		}

		// Fall back to JSON cache or network fetch
		getCachedOrFetch(currentPage).then(data => {
			applyPageData(data);
			updateUI();
			preloadAdjacentPages();
		}).catch(() => {
			showAlert('Error loading clips', 'danger');
		});
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

	function nextPage() {
		if (currentPage < totalPages - 1) {
			saveComments();
			saveCurrentDom();
			currentPage++;
			updateUrlParams();
			fetchClips();
		}
	}

	function prevPage() {
		if (currentPage > 0) {
			saveComments();
			saveCurrentDom();
			currentPage--;
			updateUrlParams();
			fetchClips();
		}
	}

	function goToPage(page) {
		if (page >= 0 && page <= (totalPages - 1)) {
			saveComments();
			saveCurrentDom();
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
			const comment = el ? el.value : '';
			clip.comment = comment;
			return { avi_path: clip.avi_path, comment };
		});

		// Sync updated comments back into the cache
		if (pageCache.has(currentPage)) {
			pageCache.get(currentPage).clips = currentClips.map(c => ({...c}));
		}

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

		releaseVideos(clipGrid);
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
