#ifndef UDISP_BUILD_CONFIG_H
#define UDISP_BUILD_CONFIG_H
#ifndef UDISP_DEFAULT_ENCODING
#define UDISP_DEFAULT_ENCODING 3
#endif
#ifndef UDISP_DRIVER_FPS
#define UDISP_DRIVER_FPS 999
#endif
#ifndef UDISP_BUILD_ID
#define UDISP_BUILD_ID 0U
#endif
#if UDISP_DEFAULT_ENCODING != 0 && UDISP_DEFAULT_ENCODING != 3
#error Unsupported default encoding
#endif
#if UDISP_DRIVER_FPS < 50
#error Release profiles must not enable the IDD low-FPS limiter
#endif
#endif
