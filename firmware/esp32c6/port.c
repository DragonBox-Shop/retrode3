/* SPDX-License-Identifier: Apache-2.0 */
/* Retrode3 UART transport; power/reset contract from Letux reference port. */
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>
#include "esp_loader_io.h"
#include "port.h"
#define PWR "/sys/devices/platform/wlan_pwrseq/enable_power"
#define BOOT "/sys/devices/platform/wlan_pwrseq/enable_flashing"
#define MMC "/sys/bus/platform/drivers/jz4740-mmc/"
#define WLAN "13460000.mmc"
static int uart = -1, failed;
static int64_t deadline;
static int64_t now(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) return 0;
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}
static int put(const char *path, const char *value) {
    int fd = open(path, O_WRONLY | O_CLOEXEC);
    if (fd < 0) { perror(path); return -1; }
    size_t size = strlen(value);
    ssize_t n = write(fd, value, size);
    int saved = errno;
    int rc = close(fd);
    if (n != (ssize_t)size || rc) { errno = n < 0 ? saved : EIO; perror(path); return -1; }
    return 0;
}
int retrode_sdio_unbind(void) {
    if (access(MMC WLAN, F_OK) != 0) return errno == ENOENT ? 0 : -1;
    return put(MMC "unbind", WLAN "\n");
}
int retrode_sdio_bind(void) {
    if (access(MMC WLAN, F_OK) == 0) return 0;
    return put(MMC "bind", WLAN "\n");
}
static esp_loader_error_t baud(uint32_t rate) {
    struct termios t;
    if (rate != 115200 || tcgetattr(uart, &t)) return ESP_LOADER_ERROR_FAIL;
    cfmakeraw(&t);
    t.c_cflag &= ~(PARENB | CSTOPB | CSIZE | CRTSCTS);
    t.c_cflag |= CS8 | CLOCAL | CREAD;
    t.c_cc[VMIN] = 0; t.c_cc[VTIME] = 0;
    if (cfsetispeed(&t, B115200) || cfsetospeed(&t, B115200) || tcsetattr(uart, TCSANOW, &t))
        return ESP_LOADER_ERROR_FAIL;
    return ESP_LOADER_SUCCESS;
}
int retrode_port_open(void) {
    uart = open("/dev/ttyS1", O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
    if (uart < 0) { perror("/dev/ttyS1"); return -1; }
    if (baud(115200) != ESP_LOADER_SUCCESS) { retrode_port_close(); return -1; }
    return 0;
}
void retrode_port_close(void) { if (uart >= 0) close(uart); uart = -1; }
int retrode_port_failed(void) { return failed; }
void loader_port_delay_ms(uint32_t ms) {
    struct timespec t = {ms / 1000, (long)(ms % 1000) * 1000000};
    while (nanosleep(&t, &t) && errno == EINTR) {}
}
void loader_port_start_timer(uint32_t ms) { deadline = now() + ms; }
uint32_t loader_port_remaining_time(void) {
    int64_t n = deadline - now(); return n > 0 ? (uint32_t)n : 0;
}
static esp_loader_error_t transfer(uint8_t *buf, uint16_t size, uint32_t timeout, int sending) {
    int64_t end = now() + timeout;
    if (deadline < end) end = deadline;
    size_t off = 0;
    while (off < size) {
        if (failed) return ESP_LOADER_ERROR_FAIL;
        int64_t rem = end - now();
        if (rem <= 0) return ESP_LOADER_ERROR_TIMEOUT;
        struct pollfd p = {uart, sending ? POLLOUT : POLLIN, 0};
        int rc = poll(&p, 1, (int)rem);
        if (rc < 0 && errno == EINTR) continue;
        if (!rc) return ESP_LOADER_ERROR_TIMEOUT;
        if (rc < 0 || (p.revents & (POLLERR | POLLHUP | POLLNVAL))) return ESP_LOADER_ERROR_FAIL;
        ssize_t n = sending ? write(uart, buf + off, size - off) : read(uart, buf + off, size - off);
        if (n < 0 && (errno == EAGAIN || errno == EINTR)) continue;
        if (n <= 0) return ESP_LOADER_ERROR_FAIL;
        off += (size_t)n;
    }
    return ESP_LOADER_SUCCESS;
}
esp_loader_error_t loader_port_read(uint8_t *buf, uint16_t size, uint32_t timeout) { return transfer(buf, size, timeout, 0); }
esp_loader_error_t loader_port_write(const uint8_t *buf, uint16_t size, uint32_t timeout) { return transfer((uint8_t *)buf, size, timeout, 1); }
esp_loader_error_t loader_port_change_transmission_rate(uint32_t rate) { return baud(rate); }
void loader_port_debug_print(const char *s) { fputs(s, stderr); }
void loader_port_enter_bootloader(void) {
    /* Host already unbound; never touch the SD-card controller (13450000). */
    if (put(PWR, "0\n") || put(BOOT, "1\n")) { failed = 1; return; }
    loader_port_delay_ms(100);
    if (put(PWR, "1\n")) { failed = 1; return; }
    loader_port_delay_ms(100);
    if (put(BOOT, "0\n")) { failed = 1; return; }
    loader_port_delay_ms(2000);
    if (tcflush(uart, TCIOFLUSH)) failed = 1;
}
void loader_port_reset_target(void) {
    if (put(BOOT, "0\n") || put(PWR, "0\n")) { failed = 1; return; }
    loader_port_delay_ms(100);
    if (put(PWR, "1\n")) failed = 1;
}
