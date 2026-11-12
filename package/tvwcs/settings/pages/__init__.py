"""The Settings app's pages, one file per page (GTK). PAGES is their order in the tab list."""

from tvwcs.settings.pages.appearance import AppearancePage
from tvwcs.settings.pages.bluetooth import BluetoothPage
from tvwcs.settings.pages.date_time import DateTimePage
from tvwcs.settings.pages.displays import DisplaysPage
from tvwcs.settings.pages.hotkeys import HotkeysPage
from tvwcs.settings.pages.network import NetworkPage
from tvwcs.settings.pages.power import PowerPage
from tvwcs.settings.pages.sound import SoundPage
from tvwcs.settings.pages.storage import StoragePage
from tvwcs.settings.pages.system_info import SystemPage
from tvwcs.settings.pages.updates import UpdatesPage
from tvwcs.settings.pages.user import UserPage

PAGES = (
    AppearancePage,
    UserPage,
    HotkeysPage,
    SoundPage,
    DisplaysPage,
    PowerPage,
    BluetoothPage,
    DateTimePage,
    UpdatesPage,
    SystemPage,
    NetworkPage,
    StoragePage,
)
