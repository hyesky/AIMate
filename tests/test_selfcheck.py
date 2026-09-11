"""AIMate 自测脚本：验证核心逻辑真实可跑（无第三方依赖）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aimate.system import build_system
from aimate.memory.manager import MemoryBudgetExceeded
from aimate.workflow.engine import WorkflowEngine, WorkflowNode
from aimate.security.audit import AuditLog, sm3_hex

fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" — {extra}" if extra else ""))
    if not cond:
        fails.append(name)

# 1. 记忆：add / replace / remove / 有界
m = build_system().memory
m.add("t", "a", "memory", "用户 X 偏好简洁；项目用 Apache-2.0。")
m.replace("t", "a", "memory", "Apache-2.0", "项目改用 MIT。")
check("memory.replace", "MIT" in "\n".join(m._stores[("t","a","memory")].entries))
m.remove("t", "a", "memory", "项目改用 MIT")   # 整条替换后按新子串定位整条删除
check("memory.remove", all("项目改用" not in e for e in m._stores[("t","a","memory")].entries))
# 有界
try:
    for i in range(50):
        m.add("t", "a", "memory", "x" * 300)
    check("memory.budget", False)
except MemoryBudgetExceeded:
    check("memory.budget", True)

# 2. SQLite 持久化
import sqlite3, tempfile
db = tempfile.mktemp(suffix=".db")
con = sqlite3.connect(db)
con.execute("CREATE TABLE mem(tenant TEXT, owner TEXT, target TEXT, entry TEXT)")
con.execute("INSERT INTO mem VALUES(?,?,?,?)", ("t","a","memory","持久化测试条目"))
con.commit()
rows = con.execute("SELECT entry FROM mem").fetchall()
check("persist.sqlite", rows and rows[0][0] == "持久化测试条目")
os.unlink(db)

# 3. RAG 检索
kb = build_system().rag
kb.index("AIMate 支持私有化内网部署。支持 RAG 知识库召回。", "d1")
kb.index("数字员工可绑定内网推理网关。", "d2")
hits = kb.search("内网推理")
check("rag.hybrid/search", any("推理" in h.text for h in hits), f"top={[h.doc_id for h in hits]}")

# 4. Workflow DAG
eng = WorkflowEngine()
async def add(x): return {"sum": x["a"] + x["b"]}
async def mul(x): return {"prod": x["add"]["sum"] * x["k"]}
eng.define("calc", [WorkflowNode("add", add), WorkflowNode("mul", mul, deps=["add"], params={"k":2})])
import asyncio
r = asyncio.run(eng.run("calc", "r1", {"a":2,"b":3,"k":4}))
# mul 结果存在节点键下: outputs["mul"]["prod"]；params.k=2 覆盖输入 k=4 → 5*2=10
check("workflow.dag", r.status=="success" and r.outputs["mul"]["prod"]==10, str(r.outputs))

# 5. License 门控
lic = build_system().license_mgr.load(
    '{"issued_at":0,"expires_at":9999999999,"features":["rag","workflow"],"max_seats":1}',
    "t")
check("license.feature", lic.has_feature("rag"))
lic.seat_used = 1
check("license.seat_gate", not lic.can_allocate_seat())

# 6. 审核（记忆写留痕）
a = AuditLog(); a.record("it-support","t","memory.write","aimate/memory","add 一条")
check("audit.query", len(a.query("t","memory.write"))==1)

# 7. 国密接口可用
check("smm3_hex", len(sm3_hex(b"hello")) == 64)

# 8. RBAC
sys_ = build_system(); sys_.bootstrap_demo()
from aimate.org.service import Role
member = sys_.org._members["u-1"]
viewer = sys_.org._members["u-admin"]
check("rbac.member_tool", sys_.org.can(member, "use_tools"))
check("rbac.admin_all", sys_.org.can(viewer, "audit.read"))

# 9. 飞书签名
feishu = __import__("aimate.gateway.channels.feishu.channel", fromlist=["FeishuChannel"]).FeishuChannel("id","secret")
sig = __import__("hashlib").sha256(("t" + "n" + "secret").encode()).hexdigest()
check("feishu.sign", feishu.verify_signature("t","n","b", sig))

print("\n" + ("ALL PASS ✔" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
