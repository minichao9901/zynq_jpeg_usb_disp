/* XUsbPs device integration, following zynqlinkPRO's Xilinx SDK 2018.3 setup.
 * Display wire descriptors/framing follow cherryusb_udisp.
 * MI_00 is IDD display. MI_01 is a WinUSB diagnostic/test transport.
 */
#include "usb_display.h"
#include "display.h"
#include "xusbps.h"
#include "xusbps_endpoint.h"
#include "xusbps_ch9.h"
#include "xscugic.h"
#include "xil_exception.h"
#include "xil_cache.h"
#include "xtime_l.h"
#include "sleep.h"
#include "profile.h"
#include "jpeg_display.h"
#include <stdio.h>
#include <string.h>

#define ALIGN32 __attribute__((aligned(32)))
#define RX_SIZE 16384U
#define RX_COUNT 32U
static XUsbPs usb;
static XScuGic gic;
static uint8_t dma_arena[1200*1024] __attribute__((aligned(4096)));
_Static_assert(2048U+6U*64U+64U*(4U+2U*(RX_COUNT+4U))+128U+2U*RX_COUNT*RX_SIZE
               <= sizeof dma_arena,"USB DMA arena capacity");
volatile uint32_t udisp_stats[S_COUNT] ALIGN32;
volatile uint32_t udisp_profile[P_COUNT] ALIGN32;
volatile unsigned profile_flags=PROFILE_NO_FNV;
static volatile unsigned configured, epoch, reset_parser;
static unsigned display_failed;
static char product[80];
static uint8_t reply[256] ALIGN32;
static uint8_t device[] = {18,1,0x10,2,0xef,2,1,64,0x3a,0x30,0x86,0x29,0,1,1,2,3,1};
static uint8_t config[] = {
    9,2,55,0,2,1,0,0x80,50,
    9,4,0,0,2,0xff,0,0,2,
    7,5,0x81,2,0,2,0, 7,5,0x01,2,0,2,0,
    9,4,1,0,2,0xff,0,0,4,
    7,5,0x82,2,0,2,0, 7,5,0x02,2,0,2,0
};
static const uint8_t qualifier[] = {10,6,0,2,0xef,2,1,64,1,0};
static const uint8_t bos[] = {5,15,33,0,1, 28,16,5,0,
    0xdf,0x60,0xdd,0xd8,0x89,0x45,0xc7,0x4c,0x9c,0xd2,0x65,0x9d,0x9e,0x64,0x8a,0x9f,
    0,0,3,6,178,0,0x20,0};
/* Only MI_01 gets WINUSB; the installed xfz1986 driver owns MI_00. */
static uint8_t msos[178];
_Static_assert(sizeof config == 55, "configuration size");
_Static_assert(sizeof bos == 33, "BOS size");

typedef struct {
    uint8_t header[16];
    uint8_t pixels[4U*1024U*1024U] ALIGN32;
    unsigned header_used, used, length, x, y, w, h, id, type, reject, seeking;
    XTime last;
    XTime copy_ticks;
} Stream;
static Stream streams[2];

static uint16_t le16(const uint8_t *p) { return p[0] | ((uint16_t)p[1]<<8); }
static uint32_t le32(const uint8_t *p) { return le16(p) | ((uint32_t)le16(p+2)<<16); }
static void put16(uint8_t *p, unsigned v) { p[0]=v; p[1]=v>>8; }

static void make_msos(void)
{
    static const uint8_t prefix[] = {
        10,0,0,0,0,0,3,6,178,0, 8,0,1,0,0,0,168,0,
        8,0,2,0,1,0,160,0, 20,0,3,0,'W','I','N','U','S','B',0,0,0,0,0,0,0,0,0,0,
        132,0,4,0,7,0,42,0
    };
    const char *name = "DeviceInterfaceGUIDs";
    const char *guid = "{8D32A953-78B1-4BFA-9D86-6C5936508986}";
    unsigned i, at = sizeof prefix;
    memcpy(msos, prefix, at);
    for (i=0; i<=strlen(name); ++i) { put16(msos+at, name[i]); at+=2; }
    put16(msos+at,80); at+=2;
    for (i=0; i<=strlen(guid); ++i) { put16(msos+at, guid[i]); at+=2; }
    put16(msos+at,0);
}

static void stall(void)
{
    ++udisp_stats[S_STALLS];
    XUsbPs_EpStall(&usb,0,XUSBPS_EP_DIRECTION_IN|XUSBPS_EP_DIRECTION_OUT);
}

