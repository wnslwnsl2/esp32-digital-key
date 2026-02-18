#pragma once

#include "esp_err.h"

/**
 * Start the cloud key sync task.
 * Periodically polls dk-server for the latest key list and
 * adds/removes keys from the local keystore to match.
 */
esp_err_t DkCloud_Init(void);
