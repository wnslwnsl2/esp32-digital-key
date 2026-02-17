#include "dk_auth.h"
#include "dk_keystore.h"

#include <string.h>
#include "esp_log.h"
#include "esp_random.h"
/* Allow direct access to mbedtls_ecp_keypair members (grp, Q) */
#define MBEDTLS_ALLOW_PRIVATE_ACCESS
#include "mbedtls/pk.h"
#include "mbedtls/ecp.h"
#include "mbedtls/sha256.h"

static const char *TAG = "dk_auth";

static dk_conn_state_t s_conns[DK_MAX_CONNECTIONS];

esp_err_t DkAuth_Init(void)
{
    memset(s_conns, 0, sizeof(s_conns));
    for (int i = 0; i < DK_MAX_CONNECTIONS; i++) {
        s_conns[i].conn_handle = 0xFFFF; /* invalid */
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
