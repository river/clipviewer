document.addEventListener('DOMContentLoaded', function () {

	// State variables
	let currentClips = [];
	const pageCache = new Map();
	const MAX_CACHE_SIZE = 7;
	const domCache = new Map();
	const MAX_DOM_CACHE_SIZE = 3;
	const preloadLinks = new Map();
	const prerenderPromises = new Map();
	let navGeneration = 0;
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

	function syncClipsToCache() {
		if (pageCache.has(currentPage)) {
			pageCache.get(currentPage).clips = currentClips.map(c => ({...c}));
		}
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

	function syncLabelOptionsDisabled() {
		labelOptionsInput.disabled = freeTextToggle.checked;
	}
	syncLabelOptionsDisabled();

	freeTextToggle.addEventListener('change', function () {
		syncLabelOptionsDisabled();
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
			.then(() => {
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
	const jumpToCollapse = document.getElementById('jumpToCollapse');
	const jumpToInput = document.getElementById('jumpToInput');
	const jumpToGo = document.getElementById('jumpToGo');
	const progressClickArea = document.getElementById('progressClickArea');
	const saveButton = document.getElementById('saveButton');
	const pageInfo = document.getElementById('pageInfo');
	const progressBar = document.getElementById('progressBar');
	const clipGrid = document.getElementById('clipGrid');

	prevButton.addEventListener('click', prevPage);
	nextButton.addEventListener('click', nextPage);
	// Auto-focus input when collapse opens
	jumpToCollapse.addEventListener('shown.bs.collapse', () => {
		jumpToInput.focus();
	});
	jumpToCollapse.addEventListener('hidden.bs.collapse', () => {
		jumpToInput.value = '';
	});

	// Handle Go button click and Enter key
	jumpToGo.addEventListener('click', handleJumpToPage);
	jumpToInput.addEventListener('keydown', (e) => {
		if (e.key === 'Enter') {
			e.preventDefault();
			handleJumpToPage();
		} else if (e.key === 'Escape') {
			bootstrap.Collapse.getInstance(jumpToCollapse)?.hide();
		}
	});

	// Clicking the progress bar opens the jump-to input
	progressClickArea.addEventListener('click', () => {
		const bsCollapse = bootstrap.Collapse.getOrCreateInstance(jumpToCollapse);
		bsCollapse.show();
	});
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
		if (currentPage < totalPages - 1) pages.push(currentPage + 1); // prioritise next
		if (currentPage > 0) pages.push(currentPage - 1);
		pages.forEach(page => {
			if (prerenderPromises.has(page) || domCache.has(page)) return;
			const promise = getCachedOrFetch(page).then(data => {
				if (Math.abs(page - currentPage) > 1) return; // stale after navigation
				if (!domCache.has(page)) {
					prerenderDom(page, data);
				}
			}).catch(() => {});
			prerenderPromises.set(page, promise);
			promise.finally(() => prerenderPromises.delete(page));
		});
	}

	function prerenderDom(page, data) {
		const fragment = document.createDocumentFragment();
		const links = [];
		const isNext = page === currentPage + 1;
		data.clips.forEach((clip, index) => {
			const wrapper = document.createElement('template');
			wrapper.innerHTML = videoCardTemplate(clip, index).trim();
			const el = wrapper.content.firstChild;
			const video = el.querySelector('video');
			if (video) {
				video.removeAttribute('autoplay');
				// Preload (high priority) for next page, prefetch (low) otherwise
				const link = document.createElement('link');
				link.rel = isNext ? 'preload' : 'prefetch';
				if (isNext) link.as = 'video';
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

	function swapFromDomCache() {
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
		clipGrid.style.minHeight = '';
		preloadAdjacentPages();
	}

	function fetchClips() {
		// Try DOM cache first (instant swap)
		if (domCache.has(currentPage) && pageCache.has(currentPage)) {
			swapFromDomCache();
			return;
		}

		// If a prerender is already in-flight for this page, wait for it
		const pending = prerenderPromises.get(currentPage);
		if (pending) {
			const gen = navGeneration;
			pending.then(() => {
				if (gen !== navGeneration) return; // stale navigation
				if (domCache.has(currentPage) && pageCache.has(currentPage)) {
					swapFromDomCache();
				} else {
					fetchClipsFallback();
				}
			});
			return;
		}

		fetchClipsFallback();
	}

	function markDisplayedClipsReviewed() {
		const unreviewedPaths = currentClips
			.filter(c => c.clip_reviewed !== 'reviewed')
			.map(c => c.avi_path);
		if (unreviewedPaths.length === 0) return;

		// Update local state synchronously (before currentPage changes)
		currentClips.forEach(clip => {
			clip.clip_reviewed = 'reviewed';
		});
		syncClipsToCache();

		// Update DOM so saveCurrentDom captures the reviewed state
		clipGrid.querySelectorAll('.card-body:not(.reviewed)').forEach(el => {
			el.classList.add('reviewed');
		});

		// Fire-and-forget POST to server
		axios.post('/mark_reviewed', unreviewedPaths).catch(() => {});
	}

	function fetchClipsFallback() {
		// Fall back to JSON cache or network fetch
		const gen = navGeneration;
		getCachedOrFetch(currentPage).then(data => {
			if (gen !== navGeneration) return; // stale navigation
			applyPageData(data);
			updateUI();
			preloadAdjacentPages();
		}).catch(() => {
			if (gen !== navGeneration) return;
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
			let extraOption = '';
			if (clip.comment && !labelOptions.includes(clip.comment)) {
				const escaped = escapeHtml(clip.comment);
				extraOption = `<option value="${escaped}" selected>${escaped}</option>`;
			}
			commentHtml = `<select id="${commentId}" class="form-select">${extraOption}${optionsHtml}</select>`;
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

	function navigateToPage(page) {
		markDisplayedClipsReviewed();
		saveComments({ silent: true });
		clipGrid.style.minHeight = clipGrid.offsetHeight + 'px';
		saveCurrentDom();
		currentPage = page;
		navGeneration++;
		updateUrlParams();
		fetchClips();
	}

	function nextPage() {
		if (currentPage < totalPages - 1) navigateToPage(currentPage + 1);
	}

	function prevPage() {
		if (currentPage > 0) navigateToPage(currentPage - 1);
	}

	function goToPage(page) {
		if (page >= 0 && page <= (totalPages - 1)) {
			navigateToPage(page);
		} else {
			showAlert('Page number is not in range.', 'danger');
		}
	}

	function handleJumpToPage() {
		const raw = jumpToInput.value.trim();
		if (!/^\d+$/.test(raw)) {
			showAlert('Invalid page number.', 'danger');
			return;
		}
		const page = parseInt(raw) - 1;
		if (page >= 0 && page <= (totalPages - 1)) {
			bootstrap.Collapse.getInstance(jumpToCollapse)?.hide();
			goToPage(page);
		} else {
			showAlert('Page number is not in range.', 'danger');
		}
	}

	const autoSaveIndicator = document.getElementById('autoSaveIndicator');

	function showAutoSaveIndicator() {
		const timeStr = new Date().toLocaleTimeString('en-GB', { hour12: false });
		autoSaveIndicator.style.visibility = 'visible';
		const tooltip = bootstrap.Tooltip.getInstance(autoSaveIndicator);
		if (tooltip) tooltip.setContent({ '.tooltip-inner': `Auto-saved at ${timeStr}` });
	}

	function saveComments({ silent = false } = {}) {
		if (currentClips.length === 0) return Promise.resolve();

		const comments = currentClips.map((clip, index) => {
			const el = document.getElementById(`comment-${index}`);
			const comment = el ? el.value : '';
			clip.comment = comment;
			return { avi_path: clip.avi_path, comment };
		});

		syncClipsToCache();

		return axios.post('/save_comments', comments)
			.then(response => {
				if (silent) {
					showAutoSaveIndicator();
				} else {
					const dbPath = response.data.db_path;
					showAlert(`Comments saved to ${dbPath}`);
				}
			})
			.catch(() => {
				if (!silent) showAlert('Error saving comments', 'danger');
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

		// Set up fade-out and removal, pausing while hovered
		let hovered = false;
		let timer = setTimeout(dismissAlert, 3000);
		alert.addEventListener('mouseenter', () => {
			hovered = true;
			clearTimeout(timer);
		});
		alert.addEventListener('mouseleave', () => {
			hovered = false;
			timer = setTimeout(dismissAlert, 1000);
		});
		function dismissAlert() {
			if (hovered) return;
			alert.classList.remove('show');
			alert.addEventListener('transitionend', () => {
				alert.remove();
			});
		}
	}

	function updatePageInfo() {
		pageInfo.textContent = `Page ${currentPage + 1} of ${totalPages} (clips ${currentPage * clipsPerPage + 1}–${Math.min((currentPage + 1) * clipsPerPage, totalClips)} of ${totalClips})`;
		const progress = totalPages > 0 ? ((currentPage + 1) / totalPages) * 100 : 0;
		progressBar.style.width = `${progress}% `;
		prevButton.disabled = currentPage === 0;
		nextButton.disabled = currentPage === totalPages - 1;
		jumpToInput.placeholder = `1–${totalPages}`;
	}

	function updateUI() {
		updatePageInfo();

		releaseVideos(clipGrid);
		clipGrid.innerHTML = '';
		currentClips.forEach((clip, index) => {
			const clipHtml = videoCardTemplate(clip, index);
			clipGrid.insertAdjacentHTML('beforeend', clipHtml);
		});
		clipGrid.style.minHeight = '';
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
