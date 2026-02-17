#include "dk_button.h"

#include <string.h>
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "dk_auth.h"
#include "dk_keystore.h"
#include "dk_led.h"
#include "dk_lock.h"

static const char *TAG = "dk_button";

#define BUTTON_GPIO       GPIO_NUM_0
#define POLL_INTERVAL_MS  100
#define LONG_PRESS_TICKS  30   /* 30 × 100ms = 3 seconds */

static esp_timer_handle_t s_timer;
static int s_press_ticks = 0;
static bool s_reset_done = false;

static void factory_reset(void)
{
    ESP_LOGW(TAG, "*** FACTORY RESET ***");

    /* Disconnect all active BLE connections */
    DkAuth_DisconnectAll();

    /* Erase all keys from NVS */
    esp_err_t ret = DkKeystore_EraseAll();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "keystore erase failed: %s", esp_err_to_name(ret));
    }

    /* Restore locked state */
    DkLock_Init();

    /* LED feedback: blue on then off */
    DkLed_SetColor(0, 0, 32);
    vTaskDelay(pdMS_TO_TICKS(1000));
    DkLed_SetLocked();

    ESP_LOGW(TAG, "factory reset complete — all keys erased");
}

static void button_poll_cb(void *arg)
{
    int level = gpio_get_level(BUTTON_GPIO);

    if (level == 0) {
        /* Button pressed (active low) */
        s_press_ticks++;

        /* Solid yellow while held */
        if (!s_reset_done && s_press_ticks >= 2) {
            DkLed_SetColor(32, 24, 0);
        }

        if (s_press_ticks >= LONG_PRESS_TICKS && !s_reset_done) {
            s_reset_done = true;
            factory_reset();
        }
    } else {
        /* Button released */
        if (s_press_ticks > 0 && s_press_ticks < LONG_PRESS_TICKS && !s_reset_done) {
            /* Short press — restore LED to current lock state */
            if (DkLock_GetState() == DK_LOCK_UNLOCKED) {
                DkLed_SetUnlocked();
            } else {
                DkLed_SetLocked();
            }
        }
        s_press_ticks = 0;
        s_reset_done = false;
    }
}

esp_err_t DkButton_Init(void)
{
    /* Configure GPIO 0 as input with internal pull-up */
    gpio_config_t io_cfg = {
        .pin_bit_mask = 1ULL << BUTTON_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t ret = gpio_config(&io_cfg);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "GPIO config failed: %s", esp_err_to_name(ret));
        return ret;
    }

    /* Create polling timer */
    esp_timer_create_args_t timer_args = {
        .callback = button_poll_cb,
        .name = "button_poll",
    };
    ret = esp_timer_create(&timer_args, &s_timer);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "timer create failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = esp_timer_start_periodic(s_timer, POLL_INTERVAL_MS * 1000);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "timer start failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ESP_LOGI(TAG, "button initialized (GPIO %d, 3s long press = factory reset)",
             BUTTON_GPIO);
    return ESP_OK;
}
