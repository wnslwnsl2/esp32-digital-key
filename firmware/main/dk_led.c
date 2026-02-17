#include "dk_led.h"

#include "esp_log.h"
#include "led_strip.h"

static const char *TAG = "dk_led";

static led_strip_handle_t s_strip;

esp_err_t DkLed_Init(void)
{
    led_strip_config_t strip_cfg = {
        .strip_gpio_num = 48,
        .max_leds = 1,
    };
    led_strip_rmt_config_t rmt_cfg = {
        .resolution_hz = 10 * 1000 * 1000,  /* 10 MHz */
    };

    esp_err_t ret = led_strip_new_rmt_device(&strip_cfg, &rmt_cfg, &s_strip);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "LED strip init failed: %s", esp_err_to_name(ret));
        return ret;
    }

    /* Start OFF (locked) */
    led_strip_clear(s_strip);
    ESP_LOGI(TAG, "LED initialized");
    return ESP_OK;
}

void DkLed_SetLocked(void)
{
    led_strip_clear(s_strip);
}

void DkLed_SetUnlocked(void)
{
    led_strip_set_pixel(s_strip, 0, 0, 32, 0);
    led_strip_refresh(s_strip);
}
