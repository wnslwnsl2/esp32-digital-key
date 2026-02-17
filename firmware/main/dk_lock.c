#include "dk_lock.h"
#include "dk_auth.h"
#include "dk_proximity.h"

#include "esp_log.h"

static const char *TAG = "dk_lock";

static dk_lock_state_t s_state = DK_LOCK_LOCKED;

esp_err_t DkLock_Init(void)
{
    s_state = DK_LOCK_LOCKED;
    ESP_LOGI(TAG, "lock initialized (locked)");
    return ESP_OK;
}

dk_lock_state_t DkLock_GetState(void)
{
    return s_state;
}

esp_err_t DkLock_Command(uint16_t conn_handle, uint8_t cmd)
{
    dk_conn_state_t *conn = DkAuth_FindConn(conn_handle);
    if (!conn) {
        ESP_LOGW(TAG, "unknown connection: %d", conn_handle);
        return ESP_ERR_NOT_FOUND;
    }

    /* Must be authenticated */
    if (conn->auth_state != DK_AUTH_OK) {
        ESP_LOGW(TAG, "not authenticated (conn=%d state=%d)",
                 conn_handle, conn->auth_state);
        return ESP_ERR_INVALID_STATE;
    }

    if (cmd == 1) {
        /* Unlock: require NEAR or IMMEDIATE zone */
        dk_zone_t zone = DkProximity_GetZone(conn_handle);
        if (zone < DK_ZONE_NEAR) {
            ESP_LOGW(TAG, "unlock denied: zone=%d (conn=%d)", zone, conn_handle);
            return ESP_ERR_INVALID_STATE;
        }
        s_state = DK_LOCK_UNLOCKED;
        ESP_LOGI(TAG, "UNLOCKED by conn=%d", conn_handle);
    } else {
        /* Lock: no proximity requirement */
        s_state = DK_LOCK_LOCKED;
        ESP_LOGI(TAG, "LOCKED by conn=%d", conn_handle);
    }

    return ESP_OK;
}
