#include "dk_cloud.h"
#include "dk_wifi.h"
#include "dk_keystore.h"
#include "dk_auth.h"
#include "ble_stack.h"

#include <string.h>
#include <stdlib.h>
#include "cJSON.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "dk_cloud";

#define MAX_RESPONSE_SIZE 4096

/* ── HTTP helper ──────────────────────────────────────────── */

typedef struct {
    char  *buf;
    size_t len;
    size_t cap;
} http_buf_t;

static esp_err_t http_event_handler(esp_http_client_event_t *evt)
{
    http_buf_t *b = (http_buf_t *)evt->user_data;
    if (evt->event_id == HTTP_EVENT_ON_DATA && b) {
        if (b->len + evt->data_len < b->cap) {
            memcpy(b->buf + b->len, evt->data, evt->data_len);
            b->len += evt->data_len;
            b->buf[b->len] = '\0';
        }
    }
    return ESP_OK;
}

/* ── Hex string → binary ─────────────────────────────────── */

static int hex_to_bytes(const char *hex, uint8_t *out, size_t max_len)
{
    size_t hex_len = strlen(hex);
    if (hex_len % 2 != 0 || hex_len / 2 > max_len) return -1;
    for (size_t i = 0; i < hex_len / 2; i++) {
        unsigned int byte;
        if (sscanf(hex + i * 2, "%2x", &byte) != 1) return -1;
        out[i] = (uint8_t)byte;
    }
    return (int)(hex_len / 2);
}

/* ── Binary → hex string ─────────────────────────────────── */

static void bytes_to_hex(const uint8_t *in, size_t len, char *out)
{
    for (size_t i = 0; i < len; i++) {
        sprintf(out + i * 2, "%02x", in[i]);
    }
    out[len * 2] = '\0';
}

/* ── Register device public key with dk-server ───────────── */

static void register_device_pubkey(void)
{
    uint8_t pubkey[65];
    size_t  pubkey_len = sizeof(pubkey);
    if (DkAuth_GetDevicePubkey(pubkey, &pubkey_len) != ESP_OK) {
        ESP_LOGW(TAG, "failed to get device pubkey");
        return;
    }

    char ble_addr[18];
    BleStack_GetAddress(ble_addr, sizeof(ble_addr));

    /* Build JSON: {"device_public_key": "04ab..."} */
    char hex[131]; /* 65 bytes * 2 + 1 */
    bytes_to_hex(pubkey, pubkey_len, hex);

    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "device_public_key", hex);
    char *json_str = cJSON_PrintUnformatted(body);
    cJSON_Delete(body);

    /* POST /api/provision/{ble_address}/device-key */
    char url[256];
    snprintf(url, sizeof(url), "%s/api/provision/%s/device-key",
             DK_SERVER_URL, ble_addr);

    esp_http_client_config_t config = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 10000,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, json_str, strlen(json_str));

    esp_err_t err = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    free(json_str);

    if (err == ESP_OK && (status == 200 || status == 201)) {
        ESP_LOGI(TAG, "device pubkey registered with server");
    } else {
        ESP_LOGW(TAG, "device pubkey registration failed: err=%s status=%d",
                 esp_err_to_name(err), status);
    }
}

/* ── Sync logic ───────────────────────────────────────────── */

