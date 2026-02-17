#include "dk_auth.h"
#include "dk_button.h"
#include "dk_keystore.h"
#include "dk_led.h"
#include "dk_lock.h"
#include "dk_proximity.h"
#include "dk_service.h"
#include "ble_stack.h"

#include "esp_log.h"
#include "nvs_flash.h"

static const char *TAG = "main";

/* ── BLE callbacks ───────────────────────────────────────── */

static void on_connect(uint16_t conn_handle)
{
    DkAuth_OnConnect(conn_handle);
}

static void on_disconnect(uint16_t conn_handle, int reason)
{
    DkAuth_OnDisconnect(conn_handle);
}

static void on_subscribe(uint16_t conn_handle, uint16_t attr_handle,
                          uint8_t cur_notify)
{
    dk_conn_state_t *conn = DkAuth_FindConn(conn_handle);
    if (conn) {
        conn->status_subscribed = cur_notify ? true : false;
    }
}

/* ── app_main ────────────────────────────────────────────── */

void app_main(void)
{
    /* NVS init (required for NimBLE + keystore) */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
        ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        ret = nvs_flash_init();
    }
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "NVS init failed: %s", esp_err_to_name(ret));
        return;
    }

    /* Initialize modules */
    DkAuth_Init();
    DkKeystore_Init();
    DkLock_Init();
    DkLed_Init();

    /* BLE stack + GATT service */
    BleStack_SetConnectCb(on_connect);
    BleStack_SetDisconnectCb(on_disconnect);
    BleStack_SetSubscribeCb(on_subscribe);

    ret = BleStack_Init(DkService_GetDefs());
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "BLE init failed: %s", esp_err_to_name(ret));
        return;
    }

    /* Start RSSI polling + status notify */
    DkProximity_Init();
    DkService_StartStatusTimer();

    /* Factory reset button (GPIO 0 long press) */
    DkButton_Init();

    ESP_LOGI(TAG, "Digital Key system ready");
}
