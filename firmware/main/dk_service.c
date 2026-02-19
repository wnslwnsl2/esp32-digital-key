#include "dk_service.h"
#include "dk_auth.h"
#include "dk_keystore.h"
#include "dk_proximity.h"
#include "dk_lock.h"

#include <string.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "host/ble_hs.h"
#include "host/ble_uuid.h"
#include "os/os_mbuf.h"

static const char *TAG = "dk_svc";

/* ── UUID helpers ────────────────────────────────────────── */

#define DK_CHR_UUID128(last_byte) \
    BLE_UUID128_INIT(0xbc, 0x9a, 0x78, 0x56, 0x34, 0x12, \
                     0x34, 0x12, 0x34, 0x12, 0x34, 0x12, \
                     0x78, 0x56, 0x34, (last_byte))

static const ble_uuid128_t s_svc_uuid       = BLE_UUID128_INIT(DK_SVC_UUID);
static const ble_uuid128_t s_auth_state_uuid = DK_CHR_UUID128(0x01);
static const ble_uuid128_t s_challenge_uuid  = DK_CHR_UUID128(0x02);
static const ble_uuid128_t s_response_uuid   = DK_CHR_UUID128(0x03);
static const ble_uuid128_t s_status_uuid     = DK_CHR_UUID128(0x06);
static const ble_uuid128_t s_key_mgmt_uuid       = DK_CHR_UUID128(0x07);
static const ble_uuid128_t s_device_pubkey_uuid  = DK_CHR_UUID128(0x08);
static const ble_uuid128_t s_device_auth_uuid    = DK_CHR_UUID128(0x09);

/* Value handles for notify */
static uint16_t s_auth_state_handle;
static uint16_t s_status_handle;

/* ── System Status packed struct ─────────────────────────── */

typedef struct __attribute__((packed)) {
    uint8_t  auth_state;
    uint8_t  zone_level;
    int8_t   rssi;
    uint8_t  lock_state;
    uint8_t  registered_keys;
    uint8_t  pending_keys;
    uint8_t  reserved[2];
} system_status_t;

/* ── Characteristic access callbacks ─────────────────────── */

static int auth_state_access(uint16_t conn_handle, uint16_t attr_handle,
                              struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    if (ctxt->op != BLE_GATT_ACCESS_OP_READ_CHR) return BLE_ATT_ERR_REQ_NOT_SUPPORTED;

    dk_conn_state_t *conn = DkAuth_FindConn(conn_handle);
    uint8_t state = conn ? (uint8_t)conn->auth_state : 0;
    os_mbuf_append(ctxt->om, &state, 1);
    return 0;
}

static int challenge_access(uint16_t conn_handle, uint16_t attr_handle,
                             struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    if (ctxt->op != BLE_GATT_ACCESS_OP_READ_CHR) return BLE_ATT_ERR_REQ_NOT_SUPPORTED;

    dk_conn_state_t *conn = DkAuth_FindConn(conn_handle);
    if (!conn) return BLE_ATT_ERR_UNLIKELY;

    DkAuth_GenerateChallenge(conn);
    os_mbuf_append(ctxt->om, conn->challenge, 32);
    return 0;
}

static int response_access(uint16_t conn_handle, uint16_t attr_handle,
                            struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    if (ctxt->op != BLE_GATT_ACCESS_OP_WRITE_CHR) return BLE_ATT_ERR_REQ_NOT_SUPPORTED;

    uint16_t len = OS_MBUF_PKTLEN(ctxt->om);
    uint8_t buf[128];
    if (len > sizeof(buf)) return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;

    os_mbuf_copydata(ctxt->om, 0, len, buf);

    dk_conn_state_t *conn = DkAuth_FindConn(conn_handle);
    if (!conn) return BLE_ATT_ERR_UNLIKELY;

    esp_err_t ret = DkAuth_VerifyResponse(conn, buf, len);

    /* Notify auth state change */
    uint8_t state = (uint8_t)conn->auth_state;
    struct os_mbuf *om = ble_hs_mbuf_from_flat(&state, 1);
    if (om) {
        ble_gatts_notify_custom(conn_handle, s_auth_state_handle, om);
    }

    return (ret == ESP_OK) ? 0 : BLE_ATT_ERR_INSUFFICIENT_AUTHEN;
}

