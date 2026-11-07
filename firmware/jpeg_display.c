#include "display.h"
#include "jpeg_display.h"
#include "profile.h"
#include "xil_cache.h"
#include "xil_io.h"

/* GP0 mapping from fpga/bd/jpeg_rtl.tcl. HP1 is noncoherent with the A9. */
#define JPEG_BASE 0x43c10000U
#define JPEG_ID 0x4a504701U
enum {
    REG_CONTROL=0x00, REG_STATUS=0x04, REG_SRC=0x08, REG_LENGTH=0x0c,
    REG_DST=0x10, REG_SIZE=0x14, REG_CYCLES=0x18, REG_PIXELS=0x1c
};
enum { CMD_START=1, CMD_ABORT=2, STATUS_BUSY=1, STATUS_DONE=2, STATUS_ERROR=4 };
static unsigned disabled;

static uint32_t reg_read(unsigned reg) { return Xil_In32(JPEG_BASE+reg); }
static void reg_write(unsigned reg, uint32_t value) { Xil_Out32(JPEG_BASE+reg,value); }

unsigned jpeg_rtl_available(void)
{
    return !disabled && reg_read(REG_CONTROL)==JPEG_ID;
}

static uint32_t wait_idle(XTime deadline)
{
    uint32_t status;
    do {
        status=reg_read(REG_STATUS);
        if (!(status&STATUS_BUSY)) break;
        display_poll();
    } while (profile_now()<deadline);
    return status;
}

int jpeg_display(const uint8_t *data,unsigned length,unsigned x,unsigned y,unsigned w,unsigned h)
{
    XTime start=profile_now(), cache_start;
    unsigned full_bytes=display_width*display_height*3U;
    uint32_t status;
    uint8_t *base;
    if (length<4 || data[0]!=0xff || data[1]!=0xd8 ||
        data[length-2]!=0xff || data[length-1]!=0xd9 ||
        ((UINTPTR)data&63U) || !jpeg_rtl_available() || (reg_read(REG_STATUS)&STATUS_BUSY))
        return 1;
    base=display_prepare(x,y,w,h);
    if (!base) return 1;

    cache_start=profile_now();
    Xil_DCacheFlushRange((INTPTR)data,(length+7U)&~7U);
    if (x || y || w!=display_width || h!=display_height)
        Xil_DCacheFlushRange((INTPTR)base,full_bytes); /* CPU copied the previous frame. */
    else
        Xil_DCacheInvalidateRange((INTPTR)base,full_bytes);
    profile_add(P_FLUSH_US,cache_start);
    reg_write(REG_SRC,(UINTPTR)data);
    reg_write(REG_LENGTH,length);
    reg_write(REG_DST,(UINTPTR)base+(y*display_width+x)*3U);
    reg_write(REG_SIZE,(h<<16)|w);
    reg_write(REG_CONTROL,CMD_START);
    DATA_SYNC;

    status=wait_idle(profile_now()+COUNTS_PER_SECOND*3U/20U);
    if (status&STATUS_BUSY) {
        reg_write(REG_CONTROL,CMD_ABORT);
        DATA_SYNC;
        status=wait_idle(profile_now()+COUNTS_PER_SECOND/100U);
    }
    udisp_profile[P_JPEG_HW_STATUS]=status;
    udisp_profile[P_JPEG_HW_CYCLES]=reg_read(REG_CYCLES);
    profile_add(P_JPEG_US,start);
    if (status&STATUS_BUSY) {
        /* An AXI slave failed to drain. DMA may still own this frame. */
        disabled=1;
        udisp_profile[P_JPEG_RTL]=0;
        display_quarantine();
        return 1;
    }
    cache_start=profile_now();
    Xil_DCacheInvalidateRange((INTPTR)base,full_bytes);
    profile_add(P_FLUSH_US,cache_start);
    if ((status&(STATUS_DONE|STATUS_ERROR))!=STATUS_DONE || reg_read(REG_PIXELS)!=w*h) {
        display_cancel();
        return 1;
    }
    return display_commit_dma(base);
}
