#include "ble_stack.h"

#include <string.h>
#include <stdio.h>

#include "esp_log.h"
#include "host/ble_gap.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

static const char *TAG = "ble_stack";

static char s_device_name[20] = "DK-????";
static uint8_t s_own_addr_type;
static uint8_t s_addr_val[6] = {0};
static const struct ble_gatt_svc_def *s_gatt_svcs = NULL;
static uint8_t s_active_connections = 0;

/* Callbacks */
static ble_stack_connect_cb_t    s_on_connect    = NULL;
static ble_stack_disconnect_cb_t s_on_disconnect = NULL;
static ble_stack_subscribe_cb_t  s_on_subscribe  = NULL;

void ble_store_config_init(void);

void BleStack_SetConnectCb(ble_stack_connect_cb_t cb)    { s_on_connect = cb; }
void BleStack_SetDisconnectCb(ble_stack_disconnect_cb_t cb) { s_on_disconnect = cb; }
void BleStack_SetSubscribeCb(ble_stack_subscribe_cb_t cb) { s_on_subscribe = cb; }

void BleStack_GetAddress(char *buf, size_t len)
{
    snprintf(buf, len, "%02X:%02X:%02X:%02X:%02X:%02X",
             s_addr_val[5], s_addr_val[4], s_addr_val[3],
             s_addr_val[2], s_addr_val[1], s_addr_val[0]);
}

/* ── Advertising ─────────────────────────────────────────── */

void BleStack_StartAdvertising(void)
{
    if (s_active_connections >= CONFIG_BT_NIMBLE_MAX_CONNECTIONS) {
        ESP_LOGI(TAG, "max connections reached, skip advertising");
        return;
    }

    struct ble_hs_adv_fields adv = {0};
    adv.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    adv.name = (uint8_t *)s_device_name;
    adv.name_len = strlen(s_device_name);
    adv.name_is_complete = 1;
    adv.tx_pwr_lvl = BLE_HS_ADV_TX_PWR_LVL_AUTO;
    adv.tx_pwr_lvl_is_present = 1;

    int rc = ble_gap_adv_set_fields(&adv);
    if (rc != 0) {
        ESP_LOGE(TAG, "adv_set_fields failed: %d", rc);
        return;
    }

    struct ble_gap_adv_params params = {0};
    params.conn_mode = BLE_GAP_CONN_MODE_UND;
    params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    params.itvl_min = BLE_GAP_ADV_ITVL_MS(100);
    params.itvl_max = BLE_GAP_ADV_ITVL_MS(150);

    rc = ble_gap_adv_start(s_own_addr_type, NULL, BLE_HS_FOREVER, &params,
                           BleStack_GapEventHandler, NULL);
    if (rc != 0 && rc != BLE_HS_EALREADY) {
        ESP_LOGE(TAG, "adv_start failed: %d", rc);
        return;
    }
    ESP_LOGI(TAG, "advertising started (%s)", s_device_name);
}

/* ── GAP event handler (multi-connection) ────────────────── */

int BleStack_GapEventHandler(struct ble_gap_event *event, void *arg)
{
    int rc = 0;

    switch (event->type) {

    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status == 0) {
            s_active_connections++;
            ESP_LOGI(TAG, "connected; conn_handle=%d (active=%d)",
                     event->connect.conn_handle, s_active_connections);

            if (s_on_connect) {
                s_on_connect(event->connect.conn_handle);
            }

            /* Continue advertising if slots available */
            BleStack_StartAdvertising();
        } else {
            ESP_LOGW(TAG, "connect failed; status=%d", event->connect.status);
            BleStack_StartAdvertising();
        }
        break;

    case BLE_GAP_EVENT_DISCONNECT:
        if (s_active_connections > 0) s_active_connections--;
        ESP_LOGI(TAG, "disconnected; conn_handle=%d reason=%d (active=%d)",
                 event->disconnect.conn.conn_handle,
                 event->disconnect.reason,
                 s_active_connections);

        if (s_on_disconnect) {
            s_on_disconnect(event->disconnect.conn.conn_handle,
                            event->disconnect.reason);
        }

        BleStack_StartAdvertising();
        break;

    case BLE_GAP_EVENT_ADV_COMPLETE:
        ESP_LOGI(TAG, "adv complete; reason=%d", event->adv_complete.reason);
        BleStack_StartAdvertising();
        break;

    case BLE_GAP_EVENT_SUBSCRIBE:
        ESP_LOGI(TAG, "subscribe; conn=%d attr=%d notify=%d",
                 event->subscribe.conn_handle,
                 event->subscribe.attr_handle,
                 event->subscribe.cur_notify);

        if (s_on_subscribe) {
            s_on_subscribe(event->subscribe.conn_handle,
                           event->subscribe.attr_handle,
                           event->subscribe.cur_notify);
        }
        break;

    case BLE_GAP_EVENT_MTU:
        ESP_LOGI(TAG, "mtu update; conn=%d mtu=%d",
                 event->mtu.conn_handle, event->mtu.value);
        break;

    case BLE_GAP_EVENT_NOTIFY_TX:
        /* Frequent, only log errors */
        if (event->notify_tx.status != 0 &&
            event->notify_tx.status != BLE_HS_EDONE) {
            ESP_LOGW(TAG, "notify_tx error; status=%d", event->notify_tx.status);
        }
        break;

    case BLE_GAP_EVENT_CONN_UPDATE:
        ESP_LOGI(TAG, "conn_update; status=%d", event->conn_update.status);
        break;

    default:
        ESP_LOGD(TAG, "gap event: %d", event->type);
        break;
    }

    return rc;
}

