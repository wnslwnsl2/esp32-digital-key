#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

#define DK_MAX_KEYS 8

typedef struct {
    char    key_id[16];
    uint8_t pubkey[65];    /* uncompressed P-256: 0x04 + X(32) + Y(32) */
    uint8_t pubkey_len;
    bool    pending;       /* true = awaiting owner approval */
} dk_stored_key_t;

esp_err_t DkKeystore_Init(void);

/** Add a public key. If no keys exist, auto-approve (owner). */
esp_err_t DkKeystore_AddKey(const char *key_id,
                             const uint8_t *pubkey, size_t pubkey_len);

/** Approve a pending key (owner only). */
esp_err_t DkKeystore_ApproveKey(const char *key_id);

/** Delete a key. */
esp_err_t DkKeystore_DeleteKey(const char *key_id);

/** Find key by ID and return its public key. */
esp_err_t DkKeystore_GetPubkey(const char *key_id,
                                uint8_t *out_pubkey, size_t *out_len);

/** Check if key_id is the first registered key (owner). */
bool DkKeystore_IsOwner(const char *key_id);

/** Erase all keys (factory reset). */
esp_err_t DkKeystore_EraseAll(void);

uint8_t DkKeystore_RegisteredCount(void);
uint8_t DkKeystore_PendingCount(void);

/** Total key count (registered + pending). */
uint8_t DkKeystore_Count(void);

/** Get key_id at index (0-based). Returns ESP_ERR_NOT_FOUND if out of range. */
esp_err_t DkKeystore_GetKeyIdAt(uint8_t index, char out_key_id[16]);