static int send_reply(const void *data, unsigned len, unsigned requested)
{
    if (len > requested) len = requested;
    if (len > sizeof reply) return XST_FAILURE;
    if (data != reply && len) memcpy(reply,data,len);
    return XUsbPs_EpBufferSend(&usb,0,len ? reply : NULL,len);
}

static unsigned high_speed(void)
{
    return (XUsbPs_ReadReg(usb.Config.BaseAddress,XUSBPS_PORTSCR1_OFFSET)&0x0c000000U) == 0x08000000U;
}

static int endpoints(unsigned value)
{
    unsigned ep, d;
    configured = 0;
    udisp_stats[S_CONFIGURED] = 0;
    ++epoch;
    reset_parser = 1;
    for (ep=1; ep<3; ++ep) {
        uint32_t mask=(1U<<ep)|(1U<<(ep+16));
        unsigned timeout=1000000;
        XUsbPs_EpDisable(&usb,ep,XUSBPS_EP_DIRECTION_IN);
        XUsbPs_EpDisable(&usb,ep,XUSBPS_EP_DIRECTION_OUT);
        XUsbPs_WriteReg(usb.Config.BaseAddress,XUSBPS_EPFLUSH_OFFSET,mask);
        while((XUsbPs_ReadReg(usb.Config.BaseAddress,XUSBPS_EPFLUSH_OFFSET)&mask) && --timeout) {}
        if(!timeout) return -1;
        XUsbPs_WriteReg(usb.Config.BaseAddress,XUSBPS_EPCOMPL_OFFSET,mask);
        if (!value) continue;
        for (d=0; d<2; ++d) {
            unsigned dir = d ? XUSBPS_EP_DIRECTION_IN : XUSBPS_EP_DIRECTION_OUT;
            {
                XUsbPs_dTD *tds=d?usb.DeviceConfig.Ep[ep].In.dTDs:usb.DeviceConfig.Ep[ep].Out.dTDs;
                XUsbPs_dQH *qh=d?usb.DeviceConfig.Ep[ep].In.dQH:usb.DeviceConfig.Ep[ep].Out.dQH;
                unsigned count=d?usb.DeviceConfig.EpCfg[ep].In.NumBufs:usb.DeviceConfig.EpCfg[ep].Out.NumBufs;
                unsigned i;
                for(i=0; i<count; ++i) {
                    XUsbPs_WritedTD(&tds[i],XUSBPS_dTDTOKEN,0);
                    XUsbPs_dTDFlushCache(&tds[i]);
                }
                XUsbPs_dQHInvalidateCache(qh);
                XUsbPs_WritedQH(qh,XUSBPS_dQHdTDTOKEN,0);
                XUsbPs_dQHFlushCache(qh);
            }
            if (d) usb.DeviceConfig.EpCfg[ep].In.MaxPacketSize=high_speed()?512:64;
            else usb.DeviceConfig.EpCfg[ep].Out.MaxPacketSize=high_speed()?512:64;
            if (XUsbPs_ReconfigureEp(&usb,&usb.DeviceConfig,ep,dir,0)) return -1;
            XUsbPs_EpEnable(&usb,ep,dir);
        }
        XUsbPs_SetBits(&usb,XUSBPS_EPCRn_OFFSET(ep),XUSBPS_EPCR_RXR_MASK|XUSBPS_EPCR_TXR_MASK);
        XUsbPs_EpPrime(&usb,ep,XUSBPS_EP_DIRECTION_OUT);
    }
    configured = value;
    udisp_stats[S_CONFIGURED] = value;
    udisp_stats[S_SESSION] = epoch;
    return 0;
}

