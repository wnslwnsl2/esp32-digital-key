#pragma once

#include <stdint.h>
#include "esp_err.h"

typedef enum {
    DK_ZONE_NONE      = 0,  /* no connection */
    DK_ZONE_FAR       = 1,  /* RSSI < -80 dBm */
    DK_ZONE_NEAR      = 2,  /* -80 ~ -55 dBm */
    DK_ZONE_IMMEDIATE = 3,  /* > -55 dBm */
} dk_zone_t;

#define DK_RSSI_THRESHOLD_FAR       (-80)
#define DK_RSSI_THRESHOLD_IMMEDIATE (-55)
#define DK_RSSI_WINDOW_SIZE 5

/**
 * Start periodic RSSI polling timer (200ms).
 */
esp_err_t DkProximity_Init(void);

/**
 * Get zone for a connection. Uses median of last 5 RSSI samples.
 */
dk_zone_t DkProximity_GetZone(uint16_t conn_handle);

/**
 * Get latest median RSSI for a connection.
 */
int8_t DkProximity_GetRssi(uint16_t conn_handle);