static void sync_keys(void)
{
    char ble_addr[18];
    BleStack_GetAddress(ble_addr, sizeof(ble_addr));

    /* Build URL */
    char url[256];
    snprintf(url, sizeof(url), "%s/api/provision/%s",
             DK_SERVER_URL, ble_addr);

    /* Allocate response buffer */
    char *resp_buf = malloc(MAX_RESPONSE_SIZE);
    if (!resp_buf) return;

    http_buf_t hbuf = { .buf = resp_buf, .len = 0, .cap = MAX_RESPONSE_SIZE };

    esp_http_client_config_t config = {
        .url = url,
        .event_handler = http_event_handler,
        .user_data = &hbuf,
        .timeout_ms = 10000,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    esp_err_t err = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);

    if (err != ESP_OK || status != 200) {
        ESP_LOGW(TAG, "HTTP request failed: err=%s status=%d",
                 esp_err_to_name(err), status);
        free(resp_buf);
        return;
    }

    /* Parse JSON response */
    cJSON *root = cJSON_Parse(resp_buf);
    free(resp_buf);
    if (!root) {
        ESP_LOGW(TAG, "JSON parse failed");
        return;
    }

    cJSON *keys_arr = cJSON_GetObjectItem(root, "keys");
    if (!cJSON_IsArray(keys_arr)) {
        cJSON_Delete(root);
        return;
    }

    int server_count = cJSON_GetArraySize(keys_arr);
    static int s_last_server_count = -1;
    if (server_count != s_last_server_count) {
        ESP_LOGI(TAG, "server has %d keys for %s", server_count, ble_addr);
        s_last_server_count = server_count;
    }

    /* Track which server key_ids we've seen (for deletion) */
    char server_ids[DK_MAX_KEYS][16];
    int  server_id_count = 0;

    /* Add new keys from server */
    cJSON *item;
    cJSON_ArrayForEach(item, keys_arr) {
        cJSON *j_kid = cJSON_GetObjectItem(item, "key_id");
        cJSON *j_pub = cJSON_GetObjectItem(item, "public_key");
        if (!cJSON_IsString(j_kid) || !cJSON_IsString(j_pub)) continue;

        const char *kid_str = j_kid->valuestring;
        const char *pub_hex = j_pub->valuestring;

        /* Store for deletion pass */
        if (server_id_count < DK_MAX_KEYS) {
            memset(server_ids[server_id_count], 0, 16);
            strncpy(server_ids[server_id_count], kid_str, 16);
            server_id_count++;
        }

        /* Convert public key from hex */
        uint8_t pubkey[65];
        int pubkey_len = hex_to_bytes(pub_hex, pubkey, sizeof(pubkey));
        if (pubkey_len <= 0) continue;

        /* Try to add — will return ESP_ERR_INVALID_STATE if duplicate */
        char kid_padded[16] = {0};
        strncpy(kid_padded, kid_str, 16);
        esp_err_t ret = DkKeystore_AddKey(kid_padded, pubkey, pubkey_len);
        if (ret == ESP_OK) {
            ESP_LOGI(TAG, "added key from cloud: %.16s", kid_padded);
            /* Auto-approve cloud-provisioned keys */
            DkKeystore_ApproveKey(kid_padded);
        }
    }

    /* Delete local keys that are no longer on server.
     * Walk keystore backwards (indices shift on delete) and remove
     * any key_id not found in the server list. */
    for (int i = DkKeystore_Count() - 1; i >= 0; i--) {
        char local_kid[16];
        if (DkKeystore_GetKeyIdAt(i, local_kid) != ESP_OK) continue;

        bool found = false;
        for (int j = 0; j < server_id_count; j++) {
            if (memcmp(local_kid, server_ids[j], 16) == 0) {
                found = true;
                break;
            }
        }
        if (!found) {
            ESP_LOGI(TAG, "revoking key not on server: %.16s", local_kid);
            DkAuth_DisconnectByKey(local_kid);
            DkKeystore_DeleteKey(local_kid);
        }
    }

    cJSON_Delete(root);
}

/* ── FreeRTOS task ────────────────────────────────────────── */

static void cloud_task(void *arg)
{
    /* Wait for WiFi connection before first poll */
    while (!DkWifi_IsConnected()) {
        vTaskDelay(pdMS_TO_TICKS(2000));
    }
    ESP_LOGI(TAG, "WiFi connected, starting cloud key sync");

    /* Register device public key with dk-server (simulates factory provisioning) */
    register_device_pubkey();

    /* Initial sync */
    sync_keys();

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(DK_CLOUD_POLL_INTERVAL_S * 1000));
        if (DkWifi_IsConnected()) {
            sync_keys();
        }
    }
}

esp_err_t DkCloud_Init(void)
{
    if (DK_WIFI_SSID[0] == '\0') {
        ESP_LOGI(TAG, "WiFi not configured, cloud sync disabled");
        return ESP_OK;
    }

    BaseType_t ret = xTaskCreate(cloud_task, "dk_cloud", 8192, NULL, 3, NULL);
    if (ret != pdPASS) {
        ESP_LOGE(TAG, "failed to create cloud task");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "cloud key sync task started (poll every %ds)",
             DK_CLOUD_POLL_INTERVAL_S);
    return ESP_OK;
}
