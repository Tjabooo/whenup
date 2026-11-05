"""End-to-end tests: a local bare repo as the queue, two simulated machines."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EXE = Path(__file__).resolve().parent / "whenup"


class Machine:
    def __init__(self, root: Path, name: str, queue: Path, aliases=()):
        self.root, self.name = root / name, name
        self.root.mkdir()
        self.env = {**os.environ, "HOME": str(self.root),
                    "WHENUP_CONFIG": str(self.root / "config.toml"),
                    "WHENUP_DATA": str(self.root / "data"), "WHENUP_STATE": str(self.root / "state"),
                    "GIT_CONFIG_GLOBAL": "/dev/null"}
        args = ["init", str(queue), "--name", name] + [x for a in aliases for x in ("--alias", a)]
        self.run(*args)
        cfg = self.root / "config.toml"
        cfg.write_text(cfg.read_text().replace("notify = true", "notify = false"))

    def run(self, *args, check=True, stdin=None):
        p = subprocess.run([sys.executable, str(EXE), *args], env=self.env, capture_output=True, text=True,
                           input=stdin)
        if check and p.returncode:
            raise AssertionError(f"whenup {' '.join(args)} failed:\n{p.stdout}\n{p.stderr}")
        return p

    def queue(self) -> Path:
        return self.root / "data/queue"


class WhenupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bare = root / "queue.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.bare)], check=True)
        self.desk = Machine(root, "desk", self.bare)
        self.laptop = Machine(root, "laptop", self.bare, aliases=["unit"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_job_runs_on_target_and_result_comes_back(self):
        self.desk.run("add", "laptop", "-t", "hello", "--", "sh", "-c", "echo hi from $WHENUP_TARGET > out.txt; cat out.txt")
        self.assertIn("hello", self.desk.run("list").stdout)
        self.assertIn("nothing waiting", self.desk.run("list", "desk").stdout)

        self.desk.run("run")  # not for desk: nothing happens
        self.assertFalse((self.desk.root / "out.txt").exists())

        out = self.laptop.run("run").stdout
        self.assertIn("ok (exit 0", out)
        self.assertEqual((self.laptop.root / "out.txt").read_text(), "hi from laptop\n")

        listing = self.desk.run("list").stdout
        self.assertIn("nothing waiting", listing)
        self.assertIn("✓", listing)
        job_id = listing.split("✓ ")[1].split()[0]
        self.assertIn("hi from laptop", self.desk.run("show", job_id).stdout)

        self.laptop.run("run")  # never runs twice
        self.assertEqual(len(list((self.laptop.queue() / "done/laptop").glob("*.json"))), 1)

    def test_alias_failure_retry_and_order(self):
        self.desk.run("add", "unit", "-t", "first", "--", "echo 1 >> log")
        self.desk.run("add", "unit", "-t", "broken", "--", "exit 3")
        self.desk.run("add", "laptop", "-t", "third", "--", "echo 3 >> log")
        out = self.laptop.run("run").stdout
        self.assertIn("failed (exit 3", out)
        self.assertEqual((self.laptop.root / "log").read_text(), "1\n3\n")

        broken = next(j for f in (self.laptop.queue() / "done").glob("*/*.json")
                      if (j := json.loads(f.read_text()))["title"] == "broken")
        self.desk.run("retry", broken["id"])
        self.assertIn("broken", self.desk.run("list", "unit").stdout)
        self.laptop.run("run")
        f = next((self.laptop.queue() / "done/unit").glob(f"{broken['id']}.json"))
        self.assertEqual(len(json.loads(f.read_text())["history"]), 1)

    def test_cancel_and_stdin_script(self):
        self.desk.run("add", "laptop", "-t", "from stdin", stdin="touch made-by-stdin\n")
        self.desk.run("add", "laptop", "-t", "nope", "--", "touch should-not-exist")
        nope = next(j for f in (self.desk.queue() / "pending/laptop").glob("*.json")
                    if (j := json.loads(f.read_text()))["title"] == "nope")
        self.desk.run("cancel", nope["id"])
        self.laptop.run("run")
        self.assertTrue((self.laptop.root / "made-by-stdin").exists())
        self.assertFalse((self.laptop.root / "should-not-exist").exists())

    def test_offline_queue_keeps_results_until_push(self):
        self.desk.run("add", "laptop", "--", "true")
        self.laptop.run("run", "-n")  # dry run touches nothing
        self.assertEqual(len(list((self.laptop.queue() / "pending/laptop").glob("*.json"))), 1)
        moved = self.bare.with_name("gone.git")
        self.laptop.run("list")  # pull while online
        self.bare.rename(moved)  # the queue host goes away
        p = self.laptop.run("run")
        self.assertIn("ok", p.stdout)
        self.bare = moved.rename(self.bare)
        self.laptop.run("run")  # back online: the stored result goes out
        self.assertIn("✓", self.desk.run("list").stdout)


if __name__ == "__main__":
    unittest.main()
