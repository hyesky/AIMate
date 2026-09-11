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

# 10. 记忆门控（借鉴 is_trivial_prompt 思想）
from aimate.memory.gate import is_trivial_prompt
check("gate.trivial", is_trivial_prompt("ok") and is_trivial_prompt("好的。")
      and is_trivial_prompt("继续") and is_trivial_prompt("") and is_trivial_prompt("/learn x"))
check("gate.semantic", not is_trivial_prompt("帮我查一下内网网关配置")
      and not is_trivial_prompt("根据 RAG 召回生成总结"))

# 11. 异步记忆 prefetch/ingest（Provider 模式 + 后台不阻塞）
class _FakeProvider:
    def __init__(self): self.prefetched=[]; self.ingested=[]
    def initialize(self): pass
    def prefetch(self, t, o, text): self.prefetched.append(text)
    def ingest(self, t, o, u, a): self.ingested.append(u)
fp = _FakeProvider(); mam = m; mam.providers=[]; mam.add_provider(fp)
mam.prefetch("t","a","一条正经的查询需求")
mam.prefetch("t","a","ok")          # 门控：不触发
mam.ingest("t","a","正经用户话","正经助手话")
mam.shutdown(wait=True)
check("mem.provider.prefetch", "一条正经的查询需求" in fp.prefetched and "ok" not in fp.prefetched)
check("mem.provider.ingest", "正经用户话" in fp.ingested)

# 12. /learn 自进化：description 校验
from aimate.skills.learn import validate_description, build_learn_prompt
check("learn.desc_ok", validate_description("处理工单。")[0])
check("learn.desc_long", not validate_description(
    "这是一个非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常长的描述句子，远超六十个字符上限就会被截断并且永不路由导致技能无法被触发。")[0])
pr = build_learn_prompt("某个目录的源码", "本次会话刚做完工单流程")
check("learn.prompt", "何时使用" in pr and "AIMate" in pr)

# 13. 技能渐进披露（索引用到再加载）
st = build_system().skills
st.create(__import__("aimate.skills.store", fromlist=["Skill","SkillStatus"]).Skill(
    name="kb", tenant_id="t", description="知识库检索。", trigger="查知识库时",
    body="# 知识库\n全量正文……", status=__import__("aimate.skills.store", fromlist=["SkillStatus"]).SkillStatus.PUBLISHED, owner="agent"))
idx = st.index_of("t")
check("skill.index_light", idx and idx[0]["name"]=="kb" and "body" not in idx[0])
check("skill.load_full", st.load("t","kb").startswith("# 知识库"))
st.use("t","kb")  # 刷新活动度

# 14. Curator：惰性触发 + pinned 保护 + 只归档不硬删 + stale/archive 分级
from aimate.skills.store import Curator, Skill, SkillStatus
from datetime import datetime, timezone, timedelta
cur = Curator(st, stale_days=30, archive_days=90)
check("curator.lazy_idle", cur.maybe_run(idle=False) is False)   # 忙不跑
check("curator.lazy_first", cur.maybe_run(idle=True) is True)    # 首次空闲跑
check("curator.lazy_throttle", cur.maybe_run(idle=True) is False) # 刚跑过,节流
# 造一个 120 天未用的 agent-created、pinned、人工技能
old = Skill(name="legacy", tenant_id="t", description="旧技能。", body="b",
            status=SkillStatus.PUBLISHED, owner="agent", pinned=False,
            last_used_at=(datetime.now(timezone.utc)-timedelta(days=120)).isoformat())
pinned = Skill(name="keep", tenant_id="t", description="钉住技能。", body="b",
               status=SkillStatus.PUBLISHED, owner="agent", pinned=True,
               last_used_at=(datetime.now(timezone.utc)-timedelta(days=120)).isoformat())
manual = Skill(name="manual", tenant_id="t", description="人工技能。", body="b",
               status=SkillStatus.PUBLISHED, owner="human",
               last_used_at=(datetime.now(timezone.utc)-timedelta(days=120)).isoformat())
for s in (old, pinned, manual): st.create(s)
# 先标 stale（mark_stale 只看 PUBLISHED），再归档（archive 把 legacy 转 ARCHIVED）
stale = cur.mark_stale("t", used_names=set())
check("curator.stale", "legacy" in stale and "keep" not in stale)
arch = cur.archive_unused("t", used_names={"kb"})
check("curator.archive_agent", "legacy" in arch and "kb" not in arch)
check("curator.pinned_safe", "keep" not in arch and st.get("t","keep").status==SkillStatus.PUBLISHED)
check("curator.manual_safe", "manual" not in arch and st.get("t","manual").status==SkillStatus.PUBLISHED)
check("curator.no_harddel", st.get("t","legacy").status==SkillStatus.ARCHIVED)  # 只归档

# 15. 工具 schema 归一化（防严格 provider 拒收；坏 schema 丢弃不拖垮 toolset）
from aimate.gateway.api.api import GatewayAPI
api = GatewayAPI(build_system().auth)
check("tool.norm_unwrapped", api.normalize_tool_schema({"name":"a","parameters":{}})=={"name":"a","parameters":{}})
check("tool.norm_wrapped", api.normalize_tool_schema({"type":"function","function":{"name":"b"}})["name"]=="b")
check("tool.norm_bad", api.normalize_tool_schema({"description":"无名"}) is None)
api.register_tool({"type":"function","function":{"name":"f1","description":"工具一","parameters":{}}})
api.register_tool({"no_name": True})                    # 坏 schema：应被拒
check("tool.register_rejects", api.register_tool({"no_name":True}) is False)
schemas = api.tool_schemas()
check("tool.toolset_clean", len(schemas)==1 and schemas[0]["function"]["name"]=="f1")
check("tool.toolset_wrapped", schemas[0]["type"]=="function")

print("\n" + ("ALL PASS ✔" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
