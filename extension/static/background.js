function enableClickToOpen() {
	chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
}

chrome.runtime.onInstalled.addListener(enableClickToOpen);
enableClickToOpen();
