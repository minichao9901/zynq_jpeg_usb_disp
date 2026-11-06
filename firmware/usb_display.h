#ifndef USB_DISPLAY_H
#define USB_DISPLAY_H
#include <stdint.h>
/* Diagnostic ABI: 32 little-endian words, vendor IN request 0x30. */
enum { S_MAGIC, S_VERSION, S_CONFIGURED, S_RESETS, S_WIDTH, S_HEIGHT,
       S_PANEL, S_USB_BYTES, S_CHUNKS, S_FRAMES, S_BAD, S_UNSUPPORTED,
       S_DISPLAY_ERRORS, S_LAST_ID, S_LAST_TYPE, S_LAST_X, S_LAST_Y,
       S_LAST_WIDTH, S_LAST_HEIGHT, S_LAST_LENGTH, S_FRONT, S_VDMA,
       S_FRAME_FNV, S_EP1_FRAMES, S_EP2_FRAMES, S_RX_TIMEOUTS,
       S_SETUP, S_STALLS, S_SPEED, S_STAGE, S_SESSION, S_RESYNC_BYTES, S_COUNT };
extern volatile uint32_t udisp_stats[S_COUNT];
int usb_display_init(void);
void usb_display_poll(void);
#endif