static int descriptor(XUsbPs_SetupData *s)
{
    unsigned type = s->wValue>>8, index=s->wValue&255, n, i;
    if (type==1 && index==0) return send_reply(device,sizeof device,s->wLength);
    if ((type==2 || type==7) && index==0) {
        uint8_t tmp[sizeof config];
        unsigned hs = high_speed();
        if(type==7) hs=!hs;
        memcpy(tmp,config,sizeof tmp);
        tmp[1]=type;
        for(i=0; i<4; ++i) { unsigned at = i<2 ? 18+i*7 : 41+(i-2)*7; put16(tmp+at+4, hs?512:64); }
        return send_reply(tmp,sizeof tmp,s->wLength);
    }
    if(type==6 && index==0) return send_reply(qualifier,sizeof qualifier,s->wLength);
    if(type==15 && index==0) return send_reply(bos,sizeof bos,s->wLength);
    if(type!=3) return -1;
    if(index==0) { static const uint8_t lang[]={4,3,9,4}; return send_reply(lang,4,s->wLength); }
    {
        const char *str;
        switch(index) {
        case 1: str="Zynq"; break;
        case 2: str=product; break;
        case 3: str="ZYNQ-UDISP-RGB-001"; break;
        case 4: str="Zynq USB Display diagnostics"; break;
        default: return -1;
        }
        n = strlen(str)*2+2;
        reply[0]=n; reply[1]=3;
        for(i=0; str[i]; ++i) put16(reply+2+2*i,str[i]);
        return send_reply(reply,n,s->wLength);
    }
}

static void setup(XUsbPs_SetupData *s)
{
    unsigned recipient=s->bmRequestType&31, kind=s->bmRequestType&0x60;
    unsigned ep=s->wIndex&15, in=s->wIndex&0x80;
    int result=-1;
    ++udisp_stats[S_SETUP];
    if (kind==0x40) {
        if(s->bmRequestType==0xc0 && s->bRequest==0x20 && s->wIndex==7 && !s->wValue)
            result=send_reply(msos,sizeof msos,s->wLength);
        else if(s->bmRequestType==0xc1 && s->bRequest==0x30 && s->wIndex==1) {
            uint32_t snapshot[S_COUNT];
            memcpy(snapshot,(const void *)udisp_stats,sizeof snapshot);
            snapshot[S_VDMA]=display_vdma_status();
            snapshot[S_FRONT]=display_front_address();
            snapshot[S_SPEED]=high_speed()?480:12;
            result=send_reply(snapshot,sizeof snapshot,s->wLength);
        } else if(s->bmRequestType==0xc1 && s->bRequest==0x31 && s->wIndex==1) {
            uint32_t snapshot[P_COUNT];
            memcpy(snapshot,(const void *)udisp_profile,sizeof snapshot);
            snapshot[P_VERSION]=1; snapshot[P_FLAGS]=profile_flags;
            snapshot[P_HZ]=COUNTS_PER_SECOND;
            result=send_reply(snapshot,sizeof snapshot,s->wLength);
        } else if(s->bmRequestType==0x41 && s->bRequest==0x33 && s->wIndex==1 && !s->wLength && s->wValue<=3) {
            profile_flags=s->wValue;
            memset((void *)udisp_profile,0,sizeof udisp_profile);
            udisp_profile[P_NEON]=jpeg_neon_available();
            result=send_reply(NULL,0,0);
        } else if(s->bmRequestType==0x41 && s->bRequest==0x32 && s->wIndex==1 && !s->wLength) {
            reset_parser=1;
            result=send_reply(NULL,0,0);
        }
    } else if (!kind) {
        switch(s->bRequest) {
        case 6: /* GET_DESCRIPTOR */
            if(s->bmRequestType==0x80) result=descriptor(s);
            break;
        case 5: /* SET_ADDRESS */
            if(s->bmRequestType==0 && s->wValue<128 && !s->wLength && !s->wIndex) {
                XUsbPs_SetDeviceAddress(&usb,s->wValue);
                result=send_reply(NULL,0,0);
            }
            break;
        case 9: /* SET_CONFIGURATION */
            if(!s->bmRequestType && s->wValue<=1 && !s->wLength && !s->wIndex && !endpoints(s->wValue))
                result=send_reply(NULL,0,0);
            break;
        case 8:
            if(s->bmRequestType==0x80 && !s->wValue && !s->wIndex && s->wLength==1) {
                reply[0]=configured; result=send_reply(reply,1,1);
            }
            break;
        case 0: /* GET_STATUS */
            if((s->bmRequestType&0x80) && s->wLength==2 && !s->wValue) {
                unsigned v=0;
                if(recipient==2 && ep<3) {
                    uint32_t reg=XUsbPs_ReadReg(usb.Config.BaseAddress,XUSBPS_EPCRn_OFFSET(ep));
                    v=!!(reg & (in?XUSBPS_EPCR_TXS_MASK:XUSBPS_EPCR_RXS_MASK));
                } else if(recipient>1 || (recipient==1 && s->wIndex>1)) break;
                put16(reply,v); result=send_reply(reply,2,2);
            }
            break;
        case 1: case 3: /* CLEAR/SET_FEATURE ENDPOINT_HALT */
            if(s->bmRequestType==2 && s->wValue==0 && !s->wLength && ep>0 && ep<3) {
                uint32_t mask=in?XUSBPS_EPCR_TXS_MASK:XUSBPS_EPCR_RXS_MASK;
                if(s->bRequest==3) { XUsbPs_SetBits(&usb,XUSBPS_EPCRn_OFFSET(ep),mask); }
                else {
                    XUsbPs_ClrBits(&usb,XUSBPS_EPCRn_OFFSET(ep),mask);
                    XUsbPs_SetBits(&usb,XUSBPS_EPCRn_OFFSET(ep),in?XUSBPS_EPCR_TXR_MASK:XUSBPS_EPCR_RXR_MASK);
                }
                result=send_reply(NULL,0,0);
            }
            break;
        case 10: /* GET_INTERFACE */
            if(s->bmRequestType==0x81 && configured && s->wIndex<2 && !s->wValue && s->wLength==1) {
                reply[0]=0; result=send_reply(reply,1,1);
            }
            break;
        case 11: /* SET_INTERFACE */
            if(s->bmRequestType==1 && configured && s->wIndex<2 && !s->wValue && !s->wLength)
                result=send_reply(NULL,0,0);
            break;
        }
    }
    if(result) stall();
}

