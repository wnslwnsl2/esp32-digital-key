#include "dk_auth.h"
#include "dk_keystore.h"

#include <string.h>
#include "esp_log.h"
#include "esp_random.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "host/ble_gap.h"
/* Allow direct access to mbedtls_ecp_keypair members (grp, Q, d) */
#define MBEDTLS_ALLOW_PRIVATE_ACCESS
#include "mbedtls/pk.h"
#include "mbedtls/ecp.h"
#include "mbedtls/sha256.h"
#include "mbedtls/entropy.h"
#include "mbedtls/ctr_drbg.h"

static const char *TAG = "dk_auth";

static dk_conn_state_t s_conns[DK_MAX_CONNECTIONS];
static mbedtls_pk_context s_device_pk;
static bool s_device_key_ready = false;

/* ── Device identity key ─────────────────────────────────── */

esp_err_t DkAuth_InitDeviceKey(void)
{
    mbedtls_pk_init(&s_device_pk);

    /* Try to load from NVS */
    nvs_handle_t nvs;
    esp_err_t ret = nvs_open("dk_device", NVS_READWRITE, &nvs);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open dk_device failed: %s", esp_err_to_name(ret));
        return ret;
    }

    uint8_t der_buf[256];
    size_t der_len = sizeof(der_buf);
    ret = nvs_get_blob(nvs, "privkey", der_buf, &der_len);

    if (ret == ESP_OK && der_len > 0) {
        /* Load existing key */
        int rc = mbedtls_pk_parse_key(&s_device_pk, der_buf, der_len,
                                       NULL, 0, NULL, NULL);
        if (rc == 0) {
            s_device_key_ready = true;
            nvs_close(nvs);
            ESP_LOGI(TAG, "device keypair loaded (%zu bytes)", der_len);
            return ESP_OK;
        }
        ESP_LOGW(TAG, "failed to parse stored key (%d), regenerating", rc);
    }

    /* Generate new keypair */
    mbedtls_entropy_context entropy;
    mbedtls_ctr_drbg_context ctr_drbg;
    mbedtls_entropy_init(&entropy);
    mbedtls_ctr_drbg_init(&ctr_drbg);

    int rc = mbedtls_ctr_drbg_seed(&ctr_drbg, mbedtls_entropy_func, &entropy,
                                    (const unsigned char *)"dk_device", 9);
    if (rc != 0) {
        ESP_LOGE(TAG, "ctr_drbg_seed failed: %d", rc);
        goto gen_fail;
    }

    rc = mbedtls_pk_setup(&s_device_pk,
                           mbedtls_pk_info_from_type(MBEDTLS_PK_ECKEY));
    if (rc != 0) {
        ESP_LOGE(TAG, "pk_setup failed: %d", rc);
        goto gen_fail;
    }

    rc = mbedtls_ecp_gen_key(MBEDTLS_ECP_DP_SECP256R1,
                              mbedtls_pk_ec(s_device_pk),
                              mbedtls_ctr_drbg_random, &ctr_drbg);
    if (rc != 0) {
        ESP_LOGE(TAG, "ecp_gen_key failed: %d", rc);
        goto gen_fail;
    }

    /* Serialize to DER and store in NVS */
    rc = mbedtls_pk_write_key_der(&s_device_pk, der_buf, sizeof(der_buf));
    if (rc < 0) {
        ESP_LOGE(TAG, "pk_write_key_der failed: %d", rc);
        goto gen_fail;
    }
    /* mbedtls writes DER from the end of the buffer */
    der_len = (size_t)rc;
    uint8_t *der_start = der_buf + sizeof(der_buf) - der_len;

    ret = nvs_set_blob(nvs, "privkey", der_start, der_len);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "nvs_set_blob failed: %s", esp_err_to_name(ret));
        goto gen_fail;
    }
    nvs_commit(nvs);

    s_device_key_ready = true;
    mbedtls_ctr_drbg_free(&ctr_drbg);
    mbedtls_entropy_free(&entropy);
    nvs_close(nvs);
    ESP_LOGI(TAG, "device keypair generated (%zu bytes)", der_len);
    return ESP_OK;

gen_fail:
    mbedtls_ctr_drbg_free(&ctr_drbg);
    mbedtls_entropy_free(&entropy);
    nvs_close(nvs);
    return ESP_FAIL;
}

