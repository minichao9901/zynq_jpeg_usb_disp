/* libjpeg-turbo 3.1.2, Cortex-A9 Neon. Decode into a non-scanned BGR888 buffer. */
#include <stdio.h>
#include <setjmp.h>
#include <string.h>
#include "jpeglib.h"
#include "display.h"
#include "profile.h"
#include "jpeg_display.h"

static struct jpeg_decompress_struct decoder;
static struct { struct jpeg_error_mgr pub; jmp_buf jump; } errors;
static void fail(j_common_ptr c) { (void)c; longjmp(errors.jump,1); }
static void quiet(j_common_ptr c) { (void)c; }
/* Pinned library's SIMD dispatch query, used only for a diagnostic assertion. */
extern int jsimd_can_ycc_rgb(void);
unsigned jpeg_neon_available(void) { return !!jsimd_can_ycc_rgb(); }

int jpeg_display(const uint8_t *data,unsigned length,unsigned x,unsigned y,unsigned w,unsigned h)
{
    uint8_t *base;
    XTime start=profile_now();
    if(length<4 || data[0]!=255 || data[1]!=216 || data[length-2]!=255 || data[length-1]!=217) return 1;
    memset(&decoder,0,sizeof decoder);
    decoder.err=jpeg_std_error(&errors.pub);
    errors.pub.error_exit=fail;
    errors.pub.output_message=quiet;
    if(setjmp(errors.jump)) {
        if(decoder.mem) jpeg_destroy_decompress(&decoder);
        profile_add(P_JPEG_US,start);
        return 1;
    }
    jpeg_create_decompress(&decoder);
    decoder.mem->max_memory_to_use=6*1024*1024;
    jpeg_mem_src(&decoder,data,length);
    if(jpeg_read_header(&decoder,TRUE)!=JPEG_HEADER_OK || decoder.image_width!=w || decoder.image_height!=h ||
       decoder.data_precision!=8 || decoder.num_components>3 || decoder.arith_code) {
        jpeg_destroy_decompress(&decoder); return 1;
    }
    decoder.out_color_space=JCS_EXT_BGR;
    decoder.dct_method=JDCT_ISLOW;
    jpeg_start_decompress(&decoder);
    base=display_prepare(x,y,w,h);
    if(!base) { jpeg_destroy_decompress(&decoder); return 1; }
    while(decoder.output_scanline<decoder.output_height) {
        JSAMPROW row=base+((y+decoder.output_scanline)*display_width+x)*3;
        if(jpeg_read_scanlines(&decoder,&row,1)!=1) fail((j_common_ptr)&decoder);
    }
    jpeg_finish_decompress(&decoder);
    if(errors.pub.num_warnings) { jpeg_destroy_decompress(&decoder); return 1; }
    jpeg_destroy_decompress(&decoder);
    profile_add(P_JPEG_US,start);
    return display_commit(base);
}
