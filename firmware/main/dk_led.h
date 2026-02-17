#pragma once

#include "esp_err.h"

esp_err_t DkLed_Init(void);
void DkLed_SetLocked(void);    /* LED OFF */
void DkLed_SetUnlocked(void);  /* LED Green */