esp_err_t DkAuth_GetDevicePubkey(uint8_t *out, size_t *len)
{
    if (!s_device_key_ready) return ESP_ERR_INVALID_STATE;

    mbedtls_ecp_keypair *ec = mbedtls_pk_ec(s_device_pk);
    size_t olen = 0;
    int rc = mbedtls_ecp_point_write_binary(&ec->grp, &ec->Q,
                                             MBEDTLS_ECP_PF_UNCOMPRESSED,
                                             &olen, out, *len);
    if (rc != 0) return ESP_FAIL;
    *len = olen;
    return ESP_OK;
}

esp_err_t DkAuth_SignChallenge(dk_conn_state_t *conn,
                                const uint8_t *challenge, uint16_t challenge_len,
                                uint8_t *out_sig, size_t *out_sig_len)
{
    if (!s_device_key_ready || !conn || !challenge)
        return ESP_ERR_INVALID_ARG;

    /* SHA-256 hash the challenge */
    uint8_t hash[32];
    mbedtls_sha256(challenge, challenge_len, hash, 0);

    /* Sign with device private key */
    mbedtls_entropy_context entropy;
    mbedtls_ctr_drbg_context ctr_drbg;
    mbedtls_entropy_init(&entropy);
    mbedtls_ctr_drbg_init(&ctr_drbg);

    int rc = mbedtls_ctr_drbg_seed(&ctr_drbg, mbedtls_entropy_func, &entropy,
                                    (const unsigned char *)"dk_sign", 7);
    if (rc != 0) {
        mbedtls_ctr_drbg_free(&ctr_drbg);
        mbedtls_entropy_free(&entropy);
        return ESP_FAIL;
    }

    size_t sig_len = 0;
    rc = mbedtls_pk_sign(&s_device_pk, MBEDTLS_MD_SHA256, hash, sizeof(hash),
                          out_sig, *out_sig_len, &sig_len,
                          mbedtls_ctr_drbg_random, &ctr_drbg);

    mbedtls_ctr_drbg_free(&ctr_drbg);
    mbedtls_entropy_free(&entropy);

    if (rc != 0) {
        ESP_LOGW(TAG, "device sign failed: %d", rc);
        return ESP_FAIL;
    }

    *out_sig_len = sig_len;
    ESP_LOGI(TAG, "device challenge signed (%zu bytes) for conn=%d",
             sig_len, conn->conn_handle);
    return ESP_OK;
}

esp_err_t DkAuth_Init(void)
{
    memset(s_conns, 0, sizeof(s_conns));
    for (int i = 0; i < DK_MAX_CONNECTIONS; i++) {
        s_conns[i].conn_handle = 0xFFFF; /* invalid */
    }

    esp_err_t ret = DkAuth_InitDeviceKey();
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "device key init failed (non-fatal): %s",
                 esp_err_to_name(ret));
    }

    ESP_LOGI(TAG, "auth module initialized");
    return ESP_OK;
}

dk_conn_state_t *DkAuth_OnConnect(uint16_t conn_handle)
{
    for (int i = 0; i < DK_MAX_CONNECTIONS; i++) {
        if (s_conns[i].conn_handle == 0xFFFF) {
            memset(&s_conns[i], 0, sizeof(dk_conn_state_t));
            s_conns[i].conn_handle = conn_handle;
            s_conns[i].auth_state = DK_AUTH_CONNECTED;
            ESP_LOGI(TAG, "slot %d assigned to conn=%d", i, conn_handle);
            return &s_conns[i];
        }
    }
    ESP_LOGW(TAG, "no free connection slots");
    return NULL;
}

void DkAuth_OnDisconnect(uint16_t conn_handle)
{
    for (int i = 0; i < DK_MAX_CONNECTIONS; i++) {
        if (s_conns[i].conn_handle == conn_handle) {
            ESP_LOGI(TAG, "slot %d released (conn=%d)", i, conn_handle);
            s_conns[i].conn_handle = 0xFFFF;
            s_conns[i].auth_state = DK_AUTH_DISCONNECTED;
            return;
        }
    }
}

dk_conn_state_t *DkAuth_FindConn(uint16_t conn_handle)
{
    for (int i = 0; i < DK_MAX_CONNECTIONS; i++) {
        if (s_conns[i].conn_handle == conn_handle) {
            return &s_conns[i];
        }
    }
    return NULL;
}

uint8_t DkAuth_ActiveCount(void)
{
    uint8_t count = 0;
    for (int i = 0; i < DK_MAX_CONNECTIONS; i++) {
        if (s_conns[i].conn_handle != 0xFFFF) count++;
    }
    return count;
}

