#include "display.h"
#include "display_ctrl/display_ctrl.h"
#include "xaxivdma.h"
#include "xgpio.h"
#include "xil_cache.h"
#include "xtime_l.h"
#include "profile.h"
#include <string.h>

uint32_t display_width, display_height, display_panel_id;
static XAxiVdma vdma;
static DisplayCtrl controller;
static unsigned front;
static uint32_t address(unsigned i) { return UDISP_FB_BASE + i * UDISP_FB_SPAN; }
uint32_t display_front_address(void) { return address(front); }
uint32_t display_vdma_status(void) { return XAxiVdma_GetStatus(&vdma, XAXIVDMA_READ); }

int display_init(void)
{
    XGpio gpio;
    XAxiVdma_Config *cfg;
    XAxiVdma_DmaSetup setup = {0};
    UINTPTR frames[3];
    const VideoMode *mode;
    unsigned i, x, y;
    if (XGpio_Initialize(&gpio, XPAR_AXI_GPIO_0_DEVICE_ID)) return -1;
    XGpio_SetDataDirection(&gpio, 1, 7);
    display_panel_id = LTDC_PanelID_Read(&gpio, 1);
    XGpio_SetDataDirection(&gpio, 1, 0);
    /* The installed panel is specified as 800x480. It may be disconnected
     * during USB tests, so floating ID pins must not prevent enumeration. */
    mode = &VMODE_800x480;
    display_width = mode->width; display_height = mode->height;
    for (i = 0; i < 3; ++i) {
        uint8_t *p = (uint8_t *)address(i);
        frames[i] = address(i);
        for (y = 0; y < display_height; ++y)
            for (x = 0; x < display_width; ++x) {
                static const uint32_t bars[] = {0xff0000,0x00ff00,0x0000ff,0xffffff,0xffff00,0x00ffff,0xff00ff,0};
                uint32_t c = bars[x*8/display_width];
                *p++ = c; *p++ = c >> 8; *p++ = c >> 16;
            }
        Xil_DCacheFlushRange(address(i), display_width * display_height * 3);
    }
    cfg = XAxiVdma_LookupConfig(XPAR_AXIVDMA_0_DEVICE_ID);
    if (!cfg || cfg->MaxFrameStoreNum != 1) return -3;
    /* Reference PL has one hardware frame store. Software owns three DDR
     * buffers and switches the address only after MM2S has halted. */
    if (XAxiVdma_CfgInitialize(&vdma, cfg, cfg->BaseAddress)) return -3;
    setup.VertSizeInput = display_height;
    setup.HoriSizeInput = setup.Stride = display_width*3;
    setup.EnableCircularBuf = 0;
    setup.FixedFrameStoreAddr = 0;
    if (XAxiVdma_DmaConfig(&vdma, XAXIVDMA_READ, &setup) ||
        XAxiVdma_DmaSetBufferAddr(&vdma, XAXIVDMA_READ, frames) ||
        XAxiVdma_DmaStart(&vdma, XAXIVDMA_READ)) return -4;
    if (DisplayInitialize(&controller, XPAR_VTC_0_DEVICE_ID, XPAR_AXI_DYNCLK_0_BASEADDR) ||
        DisplaySetMode(&controller, mode) || DisplayStart(&controller)) return -5;
    return 0;
}

int display_rgb565(const uint8_t *pixels, unsigned x, unsigned y, unsigned w, unsigned h)
{
    unsigned row, col;
    uint8_t *base = display_prepare(x,y,w,h);
    XTime start=profile_now();
    if (!base) return -1;
    for (row = 0; row < h; ++row) {
        uint8_t *d = base + ((y+row)*display_width+x)*3;
        for (col = 0; col < w; ++col) {
            uint32_t c = pixels[0] | (pixels[1]<<8);
            uint32_t r = c>>11, g = (c>>5)&63, b = c&31;
            *d++ = (b<<3)|(b>>2);
            *d++ = (g<<2)|(g>>4);
            *d++ = (r<<3)|(r>>2);
            pixels += 2;
        }
    }
    profile_add(P_CONVERT_US,start);
    return display_commit(base);
}

uint8_t *display_prepare(unsigned x,unsigned y,unsigned w,unsigned h)
{
    uint8_t *base=(uint8_t *)address((front+1)%3);
    if (!w || !h || x+w>display_width || y+h>display_height) return NULL;
    if (x || y || w != display_width || h != display_height)
        memcpy(base,(void *)address(front),display_width*display_height*3);
    return base;
}

int display_commit(uint8_t *base)
{
    unsigned back=((uint32_t)base-UDISP_FB_BASE)/UDISP_FB_SPAN;
    XTime start=profile_now(),now;
    if(back>=3 || base!=(uint8_t *)address(back) || back==front) return -1;
    Xil_DCacheFlushRange((INTPTR)base, display_width*display_height*3);
    profile_add(P_FLUSH_US,start);
    XAxiVdma_DmaStop(&vdma, XAXIVDMA_READ);
    XTime_GetTime(&start);
    do {
        if (!XAxiVdma_IsBusy(&vdma, XAXIVDMA_READ)) {
            UINTPTR frames[1] = {address(back)};
            if (XAxiVdma_DmaSetBufferAddr(&vdma,XAXIVDMA_READ,frames) ||
                XAxiVdma_DmaStart(&vdma,XAXIVDMA_READ)) return -2;
            front = back;
            profile_add(P_WAIT_US,start);
            return 0;
        }
        XTime_GetTime(&now);
    } while (now-start < COUNTS_PER_SECOND/5);
    /* Fail closed: no later frame may write any possibly scanned buffer. */
    return -3;
}

uint32_t display_frame_crc(void)
{
    /* FNV-1a: verification mode only, disabled in the normal fast path. */
    const uint8_t *p = (const uint8_t *)address(front);
    unsigned n = display_width*display_height*3;
    uint32_t v = 2166136261U;
    while (n--) v = (v ^ *p++) * 16777619U;
    return v;
}
