#include "dk_proximity.h"
#include "dk_auth.h"
#include "dk_lock.h"

#include <string.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "host/ble_gap.h"

static const char *TAG = "dk_prox";

/* ── Median filter ───────────────────────────────────────── */

static int8_t median_of_5(int8_t *buf)
{
    /* Simple sorting network for 5 elements */
    int8_t tmp[5];
    memcpy(tmp, buf, 5);

    for (int i = 0; i < 4; i++) {
        for (int j = i + 1; j < 5; j++) {
            if (tmp[j] < tmp[i]) {
                int8_t t = tmp[i];
                tmp[i] = tmp[j];
                tmp[j] = t;
            }
        }
    }
    return tmp[2]; /* median */
}

static dk_zone_t zone_from_rssi(int8_t rssi)
{
    if (rssi > DK_RSSI_THRESHOLD_IMMEDIATE) return DK_ZONE_IMMEDIATE;
    if (rssi > DK_RSSI_THRESHOLD_FAR)       return DK_ZONE_NEAR;
    return DK_ZONE_FAR;
}

/* ── Periodic RSSI polling ───────────────────────────────── */

static esp_timer_handle_t s_timer = NULL;

static void check_auto_lock(dk_conn_state_t *conn, dk_zone_t zone, uint16_t h)
{
    if (conn->auth_state != DK_AUTH_OK) return;

    if (zone == conn->prev_zone) {
        if (conn->zone_hold_count < DK_ZONE_HOLD_TICKS) {
            conn->zone_hold_count++;
        }
    } else {
        /* Zone changed — reset counter */
        conn->prev_zone = zone;
        conn->zone_hold_count = 0;
        return;
    }

    /* Only act when zone has been stable for DK_ZONE_HOLD_TICKS */
    if (conn->zone_hold_count != DK_ZONE_HOLD_TICKS) return;

    dk_lock_state_t lock = DkLock_GetState();
    if (zone == DK_ZONE_IMMEDIATE && lock == DK_LOCK_LOCKED) {
        DkLock_Command(h, 1); /* unlock */
        ESP_LOGI(TAG, "auto-unlock: zone immediate (conn=%d)", h);
    } else if (zone != DK_ZONE_IMMEDIATE && lock == DK_LOCK_UNLOCKED) {
        DkLock_Command(h, 0); /* lock */
        ESP_LOGI(TAG, "auto-lock: left immediate (conn=%d)", h);
    }
}

static void rssi_poll_cb(void *arg)
{
    for (uint16_t h = 0; h < 16; h++) {
        dk_conn_state_t *conn = DkAuth_FindConn(h);
        if (!conn) continue;

        int8_t rssi = 0;
        int rc = ble_gap_conn_rssi(h, &rssi);
        if (rc != 0) continue;

        conn->rssi_buf[conn->rssi_idx % DK_RSSI_WINDOW_SIZE] = rssi;
        conn->rssi_idx++;

        if (conn->rssi_idx >= DK_RSSI_WINDOW_SIZE) {
            dk_zone_t zone = zone_from_rssi(median_of_5(conn->rssi_buf));
            check_auto_lock(conn, zone, h);
        }
    }
}

esp_err_t DkProximity_Init(void)
{
    esp_timer_create_args_t args = {
        .callback = rssi_poll_cb,
        .name = "rssi_poll",
    };
    esp_err_t ret = esp_timer_create(&args, &s_timer);
    if (ret != ESP_OK) return ret;

    ret = esp_timer_start_periodic(s_timer, 200 * 1000); /* 200ms */
    ESP_LOGI(TAG, "RSSI polling started (200ms)");
    return ret;
}

dk_zone_t DkProximity_GetZone(uint16_t conn_handle)
{
    dk_conn_state_t *conn = DkAuth_FindConn(conn_handle);
    if (!conn) return DK_ZONE_NONE;
    if (conn->rssi_idx < DK_RSSI_WINDOW_SIZE) return DK_ZONE_FAR;

    int8_t med = median_of_5(conn->rssi_buf);
    return zone_from_rssi(med);
}

int8_t DkProximity_GetRssi(uint16_t conn_handle)
{
    dk_conn_state_t *conn = DkAuth_FindConn(conn_handle);
    if (!conn || conn->rssi_idx == 0) return -127;

    if (conn->rssi_idx < DK_RSSI_WINDOW_SIZE) {
        return conn->rssi_buf[(conn->rssi_idx - 1) % DK_RSSI_WINDOW_SIZE];
    }
    return median_of_5(conn->rssi_buf);
}