static void ep0_event(void *ref, uint8_t ep, uint8_t event, void *data)
{
    XUsbPs_SetupData s;
    uint8_t *buf;
    uint32_t len, handle;
    (void)ref; (void)data;
    if(event==XUSBPS_EP_EVENT_SETUP_DATA_RECEIVED) {
        if(!XUsbPs_EpGetSetupData(&usb,ep,&s)) setup(&s);
    } else if(event==XUSBPS_EP_EVENT_DATA_RX) {
        if(!XUsbPs_EpBufferReceive(&usb,ep,&buf,&len,&handle)) XUsbPs_EpBufferRelease(handle);
    }
}

static void usb_event(void *ref, uint32_t mask)
{
    (void)ref;
    if(mask&XUSBPS_IXR_UR_MASK) {
        configured=0;
        ++epoch; reset_parser=1;
        udisp_stats[S_CONFIGURED]=0;
        ++udisp_stats[S_RESETS];
    }
}

int usb_display_init(void)
{
    XUsbPs_Config *cfg=XUsbPs_LookupConfig(XPAR_XUSBPS_0_DEVICE_ID);
    XScuGic_Config *icfg=XScuGic_LookupConfig(XPAR_SCUGIC_SINGLE_DEVICE_ID);
    XUsbPs_DeviceConfig dc={0};
    unsigned ep;
    unsigned mio;
    snprintf(product,sizeof product,"zynq_R%ux%u_Ejpg8_Ergb16_Fps30_Bl4096",(unsigned)display_width,(unsigned)display_height);
    make_msos();
    udisp_profile[P_NEON]=jpeg_neon_available();
    if(!cfg || !icfg) return 1;
    /* Board USB3320 RESET_N is MIO8 (same wiring as zynqlinkPRO).
     * Some SDK 2018.3 hardware exports retain old PS init side products;
     * explicitly release the PHY before touching the USB controller. */
    Xil_Out32(0xF8000008U,0xDF0DU);
    /* USB3320 ULPI is on the 1.8V MIO bank. The LCD-only reference did
     * not assign these pins and Vivado otherwise defaults USB to 3.3V. */
    for(mio=28; mio<=39; ++mio) {
        uint32_t a=0xF8000700U+4*mio;
        Xil_Out32(a,Xil_In32(a)&~0x400U);
    }
    Xil_Out32(0xF8000720U,0x600U);
    Xil_Out32(0xE000A204U,Xil_In32(0xE000A204U)|0x100U);
    Xil_Out32(0xE000A208U,Xil_In32(0xE000A208U)|0x100U);
    Xil_Out32(0xE000A000U,0xFEFF0000U);
    usleep(10000);
    Xil_Out32(0xE000A000U,0xFEFF0100U);
    usleep(10000);
    Xil_Out32(0xF8000004U,0x767BU);
    if(XUsbPs_CfgInitialize(&usb,cfg,cfg->BaseAddress)) return 2;
    dc.NumEndpoints=3;
    dc.EpCfg[0].Out.Type=dc.EpCfg[0].In.Type=XUSBPS_EP_TYPE_CONTROL;
    dc.EpCfg[0].Out.NumBufs=dc.EpCfg[0].In.NumBufs=2;
    dc.EpCfg[0].Out.BufSize=dc.EpCfg[0].Out.MaxPacketSize=dc.EpCfg[0].In.MaxPacketSize=64;
    for(ep=1;ep<3;++ep) {
        dc.EpCfg[ep].Out.Type=dc.EpCfg[ep].In.Type=XUSBPS_EP_TYPE_BULK;
        dc.EpCfg[ep].Out.NumBufs=RX_COUNT;
        dc.EpCfg[ep].In.NumBufs=4;
        dc.EpCfg[ep].Out.BufSize=RX_SIZE;
        dc.EpCfg[ep].Out.MaxPacketSize=dc.EpCfg[ep].In.MaxPacketSize=512;
    }
    dc.DMAMemPhys=(uint32_t)dma_arena;
    memset(dma_arena,0,sizeof dma_arena);
    Xil_DCacheFlushRange((INTPTR)dma_arena,sizeof dma_arena);
    if(XUsbPs_ConfigureDevice(&usb,&dc)) return 3;
    if(XScuGic_CfgInitialize(&gic,icfg,icfg->CpuBaseAddress)) return 4;
    Xil_ExceptionInit();
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_INT,(Xil_ExceptionHandler)XScuGic_InterruptHandler,&gic);
    if(XScuGic_Connect(&gic,XPAR_XUSBPS_0_INTR,(Xil_ExceptionHandler)XUsbPs_IntrHandler,&usb)) return 5;
    XScuGic_Enable(&gic,XPAR_XUSBPS_0_INTR);
    XUsbPs_IntrSetHandler(&usb,usb_event,&usb,XUSBPS_IXR_UR_MASK);
    XUsbPs_EpSetHandler(&usb,0,XUSBPS_EP_DIRECTION_OUT,ep0_event,&usb);
    XUsbPs_IntrEnable(&usb,XUSBPS_IXR_UR_MASK|XUSBPS_IXR_UI_MASK);
    Xil_ExceptionEnable();
    XUsbPs_Start(&usb);
    XUsbPs_ClrBits(&usb,XUSBPS_CMD_OFFSET,XUSBPS_CMD_ITC_MASK);
    return 0;
}

