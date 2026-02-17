#pragma once

#include "esp_err.h"
#include "host/ble_gatt.h"

/* Service UUID: 12345678-1234-1234-1234-123456789abc */
#define DK_SVC_UUID  0xbc, 0x9a, 0x78, 0x56, 0x34, 0x12, \
                     0x34, 0x12, 0x34, 0x12, 0x34, 0x12, \
                     0x78, 0x56, 0x34, 0x12

/* Characteristic UUIDs (last byte varies: 01..07) */
#define DK_CHR_AUTH_STATE_UUID    0x01
#define DK_CHR_CHALLENGE_UUID     0x02
#define DK_CHR_RESPONSE_UUID      0x03
#define DK_CHR_PROVISION_UUID     0x04
#define DK_CHR_LOCK_CMD_UUID      0x05
#define DK_CHR_SYSTEM_STATUS_UUID 0x06
#define DK_CHR_KEY_MGMT_UUID      0x07

/** Get the GATT service definition table (null-terminated). */
const struct ble_gatt_svc_def *DkService_GetDefs(void);

/** Start the 200ms system status notify timer. */
esp_err_t DkService_StartStatusTimer(void);
