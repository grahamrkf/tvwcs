"""Old name of tvwcs.system.loginscreen. TVWCS 5.21's installer runs `python3 -m tvwcs.loginscreen` against the
TVWCS it has just installed, which may be this one. Remove once no release older than 5.22.0 is offered."""

import runpy

if __name__ == "__main__":
    runpy.run_module("tvwcs.system.loginscreen", run_name="__main__", alter_sys=True)
