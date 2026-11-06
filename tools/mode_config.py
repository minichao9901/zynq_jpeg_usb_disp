"""Shared release policy for firmware builds, host selection, and downloads."""
DRIVER_FPS=999
ENCODINGS={'rgb':0,'jpeg':3}


def normalize_mode(mode):
    return 'rgb' if mode=='rgb565' else mode


def product_for(mode,quality=8):
    mode=normalize_mode(mode)
    if mode not in ENCODINGS: raise ValueError('Mode must be rgb or jpeg')
    encoding=f'Ergb16_Ejpg{quality}' if mode=='rgb' else f'Ejpg{quality}_Ergb16'
    return f'zynq_R800x480_{encoding}_Fps{DRIVER_FPS}_Bl4096'
