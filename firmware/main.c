#include "display.h"
#include "usb_display.h"
#include "xil_printf.h"
#include "xil_cache.h"
#include "xtime_l.h"

int main(void)
{
    XTime last = 0, now;
    int result;
    udisp_stats[S_MAGIC] = 0x31504455; /* UDP1 */
    udisp_stats[S_VERSION] = 1;
    udisp_stats[S_STAGE] = 1;
    result = display_init();
    udisp_stats[S_PANEL] = display_panel_id;
    udisp_stats[S_WIDTH] = display_width;
    udisp_stats[S_HEIGHT] = display_height;
    xil_printf("\r\nZynq USB Display RGB565: panel=%x %ux%u init=%d\r\n",
               display_panel_id, display_width, display_height, result);
    if (result) { udisp_stats[S_STAGE] = 0x80000000U | (unsigned)-result; goto failed; }
    udisp_stats[S_STAGE] = 2;
    result = usb_display_init();
    if (result) { udisp_stats[S_STAGE] = 0x90000000U | (unsigned)result; goto failed; }
    udisp_stats[S_STAGE] = 3;
    for (;;) {
        usb_display_poll();
        XTime_GetTime(&now);
        if (now-last > COUNTS_PER_SECOND*2) {
            last = now;
            udisp_stats[S_FRONT] = display_front_address();
            udisp_stats[S_VDMA] = display_vdma_status();
            Xil_DCacheFlushRange((INTPTR)udisp_stats, sizeof udisp_stats);
            xil_printf("UDISP cfg=%u frames=%u bad=%u unsupported=%u bytes=%u vdma=%08x\r\n",
                udisp_stats[S_CONFIGURED], udisp_stats[S_FRAMES], udisp_stats[S_BAD],
                udisp_stats[S_UNSUPPORTED], udisp_stats[S_USB_BYTES], udisp_stats[S_VDMA]);
        }
    }
failed:
    Xil_DCacheFlushRange((INTPTR)udisp_stats, sizeof udisp_stats);
    for (;;) {}
}
