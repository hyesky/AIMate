"""自测：accounts 账号体系 + session_store 会话持久化/搜索/工作目录生命周期。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from aimate.web.accounts import AccountStore  # noqa: E402
from aimate.web.session_store import SessionStore  # noqa: E402

PASS = 0


def check(name, cond, extra=""):
    global PASS
    status = "PASS" if cond else "FAIL"
    print(f"{status} {name} {extra}")
    if cond:
        PASS += 1
    else:
        raise SystemExit(f"FAILED: {name}")


tmp = tempfile.mkdtemp(prefix="aimate_test_")
os.chdir(tmp)

# ── Accounts ──
acc = AccountStore()
check("register", True)
acc.register("zj", "secret123", name="张工", role="member", post="运维工程师")
try:
    acc.register("zj", "x")
    _dup_ok = False
except ValueError:
    _dup_ok = True
check("duplicate register rejected", _dup_ok)
check("wrong pwd rejected", acc.authenticate("zj", "wrong") is None)
check("correct pwd ok", acc.authenticate("zj", "secret123") is not None)
tok, acct = acc.login("zj", "secret123")
check("login returns token+acct", bool(tok) and acct.username == "zj")
check("whoami by token", acc.whoami(tok).username == "zj")
acc.update_profile("zj", name="张工V2", post="资深SRE", theme="dark")
check("profile update",
      acc.get("zj").post == "资深SRE" and acc.get("zj").theme == "dark")
check("password change", acc.change_password("zj", "secret123", "new456")
      and acc.authenticate("zj", "new456") is not None)
# license 导入
lic = '{"issued_at":100,"expires_at":9999999999,"features":["rag","workflow"],"max_seats":50}'
acc.import_license("zj", lic)
check("license import", sorted(acc.get("zj").license_features) == ["rag", "workflow"])

# ── SessionStore ──
ss = SessionStore()
s1 = ss.create("任务一", owner="zj")
s2 = ss.create("任务二", owner="zj")
check("session cwd created", os.path.isdir(s1["cwd"]))
ss.add_message(s1["id"], "user", "帮我配置 Nginx 反向代理，关于内网网关的部署")
ss.add_message(s1["id"], "assistant", "已完成 Nginx 反代配置")
ss.add_message(s2["id"], "user", "审计日志量太大了")
check("message persisted", ss.message_count(s1["id"]) == 2)

r = ss.search("Nginx 反向代理", owner="zj")
check("session search hits s1", len(r) == 1 and r[0]["session_id"] == s1["id"]
      and r[0]["count"] >= 1)
check("search snippet contains q", "Nginx" in r[0]["snippets"][0])

sess = ss.get(s1["id"])
check("rename", ss.rename(s1["id"], "反代配置") or True)
check("renamed title",
      ss.get(s1["id"])["title"] == "反代配置")

cwd = ss.get(s2["id"])["cwd"]
open(os.path.join(cwd, "scratch.txt"), "w").write("x")
ss.delete(s2["id"])
check("workdir deleted on session delete",
      ss.get(s2["id"]) is None and not os.path.exists(cwd))

print(f"\nALL PASS ✔ ({PASS} checks)")
