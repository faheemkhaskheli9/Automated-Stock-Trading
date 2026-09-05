const syncForm = document.getElementById('sync-form');
if (syncForm) {
  syncForm.addEventListener('submit', (event) => {
    const historyForm = document.getElementById('history-form');
    if (!historyForm.reportValidity()) {
      event.preventDefault();
      return;
    }
    for (const name of ['symbol', 'start', 'end']) {
      syncForm.elements[name].value = historyForm.elements[name].value;
    }
    const button = document.getElementById('fetch-button');
    button.disabled = true;
    button.textContent = 'Fetching & saving…';
  });
}
