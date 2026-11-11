import os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from tvwcs import selfupdate, vendor
from tvwcs.selfupdate import Release, UpdateError

def release_json(tag="v5.0.0",names=("tvwcs_5.0.0_all.deb",)):
    return {"tag_name":tag,"html_url":"https://example/rel","assets":[{"name":n,"browser_download_url":f"https://example/{n}"} for n in names]}

class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(selfupdate.parse_version("v2.6.0"),(2,6,0)); self.assertEqual(selfupdate.parse_version("2.6.0-beta.3"),(2,6,0))
        with self.assertRaises(UpdateError): selfupdate.parse_version("beta-12")
    def test_newer(self):
        self.assertTrue(selfupdate.is_newer("v2.6.0","2.5.0")); self.assertTrue(selfupdate.is_newer("2.10","2.9.9"))
        self.assertFalse(selfupdate.is_newer("2.5.0","2.5.0")); self.assertFalse(selfupdate.is_newer("2.5","2.5.0")); self.assertFalse(selfupdate.is_newer("2.4.9","2.5.0"))

class ReleaseTests(unittest.TestCase):
    def test_picks_the_packages(self):
        r=selfupdate.release_from_json(release_json(names=("notes.txt","TVWCS-5.0.0.zip","tvwcs_5.0.0_all.deb","tvwcs-boot-logo_5.0.0_all.deb","other_1_all.deb")))
        self.assertEqual((r.version,r.tag),("5.0.0","v5.0.0"))
        self.assertEqual(r.debs,{"tvwcs":"https://example/tvwcs_5.0.0_all.deb"})   # 5.0.x's tvwcs-boot-logo is no longer installed
    def test_prereleases_only_when_asked_and_newer(self):
        listing=[dict(release_json("v5.1.0",("tvwcs_5.1.0_all.deb",)),prerelease=True),dict(release_json("v5.2.0"),draft=True),
                 release_json("v5.0.2",("tvwcs_5.0.2_all.deb",)),release_json("v4.9.0",("TVWCS-4.9.0.zip",)),
                 dict(release_json("v5.9.0",("notes.txt",)),prerelease=True)]
        newest=selfupdate.newest_release(listing)
        self.assertEqual((newest.version,newest.prerelease),("5.1.0",True))   # not the draft, 4.x's zip or the one without a .deb
        self.assertIsNone(selfupdate.newest_release([])); self.assertIsNone(selfupdate.newest_release({"message":"rate limited"}))
        answers={selfupdate.LATEST_URL:release_json("v5.0.2",("tvwcs_5.0.2_all.deb",)),selfupdate.RELEASES_URL:listing}
        with patch.object(selfupdate,"_get_json",answers.get), patch.object(selfupdate,"source",lambda:vendor.Updates("github")):
            self.assertEqual(selfupdate.latest_release().version,"5.0.2")
            self.assertEqual(selfupdate.latest_release(prereleases=True).version,"5.1.0")
            answers[selfupdate.RELEASES_URL]=[dict(release_json("v5.0.1",("tvwcs_5.0.1_all.deb",)),prerelease=True)]
            self.assertEqual(selfupdate.latest_release(prereleases=True).version,"5.0.2")   # an older prerelease is not offered
    def test_a_release_without_the_package_is_an_error(self):
        with self.assertRaises(UpdateError): selfupdate.release_from_json(release_json(names=("TVWCS-4.2.2.zip",)))

class InstallTests(unittest.TestCase):
    def test_packaged_only_from_usr_lib(self):
        self.assertTrue(selfupdate.packaged("/usr/lib/tvwcs/tvwcs")); self.assertFalse(selfupdate.packaged("/home/me/tvwcs/package/tvwcs"))
    def test_installed_packages(self):
        class Done: stdout="tvwcs installed\ntvwcs-boot-logo not-installed\n"
        self.assertEqual(selfupdate.installed_packages(lambda *a,**k:Done()),["tvwcs"])
    def test_download_keeps_only_debs_and_apt_can_read_them(self):
        r=Release("5.1.0","v5.1.0",{"tvwcs":"https://example/a"},"")
        with patch.object(selfupdate,"_download",lambda _u,t:Path(t).write_bytes(b"!<arch>\nrest")):
            folder,files=selfupdate.download(r,["tvwcs"])
        try:
            self.assertEqual([f.name for f in files],["tvwcs_5.1.0_all.deb"])
            self.assertEqual(oct(os.stat(folder).st_mode&0o777),"0o755"); self.assertEqual(oct(os.stat(files[0]).st_mode&0o777),"0o644")
            argv=selfupdate.install_argv(files)
            self.assertEqual(argv[:6],["env","DEBIAN_FRONTEND=noninteractive","apt-get","install","-y","--allow-downgrades"]); self.assertEqual(argv[-1],str(files[0]))
        finally: selfupdate.discard(folder)
        self.assertFalse(folder.exists())
    def test_a_bad_download_leaves_nothing_behind(self):
        made=[]; real=tempfile.mkdtemp
        def mkdtemp(**kw): made.append(real(**kw)); return made[-1]
        r=Release("5.0.0","v5.0.0",{"tvwcs":"x"},"")
        with patch.object(selfupdate,"_download",lambda _u,t:Path(t).write_bytes(b"<html>")), patch.object(selfupdate.tempfile,"mkdtemp",mkdtemp):
            with self.assertRaises(UpdateError): selfupdate.download(r,["tvwcs"])
        self.assertFalse(Path(made[0]).exists())

if __name__=="__main__": unittest.main()
