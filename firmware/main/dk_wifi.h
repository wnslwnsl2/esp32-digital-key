#pragma once

#include <stdbool.h>
#include "esp_err.h"

/* ── Cloud config (edit here) ─────────────────────────────── */

#define DK_WIFI_SSID            "KT_GiGA_59AC"          /* empty = WiFi disabled */
#define DK_WIFI_PASSWORD        "dgx96cx101"
#define DK_SERVER_URL           "http://dk-server.local:8100"
#define DK_CLOUD_POLL_INTERVAL_S 2

/**
 * Initialize WiFi station and connect.
 * Skips silently if DK_WIFI_SSID is empty.
 */
esp_err_t DkWifi_Init(void);

/**
 * Check if WiFi station has an IP address.
 */
bool DkWifi_IsConnected(void);
