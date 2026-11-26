/* SPDX-License-Identifier: Apache-2.0 */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#include "esp_loader.h"
#include "port.h"
#include "esp_loader_io.h"
#include "protocol.h"
#include "md5_hash.h"
#define FW "/usr/share/retrode3/esp32c6"
struct part { const char *name; uint32_t addr, size; FILE *file; };
static struct part parts[] = {
    {"bootloader.bin", 0x00000, 22496, NULL},
    {"partition-table.bin", 0x08000, 3072, NULL},
    {"ota_data_initial.bin", 0x0d000, 8192, NULL},
    {"network_adapter.bin", 0x10000, 1024896, NULL},
};
static int verify_files(void) {
    pid_t pid=fork(); int status;
    if(pid<0) return -1;
    if(!pid) {
        if(chdir(FW)) _exit(1);
        execl("/usr/bin/sha256sum", "sha256sum", "-c", "--strict", "SHA256SUMS", (char *)NULL);
        _exit(1);
    }
    pid_t result;
    do { result=waitpid(pid,&status,0); } while(result<0&&errno==EINTR);
    return result==pid&&WIFEXITED(status)&&WEXITSTATUS(status)==0?0:-1;
}
static int preflight(void) {
    for (size_t i=0;i<sizeof(parts)/sizeof(parts[0]);i++) {
        char path[256]; struct stat st;
        snprintf(path,sizeof(path),FW "/%s",parts[i].name);
        int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
        if(fd<0) { perror(path); return -1; }
        if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size!=parts[i].size||st.st_uid!=0||(st.st_mode&022)) {
            fprintf(stderr,"Invalid firmware file: %s\n",path); close(fd); return -1;
        }
        parts[i].file=fdopen(fd,"rb");
        if(!parts[i].file) { close(fd); return -1; }
    }
    return 0;
}
static int program(struct part *p) {
    uint8_t buf[1024]; uint32_t left=p->size;
    esp_loader_error_t rc=esp_loader_flash_start(p->addr,p->size,sizeof(buf));
    if(rc!=ESP_LOADER_SUCCESS) return rc;
    while(left) {
        uint32_t n=left<sizeof(buf)?left:sizeof(buf);
        if(fread(buf,1,n,p->file)!=n) return -1;
        rc=esp_loader_flash_write(buf,n);
        if(rc!=ESP_LOADER_SUCCESS) return rc;
        left-=n;
        if(!left || (p->size-left)%65536==0) {
            printf("  %u/%u bytes written\n",p->size-left,p->size); fflush(stdout);
        }
    }
    return esp_loader_flash_verify();
}
/* ROM-loader MD5 is read-only: prove that the entire 4 MiB flash is erased.
 * A timeout or a different digest is never permission to write. */
