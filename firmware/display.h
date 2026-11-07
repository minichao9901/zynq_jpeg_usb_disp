#ifndef UDISP_DISPLAY_H
#define UDISP_DISPLAY_H
#include <stdint.h>
#define UDISP_MAX_PIXELS (800U * 480U)
#define UDISP_FB_BASE 0x02000000U
#define UDISP_FB_SPAN 0x00200000U
#define UDISP_FB_COUNT 5U
extern uint32_t display_width, display_height, display_panel_id;
int display_init(void);
int display_rgb565(const uint8_t *pixels, unsigned x, unsigned y, unsigned w, unsigned h);
uint8_t *display_prepare(unsigned x,unsigned y,unsigned w,unsigned h);
int display_commit(uint8_t *base);
int display_commit_dma(uint8_t *base);
void display_cancel(void);
void display_quarantine(void);
void display_poll(void);
void display_snapshot(uint32_t out[32]);
uint32_t display_front_address(void);
uint32_t display_vdma_status(void);
uint32_t display_frame_crc(void);
#endif
