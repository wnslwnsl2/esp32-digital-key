idf_component_register(
    SRCS "main.c"
         "dk_service.c"
         "dk_auth.c"
         "dk_keystore.c"
         "dk_proximity.c"
         "dk_lock.c"
    INCLUDE_DIRS "."
    REQUIRES bt nvs_flash ble_stack mbedtls esp_timer
)
