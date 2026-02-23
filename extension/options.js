// Options page JavaScript
document.addEventListener('DOMContentLoaded', function() {
  const form = document.getElementById('options-form');
  const domainInput = document.getElementById('domain');
  const saveButton = document.getElementById('save');
  const resetButton = document.getElementById('reset');
  const statusDiv = document.getElementById('status');

  // Use browser API for Firefox, chrome API for Chrome
  const api = typeof browser !== 'undefined' ? browser : chrome;

  // Load saved settings
  loadSettings();

  // Save settings
  form.addEventListener('submit', function(e) {
    e.preventDefault();
    saveSettings();
  });

  // Reset to default
  resetButton.addEventListener('click', function() {
    resetToDefault();
  });

  function loadSettings() {
    api.storage.sync.get(['favoritesDomain'], function(result) {
      domainInput.value = result.favoritesDomain || 'cloudportal.link';
    });
  }

  function saveSettings() {
    const domain = domainInput.value.trim();

    if (!domain) {
      showStatus('Please enter a domain', 'error');
      return;
    }

    // Basic domain validation
    if (!isValidDomain(domain)) {
      showStatus('Please enter a valid domain (e.g., cloudportal.link)', 'error');
      return;
    }

    api.storage.sync.set({
      favoritesDomain: domain
    }, function() {
      if (api.runtime.lastError) {
        showStatus('Error saving settings: ' + api.runtime.lastError.message, 'error');
      } else {
        showStatus('Settings saved successfully!', 'success');
      }
    });
  }

  function resetToDefault() {
    domainInput.value = 'cloudportal.link';
    saveSettings();
  }

  function isValidDomain(domain) {
    // Basic domain validation - allows subdomains
    const domainRegex = /^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$/;
    return domainRegex.test(domain);
  }

  function showStatus(message, type) {
    statusDiv.textContent = message;
    statusDiv.className = 'status-message ' + type;

    // Clear status after 3 seconds for success/error messages
    if (type === 'success' || type === 'error') {
      setTimeout(() => {
        statusDiv.textContent = '';
        statusDiv.className = 'status-message';
      }, 3000);
    }
  }
});
