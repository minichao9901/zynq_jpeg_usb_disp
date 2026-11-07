#ifndef UDISP_PROFILE_H
#define UDISP_PROFILE_H
#include <stdint.h>
#include "xtime_l.h"
enum { P_VERSION, P_FLAGS, P_FRAMES, P_CONVERT_US, P_JPEG_US, P_FLUSH_US,
       P_WAIT_US, P_FNV_US, P_COPY_US, P_FRAME_US, P_LAST_US, P_MAX_US,
       P_JPEG_ERRORS, P_NEON, P_SINK_FRAMES, P_HZ, P_JPEG_RTL, P_JPEG_HW_STATUS,
       P_JPEG_HW_CYCLES, P_COUNT=32 };
#define PROFILE_RX_ONLY 1U
#define PROFILE_NO_FNV 2U
extern volatile unsigned profile_flags;
extern volatile uint32_t udisp_profile[P_COUNT];
static inline XTime profile_now(void) { XTime t; XTime_GetTime(&t); return t; }
static inline uint32_t profile_us(XTime t) { return (uint32_t)(t*1000000U/COUNTS_PER_SECOND); }
static inline void profile_add(unsigned field, XTime start) { udisp_profile[field]+=profile_us(profile_now()-start); }
#endif
