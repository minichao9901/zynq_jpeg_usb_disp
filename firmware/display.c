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
/* One hardware frame slot, with frame-boundary shadow updates. Never stop
 * MM2S for a present. Keep the programmed frame and two generations of
 * retired readers immutable; a separate ready and drawing slot allow the
 * producer to replace old queued pictures without touching scanout. */
static unsigned programmed,latest;
static int ready=-1,drawing=-1;
static uint32_t frame_epoch,retired_mask,retired_at[UDISP_FB_COUNT];
static uint32_t sequences[UDISP_FB_COUNT],decoded,published,replaced,published_epoch;
static uint32_t halted_seen,error_seen,no_buffer;
static uint32_t quarantined_mask;
static XTime last_frame_event;
static uint32_t address(unsigned i) { return UDISP_FB_BASE + i * UDISP_FB_SPAN; }
uint32_t display_front_address(void) { return address(programmed); }
uint32_t display_vdma_status(void) { return XAxiVdma_GetStatus(&vdma, XAXIVDMA_READ); }

int display_init(void)
{
    XGpio gpio;
    XAxiVdma_Config *cfg;
    XAxiVdma_DmaSetup setup = {0};
    UINTPTR frames[1];
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
    for (i = 0; i < UDISP_FB_COUNT; ++i) {
        uint8_t *p = (uint8_t *)address(i);
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
    /* The reference PL's single slot supports dynamic parameter updates.
     * START_ADDRESS followed by VSIZE takes effect on a frame boundary. */
    if (XAxiVdma_CfgInitialize(&vdma, cfg, cfg->BaseAddress)) return -3;
    setup.VertSizeInput = display_height;
    setup.HoriSizeInput = setup.Stride = display_width*3;
    setup.EnableCircularBuf = 0;
    setup.FixedFrameStoreAddr = 0;
    frames[0]=address(0);
    if (XAxiVdma_DmaConfig(&vdma, XAXIVDMA_READ, &setup) ||
        XAxiVdma_DmaSetBufferAddr(&vdma, XAXIVDMA_READ, frames) ||
        XAxiVdma_DmaStart(&vdma, XAXIVDMA_READ)) return -4;
    if (DisplayInitialize(&controller, XPAR_VTC_0_DEVICE_ID, 0) ||
        DisplaySetMode(&controller, mode) || DisplayStart(&controller)) return -5;
    last_frame_event=profile_now();
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
    unsigned i;
    uint8_t *base;
    if (!w || !h || x+w>display_width || y+h>display_height) return NULL;
    display_poll();
    if(drawing>=0) return NULL;
    for(i=0;i<UDISP_FB_COUNT;++i) {
        if(i==programmed || (int)i==ready || ((retired_mask|quarantined_mask)&(1U<<i))) continue;
        drawing=(int)i;base=(uint8_t *)address(i);
        if (x || y || w != display_width || h != display_height)
            memcpy(base,(void *)address(latest),display_width*display_height*3);
        return base;
    }
    ++no_buffer;
    return NULL;
}

static int publish_drawing(uint8_t *base, int cpu_written)
{
    unsigned back;
    XTime start=profile_now();
    if(drawing<0 || base!=(uint8_t *)address((unsigned)drawing)) return -1;
    back=(unsigned)drawing;
    if (cpu_written) {
        Xil_DCacheFlushRange((INTPTR)base, display_width*display_height*3);
        profile_add(P_FLUSH_US,start);
    }
    if(ready>=0) ++replaced;
    latest=back;ready=(int)back;drawing=-1;
    sequences[back]=++decoded;
    start=profile_now();
    display_poll();
    profile_add(P_WAIT_US,start);
    return 0;
}

int display_commit(uint8_t *base) { return publish_drawing(base, 1); }
int display_commit_dma(uint8_t *base) { return publish_drawing(base, 0); }
void display_cancel(void) { drawing=-1; }
void display_quarantine(void)
{
    if (drawing >= 0) quarantined_mask |= 1U << drawing;
    drawing = -1;
}

void display_poll(void)
{
    uint32_t status=XAxiVdma_GetStatus(&vdma,XAXIVDMA_READ);
    unsigned i;
    if(status&XAXIVDMA_SR_HALTED_MASK) ++halted_seen;
    if(status&XAXIVDMA_SR_ERR_ALL_MASK) ++error_seen;
    if(!(status&XAXIVDMA_IXR_FRMCNT_MASK)) return;
    XAxiVdma_IntrClear(&vdma,XAXIVDMA_IXR_FRMCNT_MASK,XAXIVDMA_READ);
    ++frame_epoch;last_frame_event=profile_now();
    for(i=0;i<UDISP_FB_COUNT;++i)
        if((retired_mask&(1U<<i)) && (uint32_t)(frame_epoch-retired_at[i])>=2U)
            retired_mask&=~(1U<<i);
    if(ready>=0) {
        unsigned next=(unsigned)ready;
        /* PG020: commit shadow start-address with VSIZE, leaving RS=1.
         * Polling can miss sticky completion events, so retaining old readers
         * for two observed events is conservative even if the CPU was busy. */
        XAxiVdma_WriteReg(XPAR_AXIVDMA_0_BASEADDR+XAXIVDMA_MM2S_ADDR_OFFSET,
            XAXIVDMA_START_ADDR_OFFSET,address(next));
        XAxiVdma_WriteReg(XPAR_AXIVDMA_0_BASEADDR+XAXIVDMA_MM2S_ADDR_OFFSET,
            XAXIVDMA_VSIZE_OFFSET,display_height);
        retired_at[programmed]=frame_epoch;
        retired_mask|=1U<<programmed;
        programmed=next;ready=-1;published_epoch=frame_epoch;++published;
    }
}

void display_snapshot(uint32_t out[32])
{
    memset(out,0,32*sizeof(uint32_t));
    out[0]=0x31505344U;out[1]=1;out[2]=UDISP_FB_COUNT;out[3]=frame_epoch;
    out[4]=address(programmed);out[5]=address(latest);
    out[6]=ready<0?0:address((unsigned)ready);out[7]=drawing<0?0:address((unsigned)drawing);
    out[8]=retired_mask;out[9]=decoded;out[10]=published;out[11]=replaced;
    out[12]=display_vdma_status();out[13]=profile_us(profile_now()-last_frame_event)/1000;
    out[14]=halted_seen;out[15]=error_seen;out[16]=no_buffer;
    out[17]=sequences[programmed];out[18]=sequences[latest];out[19]=2;
    out[20]=ready<0 && drawing<0 && (uint32_t)(frame_epoch-published_epoch)>=2U;
    out[21]=XAxiVdma_ReadReg(XPAR_AXIVDMA_0_BASEADDR,XAXIVDMA_CR_OFFSET);
    out[22]=quarantined_mask;
}

uint32_t display_frame_crc(void)
{
    /* FNV-1a: verification mode only, disabled in the normal fast path. */
    const uint8_t *p = (const uint8_t *)address(latest);
    unsigned n = display_width*display_height*3;
    uint32_t v = 2166136261U;
    while (n--) v = (v ^ *p++) * 16777619U;
    return v;
}