static void stream_reset(Stream *s) { s->header_used=s->used=s->length=s->reject=s->seeking=0; s->copy_ticks=0; }

static void consume(Stream *s, unsigned ep, const uint8_t *p, unsigned n)
{
    unsigned k;
    XTime_GetTime(&s->last);
    while(n) {
        if(s->header_used<16) {
            k=16-s->header_used; if(k>n) k=n;
            memcpy(s->header+s->header_used,p,k);
            s->header_used+=k; p+=k; n-=k;
            if(s->header_used<16) return;
            s->type=s->header[2];
            s->x=le16(s->header+4); s->y=le16(s->header+6);
            s->w=le16(s->header+8); s->h=le16(s->header+10);
            s->id=le32(s->header+12)&1023;
            s->length=le32(s->header+12)>>10;
            s->used=0;
            /* A USB reset can leave the host's first URB in mid-payload.
             * Search for a plausible header instead of trusting random RGB
             * bytes as a 22-bit length and staying out of sync indefinitely. */
            if(s->type==255 && !s->length) { stream_reset(s); continue; }
            if(!s->w || !s->h || s->w>display_width || s->h>display_height ||
                !s->length || s->type>3 ||
                (s->type==0 && s->length!=s->w*s->h*2)) {
                if(!s->seeking) { ++udisp_stats[S_BAD]; s->seeking=1; }
                ++udisp_stats[S_RESYNC_BYTES];
                memmove(s->header,s->header+1,15);
                s->header_used=15;
                continue;
            }
            s->seeking=0;
            s->reject=!s->w || !s->h || s->w>display_width || s->h>display_height ||
                s->x+s->w>display_width || s->y+s->h>display_height ||
                (s->type==0 && s->length!=s->w*s->h*2);
            if(s->type!=0 && s->type!=3) s->reject=2;
        }
        k=s->length-s->used; if(k>n) k=n;
        if(!s->reject && !(profile_flags&PROFILE_RX_ONLY)) {
            XTime start=profile_now();
            memcpy(s->pixels+s->used,p,k);
            s->copy_ticks+=profile_now()-start;
        }
        s->used+=k; p+=k; n-=k;
        if(s->used==s->length) {
            udisp_stats[S_LAST_ID]=s->id; udisp_stats[S_LAST_TYPE]=s->type;
            udisp_stats[S_LAST_X]=s->x; udisp_stats[S_LAST_Y]=s->y;
            udisp_stats[S_LAST_WIDTH]=s->w; udisp_stats[S_LAST_HEIGHT]=s->h;
            udisp_stats[S_LAST_LENGTH]=s->length;
            udisp_profile[P_COPY_US]+=profile_us(s->copy_ticks);
            if(s->reject) ++udisp_stats[s->reject==2?S_UNSUPPORTED:S_BAD];
            else {
                int status=0;
                XTime start=profile_now();
                if(profile_flags&PROFILE_RX_ONLY) ++udisp_profile[P_SINK_FRAMES];
                else if(display_failed) status=-1;
                else if(s->type==3) status=jpeg_display(s->pixels,s->length,s->x,s->y,s->w,s->h);
                else status=display_rgb565(s->pixels,s->x,s->y,s->w,s->h);
                if(status>0) { ++udisp_stats[S_BAD]; if(s->type==3) ++udisp_profile[P_JPEG_ERRORS]; }
                else if(status<0) { display_failed=1; ++udisp_stats[S_DISPLAY_ERRORS]; }
                else {
                    if(!(profile_flags&(PROFILE_RX_ONLY|PROFILE_NO_FNV))) {
                        XTime hash_start=profile_now();
                        udisp_stats[S_FRAME_FNV]=display_frame_crc();
                        profile_add(P_FNV_US,hash_start);
                    }
                    udisp_stats[S_FRONT]=display_front_address();
                    ++udisp_stats[S_FRAMES];
                    ++udisp_stats[ep==1?S_EP1_FRAMES:S_EP2_FRAMES];
                    ++udisp_profile[P_FRAMES];
                    udisp_profile[P_LAST_US]=profile_us(profile_now()-start);
                    udisp_profile[P_FRAME_US]+=udisp_profile[P_LAST_US];
                    if(udisp_profile[P_LAST_US]>udisp_profile[P_MAX_US]) udisp_profile[P_MAX_US]=udisp_profile[P_LAST_US];
                }
            }
            stream_reset(s);
        }
    }
}

