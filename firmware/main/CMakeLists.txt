idf_component_register(
    SRCS "main.c"
         "dk_service.c"
         "dk_auth.c"
         "dk_button.c"
         "dk_cloud.c"
         "dk_keystore.c"
         "dk_proximity.c"
         "dk_lock.c"
         "dk_led.c"
         "dk_wifi.c"
    INCLUDE_DIRS "."
    REQUIRES bt nvs_flash ble_stack mbedtls esp_timer led_strip esp_driver_gpio
             esp_wifi esp_netif esp_http_client json espressif__mdns
)