/* ── GATT registration callback ──────────────────────────── */

static void gatt_svr_register_cb(struct ble_gatt_register_ctxt *ctxt, void *arg)
{
    switch (ctxt->op) {
    case BLE_GATT_REGISTER_OP_SVC:
        ESP_LOGD(TAG, "svc registered: handle=%d", ctxt->svc.handle);
        break;
    case BLE_GATT_REGISTER_OP_CHR:
        ESP_LOGD(TAG, "chr registered: def_handle=%d val_handle=%d",
                 ctxt->chr.def_handle, ctxt->chr.val_handle);
        break;
    case BLE_GATT_REGISTER_OP_DSC:
        ESP_LOGD(TAG, "dsc registered: handle=%d", ctxt->dsc.handle);
        break;
    default:
        break;
    }
}

/* ── Stack sync / reset ──────────────────────────────────── */

static void on_stack_sync(void)
{
    int rc = ble_hs_util_ensure_addr(0);
    if (rc != 0) {
        ESP_LOGE(TAG, "no BT address available");
        return;
    }

    rc = ble_hs_id_infer_auto(0, &s_own_addr_type);
    if (rc != 0) {
        ESP_LOGE(TAG, "infer_auto failed: %d", rc);
        return;
    }

    rc = ble_hs_id_copy_addr(s_own_addr_type, s_addr_val, NULL);
    if (rc != 0) {
        ESP_LOGE(TAG, "copy_addr failed: %d", rc);
        return;
    }

    /* Build device name "DK-XXXX" from last 2 bytes of address */
    snprintf(s_device_name, sizeof(s_device_name), "DK-%02X%02X",
             s_addr_val[1], s_addr_val[0]);

    ESP_LOGI(TAG, "BT addr: %02X:%02X:%02X:%02X:%02X:%02X → %s",
             s_addr_val[5], s_addr_val[4], s_addr_val[3],
             s_addr_val[2], s_addr_val[1], s_addr_val[0],
             s_device_name);

    BleStack_StartAdvertising();
}

static void on_stack_reset(int reason)
{
    ESP_LOGW(TAG, "stack reset; reason=%d", reason);
}

/* ── NimBLE host task ────────────────────────────────────── */

static void nimble_host_task(void *param)
{
    ESP_LOGI(TAG, "NimBLE host task started");
    nimble_port_run();   /* blocks until nimble_port_stop() */
    vTaskDelete(NULL);
}

/* ── Public init ─────────────────────────────────────────── */

esp_err_t BleStack_Init(const struct ble_gatt_svc_def *gatt_svcs)
{
    s_gatt_svcs = gatt_svcs;

    esp_err_t ret = nimble_port_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "nimble_port_init failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ble_store_config_init();

    /* GAP */
    ble_svc_gap_init();
    ble_svc_gatt_init();

    /* Register GATT services */
    int rc = ble_gatts_count_cfg(gatt_svcs);
    if (rc != 0) {
        ESP_LOGE(TAG, "gatts_count_cfg failed: %d", rc);
        return ESP_FAIL;
    }
    rc = ble_gatts_add_svcs(gatt_svcs);
    if (rc != 0) {
        ESP_LOGE(TAG, "gatts_add_svcs failed: %d", rc);
        return ESP_FAIL;
    }

    /* Host config */
    ble_hs_cfg.reset_cb = on_stack_reset;
    ble_hs_cfg.sync_cb = on_stack_sync;
    ble_hs_cfg.gatts_register_cb = gatt_svr_register_cb;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;

    /* Just Works pairing (no PIN, no bonding) */
    ble_hs_cfg.sm_io_cap = BLE_HS_IO_NO_INPUT_OUTPUT;
    ble_hs_cfg.sm_bonding = 0;
    ble_hs_cfg.sm_mitm = 0;
    ble_hs_cfg.sm_sc = 1;

    xTaskCreate(nimble_host_task, "nimble", 8 * 1024, NULL, 5, NULL);

    ESP_LOGI(TAG, "BLE stack initialized");
    return ESP_OK;
}
