/**
 * Fuse Cron Service — Apps Script webhook proxy
 *
 * Deploy: Deploy → New deployment → Web app
 *   Execute as: Me
 *   Who has access: Anyone
 *
 * Paste your Cron Service SERVICE_API_KEY into CALLBACK_SECRET below (optional if
 * you rely on callback_secret from each POST body).
 *
 * Cron Service POSTs JSON to this URL when proxy mode is enabled.
 */

/** Same value as Cron Service SERVICE_API_KEY (Admin → API key). */
var CALLBACK_SECRET = "";

var DEFAULT_MAX_ATTEMPTS = 5;
var DEFAULT_RETRY_BASE_SECONDS = 2;

/**
 * @param {GoogleAppsScript.Events.DoPost} e
 * @return {GoogleAppsScript.Content.TextOutput}
 */
function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var result = callNoneyWithRetries_(data);
    reportCallback_(data, result);
    return jsonOutput_({ ok: true, workflow_id: data.workflow_id, noney_ok: result.success });
  } catch (err) {
    var message = err && err.message ? err.message : String(err);
    try {
      var payload = JSON.parse(e.postData.contents);
      reportCallback_(payload, {
        success: false,
        attempts: 0,
        status_code: null,
        error: "Apps Script error: " + message,
      });
    } catch (ignore) {}
    return jsonOutput_({ ok: false, error: message });
  }
}

/**
 * @param {Object} data
 * @return {{success: boolean, attempts: number, status_code: (number|null), error: (string|null)}}
 */
function callNoneyWithRetries_(data) {
  var url = data.noney_trigger_url;
  var secret = data.noney_trigger_secret;
  var firedAt = data.fired_at || new Date().toISOString();
  var maxAttempts = parseInt(data.max_attempts, 10) || DEFAULT_MAX_ATTEMPTS;
  var baseDelay = parseFloat(data.retry_base_seconds) || DEFAULT_RETRY_BASE_SECONDS;

  if (!url || !secret) {
    return {
      success: false,
      attempts: 0,
      status_code: null,
      error: "Missing noney_trigger_url or noney_trigger_secret",
    };
  }

  var lastCode = null;
  var lastError = null;

  for (var attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      var response = UrlFetchApp.fetch(url, {
        method: "post",
        contentType: "application/json",
        headers: {
          Authorization: "Bearer " + secret,
        },
        payload: JSON.stringify({ fired_at: firedAt }),
        muteHttpExceptions: true,
      });
      lastCode = response.getResponseCode();
      if (lastCode >= 200 && lastCode < 300) {
        return { success: true, attempts: attempt, status_code: lastCode, error: null };
      }
      lastError = response.getContentText().slice(0, 2000);
    } catch (fetchErr) {
      lastError = fetchErr.message || String(fetchErr);
      lastCode = null;
    }

    if (attempt < maxAttempts) {
      Utilities.sleep(Math.round(baseDelay * attempt * 1000));
    }
  }

  return {
    success: false,
    attempts: maxAttempts,
    status_code: lastCode,
    error: lastError || "Unknown error",
  };
}

/**
 * @param {Object} data
 * @param {{success: boolean, attempts: number, status_code: (number|null), error: (string|null)}} result
 */
function reportCallback_(data, result) {
  var callbackUrl = data.callback_url;
  if (!callbackUrl) {
    throw new Error("Missing callback_url in dispatch payload");
  }
  var secret = CALLBACK_SECRET || data.callback_secret || "";
  if (!secret) {
    throw new Error("No callback secret configured");
  }

  var body = {
    dispatch_id: data.dispatch_id,
    success: result.success,
    attempts: result.attempts,
    status_code: result.status_code,
    error: result.error,
  };

  var cb = UrlFetchApp.fetch(callbackUrl, {
    method: "post",
    contentType: "application/json",
    headers: {
      Authorization: "Bearer " + secret,
    },
    payload: JSON.stringify(body),
    muteHttpExceptions: true,
  });

  var code = cb.getResponseCode();
  if (code < 200 || code >= 300) {
    throw new Error("Callback failed HTTP " + code + ": " + cb.getContentText().slice(0, 500));
  }
}

/**
 * @param {Object} obj
 * @return {GoogleAppsScript.Content.TextOutput}
 */
function jsonOutput_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}
