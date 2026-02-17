#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

typedef enum {
    DK_LOCK_LOCKED   = 0,
    DK_LOCK_UNLOCKED = 1,
} dk_lock_state_t;

esp_err_t DkLock_Init(void);

/** Get current global lock state. */
dk_lock_state_t DkLock_GetState(void);

/**
 * Attempt lock/unlock. Checks auth + proximity conditions.
 * @param conn_handle  The requesting connection
 * @param cmd          0=lock, 1=unlock
 * @return ESP_OK on success, ESP_ERR_INVALID_STATE if conditions not met
 */
esp_err_t DkLock_Command(uint16_t conn_handle, uint8_t cmd);