static int system_status_access(uint16_t conn_handle, uint16_t attr_handle,
                                 struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    if (ctxt->op != BLE_GATT_ACCESS_OP_READ_CHR) return BLE_ATT_ERR_REQ_NOT_SUPPORTED;

    dk_conn_state_t *conn = DkAuth_FindConn(conn_handle);

    system_status_t st = {0};
    if (conn) {
        st.auth_state = (uint8_t)conn->auth_state;
        st.zone_level = (uint8_t)DkProximity_GetZone(conn_handle);
        st.rssi = DkProximity_GetRssi(conn_handle);
    }
    st.lock_state = (uint8_t)DkLock_GetState();
    st.registered_keys = DkKeystore_RegisteredCount();
    st.pending_keys = DkKeystore_PendingCount();

    os_mbuf_append(ctxt->om, &st, sizeof(st));
    return 0;
}

static int key_mgmt_access(uint16_t conn_handle, uint16_t attr_handle,
                            struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    if (ctxt->op != BLE_GATT_ACCESS_OP_WRITE_CHR) return BLE_ATT_ERR_REQ_NOT_SUPPORTED;

    uint16_t len = OS_MBUF_PKTLEN(ctxt->om);
    if (len != 17) return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN; /* 1 cmd + 16 key_id */

    uint8_t buf[17];
    os_mbuf_copydata(ctxt->om, 0, 17, buf);

    /* Only authenticated owner can manage keys */
    dk_conn_state_t *conn = DkAuth_FindConn(conn_handle);
    if (!conn || !DkAuth_IsOwner(conn)) {
        ESP_LOGW(TAG, "key mgmt denied: not owner (conn=%d)", conn_handle);
        return BLE_ATT_ERR_INSUFFICIENT_AUTHEN;
    }

    uint8_t cmd = buf[0];
    char key_id[16];
    memcpy(key_id, buf + 1, 16);

    esp_err_t ret;
    if (cmd == 0x01) {
        ret = DkKeystore_DeleteKey(key_id);
    } else if (cmd == 0x02) {
        ret = DkKeystore_ApproveKey(key_id);
    } else {
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }

    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "key mgmt cmd=%02x failed: %s", cmd, esp_err_to_name(ret));
        return BLE_ATT_ERR_WRITE_NOT_PERMITTED;
    }
    return 0;
}

static int device_pubkey_access(uint16_t conn_handle, uint16_t attr_handle,
                                struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    if (ctxt->op != BLE_GATT_ACCESS_OP_READ_CHR) return BLE_ATT_ERR_REQ_NOT_SUPPORTED;

    uint8_t pubkey[65];
    size_t len = sizeof(pubkey);
    esp_err_t ret = DkAuth_GetDevicePubkey(pubkey, &len);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "device pubkey not available");
        return BLE_ATT_ERR_UNLIKELY;
    }

    os_mbuf_append(ctxt->om, pubkey, len);
    return 0;
}

static int device_auth_access(uint16_t conn_handle, uint16_t attr_handle,
                               struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    dk_conn_state_t *conn = DkAuth_FindConn(conn_handle);
    if (!conn) return BLE_ATT_ERR_UNLIKELY;

    if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
        /* Client writes 32-byte challenge */
        uint16_t len = OS_MBUF_PKTLEN(ctxt->om);
        if (len != 32) return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;

        os_mbuf_copydata(ctxt->om, 0, 32, conn->device_challenge);
        conn->device_challenge_valid = true;
        ESP_LOGI(TAG, "device challenge received from conn=%d", conn_handle);
        return 0;
    }

    if (ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR) {
        /* Client reads DER signature */
        if (!conn->device_challenge_valid) {
            ESP_LOGW(TAG, "no device challenge pending for conn=%d", conn_handle);
            return BLE_ATT_ERR_UNLIKELY;
        }

        uint8_t sig[128];
        size_t sig_len = sizeof(sig);
        esp_err_t ret = DkAuth_SignChallenge(conn, conn->device_challenge, 32,
                                              sig, &sig_len);
        conn->device_challenge_valid = false;

        if (ret != ESP_OK) {
            ESP_LOGW(TAG, "device sign failed for conn=%d", conn_handle);
            return BLE_ATT_ERR_UNLIKELY;
        }

        os_mbuf_append(ctxt->om, sig, sig_len);
        return 0;
    }

    return BLE_ATT_ERR_REQ_NOT_SUPPORTED;
}