void usb_display_poll(void)
{
    unsigned ep, tries;
    XTime now;
    if(reset_parser) {
        Xil_ExceptionDisable();
        reset_parser=0;
        Xil_ExceptionEnable();
        for(ep=0;ep<2;++ep) stream_reset(&streams[ep]);
    }
    if(!configured) return;
    XTime_GetTime(&now);
    for(ep=1;ep<3;++ep) {
        Stream *s=&streams[ep-1];
        if(s->header_used && now-s->last>COUNTS_PER_SECOND/2) {
            stream_reset(s); ++udisp_stats[S_RX_TIMEOUTS];
        }
        for(tries=0;tries<4 && configured;++tries) {
            uint8_t *p;
            uint32_t n, handle;
            unsigned session=epoch;
            /* The bulk ring is private to this loop. Only bus reset/config
             * can interrupt it; epoch prevents releasing a rebuilt dTD. */
            Xil_ExceptionDisable();
            if(!configured || session!=epoch || XUsbPs_EpBufferReceive(&usb,ep,&p,&n,&handle)) {
                Xil_ExceptionEnable();
                break;
            }
            Xil_ExceptionEnable();
            if(n>RX_SIZE) { ++udisp_stats[S_BAD]; break; }
            Xil_DCacheInvalidateRange((INTPTR)p,(n+31)&~31U);
            udisp_stats[S_USB_BYTES]+=n;
            ++udisp_stats[S_CHUNKS];
            consume(s,ep,p,n);
            Xil_ExceptionDisable();
            if(session!=epoch) { Xil_ExceptionEnable(); break; }
            XUsbPs_EpBufferRelease(handle);
            usb.DeviceConfig.Ep[ep].Out.dTDCurr=XUsbPs_dTDGetNLP((XUsbPs_dTD *)handle);
            XUsbPs_EpPrime(&usb,ep,XUSBPS_EP_DIRECTION_OUT);
            Xil_ExceptionEnable();
        }
    }
}