static int erased_flash(uint32_t size) {
    struct MD5Context ctx;
    uint8_t block[1024], digest[16], observed[33]={0};
    char expected[33];
    memset(block, 0xff, sizeof(block));
    MD5Init(&ctx);
    for (uint32_t offset=0; offset<size; offset+=sizeof(block))
        MD5Update(&ctx, block, sizeof(block));
    MD5Final(digest, &ctx);
    for (size_t i=0; i<sizeof(digest); i++)
        snprintf(expected+2*i, 3, "%02x", digest[i]);
    loader_port_start_timer(1000);
    if (loader_spi_parameters(size)!=ESP_LOADER_SUCCESS || retrode_port_failed())
        return -1;
    loader_port_start_timer(60000);
    if (loader_md5_cmd(0, size, observed)!=ESP_LOADER_SUCCESS || retrode_port_failed())
        return -1;
    return !memcmp(expected, observed, 32);
}
static int restore_sdio(void) {
    esp_loader_reset_target();
    retrode_port_close();
    int rc=retrode_sdio_bind();
    return retrode_port_failed() || rc ? -1 : 0;
}
int main(int argc,char **argv) {
    int blank_only=argc==2&&!strcmp(argv[1],"--flash-if-blank");
    int probe_only=argc==2&&!strcmp(argv[1],"--probe-blank");
    int verify_only=argc==2&&!strcmp(argv[1],"--verify-installed");
    if(argc!=2||(!blank_only&&!probe_only&&!verify_only&&strcmp(argv[1],"--flash-confirmed"))) {
        fprintf(stderr,"Usage: retrode3-esp-flasher --flash-confirmed|--flash-if-blank|--probe-blank|--verify-installed\nExperimental: maintenance candidate; physical recovery required.\n");
        return argc==2&&!strcmp(argv[1],"--help")?0:2;
    }
    if(geteuid()!=0) { fputs("Root required\n",stderr); return 1; }
    int lock=open("/run/lock/retrode3-esp-flasher.lock",O_CREAT|O_RDWR|O_NOFOLLOW|O_CLOEXEC,0600);
    if(lock<0||flock(lock,LOCK_EX|LOCK_NB)) { perror("flasher lock"); return 1; }
    if(verify_files()||preflight()||retrode_port_open()) return 1;
    /* Confirm the GPIO and UART contract before disconnecting the WLAN bus. */
    if(access("/sys/devices/platform/wlan_pwrseq/enable_power",W_OK)||
       access("/sys/devices/platform/wlan_pwrseq/enable_flashing",W_OK)||
       retrode_sdio_unbind()) { fputs("WLAN control unavailable\n",stderr); return 1; }
    esp_loader_connect_args_t args=ESP_LOADER_CONNECT_DEFAULT();
    uint32_t flash_size=0;
    esp_loader_target_security_info_t security={0};
    if(esp_loader_connect(&args)!=ESP_LOADER_SUCCESS||retrode_port_failed()||esp_loader_get_target()!=ESP32C6_CHIP||
       esp_loader_get_security_info(&security)!=ESP_LOADER_SUCCESS||security.target_chip!=ESP32C6_CHIP||security.secure_boot_enabled||security.flash_encryption_enabled||security.secure_download_mode_enabled||
       esp_loader_flash_detect_size(&flash_size)!=ESP_LOADER_SUCCESS||flash_size!=4u*1024u*1024u) {
        fputs("Target identification/security/flash size check failed; no firmware written\n",stderr);
        restore_sdio();
        return 1;
    }
    if(blank_only||probe_only) {
        int blank=erased_flash(flash_size);
        if(blank!=1||probe_only) {
            if(blank==1) puts("ESP32-C6 flash is entirely erased.");
            else if(blank==0) puts("ESP32-C6 flash is not blank; no firmware written.");
            else fputs("Cannot prove erased flash; no firmware written\n",stderr);
            if(restore_sdio()) return 1;
            return blank==1 ? 0 : blank==0 ? 3 : 1;
        }
    }
    if(verify_only) {
        int good=1;
        loader_port_start_timer(1000);
        if(loader_spi_parameters(flash_size)!=ESP_LOADER_SUCCESS) good=0;
        for(size_t i=0;good&&i<sizeof(parts)/sizeof(parts[0]);i++) {
            struct part *p=&parts[i];
            struct MD5Context ctx;
            uint8_t buf[1024], digest[16], observed[33]={0};
            char expected[33];
            uint32_t left=p->size;
            MD5Init(&ctx);
            while(left) {
                uint32_t n=left<sizeof(buf)?left:sizeof(buf);
                if(fread(buf,1,n,p->file)!=n) { good=0; break; }
                MD5Update(&ctx,buf,n); left-=n;
            }
            if(!good) break;
            MD5Final(digest,&ctx);
            for(size_t j=0;j<sizeof(digest);j++)
                snprintf(expected+2*j,3,"%02x",digest[j]);
            loader_port_start_timer(60000);
            good=loader_md5_cmd(p->addr,p->size,observed)==ESP_LOADER_SUCCESS &&
                 !retrode_port_failed() && !memcmp(expected,observed,32);
            printf("%s: %s\n",p->name,good?"verified":"verification failed");
            fflush(stdout);
        }
        if(restore_sdio()) return 1;
        return good?0:1;
    }
    for(size_t i=0;i<sizeof(parts)/sizeof(parts[0]);i++) {
        printf("Programming and verifying %s\n",parts[i].name); fflush(stdout);
        int rc=program(&parts[i]);
        if(rc||retrode_port_failed()) { fprintf(stderr,"Failed %s: %d\n",parts[i].name,rc); goto fail; }
        printf("Verified %s\n",parts[i].name); fflush(stdout);
    }
    /* The ESP32-C6 ROM rejected FLASH_END after all four MD5 checks on
     * hardware. A physical reset successfully booted the verified image.
     * Finish is not a write or integrity check; always reset explicitly.
     * Do not reach this path after a failed write or digest mismatch. */
    esp_loader_error_t finish=esp_loader_flash_finish(false);
    if(finish!=ESP_LOADER_SUCCESS)
        fprintf(stderr,"Warning: FLASH_END returned %d after all MD5 checks; resetting ESP\n",finish);
    if(restore_sdio()) {
        fputs("All partitions verified, but ESP reset/SDIO rebind failed; cold boot required.\n",stderr);
        goto fail;
    }
    puts("All four partitions verified. Check WLAN and cold boot.");
    return 0;
fail:
    retrode_port_close();
    fputs("ESP update failed. WLAN SDIO may be unbound; use physical recovery. Do not assume success.\n",stderr);
    return 1;
}
