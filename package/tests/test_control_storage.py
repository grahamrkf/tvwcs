import json, unittest
from tvwcs import control_storage as st

LSBLK = {
    "blockdevices": [
        {
            "name": "loop0",
            "path": "/dev/loop0",
            "type": "loop",
            "size": "100",
            "fstype": "squashfs",
            "mountpoints": ["/snap/x"],
        },
        {
            "name": "nvme0n1",
            "path": "/dev/nvme0n1",
            "type": "disk",
            "size": "256060514304",
            "model": "Samsung SSD ",
            "rm": False,
            "hotplug": False,
            "tran": "nvme",
            "mountpoints": [None],
            "children": [
                {
                    "name": "nvme0n1p1",
                    "path": "/dev/nvme0n1p1",
                    "type": "part",
                    "size": "536870912",
                    "fstype": "vfat",
                    "mountpoints": ["/boot/efi"],
                },
                {
                    "name": "nvme0n1p2",
                    "path": "/dev/nvme0n1p2",
                    "type": "part",
                    "size": "255000000000",
                    "fstype": "ext4",
                    "label": "root",
                    "mountpoints": ["/"],
                    "fsused": "1000",
                    "fsavail": "2000",
                },
            ],
        },
        {
            "name": "sdb",
            "path": "/dev/sdb",
            "type": "disk",
            "size": "32000000000",
            "model": "USB Stick",
            "rm": True,
            "hotplug": True,
            "tran": "usb",
            "mountpoints": [None],
            "children": [
                {
                    "name": "sdb1",
                    "path": "/dev/sdb1",
                    "type": "part",
                    "size": "32000000000",
                    "fstype": "exfat",
                    "label": "MOVIES",
                    "mountpoints": [None],
                }
            ],
        },
        {"name": "sr0", "path": "/dev/sr0", "type": "rom", "size": "0"},
    ]
}


class StorageTests(unittest.TestCase):
    def test_lsblk_drives_and_volumes(self):
        drives = st.parse_lsblk(json.dumps(LSBLK))
        self.assertEqual(
            [d.name for d in drives], ["nvme0n1", "sdb"]
        )  # the system drive first; loop and CD drives left out
        system, usb = drives
        self.assertTrue(system.system)
        self.assertEqual(system.title, "Samsung SSD")
        self.assertEqual([v.name for v in system.volumes], ["nvme0n1p1", "nvme0n1p2"])
        self.assertEqual(system.volumes[1].used, 1000)
        self.assertTrue(usb.removable)
        self.assertFalse(usb.system)
        self.assertEqual(usb.volumes[0].title, "MOVIES")
        self.assertFalse(usb.volumes[0].mounted)

    def test_lsblk_drive_without_partitions(self):
        data = {
            "blockdevices": [
                {
                    "name": "sdc",
                    "path": "/dev/sdc",
                    "type": "disk",
                    "size": "1000",
                    "fstype": "vfat",
                    "label": "CAM",
                    "mountpoints": ["/media/tv/CAM"],
                    "rm": True,
                }
            ]
        }
        d = st.parse_lsblk(json.dumps(data))[0]
        self.assertEqual(len(d.volumes), 1)
        self.assertTrue(d.volumes[0].mounted)

    def test_system_partition_titles(self):
        self.assertEqual(st.Volume("/dev/a2", "a2", mountpoints=["/"]).title, "System (a2)")
        self.assertEqual(st.Volume("/dev/a3", "a3", mountpoints=["/home"]).title, "Home (a3)")
        self.assertEqual(st.Volume("/dev/a3", "a3", label="data", mountpoints=["/home"]).title, "data")
        self.assertEqual(st.Volume("/dev/b1", "b1", mountpoints=["/media/x"]).title, "b1")

    def test_bad_lsblk_output(self):
        self.assertEqual(st.parse_lsblk("not json"), [])

    def test_size_text(self):
        self.assertEqual(st.size_text(1500000000), "1.5 GB")
        self.assertEqual(st.size_text(256060514304), "256 GB")
        self.assertEqual(st.size_text(512), "512 B")


if __name__ == "__main__":
    unittest.main()
