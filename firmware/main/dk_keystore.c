#include "dk_keystore.h"

#include <string.h>
#include "esp_log.h"
#include "nvs_flash.h"
#include "nvs.h"

static const char *TAG = "dk_keystore";
#define NVS_NAMESPACE "dk_keys"
#define NVS_KEY_COUNT "count"

static dk_stored_key_t s_keys[DK_MAX_KEYS];
static uint8_t s_key_count = 0;

/* ── NVS persistence ─────────────────────────────────────── */

static esp_err_t save_keys(void)
{
    nvs_handle_t h;
    esp_err_t ret = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h);
    if (ret != ESP_OK) return ret;

    nvs_set_u8(h, NVS_KEY_COUNT, s_key_count);
    nvs_set_blob(h, "keys", s_keys, sizeof(dk_stored_key_t) * s_key_count);
    ret = nvs_commit(h);
    nvs_close(h);
    return ret;
}

static esp_err_t load_keys(void)
{
    nvs_handle_t h;
    esp_err_t ret = nvs_open(NVS_NAMESPACE, NVS_READONLY, &h);
    if (ret == ESP_ERR_NVS_NOT_FOUND) {
        s_key_count = 0;
        return ESP_OK; /* first boot, no keys */
    }
    if (ret != ESP_OK) return ret;

    nvs_get_u8(h, NVS_KEY_COUNT, &s_key_count);
    if (s_key_count > DK_MAX_KEYS) s_key_count = DK_MAX_KEYS;

    size_t blob_len = sizeof(dk_stored_key_t) * s_key_count;
    nvs_get_blob(h, "keys", s_keys, &blob_len);
    nvs_close(h);

    ESP_LOGI(TAG, "loaded %d keys from NVS", s_key_count);
    return ESP_OK;
}

/* ── Public API ──────────────────────────────────────────── */

esp_err_t DkKeystore_Init(void)
{
    memset(s_keys, 0, sizeof(s_keys));
    esp_err_t ret = load_keys();
    ESP_LOGI(TAG, "keystore init: %d registered, %d pending",
             DkKeystore_RegisteredCount(), DkKeystore_PendingCount());
    return ret;
}

esp_err_t DkKeystore_AddKey(const char *key_id,
                             const uint8_t *pubkey, size_t pubkey_len)
{
    if (!key_id || !pubkey || pubkey_len == 0 || pubkey_len > 65) {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_key_count >= DK_MAX_KEYS) {
        ESP_LOGW(TAG, "keystore full");
        return ESP_ERR_NO_MEM;
    }

    /* Check duplicate */
    for (int i = 0; i < s_key_count; i++) {
        if (memcmp(s_keys[i].key_id, key_id, 16) == 0) {
            ESP_LOGW(TAG, "duplicate key_id: %.16s", key_id);
            return ESP_ERR_INVALID_STATE;
        }
    }

    dk_stored_key_t *k = &s_keys[s_key_count];
    memcpy(k->key_id, key_id, 16);
    memcpy(k->pubkey, pubkey, pubkey_len);
    k->pubkey_len = pubkey_len;

    /* First key = owner, auto-approve. Subsequent keys = pending. */
    if (s_key_count == 0) {
        k->pending = false;
        ESP_LOGI(TAG, "owner key registered: %.16s", key_id);
    } else {
        k->pending = true;
        ESP_LOGI(TAG, "pending key added: %.16s", key_id);
    }

    s_key_count++;
    return save_keys();
}

esp_err_t DkKeystore_ApproveKey(const char *key_id)
{
    for (int i = 0; i < s_key_count; i++) {
        if (memcmp(s_keys[i].key_id, key_id, 16) == 0) {
            if (!s_keys[i].pending) return ESP_OK; /* already approved */
            s_keys[i].pending = false;
            ESP_LOGI(TAG, "key approved: %.16s", key_id);
            return save_keys();
        }
    }
    return ESP_ERR_NOT_FOUND;
}

esp_err_t DkKeystore_DeleteKey(const char *key_id)
{
    for (int i = 0; i < s_key_count; i++) {
        if (memcmp(s_keys[i].key_id, key_id, 16) == 0) {
            ESP_LOGI(TAG, "key deleted: %.16s", key_id);
            /* Shift remaining keys */
            for (int j = i; j < s_key_count - 1; j++) {
                s_keys[j] = s_keys[j + 1];
            }
            s_key_count--;
            memset(&s_keys[s_key_count], 0, sizeof(dk_stored_key_t));
            return save_keys();
        }
    }
    return ESP_ERR_NOT_FOUND;
}

esp_err_t DkKeystore_GetPubkey(const char *key_id,
                                uint8_t *out_pubkey, size_t *out_len)
{
    for (int i = 0; i < s_key_count; i++) {
        if (memcmp(s_keys[i].key_id, key_id, 16) == 0 && !s_keys[i].pending) {
            if (*out_len < s_keys[i].pubkey_len) return ESP_ERR_NO_MEM;
            memcpy(out_pubkey, s_keys[i].pubkey, s_keys[i].pubkey_len);
            *out_len = s_keys[i].pubkey_len;
            return ESP_OK;
        }
    }
    return ESP_ERR_NOT_FOUND;
}

bool DkKeystore_IsOwner(const char *key_id)
{
    /* Owner = first registered (index 0), non-pending */
    if (s_key_count == 0) return false;
    return (memcmp(s_keys[0].key_id, key_id, 16) == 0 && !s_keys[0].pending);
}

esp_err_t DkKeystore_EraseAll(void)
{
    nvs_handle_t h;
    esp_err_t ret = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h);
    if (ret != ESP_OK) return ret;

    ret = nvs_erase_all(h);
    nvs_commit(h);
    nvs_close(h);

    s_key_count = 0;
    memset(s_keys, 0, sizeof(s_keys));

    ESP_LOGW(TAG, "all keys erased");
    return ret;
}

uint8_t DkKeystore_RegisteredCount(void)
{
    uint8_t n = 0;
    for (int i = 0; i < s_key_count; i++) {
        if (!s_keys[i].pending) n++;
    }
    return n;
}

uint8_t DkKeystore_PendingCount(void)
{
    uint8_t n = 0;
    for (int i = 0; i < s_key_count; i++) {
        if (s_keys[i].pending) n++;
    }
    return n;
}
