import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="hotshelf-test-")
for sub in ("fast", "slow"):
    os.makedirs(os.path.join(_tmp, sub))
with open(os.path.join(_tmp, "config.yaml"), "w") as f:
    f.write(f"""branches:
  fast: {_tmp}/fast
  slow: {_tmp}/slow
run:
  dry_run: true
""")
os.environ["HOTSHELF_CONFIG"] = os.path.join(_tmp, "config.yaml")
os.environ["HOTSHELF_STATE"] = os.path.join(_tmp, "state.db")
os.environ.pop("HOTSHELF_JELLYFIN_KEY", None)
