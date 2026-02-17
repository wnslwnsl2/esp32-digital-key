#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#define DK_MAX_CONNECTIONS 3

typedef enum {
    DK_AUTH_DISCONNECTED = 0,
    DK_AUTH_CONNECTED    = 1,
    DK_AUTH_CHALLENGE    = 2,
    DK_AUTH_OK           = 3,
    DK_AUTH_FAILED       = 4,
} dk_auth_state_t;

typedef struct {
    uint16_t        conn_handle;
    dk_auth_state_t auth_state;
    uint8_t         challenge[32];
    char            key_id[16];
    int8_t          rssi_buf[5];
    uint8_t         rssi_idx;
    bool            status_subscribed;
    bool            auth_subscribed;
    uint8_t         prev_zone;
    uint8_t         zone_hold_count;
} dk_conn_state_t;

esp_err_t DkAuth_Init(void);

/** Per-connection lifecycle */
dk_conn_state_t *DkAuth_OnConnect(uint16_t conn_handle);
void             DkAuth_OnDisconnect(uint16_t conn_handle);
dk_conn_state_t *DkAuth_FindConn(uint16_t conn_handle);

/** Challenge-response */
esp_err_t DkAuth_GenerateChallenge(dk_conn_state_t *conn);
esp_err_t DkAuth_VerifyResponse(dk_conn_state_t *conn,
                                 const uint8_t *data, uint16_t len);

/** Query */
uint8_t DkAuth_ActiveCount(void);
bool    DkAuth_IsOwner(dk_conn_state_t *conn);

/** Terminate all active BLE connections. */
void DkAuth_DisconnectAll(void);
