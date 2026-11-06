"""Keep the existing primary display and use the Windows extended topology."""
import ctypes
import time
import win32api
import win32con
from idd_probe import topology


def primary_snapshot():
    for item in topology():
        if item['flags']&4:
            return item['name'],win32api.EnumDisplaySettings(item['name'],-1)
    raise RuntimeError('No primary monitor found')


def extend(primary_name,primary_mode):
    # Restore an extended path set before placing the monitors. The saved
    # primary DEVMODE was captured before enabling this USB display.
    result=ctypes.windll.user32.SetDisplayConfig(0,None,0,None,0x80|0x4)
    if result: raise RuntimeError(f'SetDisplayConfig(EXTEND) failed: {result}')
    deadline=time.monotonic()+5
    usb_name=None
    while time.monotonic()<deadline:
        matches=[x for x in topology() if x['device'].startswith('xfz1986_usb_graphic') and 'mode' in x]
        if len(matches)==1:
            usb_name=matches[0]['name']; break
        time.sleep(.1)
    if usb_name is None: raise RuntimeError('USB display GDI path not found')
    items=topology()
    main=next(x for x in items if x['name']==primary_name)
    if not (main['flags']&5)==5:
        primary_mode.Position_x=0; primary_mode.Position_y=0
        primary_mode.Fields=win32con.DM_POSITION|win32con.DM_PELSWIDTH|win32con.DM_PELSHEIGHT|win32con.DM_BITSPERPEL|win32con.DM_DISPLAYFREQUENCY
        result=win32api.ChangeDisplaySettingsEx(primary_name,primary_mode,win32con.CDS_UPDATEREGISTRY|win32con.CDS_SET_PRIMARY)
        if result: raise RuntimeError(f'Restore primary failed: {result}, {items}')
        items=topology()
        main=next(x for x in items if x['name']==primary_name)
    external=next(x for x in items if x['name']==usb_name)
    if not (main['flags']&5)==5 or not external['flags']&1:
        raise RuntimeError(f'Primary/extended display validation failed: {items}')
    return items
