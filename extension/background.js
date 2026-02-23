// Background script for the extension

// Store popup window ID for closing
let popupWindowId = null;

// Firefox uses 'browser' API, Chrome uses 'chrome' API
const api = typeof browser !== 'undefined' ? browser : chrome;

// Function to get the configured domain
function getFavoritesDomain(callback) {
  api.storage.sync.get(['favoritesDomain'], function(result) {
    const domain = (result && result.favoritesDomain) || 'cloudportal.link';
    callback(domain);
  });
}

// Handle browser action click
api.browserAction.onClicked.addListener(function(tab) {
  // Get the current tab's title and URL
  const title = tab.title || tab.url;
  const url = tab.url;

  // Get current window to position popup relative to it
  api.windows.getCurrent(function(currentWindow) {
    // Center popup over current window
    const popupWidth = 450;
    const popupHeight = 400;
    const left = Math.round(currentWindow.left + (currentWindow.width - popupWidth) / 2);
    const top = currentWindow.top + 150;
    // Get the configured domain and open popup
    getFavoritesDomain(function(domain) {
      const popupUrl = `https://${domain}/favorites/extension?name=${encodeURIComponent(title)}&url=${encodeURIComponent(url)}`;

      if (typeof browser !== 'undefined') {
        // Firefox - uses promises
        api.windows.create({
          url: popupUrl,
          type: 'popup',
          width: popupWidth,
          height: popupHeight,
          focused: true
        }).then(function(win) {
          popupWindowId = win.id;
          return api.windows.update(win.id, { left: left, top: top });
        });
      } else {
        // Chrome - uses callbacks
        api.windows.create({
          url: popupUrl,
          type: 'popup',
          width: popupWidth,
          height: popupHeight,
          focused: true
        }, function(win) {
          popupWindowId = win.id;
          api.windows.update(win.id, { left: left, top: top });
        });
      }
    });
  });
});

// Add context menu item
api.runtime.onInstalled.addListener(function() {
  api.contextMenus.create({
    id: 'add-to-favorites',
    title: 'Add to Favorites',
    contexts: ['page', 'link']
  });

});

// Handle context menu clicks
api.contextMenus.onClicked.addListener(function(info, tab) {
  if (info.menuItemId === 'add-to-favorites') {
    const title = info.linkText || tab.title || tab.url;
    const url = info.linkUrl || tab.url;

    // Get current window to position popup relative to it
    api.windows.getCurrent(function(currentWindow) {
      // Center popup over current window
      const popupWidth = 450;
      const popupHeight = 400;
      const left = Math.round(currentWindow.left + (currentWindow.width - popupWidth) / 2);
      const top = currentWindow.top + 150;

      // Get the configured domain and open popup
      getFavoritesDomain(function(domain) {
        const popupUrl = `https://${domain}/favorites/extension?name=${encodeURIComponent(title)}&url=${encodeURIComponent(url)}`;

        if (typeof browser !== 'undefined') {
          // Firefox - uses promises
          api.windows.create({
            url: popupUrl,
            type: 'popup',
            width: popupWidth,
            height: popupHeight,
            focused: true
          }).then(function(win) {
            popupWindowId = win.id;
            return api.windows.update(win.id, { left: left, top: top });
          });
        } else {
          // Chrome - uses callbacks
          api.windows.create({
            url: popupUrl,
            type: 'popup',
            width: popupWidth,
            height: popupHeight,
            focused: true
          }, function(win) {
            popupWindowId = win.id;
            api.windows.update(win.id, { left: left, top: top });
          });
        }
      });
    });
  }
});

// Listen for messages from the popup to close it

api.runtime.onMessage.addListener(function(request, sender, sendResponse) {
  if (request.action === 'closePopup') {
    if (popupWindowId) {
      if (typeof browser !== 'undefined') {
        api.windows.remove(popupWindowId).then(() => {
          popupWindowId = null;
        }).catch(err => {});
      } else {
        api.windows.remove(popupWindowId, function() {
          popupWindowId = null;
        });
      }
    }
  }
});
