import io, json, unittest
from tvwcs.system import last_app


def event(change, con_id, app_id="foot", name="foot"):
    return json.dumps({"change": change, "container": {"id": con_id, "app_id": app_id, "name": name}}) + "\n"


def win(i, focused=False):
    return {"con_id": i, "class": "app", "title": "app", "focused": focused}


class LastAppTests(unittest.TestCase):
    def test_parse_event(self):
        self.assertEqual(last_app.parse_event(event("focus", 5)), ("focus", 5))
        self.assertEqual(last_app.parse_event(event("close", 5)), ("close", 5))
        self.assertIsNone(last_app.parse_event(event("title", 5)))
        self.assertIsNone(last_app.parse_event(event("focus", 9, "com.tvwcs.TVWCS", "TVWCS")))  # the Quick Menu
        self.assertIsNone(last_app.parse_event(event("focus", 9, None, "TVWCS · Edit profile")))  # its dialogs
        self.assertIsNone(last_app.parse_event(event("focus", 9, "com.tvwcs.Osd", "")))  # the volume indicator
        self.assertEqual(
            last_app.parse_event(event("focus", 8, "com.tvwcs.ControlPanel", "TVWCS Settings")), ("focus", 8)
        )  # Settings is an app
        self.assertIsNone(last_app.parse_event("not json"))
        self.assertIsNone(last_app.parse_event("[1]"))

    def test_history_puts_the_last_focused_first(self):
        h = last_app.FocusHistory()
        for line in (event("focus", 1), event("focus", 2), event("focus", 3), event("focus", 1), event("close", 2)):
            h.event(last_app.parse_event(line))
        self.assertEqual(h.ids(), [1, 3])
        for i in range(100):
            h.focused(i)
        self.assertEqual(len(h.ids()), last_app.KEEP)

    def test_pick_flips_between_the_last_two(self):
        windows = [win(1), win(2), win(3, focused=True)]
        self.assertEqual(last_app.pick([3, 1, 2], windows, 3)["con_id"], 1)
        self.assertEqual(last_app.pick([1, 3, 2], windows, 1)["con_id"], 3)  # pressed again: back
        self.assertEqual(last_app.pick([4, 3, 1], windows, 3)["con_id"], 1)  # 4 has closed
        self.assertEqual(
            last_app.pick([3, 1], windows, None)["con_id"], 3
        )  # nothing in use (an empty workspace): the last one
        self.assertIsNone(last_app.pick([3], [win(3)], 3))

    def test_windows_from_before_tvwcs_started_come_from_the_tree(self):
        self.assertEqual(last_app.pick([], [win(1), win(2, focused=True)], 2, order=[2, 1])["con_id"], 1)
        self.assertEqual(last_app.pick([2], [win(1), win(2), win(3)], 2, order=[2, 3, 1])["con_id"], 3)

    def test_tree_order_follows_focus_lists(self):
        def leaf(i):
            return {"id": i, "type": "con", "app_id": "a", "nodes": [], "floating_nodes": []}

        tree = {
            "id": 0,
            "type": "root",
            "focus": [10],
            "nodes": [
                {
                    "id": 10,
                    "type": "output",
                    "focus": [21, 20],
                    "nodes": [
                        {
                            "id": 20,
                            "type": "workspace",
                            "focus": [2, 1],
                            "nodes": [leaf(1), leaf(2)],
                            "floating_nodes": [],
                        },
                        {"id": 21, "type": "workspace", "focus": [3], "nodes": [], "floating_nodes": [leaf(3)]},
                        {"id": 22, "type": "workspace", "focus": [], "nodes": [], "floating_nodes": []},
                    ],
                }
            ],
        }
        self.assertEqual(last_app.tree_order(tree), [3, 2, 1])
        self.assertEqual(last_app.tree_order({}), [])

    def test_follower_reads_events_and_restarts(self):
        h = last_app.FocusHistory()
        runs = []

        class Proc:
            def __init__(self, text):
                self.stdout = io.StringIO(text)

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return 0

        f = last_app.FocusFollower(h, which=lambda _n: "/usr/bin/swaymsg")

        def popen(args, **_kw):
            runs.append(args)
            if len(runs) > 1:
                f.stopping.set()
            return Proc(event("focus", 1) + event("focus", 2) if len(runs) == 1 else "")

        f.popen = popen
        f.RETRY = 0
        f._follow()
        self.assertEqual(runs[0], ["/usr/bin/swaymsg", "-t", "subscribe", "-m", '["window"]'])
        self.assertEqual(len(runs), 2)
        self.assertEqual(h.ids(), [2, 1])
        f2 = last_app.FocusFollower(h, which=lambda _n: None)
        f2.start()
        self.assertIsNone(f2.thread)  # no sway: nothing to follow


if __name__ == "__main__":
    unittest.main()
