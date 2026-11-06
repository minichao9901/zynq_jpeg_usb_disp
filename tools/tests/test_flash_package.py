"""Prevent a wrong/limited/tampered pair from reaching the download step."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import flash
from mode_config import product_for


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.package=Path(self.temp.name)
        for name in flash.FILES: (self.package/name).write_bytes(name.encode())
        self.manifest={'schema':1,'mode':'rgb','default_encoding':0,'fps_limit':None,
            'driver_fps_token':999,'normal_profile_flags':2,'product':product_for('rgb'),'build_id':'0x12345678',
            'sha256':{name:hashlib.sha256((self.package/name).read_bytes()).hexdigest() for name in flash.FILES}}
        self.save()

    def tearDown(self): self.temp.cleanup()
    def save(self): (self.package/'manifest.json').write_text(json.dumps(self.manifest))

    def test_valid_package(self):
        self.assertEqual(flash.validate_package(self.package,'rgb')['mode'],'rgb')

    def test_mode_mismatch(self):
        with self.assertRaises(ValueError): flash.validate_package(self.package,'jpeg')

    def test_changed_elf(self):
        (self.package/'usb_display.elf').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'SHA-256'): flash.validate_package(self.package,'rgb')

    def test_reject_limited_or_fingerprint_profile(self):
        for key,value in [('fps_limit',30),('driver_fps_token',30),('normal_profile_flags',0)]:
            old=self.manifest[key];self.manifest[key]=value;self.save()
            with self.assertRaises(ValueError): flash.validate_package(self.package,'rgb')
            self.manifest[key]=old

    def test_reject_extra_path(self):
        self.manifest['sha256']['../other.elf']='0'*64;self.save()
        with self.assertRaises(ValueError): flash.validate_package(self.package,'rgb')

    def test_dry_run_never_downloads(self):
        with mock.patch.object(sys,'argv',['flash.py','rgb','--dry-run']),mock.patch.object(flash,'flash') as download,contextlib.redirect_stdout(io.StringIO()):
            flash.main()
        download.assert_not_called()


if __name__=='__main__': unittest.main()
