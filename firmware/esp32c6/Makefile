CROSS_COMPILE ?=
CC = $(CROSS_COMPILE)gcc
CFLAGS ?= -Os -g0
CPPFLAGS += -Ivendor/include -Ivendor/private_include -DSERIAL_FLASHER_INTERFACE_UART=1 -DMD5_ENABLED=1 -DSERIAL_FLASHER_WRITE_BLOCK_RETRIES=5
SOURCES = main.c port.c vendor/src/esp_loader.c vendor/src/esp_stubs.c vendor/src/esp_targets.c vendor/src/md5_hash.c vendor/src/slip.c vendor/src/protocol_uart.c vendor/src/protocol_common.c
.PHONY: all check clean package
all: retrode3-esp-flasher
retrode3-esp-flasher: $(SOURCES) $(wildcard vendor/include/*.h vendor/private_include/*.h)
	$(CC) $(CPPFLAGS) $(CFLAGS) -std=gnu11 -Wall -Wextra -o $@ $(SOURCES) $(LDFLAGS)
check:
	cd firmware && sha256sum -c SHA256SUMS
package: check all
	./build-deb.sh
clean:
	rm -f retrode3-esp-flasher
