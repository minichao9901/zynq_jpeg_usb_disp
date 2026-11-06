#ifndef UDISP_JPEG_DISPLAY_H
#define UDISP_JPEG_DISPLAY_H
#include <stdint.h>
int jpeg_display(const uint8_t *data,unsigned length,unsigned x,unsigned y,unsigned w,unsigned h);
unsigned jpeg_neon_available(void);
#endif
