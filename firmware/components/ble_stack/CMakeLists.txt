idf_component_register(
    SRCS "src/ble_stack.c"
    INCLUDE_DIRS "include"
    REQUIRES bt nvs_flash
)