/* ── GATT service table ──────────────────────────────────── */

static const struct ble_gatt_svc_def s_gatt_svcs[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &s_svc_uuid.u,
        .characteristics = (struct ble_gatt_chr_def[]) {
            /* 01: Auth State (Read | Notify) */
            {
                .uuid = &s_auth_state_uuid.u,
                .access_cb = auth_state_access,
                .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY,
                .val_handle = &s_auth_state_handle,
            },
            /* 02: Challenge (Read) */
            {
                .uuid = &s_challenge_uuid.u,
                .access_cb = challenge_access,
                .flags = BLE_GATT_CHR_F_READ,
            },
            /* 03: Response (Write) */
            {
                .uuid = &s_response_uuid.u,
                .access_cb = response_access,
                .flags = BLE_GATT_CHR_F_WRITE,
            },
            /* 06: System Status (Read | Notify) */
            {
                .uuid = &s_status_uuid.u,
                .access_cb = system_status_access,
                .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY,
                .val_handle = &s_status_handle,
            },
            /* 07: Key Management (Write) */
            {
                .uuid = &s_key_mgmt_uuid.u,
                .access_cb = key_mgmt_access,
                .flags = BLE_GATT_CHR_F_WRITE,
            },
            /* 08: Device Public Key (Read) */
            {
                .uuid = &s_device_pubkey_uuid.u,
                .access_cb = device_pubkey_access,
                .flags = BLE_GATT_CHR_F_READ,
            },
            /* 09: Device Auth (Read | Write) */
            {
                .uuid = &s_device_auth_uuid.u,
                .access_cb = device_auth_access,
                .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_WRITE,
            },
            {0}, /* terminator */
        },
    },
    {0}, /* terminator */
};

const struct ble_gatt_svc_def *DkService_GetDefs(void)
{
    return s_gatt_svcs;
}

/* ── Status notify timer (200ms) ─────────────────────────── */

static esp_timer_handle_t s_status_timer = NULL;

static void status_timer_cb(void *arg)
{
    /* Send status to each subscribed connection */
    for (uint16_t h = 0; h < 16; h++) {
        dk_conn_state_t *conn = DkAuth_FindConn(h);
        if (!conn || !conn->status_subscribed) continue;

        system_status_t st = {
            .auth_state = (uint8_t)conn->auth_state,
            .zone_level = (uint8_t)DkProximity_GetZone(h),
            .rssi = DkProximity_GetRssi(h),
            .lock_state = (uint8_t)DkLock_GetState(),
            .registered_keys = DkKeystore_RegisteredCount(),
            .pending_keys = DkKeystore_PendingCount(),
        };

        struct os_mbuf *om = ble_hs_mbuf_from_flat(&st, sizeof(st));
        if (om) {
            ble_gatts_notify_custom(h, s_status_handle, om);
        }
    }
}

esp_err_t DkService_StartStatusTimer(void)
{
    esp_timer_create_args_t args = {
        .callback = status_timer_cb,
        .name = "dk_status",
    };
    esp_err_t ret = esp_timer_create(&args, &s_status_timer);
    if (ret != ESP_OK) return ret;

    ret = esp_timer_start_periodic(s_status_timer, 200 * 1000); /* 200ms */
    ESP_LOGI(TAG, "status notify timer started (200ms)");
    return ret;
}