bool DkAuth_IsOwner(dk_conn_state_t *conn)
{
    if (!conn || conn->auth_state != DK_AUTH_OK) return false;
    return DkKeystore_IsOwner(conn->key_id);
}

void DkAuth_DisconnectAll(void)
{
    for (int i = 0; i < DK_MAX_CONNECTIONS; i++) {
        if (s_conns[i].conn_handle != 0xFFFF) {
            ESP_LOGI(TAG, "terminating conn=%d", s_conns[i].conn_handle);
            ble_gap_terminate(s_conns[i].conn_handle,
                              BLE_ERR_REM_USER_CONN_TERM);
        }
    }
}

void DkAuth_DisconnectByKey(const char key_id[16])
{
    for (int i = 0; i < DK_MAX_CONNECTIONS; i++) {
        if (s_conns[i].conn_handle != 0xFFFF &&
            s_conns[i].auth_state == DK_AUTH_OK &&
            memcmp(s_conns[i].key_id, key_id, 16) == 0) {
            ESP_LOGI(TAG, "disconnecting conn=%d (revoked key %.16s)",
                     s_conns[i].conn_handle, key_id);
            ble_gap_terminate(s_conns[i].conn_handle,
                              BLE_ERR_REM_USER_CONN_TERM);
        }
    }
}

/* ── Challenge generation ────────────────────────────────── */

esp_err_t DkAuth_GenerateChallenge(dk_conn_state_t *conn)
{
    if (!conn) return ESP_ERR_INVALID_ARG;

    esp_fill_random(conn->challenge, 32);
    conn->auth_state = DK_AUTH_CHALLENGE;

    ESP_LOGI(TAG, "challenge generated for conn=%d", conn->conn_handle);
    return ESP_OK;
}

/* ── Signature verification ──────────────────────────────── */

esp_err_t DkAuth_VerifyResponse(dk_conn_state_t *conn,
                                 const uint8_t *data, uint16_t len)
{
    if (!conn || !data) return ESP_ERR_INVALID_ARG;
    if (conn->auth_state != DK_AUTH_CHALLENGE) {
        ESP_LOGW(TAG, "verify called in wrong state: %d", conn->auth_state);
        return ESP_ERR_INVALID_STATE;
    }

    /* data = key_id(16) + signature(variable, DER-encoded up to 72 bytes) */
    if (len < 16 + 8) {
        conn->auth_state = DK_AUTH_FAILED;
        return ESP_ERR_INVALID_SIZE;
    }

    char key_id[16];
    memcpy(key_id, data, 16);
    const uint8_t *sig = data + 16;
    size_t sig_len = len - 16;

    /* Look up public key */
    uint8_t pubkey[65];
    size_t pubkey_len = sizeof(pubkey);
    esp_err_t ret = DkKeystore_GetPubkey(key_id, pubkey, &pubkey_len);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "key not found: %.16s", key_id);
        conn->auth_state = DK_AUTH_FAILED;
        return ESP_ERR_NOT_FOUND;
    }

    /* Hash the challenge with SHA-256 */
    uint8_t hash[32];
    mbedtls_sha256(conn->challenge, 32, hash, 0);

    /* Verify ECDSA signature using mbedtls_pk */
    mbedtls_pk_context pk;
    mbedtls_pk_init(&pk);

    int rc = mbedtls_pk_setup(&pk, mbedtls_pk_info_from_type(MBEDTLS_PK_ECKEY));
    if (rc != 0) goto fail;

    mbedtls_ecp_keypair *ec = mbedtls_pk_ec(pk);
    rc = mbedtls_ecp_group_load(&ec->grp, MBEDTLS_ECP_DP_SECP256R1);
    if (rc != 0) goto fail;

    rc = mbedtls_ecp_point_read_binary(&ec->grp, &ec->Q, pubkey, pubkey_len);
    if (rc != 0) goto fail;

    rc = mbedtls_pk_verify(&pk, MBEDTLS_MD_SHA256, hash, sizeof(hash),
                            sig, sig_len);

fail:
    mbedtls_pk_free(&pk);

    if (rc == 0) {
        conn->auth_state = DK_AUTH_OK;
        memcpy(conn->key_id, key_id, 16);
        ESP_LOGI(TAG, "auth OK for conn=%d key=%.16s",
                 conn->conn_handle, key_id);
        return ESP_OK;
    }

    ESP_LOGW(TAG, "signature verification failed: %d", rc);
    conn->auth_state = DK_AUTH_FAILED;
    return ESP_ERR_INVALID_RESPONSE;
}
