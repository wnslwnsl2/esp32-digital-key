#pragma once

#include "esp_err.h"
#include "host/ble_gap.h"
#include "host/ble_gatt.h"

/**
 * Initialize NimBLE stack, GAP, and GATT server.
 * Starts advertising as "DK-XXXX" where XXXX is last 4 hex digits of BT addr.
 *
 * @param gatt_svcs  Null-terminated GATT service definition array
 * @return ESP_OK on success
 */
esp_err_t BleStack_Init(const struct ble_gatt_svc_def *gatt_svcs);

/**
 * Restart advertising (call after disconnect if multi-conn slots available).
 */
void BleStack_StartAdvertising(void);

/**
 * GAP event handler — forwards connect/disconnect to registered callbacks.
 * Registered automatically by BleStack_Init; also usable as the adv callback.
 */
int BleStack_GapEventHandler(struct ble_gap_event *event, void *arg);

/** Callback types for connect/disconnect hooks */
typedef void (*ble_stack_connect_cb_t)(uint16_t conn_handle);
typedef void (*ble_stack_disconnect_cb_t)(uint16_t conn_handle, int reason);
typedef void (*ble_stack_subscribe_cb_t)(uint16_t conn_handle,
                                         uint16_t attr_handle,
                                         uint8_t cur_notify);

void BleStack_SetConnectCb(ble_stack_connect_cb_t cb);
void BleStack_SetDisconnectCb(ble_stack_disconnect_cb_t cb);
void BleStack_SetSubscribeCb(ble_stack_subscribe_cb_t cb);

/**
 * Get the BLE address as a string "XX:XX:XX:XX:XX:XX".
 * Only valid after BleStack_Init() and stack sync.
 * @param buf  Output buffer (at least 18 bytes)
 * @param len  Buffer size
 */
void BleStack_GetAddress(char *buf, size_t len);
